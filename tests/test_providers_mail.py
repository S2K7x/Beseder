import httpx
import pytest
from imapclient.exceptions import LoginError

import beseder.mail.imap as imap_mod
from beseder.mail import providers
from beseder.mail.imap import LoginRejected, MailService
from beseder.mail.oauth_ms import MicrosoftOAuth


def test_every_provider_is_complete():
    for key, p in providers.PROVIDERS.items():
        assert p["label"] and p["mark"] and p["steps"], key
        if key != "imap":
            assert p["host"] and p["port"] == 993, key
        if p.get("auth") != "oauth":
            assert p["password_label"], key
    all_domains = [d for p in providers.PROVIDERS.values() for d in p["domains"]]
    assert len(all_domains) == len(set(all_domains)), "a domain belongs to two providers"


@pytest.mark.parametrize("email,kind,host", [
    ("me@yahoo.fr", "yahoo", "imap.mail.yahoo.com"),
    ("me@hotmail.fr", "outlook", "outlook.office365.com"),
    ("me@me.com", "icloud", "imap.mail.me.com"),
    ("me@wanadoo.fr", "orange", "imap.orange.fr"),
    ("me@gmx.fr", "gmx", "imap.gmx.net"),
    ("me@gmx.com", "gmx", "imap.gmx.com"),
    ("me@zohomail.eu", "zoho", "imap.zoho.eu"),
    ("me@laposte.net", "laposte", "imap.laposte.net"),
])
def test_detect_and_host(email, kind, host):
    assert providers.detect(email) == kind
    assert providers.host_for(kind, email) == host


def test_unknown_domain_is_not_guessed():
    assert providers.detect("me@my-own-domain.dev") is None


def test_icloud_tries_short_username_then_full_address():
    assert providers.usernames_for("icloud", "john@icloud.com") == ["john", "john@icloud.com"]
    assert providers.usernames_for("gmail", "john@gmail.com") == ["john@gmail.com"]
    assert providers.usernames_for("icloud", "john@icloud.com", "custom") == ["custom"]


class FakeConn:
    def __init__(self, accept, log):
        self.accept, self.log = accept, log

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def login(self, user, password):
        self.log.append(user)
        if user != self.accept:
            raise LoginError("no")

    def select_folder(self, *a, **k):
        return {}


def test_login_falls_back_to_the_next_username(monkeypatch):
    tried = []
    monkeypatch.setattr(imap_mod, "open_imap", lambda host, port, timeout=60: FakeConn("john@icloud.com", tried))
    assert MailService.test_login("h", 993, ["john", "john@icloud.com"], "pw") == "john@icloud.com"
    assert tried == ["john", "john@icloud.com"]
    with pytest.raises(LoginRejected):
        MailService.test_login("h", 993, ["nobody"], "pw")


def test_port_143_uses_starttls(monkeypatch):
    calls = []

    class Client:
        def __init__(self, host, port, ssl, timeout):
            calls.append(("open", port, ssl))

        def starttls(self):
            calls.append(("starttls",))

    monkeypatch.setattr(imap_mod, "IMAPClient", Client)
    imap_mod.open_imap("mail.example.com", 143)
    imap_mod.open_imap("mail.example.com", 993)
    assert calls == [("open", 143, False), ("starttls",), ("open", 993, True)]


def test_outlook_personal_only_app_retries_on_consumers():
    seen = []

    def handler(request: httpx.Request):
        seen.append(request.url.path)
        if "/common/" in request.url.path:
            return httpx.Response(400, json={"error": "invalid_request", "error_description":
                "AADSTS9002331: Application is configured for use by Microsoft Account users only."})
        return httpx.Response(200, json={"device_code": "d", "user_code": "ABCD-EFGH", "expires_in": 900,
                                         "interval": 5, "verification_uri": "https://microsoft.com/devicelogin"})

    oauth = MicrosoftOAuth(http=httpx.Client(transport=httpx.MockTransport(handler)))
    r = oauth.start("client-id", "common", "me@outlook.com", "Me")
    assert r["user_code"] == "ABCD-EFGH"
    assert seen == ["/common/oauth2/v2.0/devicecode", "/consumers/oauth2/v2.0/devicecode"]
    assert oauth.pending[r["flow_id"]].tenant == "consumers"


def test_providers_endpoint_and_add_account_validation(client):
    provs = client.get("/api/mail/providers").json()
    keys = [p["key"] for p in provs]
    assert keys[:4] == ["gmail", "outlook", "icloud", "yahoo"] and "orange" in keys
    assert client.post("/api/accounts", json={"kind": "outlook", "email": "a@outlook.com", "password": "x"}).status_code == 400
    assert client.post("/api/accounts", json={"kind": "nope", "email": "a@b.c", "password": "x"}).status_code == 400
    r = client.post("/api/accounts", json={"kind": "yahoo", "email": "no-at-sign", "password": "x"})
    assert r.status_code == 400 and "full email" in r.json()["detail"]
    r = client.post("/api/accounts", json={"kind": "yahoo", "email": "a@yahoo.fr", "password": " "})
    assert r.status_code == 400 and "app password" in r.json()["detail"]
