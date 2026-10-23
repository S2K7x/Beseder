"""Encrypted backups: the database and the encryption key, sealed with a passphrase.

A backup holds everything (passwords and tokens are inside, still encrypted with
secret.key, which is in the backup too), so the whole file is encrypted with a key derived
from the passphrase (scrypt) and authenticated (Fernet). Without the passphrase it is noise.

Restore, with Beseder stopped:  python -m beseder restore beseder-backup.besb
"""

import base64
import hashlib
import io
import os
import sqlite3
import tempfile
import zipfile
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

MAGIC = b"BESEDER1"
MIN_PASSPHRASE = 8


def _fernet(passphrase: str, salt: bytes) -> Fernet:
    key = hashlib.scrypt(passphrase.encode(), salt=salt, n=2**15, r=8, p=1, maxmem=64 * 1024 * 1024, dklen=32)
    return Fernet(base64.urlsafe_b64encode(key))


def create(db_path: Path, key_path: Path, passphrase: str) -> bytes:
    if len(passphrase) < MIN_PASSPHRASE:
        raise ValueError(f"Use a passphrase of at least {MIN_PASSPHRASE} characters")
    with tempfile.TemporaryDirectory() as tmp:
        copy = Path(tmp) / "beseder.db"
        # SQLite's own backup: a consistent copy even while syncs are writing.
        src, dst = sqlite3.connect(db_path), sqlite3.connect(copy)
        with dst:
            src.backup(dst)
        src.close()
        dst.close()
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            z.write(copy, "beseder.db")
            z.write(key_path, "secret.key")
    salt = os.urandom(16)
    return MAGIC + salt + _fernet(passphrase, salt).encrypt(buf.getvalue())


def restore(data: bytes, passphrase: str, data_dir: Path) -> None:
    """Replaces the database and key in data_dir. Beseder must be stopped."""
    if not data.startswith(MAGIC):
        raise ValueError("This is not a Beseder backup")
    salt, token = data[len(MAGIC):len(MAGIC) + 16], data[len(MAGIC) + 16:]
    try:
        payload = _fernet(passphrase, salt).decrypt(token)
    except InvalidToken:
        raise ValueError("Wrong passphrase, or the file is damaged")
    with zipfile.ZipFile(io.BytesIO(payload)) as z:
        names = set(z.namelist())
        if names != {"beseder.db", "secret.key"}:
            raise ValueError("This backup is incomplete")
        db, key = z.read("beseder.db"), z.read("secret.key")
    with tempfile.NamedTemporaryFile(suffix=".db") as check:
        check.write(db)
        check.flush()
        tables = {r[0] for r in sqlite3.connect(check.name).execute("SELECT name FROM sqlite_master")}
    if not {"accounts", "messages", "settings"} <= tables:
        raise ValueError("This backup doesn't contain a Beseder database")
    data_dir.mkdir(parents=True, exist_ok=True)
    for leftover in ("beseder.db-wal", "beseder.db-shm"):
        (data_dir / leftover).unlink(missing_ok=True)
    (data_dir / "beseder.db").write_bytes(db)
    key_file = data_dir / "secret.key"
    key_file.write_bytes(key)
    key_file.chmod(0o600)
