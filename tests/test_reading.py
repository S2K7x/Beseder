"""Phase 7: calendar invites, picture previews, conversation summaries."""

import base64
import json
from email.message import EmailMessage

import beseder.main as main_mod
from beseder.ai import tasks
from beseder.mail.invite import parse_invite
from beseder.mail.parse import parse_message

from .conftest import FakeProvider, add_account, add_message

ICS = """BEGIN:VCALENDAR\r
METHOD:REQUEST\r
BEGIN:VTIMEZONE\r
TZID:Europe/Paris\r
END:VTIMEZONE\r
BEGIN:VEVENT\r
SUMMARY:Project review\\, Q4\r
DTSTART;TZID=Europe/Paris:20261030T100000\r
DTEND;TZID=Europe/Paris:20261030T113000\r
LOCATION:Room 4\\nBuilding B\r
ORGANIZER;CN="Alice Martin":mailto:alice@example.com\r
DESCRIPTION:a very long line that is folded\r
  across two lines\r
END:VEVENT\r
END:VCALENDAR\r
"""
PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII=")


def test_parse_invite():
    ev = parse_invite(ICS.encode())
    assert ev["title"] == "Project review, Q4" and ev["method"] == "REQUEST"
    assert ev["start"] == {"iso": "2026-10-30T10:00:00+01:00", "all_day": False}
    assert ev["end"]["iso"] == "2026-10-30T11:30:00+01:00"
    assert ev["location"] == "Room 4\nBuilding B" and ev["organizer"] == "Alice Martin"
    allday = parse_invite(b"BEGIN:VEVENT\nSUMMARY:Holiday\nDTSTART;VALUE=DATE:20261224\nEND:VEVENT")
    assert allday["start"] == {"iso": "2026-12-24", "all_day": True} and allday["end"] is None
    utc = parse_invite(b"BEGIN:VEVENT\nDTSTART:20261030T090000Z\nDTSTART;TZID=Nowhere/Land:20991231T000000\nEND:VEVENT")
    assert utc["start"]["iso"] == "2026-10-30T09:00:00+00:00" and utc["title"] == "(no title)"
    windows = parse_invite(b"BEGIN:VEVENT\nDTSTART;TZID=Romance Standard Time:20261030T100000\nEND:VEVENT")
    assert windows["start"]["iso"] == "2026-10-30T10:00:00"   # unknown zone: kept as written
    assert parse_invite(b"BEGIN:VEVENT\nSUMMARY:x\nEND:VEVENT") is None
    assert parse_invite(b"garbage \xff\xfe") is None


def invite_mail():
    m = EmailMessage()
    m["From"], m["Subject"], m["Message-ID"] = "Alice <alice@example.com>", "Invitation: review", "<inv@x>"
    m.set_content("You are invited")
    m.add_alternative(ICS, subtype="calendar", params={"method": "REQUEST"})
    m.add_attachment(PNG, maintype="image", subtype="png", filename="dot.png")
    m.add_attachment(b"<svg onload=alert(1)>", maintype="image", subtype="png", filename="fake.png")
    return m.as_bytes()


def test_invite_is_parsed_at_sync_and_shown(client, core):
    p = parse_message(invite_mail())
    assert p.invite["title"] == "Project review, Q4"
    acc = add_account(core)
    mid = add_message(core, acc, 1)
    with core.db.conn() as c:
        c.execute("UPDATE messages SET invite=? WHERE id=?", (json.dumps(p.invite), mid))
    assert client.get(f"/api/messages/{mid}").json()["invite"]["location"] == "Room 4\nBuilding B"
    assert client.get(f"/api/messages/{add_message(core, acc, 2)}").json()["invite"] is None


def test_ics_download_and_picture_previews(client, core, monkeypatch):
    acc = add_account(core)
    mid = add_message(core, acc, 1)
    raw = invite_mail()

    class Server:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def select_folder(self, name, readonly=False):
            assert readonly

        def fetch(self, uids, items):
            return {uids[0]: {b"BODY[]": raw}}

    monkeypatch.setattr(core.mail, "connect", lambda account: Server())
    r = client.get(f"/api/messages/{mid}/invite.ics")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/calendar")
    assert b"SUMMARY:Project review" in r.content and r.headers["content-disposition"].startswith("attachment")
    r = client.get(f"/api/messages/{mid}/attachments/0", params={"preview": True})
    assert r.headers["content-type"] == "image/png" and r.headers["content-disposition"].startswith("inline")
    assert "sandbox" in r.headers["content-security-policy"]
    # A file that only claims to be a picture is never shown.
    assert client.get(f"/api/messages/{mid}/attachments/1", params={"preview": True}).status_code == 415
    r = client.get(f"/api/messages/{mid}/attachments/1")
    assert r.headers["content-type"] == "application/octet-stream" and r.headers["content-disposition"].startswith("attachment")


def test_image_type_sniffing():
    assert main_mod.image_type(PNG) == "image/png"
    assert main_mod.image_type(b"\xff\xd8\xff\xe0rest") == "image/jpeg"
    assert main_mod.image_type(b"GIF89a....") == "image/gif"
    assert main_mod.image_type(b"RIFF\x00\x00\x00\x00WEBPVP8 ") == "image/webp"
    assert main_mod.image_type(b"<svg xmlns='http://www.w3.org/2000/svg'/>") is None


def test_conversation_summary(client, core, monkeypatch):
    acc = add_account(core)
    first = add_message(core, acc, 1, thread_key="<t@x>", body_text="Can you send the contract by Friday?",
                        date="2026-10-10T10:00:00+00:00")
    last = add_message(core, acc, 2, thread_key="<t@x>", body_text="Reminder: Friday!", date="2026-10-12T10:00:00+00:00")
    with core.db.conn() as c:
        c.execute("INSERT INTO sent_messages(account_id, uid, to_addr, subject, date, body_text, thread_key)"
                  " VALUES(?, 1, 'alice@example.com', 'Re', '2026-10-11T10:00:00+00:00', 'Working on it', '<t@x>')", (acc,))
    fake = FakeProvider('{"summary": "Alice needs the contract.", "actions": ["Send the contract", {"bad": 1}],'
                        ' "dates": [{"what": "Deadline", "when": "Friday"}, {"what": "no date"}]}')
    monkeypatch.setattr(core, "provider", lambda: fake)
    r = client.post(f"/api/messages/{last}/explain").json()
    assert r == {"summary": "Alice needs the contract.", "actions": ["Send the contract"],
                 "dates": [{"what": "Deadline", "when": "Friday"}]}
    user = fake.calls[0]["user"]
    assert user.index("send the contract") < user.index("Working on it") < user.index("Reminder")
    assert '"from": "me"' in user and "DATA" in fake.calls[0]["system"]
    assert first


def test_parse_thread_fallback():
    assert tasks.parse_thread("Just text") == {"summary": "Just text", "actions": [], "dates": []}
