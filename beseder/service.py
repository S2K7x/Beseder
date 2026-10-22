"""Application logic: AI config, triage, periodic sync."""

import asyncio
import logging

from .ai.providers import AIConfig, AIError, Provider, make_provider, presets_for
from .ai.tasks import CATEGORIES, triage
from .config import Config
from .crypto import Vault
from .db import DB, now_iso
from .mail.imap import MailService
from .mail.oauth_ms import MicrosoftOAuth

log = logging.getLogger(__name__)

TRIAGE_BACKLOG = 200
# Read marks are sent to the server in one batch per account, this many seconds after the first.
SEEN_FLUSH_DELAY = 3


class Beseder:
    def __init__(self, config: Config, oauth: MicrosoftOAuth | None = None):
        self.config = config
        self.db = DB(config.db_path)
        self.vault = Vault(config.key_path)
        self.mail = MailService(self.db, self.vault, config, oauth)
        self.sync_lock = asyncio.Lock()
        self.status = {"syncing": False, "triage_error": None}
        self._seen_flush: set[int] = set()
        self._provider: Provider | None = None
        self._provider_key = None

    # --- IA -------------------------------------------------------------
    def ai_config(self) -> AIConfig:
        stored = self.db.get_setting("ai", {}) or {}
        key_enc = self.db.get_setting("ai_key")
        api_key = self.vault.decrypt(key_enc.encode())["key"] if key_enc else ""
        return AIConfig(api_key=api_key, **{k: v for k, v in stored.items() if k in AIConfig.__dataclass_fields__})

    def save_ai_config(self, data: dict) -> None:
        presets = presets_for(self.config.in_docker)
        preset = data.get("preset", "")
        if preset not in presets:
            raise ValueError("Unknown provider")
        cfg = {
            "preset": preset,
            "kind": presets[preset]["kind"],
            "base_url": (data.get("base_url") or presets[preset]["base_url"]).strip(),
            "model": (data.get("model") or "").strip(),
            "model_fast": (data.get("model_fast") or "").strip(),
            "command": (data.get("command") or "claude").strip(),
        }
        self.db.set_setting("ai", cfg)
        if data.get("api_key"):
            self.db.set_setting("ai_key", self.vault.encrypt({"key": data["api_key"].strip()}).decode())
        elif data.get("clear_key"):
            self.db.set_setting("ai_key", None)
        self._provider = None

    def provider(self) -> Provider:
        cfg = self.ai_config()
        if not cfg.configured:
            raise AIError("Set up an AI provider in Settings")
        key = repr(cfg) + cfg.api_key
        if self._provider is None or self._provider_key != key:
            self._provider = make_provider(cfg)
            self._provider_key = key
        return self._provider

    @property
    def onboarded(self) -> bool:
        return bool(self.db.get_setting("onboarded", False))

    @property
    def auto_triage(self) -> bool:
        return bool(self.db.get_setting("auto_triage", False))

    # --- triage ---------------------------------------------------------
    def apply_sender_rules(self) -> int:
        with self.db.conn() as c:
            cur = c.execute(
                "UPDATE messages SET category=(SELECT category FROM sender_rules r WHERE r.addr=messages.from_addr),"
                " category_source='rule' WHERE category IS NULL"
                " AND from_addr IN (SELECT addr FROM sender_rules)"
            )
            return cur.rowcount

    async def run_triage(self) -> int:
        self.apply_sender_rules()
        if not self.auto_triage:
            return 0
        with self.db.conn() as c:
            rows = [
                dict(r)
                for r in c.execute(
                    "SELECT id, from_name, from_addr, subject, list_unsubscribe, snippet, body_text"
                    " FROM messages WHERE category IS NULL ORDER BY date DESC LIMIT ?",
                    (TRIAGE_BACKLOG,),
                )
            ]
        if not rows:
            return 0
        saved = 0

        def save(batch: dict[int, str]) -> None:
            nonlocal saved
            with self.db.conn() as c:
                c.executemany(
                    "UPDATE messages SET category=?, category_source='ai' WHERE id=? AND category IS NULL",
                    [(cat, mid) for mid, cat in batch.items()],
                )
            saved += len(batch)

        try:
            await triage(self.provider(), rows, on_batch=save)
            self.status["triage_error"] = None
        except AIError as e:
            self.status["triage_error"] = str(e)
        self.db.audit("ai_triage", f"{saved}/{len(rows)} classified")
        return saved

    def set_category(self, message_id: int, category: str, remember_sender: bool) -> None:
        if category not in CATEGORIES:
            raise ValueError("Unknown category")
        with self.db.conn() as c:
            m = c.execute("SELECT from_addr FROM messages WHERE id=?", (message_id,)).fetchone()
            if m is None:
                raise LookupError("Message not found")
            c.execute("UPDATE messages SET category=?, category_source='user' WHERE id=?", (category, message_id))
            if remember_sender and m["from_addr"]:
                c.execute(
                    "INSERT INTO sender_rules(addr, category, created_at) VALUES(?,?,?)"
                    " ON CONFLICT(addr) DO UPDATE SET category=excluded.category",
                    (m["from_addr"], category, now_iso()),
                )
                # Apply right away to this sender's other messages (except manual choices).
                c.execute(
                    "UPDATE messages SET category=?, category_source='rule'"
                    " WHERE from_addr=? AND (category_source IS NULL OR category_source!='user')",
                    (category, m["from_addr"]),
                )

    async def mark_read(self, message_id: int) -> None:
        account_id = self.mail.queue_seen(message_id)
        if account_id is None or account_id in self._seen_flush:
            return  # a flush for this account is already scheduled and will include it
        self._seen_flush.add(account_id)
        try:
            await asyncio.sleep(SEEN_FLUSH_DELAY)
        finally:
            self._seen_flush.discard(account_id)
        await asyncio.to_thread(self.mail.flush_seen, account_id)

    # --- sync -----------------------------------------------------------
    async def sync_all(self) -> int:
        if self.sync_lock.locked():
            return 0
        async with self.sync_lock:
            self.status["syncing"] = True
            try:
                with self.db.conn() as c:
                    ids = [r["id"] for r in c.execute("SELECT id FROM accounts")]
                new = 0
                for account_id in ids:
                    new += await asyncio.to_thread(self.mail.sync_account, account_id)
                await self.run_triage()
                return new
            finally:
                self.status["syncing"] = False

    async def scheduler(self) -> None:
        while True:
            try:
                await self.sync_all()
            except Exception:
                log.exception("Error during sync")
            await asyncio.sleep(self.config.sync_interval)
