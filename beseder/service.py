"""Application logic: AI config, triage, follow-ups, briefs, periodic sync."""

import asyncio
import logging
import re
import sqlite3
import threading
import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .ai import tasks
from .ai.providers import AIConfig, AIError, Provider, make_provider, presets_for
from .ai.tasks import CATEGORIES, triage
from .config import Config
from .crypto import Vault
from .db import DB, now_iso
from .mail.imap import MailService
from .mail.oauth_ms import MicrosoftOAuth
from .push import MODES as PUSH_MODES
from .push import PushService

log = logging.getLogger(__name__)

TRIAGE_BACKLOG = 200
RESORT_DAYS = 14
# Follow-ups: "To reply" looks at the last 14 days; "Waiting" at what you sent 2 to 30 days ago.
TO_REPLY_DAYS = 14
WAITING_MIN_DAYS = 2
WAITING_MAX_DAYS = 30
NO_REPLY = re.compile(r"(^|[._+-])(no-?reply|do-?not-?reply|ne-?pas-?repondre|notifications?|mailer-daemon|bounce)", re.I)
FOLLOWUPS_TTL = 60  # seconds; also refreshed after each sync, triage or "Done"
# The morning brief is skipped if Beseder was off for more than this after the chosen time.
BRIEF_GRACE = timedelta(hours=3)
# Read marks are sent to the server in one batch per account, this many seconds after the first.
SEEN_FLUSH_DELAY = 3


class Beseder:
    def __init__(self, config: Config, oauth: MicrosoftOAuth | None = None):
        self.config = config
        self.db = DB(config.db_path)
        self.vault = Vault(config.key_path)
        self.mail = MailService(self.db, self.vault, config, oauth)
        self.sync_lock = asyncio.Lock()
        # "version" goes up whenever the mail list changes, so open pages know to refresh.
        self.status = {"syncing": False, "triage_error": None, "version": 0}
        self._seen_flush: set[int] = set()
        self.push = PushService(self.db, self.vault)
        self._watchers: dict[int, threading.Event] = {}
        self._sync_soon: set[int] = set()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._changed = asyncio.Event()
        self._followups: tuple[float, dict] | None = None
        self._provider: Provider | None = None
        self._provider_key = None

    # --- AI -------------------------------------------------------------
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

    def triage_rules(self) -> list[str]:
        return tasks.clean_rules(self.db.get_setting("triage_rules", "") or "")

    async def run_triage(self, resort: bool = False) -> int:
        """Sorts new mail. resort=True sorts the last 14 days again (after the rules changed),
        except what the user or a sender rule filed."""
        self.apply_sender_rules()
        if not self.auto_triage and not resort:
            return 0
        if resort:
            since = (datetime.now(timezone.utc) - timedelta(days=RESORT_DAYS)).isoformat(timespec="seconds")
            which, args = "(category IS NULL OR category_source='ai') AND date>=?", (since,)
        else:
            which, args = "category IS NULL", ()
        with self.db.conn() as c:
            rows = [
                dict(r)
                for r in c.execute(
                    "SELECT id, from_name, from_addr, subject, list_unsubscribe, snippet, body_text"
                    f" FROM messages WHERE {which} ORDER BY date DESC LIMIT ?",
                    (*args, TRIAGE_BACKLOG),
                )
            ]
        if not rows:
            return 0
        saved = 0

        def save(batch: dict[int, tuple[str, bool | None]]) -> None:
            nonlocal saved
            with self.db.conn() as c:
                c.executemany(
                    "UPDATE messages SET category=?, category_source='ai', needs_reply=COALESCE(?, needs_reply)"
                    " WHERE id=? AND (category IS NULL OR category_source='ai')",
                    [(cat, None if reply is None else int(reply), mid) for mid, (cat, reply) in batch.items()],
                )
            saved += len(batch)
            self._followups = None

        try:
            await triage(self.provider(), rows, on_batch=save, rules=self.triage_rules())
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

    # --- follow-ups -------------------------------------------------------
    def followups(self) -> dict:
        cached = self._followups
        if cached and time.monotonic() - cached[0] < FOLLOWUPS_TTL:
            return cached[1]
        result = self._compute_followups()
        self._followups = (time.monotonic(), result)
        return result

    def _compute_followups(self, limit: int = 50) -> dict:
        """To reply: mail the AI flagged as expecting an answer, not answered yet.
        Waiting: what you sent that asks something, with no answer after 2 days."""
        now = datetime.now(timezone.utc)
        iso = lambda d: (now - timedelta(days=d)).isoformat(timespec="seconds")  # noqa: E731
        with self.db.conn() as c:
            to_reply = [dict(r) for r in c.execute(
                "SELECT m.id, m.account_id, a.name AS account_name, m.subject, m.from_name, m.from_addr, m.date,"
                " m.snippet, m.seen, m.category FROM messages m JOIN accounts a ON a.id=m.account_id"
                " WHERE m.needs_reply=1 AND m.answered=0 AND m.followup_done=0 AND m.date>=? AND m.snoozed_until IS NULL"
                " AND (m.category IS NULL OR m.category IN ('important', 'other'))"
                " AND NOT (COALESCE(m.message_id, '')!='' AND (EXISTS (SELECT 1 FROM sent_messages s"
                "   WHERE s.in_reply_to=m.message_id) OR EXISTS (SELECT 1 FROM sent_messages s"
                "   WHERE s.date>=m.date AND instr(s.refs, m.message_id)>0)))"
                " ORDER BY m.date DESC LIMIT ?", (iso(TO_REPLY_DAYS), limit))]
            sent = [dict(r) for r in c.execute(
                "SELECT s.id, s.account_id, a.name AS account_name, a.email AS account_email, s.message_id,"
                " s.to_addr, s.to_name, s.subject, s.date, s.done, substr(s.body_text, 1, 200) AS snippet"
                " FROM sent_messages s JOIN accounts a ON a.id=s.account_id"
                " WHERE s.expects_reply=1 AND s.date<=? AND s.date>=? AND s.to_addr!=''"
                " ORDER BY s.date DESC", (iso(WAITING_MIN_DAYS), iso(WAITING_MAX_DAYS)))]
            waiting, seen_threads = [], set()
            for s in sent:
                local = s["to_addr"].split("@")[0]
                thread = (s["to_addr"], re.sub(r"^\s*((re|fwd?|tr)\s*:\s*)+", "", s["subject"], flags=re.I).lower())
                if NO_REPLY.search(local) or s["to_addr"] == s["account_email"].lower() or thread in seen_threads:
                    continue
                seen_threads.add(thread)  # only the latest message of a conversation counts
                if s["done"]:
                    continue
                answered = c.execute(
                    "SELECT 1 FROM messages WHERE from_addr=? AND date>? LIMIT 1", (s["to_addr"], s["date"])
                ).fetchone() or (s["message_id"] and c.execute(
                    "SELECT 1 FROM thread_index WHERE in_reply_to=? OR (date>? AND instr(refs, ?)>0) LIMIT 1",
                    (s["message_id"], s["date"], s["message_id"])).fetchone())
                if not answered:
                    waiting.append({k: v for k, v in s.items() if k not in ("account_email", "message_id", "done")})
                if len(waiting) >= limit:
                    break
        return {"to_reply": to_reply, "waiting": waiting}

    def followup_done(self, kind: str, item_id: int) -> None:
        table = {"reply": ("messages", "followup_done"), "waiting": ("sent_messages", "done")}.get(kind)
        if table is None:
            raise ValueError("Unknown follow-up")
        with self.db.conn() as c:
            if c.execute(f"UPDATE {table[0]} SET {table[1]}=1 WHERE id=?", (item_id,)).rowcount == 0:
                raise LookupError("Not found")
        self._followups = None

    # --- writing style ----------------------------------------------------
    @property
    def learn_style(self) -> bool:
        return bool(self.db.get_setting("learn_style", True))

    def style_examples(self, to_addr: str) -> list[str]:
        """A few emails the user sent, to this person first: the AI copies the tone, not the content."""
        if not self.learn_style:
            return []
        n = tasks.STYLE_EXAMPLES
        with self.db.conn() as c:
            rows = [r[0] for r in c.execute(
                "SELECT body_text FROM sent_messages WHERE to_addr=? AND length(body_text)>=20"
                " ORDER BY date DESC LIMIT ?", (to_addr.lower(), n))]
            if len(rows) < n:
                rows += [r[0] for r in c.execute(
                    "SELECT body_text FROM sent_messages WHERE to_addr!=? AND length(body_text)>=20"
                    " ORDER BY date DESC LIMIT ?", (to_addr.lower(), n - len(rows)))]
        return [r[: tasks.STYLE_EXAMPLE_LEN] for r in rows]

    # --- briefs -----------------------------------------------------------
    async def make_summary(self, account_id: int | None = None) -> dict:
        sql = "SELECT * FROM messages WHERE seen=0 AND snoozed_until IS NULL"
        args: list = []
        if account_id:
            sql += " AND account_id=?"
            args.append(account_id)
        sql += " ORDER BY date DESC LIMIT ?"
        args.append(tasks.SUMMARY_LIMIT)
        with self.db.conn() as c:
            rows = [dict(r) for r in c.execute(sql, args)]
        language = self.db.get_setting("summary_language", "English") or "English"
        result = await tasks.summarize(self.provider() if rows else None, rows, language)
        meta = {r["id"]: r for r in rows}
        for it in result["items"]:
            r = meta[it["id"]]
            it.update(subject=r["subject"], from_name=r["from_name"] or r["from_addr"], date=r["date"],
                      from_addr=r["from_addr"])
        self.db.audit("ai_summary", f"{len(rows)} messages")
        result["count"] = len(rows)
        result["generated_at"] = now_iso()
        self.db.set_setting("last_summary", result)
        return result

    def brief_settings(self) -> dict:
        return {"time": self.db.get_setting("brief_time", ""), "tz": self.db.get_setting("brief_tz", "UTC")}

    def set_brief_settings(self, time: str, tz: str) -> None:
        if time and not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", time):
            raise ValueError("Pick a time like 07:30")
        try:
            zone = ZoneInfo(tz or "UTC")
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError("Unknown time zone")
        self.db.set_setting("brief_time", time)
        self.db.set_setting("brief_tz", tz or "UTC")
        if time:  # already past today's time: start tomorrow rather than right now
            local = datetime.now(zone)
            if local.strftime("%H:%M") >= time:
                self.db.set_setting("brief_last_day", local.date().isoformat())

    async def morning_brief(self, now: datetime | None = None) -> bool:
        """Runs the brief once a day at the chosen time and sends it as a notification."""
        cfg = self.brief_settings()
        if not cfg["time"]:
            return False
        try:
            zone = ZoneInfo(cfg["tz"])
        except (ZoneInfoNotFoundError, ValueError):
            zone = timezone.utc
        local = (now or datetime.now(timezone.utc)).astimezone(zone)
        hh, mm = (int(x) for x in cfg["time"].split(":"))
        due = local.replace(hour=hh, minute=mm, second=0, microsecond=0)
        today = local.date().isoformat()
        if local < due or self.db.get_setting("brief_last_day") == today:
            return False
        self.db.set_setting("brief_last_day", today)
        if local - due > BRIEF_GRACE or not self.ai_config().configured:
            return False
        with self.db.conn() as c:
            if not c.execute("SELECT 1 FROM messages WHERE seen=0 LIMIT 1").fetchone():
                return False
        result = await self.make_summary()
        if self.push.count():
            preview = self.db.get_setting("push_preview", True)
            n = result["count"]
            await self.push.send({
                "title": "Your morning brief",
                "body": result["overview"][:180] if preview else f"{n} unread email{'s' if n != 1 else ''} summarized",
                "url": "/#/brief", "tag": "brief",
            })
        return True

    async def minute_loop(self) -> None:
        """Snoozed mail coming back, and the morning brief."""
        while True:
            try:
                await self.wake_snoozed()
            except Exception:
                log.exception("Could not bring snoozed mail back")
            try:
                await self.morning_brief()
            except AIError as e:
                log.warning("Morning brief failed: %s", e)
            except Exception:
                log.exception("Morning brief failed")
            await asyncio.sleep(60)

    # --- conversations and snooze -------------------------------------------
    def thread_ids(self, message_ids: list[int]) -> list[int]:
        """The given messages plus the rest of their conversations (same mailbox)."""
        ids = list(dict.fromkeys(message_ids))[:500]
        if not ids:
            return []
        with self.db.conn() as c:
            rows = c.execute(
                f"SELECT DISTINCT t.id FROM messages m JOIN messages t ON t.id=m.id OR (m.thread_key!=''"
                f" AND t.thread_key=m.thread_key AND t.account_id=m.account_id) WHERE m.id IN ({','.join('?' * len(ids))})",
                ids).fetchall()
        return [r[0] for r in rows]

    def conversation(self, m: dict, limit: int = 30) -> list[dict]:
        """The other messages of a conversation, received and sent, oldest first."""
        if not m.get("thread_key"):
            return []
        with self.db.conn() as c:
            items = [dict(r, kind="received") for r in c.execute(
                "SELECT id, from_name AS name, from_addr AS addr, date, substr(body_text, 1, 3000) AS body_text, seen"
                " FROM messages WHERE thread_key=? AND id!=? ORDER BY date DESC LIMIT ?",
                (m["thread_key"], m["id"], limit))]
            items += [dict(r, kind="sent") for r in c.execute(
                "SELECT id, to_name AS name, to_addr AS addr, date, substr(body_text, 1, 3000) AS body_text"
                " FROM sent_messages WHERE thread_key=? ORDER BY date DESC LIMIT ?", (m["thread_key"], limit))]
        items.sort(key=lambda it: it["date"])
        return items[-limit:]

    def snooze(self, ids: list[int], until: str | None) -> None:
        """Hides mail from the inbox until a date. Only in Beseder: nothing changes on the server."""
        value = None
        if until:
            try:
                when = datetime.fromisoformat(until.replace("Z", "+00:00"))
            except ValueError:
                raise ValueError("Invalid date")
            if when.tzinfo is None:
                raise ValueError("The date needs a time zone")
            now = datetime.now(timezone.utc)
            if not now < when < now + timedelta(days=366):
                raise ValueError("Pick a time in the next 12 months")
            value = when.astimezone(timezone.utc).isoformat(timespec="seconds")
        with self.db.conn() as c:
            c.executemany("UPDATE messages SET snoozed_until=?, resurfaced_at=NULL WHERE id=?",
                          [(value, i) for i in ids])
        self._followups = None

    async def wake_snoozed(self) -> int:
        """Snoozed mail whose time has come goes back on top of the inbox, with a notification."""
        now = now_iso()
        with self.db.conn() as c:
            rows = [dict(r) for r in c.execute(
                "SELECT m.id, m.subject, m.from_name, m.from_addr, a.name AS account FROM messages m"
                " JOIN accounts a ON a.id=m.account_id WHERE m.snoozed_until<=? ORDER BY m.date", (now,))]
            c.executemany("UPDATE messages SET snoozed_until=NULL, resurfaced_at=? WHERE id=?",
                          [(now, r["id"]) for r in rows])
        if not rows:
            return 0
        self.mark_changed()
        if self.db.get_setting("push_mode", "important") != "off" and self.push.count():
            note = self._notification(rows)
            note["title"] = f"Back from snooze: {note['title']}" if len(rows) == 1 else f"{len(rows)} emails back from snooze"
            await self.push.send(note)
        return len(rows)

    async def archive_ids(self, ids: list[int]) -> list[dict]:
        with self.db.conn() as c:
            rows = c.execute(f"SELECT id, account_id FROM messages WHERE id IN ({','.join('?' * len(ids))})",
                             ids).fetchall()
        by_account: dict[int, list[int]] = {}
        for r in rows:
            by_account.setdefault(r["account_id"], []).append(r["id"])
        return [await asyncio.to_thread(self.mail.move_many, a, i, None) for a, i in by_account.items()]

    # --- search -----------------------------------------------------------
    async def ask_search(self, question: str, account_id: int | None = None) -> dict:
        provider = self.provider()
        system, user = tasks.search_plan_prompt(question, datetime.now(timezone.utc).date().isoformat())
        plan = tasks.parse_search_plan(await provider.complete(system, user, fast=True, max_tokens=300))
        where, args = [], []
        if plan["terms"]:
            where.append("messages_fts MATCH ?")
            args.append(" OR ".join(f'"{t}"*' for t in plan["terms"]))
        if plan["from"]:
            where.append("(m.from_name LIKE ? OR m.from_addr LIKE ?)")
            args += [f"%{plan['from']}%"] * 2
        if plan["category"]:
            where.append("m.category=?")
            args.append(plan["category"])
        if plan["days"]:
            where.append("m.date>=?")
            args.append((datetime.now(timezone.utc) - timedelta(days=plan["days"])).isoformat(timespec="seconds"))
        if plan["unread"]:
            where.append("m.seen=0")
        if account_id:
            where.append("m.account_id=?")
            args.append(account_id)
        sql = ("SELECT m.id, m.account_id, a.name AS account_name, m.subject, m.from_name, m.from_addr, m.date,"
               " m.snippet, m.seen, m.category, m.category_source, m.body_text FROM messages m"
               " JOIN accounts a ON a.id=m.account_id")
        if plan["terms"]:
            sql += " JOIN messages_fts ON messages_fts.rowid=m.id"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY " + ("messages_fts.rank" if plan["terms"] else "m.date DESC") + " LIMIT ?"
        args.append(tasks.ASK_LIMIT)
        with self.db.conn() as c:
            try:
                rows = [dict(r) for r in c.execute(sql, args)]
            except sqlite3.OperationalError:  # a term FTS can't parse: no result rather than an error
                rows = []
        self.db.audit("ai_search", f"{len(rows)} candidates")
        if not rows:
            return {"items": [], "answer": "", "loose": False}
        system, user = tasks.search_rank_prompt(question, rows)
        ranked = tasks.parse_search_rank(await provider.complete(system, user, max_tokens=600), [r["id"] for r in rows])
        by_id = {r["id"]: r for r in rows}
        items, loose = [by_id[i] for i in ranked["ids"]], False
        if not items:  # nothing answers it exactly: show the closest matches anyway
            items, loose = rows[:10], True
        for it in items:
            it.pop("body_text", None)
        return {"items": items, "answer": ranked["answer"], "loose": loose}

    # --- bulk actions -----------------------------------------------------
    async def archive_sender(self, addr: str) -> list[dict]:
        """Archives everything from one sender, in every mailbox. Returns what to undo."""
        with self.db.conn() as c:
            ids = [r[0] for r in c.execute("SELECT id FROM messages WHERE from_addr=?", (addr.lower(),))]
        return await self.archive_ids(ids) if ids else []

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
                await self.after_sync()
                self.mark_changed()
                return new
            finally:
                self.status["syncing"] = False

    def mark_changed(self) -> None:
        """The mail list changed: wake up the pages listening on /api/events."""
        self.status["version"] += 1
        self._followups = None
        self._changed.set()
        self._changed = asyncio.Event()

    async def wait_change(self, timeout: float) -> None:
        try:
            await asyncio.wait_for(self._changed.wait(), timeout)
        except asyncio.TimeoutError:
            pass

    async def sync_one(self, account_id: int) -> int:
        """Syncs one mailbox now (new mail announced by IDLE). Waits for a running sync."""
        async with self.sync_lock:
            self.status["syncing"] = True
            try:
                new = await asyncio.to_thread(self.mail.sync_account, account_id, True)
                await self.after_sync()
                self.mark_changed()
                return new
            finally:
                self.status["syncing"] = False

    async def after_sync(self) -> None:
        await self.run_triage()
        try:
            await self.notify_new()
        except Exception:
            log.exception("Could not send notifications")

    # --- notifications -----------------------------------------------------
    async def notify_new(self) -> int:
        """Sends a push for new unread mail, once triage has had its say. Returns how many were announced."""
        mode = self.db.get_setting("push_mode", "important")
        with self.db.conn() as c:
            rows = [dict(r) for r in c.execute(
                "SELECT m.id, m.category, m.subject, m.from_name, m.from_addr, m.date, m.seen, a.name AS account"
                " FROM messages m JOIN accounts a ON a.id=m.account_id WHERE m.notified=0 ORDER BY m.date"
            )]
        if not rows:
            return 0
        old = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(timespec="seconds")
        announce, done = [], []
        for r in rows:
            if mode == "all" and not r["seen"]:
                announce.append(r)
            elif mode == "important" and not r["seen"] and r["category"] == "important":
                announce.append(r)
            elif mode == "important" and r["category"] is None and self.auto_triage and r["date"] > old:
                continue  # not sorted yet: decide at the next pass
            done.append(r["id"])
        done += [r["id"] for r in announce]
        with self.db.conn() as c:
            c.executemany("UPDATE messages SET notified=1 WHERE id=?", [(i,) for i in set(done)])
        if announce and self.push.count():
            await self.push.send(self._notification(announce), urgency="high")
        return len(announce)

    def _notification(self, mails: list[dict]) -> dict:
        preview = self.db.get_setting("push_preview", True)
        if len(mails) == 1:
            m = mails[0]
            return {
                "title": (m["from_name"] or m["from_addr"]) if preview else "New email",
                "body": (m["subject"] or "(no subject)") if preview else f"In {m['account']}",
                "url": f"/#/m/{m['id']}", "tag": f"m{m['id']}",
            }
        senders = ", ".join(dict.fromkeys(m["from_name"] or m["from_addr"] for m in mails))
        return {
            "title": f"{len(mails)} new emails",
            "body": senders[:180] if preview else "Open Beseder to read them",
            "url": "/#/", "tag": "batch",
        }

    def push_settings(self) -> dict:
        return {"mode": self.db.get_setting("push_mode", "important"),
                "preview": self.db.get_setting("push_preview", True)}

    def set_push_settings(self, mode: str, preview: bool) -> None:
        if mode not in PUSH_MODES:
            raise ValueError("Unknown notification mode")
        self.db.set_setting("push_mode", mode)
        self.db.set_setting("push_preview", bool(preview))

    # --- instant mail (IMAP IDLE) -------------------------------------------
    def start_watchers(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop
        with self.db.conn() as c:
            for (account_id,) in c.execute("SELECT id FROM accounts").fetchall():
                self.watch(account_id)

    def watch(self, account_id: int) -> None:
        if self._loop is None or account_id in self._watchers:
            return
        stop = threading.Event()
        self._watchers[account_id] = stop

        def on_new() -> None:  # called from the IDLE thread
            asyncio.run_coroutine_threadsafe(self._sync_soon_once(account_id), self._loop)

        threading.Thread(target=self.mail.watch_inbox, args=(account_id, on_new, stop),
                         name=f"idle-{account_id}", daemon=True).start()

    def unwatch(self, account_id: int) -> None:
        stop = self._watchers.pop(account_id, None)
        if stop:
            stop.set()

    def stop_watchers(self) -> None:
        for account_id in list(self._watchers):
            self.unwatch(account_id)

    async def _sync_soon_once(self, account_id: int) -> None:
        # Servers often send several events in a row: one sync covers them all.
        if account_id in self._sync_soon:
            return
        self._sync_soon.add(account_id)
        try:
            await asyncio.sleep(1)
        finally:
            self._sync_soon.discard(account_id)
        await self.sync_one(account_id)

    async def scheduler(self) -> None:
        while True:
            try:
                await self.sync_all()
            except Exception:
                log.exception("Error during sync")
            await asyncio.sleep(self.config.sync_interval)
