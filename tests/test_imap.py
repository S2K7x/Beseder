from email.message import EmailMessage

from beseder.mail.imap import build_reply

from .conftest import add_account


def raw(uid, subject="Hello"):
    m = EmailMessage()
    m["From"] = "Bob <bob@example.com>"
    m["Subject"] = subject
    m["Date"] = "Tue, 20 Oct 2026 09:30:00 +0000"
    m["Message-ID"] = f"<{uid}@example.com>"
    m.set_content(f"message {uid}")
    return m.as_bytes()


class FakeIMAP:
    def __init__(self, messages, uidvalidity=1, seen=()):
        self.messages = messages  # uid -> bytes
        self.uidvalidity = uidvalidity
        self.seen = set(seen)
        self.writes = []

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def select_folder(self, name, readonly=False):
        assert readonly, "sync must open INBOX read-only"
        return {b"UIDVALIDITY": self.uidvalidity}

    def search(self, criteria):
        if criteria[0] == "UID":
            start = int(criteria[1].split(":")[0])
            found = [u for u in self.messages if u >= start]
            return found or [max(self.messages)]  # real IMAP behavior on an empty range
        return list(self.messages)

    def fetch(self, uids, items):
        out = {}
        for u in uids:
            if u not in self.messages:
                continue
            d = {b"FLAGS": (b"\\Seen",) if u in self.seen else ()}
            if "RFC822.SIZE" in items:
                d[b"RFC822.SIZE"] = len(self.messages[u])
            if "BODY.PEEK[]" in items:
                d[b"BODY[]"] = self.messages[u]
            out[u] = d
        return out

    def __getattr__(self, name):  # any other command (delete, expunge, move...) is forbidden
        raise AssertionError(f"unexpected IMAP command: {name}")


def test_sync_imports_refreshes_flags_and_handles_deletions(core, monkeypatch):
    acc = add_account(core)
    server = FakeIMAP({10: raw(10), 11: raw(11, "Invoice")})
    monkeypatch.setattr(core.mail, "connect", lambda account: server)

    assert core.mail.sync_account(acc) == 2
    assert core.mail.sync_account(acc) == 0  # nothing new, no duplicates

    server.messages[12] = raw(12)
    server.seen.add(10)
    del server.messages[11]  # deleted from the phone
    assert core.mail.sync_account(acc) == 1
    with core.db.conn() as c:
        rows = {r["uid"]: r["seen"] for r in c.execute("SELECT uid, seen FROM messages")}
        last_uid = c.execute("SELECT last_uid FROM accounts").fetchone()[0]
    assert rows == {10: 1, 12: 0}
    assert last_uid == 12


def test_uidvalidity_change_resets_local_copy(core, monkeypatch):
    acc = add_account(core)
    server = FakeIMAP({5: raw(5)})
    monkeypatch.setattr(core.mail, "connect", lambda account: server)
    core.mail.sync_account(acc)
    server.uidvalidity = 2
    server.messages = {1: raw(1)}
    core.mail.sync_account(acc)
    with core.db.conn() as c:
        assert [r[0] for r in c.execute("SELECT uid FROM messages")] == [1]


def test_sync_error_is_stored(core, monkeypatch):
    acc = add_account(core)

    def boom(account):
        raise OSError("network down")

    monkeypatch.setattr(core.mail, "connect", boom)
    assert core.mail.sync_account(acc) == 0
    assert core.mail.get_account(acc)["last_error"] == "network down"


def test_build_reply_threads_correctly():
    m = {
        "subject": "Dinner", "reply_to": "", "from_name": "Bob", "from_addr": "bob@example.com",
        "message_id": "<1@example.com>", "refs": "<0@example.com>",
    }
    msg = build_reply(m, "me@gmail.com", "With pleasure")
    assert msg["Subject"] == "Re: Dinner"
    assert msg["To"] == "Bob <bob@example.com>"
    assert msg["In-Reply-To"] == "<1@example.com>"
    assert msg["References"] == "<0@example.com> <1@example.com>"
    assert build_reply(dict(m, subject="RE: Dinner"), "me@gmail.com", "x")["Subject"] == "RE: Dinner"


def test_read_in_beseder_survives_a_sync_before_the_server_knows(core, monkeypatch):
    acc = add_account(core)
    server = FakeIMAP({10: raw(10)})
    monkeypatch.setattr(core.mail, "connect", lambda account: server)
    core.mail.sync_account(acc)
    with core.db.conn() as c:
        mid = c.execute("SELECT id FROM messages").fetchone()[0]
        c.execute("UPDATE messages SET seen=1 WHERE id=?", (mid,))
    core.mail.queue_seen(mid)
    core.mail.sync_account(acc)  # the server still says unread
    with core.db.conn() as c:
        assert c.execute("SELECT seen FROM messages").fetchone()[0] == 1


def test_read_marks_are_sent_in_one_batch(core, monkeypatch):
    acc = add_account(core)
    server = FakeIMAP({10: raw(10), 11: raw(11), 12: raw(12)})
    monkeypatch.setattr(core.mail, "connect", lambda account: server)
    core.mail.sync_account(acc)
    connects = []

    class Writer(FakeIMAP):
        def select_folder(self, name, readonly=False):
            return {}

        def add_flags(self, uids, flags):
            connects.append(sorted(uids))

    monkeypatch.setattr(core.mail, "connect", lambda account: Writer({}))
    with core.db.conn() as c:
        for (mid,) in c.execute("SELECT id FROM messages").fetchall():
            core.mail.queue_seen(mid)
    core.mail.flush_seen(acc)
    core.mail.flush_seen(acc)  # nothing left to send
    assert connects == [[10, 11, 12]]


def test_failed_read_marks_are_retried_at_next_sync(core, monkeypatch):
    acc = add_account(core)
    server = FakeIMAP({10: raw(10)})
    monkeypatch.setattr(core.mail, "connect", lambda account: server)
    core.mail.sync_account(acc)
    with core.db.conn() as c:
        mid = c.execute("SELECT id FROM messages").fetchone()[0]
    core.mail.queue_seen(mid)

    def offline(account):
        raise OSError("network down")

    monkeypatch.setattr(core.mail, "connect", offline)
    core.mail.flush_seen(acc)  # fails, keeps the mark

    sent = []

    class Back(FakeIMAP):
        def select_folder(self, name, readonly=False):
            return {b"UIDVALIDITY": 1}

        def add_flags(self, uids, flags):
            sent.append(list(uids))
            self.seen.update(uids)

    monkeypatch.setattr(core.mail, "connect", lambda account: Back({10: raw(10)}))
    core.mail.sync_account(acc)
    assert sent == [[10]]
    with core.db.conn() as c:
        assert c.execute("SELECT seen FROM messages").fetchone()[0] == 1
