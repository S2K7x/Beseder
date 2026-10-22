"""Phase 3: conversations, snooze, bulk actions."""

import asyncio
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage

from beseder.db import DB
from beseder.mail.threads import ids_in, normalize_subject

from .conftest import add_account, add_message
from .test_imap import FakeFolders, FakeGmail


def soon(**kw):
    return (datetime.now(timezone.utc) + timedelta(**kw)).isoformat(timespec="seconds")


def msg(mid, subject="Trip", sender="Alice <alice@example.com>", in_reply_to="", refs="", day=20):
    m = EmailMessage()
    m["From"], m["To"], m["Subject"] = sender, "me@gmail.com", subject
    m["Date"] = f"Tue, {day} Oct 2026 09:00:00 +0000"
    m["Message-ID"] = mid
    if in_reply_to:
        m["In-Reply-To"] = in_reply_to
    if refs:
        m["References"] = refs
    m.set_content(f"body of {mid}")
    return m.as_bytes()


def test_header_helpers():
    assert ids_in("<a@x> <b@x>", "<b@x>") == ["<a@x>", "<b@x>"]
    assert normalize_subject("RE: Fwd: TR:  Trip  plans") == "trip plans"


def test_sync_groups_replies_into_one_conversation(core, monkeypatch):
    acc = add_account(core)
    inbox = {
        1: msg("<root@x>"),
        2: msg("<r1@x>", "Re: Trip", "Bob <bob@example.com>", "<root@x>", "<root@x>", day=21),
        # Only In-Reply-To, pointing at my sent reply: still the same conversation.
        3: msg("<r3@x>", "Re: Trip", in_reply_to="<sent1@me>", day=23),
        4: msg("<other@x>", "Trip"),  # same subject, not a reply: another conversation
    }
    sent = {1: msg("<sent1@me>", "Re: Trip", "Me <me@gmail.com>", "<r1@x>", "<root@x> <r1@x>", day=22)}
    monkeypatch.setattr(core.mail, "connect", lambda account: FakeFolders(inbox, sent))
    core.mail.sync_account(acc)   # inbox first (message 3 can't be linked yet), then Sent
    core.mail.sync_account(acc)
    with core.db.conn() as c:
        keys = {r["message_id"]: r["thread_key"] for r in c.execute("SELECT message_id, thread_key FROM messages")}
        sent_key = c.execute("SELECT thread_key FROM sent_messages").fetchone()[0]
    assert keys["<root@x>"] == keys["<r1@x>"] == sent_key == "<root@x>"
    assert keys["<other@x>"] == "<other@x>"
    # Message 3 arrived before Beseder knew about the sent reply; the one-time backfill and
    # new mail fix that up. A fresh reply to it now lands in the right conversation:
    inbox[5] = msg("<r5@x>", "Re: Trip", in_reply_to="<sent1@me>", day=24)
    core.mail.sync_account(acc)
    with core.db.conn() as c:
        assert c.execute("SELECT thread_key FROM messages WHERE message_id='<r5@x>'").fetchone()[0] == "<root@x>"


def test_backfill_links_old_mail(core, tmp_path):
    acc = add_account(core)
    add_message(core, acc, 1, message_id="<a@x>", date="2026-10-01T10:00:00+00:00")
    add_message(core, acc, 2, message_id="<b@x>", date="2026-10-02T10:00:00+00:00")
    with core.db.conn() as c:
        c.execute("UPDATE messages SET in_reply_to='<a@x>' WHERE uid=2")
        c.execute("INSERT INTO thread_index(message_id, in_reply_to, refs, date) VALUES"
                  " ('<a@x>', '', '', '2026-10-01T10:00:00+00:00'), ('<b@x>', '<a@x>', '', '2026-10-02T10:00:00+00:00')")
        c.execute("DELETE FROM settings WHERE key='threads_built'")
    DB(core.config.db_path)   # reopening runs the one-time backfill
    with core.db.conn() as c:
        assert {r[0] for r in c.execute("SELECT thread_key FROM messages")} == {"<a@x>"}


def thread(core, acc):
    ids = [add_message(core, acc, u, thread_key="<t@x>", date=f"2026-10-1{u}T10:00:00+00:00", seen=int(u == 3),
                       category="important" if u == 1 else "newsletters") for u in (1, 2, 3)]
    alone = add_message(core, acc, 9, date="2026-10-15T10:00:00+00:00", message_id="<solo@x>")
    return ids, alone


def test_list_shows_one_card_per_conversation(client, core):
    acc = add_account(core)
    (a, b, c_), alone = thread(core, acc)
    rows = client.get("/api/messages").json()
    assert [(r["id"], r.get("thread_count"), r.get("thread_unread")) for r in rows] == [(alone, 0, 0), (c_, 3, 2)]
    # Filters look inside conversations: the latest unread / important message stands for it.
    assert [r["id"] for r in client.get("/api/messages", params={"unread": True}).json()] == [alone, b]
    assert [r["id"] for r in client.get("/api/messages", params={"category": "important"}).json()] == [a]
    # Search and "threads=false" show every message.
    assert len(client.get("/api/messages", params={"threads": False}).json()) == 4


def test_reader_shows_the_conversation_and_reads_all_of_it(client, core):
    acc = add_account(core)
    (a, b, c_), _alone = thread(core, acc)
    with core.db.conn() as c:
        c.execute("INSERT INTO sent_messages(account_id, uid, message_id, to_addr, to_name, subject, date, body_text,"
                  " thread_key) VALUES(?, 1, '<me@x>', 'alice@example.com', 'Alice', 'Re', '2026-10-12T12:00:00+00:00',"
                  " 'My answer', '<t@x>')", (acc,))
    m = client.get(f"/api/messages/{c_}").json()
    assert [(t["kind"], t.get("id")) for t in m["thread"]] == [("received", a), ("received", b), ("sent", 1)]
    assert m["thread"][2]["body_text"] == "My answer"
    client.post(f"/api/messages/{c_}/read")
    with core.db.conn() as c:
        assert c.execute("SELECT COUNT(*) FROM messages WHERE seen=0 AND thread_key='<t@x>'").fetchone()[0] == 0


def test_archive_moves_the_whole_conversation(core, monkeypatch):
    acc = add_account(core)
    (a, b, c_), alone = thread(core, acc)
    gmail = FakeGmail()
    monkeypatch.setattr(core.mail, "connect", lambda account: gmail)
    r = core.mail.move(c_, None)
    assert ("remove_labels", [1, 2, 3], ["\\Inbox"]) in gmail.calls and len(r["message_ids"]) == 3
    with core.db.conn() as c:
        assert [r[0] for r in c.execute("SELECT id FROM messages")] == [alone]


def test_snooze_hides_then_brings_back_on_top(client, core, monkeypatch):
    acc = add_account(core)
    (a, b, c_), alone = thread(core, acc)
    for bad in ("tomorrow", "2026-10-30T08:00:00", soon(minutes=-5), soon(days=400)):
        assert client.post(f"/api/messages/{alone}/snooze", json={"until": bad}).status_code == 400
    assert client.post(f"/api/messages/{c_}/snooze", json={"until": soon(hours=3)}).status_code == 200
    assert [r["id"] for r in client.get("/api/messages").json()] == [alone]
    assert {r["id"] for r in client.get("/api/messages", params={"snoozed": True}).json()} == {a, b, c_}
    st = client.get("/api/status").json()
    assert st["snoozed"] == 3 and st["unread_by_category"] == {"untriaged": 1}

    pushed = []

    async def send(payload, urgency="normal"):
        pushed.append(payload)
        return 1

    monkeypatch.setattr(core.push, "send", send)
    monkeypatch.setattr(core.push, "count", lambda: 1)
    assert asyncio.run(core.wake_snoozed()) == 0          # not yet
    with core.db.conn() as c:
        c.execute("UPDATE messages SET snoozed_until=? WHERE snoozed_until IS NOT NULL", (soon(minutes=-1),))
    assert asyncio.run(core.wake_snoozed()) == 3
    assert pushed[0]["title"] == "3 emails back from snooze"
    rows = client.get("/api/messages").json()
    assert rows[0]["resurfaced"] and rows[0]["id"] == c_ and [r["id"] for r in rows[1:]] == [alone]
    client.post(f"/api/messages/{c_}/read")     # opened: back to its normal place
    assert [r["id"] for r in client.get("/api/messages").json()] == [alone, c_]


def test_bulk_actions(client, core, monkeypatch):
    acc = add_account(core)
    (a, b, c_), alone = thread(core, acc)
    r = client.post("/api/messages/bulk", json={"ids": [c_, alone], "action": "read"}).json()
    assert r["count"] == 4
    with core.db.conn() as c:
        assert c.execute("SELECT COUNT(*) FROM messages WHERE seen=0").fetchone()[0] == 0
    client.post("/api/messages/bulk", json={"ids": [alone], "action": "category", "category": "receipts"})
    with core.db.conn() as c:
        assert c.execute("SELECT category, category_source FROM messages WHERE id=?", (alone,)).fetchone()[:] == (
            "receipts", "user")
    assert client.post("/api/messages/bulk", json={"ids": [alone], "action": "category", "category": "x"}).status_code == 400
    client.post("/api/messages/bulk", json={"ids": [alone], "action": "snooze", "until": soon(days=1)})
    assert client.get("/api/status").json()["snoozed"] == 1
    client.post("/api/messages/bulk", json={"ids": [alone], "action": "unsnooze"})
    assert client.get("/api/status").json()["snoozed"] == 0
    calls = []
    monkeypatch.setattr(core.mail, "move_many", lambda account_id, ids, target: calls.append(sorted(ids)) or
                        {"folder": "Archive", "account_id": account_id, "message_ids": ["<x>"]})
    r = client.post("/api/messages/bulk", json={"ids": [c_], "action": "archive"}).json()
    assert calls == [sorted([a, b, c_])] and r["moved"][0]["folder"] == "Archive"
    assert client.post("/api/messages/bulk", json={"ids": [a], "action": "delete"}).status_code == 400
    assert client.post("/api/messages/bulk", json={"ids": [], "action": "read"}).status_code == 400
