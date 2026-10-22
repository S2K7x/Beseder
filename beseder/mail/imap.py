"""IMAP sync.

Allowed writes on the server (see CLAUDE.md): mark as read, add a draft.
Nothing else: no sending, no deleting, no moving.
"""

import logging
import threading
from datetime import date, datetime, timedelta, timezone
from email.message import EmailMessage
from email.utils import formatdate, make_msgid

from imapclient import IMAPClient
from imapclient.imapclient import DRAFTS
from imapclient.exceptions import IMAPClientError, LoginError

from ..config import Config
from ..crypto import Vault
from ..db import DB, now_iso
from .oauth_ms import MicrosoftOAuth
from .parse import parse_message

log = logging.getLogger(__name__)

STARTTLS_PORT = 143


def open_imap(host: str, port: int, timeout: int = 60) -> IMAPClient:
    """Encrypted connection: SSL from the start (993), or STARTTLS on 143. Never in clear text."""
    if port == STARTTLS_PORT:
        client = IMAPClient(host, port=port, ssl=False, timeout=timeout)
        client.starttls()
        return client
    return IMAPClient(host, port=port, ssl=True, timeout=timeout)


class LoginRejected(Exception):
    pass


FETCH_CHUNK = 25
FLAG_REFRESH_LIMIT = 1000


class MailService:
    def __init__(self, db: DB, vault: Vault, config: Config, oauth: MicrosoftOAuth | None = None):
        self.db = db
        self.vault = vault
        self.config = config
        self.oauth = oauth or MicrosoftOAuth()
        # Messages read in Beseder but not yet flagged on the server: account_id -> uids.
        self._pending_seen: dict[int, set[int]] = {}
        self._seen_lock = threading.Lock()

    # --- connection ---------------------------------------------------
    def _save_secret(self, account_id: int):
        def save(secret: dict) -> None:
            with self.db.conn() as c:
                c.execute("UPDATE accounts SET secret=? WHERE id=?", (self.vault.encrypt(secret), account_id))

        return save

    def connect(self, account) -> IMAPClient:
        secret = self.vault.decrypt(account["secret"])
        client = open_imap(account["host"], account["port"])
        try:
            if account["kind"] == "outlook":
                token = self.oauth.access_token(account["id"], secret, self._save_secret(account["id"]))
                client.oauth2_login(account["username"], token)
            else:
                client.login(account["username"], secret["password"])
        except Exception:
            try:
                client.shutdown()
            except Exception:
                pass
            raise
        return client

    @staticmethod
    def test_login(host: str, port: int, usernames: list[str], password: str) -> str:
        """Logs in with the first username that works and returns it."""
        for username in usernames:
            with open_imap(host, port, timeout=15) as client:
                try:
                    client.login(username, password)
                except LoginError:
                    continue
                client.select_folder("INBOX", readonly=True)
                return username
        raise LoginRejected()

    def get_account(self, account_id: int):
        with self.db.conn() as c:
            return c.execute("SELECT * FROM accounts WHERE id=?", (account_id,)).fetchone()

    # --- sync ---------------------------------------------------------
    def sync_account(self, account_id: int) -> int:
        """Imports new INBOX messages and refreshes flags. Returns the number of new messages."""
        account = self.get_account(account_id)
        if account is None:
            return 0
        try:
            with self.connect(account) as client:
                self._send_seen(client, account_id)
                new = self._sync_inbox(client, account)
            with self.db.conn() as c:
                c.execute("UPDATE accounts SET last_sync=?, last_error=NULL WHERE id=?", (now_iso(), account_id))
            return new
        except Exception as e:  # stored so the app can show it
            log.warning("Sync failed for account %s: %s", account_id, type(e).__name__)
            with self.db.conn() as c:
                c.execute("UPDATE accounts SET last_error=? WHERE id=?", (str(e)[:300], account_id))
            return 0

    def _sync_inbox(self, client: IMAPClient, account) -> int:
        info = client.select_folder("INBOX", readonly=True)
        uidvalidity = int(info.get(b"UIDVALIDITY", 0))
        last_uid = account["last_uid"]
        if account["uidvalidity"] is not None and account["uidvalidity"] != uidvalidity:
            # The mailbox was rebuilt on the server: the old UIDs mean nothing anymore.
            with self.db.conn() as c:
                c.execute("DELETE FROM messages WHERE account_id=?", (account["id"],))
            last_uid = 0

        if last_uid == 0:
            since = date.today() - timedelta(days=self.config.initial_days)
            uids = sorted(client.search(["SINCE", since]))[-self.config.initial_max :]
        else:
            uids = [u for u in client.search(["UID", f"{last_uid + 1}:*"]) if u > last_uid]
        uids.sort()

        new = 0
        for i in range(0, len(uids), FETCH_CHUNK):
            chunk = uids[i : i + FETCH_CHUNK]
            sizes = client.fetch(chunk, ["RFC822.SIZE"])
            small = [u for u in chunk if sizes.get(u, {}).get(b"RFC822.SIZE", 0) <= self.config.max_message_bytes]
            big = [u for u in chunk if u not in small]
            fetched = {}
            if small:
                fetched.update(client.fetch(small, ["BODY.PEEK[]", "FLAGS", "INTERNALDATE"]))
            if big:
                fetched.update(client.fetch(big, ["BODY.PEEK[HEADER]", "FLAGS", "INTERNALDATE"]))
            rows = []
            for uid in chunk:
                data = fetched.get(uid)
                if not data:
                    continue
                raw = data.get(b"BODY[]") or data.get(b"BODY[HEADER]") or b""
                internal = data.get(b"INTERNALDATE")
                if isinstance(internal, datetime) and internal.tzinfo is None:
                    internal = internal.replace(tzinfo=timezone.utc)
                p = parse_message(raw, fallback_date=internal, headers_only=uid in big)
                seen = int(b"\\Seen" in data.get(b"FLAGS", ()))
                rows.append(
                    (account["id"], uid, p.message_id, p.in_reply_to, p.refs, p.subject, p.from_name,
                     p.from_addr, p.reply_to, p.to_addrs, p.cc_addrs, p.date, p.snippet, p.body_text,
                     p.body_html, int(p.list_unsubscribe), int(p.truncated), seen)
                )
            with self.db.conn() as c:
                c.executemany(
                    "INSERT OR IGNORE INTO messages(account_id, uid, message_id, in_reply_to, refs, subject,"
                    " from_name, from_addr, reply_to, to_addrs, cc_addrs, date, snippet, body_text, body_html,"
                    " list_unsubscribe, truncated, seen) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    rows,
                )
                c.execute(
                    "UPDATE accounts SET uidvalidity=?, last_uid=MAX(last_uid, ?) WHERE id=?",
                    (uidvalidity, chunk[-1], account["id"]),
                )
            new += len(rows)

        with self.db.conn() as c:
            c.execute("UPDATE accounts SET uidvalidity=? WHERE id=?", (uidvalidity, account["id"]))
        self._refresh_flags(client, account["id"])
        return new

    def _refresh_flags(self, client: IMAPClient, account_id: int) -> None:
        """Read state changed on the phone, messages deleted elsewhere: catch up with the server."""
        with self.db.conn() as c:
            known = [
                r["uid"]
                for r in c.execute(
                    "SELECT uid FROM messages WHERE account_id=? ORDER BY uid DESC LIMIT ?",
                    (account_id, FLAG_REFRESH_LIMIT),
                )
            ]
        if not known:
            return
        flags = client.fetch(known, ["FLAGS"])
        with self._seen_lock:
            pending = set(self._pending_seen.get(account_id, ()))
        gone = [(account_id, uid) for uid in known if uid not in flags]
        # A message read in Beseder stays read even if the server hasn't heard about it yet.
        seen = [
            (int(uid in pending or b"\\Seen" in flags[uid].get(b"FLAGS", ())), account_id, uid)
            for uid in known if uid in flags
        ]
        with self.db.conn() as c:
            c.executemany("DELETE FROM messages WHERE account_id=? AND uid=?", gone)
            c.executemany("UPDATE messages SET seen=? WHERE account_id=? AND uid=?", seen)

    # --- allowed writes -----------------------------------------------
    def queue_seen(self, message_id: int) -> int | None:
        """Remembers that a message was read. flush_seen() tells the server. Returns the account id."""
        with self.db.conn() as c:
            m = c.execute("SELECT account_id, uid FROM messages WHERE id=?", (message_id,)).fetchone()
        if m is None:
            return None
        with self._seen_lock:
            self._pending_seen.setdefault(m["account_id"], set()).add(m["uid"])
        return m["account_id"]

    def _send_seen(self, client: IMAPClient, account_id: int) -> None:
        with self._seen_lock:
            uids = sorted(self._pending_seen.pop(account_id, ()))
        if not uids:
            return
        try:
            client.select_folder("INBOX")
            client.add_flags(uids, [b"\\Seen"])
        except Exception:
            with self._seen_lock:  # keep them for the next attempt (next read or next sync)
                self._pending_seen.setdefault(account_id, set()).update(uids)
            raise

    def flush_seen(self, account_id: int) -> None:
        """Marks every queued message of an account as read on the server, in one connection."""
        with self._seen_lock:
            if not self._pending_seen.get(account_id):
                return
        account = self.get_account(account_id)
        if account is None:
            return
        try:
            with self.connect(account) as client:
                self._send_seen(client, account_id)
        except (IMAPClientError, OSError, PermissionError) as e:
            log.warning("Could not mark messages as read, will retry at the next sync: %s", type(e).__name__)

    def save_draft(self, message_id: int, body: str) -> str:
        """Adds a reply to the account's Drafts folder. Sends nothing."""
        with self.db.conn() as c:
            m = c.execute("SELECT * FROM messages WHERE id=?", (message_id,)).fetchone()
        if m is None:
            raise LookupError("Message not found")
        account = self.get_account(m["account_id"])
        draft = build_reply(m, account["email"], body)
        with self.connect(account) as client:
            folder = client.find_special_folder(DRAFTS)
            if folder is None:
                names = {f[2] for f in client.list_folders()}
                folder = next((n for n in ("Drafts", "[Gmail]/Drafts", "Brouillons", "INBOX.Drafts") if n in names), None)
            if folder is None:
                raise LookupError("No Drafts folder found on this account")
            client.append(folder, draft.as_bytes(), flags=[b"\\Draft", b"\\Seen"])
        self.db.audit("draft_saved", f"message={message_id} folder={folder}")
        return folder


def reply_recipient(m) -> str:
    return m["reply_to"] or (f"{m['from_name']} <{m['from_addr']}>" if m["from_name"] else m["from_addr"])


def build_reply(m, from_email: str, body: str) -> EmailMessage:
    subject = m["subject"] or ""
    if not subject.lower().startswith(("re:", "re :")):
        subject = f"Re: {subject}"
    msg = EmailMessage()
    msg["From"] = from_email
    msg["To"] = reply_recipient(m)
    msg["Subject"] = subject
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain=from_email.split("@")[-1] or None)
    if m["message_id"]:
        msg["In-Reply-To"] = m["message_id"]
        msg["References"] = f"{m['refs']} {m['message_id']}".strip()
    msg.set_content(body)
    return msg
