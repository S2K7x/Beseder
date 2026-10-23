"""Phase 8: encrypted backups and the activity log."""

import pytest

from beseder import backup
from beseder.config import Config
from beseder.crypto import Vault
from beseder.db import DB

from .conftest import add_account, add_message


def test_backup_round_trip(client, core, tmp_path):
    acc = add_account(core)
    add_message(core, acc, 1, subject="Keep me")
    r = client.post("/api/backup", json={"passphrase": "correct horse"})
    assert r.status_code == 200 and r.headers["content-disposition"].startswith("attachment; filename=beseder-backup-")
    data = r.content
    assert data.startswith(backup.MAGIC) and b"Keep me" not in data and b"SQLite" not in data
    assert client.post("/api/backup", json={"passphrase": "short"}).status_code == 400

    target = tmp_path / "restored"
    with pytest.raises(ValueError, match="Wrong passphrase"):
        backup.restore(data, "wrong horse", target)
    with pytest.raises(ValueError, match="Wrong passphrase"):
        backup.restore(data[:-5] + b"xxxxx", "correct horse", target)
    with pytest.raises(ValueError, match="not a Beseder backup"):
        backup.restore(b"PK\x03\x04 zip", "correct horse", target)
    backup.restore(data, "correct horse", target)

    restored = Config(data_dir=target)
    assert (restored.key_path.stat().st_mode & 0o777) == 0o600
    db = DB(restored.db_path)
    with db.conn() as c:
        assert c.execute("SELECT subject FROM messages").fetchone()[0] == "Keep me"
        secret = c.execute("SELECT secret FROM accounts").fetchone()[0]
    assert Vault(restored.key_path).decrypt(secret) == {"password": "x"}   # the key came along


def test_activity_log(client, core):
    for i in range(5):
        core.db.audit("moved", f"count={i}")
    r = client.get("/api/activity", params={"limit": 3}).json()
    assert [i["detail"] for i in r["items"]] == ["count=4", "count=3", "count=2"] and r["more"]
    r2 = client.get("/api/activity", params={"limit": 3, "before": r["more"]}).json()
    assert [i["detail"] for i in r2["items"]] == ["count=1", "count=0"] and r2["more"] is None


def test_backup_and_activity_need_unlocking(app, client):
    from fastapi.testclient import TestClient

    client.put("/api/lock", json={"new": "4321"})
    with TestClient(app, headers={"X-Beseder": "1"}) as other:
        assert other.post("/api/backup", json={"passphrase": "correct horse"}).status_code == 401
        assert other.get("/api/activity").status_code == 401
