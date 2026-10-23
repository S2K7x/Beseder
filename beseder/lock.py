"""Optional app lock: a passcode, then a session cookie per device.

Tailscale already keeps strangers out; the lock is for the people and devices inside your
own network (a shared computer, a phone left unlocked). The passcode is stored as a scrypt
hash, sessions as SHA-256 hashes of random tokens, and wrong guesses slow down quickly.
"""

import hashlib
import hmac
import secrets
import time

from .db import DB, now_iso

COOKIE = "beseder_session"
SESSION_DAYS = 30
MIN_LENGTH = 4
FREE_ATTEMPTS = 5
MAX_WAIT = 15 * 60  # seconds

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY,
    label TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    last_seen REAL NOT NULL
);
"""


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def hash_passcode(passcode: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.scrypt(passcode.encode(), salt=salt, n=2**14, r=8, p=1, dklen=32)
    return f"scrypt${salt.hex()}${digest.hex()}"


def check_passcode(passcode: str, stored: str) -> bool:
    try:
        _algo, salt, digest = stored.split("$")
        expected = hash_passcode(passcode, bytes.fromhex(salt)).split("$")[2]
    except ValueError:
        return False
    return hmac.compare_digest(expected, digest)


class Lock:
    def __init__(self, db: DB):
        self.db = db
        with db.conn() as c:
            c.executescript(SCHEMA)
        self._failures = 0
        self._blocked_until = 0.0

    @property
    def enabled(self) -> bool:
        return bool(self.db.get_setting("lock_hash"))

    def wait_seconds(self) -> int:
        return max(0, int(self._blocked_until - time.monotonic() + 0.999))

    def valid(self, token: str | None) -> bool:
        if not token:
            return False
        with self.db.conn() as c:
            row = c.execute("SELECT last_seen FROM sessions WHERE token_hash=?", (_hash_token(token),)).fetchone()
            if row is None or time.time() - row["last_seen"] > SESSION_DAYS * 86400:
                return False
            if time.time() - row["last_seen"] > 3600:  # sliding expiry, written at most hourly
                c.execute("UPDATE sessions SET last_seen=? WHERE token_hash=?", (time.time(), _hash_token(token)))
        return True

    def new_session(self, label: str = "") -> str:
        token = secrets.token_urlsafe(32)
        with self.db.conn() as c:
            c.execute("DELETE FROM sessions WHERE last_seen<?", (time.time() - SESSION_DAYS * 86400,))
            c.execute("INSERT INTO sessions(token_hash, label, created_at, last_seen) VALUES(?,?,?,?)",
                      (_hash_token(token), label[:60], now_iso(), time.time()))
        return token

    def end_session(self, token: str | None) -> None:
        if token:
            with self.db.conn() as c:
                c.execute("DELETE FROM sessions WHERE token_hash=?", (_hash_token(token),))

    def unlock(self, passcode: str, label: str = "") -> str:
        """Returns a new session token. Raises PermissionError (wrong) or TimeoutError (wait)."""
        if self.wait_seconds():
            raise TimeoutError(self.wait_seconds())
        if not check_passcode(passcode, self.db.get_setting("lock_hash") or ""):
            self._failures += 1
            if self._failures >= FREE_ATTEMPTS:
                self._blocked_until = time.monotonic() + min(MAX_WAIT, 30 * 2 ** (self._failures - FREE_ATTEMPTS))
            self.db.audit("unlock_failed", f"attempt={self._failures}")
            raise PermissionError("Wrong passcode")
        self._failures = 0
        self.db.audit("unlocked", label[:60])
        return self.new_session(label)

    def set_passcode(self, current: str, new: str, label: str = "") -> str | None:
        """Sets, changes or (new="") removes the passcode. Other devices are signed out.
        Returns a session for this device when the lock is on."""
        if self.enabled and not check_passcode(current, self.db.get_setting("lock_hash")):
            raise PermissionError("The current passcode is wrong")
        if new and len(new) < MIN_LENGTH:
            raise ValueError(f"Use at least {MIN_LENGTH} characters")
        self.db.set_setting("lock_hash", hash_passcode(new) if new else None)
        with self.db.conn() as c:
            c.execute("DELETE FROM sessions")
        self.db.audit("lock_changed", "on" if new else "off")
        return self.new_session(label) if new else None
