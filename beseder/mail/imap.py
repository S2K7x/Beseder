"""IMAP sync.

Allowed writes on the server (see CLAUDE.md), always on a user click: mark as read, add a
draft, move a message out of the inbox (archive or a folder the user picks, never the
trash). No sending, no deleting.
"""

import logging
import re
import threading
import time
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
from .parse import extract_attachment, parse_message, strip_quoted
from .threads import thread_key

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
QUICK_FLAG_REFRESH_LIMIT = 200  # syncs triggered by IDLE: recent mail only, the periodic sync does the rest
IDLE_RENEW = 25 * 60  # servers drop IDLE after ~29 minutes (RFC 2177)
ARCHIVE_NAMES = ("Archive", "Archives", "INBOX.Archive")
# Folders a user may move mail into. Trash is left out on purpose (no deleting); the others
# make no sense as a destination (Sent, Gmail's Starred/Important/All Mail views).
NOT_A_TARGET = {b"\\Noselect", b"\\NonExistent", b"\\Trash", b"\\Drafts", b"\\Sent",
                b"\\Flagged", b"\\Important", b"\\All"}
GMAIL = b"X-GM-EXT-1"
# Sent folder: read only, to know what was answered and how the user writes.
SENT_NAMES = ("Sent", "Sent Items", "Sent Messages", "Sent Mail", "INBOX.Sent", "Envoyés",
              "Éléments envoyés", "Messages envoyés")
SENT_INITIAL_DAYS = 30
SENT_INITIAL_MAX = 200
SENT_MAX_BYTES = 2 * 1024 * 1024
# Phrases that ask the other person for something, besides a question mark.
ASKS = re.compile(
    r"\?|\b(let me know|can you|could you|would you|please (send|confirm|reply)|get back to me|"
    r"dis-moi|tiens-moi au courant|peux-tu|pourrais-tu|pouvez-vous|pourriez-vous|merci de (me )?"
    r"(confirmer|répondre|renvoyer|transmettre)|j'attends ton retour|j'attends votre retour)\b",
    re.I,
)
OWN_WRITE_ECHO = 10  # seconds during which IDLE events caused by our own writes are ignored


class MailService:
    def __init__(self, db: DB, vault: Vault, config: Config, oauth: MicrosoftOAuth | None = None):
        self.db = db
        self.vault = vault
        self.config = config
        self.oauth = oauth or MicrosoftOAuth()
        # Messages read in Beseder but not yet flagged on the server: account_id -> uids.
        self._pending_seen: dict[int, set[int]] = {}
        self._seen_lock = threading.Lock()
        self._last_write: dict[int, float] = {}  # account_id -> monotonic time of our last write

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
    def sync_account(self, account_id: int, quick: bool = False) -> int:
        """Imports new INBOX messages and refreshes flags. Returns the number of new messages."""
        account = self.get_account(account_id)
        if account is None:
            return 0
        try:
            with self.connect(account) as client:
                self._send_seen(client, account_id)
                new = self._sync_inbox(client, account, quick)
                if not quick:
                    try:
                        self._sync_sent(client, account)
                    except Exception as e:  # never blocks the inbox
                        log.warning("Sent folder sync failed for account %s: %s", account_id, type(e).__name__)
            with self.db.conn() as c:
                c.execute("UPDATE accounts SET last_sync=?, last_error=NULL WHERE id=?", (now_iso(), account_id))
            return new
        except Exception as e:  # stored so the app can show it
            log.warning("Sync failed for account %s: %s", account_id, type(e).__name__)
            with self.db.conn() as c:
                c.execute("UPDATE accounts SET last_error=? WHERE id=?", (str(e)[:300], account_id))
            return 0

    def _sync_inbox(self, client: IMAPClient, account, quick: bool = False) -> int:
        info = client.select_folder("INBOX", readonly=True)
        uidvalidity = int(info.get(b"UIDVALIDITY", 0))
        last_uid = account["last_uid"]
        if account["uidvalidity"] is not None and account["uidvalidity"] != uidvalidity:
            # The mailbox was rebuilt on the server: the old UIDs mean nothing anymore.
            with self.db.conn() as c:
                c.execute("DELETE FROM messages WHERE account_id=?", (account["id"],))
            last_uid = 0

        initial = last_uid == 0  # first import: nothing to notify about
        if initial:
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
            rows, attachments, threads = [], {}, []
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
                     p.body_html, int(p.list_unsubscribe), int(p.truncated), seen, int(initial or seen),
                     p.unsub_url, p.unsub_mailto, int(p.unsub_one_click),
                     int(b"\\Answered" in data.get(b"FLAGS", ())))
                )
                threads.append((p.message_id, p.in_reply_to, p.refs, p.date, p.subject, p.from_addr))
                if p.attachments:
                    attachments[uid] = p.attachments
            with self.db.conn() as c:
                # One at a time: a reply in this batch joins the thread of a message just before it.
                for i, (mid, irt, refs, when, subject, addr) in enumerate(threads):
                    key = thread_key(c, mid, irt, refs, subject, addr)
                    rows[i] += (key,)
                    if mid:
                        c.execute("INSERT OR IGNORE INTO thread_index(message_id, in_reply_to, refs, date, thread_key)"
                                  " VALUES(?,?,?,?,?)", (mid, irt, refs, when, key))
                c.executemany(
                    "INSERT OR IGNORE INTO messages(account_id, uid, message_id, in_reply_to, refs, subject,"
                    " from_name, from_addr, reply_to, to_addrs, cc_addrs, date, snippet, body_text, body_html,"
                    " list_unsubscribe, truncated, seen, notified, unsub_url, unsub_mailto, unsub_one_click, answered,"
                    " thread_key) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    rows,
                )
                for uid, items in attachments.items():
                    mid = c.execute("SELECT id FROM messages WHERE account_id=? AND uid=?",
                                    (account["id"], uid)).fetchone()[0]
                    c.executemany(
                        "INSERT OR IGNORE INTO attachments(message_id, idx, filename, content_type, size)"
                        " VALUES(?,?,?,?,?)", [(mid, *item) for item in items],
                    )
                c.execute(
                    "UPDATE accounts SET uidvalidity=?, last_uid=MAX(last_uid, ?) WHERE id=?",
                    (uidvalidity, chunk[-1], account["id"]),
                )
            new += len(rows)

        with self.db.conn() as c:
            c.execute("UPDATE accounts SET uidvalidity=? WHERE id=?", (uidvalidity, account["id"]))
        self._refresh_flags(client, account["id"], QUICK_FLAG_REFRESH_LIMIT if quick else FLAG_REFRESH_LIMIT)
        return new

    def _refresh_flags(self, client: IMAPClient, account_id: int, limit: int = FLAG_REFRESH_LIMIT) -> None:
        """Read state changed on the phone, messages deleted elsewhere: catch up with the server."""
        with self.db.conn() as c:
            known = [
                r["uid"]
                for r in c.execute(
                    "SELECT uid FROM messages WHERE account_id=? ORDER BY uid DESC LIMIT ?",
                    (account_id, limit),
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
            (int(uid in pending or b"\\Seen" in flags[uid].get(b"FLAGS", ())),
             int(b"\\Answered" in flags[uid].get(b"FLAGS", ())), account_id, uid)
            for uid in known if uid in flags
        ]
        with self.db.conn() as c:
            c.executemany("DELETE FROM messages WHERE account_id=? AND uid=?", gone)
            c.executemany("UPDATE messages SET seen=?, answered=? WHERE account_id=? AND uid=?", seen)

    def _sent_folder(self, client: IMAPClient, account) -> str | None:
        if account["sent_folder"]:
            return account["sent_folder"]
        folders = client.list_folders()
        folder = self._flag_folder(folders, b"\\Sent")
        if folder is None:
            names = {name for _flags, _sep, name in folders}
            folder = next((n for n in SENT_NAMES if n in names or f"INBOX.{n}" in names), None)
            if folder and folder not in names:
                folder = f"INBOX.{folder}"
        if folder:
            with self.db.conn() as c:
                c.execute("UPDATE accounts SET sent_folder=? WHERE id=?", (folder, account["id"]))
        return folder

    def _sync_sent(self, client: IMAPClient, account) -> int:
        """Imports what the user sent (read only): who they wrote to, and in their own words."""
        folder = self._sent_folder(client, account)
        if folder is None:
            return 0
        try:
            info = client.select_folder(folder, readonly=True)
        except IMAPClientError:
            with self.db.conn() as c:  # renamed or deleted: look for it again next time
                c.execute("UPDATE accounts SET sent_folder=NULL WHERE id=?", (account["id"],))
            return 0
        uidvalidity = int(info.get(b"UIDVALIDITY", 0))
        last_uid = account["sent_last_uid"]
        if account["sent_uidvalidity"] is not None and account["sent_uidvalidity"] != uidvalidity:
            with self.db.conn() as c:
                c.execute("DELETE FROM sent_messages WHERE account_id=?", (account["id"],))
            last_uid = 0
        if last_uid == 0:
            since = date.today() - timedelta(days=SENT_INITIAL_DAYS)
            uids = sorted(client.search(["SINCE", since]))[-SENT_INITIAL_MAX:]
        else:
            uids = sorted(u for u in client.search(["UID", f"{last_uid + 1}:*"]) if u > last_uid)
        new = 0
        for i in range(0, len(uids), FETCH_CHUNK):
            chunk = uids[i : i + FETCH_CHUNK]
            sizes = client.fetch(chunk, ["RFC822.SIZE"])
            small = [u for u in chunk if sizes.get(u, {}).get(b"RFC822.SIZE", 0) <= SENT_MAX_BYTES]
            big = [u for u in chunk if u not in small]
            fetched = {}
            if small:
                fetched.update(client.fetch(small, ["BODY.PEEK[]", "INTERNALDATE"]))
            if big:
                fetched.update(client.fetch(big, ["BODY.PEEK[HEADER]", "INTERNALDATE"]))
            rows = []
            for uid in chunk:
                data = fetched.get(uid)
                if not data:
                    continue
                internal = data.get(b"INTERNALDATE")
                if isinstance(internal, datetime) and internal.tzinfo is None:
                    internal = internal.replace(tzinfo=timezone.utc)
                p = parse_message(data.get(b"BODY[]") or data.get(b"BODY[HEADER]") or b"",
                                  fallback_date=internal, headers_only=uid in big)
                own = "" if uid in big else strip_quoted(p.body_text)[:4000]
                rows.append((account["id"], uid, p.message_id, p.in_reply_to, p.refs, p.first_to[1],
                             p.first_to[0], p.subject, p.date, own, int(bool(ASKS.search(own)))))
            with self.db.conn() as c:
                for row in rows:
                    key = thread_key(c, row[2], row[3], row[4], row[7], row[5])
                    c.execute(
                        "INSERT OR IGNORE INTO sent_messages(account_id, uid, message_id, in_reply_to, refs, to_addr,"
                        " to_name, subject, date, body_text, expects_reply, thread_key) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                        (*row, key))
                c.execute("UPDATE accounts SET sent_uidvalidity=?, sent_last_uid=MAX(sent_last_uid, ?) WHERE id=?",
                          (uidvalidity, chunk[-1], account["id"]))
            new += len(rows)
        with self.db.conn() as c:
            c.execute("UPDATE accounts SET sent_uidvalidity=? WHERE id=?", (uidvalidity, account["id"]))
        return new

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
            self._last_write[account_id] = time.monotonic()
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

    def _message(self, message_id: int):
        with self.db.conn() as c:
            m = c.execute("SELECT * FROM messages WHERE id=?", (message_id,)).fetchone()
        if m is None:
            raise LookupError("Message not found")
        return m

    def load_full(self, message_id: int) -> None:
        """For a message too big to import at sync time: fetches it entirely, on request."""
        m = self._message(message_id)
        with self.connect(self.get_account(m["account_id"])) as client:
            client.select_folder("INBOX", readonly=True)
            data = client.fetch([m["uid"]], ["BODY.PEEK[]"]).get(m["uid"])
        if not data:
            raise LookupError("This message is no longer in the inbox")
        p = parse_message(data[b"BODY[]"])
        with self.db.conn() as c:
            c.execute("UPDATE messages SET body_text=?, body_html=?, snippet=?, truncated=0 WHERE id=?",
                      (p.body_text, p.body_html, p.snippet, message_id))
            c.executemany("INSERT OR IGNORE INTO attachments(message_id, idx, filename, content_type, size)"
                          " VALUES(?,?,?,?,?)", [(message_id, *a) for a in p.attachments])

    def download_attachment(self, message_id: int, idx: int) -> tuple[str, bytes]:
        """Fetches the message again from the server and returns one attachment."""
        m = self._message(message_id)
        with self.connect(self.get_account(m["account_id"])) as client:
            client.select_folder("INBOX", readonly=True)
            data = client.fetch([m["uid"]], ["BODY.PEEK[]"]).get(m["uid"])
        if not data:
            raise LookupError("This message is no longer in the inbox")
        return extract_attachment(data[b"BODY[]"], idx)

    @staticmethod
    def _flag_folder(folders, flag: bytes) -> str | None:
        return next((name for flags, _sep, name in folders if flag in flags), None)

    @staticmethod
    def _archive_folder(folders) -> str | None:
        by_flag = {flag: name for flags, _sep, name in folders for flag in flags}
        # \Archive (iCloud, Outlook, Yahoo...), or \All for Gmail where archiving = leaving the inbox.
        for flag in (b"\\Archive", b"\\All"):
            if flag in by_flag:
                return by_flag[flag]
        names = {name for _flags, _sep, name in folders}
        return next((n for n in ARCHIVE_NAMES if n in names), None)

    def folders(self, account_id: int) -> dict:
        """Folders the user can move mail into, and which one is the archive."""
        with self.connect(self.get_account(account_id)) as client:
            folders = client.list_folders()
        targets = sorted(
            name for flags, _sep, name in folders
            if name.upper() != "INBOX" and not (set(flags) & NOT_A_TARGET)
        )
        return {"archive": self._archive_folder(folders), "folders": targets}

    def move(self, message_id: int, target: str | None) -> dict:
        """Moves a conversation out of the inbox (target=None means the archive): the message
        and the rest of its thread in the same mailbox. Never to the trash."""
        m = self._message(message_id)
        ids = [message_id]
        if m["thread_key"]:
            with self.db.conn() as c:
                ids += [r[0] for r in c.execute("SELECT id FROM messages WHERE account_id=? AND thread_key=? AND id!=?",
                                                (m["account_id"], m["thread_key"], message_id))]
        r = self.move_many(m["account_id"], ids, target)
        return {"folder": r["folder"], "account_id": r["account_id"], "message_id": m["message_id"] or "",
                "message_ids": r["message_ids"]}

    def move_many(self, account_id: int, message_ids: list[int], target: str | None) -> dict:
        """Moves messages of one account out of the inbox, in one connection. Never to the trash.
        Returns the folder and the Message-IDs, for Undo."""
        with self.db.conn() as c:
            rows = c.execute(
                f"SELECT id, uid, message_id FROM messages WHERE account_id=? AND id IN ({','.join('?' * len(message_ids))})",
                (account_id, *message_ids)).fetchall()
        if not rows:
            raise LookupError("Message not found")
        uids = [r["uid"] for r in rows]
        account = self.get_account(account_id)
        with self.connect(account) as client:
            folders = client.list_folders()
            if target is None and client.has_capability(GMAIL):
                # Gmail's own archive: remove the Inbox label. Works even if "All Mail" is hidden
                # from IMAP; Undo needs All Mail to find the message again.
                client.select_folder("INBOX")
                client.remove_gmail_labels(uids, ["\\Inbox"])
                target = self._flag_folder(folders, b"\\All") or ""
            else:
                if target is None:
                    target = self._archive_folder(folders)
                    if target is None:
                        client.create_folder("Archive")
                        target = "Archive"
                else:
                    flags = next((set(f) for f, _sep, name in folders if name == target), None)
                    if flags is None or flags & NOT_A_TARGET or target.upper() == "INBOX":
                        raise ValueError("You can't move mail to this folder")
                if not client.has_capability("MOVE"):
                    raise ValueError("This mail server can't move messages")
                client.select_folder("INBOX")
                client.move(uids, target)
            self._last_write[account_id] = time.monotonic()
        with self.db.conn() as c:
            c.executemany("DELETE FROM messages WHERE id=?", [(r["id"],) for r in rows])
        self.db.audit("moved", f"account={account_id} count={len(rows)} folder={target}")
        return {"folder": target, "account_id": account_id,
                "message_ids": [r["message_id"] for r in rows if r["message_id"]]}

    def restore(self, account_id: int, folder: str, message_id_headers: list[str]) -> int:
        """Undo a move: finds the messages by Message-ID and puts them back in the inbox.
        Returns how many were found."""
        wanted = [m for m in message_id_headers if m][:500]
        if not wanted or not folder:
            return 0
        with self.connect(self.get_account(account_id)) as client:
            folders = client.list_folders()
            client.select_folder(folder)
            uids = []
            for mid in wanted:
                found = client.search(["HEADER", "Message-ID", mid])
                uids += found[-1:]
            if not uids:
                return 0
            if client.has_capability(GMAIL) and folder == self._flag_folder(folders, b"\\All"):
                client.add_gmail_labels(uids, ["\\Inbox"])  # undo Gmail's archive
            else:
                client.move(uids, "INBOX")
            self._last_write[account_id] = time.monotonic()
        self.db.audit("restored", f"account={account_id} count={len(uids)} folder={folder}")
        return len(uids)

    # --- push from the server (IDLE) --------------------------------------
    def watch_inbox(self, account_id: int, on_new, stop: threading.Event) -> None:
        """Waits on the server for new mail (IMAP IDLE) and calls on_new() as soon as some arrives.
        Runs in its own thread; reconnects with backoff. Returns if the server has no IDLE."""
        backoff = 30
        while not stop.is_set():
            account = self.get_account(account_id)
            if account is None:
                return
            try:
                with self.connect(account) as client:
                    if not client.has_capability("IDLE"):
                        log.info("Account %s has no IMAP IDLE, using periodic sync only", account_id)
                        return
                    client.select_folder("INBOX", readonly=True)
                    backoff = 30
                    started = time.monotonic()
                    client.idle()
                    while not stop.is_set() and time.monotonic() - started < IDLE_RENEW:
                        responses = client.idle_check(timeout=30)
                        events = {r[1] for r in responses if len(r) > 1}
                        # New mail (EXISTS), or a message read or deleted elsewhere (FETCH, EXPUNGE).
                        # FETCH/EXPUNGE right after our own write are just its echo: skip them.
                        ours = time.monotonic() - self._last_write.get(account_id, -1e9) < OWN_WRITE_ECHO
                        if b"EXISTS" in events or (events & {b"EXPUNGE", b"FETCH"} and not ours):
                            client.idle_done()
                            on_new()
                            client.idle()
                    client.idle_done()
            except Exception as e:  # network drop, expired token... try again later
                log.info("IDLE for account %s stopped (%s), retrying in %ss", account_id, type(e).__name__, backoff)
                if stop.wait(backoff):
                    return
                backoff = min(backoff * 2, 600)

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
