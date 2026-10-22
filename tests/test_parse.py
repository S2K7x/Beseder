from email.message import EmailMessage

from beseder.mail.parse import parse_message, sanitize_html


def make(html=None, text=None, **headers):
    m = EmailMessage()
    m["From"] = headers.get("from", "Alice Martin <Alice@Exemple.com>")
    m["To"] = "moi@gmail.com"
    m["Subject"] = headers.get("subject", "Bonjour")
    m["Date"] = "Tue, 20 Oct 2026 09:30:00 +0200"
    m["Message-ID"] = "<abc@exemple.com>"
    if "list_unsubscribe" in headers:
        m["List-Unsubscribe"] = headers["list_unsubscribe"]
    if text is not None:
        m.set_content(text)
    if html is not None:
        if text is None:
            m.set_content(html, subtype="html")
        else:
            m.add_alternative(html, subtype="html")
    return m.as_bytes()


def test_multipart_plain_and_html():
    p = parse_message(make(text="Salut !\nÇa va ?", html="<p>Salut !</p>"))
    assert p.subject == "Bonjour"
    assert p.from_name == "Alice Martin"
    assert p.from_addr == "alice@exemple.com"
    assert p.body_text.startswith("Salut !")
    assert "<p>Salut !</p>" in p.body_html
    assert p.date == "2026-10-20T07:30:00+00:00"
    assert not p.list_unsubscribe


def test_html_only_gets_text_version():
    p = parse_message(make(html="<div>Ligne 1</div><div>Ligne&nbsp;2</div>", list_unsubscribe="<mailto:x@y>"))
    assert "Ligne 1" in p.body_text and "Ligne 2" in p.body_text
    assert p.list_unsubscribe


def test_sanitize_removes_active_content():
    dirty = (
        '<p style="color:red" onclick="steal()">hi</p><script>alert(1)</script>'
        '<img src="https://t.co/pixel.gif" onerror="x()"><iframe src="https://evil"></iframe>'
        '<form action="https://evil"><input name="pw"></form><a href="javascript:alert(1)">x</a>'
        '<a href="https://ok.com">ok</a><style>body{}</style>'
    )
    clean = sanitize_html(dirty)
    for bad in ("script", "onclick", "onerror", "iframe", "<form", "<input", "javascript:", "<style"):
        assert bad not in clean
    assert 'style="color:red"' in clean
    assert 'target="_blank"' in clean


def test_headers_only_and_bad_input():
    p = parse_message(make(text="gros fichier"), headers_only=True)
    assert p.truncated and p.body_text == "" and "volumineux" in p.snippet
    junk = parse_message(b"pas vraiment un mail")
    assert junk.subject == ""


def test_broken_charset_does_not_crash():
    raw = (
        b"From: a@b.c\r\nSubject: x\r\nContent-Type: text/plain; charset=nimportequoi\r\n"
        b"Content-Transfer-Encoding: 8bit\r\n\r\nH\xe9llo"
    )
    p = parse_message(raw)
    assert "llo" in p.body_text
