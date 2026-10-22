import pytest
from fastapi.testclient import TestClient

from beseder.config import Config
from beseder.main import create_app


class FakeProvider:
    """Test AI provider: returns a fixed reply and records the prompts it gets."""

    def __init__(self, reply="OK"):
        self.reply = reply
        self.calls = []

    async def complete(self, system, user, *, fast=False, max_tokens=2000):
        self.calls.append({"system": system, "user": user, "fast": fast})
        return self.reply(system, user) if callable(self.reply) else self.reply

    async def list_models(self):
        return ["fake-model"]


@pytest.fixture
def config(tmp_path):
    return Config(data_dir=tmp_path, run_scheduler=False, allowed_hosts=["testserver", "localhost"])


@pytest.fixture
def app(config):
    return create_app(config)


@pytest.fixture
def core(app):
    return app.state.core


@pytest.fixture
def client(app):
    with TestClient(app, headers={"X-Beseder": "1"}) as c:
        yield c


def add_account(core, email="me@gmail.com", kind="gmail"):
    with core.db.conn() as c:
        cur = c.execute(
            "INSERT INTO accounts(name, email, kind, host, port, username, secret, created_at)"
            " VALUES(?,?,?,?,?,?,?,datetime('now'))",
            ("Personal", email, kind, "imap.gmail.com", 993, email, core.vault.encrypt({"password": "x"})),
        )
        return cur.lastrowid


def add_message(core, account_id, uid, **kw):
    row = {
        "subject": f"Subject {uid}", "from_name": "Alice", "from_addr": "alice@example.com",
        "date": f"2026-10-{10 + uid % 10:02d}T10:00:00+00:00", "snippet": "excerpt", "body_text": "body",
        "seen": 0, "category": None, "message_id": f"<m{uid}@example.com>",
    }
    row.update(kw)
    with core.db.conn() as c:
        cur = c.execute(
            "INSERT INTO messages(account_id, uid, message_id, subject, from_name, from_addr, date, snippet,"
            " body_text, seen, category) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (account_id, uid, row["message_id"], row["subject"], row["from_name"], row["from_addr"], row["date"],
             row["snippet"], row["body_text"], row["seen"], row["category"]),
        )
        return cur.lastrowid
