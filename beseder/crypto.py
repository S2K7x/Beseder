"""Chiffrement des secrets au repos (mots de passe d'application, tokens, clés API)."""

import json
import os
from pathlib import Path

from cryptography.fernet import Fernet


class Vault:
    def __init__(self, key_path: Path):
        key_path.parent.mkdir(parents=True, exist_ok=True)
        if not key_path.exists():
            fd = os.open(key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "wb") as f:
                f.write(Fernet.generate_key())
        self._fernet = Fernet(key_path.read_bytes().strip())

    def encrypt(self, data: dict) -> bytes:
        return self._fernet.encrypt(json.dumps(data).encode())

    def decrypt(self, token: bytes) -> dict:
        return json.loads(self._fernet.decrypt(token))
