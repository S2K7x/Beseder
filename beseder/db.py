"""SQLite storage. One connection per call: simple and safe with the sync threads."""

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS accounts (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    email TEXT NOT NULL,
    kind TEXT NOT NULL,              -- gmail | icloud | outlook | imap
    host TEXT NOT NULL,
    port INTEGER NOT NULL,
    username TEXT NOT NULL,
    secret BLOB NOT NULL,            -- encrypted (password or refresh token)
    uidvalidity INTEGER,
    last_uid INTEGER NOT NULL DEFAULT 0,
    last_sync TEXT,
    last_error TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY,
    account_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    uid INTEGER NOT NULL,
    message_id TEXT,
    in_reply_to TEXT,
    refs TEXT,
    subject TEXT NOT NULL DEFAULT '',
    from_name TEXT NOT NULL DEFAULT '',
    from_addr TEXT NOT NULL DEFAULT '',
    reply_to TEXT NOT NULL DEFAULT '',
    to_addrs TEXT NOT NULL DEFAULT '',
    cc_addrs TEXT NOT NULL DEFAULT '',
    date TEXT NOT NULL,
    snippet TEXT NOT NULL DEFAULT '',
    body_text TEXT NOT NULL DEFAULT '',
    body_html TEXT NOT NULL DEFAULT '',
    list_unsubscribe INTEGER NOT NULL DEFAULT 0,
    truncated INTEGER NOT NULL DEFAULT 0,
    seen INTEGER NOT NULL DEFAULT 0,
    category TEXT,
    category_source TEXT,            -- ai | rule | user
    UNIQUE(account_id, uid)
);
CREATE INDEX IF NOT EXISTS idx_messages_date ON messages(date DESC);
CREATE INDEX IF NOT EXISTS idx_messages_cat ON messages(category);

-- Per-sender rules, created when the user re-categorizes a message.
CREATE TABLE IF NOT EXISTS sender_rules (
    addr TEXT PRIMARY KEY,
    category TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- Log of AI actions and IMAP writes. Never any message content here.
CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY,
    ts TEXT NOT NULL,
    action TEXT NOT NULL,
    detail TEXT NOT NULL DEFAULT ''
);

-- File names and sizes only. The content is fetched from the server when downloaded.
CREATE TABLE IF NOT EXISTS attachments (
    message_id INTEGER NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
    idx INTEGER NOT NULL,
    filename TEXT NOT NULL,
    content_type TEXT NOT NULL,
    size INTEGER NOT NULL,
    PRIMARY KEY (message_id, idx)
);

-- Browsers that asked for notifications.
CREATE TABLE IF NOT EXISTS push_subscriptions (
    endpoint TEXT PRIMARY KEY,
    keys TEXT NOT NULL,
    label TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
"""

# Columns added after the first release: (table, column, definition).
MIGRATIONS = [
    # 1 = nothing to notify about (everything imported before notifications existed).
    ("messages", "notified", "INTEGER NOT NULL DEFAULT 1"),
    # Follow-ups: does it expect an answer from me (AI, NULL = unknown), did I answer, did I dismiss it.
    ("messages", "needs_reply", "INTEGER"),
    ("messages", "answered", "INTEGER NOT NULL DEFAULT 0"),
    ("messages", "followup_done", "INTEGER NOT NULL DEFAULT 0"),
    # One-tap unsubscribe (List-Unsubscribe and RFC 8058 List-Unsubscribe-Post headers).
    ("messages", "unsub_url", "TEXT NOT NULL DEFAULT ''"),
    ("messages", "unsub_mailto", "TEXT NOT NULL DEFAULT ''"),
    ("messages", "unsub_one_click", "INTEGER NOT NULL DEFAULT 0"),
    # Sent folder sync.
    ("accounts", "sent_folder", "TEXT"),
    ("accounts", "sent_uidvalidity", "INTEGER"),
    ("accounts", "sent_last_uid", "INTEGER NOT NULL DEFAULT 0"),
]

# Created after the migrations (they use the columns above).
LATE_SCHEMA = """
-- What the user sent (Sent folder): to know what was answered, and how the user writes.
CREATE TABLE IF NOT EXISTS sent_messages (
    id INTEGER PRIMARY KEY,
    account_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    uid INTEGER NOT NULL,
    message_id TEXT NOT NULL DEFAULT '',
    in_reply_to TEXT NOT NULL DEFAULT '',
    refs TEXT NOT NULL DEFAULT '',
    to_addr TEXT NOT NULL DEFAULT '',     -- first recipient, lower case
    to_name TEXT NOT NULL DEFAULT '',
    subject TEXT NOT NULL DEFAULT '',
    date TEXT NOT NULL,
    body_text TEXT NOT NULL DEFAULT '',   -- the user's own words, quoted text removed
    expects_reply INTEGER,                -- NULL = unknown
    done INTEGER NOT NULL DEFAULT 0,      -- dismissed from "Waiting for a reply"
    UNIQUE(account_id, uid)
);
CREATE INDEX IF NOT EXISTS idx_sent_date ON sent_messages(date DESC);
CREATE INDEX IF NOT EXISTS idx_sent_reply ON sent_messages(in_reply_to);

-- Message-IDs of every received message, kept after archiving, to see who answered what.
CREATE TABLE IF NOT EXISTS thread_index (
    message_id TEXT PRIMARY KEY,
    in_reply_to TEXT NOT NULL DEFAULT '',
    refs TEXT NOT NULL DEFAULT '',
    date TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_thread_reply ON thread_index(in_reply_to);
CREATE INDEX IF NOT EXISTS idx_thread_date ON thread_index(date);
CREATE INDEX IF NOT EXISTS idx_messages_from ON messages(from_addr, date);

-- Full-text search (accents ignored), kept in sync by triggers.
CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
    subject, from_name, from_addr, body_text,
    content='messages', content_rowid='id', tokenize='unicode61 remove_diacritics 2'
);
CREATE TRIGGER IF NOT EXISTS messages_fts_ai AFTER INSERT ON messages BEGIN
    INSERT INTO messages_fts(rowid, subject, from_name, from_addr, body_text)
    VALUES (new.id, new.subject, new.from_name, new.from_addr, new.body_text);
END;
CREATE TRIGGER IF NOT EXISTS messages_fts_ad AFTER DELETE ON messages BEGIN
    INSERT INTO messages_fts(messages_fts, rowid, subject, from_name, from_addr, body_text)
    VALUES ('delete', old.id, old.subject, old.from_name, old.from_addr, old.body_text);
END;
CREATE TRIGGER IF NOT EXISTS messages_fts_au AFTER UPDATE OF subject, from_name, from_addr, body_text ON messages BEGIN
    INSERT INTO messages_fts(messages_fts, rowid, subject, from_name, from_addr, body_text)
    VALUES ('delete', old.id, old.subject, old.from_name, old.from_addr, old.body_text);
    INSERT INTO messages_fts(rowid, subject, from_name, from_addr, body_text)
    VALUES (new.id, new.subject, new.from_name, new.from_addr, new.body_text);
END;
"""


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class DB:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.conn() as c:
            c.execute("PRAGMA journal_mode=WAL")
            c.executescript(SCHEMA)
            for table, column, definition in MIGRATIONS:
                existing = {r["name"] for r in c.execute(f"PRAGMA table_info({table})")}
                if column not in existing:
                    c.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
            c.executescript(LATE_SCHEMA)
            # One-time backfills for databases created before these tables existed.
            if not c.execute("SELECT 1 FROM settings WHERE key='fts_built'").fetchone():
                c.execute("INSERT INTO messages_fts(messages_fts) VALUES('rebuild')")
                c.execute("INSERT OR IGNORE INTO thread_index(message_id, in_reply_to, refs, date)"
                          " SELECT message_id, COALESCE(in_reply_to, ''), COALESCE(refs, ''), date FROM messages"
                          " WHERE message_id IS NOT NULL AND message_id != ''")
                c.execute("INSERT INTO settings(key, value) VALUES('fts_built', 'true')")

    @contextmanager
    def conn(self):
        c = sqlite3.connect(self.path, timeout=30)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA foreign_keys=ON")
        try:
            yield c
            c.commit()
        finally:
            c.close()

    # --- settings -------------------------------------------------------
    def get_setting(self, key: str, default=None):
        with self.conn() as c:
            row = c.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return json.loads(row["value"]) if row else default

    def set_setting(self, key: str, value) -> None:
        with self.conn() as c:
            c.execute(
                "INSERT INTO settings(key, value) VALUES(?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, json.dumps(value)),
            )

    def audit(self, action: str, detail: str = "") -> None:
        with self.conn() as c:
            c.execute("INSERT INTO audit_log(ts, action, detail) VALUES(?,?,?)", (now_iso(), action, detail))
