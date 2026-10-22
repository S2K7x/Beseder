"""API HTTP + service de la PWA."""

import asyncio
import contextlib
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from imapclient.exceptions import IMAPClientError, LoginError
from pydantic import BaseModel

from .ai import tasks
from .ai.providers import PRESETS, AIError, make_provider
from .config import Config
from .db import now_iso
from .mail.imap import PRESETS as MAIL_PRESETS
from .mail.imap import MailService, reply_recipient
from .mail.oauth_ms import MicrosoftOAuth
from .service import Beseder

WEB_DIR = Path(__file__).resolve().parent.parent / "web"

CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data: https:; connect-src 'self'; frame-src 'self' about:; "
    "object-src 'none'; base-uri 'self'; form-action 'none'; frame-ancestors 'none'"
)


# --- modèles d'entrée ---------------------------------------------------------
class AccountIn(BaseModel):
    kind: str
    name: str = ""
    email: str
    password: str
    host: str = ""
    port: int = 993
    username: str = ""


class OutlookStartIn(BaseModel):
    email: str
    name: str = ""
    client_id: str
    tenant: str = "common"


class FlowIn(BaseModel):
    flow_id: str


class CategoryIn(BaseModel):
    category: str
    remember_sender: bool = False


class DraftIn(BaseModel):
    instructions: str = ""


class DraftSaveIn(BaseModel):
    body: str


class SummaryIn(BaseModel):
    account_id: int | None = None


class TriageIn(BaseModel):
    auto: bool


class AIIn(BaseModel):
    preset: str
    base_url: str = ""
    model: str = ""
    model_fast: str = ""
    api_key: str = ""
    clear_key: bool = False
    command: str = "claude"


class ProfileIn(BaseModel):
    name: str = ""


def create_app(config: Config | None = None, oauth: MicrosoftOAuth | None = None) -> FastAPI:
    config = config or Config()
    core = Beseder(config, oauth)
    background: set[asyncio.Task] = set()

    def spawn(coro) -> None:
        task = asyncio.create_task(coro)
        background.add(task)
        task.add_done_callback(background.discard)

    @contextlib.asynccontextmanager
    async def lifespan(app):
        task = asyncio.create_task(core.scheduler()) if config.run_scheduler else None
        yield
        if task:
            task.cancel()

    app = FastAPI(title="Beseder", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.core = core
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=config.allowed_hosts)

    @app.middleware("http")
    async def security(request: Request, call_next):
        # Anti-CSRF : un site tiers ne peut pas ajouter d'en-tête personnalisé sans preflight CORS.
        if request.url.path.startswith("/api/") and request.method not in ("GET", "HEAD", "OPTIONS"):
            if request.headers.get("x-beseder") != "1":
                return JSONResponse({"detail": "En-tête X-Beseder manquant"}, status_code=403)
        response = await call_next(request)
        response.headers["Content-Security-Policy"] = CSP
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    def ai_error(e: AIError):
        raise HTTPException(502, str(e))

    # --- statut -----------------------------------------------------------
    @app.get("/api/status")
    def status():
        with core.db.conn() as c:
            accounts = [
                dict(r)
                for r in c.execute(
                    "SELECT a.id, a.name, a.email, a.kind, a.last_sync, a.last_error,"
                    " (SELECT COUNT(*) FROM messages m WHERE m.account_id=a.id AND m.seen=0) AS unread"
                    " FROM accounts a ORDER BY a.id"
                )
            ]
            counts = {
                (r["category"] or "non_trie"): r["n"]
                for r in c.execute("SELECT category, COUNT(*) n FROM messages WHERE seen=0 GROUP BY category")
            }
        cfg = core.ai_config()
        return {
            "accounts": accounts,
            "unread_by_category": counts,
            "categories": tasks.CATEGORIES,
            "auto_triage": core.auto_triage,
            "ai_configured": cfg.configured,
            "ai_label": PRESETS.get(cfg.preset, {}).get("label", ""),
            "syncing": core.status["syncing"],
            "triage_error": core.status["triage_error"],
        }

    # --- messages ---------------------------------------------------------
    @app.get("/api/messages")
    def list_messages(
        category: str = "", account_id: int | None = None, unread: bool = False, q: str = "",
        before: str = "", limit: int = 50,
    ):
        where, args = [], []
        if category == "non_trie":
            where.append("m.category IS NULL")
        elif category:
            where.append("m.category=?")
            args.append(category)
        if account_id:
            where.append("m.account_id=?")
            args.append(account_id)
        if unread:
            where.append("m.seen=0")
        if q:
            where.append("(m.subject LIKE ? OR m.from_name LIKE ? OR m.from_addr LIKE ? OR m.body_text LIKE ?)")
            args += [f"%{q}%"] * 4
        if before:
            where.append("m.date<?")
            args.append(before)
        sql = (
            "SELECT m.id, m.account_id, a.name AS account_name, m.subject, m.from_name, m.from_addr, m.date,"
            " m.snippet, m.seen, m.category, m.category_source FROM messages m JOIN accounts a ON a.id=m.account_id"
        )
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY m.date DESC LIMIT ?"
        args.append(max(1, min(limit, 200)))
        with core.db.conn() as c:
            return [dict(r) for r in c.execute(sql, args)]

    def get_message(message_id: int) -> dict:
        with core.db.conn() as c:
            row = c.execute(
                "SELECT m.*, a.name AS account_name, a.email AS account_email FROM messages m"
                " JOIN accounts a ON a.id=m.account_id WHERE m.id=?",
                (message_id,),
            ).fetchone()
        if row is None:
            raise HTTPException(404, "Message introuvable")
        return dict(row)

    @app.get("/api/messages/{message_id}")
    def read_message(message_id: int):
        m = get_message(message_id)
        m["reply_to_display"] = reply_recipient(m)
        return m

    @app.post("/api/messages/{message_id}/read")
    async def mark_read(message_id: int):
        get_message(message_id)
        with core.db.conn() as c:
            c.execute("UPDATE messages SET seen=1 WHERE id=?", (message_id,))
        spawn(asyncio.to_thread(core.mail.mark_seen, message_id))
        return {"ok": True}

    @app.post("/api/messages/{message_id}/category")
    def set_category(message_id: int, body: CategoryIn):
        try:
            core.set_category(message_id, body.category, body.remember_sender)
        except ValueError as e:
            raise HTTPException(400, str(e))
        except LookupError as e:
            raise HTTPException(404, str(e))
        return {"ok": True}

    @app.post("/api/messages/{message_id}/draft")
    async def draft(message_id: int, body: DraftIn):
        m = get_message(message_id)
        try:
            text = await tasks.draft(core.provider(), m, body.instructions, core.db.get_setting("my_name", ""))
        except AIError as e:
            ai_error(e)
        core.db.audit("ai_draft", f"message={message_id}")
        return {"body": text, "to": reply_recipient(m), "subject": m["subject"]}

    @app.post("/api/messages/{message_id}/draft/save")
    async def save_draft(message_id: int, body: DraftSaveIn):
        get_message(message_id)
        if not body.body.strip():
            raise HTTPException(400, "Brouillon vide")
        try:
            folder = await asyncio.to_thread(core.mail.save_draft, message_id, body.body)
        except LookupError as e:
            raise HTTPException(404, str(e))
        except (IMAPClientError, OSError, PermissionError) as e:
            raise HTTPException(502, f"Échec IMAP : {e}")
        return {"ok": True, "folder": folder}

    # --- IA : résumé et tri ----------------------------------------------
    @app.post("/api/summary")
    async def summary(body: SummaryIn):
        sql = "SELECT * FROM messages WHERE seen=0"
        args: list = []
        if body.account_id:
            sql += " AND account_id=?"
            args.append(body.account_id)
        sql += " ORDER BY date DESC LIMIT ?"
        args.append(tasks.SUMMARY_LIMIT)
        with core.db.conn() as c:
            rows = [dict(r) for r in c.execute(sql, args)]
        try:
            result = await tasks.summarize(core.provider() if rows else None, rows)
        except AIError as e:
            ai_error(e)
        meta = {r["id"]: r for r in rows}
        for it in result["items"]:
            r = meta[it["id"]]
            it.update(subject=r["subject"], from_name=r["from_name"] or r["from_addr"])
        core.db.audit("ai_summary", f"{len(rows)} mails")
        result["count"] = len(rows)
        result["generated_at"] = now_iso()
        return result

    @app.put("/api/settings/triage")
    async def set_triage(body: TriageIn):
        core.db.set_setting("auto_triage", body.auto)
        if body.auto:
            spawn(core.run_triage())
        return {"auto_triage": body.auto}

    @app.post("/api/triage/run")
    async def run_triage():
        if not core.auto_triage:
            raise HTTPException(400, "Le tri automatique est désactivé")
        n = await core.run_triage()
        if core.status["triage_error"]:
            raise HTTPException(502, core.status["triage_error"])
        return {"classified": n}

    @app.get("/api/rules")
    def rules():
        with core.db.conn() as c:
            return [dict(r) for r in c.execute("SELECT * FROM sender_rules ORDER BY addr")]

    @app.delete("/api/rules/{addr}")
    def delete_rule(addr: str):
        with core.db.conn() as c:
            c.execute("DELETE FROM sender_rules WHERE addr=?", (addr,))
        return {"ok": True}

    # --- réglages IA ------------------------------------------------------
    @app.get("/api/settings/ai")
    def get_ai():
        cfg = core.ai_config()
        return {
            "presets": PRESETS,
            "preset": cfg.preset,
            "base_url": cfg.base_url,
            "model": cfg.model,
            "model_fast": cfg.model_fast,
            "command": cfg.command,
            "has_key": bool(cfg.api_key),
            "my_name": core.db.get_setting("my_name", ""),
        }

    @app.put("/api/settings/ai")
    def put_ai(body: AIIn):
        try:
            core.save_ai_config(body.model_dump())
        except ValueError as e:
            raise HTTPException(400, str(e))
        return {"ok": True}

    @app.put("/api/settings/profile")
    def put_profile(body: ProfileIn):
        core.db.set_setting("my_name", body.name.strip()[:100])
        return {"ok": True}

    @app.post("/api/settings/ai/test")
    async def test_ai():
        try:
            text = await core.provider().complete(
                "Tu réponds en un seul mot.", "Réponds exactement : OK", fast=True, max_tokens=20
            )
        except AIError as e:
            ai_error(e)
        return {"ok": True, "reply": text.strip()[:100]}

    @app.post("/api/settings/ai/models")
    async def list_models(body: AIIn):
        """Liste les modèles avec les valeurs du formulaire (avant d'enregistrer)."""
        cfg = core.ai_config()
        preset = PRESETS.get(body.preset)
        if not preset:
            raise HTTPException(400, "Fournisseur inconnu")
        cfg.kind = preset["kind"]
        cfg.base_url = body.base_url or preset["base_url"]
        cfg.command = body.command or "claude"
        if body.api_key:
            cfg.api_key = body.api_key
        elif cfg.preset != body.preset:
            cfg.api_key = ""
        try:
            return {"models": await make_provider(cfg).list_models()}
        except Exception as e:
            raise HTTPException(502, f"Impossible de lister les modèles : {e}")

    # --- comptes ----------------------------------------------------------
    @app.get("/api/accounts")
    def accounts():
        with core.db.conn() as c:
            return [
                dict(r)
                for r in c.execute(
                    "SELECT id, name, email, kind, host, port, username, last_sync, last_error FROM accounts"
                )
            ]

    def insert_account(kind, name, email, host, port, username, secret) -> int:
        with core.db.conn() as c:
            cur = c.execute(
                "INSERT INTO accounts(name, email, kind, host, port, username, secret, created_at)"
                " VALUES(?,?,?,?,?,?,?,?)",
                (name or email, email, kind, host, port, username, core.vault.encrypt(secret), now_iso()),
            )
            return cur.lastrowid

    @app.post("/api/accounts")
    async def add_account(body: AccountIn):
        if body.kind not in ("gmail", "icloud", "imap"):
            raise HTTPException(400, "Type de compte inconnu (Outlook passe par la connexion Microsoft)")
        preset = MAIL_PRESETS.get(body.kind, {})
        host = preset.get("host") or body.host.strip()
        port = preset.get("port") or body.port
        username = body.username.strip() or body.email.strip()
        password = body.password.replace(" ", "") if body.kind == "gmail" else body.password
        if not host:
            raise HTTPException(400, "Serveur IMAP requis")
        try:
            await asyncio.to_thread(MailService.test_login, host, port, username, password)
        except LoginError:
            raise HTTPException(400, "Identifiants refusés. Utilise un mot de passe d'application.")
        except (IMAPClientError, OSError) as e:
            raise HTTPException(400, f"Connexion impossible : {e}")
        account_id = insert_account(body.kind, body.name, body.email.strip(), host, port, username, {"password": password})
        spawn(core.sync_all())
        return {"id": account_id}

    @app.post("/api/accounts/outlook/start")
    def outlook_start(body: OutlookStartIn):
        core.db.set_setting("ms_client_id", body.client_id.strip())
        try:
            return core.mail.oauth.start(body.client_id.strip(), body.tenant or "common", body.email.strip(), body.name)
        except Exception as e:
            raise HTTPException(400, f"Microsoft a refusé : {e}")

    @app.post("/api/accounts/outlook/poll")
    async def outlook_poll(body: FlowIn):
        state, data, flow = await asyncio.to_thread(core.mail.oauth.poll, body.flow_id)
        if state == "pending":
            return {"status": "pending"}
        if state == "error":
            return {"status": "error", "message": data["message"]}
        secret = {"client_id": flow.client_id, "tenant": flow.tenant, "refresh_token": data["refresh_token"]}
        p = MAIL_PRESETS["outlook"]
        account_id = insert_account("outlook", flow.name, flow.email, p["host"], p["port"], flow.email, secret)
        spawn(core.sync_all())
        return {"status": "done", "id": account_id}

    @app.get("/api/settings/outlook")
    def outlook_settings():
        return {"client_id": core.db.get_setting("ms_client_id", "")}

    @app.delete("/api/accounts/{account_id}")
    def delete_account(account_id: int):
        """Retire le compte de Beseder (données locales seulement, rien n'est supprimé sur le serveur)."""
        with core.db.conn() as c:
            c.execute("DELETE FROM accounts WHERE id=?", (account_id,))
        return {"ok": True}

    @app.post("/api/sync")
    async def sync():
        if core.sync_lock.locked():
            return {"started": False}
        spawn(core.sync_all())
        return {"started": True}

    # --- PWA --------------------------------------------------------------
    @app.get("/")
    def index():
        return FileResponse(WEB_DIR / "index.html")

    @app.get("/sw.js")
    def service_worker():
        return FileResponse(WEB_DIR / "sw.js", media_type="text/javascript", headers={"Cache-Control": "no-cache"})

    app.mount("/", StaticFiles(directory=WEB_DIR), name="web")
    return app
