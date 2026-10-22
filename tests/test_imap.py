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


class FakeGmail:
    """Just enough of Gmail's IMAP: X-GM-EXT-1 labels, \\All folder."""

    def __init__(self, all_visible=True):
        self.calls = []
        self.all_visible = all_visible

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def has_capability(self, cap):
        return cap in ("X-GM-EXT-1", b"X-GM-EXT-1", "MOVE")

    def list_folders(self):
        folders = [((b"\\HasNoChildren",), b"/", "INBOX"), ((b"\\Sent",), b"/", "[Gmail]/Sent Mail")]
        if self.all_visible:
            folders.append(((b"\\All",), b"/", "[Gmail]/All Mail"))
        return folders

    def select_folder(self, name, readonly=False):
        self.calls.append(("select", name))
        return {}

    def remove_gmail_labels(self, uids, labels):
        self.calls.append(("remove_labels", list(uids), labels))

    def add_gmail_labels(self, uids, labels):
        self.calls.append(("add_labels", list(uids), labels))

    def search(self, criteria):
        return [99]

    def move(self, uids, folder):
        raise AssertionError("Gmail archive must use labels, not MOVE")


def test_gmail_archive_removes_the_inbox_label_and_undo_adds_it_back(core, monkeypatch):
    from .conftest import add_message

    acc = add_account(core)
    mid = add_message(core, acc, 5, message_id="<g@x>")
    gmail = FakeGmail()
    monkeypatch.setattr(core.mail, "connect", lambda account: gmail)
    r = core.mail.move(mid, None)
    assert r == {"folder": "[Gmail]/All Mail", "account_id": acc, "message_id": "<g@x>"}
    assert ("remove_labels", [5], ["\\Inbox"]) in gmail.calls
    assert core.mail.restore(acc, r["folder"], [r["message_id"]]) == 1
    assert ("add_labels", [99], ["\\Inbox"]) in gmail.calls


def test_gmail_archive_without_all_mail_has_no_undo(core, monkeypatch):
    from .conftest import add_message

    acc = add_account(core)
    mid = add_message(core, acc, 5, message_id="<g@x>")
    monkeypatch.setattr(core.mail, "connect", lambda account: FakeGmail(all_visible=False))
    r = core.mail.move(mid, None)
    assert r["folder"] == ""
    assert core.mail.restore(acc, r["folder"], [r["message_id"]]) == 0


def sent_raw(uid, to="Alice <alice@example.com>", body="Can we meet Tuesday?", in_reply_to=""):
    m = EmailMessage()
    m["From"] = "Me <me@gmail.com>"
    m["To"] = to
    m["Subject"] = f"Plan {uid}"
    m["Date"] = "Tue, 20 Oct 2026 10:00:00 +0000"
    m["Message-ID"] = f"<sent{uid}@gmail.com>"
    if in_reply_to:
        m["In-Reply-To"] = in_reply_to
    m.set_content(f"{body}\n\nOn Mon, 19 Oct 2026, Alice <alice@example.com> wrote:\n> secret quoted text")
    return m.as_bytes()


class FakeFolders(FakeIMAP):
    """INBOX plus a Sent folder flagged \\Sent, both read-only."""

    def __init__(self, inbox, sent, answered=()):
        super().__init__(inbox)
        self.folders = {"INBOX": inbox, "Sent Items": sent}
        self.answered = set(answered)
        self.current = "INBOX"

    def list_folders(self):
        return [((b"\\HasNoChildren",), b"/", "INBOX"), ((b"\\Sent",), b"/", "Sent Items"),
                ((b"\\Trash",), b"/", "Trash")]

    def select_folder(self, name, readonly=False):
        assert readonly, "sync must open folders read-only"
        self.current = name
        self.messages = self.folders[name]
        return {b"UIDVALIDITY": 1}

    def fetch(self, uids, items):
        out = super().fetch(uids, items)
        for u, d in out.items():
            if self.current == "INBOX" and u in self.answered:
                d[b"FLAGS"] = d[b"FLAGS"] + (b"\\Answered",)
        return out


def test_sent_folder_sync_threads_and_answered_flag(core, monkeypatch):
    acc = add_account(core)
    server = FakeFolders({10: raw(10), 11: raw(11)}, {
        1: sent_raw(1),
        2: sent_raw(2, body="Thanks, done.", in_reply_to="<10@example.com>"),
    }, answered={11})
    monkeypatch.setattr(core.mail, "connect", lambda account: server)
    assert core.mail.sync_account(acc) == 2
    with core.db.conn() as c:
        sent = {r["uid"]: dict(r) for r in c.execute("SELECT * FROM sent_messages")}
        threads = {r["message_id"] for r in c.execute("SELECT message_id FROM thread_index")}
        answered = {r["uid"]: r["answered"] for r in c.execute("SELECT uid, answered FROM messages")}
        folder = c.execute("SELECT sent_folder, sent_last_uid FROM accounts").fetchone()
    assert tuple(folder) == ("Sent Items", 2)
    assert sent[1]["to_addr"] == "alice@example.com" and sent[1]["to_name"] == "Alice"
    assert sent[1]["body_text"] == "Can we meet Tuesday?"   # quoted text removed
    assert sent[1]["expects_reply"] == 1 and sent[2]["expects_reply"] == 0
    assert sent[2]["in_reply_to"] == "<10@example.com>"
    assert threads == {"<10@example.com>", "<11@example.com>"}
    assert answered == {10: 0, 11: 1}

    # Incremental: only the new sent message is fetched; quick (IDLE) syncs skip the Sent folder.
    server.folders["Sent Items"][3] = sent_raw(3)
    core.mail.sync_account(acc, quick=True)
    with core.db.conn() as c:
        assert c.execute("SELECT COUNT(*) FROM sent_messages").fetchone()[0] == 2
    core.mail.sync_account(acc)
    with core.db.conn() as c:
        assert c.execute("SELECT COUNT(*) FROM sent_messages").fetchone()[0] == 3


def test_a_broken_sent_folder_never_blocks_the_inbox(core, monkeypatch):
    acc = add_account(core)
    server = FakeFolders({10: raw(10)}, {})

    def boom():
        raise OSError("weird server")

    server.list_folders = boom
    monkeypatch.setattr(core.mail, "connect", lambda account: server)
    assert core.mail.sync_account(acc) == 1
    assert core.mail.get_account(acc)["last_error"] is None


def test_bulk_archive_uses_one_connection(core, monkeypatch):
    from .conftest import add_message

    acc = add_account(core)
    ids = [add_message(core, acc, u, message_id=f"<b{u}@x>") for u in (5, 6, 7)]
    gmail = FakeGmail()
    connects = []
    monkeypatch.setattr(core.mail, "connect", lambda account: connects.append(1) or gmail)
    r = core.mail.move_many(acc, ids[:2], None)
    assert len(connects) == 1 and ("remove_labels", [5, 6], ["\\Inbox"]) in gmail.calls
    assert sorted(r["message_ids"]) == ["<b5@x>", "<b6@x>"]
    assert core.mail.restore(acc, r["folder"], r["message_ids"]) == 2
