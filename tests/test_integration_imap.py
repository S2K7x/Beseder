"""End-to-end sync against a real IMAP server. Skipped unless BESEDER_TEST_IMAP is set.

Run a throwaway Dovecot (self-signed TLS, any user, password "qa-pass"):

    docker run -d --name qa-imap -e USER_PASSWORD=qa-pass -p 127.0.0.1:31993:31993 dovecot/dovecot
    BESEDER_TEST_IMAP=127.0.0.1:31993 python -m pytest -q tests/test_integration_imap.py
"""

import os
import ssl
import uuid
from email.message import EmailMessage
from functools import partial

import pytest
from fastapi.testclient import TestClient

import beseder.mail.imap as imap_mod
from beseder.config import Config
from beseder.main import create_app
from imapclient import IMAPClient

TARGET = os.environ.get("BESEDER_TEST_IMAP", "")
pytestmark = pytest.mark.skipif(not TARGET, reason="set BESEDER_TEST_IMAP=host:port to run")
PASSWORD = "qa-pass"


def _insecure_ctx():
    # Test server only: Dovecot's image uses a self-signed certificate.
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def server(user):
    host, port = TARGET.split(":")
    c = IMAPClient(host, port=int(port), ssl=True, ssl_context=_insecure_ctx())
    c.login(user, PASSWORD)
    return c


def mail(i, *, html=None, attachment=0, sender="Alice Martin <alice@example.com>", subject=None):
    m = EmailMessage()
    m["From"] = sender
    m["To"] = "sam@example.com"
    m["Subject"] = subject or f"Message {i}"
    m["Date"] = f"Tue, 20 Oct 2026 09:{i % 60:02d}:00 +0000"
    m["Message-ID"] = f"<qa-{i}@example.com>"
    m.set_content(f"Plain body {i}")
    if html:
        m.add_alternative(html, subtype="html")
    if attachment:
        m.add_attachment(b"x" * attachment, maintype="application", subtype="octet-stream", filename="big.bin")
    return m.as_bytes()


@pytest.fixture
def env(tmp_path, monkeypatch):
    host, port = TARGET.split(":")
    monkeypatch.setattr(imap_mod, "IMAPClient", partial(IMAPClient, ssl_context=_insecure_ctx()))
    user = f"qa-{uuid.uuid4().hex[:8]}@example.com"  # fresh mailbox per test
    config = Config(data_dir=tmp_path, run_scheduler=False, allowed_hosts=["testserver"],
                    initial_max=500, max_message_bytes=50_000)
    app = create_app(config)
    with TestClient(app, headers={"X-Beseder": "1"}) as client:
        r = client.post("/api/accounts", json={"kind": "imap", "email": user, "password": PASSWORD,
                                               "host": host, "port": int(port)})
        assert r.status_code == 200, r.text
        yield app.state.core, client, r.json()["id"], user


def inbox_rows(core):
    with core.db.conn() as c:
        return {r["uid"]: dict(r) for r in c.execute("SELECT * FROM messages")}


def test_full_sync_cycle(env):
    core, client, account_id, user = env
    s = server(user)
    s.append("INBOX", mail(1))
    s.append("INBOX", mail(2, html="<p>Hi <script>x()</script><img src='https://t.example/p.gif'></p>"), flags=[b"\\Seen"])
    s.append("INBOX", mail(3, attachment=200_000))
    s.append("INBOX", mail(4, sender="=?utf-8?q?Ren=C3=A9e_O=27Hara?= <renee@example.com>", subject="Café ☕"))
    for i in range(5, 41):
        s.append("INBOX", mail(i))

    assert core.mail.sync_account(account_id) == 40
    rows = inbox_rows(core)
    assert len(rows) == 40
    by_mid = {r["message_id"]: r for r in rows.values()}
    assert by_mid["<qa-2@example.com>"]["seen"] == 1
    assert "script" not in by_mid["<qa-2@example.com>"]["body_html"]
    assert by_mid["<qa-3@example.com>"]["truncated"] == 1       # above max_message_bytes: headers only
    assert by_mid["<qa-4@example.com>"]["from_name"] == "Renée O'Hara"
    assert by_mid["<qa-4@example.com>"]["subject"] == "Café ☕"
    assert core.mail.get_account(account_id)["last_error"] is None

    # Nothing new: no duplicates.
    assert core.mail.sync_account(account_id) == 0

    # New mail, a read on the phone and a deletion on the phone.
    s.select_folder("INBOX")
    s.append("INBOX", mail(41))
    uid1 = next(u for u, r in rows.items() if r["message_id"] == "<qa-1@example.com>")
    uid5 = next(u for u, r in rows.items() if r["message_id"] == "<qa-5@example.com>")
    s.add_flags([uid1], [b"\\Seen"])
    s.delete_messages([uid5])
    s.expunge()
    assert core.mail.sync_account(account_id) == 1
    rows = inbox_rows(core)
    assert rows[uid1]["seen"] == 1 and uid5 not in rows and len(rows) == 40

    # Opening a message in Beseder marks it read on the server, and only that.
    target = next(r for r in rows.values() if r["message_id"] == "<qa-6@example.com>")
    assert client.post(f"/api/messages/{target['id']}/read").status_code == 200
    core.mail.flush_seen(target["account_id"])
    s.select_folder("INBOX", readonly=True)
    assert b"\\Seen" in s.get_flags([target["uid"]])[target["uid"]]
    assert len(s.search("ALL")) == 40                          # Beseder deleted nothing

    # Saving a draft puts a threaded reply in Drafts, flagged as a draft.
    r = client.post(f"/api/messages/{target['id']}/draft/save", json={"body": "Sounds good."})
    assert r.status_code == 200 and r.json()["folder"] == "Drafts"
    s.select_folder("Drafts", readonly=True)
    (duid,) = s.search("ALL")
    data = s.fetch([duid], ["FLAGS", "BODY.PEEK[]"])[duid]
    assert b"\\Draft" in data[b"FLAGS"]
    raw = data[b"BODY[]"]
    assert b"In-Reply-To: <qa-6@example.com>" in raw and b"Subject: Re: Message 6" in raw
    s.logout()


def test_initial_import_is_capped(env, monkeypatch):
    core, _client, account_id, user = env
    s = server(user)
    for i in range(30):
        s.append("INBOX", mail(i))
    s.logout()
    monkeypatch.setattr(core.config, "initial_max", 10)
    with core.db.conn() as c:
        c.execute("DELETE FROM messages")
        c.execute("UPDATE accounts SET last_uid=0, uidvalidity=NULL")
    assert core.mail.sync_account(account_id) == 10
    assert sorted(inbox_rows(core)) == list(range(21, 31))   # the 10 most recent


def test_wrong_password_is_rejected(env):
    _core, client, _account_id, _user = env
    host, port = TARGET.split(":")
    r = client.post("/api/accounts", json={"kind": "imap", "email": "x@example.com", "password": "nope",
                                           "host": host, "port": int(port)})
    assert r.status_code == 400 and "Login rejected" in r.json()["detail"]
