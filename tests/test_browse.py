"""Phase 4: browsing other folders (read only), server search, sender view."""

from .conftest import add_account, add_message
from .test_imap import FakeFolders, raw


class Archive(FakeFolders):
    """INBOX, Sent Items and a big Archive; records searches; no Gmail."""

    def __init__(self, archive):
        super().__init__({}, {})
        self.folders["Archive"] = archive
        self.searches = []

    def list_folders(self):
        return super().list_folders() + [((b"\\Archive",), b"/", "Archive"), ((b"\\Noselect",), b"/", "[Parent]")]

    def has_capability(self, cap):
        return False

    def search(self, criteria, charset=None):
        self.searches.append((criteria, charset))
        if criteria[0] == "TEXT":
            return [u for u, m in self.messages.items() if criteria[1].encode() in m]
        if criteria[0] == "UID":
            hi = int(criteria[1].split(":")[1])
            return [u for u in self.messages if u <= hi]
        return list(self.messages)

    def fetch(self, uids, items):
        out = super().fetch(uids, items)
        for u, d in out.items():
            if "BODY.PEEK[HEADER]" in items:
                d[b"BODY[HEADER]"] = self.messages[u].split(b"\n\n")[0]
        return out


def setup(core, monkeypatch, n=120):
    acc = add_account(core)
    server = Archive({u: raw(u, f"Old {u}") for u in range(1, n + 1)})
    monkeypatch.setattr(core.mail, "connect", lambda account: server)
    return acc, server


def test_folder_list_has_roles_and_skips_unopenable(client, core, monkeypatch):
    acc, _server = setup(core, monkeypatch)
    browse = client.get(f"/api/accounts/{acc}/folders").json()["browse"]
    assert [(f["name"], f["role"]) for f in browse] == [
        ("INBOX", "inbox"), ("Archive", "archive"), ("Sent Items", "sent"), ("Trash", "trash")]


def test_browse_pages_newest_first_read_only(client, core, monkeypatch):
    acc, server = setup(core, monkeypatch)
    r = client.get(f"/api/accounts/{acc}/browse", params={"folder": "Archive"}).json()
    assert [i["uid"] for i in r["items"]][:3] == [120, 119, 118] and len(r["items"]) == 50 and r["more"] == 71
    assert r["items"][0]["subject"] == "Old 120" and r["items"][0]["from_addr"] == "bob@example.com"
    r = client.get(f"/api/accounts/{acc}/browse", params={"folder": "Archive", "before": r["more"]}).json()
    assert r["items"][0]["uid"] == 70
    r = client.get(f"/api/accounts/{acc}/browse", params={"folder": "Archive", "before": 21}).json()
    assert [i["uid"] for i in r["items"]][-1] == 1 and r["more"] is None
    # FakeIMAP fails on any write and asserts every select is read only.
    assert client.get(f"/api/accounts/{acc}/browse", params={"folder": "Nope"}).status_code == 404
    assert client.get(f"/api/accounts/{acc}/browse", params={"folder": "[Parent]"}).status_code == 404
    with core.db.conn() as c:
        assert c.execute("SELECT COUNT(*) FROM messages").fetchone()[0] == 0   # nothing stored


def test_server_search_and_open(client, core, monkeypatch):
    acc, server = setup(core, monkeypatch)
    r = client.get(f"/api/accounts/{acc}/browse", params={"folder": "Archive", "q": "message 42"}).json()
    assert [i["uid"] for i in r["items"]] == [42]
    assert server.searches[-1] == (["TEXT", "message 42"], "UTF-8")
    m = client.get(f"/api/accounts/{acc}/browse/message", params={"folder": "Archive", "uid": 42}).json()
    assert m["subject"] == "Old 42" and "message 42" in m["body_text"] and m["account_name"] == "Personal"
    assert client.get(f"/api/accounts/{acc}/browse/message", params={"folder": "Archive", "uid": 999}).status_code == 404


def test_gmail_uses_its_own_search(client, core, monkeypatch):
    acc, server = setup(core, monkeypatch)
    server.has_capability = lambda cap: cap in (b"X-GM-EXT-1", "X-GM-EXT-1")
    server.gmail_search = lambda q, charset="UTF-8": server.searches.append(("gmail", q)) or [7]
    r = client.get(f"/api/accounts/{acc}/browse", params={"folder": "Archive", "q": "from:bob has:attachment"}).json()
    assert [i["uid"] for i in r["items"]] == [7] and server.searches[-1] == ("gmail", "from:bob has:attachment")


def test_sender_filter(client, core):
    acc = add_account(core)
    add_message(core, acc, 1, from_addr="bob@example.com")
    add_message(core, acc, 2, from_addr="eve@example.com")
    rows = client.get("/api/messages", params={"sender": "Bob@Example.com"}).json()
    assert [r["from_addr"] for r in rows] == ["bob@example.com"]


def test_mailbox_check_reports_in_plain_words(client, core, monkeypatch):
    acc, server = setup(core, monkeypatch)
    server.has_capability = lambda cap: cap in ("IDLE",)       # no MOVE
    server.find_special_folder = lambda flag: None
    items = {i["label"]: i for i in client.get(f"/api/accounts/{acc}/check").json()["items"]}
    assert items["Sign-in"]["status"] == "ok" and items["Instant mail"]["status"] == "ok"
    assert items["Archive and move"]["status"] == "error" and "MOVE" in items["Archive and move"]["detail"]
    assert items["Sent folder"]["detail"].startswith("Sent Items")
    assert items["Drafts folder"]["status"] == "error"

    def refused(account):
        raise OSError("connection refused")

    monkeypatch.setattr(core.mail, "connect", refused)
    (only,) = client.get(f"/api/accounts/{acc}/check").json()["items"]
    assert only["status"] == "error" and "connection refused" in only["detail"]
