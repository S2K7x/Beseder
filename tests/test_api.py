from fastapi.testclient import TestClient

from .conftest import FakeProvider, add_account, add_message


def test_mutations_require_custom_header(app):
    with TestClient(app) as c:
        assert c.put("/api/settings/triage", json={"auto": True}).status_code == 403
        assert c.get("/api/status").status_code == 200


def test_unknown_host_rejected(app):
    with TestClient(app, base_url="http://evil.example") as c:
        assert c.get("/api/status").status_code == 400


def test_security_headers_and_pwa(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "script-src 'self'" in r.headers["content-security-policy"]
    assert client.get("/manifest.webmanifest").status_code == 200
    assert client.get("/api/status").headers["cache-control"] == "no-store"


def test_list_filters_and_category_rules(client, core):
    acc = add_account(core)
    m1 = add_message(core, acc, 1, from_addr="news@shop.com", subject="Sale")
    m2 = add_message(core, acc, 2, from_addr="news@shop.com", subject="More sales")
    add_message(core, acc, 3, seen=1)

    assert len(client.get("/api/messages").json()) == 3
    assert len(client.get("/api/messages", params={"unread": True}).json()) == 2
    assert [m["id"] for m in client.get("/api/messages", params={"q": "More"}).json()] == [m2]

    r = client.post(f"/api/messages/{m1}/category", json={"category": "promotions", "remember_sender": True})
    assert r.status_code == 200
    assert client.get(f"/api/messages/{m2}").json()["category"] == "promotions"
    assert client.get("/api/rules").json()[0]["addr"] == "news@shop.com"
    assert client.post(f"/api/messages/{m1}/category", json={"category": "trash"}).status_code == 400

    # A new message from the same sender is filed by the rule, without AI.
    m4 = add_message(core, acc, 4, from_addr="news@shop.com")
    core.apply_sender_rules()
    assert client.get(f"/api/messages/{m4}").json()["category_source"] == "rule"
    counts = client.get("/api/status").json()["unread_by_category"]
    assert counts["promotions"] == 3


def test_summary_endpoint_validates_ids(client, core, monkeypatch):
    acc = add_account(core)
    m1 = add_message(core, acc, 1, subject="Meeting tomorrow")
    add_message(core, acc, 2, seen=1)
    fake = FakeProvider(
        f'{{"overview": "A meeting.", "emails": [{{"id": "{m1}", "summary": "Meeting", "priority": "high"}}, {{"id": "12345"}}]}}'
    )
    monkeypatch.setattr(core, "provider", lambda: fake)
    r = client.post("/api/summary", json={}).json()
    assert r["count"] == 1
    assert r["items"] == [{"id": m1, "summary": "Meeting", "priority": "high", "subject": "Meeting tomorrow",
                           "from_name": "Alice", "date": "2026-10-11T10:00:00+00:00",
                           "from_addr": "alice@example.com"}]
    assert "Meeting tomorrow" in fake.calls[0]["user"]
    assert client.get("/api/summary/last").json()["overview"] == "A meeting."


def test_ai_not_configured_gives_clear_error(client, core):
    acc = add_account(core)
    add_message(core, acc, 1)
    r = client.post("/api/summary", json={})
    assert r.status_code == 502 and "Settings" in r.json()["detail"]


def test_auto_triage_toggle(client, core, monkeypatch):
    acc = add_account(core)
    m1 = add_message(core, acc, 1)
    fake = FakeProvider(f'{{"{m1}": "important"}}')
    monkeypatch.setattr(core, "provider", lambda: fake)
    assert client.post("/api/triage/run").status_code == 400  # off by default
    client.put("/api/settings/triage", json={"auto": True})
    assert client.get("/api/status").json()["auto_triage"] is True
    client.post("/api/triage/run")
    assert client.get(f"/api/messages/{m1}").json()["category"] == "important"


def test_draft_endpoint(client, core, monkeypatch):
    acc = add_account(core)
    m1 = add_message(core, acc, 1)
    monkeypatch.setattr(core, "provider", lambda: FakeProvider("Hi Alice,\n\nThanks!"))
    r = client.post(f"/api/messages/{m1}/draft", json={"instructions": "say thanks"}).json()
    assert r["body"].startswith("Hi Alice")
    assert r["to"] == "Alice <alice@example.com>"


def test_ai_settings_keep_key_secret(client, core):
    r = client.put("/api/settings/ai", json={"preset": "openrouter", "model": "m:free", "api_key": "sk-secret"})
    assert r.status_code == 200
    got = client.get("/api/settings/ai").json()
    assert got["has_key"] is True and "sk-secret" not in str(got)
    assert got["base_url"] == "https://openrouter.ai/api/v1"
    assert core.ai_config().api_key == "sk-secret"
    # Saving again without a key keeps the stored one.
    client.put("/api/settings/ai", json={"preset": "openrouter", "model": "autre"})
    assert core.ai_config().api_key == "sk-secret"
    assert client.put("/api/settings/ai", json={"preset": "nope"}).status_code == 400


def test_account_kind_validation(client):
    r = client.post("/api/accounts", json={"kind": "outlook", "email": "a@b.c", "password": "x"})
    assert r.status_code == 400


def test_profile_and_summary_language(client):
    client.put("/api/settings/profile", json={"name": "Sam", "summary_language": "French"})
    got = client.get("/api/settings/ai").json()
    assert got["my_name"] == "Sam" and got["summary_language"] == "French"


def test_health_and_onboarding_flag(client):
    assert client.get("/api/health").json() == {"ok": True}
    assert client.get("/api/status").json()["onboarded"] is False
    client.put("/api/settings/onboarded", json={"done": True})
    assert client.get("/api/status").json()["onboarded"] is True


def test_ollama_points_to_host_inside_docker(tmp_path):
    from beseder.config import Config
    from beseder.main import create_app

    app = create_app(Config(data_dir=tmp_path, run_scheduler=False, allowed_hosts=["testserver"], in_docker=True))
    with TestClient(app, headers={"X-Beseder": "1"}) as c:
        presets = c.get("/api/settings/ai").json()["presets"]
        assert presets["ollama"]["base_url"] == "http://host.docker.internal:11434/v1"
        c.put("/api/settings/ai", json={"preset": "ollama", "model": "llama3.2"})
        assert app.state.core.ai_config().base_url == "http://host.docker.internal:11434/v1"


def test_stored_html_is_sanitized_again_on_read(client, core):
    acc = add_account(core)
    mid = add_message(core, acc, 1)
    with core.db.conn() as c:
        c.execute("UPDATE messages SET body_html=? WHERE id=?",
                  ('<p>hi</p><svg onload="x()"></svg><a href="javascript:x()">y</a>', mid))
    html = client.get(f"/api/messages/{mid}").json()["body_html"]
    assert "<p>hi</p>" in html and "onload" not in html and "javascript:" not in html


def test_pagination_keeps_messages_that_share_a_date(client, core):
    acc = add_account(core)
    ids = [add_message(core, acc, uid, date="2026-10-20T10:00:00+00:00") for uid in range(1, 8)]
    seen, before = [], None
    while True:
        params = {"limit": 3}
        if before:
            params.update(before=before["date"], before_id=before["id"])
        page = client.get("/api/messages", params=params).json()
        if not page:
            break
        seen += [m["id"] for m in page]
        before = page[-1]
    assert sorted(seen) == sorted(ids) and len(seen) == len(set(seen))


def test_triage_keeps_batches_done_before_an_ai_failure(client, core, monkeypatch):
    from beseder.ai.providers import AIError

    acc = add_account(core)
    ids = [add_message(core, acc, uid) for uid in range(1, 21)]  # 2 batches of 15 + 5
    calls = {"n": 0}

    def reply(system, user):
        calls["n"] += 1
        if calls["n"] == 2:
            raise AIError("429: rate limited")
        return "{" + ",".join(f'"{i}": "other"' for i in ids) + "}"

    monkeypatch.setattr(core, "provider", lambda: FakeProvider(reply))
    client.put("/api/settings/triage", json={"auto": False})
    core.db.set_setting("auto_triage", True)
    r = client.post("/api/triage/run")
    assert r.status_code == 502 and "rate limited" in r.json()["detail"]
    with core.db.conn() as c:
        done = c.execute("SELECT COUNT(*) FROM messages WHERE category='other'").fetchone()[0]
    assert done == 15


def test_downloads_keep_their_sandbox_policy(client, core, monkeypatch):
    from .conftest import add_account, add_message

    mid = add_message(core, add_account(core), 1)
    monkeypatch.setattr(core.mail, "download_attachment", lambda message_id, idx: ("x.html", b"<script>1</script>"))
    r = client.get(f"/api/messages/{mid}/attachments/0")
    assert r.headers["content-security-policy"] == "sandbox; default-src 'none'"
    assert client.get("/").headers["content-security-policy"].startswith("default-src 'self'")
