"""Phase 6: the optional app lock."""

from fastapi.testclient import TestClient

import beseder.lock as lock_mod
from beseder.lock import check_passcode, hash_passcode

from .conftest import add_account, add_message


def test_passcode_hash():
    h = hash_passcode("1234")
    assert h.startswith("scrypt$") and "1234" not in h
    assert check_passcode("1234", h) and not check_passcode("1235", h) and not check_passcode("1234", "garbage")
    assert hash_passcode("1234") != h  # salted


def test_lock_off_by_default(client):
    assert client.get("/api/lock").json() == {"enabled": False, "unlocked": True, "wait": 0}
    assert client.get("/api/status").status_code == 200


def test_turning_the_lock_on_keeps_this_device_and_locks_the_others(app, client, core):
    acc = add_account(core)
    add_message(core, acc, 1)
    assert client.put("/api/lock", json={"new": "12"}).status_code == 400            # too short
    r = client.put("/api/lock", json={"new": "4321", "label": "Computer"})
    assert r.status_code == 200 and "httponly" in r.headers["set-cookie"].lower()
    assert "samesite=strict" in r.headers["set-cookie"].lower()
    assert client.get("/api/messages").status_code == 200                           # this device stays in

    with TestClient(app, headers={"X-Beseder": "1"}) as other:
        for path in ("/api/messages", "/api/status", "/api/events", "/api/messages/1", "/api/settings/ai"):
            r = other.get(path)
            assert r.status_code == 401 and r.json()["locked"] is True, path
        assert other.post("/api/sync").status_code == 401
        assert other.get("/api/health").status_code == 200 and other.get("/").status_code == 200
        assert other.get("/api/lock").json()["unlocked"] is False
        assert other.post("/api/lock/unlock", json={"passcode": "0000"}).status_code == 401
        assert other.post("/api/lock/unlock", json={"passcode": "4321", "label": "iPhone"}).status_code == 200
        assert other.get("/api/messages").status_code == 200
        other.post("/api/lock/lock")
        assert other.get("/api/messages").status_code == 401

    # Changing the passcode needs the current one, and signs out every other device.
    assert client.put("/api/lock", json={"current": "nope", "new": "9999"}).status_code == 403
    assert client.put("/api/lock", json={"current": "4321", "new": ""}).json() == {"enabled": False}
    with core.db.conn() as c:
        assert c.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 0
        assert "4321" not in str(c.execute("SELECT * FROM settings").fetchall())


def test_wrong_guesses_slow_down(app, client, monkeypatch):
    client.put("/api/lock", json={"new": "4321"})
    with TestClient(app, headers={"X-Beseder": "1"}) as other:
        for _ in range(lock_mod.FREE_ATTEMPTS):
            assert other.post("/api/lock/unlock", json={"passcode": "0000"}).status_code == 401
        r = other.post("/api/lock/unlock", json={"passcode": "4321"})     # even the right one must wait
        assert r.status_code == 429 and "try again in 30 s" in r.json()["detail"]
        assert other.get("/api/lock").json()["wait"] == 30
        app.state.lock._blocked_until = 0
        assert other.post("/api/lock/unlock", json={"passcode": "4321"}).status_code == 200


def test_sessions_expire(app, client, monkeypatch):
    client.put("/api/lock", json={"new": "4321"})
    import time
    real = time.time()
    monkeypatch.setattr(lock_mod.time, "time", lambda: real + lock_mod.SESSION_DAYS * 86400 + 60)
    assert client.get("/api/messages").status_code == 401


def test_unlock_needs_the_csrf_header(app, client):
    client.put("/api/lock", json={"new": "4321"})
    with TestClient(app) as bare:
        assert bare.post("/api/lock/unlock", json={"passcode": "4321"}).status_code == 403
