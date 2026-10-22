import asyncio
import json
import os

import httpx
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from beseder.db import now_iso
from beseder.push import PushService, b64u, encrypt, unb64u, vapid_header

from .conftest import add_account, add_message


def _hkdf(salt, ikm, info, n):
    return HKDF(hashes.SHA256(), n, salt, info).derive(ikm)


def browser():
    key = ec.generate_private_key(ec.SECP256R1())
    pub = key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    return key, pub, os.urandom(16)


def decrypt(data, key, pub, auth):
    """What the browser does (RFC 8291), written independently from beseder.push."""
    salt, rs, idlen = data[:16], int.from_bytes(data[16:20], "big"), data[20]
    sender_pub = data[21:21 + idlen]
    body = data[21 + idlen:]
    shared = key.exchange(ec.ECDH(), ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), sender_pub))
    ikm = _hkdf(auth, shared, b"WebPush: info\x00" + pub + sender_pub, 32)
    cek = _hkdf(salt, ikm, b"Content-Encoding: aes128gcm\x00", 16)
    nonce = _hkdf(salt, ikm, b"Content-Encoding: nonce\x00", 12)
    plain = AESGCM(cek).decrypt(nonce, body, None)
    assert rs == 4096 and plain.endswith(b"\x02")
    return plain[:-1]


def test_payload_is_readable_only_by_the_browser():
    key, pub, auth = browser()
    data = encrypt(b'{"title":"Claire"}', b64u(pub), b64u(auth))
    assert decrypt(data, key, pub, auth) == b'{"title":"Claire"}'
    assert b"Claire" not in data


def test_vapid_header_is_a_valid_es256_jwt():
    key = ec.generate_private_key(ec.SECP256R1())
    header = vapid_header("https://web.push.apple.com/QRx/abc", key, now=1_000)
    token, k = header.removeprefix("vapid t=").split(", k=")
    head, claims, sig = token.split(".")
    assert json.loads(unb64u(claims)) == {"aud": "https://web.push.apple.com", "exp": 1_000 + 12 * 3600,
                                          "sub": "https://github.com/S2K7x/Beseder"}
    raw = unb64u(sig)
    pub = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), unb64u(k))
    pub.verify(encode_dss_signature(int.from_bytes(raw[:32], "big"), int.from_bytes(raw[32:], "big")),
               f"{head}.{claims}".encode(), ec.ECDSA(hashes.SHA256()))


def subscription(endpoint):
    _key, pub, auth = browser()
    return {"endpoint": endpoint, "keys": {"p256dh": b64u(pub), "auth": b64u(auth)}}


def test_send_drops_devices_that_are_gone(core):
    calls = []

    def handler(request: httpx.Request):
        calls.append(request)
        return httpx.Response(410 if "gone" in str(request.url) else 201)

    push = PushService(core.db, core.vault, transport=httpx.MockTransport(handler))
    push.subscribe(subscription("https://push.example/ok"))
    push.subscribe(subscription("https://push.example/gone"))
    assert asyncio.run(push.send({"title": "x"})) == 1
    assert push.count() == 1
    req = calls[0]
    assert req.headers["content-encoding"] == "aes128gcm" and req.headers["authorization"].startswith("vapid t=")
    # The VAPID key survives a restart (stored encrypted).
    assert PushService(core.db, core.vault).public_key() == push.public_key()


def test_subscribe_rejects_bad_input(client):
    assert client.post("/api/push/subscribe", json={"subscription": {"endpoint": "http://plain/x",
                       "keys": {"p256dh": "a", "auth": "b"}}}).status_code == 400
    assert client.post("/api/push/subscribe", json={"subscription": {"endpoint": "https://x"}}).status_code == 400
    ok = client.post("/api/push/subscribe", json={"subscription": subscription("https://push.example/1")})
    assert ok.json()["devices"] == 1
    assert len(client.get("/api/push").json()["public_key"]) > 80
    assert client.put("/api/push/settings", json={"mode": "loud"}).status_code == 400


def notified(core):
    with core.db.conn() as c:
        return {r["id"]: r["notified"] for r in c.execute("SELECT id, notified FROM messages")}


def new_mail(core, acc, uid, **kw):
    mid = add_message(core, acc, uid, **kw)
    with core.db.conn() as c:
        c.execute("UPDATE messages SET notified=0, date=? WHERE id=?", (now_iso(), mid))
    return mid


def test_important_mode_waits_for_triage_then_announces(core, monkeypatch):
    sent = []

    async def fake_send(payload, urgency="normal"):
        sent.append(payload)
        return 1

    monkeypatch.setattr(core.push, "send", fake_send)
    monkeypatch.setattr(core.push, "count", lambda: 1)
    core.db.set_setting("auto_triage", True)
    acc = add_account(core)
    a = new_mail(core, acc, 1, from_name="Claire", subject="Viewing Thursday")
    b = new_mail(core, acc, 2, subject="Sale")
    assert asyncio.run(core.notify_new()) == 0  # not sorted yet: wait
    assert notified(core) == {a: 0, b: 0}
    with core.db.conn() as c:
        c.execute("UPDATE messages SET category='important' WHERE id=?", (a,))
        c.execute("UPDATE messages SET category='promotions' WHERE id=?", (b,))
    assert asyncio.run(core.notify_new()) == 1
    assert sent == [{"title": "Claire", "body": "Viewing Thursday", "url": f"/#/m/{a}", "tag": f"m{a}"}]
    assert notified(core) == {a: 1, b: 1}
    assert asyncio.run(core.notify_new()) == 0  # never twice


def test_all_mode_preview_off_and_seen_mail(core, monkeypatch):
    sent = []

    async def fake_send(payload, urgency="normal"):
        sent.append(payload)
        return 1

    monkeypatch.setattr(core.push, "send", fake_send)
    monkeypatch.setattr(core.push, "count", lambda: 1)
    core.set_push_settings("all", preview=False)
    acc = add_account(core)
    new_mail(core, acc, 1, subject="Secret plan")
    new_mail(core, acc, 2, seen=1)  # already read on the phone: no buzz
    assert asyncio.run(core.notify_new()) == 1
    assert "Secret" not in json.dumps(sent) and sent[0]["title"] == "New email"
    core.set_push_settings("off", preview=True)
    new_mail(core, acc, 3)
    assert asyncio.run(core.notify_new()) == 0


def test_first_import_is_never_announced(core, monkeypatch):
    from .test_imap import FakeIMAP, raw

    acc = add_account(core)
    monkeypatch.setattr(core.mail, "connect", lambda account: FakeIMAP({1: raw(1), 2: raw(2)}))
    core.mail.sync_account(acc)
    assert set(notified(core).values()) == {1}
