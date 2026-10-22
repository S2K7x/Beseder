"""End-to-end sync against a real IMAP server. Skipped unless BESEDER_TEST_IMAP is set.

Run a throwaway Dovecot (self-signed TLS, any user, password "qa-pass"):

    docker run -d --name qa-imap -e USER_PASSWORD=qa-pass -p 127.0.0.1:31993:31993 dovecot/dovecot
    BESEDER_TEST_IMAP=127.0.0.1:31993 python -m pytest -q tests/test_integration_imap.py
"""

import os
import ssl
import time
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


def test_attachments_archive_undo_and_folders(env):
    core, client, account_id, user = env
    s = server(user)
    with_file = mail(1)
    m = EmailMessage()
    m["From"], m["Subject"], m["Message-ID"] = "Bob <bob@example.com>", "Invoice", "<qa-att@example.com>"
    m.set_content("See attached")
    m.add_attachment(b"%PDF-1.4 fake", maintype="application", subtype="pdf", filename="facture été.pdf")
    s.append("INBOX", m.as_bytes())
    s.append("INBOX", with_file)
    assert core.mail.sync_account(account_id) == 2
    rows = {r["message_id"]: r for r in inbox_rows(core).values()}
    inv = rows["<qa-att@example.com>"]

    # Attachment listed, then downloaded as a file (never rendered).
    meta = client.get(f"/api/messages/{inv['id']}").json()["attachments"]
    assert meta == [{"idx": 0, "filename": "facture été.pdf", "content_type": "application/pdf", "size": 13}]
    r = client.get(f"/api/messages/{inv['id']}/attachments/0")
    assert r.status_code == 200 and r.content == b"%PDF-1.4 fake"
    assert r.headers["content-type"] == "application/octet-stream"
    assert r.headers["content-disposition"].startswith("attachment;")

    # Folders: the trash and drafts are never offered.
    folders = client.get(f"/api/accounts/{account_id}/folders").json()
    assert "Junk" in folders["folders"] and "Trash" not in folders["folders"] and "Drafts" not in folders["folders"]

    # Archive (the server has none yet: Beseder creates "Archive"), then undo.
    r = client.post(f"/api/messages/{inv['id']}/move", json={"folder": None}).json()
    assert r["folder"] == "Archive" and r["message_id"] == "<qa-att@example.com>"
    s.select_folder("INBOX", readonly=True)
    assert len(s.search("ALL")) == 1
    s.select_folder("Archive", readonly=True)
    assert len(s.search("ALL")) == 1
    assert client.post(f"/api/accounts/{account_id}/restore",
                       json={"folder": "Archive", "message_id": r["message_id"]}).status_code == 200
    s.select_folder("INBOX", readonly=True)
    assert len(s.search("ALL")) == 2

    # Moving to the trash is refused; to Junk it works.
    other = rows["<qa-1@example.com>"]
    assert client.post(f"/api/messages/{other['id']}/move", json={"folder": "Trash"}).status_code == 400
    assert client.post(f"/api/messages/{other['id']}/move", json={"folder": "Junk"}).json()["folder"] == "Junk"
    s.logout()


def test_idle_announces_new_mail(env):
    import threading
    import time

    core, _client, account_id, user = env
    arrived, stop = threading.Event(), threading.Event()
    t = threading.Thread(target=core.mail.watch_inbox, args=(account_id, arrived.set, stop), daemon=True)
    t.start()
    time.sleep(2)  # let it enter IDLE
    s = server(user)
    started = time.monotonic()
    s.append("INBOX", mail(77))
    assert arrived.wait(15), "IDLE did not report the new message"
    print(f"IDLE reported new mail after {time.monotonic() - started:.1f}s")
    stop.set()
    s.logout()


def test_big_message_can_be_loaded_in_full(env):
    core, client, account_id, user = env
    s = server(user)
    m = EmailMessage()
    m["From"], m["Subject"], m["Message-ID"] = "Bob <bob@example.com>", "Big scan", "<qa-big@example.com>"
    m.set_content("Here is the scan")
    m.add_attachment(b"x" * 80_000, maintype="application", subtype="pdf", filename="scan/2026.pdf")
    s.append("INBOX", m.as_bytes())
    s.logout()
    core.mail.sync_account(account_id)
    (row,) = inbox_rows(core).values()
    assert row["truncated"] == 1 and client.get(f"/api/messages/{row['id']}").json()["attachments"] == []
    assert client.post(f"/api/messages/{row['id']}/load-full").status_code == 200
    full = client.get(f"/api/messages/{row['id']}").json()
    assert full["truncated"] == 0 and "Here is the scan" in full["body_text"]
    assert full["attachments"][0]["filename"] == "scan/2026.pdf"
    r = client.get(f"/api/messages/{row['id']}/attachments/0")
    assert len(r.content) == 80_000 and "scan%2F2026.pdf" in r.headers["content-disposition"]


def test_idle_ignores_the_echo_of_our_own_writes(env):
    import threading

    core, _client, account_id, user = env
    s = server(user)
    s.append("INBOX", mail(1))
    s.append("INBOX", mail(2))
    core.mail.sync_account(account_id)
    rows = sorted(inbox_rows(core).values(), key=lambda r: r["uid"])
    fired, stop = threading.Event(), threading.Event()
    threading.Thread(target=core.mail.watch_inbox, args=(account_id, fired.set, stop), daemon=True).start()
    time.sleep(2)
    core.mail.queue_seen(rows[0]["id"])
    core.mail.flush_seen(account_id)          # our own write: its FETCH echo must not trigger a sync
    assert not fired.wait(4)
    core.mail._last_write.clear()
    s.select_folder("INBOX")
    s.add_flags([rows[1]["uid"]], [b"\\Seen"])  # read on another device: must trigger
    assert fired.wait(10)
    stop.set()
    s.logout()


def test_sent_folder_feeds_follow_ups(env):
    core, client, account_id, user = env
    s = server(user)
    question = mail(1, sender="Bob <bob@example.com>", subject="Contract")
    s.append("INBOX", question)
    s.append("INBOX", mail(2, sender="Carol <carol@example.com>", subject="Lunch?"))
    sent_folder = next(name for flags, _sep, name in s.list_folders() if b"\\Sent" in flags)
    reply = EmailMessage()
    reply["From"], reply["To"], reply["Subject"] = user, "Bob <bob@example.com>", "Re: Contract"
    reply["Message-ID"], reply["In-Reply-To"] = "<me-1@example.com>", "<qa-1@example.com>"
    reply["Date"] = "Tue, 20 Oct 2026 10:00:00 +0000"
    reply.set_content("Signed, see attached.\n\nOn Tue, Bob <bob@example.com> wrote:\n> please sign")
    s.append(sent_folder, reply.as_bytes())
    s.logout()

    core.mail.sync_account(account_id)
    with core.db.conn() as c:
        (row,) = c.execute("SELECT * FROM sent_messages").fetchall()
        c.execute("UPDATE messages SET needs_reply=1, category='important', date=?", (time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime()),))
    assert row["to_addr"] == "bob@example.com" and row["body_text"] == "Signed, see attached."
    assert core.mail.get_account(account_id)["sent_folder"] == sent_folder
    # Bob's mail was answered from the phone: only Carol's is left to reply to.
    assert [m["subject"] for m in client.get("/api/followups").json()["to_reply"]] == ["Lunch?"]
    # The Sent folder is only read.
    s = server(user)
    s.select_folder(sent_folder, readonly=True)
    assert len(s.search("ALL")) == 1
    s.logout()


def test_bulk_archive_and_undo_on_a_real_server(env):
    core, client, account_id, user = env
    s = server(user)
    for i in range(3):
        s.append("INBOX", mail(i, sender="News <news@shop.com>"))
    s.append("INBOX", mail(9))
    core.mail.sync_account(account_id)
    r = client.post("/api/senders/archive", json={"addr": "news@shop.com"}).json()
    assert r["count"] == 3
    s.select_folder("INBOX", readonly=True)
    assert len(s.search("ALL")) == 1
    moved = r["moved"][0]
    assert client.post(f"/api/accounts/{account_id}/restore",
                       json={"folder": moved["folder"], "message_ids": moved["message_ids"]}).json()["restored"] == 3
    s.select_folder("INBOX", readonly=True)
    assert len(s.search("ALL")) == 4
    s.logout()


def test_conversation_is_grouped_and_archived_together(env):
    core, client, account_id, user = env
    s = server(user)
    s.append("INBOX", mail(1, subject="Trip"))
    reply = EmailMessage()
    reply["From"], reply["Subject"], reply["Message-ID"] = "Bob <bob@example.com>", "Re: Trip", "<qa-reply@example.com>"
    reply["In-Reply-To"] = reply["References"] = "<qa-1@example.com>"
    reply["Date"] = "Tue, 20 Oct 2026 10:30:00 +0000"
    reply.set_content("I'm in")
    s.append("INBOX", reply.as_bytes())
    s.append("INBOX", mail(2, subject="Other"))
    core.mail.sync_account(account_id)
    cards = client.get("/api/messages").json()
    assert sorted((c["subject"], c["thread_count"]) for c in cards) == [("Other", 1), ("Re: Trip", 2)]
    trip = next(c for c in cards if c["subject"] == "Re: Trip")
    r = client.post(f"/api/messages/{trip['id']}/move", json={"folder": None}).json()
    assert sorted(r["message_ids"]) == ["<qa-1@example.com>", "<qa-reply@example.com>"]
    s.select_folder("INBOX", readonly=True)
    assert len(s.search("ALL")) == 1
    client.post(f"/api/accounts/{account_id}/restore", json={"folder": r["folder"], "message_ids": r["message_ids"]})
    s.select_folder("INBOX", readonly=True)
    assert len(s.search("ALL")) == 3
    s.logout()
