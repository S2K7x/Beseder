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
    m1 = add_message(core, acc, 1, from_addr="news@shop.com", subject="Soldes")
    m2 = add_message(core, acc, 2, from_addr="news@shop.com", subject="Encore des soldes")
    add_message(core, acc, 3, seen=1)

    assert len(client.get("/api/messages").json()) == 3
    assert len(client.get("/api/messages", params={"unread": True}).json()) == 2
    assert [m["id"] for m in client.get("/api/messages", params={"q": "Encore"}).json()] == [m2]

    r = client.post(f"/api/messages/{m1}/category", json={"category": "promotions", "remember_sender": True})
    assert r.status_code == 200
    assert client.get(f"/api/messages/{m2}").json()["category"] == "promotions"
    assert client.get("/api/rules").json()[0]["addr"] == "news@shop.com"
    assert client.post(f"/api/messages/{m1}/category", json={"category": "poubelle"}).status_code == 400

    # Un nouveau mail du même expéditeur est classé par la règle, sans IA.
    m4 = add_message(core, acc, 4, from_addr="news@shop.com")
    core.apply_sender_rules()
    assert client.get(f"/api/messages/{m4}").json()["category_source"] == "rule"
    counts = client.get("/api/status").json()["unread_by_category"]
    assert counts["promotions"] == 3


def test_summary_endpoint_validates_ids(client, core, monkeypatch):
    acc = add_account(core)
    m1 = add_message(core, acc, 1, subject="RDV demain")
    add_message(core, acc, 2, seen=1)
    fake = FakeProvider(
        f'{{"apercu": "Un RDV.", "mails": [{{"id": "{m1}", "resume": "RDV", "priorite": "haute"}}, {{"id": "12345"}}]}}'
    )
    monkeypatch.setattr(core, "provider", lambda: fake)
    r = client.post("/api/summary", json={}).json()
    assert r["count"] == 1
    assert r["items"] == [{"id": m1, "summary": "RDV", "priority": "haute", "subject": "RDV demain", "from_name": "Alice"}]
    assert "RDV demain" in fake.calls[0]["user"]


def test_ai_not_configured_gives_clear_error(client, core):
    acc = add_account(core)
    add_message(core, acc, 1)
    r = client.post("/api/summary", json={})
    assert r.status_code == 502 and "Configure" in r.json()["detail"]


def test_auto_triage_toggle(client, core, monkeypatch):
    acc = add_account(core)
    m1 = add_message(core, acc, 1)
    fake = FakeProvider(f'{{"{m1}": "important"}}')
    monkeypatch.setattr(core, "provider", lambda: fake)
    assert client.post("/api/triage/run").status_code == 400  # désactivé par défaut
    client.put("/api/settings/triage", json={"auto": True})
    assert client.get("/api/status").json()["auto_triage"] is True
    client.post("/api/triage/run")
    assert client.get(f"/api/messages/{m1}").json()["category"] == "important"


def test_draft_endpoint(client, core, monkeypatch):
    acc = add_account(core)
    m1 = add_message(core, acc, 1)
    monkeypatch.setattr(core, "provider", lambda: FakeProvider("Bonjour Alice,\n\nMerci !"))
    r = client.post(f"/api/messages/{m1}/draft", json={"instructions": "remercie"}).json()
    assert r["body"].startswith("Bonjour Alice")
    assert r["to"] == "Alice <alice@exemple.com>"


def test_ai_settings_keep_key_secret(client, core):
    r = client.put("/api/settings/ai", json={"preset": "openrouter", "model": "m:free", "api_key": "sk-secret"})
    assert r.status_code == 200
    got = client.get("/api/settings/ai").json()
    assert got["has_key"] is True and "sk-secret" not in str(got)
    assert got["base_url"] == "https://openrouter.ai/api/v1"
    assert core.ai_config().api_key == "sk-secret"
    # Réenregistrer sans clé garde l'ancienne.
    client.put("/api/settings/ai", json={"preset": "openrouter", "model": "autre"})
    assert core.ai_config().api_key == "sk-secret"
    assert client.put("/api/settings/ai", json={"preset": "nope"}).status_code == 400


def test_account_kind_validation(client):
    r = client.post("/api/accounts", json={"kind": "outlook", "email": "a@b.c", "password": "x"})
    assert r.status_code == 400
