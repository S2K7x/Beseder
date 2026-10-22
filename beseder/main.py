"""HTTP API + PWA serving."""

import asyncio
import contextlib
import re
import sqlite3
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from imapclient.exceptions import IMAPClientError
from pydantic import BaseModel

from .ai import tasks
from .ai.providers import AIError, make_provider, presets_for
from .config import Config
from .db import now_iso
from .mail import providers
from .mail.imap import LoginRejected, MailService, reply_recipient
from .mail.oauth_ms import MicrosoftOAuth
from .mail.parse import sanitize_html
from .service import Beseder
from .unsubscribe import UnsubscribeError, one_click

WEB_DIR = Path(__file__).resolve().parent.parent / "web"

CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data: https:; connect-src 'self'; frame-src 'self' about:; "
    "object-src 'none'; base-uri 'self'; form-action 'none'; frame-ancestors 'none'"
)


# --- request models -----------------------------------------------------------
class AccountIn(BaseModel):
    kind: str
    name: str = ""
    email: str
    password: str
    host: str = ""
    port: int = 0
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


class OnboardedIn(BaseModel):
    done: bool = True


class MoveIn(BaseModel):
    folder: str | None = None  # None = the archive


class RestoreIn(BaseModel):
    folder: str
    message_id: str = ""
    message_ids: list[str] = []


class SenderIn(BaseModel):
    addr: str


class FollowupDoneIn(BaseModel):
    kind: str  # reply | waiting
    id: int


class RulesIn(BaseModel):
    rules: str = ""


class StyleIn(BaseModel):
    learn: bool


class BriefIn(BaseModel):
    time: str = ""  # "07:30", empty = off
    tz: str = "UTC"


class SnoozeIn(BaseModel):
    until: str | None = None  # ISO date-time; None = back to the inbox now


class BulkIn(BaseModel):
    ids: list[int]
    action: str  # archive | read | category | snooze | unsnooze
    category: str = ""
    until: str = ""


class AskIn(BaseModel):
    question: str
    account_id: int | None = None


class PushSubscriptionIn(BaseModel):
    subscription: dict
    label: str = ""


class EndpointIn(BaseModel):
    endpoint: str


class PushSettingsIn(BaseModel):
    mode: str
    preview: bool = True


class ProfileIn(BaseModel):
    name: str = ""
    summary_language: str = "English"


LIST_COLUMNS = ("m.id, m.account_id, a.name AS account_name, m.subject, m.from_name, m.from_addr, m.date,"
                " m.snippet, m.seen, m.category, m.category_source")


def fts_query(q: str) -> str | None:
    """Search box text -> FTS5 query: every word must match the start of a word ("fact"
    finds "facture"). Accents are ignored by the index. Quotes keep FTS syntax out."""
    words = re.findall(r"\w+", q)[:8]
    return " ".join(f'"{w}"*' for w in words) or None


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
        tasks_ = [asyncio.create_task(core.scheduler()), asyncio.create_task(core.minute_loop())] \
            if config.run_scheduler else []
        if config.run_scheduler and config.idle:
            core.start_watchers(asyncio.get_running_loop())
        yield
        core.stop_watchers()
        for t in tasks_:
            t.cancel()

    app = FastAPI(title="Beseder", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.core = core
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=config.allowed_hosts)

    @app.middleware("http")
    async def security(request: Request, call_next):
        # Anti-CSRF: a third-party site cannot add a custom header without a CORS preflight.
        if request.url.path.startswith("/api/") and request.method not in ("GET", "HEAD", "OPTIONS"):
            if request.headers.get("x-beseder") != "1":
                return JSONResponse({"detail": "Missing X-Beseder header"}, status_code=403)
        response = await call_next(request)
        response.headers["Content-Security-Policy"] = CSP
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    def ai_error(e: AIError):
        raise HTTPException(502, str(e))

    presets = presets_for(config.in_docker)

    # --- status -----------------------------------------------------------
    @app.get("/api/health")
    def health():
        return {"ok": True}

    @app.put("/api/settings/onboarded")
    async def set_onboarded(body: OnboardedIn):
        core.db.set_setting("onboarded", body.done)
        if body.done:
            spawn(core.sync_all())
        return {"onboarded": body.done}

    @app.get("/api/events")
    async def events(request: Request):
        """Server-sent events: the page hears about new mail as soon as it is synced."""
        async def stream():
            last = None
            while not await request.is_disconnected():
                version = core.status["version"]
                if version != last:
                    last = version
                    yield f"data: {version}\n\n"
                else:
                    yield ": keep-alive\n\n"
                await core.wait_change(timeout=25)

        return StreamingResponse(stream(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})

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
                (r["category"] or "untriaged"): r["n"]
                for r in c.execute("SELECT category, COUNT(*) n FROM messages WHERE seen=0 AND snoozed_until IS NULL"
                                   " GROUP BY category")
            }
            snoozed = c.execute("SELECT COUNT(*) FROM messages WHERE snoozed_until IS NOT NULL").fetchone()[0]
        cfg = core.ai_config()
        follow = core.followups()
        return {
            "accounts": accounts,
            "followups": {"to_reply": len(follow["to_reply"]), "waiting": len(follow["waiting"])},
            "snoozed": snoozed,
            "unread_by_category": counts,
            "categories": tasks.CATEGORIES,
            "auto_triage": core.auto_triage,
            "ai_configured": cfg.configured,
            "ai_label": presets.get(cfg.preset, {}).get("label", ""),
            "syncing": core.status["syncing"],
            "version": core.status["version"],
            "triage_error": core.status["triage_error"],
            "my_name": core.db.get_setting("my_name", ""),
            "summary_language": core.db.get_setting("summary_language", "English"),
            "onboarded": core.onboarded,
            "in_docker": config.in_docker,
        }

    # --- messages ---------------------------------------------------------
    @app.get("/api/messages")
    def list_messages(
        category: str = "", account_id: int | None = None, unread: bool = False, q: str = "",
        before: str = "", before_id: int = 0, limit: int = 50, snoozed: bool = False, threads: bool = True,
        sender: str = "",
    ):
        """One card per conversation (its latest message), newest first. Searches and the
        Snoozed list show single messages. Mail back from snooze comes first on page one."""
        def filters(t: str) -> tuple[list, list]:
            w, a = [], []
            if category == "untriaged":
                w.append(f"{t}.category IS NULL")
            elif category:
                w.append(f"{t}.category=?")
                a.append(category)
            if account_id:
                w.append(f"{t}.account_id=?")
                a.append(account_id)
            if unread:
                w.append(f"{t}.seen=0")
            if sender:
                w.append(f"{t}.from_addr=?")
                a.append(sender.strip().lower())
            w.append(f"{t}.snoozed_until IS {'NOT ' if snoozed else ''}NULL")
            return w, a

        def latest_of_thread(resurfaced: bool) -> tuple[str, list]:
            # No newer message of the same conversation passes the same filters.
            inner, inner_args = filters("n")
            return ("NOT (m.thread_key!='' AND EXISTS (SELECT 1 FROM messages n WHERE n.thread_key=m.thread_key"
                    " AND (n.date>m.date OR (n.date=m.date AND n.id>m.id))" + "".join(f" AND {x}" for x in inner)
                    + f" AND n.resurfaced_at IS {'NOT ' if resurfaced else ''}NULL))"), inner_args

        where, args = filters("m")
        group = threads and not q and not snoozed
        columns = LIST_COLUMNS
        pinned_where, pinned_args = where + ["m.resurfaced_at IS NOT NULL"], list(args)
        if group:
            clause, extra = latest_of_thread(False)
            where, args = where + [clause], args + extra
            clause, extra = latest_of_thread(True)
            pinned_where, pinned_args = pinned_where + [clause], pinned_args + extra
            columns += (", (SELECT COUNT(*) FROM messages t WHERE t.thread_key=m.thread_key AND m.thread_key!='')"
                        " AS thread_count, (SELECT COUNT(*) FROM messages t WHERE t.thread_key=m.thread_key"
                        " AND m.thread_key!='' AND t.seen=0) AS thread_unread")
        if not snoozed:
            where.append("m.resurfaced_at IS NULL")
        match = fts_query(q) if q else None
        if match:
            where.append("m.id IN (SELECT rowid FROM messages_fts WHERE messages_fts MATCH ?)")
            args.append(match)
        elif q:  # only punctuation or symbols: plain substring search
            where.append("(m.subject LIKE ? OR m.from_name LIKE ? OR m.from_addr LIKE ? OR m.body_text LIKE ?)")
            args += [f"%{q}%"] * 4
        if before:
            # Keyset pagination on (date, id): messages sharing a date are neither skipped nor repeated.
            where.append("(m.date<? OR (m.date=? AND m.id<?))")
            args += [before, before, before_id or 2**62]
        sql = f"SELECT {columns}, m.snoozed_until FROM messages m JOIN accounts a ON a.id=m.account_id"
        sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY m.date DESC, m.id DESC LIMIT ?"
        args.append(max(1, min(limit, 200)))
        with core.db.conn() as c:
            try:
                rows = [dict(r) for r in c.execute(sql, args)]
            except sqlite3.OperationalError:
                raise HTTPException(400, "Cannot search for this")
            if not before and not q and not snoozed:
                pinned = [dict(r, resurfaced=True) for r in c.execute(
                    f"SELECT {columns}, m.snoozed_until FROM messages m JOIN accounts a ON a.id=m.account_id WHERE "
                    + " AND ".join(pinned_where)
                    + " ORDER BY m.resurfaced_at DESC LIMIT 50", pinned_args)]
                rows = pinned + rows
        return rows

    @app.post("/api/search/ask")
    async def ask_search(body: AskIn):
        """Search in plain language: the AI turns the question into a search, then picks the
        emails that answer it among the results."""
        if not body.question.strip():
            raise HTTPException(400, "Ask a question")
        try:
            return await core.ask_search(body.question, body.account_id)
        except AIError as e:
            ai_error(e)

    def get_message(message_id: int) -> dict:
        with core.db.conn() as c:
            row = c.execute(
                "SELECT m.*, a.name AS account_name, a.email AS account_email FROM messages m"
                " JOIN accounts a ON a.id=m.account_id WHERE m.id=?",
                (message_id,),
            ).fetchone()
        if row is None:
            raise HTTPException(404, "Message not found")
        return dict(row)

    @app.get("/api/messages/{message_id}")
    def read_message(message_id: int):
        m = get_message(message_id)
        m["reply_to_display"] = reply_recipient(m)
        # Sanitized at import too; doing it again here covers mail stored by an older sanitizer.
        m["body_html"] = sanitize_html(m["body_html"]) if m["body_html"] else ""
        with core.db.conn() as c:
            m["attachments"] = [dict(r) for r in c.execute(
                "SELECT idx, filename, content_type, size FROM attachments WHERE message_id=? ORDER BY idx",
                (message_id,))]
        m["thread"] = core.conversation(m)
        return m

    @app.post("/api/messages/{message_id}/snooze")
    def snooze(message_id: int, body: SnoozeIn):
        get_message(message_id)
        try:
            core.snooze(core.thread_ids([message_id]), body.until)
        except ValueError as e:
            raise HTTPException(400, str(e))
        core.mark_changed()
        return {"ok": True}

    @app.post("/api/messages/bulk")
    async def bulk(body: BulkIn):
        """Acts on several conversations at once. Same writes as one by one, nothing more."""
        if not body.ids or len(body.ids) > 500:
            raise HTTPException(400, "Select between 1 and 500 emails")
        ids = core.thread_ids(body.ids)
        result: dict = {"count": len(ids)}
        try:
            if body.action == "archive":
                result["moved"] = await core.archive_ids(ids)
            elif body.action == "read":
                with core.db.conn() as c:
                    c.executemany("UPDATE messages SET seen=1, resurfaced_at=NULL WHERE id=?", [(i,) for i in ids])
                for i in ids:
                    spawn(core.mark_read(i))
            elif body.action == "category":
                for i in ids:
                    core.set_category(i, body.category, False)
            elif body.action in ("snooze", "unsnooze"):
                core.snooze(ids, body.until if body.action == "snooze" else None)
            else:
                raise HTTPException(400, "Unknown action")
        except ValueError as e:
            raise HTTPException(400, str(e))
        except (IMAPClientError, OSError, PermissionError) as e:
            raise HTTPException(502, f"IMAP error: {e}")
        core.mark_changed()
        return result

    @app.get("/api/messages/{message_id}/attachments/{idx}")
    async def download_attachment(message_id: int, idx: int):
        get_message(message_id)
        try:
            name, data = await asyncio.to_thread(core.mail.download_attachment, message_id, idx)
        except LookupError as e:
            raise HTTPException(404, str(e))
        except (IMAPClientError, OSError, PermissionError) as e:
            raise HTTPException(502, f"IMAP error: {e}")
        # Always a download, never rendered: an HTML or SVG attachment must not run in Beseder's page.
        return Response(data, media_type="application/octet-stream", headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(name, safe='')}",
            "Content-Security-Policy": "sandbox; default-src 'none'",
        })

    @app.post("/api/messages/{message_id}/load-full")
    async def load_full(message_id: int):
        get_message(message_id)
        try:
            await asyncio.to_thread(core.mail.load_full, message_id)
        except LookupError as e:
            raise HTTPException(404, str(e))
        except (IMAPClientError, OSError, PermissionError) as e:
            raise HTTPException(502, f"IMAP error: {e}")
        return {"ok": True}

    @app.post("/api/messages/{message_id}/move")
    async def move_message(message_id: int, body: MoveIn):
        get_message(message_id)
        try:
            return await asyncio.to_thread(core.mail.move, message_id, body.folder)
        except ValueError as e:
            raise HTTPException(400, str(e))
        except LookupError as e:
            raise HTTPException(404, str(e))
        except (IMAPClientError, OSError, PermissionError) as e:
            raise HTTPException(502, f"IMAP error: {e}")

    @app.post("/api/accounts/{account_id}/restore")
    async def restore_message(account_id: int, body: RestoreIn):
        if core.mail.get_account(account_id) is None:
            raise HTTPException(404, "Mailbox not found")
        wanted = [body.message_id] if body.message_id else body.message_ids
        try:
            n = await asyncio.to_thread(core.mail.restore, account_id, body.folder, wanted)
        except (IMAPClientError, OSError, PermissionError) as e:
            raise HTTPException(502, f"IMAP error: {e}")
        if not n:
            raise HTTPException(404, "Could not find the message to put back")
        spawn(core.sync_one(account_id))
        return {"ok": True, "restored": n}

    @app.post("/api/senders/archive")
    async def archive_sender(body: SenderIn):
        """Archives every email from one sender (Undo puts them back)."""
        try:
            done = await core.archive_sender(body.addr.strip())
        except ValueError as e:
            raise HTTPException(400, str(e))
        except (IMAPClientError, OSError, PermissionError) as e:
            raise HTTPException(502, f"IMAP error: {e}")
        core.mark_changed()
        return {"count": sum(len(d["message_ids"]) for d in done), "moved": done}

    @app.post("/api/messages/{message_id}/unsubscribe")
    async def unsubscribe(message_id: int):
        """One-click unsubscribe when the sender supports it (RFC 8058). Otherwise returns the
        link or address for the user to open: Beseder never sends email."""
        m = get_message(message_id)
        if m["unsub_one_click"] and m["unsub_url"]:
            try:
                await one_click(m["unsub_url"])
            except UnsubscribeError as e:
                raise HTTPException(502, str(e))
            core.db.audit("unsubscribed", f"message={message_id}")
            return {"done": True, "sender": m["from_addr"]}
        if m["unsub_url"]:
            return {"done": False, "open": m["unsub_url"], "sender": m["from_addr"]}
        if m["unsub_mailto"]:
            return {"done": False, "open": m["unsub_mailto"], "sender": m["from_addr"]}
        raise HTTPException(404, "This email has no unsubscribe link")

    # --- follow-ups ---------------------------------------------------------
    @app.get("/api/followups")
    def followups():
        return core.followups()

    @app.post("/api/followups/done")
    def followup_done(body: FollowupDoneIn):
        try:
            core.followup_done(body.kind, body.id)
        except ValueError as e:
            raise HTTPException(400, str(e))
        except LookupError as e:
            raise HTTPException(404, str(e))
        return {"ok": True}

    def imap_call(fn, *args):
        """Runs a read-only IMAP call in a thread and turns its errors into HTTP ones."""
        async def run():
            try:
                return await asyncio.to_thread(fn, *args)
            except LookupError as e:
                raise HTTPException(404, str(e))
            except ValueError as e:
                raise HTTPException(400, str(e))
            except (IMAPClientError, OSError, PermissionError) as e:
                raise HTTPException(502, f"IMAP error: {e}")
        return run()

    def need_account(account_id: int) -> None:
        if core.mail.get_account(account_id) is None:
            raise HTTPException(404, "Mailbox not found")

    @app.get("/api/accounts/{account_id}/check")
    async def check_account(account_id: int):
        """Tests a mailbox (read only) and says what works."""
        need_account(account_id)
        return {"items": await imap_call(core.mail.check, account_id)}

    @app.get("/api/accounts/{account_id}/browse")
    async def browse(account_id: int, folder: str, before: int = 0, q: str = ""):
        """Another folder of the mailbox (Archive, All Mail, Sent...), read live and read only."""
        need_account(account_id)
        return await imap_call(core.mail.folder_messages, account_id, folder, before, q)

    @app.get("/api/accounts/{account_id}/browse/message")
    async def browse_message(account_id: int, folder: str, uid: int):
        need_account(account_id)
        m = await imap_call(core.mail.folder_message, account_id, folder, uid)
        m["account_name"] = core.mail.get_account(account_id)["name"]
        return m

    @app.get("/api/accounts/{account_id}/browse/attachment")
    async def browse_attachment(account_id: int, folder: str, uid: int, idx: int):
        need_account(account_id)
        name, data = await imap_call(core.mail.folder_attachment, account_id, folder, uid, idx)
        return Response(data, media_type="application/octet-stream", headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(name, safe='')}",
            "Content-Security-Policy": "sandbox; default-src 'none'",
        })

    @app.get("/api/accounts/{account_id}/folders")
    async def account_folders(account_id: int):
        if core.mail.get_account(account_id) is None:
            raise HTTPException(404, "Mailbox not found")
        try:
            return await asyncio.to_thread(core.mail.folders, account_id)
        except (IMAPClientError, OSError, PermissionError) as e:
            raise HTTPException(502, f"IMAP error: {e}")

    # --- notifications ------------------------------------------------------
    @app.get("/api/push")
    def push_info():
        return {"public_key": core.push.public_key(), "devices": core.push.count(), **core.push_settings()}

    @app.post("/api/push/subscribe")
    def push_subscribe(body: PushSubscriptionIn):
        try:
            core.push.subscribe(body.subscription, body.label)
        except (KeyError, TypeError, ValueError) as e:
            raise HTTPException(400, f"Invalid subscription: {e}")
        return {"devices": core.push.count()}

    @app.post("/api/push/unsubscribe")
    def push_unsubscribe(body: EndpointIn):
        core.push.unsubscribe(body.endpoint)
        return {"devices": core.push.count()}

    @app.put("/api/push/settings")
    def push_settings(body: PushSettingsIn):
        try:
            core.set_push_settings(body.mode, body.preview)
        except ValueError as e:
            raise HTTPException(400, str(e))
        return core.push_settings()

    @app.post("/api/push/test")
    async def push_test():
        sent = await core.push.send({"title": "Beseder", "body": "Notifications work.", "url": "/#/", "tag": "test"})
        if not sent:
            raise HTTPException(400, "No device received it. Turn notifications on from this device first.")
        return {"sent": sent}

    @app.post("/api/messages/{message_id}/read")
    async def mark_read(message_id: int):
        """Opening a conversation reads all of it."""
        get_message(message_id)
        ids = core.thread_ids([message_id])
        with core.db.conn() as c:
            unread = [r[0] for r in c.execute(
                f"SELECT id FROM messages WHERE seen=0 AND id IN ({','.join('?' * len(ids))})", ids)]
            c.executemany("UPDATE messages SET seen=1, resurfaced_at=NULL WHERE id=?", [(i,) for i in ids])
        for i in unread:
            spawn(core.mark_read(i))
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
            text = await tasks.draft(core.provider(), m, body.instructions, core.db.get_setting("my_name", ""),
                                     core.style_examples(m["from_addr"]))
        except AIError as e:
            ai_error(e)
        core.db.audit("ai_draft", f"message={message_id}")
        return {"body": text, "to": reply_recipient(m), "subject": m["subject"]}

    @app.post("/api/messages/{message_id}/draft/save")
    async def save_draft(message_id: int, body: DraftSaveIn):
        get_message(message_id)
        if not body.body.strip():
            raise HTTPException(400, "The draft is empty")
        try:
            folder = await asyncio.to_thread(core.mail.save_draft, message_id, body.body)
        except LookupError as e:
            raise HTTPException(404, str(e))
        except (IMAPClientError, OSError, PermissionError) as e:
            raise HTTPException(502, f"IMAP error: {e}")
        return {"ok": True, "folder": folder}

    # --- AI: summary and triage ------------------------------------------
    @app.post("/api/summary")
    async def summary(body: SummaryIn):
        try:
            return await core.make_summary(body.account_id)
        except AIError as e:
            ai_error(e)

    @app.get("/api/summary/last")
    def last_summary():
        return core.db.get_setting("last_summary")

    @app.put("/api/settings/triage")
    async def set_triage(body: TriageIn):
        core.db.set_setting("auto_triage", body.auto)
        if body.auto:
            spawn(core.run_triage())
        return {"auto_triage": body.auto}

    @app.post("/api/triage/run")
    async def run_triage():
        if not core.auto_triage:
            raise HTTPException(400, "Auto-triage is off")
        n = await core.run_triage()
        if core.status["triage_error"]:
            raise HTTPException(502, core.status["triage_error"])
        return {"classified": n}

    @app.post("/api/triage/resort")
    async def resort():
        """Sorts the last 14 days again, e.g. after changing the sorting rules."""
        n = await core.run_triage(resort=True)
        if core.status["triage_error"]:
            raise HTTPException(502, core.status["triage_error"])
        core.mark_changed()
        return {"classified": n}

    @app.get("/api/settings/assistant")
    def assistant_settings():
        return {"rules": core.db.get_setting("triage_rules", "") or "", "learn_style": core.learn_style,
                **core.brief_settings(), "max_rules": tasks.MAX_RULES}

    @app.put("/api/settings/rules")
    def set_rules(body: RulesIn):
        rules = tasks.clean_rules(body.rules)
        core.db.set_setting("triage_rules", "\n".join(rules))
        return {"rules": rules}

    @app.put("/api/settings/style")
    def set_style(body: StyleIn):
        core.db.set_setting("learn_style", body.learn)
        return {"learn_style": body.learn}

    @app.put("/api/settings/brief")
    def set_brief(body: BriefIn):
        try:
            core.set_brief_settings(body.time.strip(), body.tz.strip())
        except ValueError as e:
            raise HTTPException(400, str(e))
        return core.brief_settings()

    @app.get("/api/rules")
    def rules():
        with core.db.conn() as c:
            return [dict(r) for r in c.execute("SELECT * FROM sender_rules ORDER BY addr")]

    @app.delete("/api/rules/{addr}")
    def delete_rule(addr: str):
        with core.db.conn() as c:
            c.execute("DELETE FROM sender_rules WHERE addr=?", (addr,))
        return {"ok": True}

    # --- AI settings ------------------------------------------------------
    @app.get("/api/settings/ai")
    def get_ai():
        cfg = core.ai_config()
        return {
            "presets": presets,
            "preset": cfg.preset,
            "base_url": cfg.base_url,
            "model": cfg.model,
            "model_fast": cfg.model_fast,
            "command": cfg.command,
            "has_key": bool(cfg.api_key),
            "my_name": core.db.get_setting("my_name", ""),
            "summary_language": core.db.get_setting("summary_language", "English"),
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
        core.db.set_setting("summary_language", body.summary_language.strip()[:40] or "English")
        return {"ok": True}

    @app.post("/api/settings/ai/test")
    async def test_ai():
        try:
            text = await core.provider().complete(
                "You answer with a single word.", "Reply exactly: OK", fast=True, max_tokens=20
            )
        except AIError as e:
            ai_error(e)
        return {"ok": True, "reply": text.strip()[:100]}

    @app.post("/api/settings/ai/models")
    async def list_models(body: AIIn):
        """Lists models using the form values (before saving)."""
        cfg = core.ai_config()
        preset = presets.get(body.preset)
        if not preset:
            raise HTTPException(400, "Unknown provider")
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
            raise HTTPException(502, f"Cannot list models: {e}")

    # --- accounts ---------------------------------------------------------
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
        preset = providers.PROVIDERS.get(body.kind)
        if preset is None or preset.get("auth") == "oauth":
            raise HTTPException(400, "Unknown account type (Outlook uses the Microsoft sign-in)")
        email = body.email.strip()
        if "@" not in email:
            raise HTTPException(400, "Enter the full email address")
        # Server settings can be overridden (regional servers, self-hosted mail...).
        host = body.host.strip() or providers.host_for(body.kind, email)
        port = body.port or preset["port"]
        password = body.password.replace(" ", "") if preset.get("strip_spaces") else body.password.strip()
        if not host:
            raise HTTPException(400, "IMAP server required")
        if not password:
            raise HTTPException(400, f"Enter the {preset['password_label'].lower()}")
        try:
            username = await asyncio.to_thread(
                MailService.test_login, host, port, providers.usernames_for(body.kind, email, body.username.strip()),
                password)
        except LoginRejected:
            raise HTTPException(400, f"Login rejected by {preset['label']}. Check the address and use the "
                                     f"{preset['password_label'].lower()} from the steps above.")
        except (IMAPClientError, OSError) as e:
            raise HTTPException(400, f"Cannot reach {host}:{port} ({e}). Check the address and the server name.")
        account_id = insert_account(body.kind, body.name, email, host, port, username, {"password": password})
        core.watch(account_id)
        spawn(core.sync_all())
        return {"id": account_id}

    @app.get("/api/mail/providers")
    def mail_providers():
        return providers.public_list()

    @app.post("/api/accounts/outlook/start")
    def outlook_start(body: OutlookStartIn):
        core.db.set_setting("ms_client_id", body.client_id.strip())
        try:
            return core.mail.oauth.start(body.client_id.strip(), body.tenant or "common", body.email.strip(), body.name)
        except Exception as e:
            raise HTTPException(400, f"Microsoft refused: {e}")

    @app.post("/api/accounts/outlook/poll")
    async def outlook_poll(body: FlowIn):
        state, data, flow = await asyncio.to_thread(core.mail.oauth.poll, body.flow_id)
        if state == "pending":
            return {"status": "pending"}
        if state == "error":
            return {"status": "error", "message": data["message"]}
        secret = {"client_id": flow.client_id, "tenant": flow.tenant, "refresh_token": data["refresh_token"]}
        p = providers.PROVIDERS["outlook"]
        account_id = insert_account("outlook", flow.name, flow.email, p["host"], p["port"], flow.email, secret)
        core.watch(account_id)
        spawn(core.sync_all())
        return {"status": "done", "id": account_id}

    @app.get("/api/settings/outlook")
    def outlook_settings():
        return {"client_id": core.db.get_setting("ms_client_id", "")}

    @app.delete("/api/accounts/{account_id}")
    def delete_account(account_id: int):
        """Removes the account from Beseder (local data only, nothing is deleted on the server)."""
        core.unwatch(account_id)
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
