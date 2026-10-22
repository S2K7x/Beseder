"""Phase 2: follow-ups, writing style, sorting rules, unsubscribe, morning brief, search."""

import asyncio
import json
from datetime import datetime, timedelta, timezone

import pytest

import beseder.main as main_mod
from beseder.unsubscribe import UnsubscribeError, one_click

from .conftest import FakeProvider, add_account, add_message


def ago(days):
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="seconds")


def add_sent(core, account_id, uid, **kw):
    row = {"message_id": f"<s{uid}@me>", "in_reply_to": "", "refs": "", "to_addr": "bob@example.com",
           "to_name": "Bob", "subject": f"Question {uid}", "date": ago(3), "body_text": "Can you send it?",
           "expects_reply": 1}
    row.update(kw)
    with core.db.conn() as c:
        return c.execute(
            "INSERT INTO sent_messages(account_id, uid, message_id, in_reply_to, refs, to_addr, to_name, subject,"
            " date, body_text, expects_reply) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (account_id, uid, *row.values())).lastrowid


def set_ai(core, monkeypatch, reply):
    fake = FakeProvider(reply)
    monkeypatch.setattr(core, "provider", lambda: fake)
    return fake


def test_triage_flags_mail_that_needs_a_reply_and_follows_user_rules(client, core, monkeypatch):
    acc = add_account(core)
    m1 = add_message(core, acc, 1, date=ago(1))
    m2 = add_message(core, acc, 2, date=ago(1))
    fake = set_ai(core, monkeypatch, lambda s, u: json.dumps({
        str(m1): {"category": "important", "reply": True}, str(m2): {"category": "newsletters", "reply": False}}))
    client.put("/api/settings/rules", json={"rules": "Anything from my landlord is important\n\n"})
    core.db.set_setting("auto_triage", True)
    asyncio.run(core.run_triage())
    assert "Anything from my landlord is important" in fake.calls[0]["system"]
    with core.db.conn() as c:
        got = {r["id"]: (r["category"], r["needs_reply"]) for r in c.execute("SELECT * FROM messages")}
    assert got == {m1: ("important", 1), m2: ("newsletters", 0)}
    assert client.get("/api/settings/assistant").json()["rules"] == "Anything from my landlord is important"


def test_resort_redoes_ai_choices_but_keeps_the_users(client, core, monkeypatch):
    acc = add_account(core)
    ai = add_message(core, acc, 1, date=ago(1), category="promotions")
    mine = add_message(core, acc, 2, date=ago(1), category="receipts")
    old = add_message(core, acc, 3, date=ago(60), category="promotions")
    with core.db.conn() as c:
        c.execute("UPDATE messages SET category_source='ai' WHERE id IN (?, ?)", (ai, old))
        c.execute("UPDATE messages SET category_source='user' WHERE id=?", (mine,))
    set_ai(core, monkeypatch, lambda s, u: json.dumps({str(i): "important" for i in (ai, mine, old)}))
    assert client.post("/api/triage/resort").json() == {"classified": 1}
    with core.db.conn() as c:
        cats = {r["id"]: r["category"] for r in c.execute("SELECT id, category FROM messages")}
    assert cats == {ai: "important", mine: "receipts", old: "promotions"}


def test_to_reply_list(client, core):
    acc = add_account(core)
    want = add_message(core, acc, 1, date=ago(1), category="important")
    answered_here = add_message(core, acc, 2, date=ago(1), category="important", message_id="<q2@x>")
    flagged = add_message(core, acc, 3, date=ago(1), category="important")
    promo = add_message(core, acc, 4, date=ago(1), category="promotions")
    too_old = add_message(core, acc, 5, date=ago(20), category="important")
    dismissed = add_message(core, acc, 6, date=ago(1), category="important")
    with core.db.conn() as c:
        c.execute("UPDATE messages SET needs_reply=1")
        c.execute("UPDATE messages SET answered=1 WHERE id=?", (flagged,))
    add_sent(core, acc, 1, in_reply_to="<q2@x>")
    assert client.post("/api/followups/done", json={"kind": "reply", "id": dismissed}).status_code == 200
    ids = [m["id"] for m in client.get("/api/followups").json()["to_reply"]]
    assert ids == [want]
    assert {answered_here, flagged, promo, too_old, dismissed}.isdisjoint(ids)
    assert client.get("/api/status").json()["followups"]["to_reply"] == 1
    assert client.post("/api/followups/done", json={"kind": "nope", "id": 1}).status_code == 400
    assert client.post("/api/followups/done", json={"kind": "waiting", "id": 999}).status_code == 404


def test_waiting_for_a_reply_list(client, core):
    acc = add_account(core, email="Me@Gmail.com")
    waiting = add_sent(core, acc, 1, subject="Contract")
    add_sent(core, acc, 2, to_addr="carol@example.com", message_id="<s2@me>")       # Carol answered in the thread
    add_sent(core, acc, 3, to_addr="dave@example.com")                             # Dave wrote back since
    add_sent(core, acc, 4, to_addr="noreply@shop.com")
    add_sent(core, acc, 5, to_addr="erin@example.com", expects_reply=0)
    add_sent(core, acc, 6, to_addr="frank@example.com", date=ago(0))               # too recent
    add_sent(core, acc, 7, to_addr="me@gmail.com")                                 # note to self
    add_sent(core, acc, 8, subject="Re: Contract", date=ago(4))                    # older message, same thread
    with core.db.conn() as c:
        c.execute("INSERT INTO thread_index(message_id, in_reply_to, refs, date) VALUES('<r@carol>', '<s2@me>', '', ?)",
                  (ago(1),))
    add_message(core, acc, 1, from_addr="dave@example.com", date=ago(1))
    items = client.get("/api/followups").json()["waiting"]
    assert [i["id"] for i in items] == [waiting]
    assert items[0]["to_name"] == "Bob" and "message_id" not in items[0]
    client.post("/api/followups/done", json={"kind": "waiting", "id": waiting})
    assert client.get("/api/followups").json()["waiting"] == []


def test_drafts_learn_from_what_i_sent(client, core, monkeypatch):
    acc = add_account(core)
    m = add_message(core, acc, 1, from_addr="bob@example.com")
    add_sent(core, acc, 1, body_text="Hey Bob, all good on my side. Cheers, Sam")
    add_sent(core, acc, 2, to_addr="zoe@example.com", body_text="Dear Zoe, thank you for your message. Best, Sam")
    add_sent(core, acc, 3, to_addr="x@example.com", body_text="ok")  # too short to say anything
    fake = set_ai(core, monkeypatch, "Hi Bob")
    client.post(f"/api/messages/{m}/draft", json={})
    user = fake.calls[0]["user"]
    assert user.index("Hey Bob") < user.index("Dear Zoe")   # same person first
    assert "\nok\n" not in user
    client.put("/api/settings/style", json={"learn": False})
    client.post(f"/api/messages/{m}/draft", json={})
    assert "Hey Bob" not in fake.calls[1]["user"]


def test_unsubscribe_routes(client, core, monkeypatch):
    acc = add_account(core)
    one = add_message(core, acc, 1, from_addr="news@shop.com")
    link = add_message(core, acc, 2)
    mail = add_message(core, acc, 3)
    none = add_message(core, acc, 4)
    with core.db.conn() as c:
        c.execute("UPDATE messages SET unsub_url='https://shop.com/u/1', unsub_one_click=1 WHERE id=?", (one,))
        c.execute("UPDATE messages SET unsub_url='https://x.com/u' WHERE id=?", (link,))
        c.execute("UPDATE messages SET unsub_mailto='mailto:u@x.com' WHERE id=?", (mail,))
    posted = []

    async def fake_one_click(url):
        posted.append(url)
        return 200

    monkeypatch.setattr(main_mod, "one_click", fake_one_click)
    assert client.post(f"/api/messages/{one}/unsubscribe").json() == {"done": True, "sender": "news@shop.com"}
    assert posted == ["https://shop.com/u/1"]
    assert client.post(f"/api/messages/{link}/unsubscribe").json()["open"] == "https://x.com/u"
    assert client.post(f"/api/messages/{mail}/unsubscribe").json()["open"] == "mailto:u@x.com"
    assert client.post(f"/api/messages/{none}/unsubscribe").status_code == 404

    async def refused(url):
        raise UnsubscribeError("This unsubscribe link points to a private network: refused")

    monkeypatch.setattr(main_mod, "one_click", refused)
    r = client.post(f"/api/messages/{one}/unsubscribe")
    assert r.status_code == 502 and "private network" in r.json()["detail"]


def test_one_click_posts_to_the_checked_address(monkeypatch):
    import httpcore

    import beseder.unsubscribe as unsub

    async def fake_resolve(host, port):
        assert (host, port) == ("shop.example", 443)
        return "93.184.216.34"

    seen = {}

    class Backend(httpcore.AsyncMockBackend):
        async def connect_tcp(self, host, port, **kw):
            seen["target"] = (host, port)
            return await super().connect_tcp(host, port, **kw)

    monkeypatch.setattr(unsub, "public_address", fake_resolve)
    monkeypatch.setattr(httpcore, "AnyIOBackend", lambda: Backend([b"HTTP/1.1 200 OK\r\nContent-Length: 0\r\n\r\n"]))
    assert asyncio.run(one_click("https://shop.example/unsub?id=1")) == 200
    assert seen["target"] == ("93.184.216.34", 443)
    monkeypatch.setattr(httpcore, "AnyIOBackend", lambda: Backend([b"HTTP/1.1 302 Found\r\nLocation: http://10.0.0.1/\r\n"
                                                                   b"Content-Length: 0\r\n\r\n"]))
    assert asyncio.run(one_click("https://shop.example/unsub?id=1")) == 302   # not followed
    monkeypatch.setattr(httpcore, "AnyIOBackend", lambda: Backend([b"HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\n\r\n"]))
    with pytest.raises(UnsubscribeError):
        asyncio.run(one_click("https://shop.example/unsub?id=1"))


@pytest.mark.parametrize("url", ["http://shop.com/u", "https://127.0.0.1/u", "https://localhost/u", "https://10.1.2.3/u",
                                 "https://100.100.1.1/u", "https://[::1]/u", "https://169.254.169.254/latest",
                                 "https://user:pw@shop.com/u", "javascript:alert(1)"])
def test_one_click_refuses_private_or_odd_links(url):
    with pytest.raises(UnsubscribeError):
        asyncio.run(one_click(url))


def test_archive_everything_from_a_sender(client, core, monkeypatch):
    a1, a2 = add_account(core), add_account(core, email="work@x.com")
    for acc, uid in ((a1, 1), (a1, 2), (a2, 3)):
        add_message(core, acc, uid, from_addr="news@shop.com", message_id=f"<n{uid}@shop>")
    keep = add_message(core, a1, 9)
    calls = []

    def move_many(account_id, ids, target):
        calls.append((account_id, sorted(ids), target))
        return {"folder": "Archive", "account_id": account_id, "message_ids": [f"<n{i}>" for i in ids]}

    monkeypatch.setattr(core.mail, "move_many", move_many)
    r = client.post("/api/senders/archive", json={"addr": "News@Shop.com"}).json()
    assert r["count"] == 3 and len(calls) == 2 and all(t is None for _a, _i, t in calls)
    assert keep not in sum((ids for _a, ids, _t in calls), [])


def test_morning_brief_runs_once_at_the_chosen_local_time(client, core, monkeypatch):
    acc = add_account(core)
    add_message(core, acc, 1)
    set_ai(core, monkeypatch, '{"overview": "One thing matters.", "emails": []}')
    monkeypatch.setattr(core, "ai_config", lambda: type("C", (), {"configured": True})())
    pushed = []

    async def send(payload, urgency="normal"):
        pushed.append(payload)
        return 1

    monkeypatch.setattr(core.push, "send", send)
    monkeypatch.setattr(core.push, "count", lambda: 1)
    assert client.put("/api/settings/brief", json={"time": "25:00", "tz": "Europe/Paris"}).status_code == 400
    assert client.put("/api/settings/brief", json={"time": "07:30", "tz": "Mars/Base"}).status_code == 400
    core.db.set_setting("brief_time", "07:30")
    core.db.set_setting("brief_tz", "Europe/Paris")   # UTC+2 in October
    at = lambda hh, mm, day=21: datetime(2026, 10, day, hh, mm, tzinfo=timezone.utc)  # noqa: E731
    assert asyncio.run(core.morning_brief(at(5, 29))) is False          # 07:29 in Paris
    assert asyncio.run(core.morning_brief(at(5, 31))) is True
    assert pushed == [{"title": "Your morning brief", "body": "One thing matters.", "url": "/#/brief", "tag": "brief"}]
    assert asyncio.run(core.morning_brief(at(6, 0))) is False           # once a day
    assert asyncio.run(core.morning_brief(at(12, 0, day=22))) is False  # Beseder was off: too late, skip
    assert asyncio.run(core.morning_brief(at(5, 31, day=23))) is True
    core.db.set_setting("push_preview", False)
    asyncio.run(core.morning_brief(at(5, 31, day=24)))
    assert pushed[-1]["body"] == "1 unread email summarized"


def test_search_ignores_accents_and_matches_word_starts(client, core):
    acc = add_account(core)
    bill = add_message(core, acc, 1, subject="Facture électricité octobre", body_text="Montant 42 €")
    add_message(core, acc, 2, subject="Dinner", body_text="See you at 8")
    q = lambda s: [m["id"] for m in client.get("/api/messages", params={"q": s}).json()]  # noqa: E731
    assert q("electricite") == [bill]
    assert q("fact oct") == [bill]
    assert q("ÉLEC") == [bill]
    assert q("dinner bill") == []
    assert q('" OR *') == []   # FTS syntax in the box is just text
    with core.db.conn() as c:
        c.execute("UPDATE messages SET subject='Dîner samedi' WHERE id=?", (bill,))
    assert q("diner") == [bill] and q("facture") == []


def test_ask_search(client, core, monkeypatch):
    acc = add_account(core)
    bill = add_message(core, acc, 1, subject="Your EDF invoice", body_text="Amount due: 42 EUR", from_addr="edf@edf.fr")
    other = add_message(core, acc, 2, subject="Invoice from a shop", body_text="Thanks for your order")
    add_message(core, acc, 3, subject="Dinner", body_text="See you")

    def ai(system, user):
        if "turn a person's question" in system:
            return '{"terms": ["invoice", "facture"], "from": "", "category": "", "days": 0, "unread": false}'
        assert "Question: How much was my electricity bill?" in user and "Dinner" not in user
        return json.dumps({"ids": [str(bill), "424242"], "answer": "42 EUR."})

    set_ai(core, monkeypatch, ai)
    r = client.post("/api/search/ask", json={"question": "How much was my electricity bill?"}).json()
    assert [m["id"] for m in r["items"]] == [bill] and r["answer"] == "42 EUR." and r["loose"] is False
    assert "body_text" not in r["items"][0]
    set_ai(core, monkeypatch, lambda s, u: '{"terms": ["invoice"]}' if "turn a person" in s else '{"ids": []}')
    r = client.post("/api/search/ask", json={"question": "anything?"}).json()
    assert r["loose"] is True and {m["id"] for m in r["items"]} == {bill, other}
    assert client.post("/api/search/ask", json={"question": "  "}).status_code == 400
