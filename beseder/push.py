"""Web Push notifications (RFC 8030), signed with VAPID (RFC 8292), payload encrypted
end to end with aes128gcm (RFC 8291). Only `cryptography` and `httpx`: no extra dependency.

Apple, Google or Mozilla relay the notification but cannot read it: it is encrypted for the
browser that subscribed.
"""

import base64
import json
import logging
import os
import time
from urllib.parse import urlparse

import httpx
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from .crypto import Vault
from .db import DB, now_iso

log = logging.getLogger(__name__)

# Who to contact about these pushes (required by Apple). A public URL is accepted.
VAPID_SUBJECT = "https://github.com/S2K7x/Beseder"
RECORD_SIZE = 4096
MODES = ("important", "all", "off")


def b64u(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def unb64u(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _hkdf(salt: bytes, ikm: bytes, info: bytes, length: int) -> bytes:
    return HKDF(hashes.SHA256(), length, salt, info).derive(ikm)


def _raw_public(key: ec.EllipticCurvePrivateKey) -> bytes:
    return key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)


def encrypt(payload: bytes, p256dh: str, auth: str, *, salt: bytes | None = None,
            sender: ec.EllipticCurvePrivateKey | None = None) -> bytes:
    """RFC 8291: encrypts a payload for one browser subscription (single aes128gcm record)."""
    if len(payload) > RECORD_SIZE - 17:
        raise ValueError("payload too large")
    receiver_public = unb64u(p256dh)
    receiver = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), receiver_public)
    sender = sender or ec.generate_private_key(ec.SECP256R1())
    sender_public = _raw_public(sender)
    shared = sender.exchange(ec.ECDH(), receiver)
    ikm = _hkdf(unb64u(auth), shared, b"WebPush: info\x00" + receiver_public + sender_public, 32)
    salt = salt or os.urandom(16)
    cek = _hkdf(salt, ikm, b"Content-Encoding: aes128gcm\x00", 16)
    nonce = _hkdf(salt, ikm, b"Content-Encoding: nonce\x00", 12)
    ciphertext = AESGCM(cek).encrypt(nonce, payload + b"\x02", None)  # \x02 = last record
    header = salt + RECORD_SIZE.to_bytes(4, "big") + bytes([len(sender_public)]) + sender_public
    return header + ciphertext


def vapid_header(endpoint: str, key: ec.EllipticCurvePrivateKey, now: float | None = None) -> str:
    """RFC 8292: a short-lived ES256 JWT for the push service that owns the endpoint."""
    url = urlparse(endpoint)
    claims = {"aud": f"{url.scheme}://{url.netloc}", "exp": int((now or time.time()) + 12 * 3600), "sub": VAPID_SUBJECT}
    signing_input = (b64u(json.dumps({"typ": "JWT", "alg": "ES256"}, separators=(",", ":")).encode()) + "."
                     + b64u(json.dumps(claims, separators=(",", ":")).encode()))
    r, s = decode_dss_signature(key.sign(signing_input.encode(), ec.ECDSA(hashes.SHA256())))
    token = signing_input + "." + b64u(r.to_bytes(32, "big") + s.to_bytes(32, "big"))
    return f"vapid t={token}, k={b64u(_raw_public(key))}"


class PushService:
    def __init__(self, db: DB, vault: Vault, transport: httpx.AsyncBaseTransport | None = None):
        self.db = db
        self.vault = vault
        self._transport = transport
        self._key: ec.EllipticCurvePrivateKey | None = None

    def _vapid_key(self) -> ec.EllipticCurvePrivateKey:
        if self._key is None:
            stored = self.db.get_setting("vapid_key")
            if stored:
                pem = self.vault.decrypt(stored.encode())["pem"].encode()
                self._key = serialization.load_pem_private_key(pem, None)
            else:
                self._key = ec.generate_private_key(ec.SECP256R1())
                pem = self._key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                              serialization.NoEncryption()).decode()
                self.db.set_setting("vapid_key", self.vault.encrypt({"pem": pem}).decode())
        return self._key

    def public_key(self) -> str:
        return b64u(_raw_public(self._vapid_key()))

    # --- subscriptions ---------------------------------------------------
    def subscribe(self, sub: dict, label: str = "") -> None:
        endpoint = sub["endpoint"]
        if urlparse(endpoint).scheme != "https":
            raise ValueError("Push endpoint must be https")
        keys = {"p256dh": sub["keys"]["p256dh"], "auth": sub["keys"]["auth"]}
        unb64u(keys["p256dh"]), unb64u(keys["auth"])  # rejects garbage early
        with self.db.conn() as c:
            c.execute(
                "INSERT INTO push_subscriptions(endpoint, keys, label, created_at) VALUES(?,?,?,?)"
                " ON CONFLICT(endpoint) DO UPDATE SET keys=excluded.keys, label=excluded.label",
                (endpoint, json.dumps(keys), label[:80], now_iso()),
            )

    def unsubscribe(self, endpoint: str) -> None:
        with self.db.conn() as c:
            c.execute("DELETE FROM push_subscriptions WHERE endpoint=?", (endpoint,))

    def count(self) -> int:
        with self.db.conn() as c:
            return c.execute("SELECT COUNT(*) FROM push_subscriptions").fetchone()[0]

    # --- sending ------------------------------------------------------------
    async def send(self, payload: dict, urgency: str = "normal") -> int:
        """Sends to every subscribed device. Returns how many accepted it."""
        with self.db.conn() as c:
            subs = [(r["endpoint"], json.loads(r["keys"])) for r in c.execute("SELECT * FROM push_subscriptions")]
        if not subs:
            return 0
        body = json.dumps(payload, ensure_ascii=False).encode()
        key = self._vapid_key()
        sent, gone = 0, []
        async with httpx.AsyncClient(timeout=15, transport=self._transport) as http:
            for endpoint, keys in subs:
                try:
                    r = await http.post(endpoint, content=encrypt(body, keys["p256dh"], keys["auth"]), headers={
                        "Authorization": vapid_header(endpoint, key),
                        "Content-Encoding": "aes128gcm",
                        "Content-Type": "application/octet-stream",
                        "TTL": "86400",
                        "Urgency": urgency,
                    })
                except httpx.HTTPError as e:
                    log.warning("Push failed: %s", type(e).__name__)
                    continue
                if r.status_code in (404, 410):  # the browser unsubscribed or the app was removed
                    gone.append(endpoint)
                elif r.status_code < 300:
                    sent += 1
                else:
                    log.warning("Push refused with status %s", r.status_code)
        for endpoint in gone:
            self.unsubscribe(endpoint)
        return sent
