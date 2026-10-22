from email.message import EmailMessage

from beseder.mail.parse import parse_message, sanitize_html


def make(html=None, text=None, **headers):
    m = EmailMessage()
    m["From"] = headers.get("from", "Alice Martin <Alice@Example.com>")
    m["To"] = "me@gmail.com"
    m["Subject"] = headers.get("subject", "Hello")
    m["Date"] = "Tue, 20 Oct 2026 09:30:00 +0200"
    m["Message-ID"] = "<abc@example.com>"
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
    p = parse_message(make(text="Hi!\nHow are you?", html="<p>Hi!</p>"))
    assert p.subject == "Hello"
    assert p.from_name == "Alice Martin"
    assert p.from_addr == "alice@example.com"
    assert p.body_text.startswith("Hi!")
    assert "<p>Hi!</p>" in p.body_html
    assert p.date == "2026-10-20T07:30:00+00:00"
    assert not p.list_unsubscribe


def test_html_only_gets_text_version():
    p = parse_message(make(html="<div>Line 1</div><div>Line&nbsp;2</div>", list_unsubscribe="<mailto:x@y>"))
    assert "Line 1" in p.body_text and "Line 2" in p.body_text
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
    p = parse_message(make(text="big file"), headers_only=True)
    assert p.truncated and p.body_text == "" and "Large message" in p.snippet
    junk = parse_message(b"not really an email")
    assert junk.subject == ""


def test_broken_charset_does_not_crash():
    raw = (
        b"From: a@b.c\r\nSubject: x\r\nContent-Type: text/plain; charset=whatever\r\n"
        b"Content-Transfer-Encoding: 8bit\r\n\r\nH\xe9llo"
    )
    p = parse_message(raw)
    assert "llo" in p.body_text


def test_inline_images_are_embedded_and_not_listed_as_attachments():
    from email.utils import make_msgid

    m = EmailMessage()
    m["From"], m["Subject"] = "a@b.c", "logo"
    cid = make_msgid()[1:-1]
    m.set_content("text")
    m.add_alternative(f'<p>Hi</p><img src="cid:{cid}"><img src="cid:missing@x">', subtype="html")
    m.get_payload()[1].add_related(b"\x89PNG fake", maintype="image", subtype="png", cid=f"<{cid}>")
    m.add_attachment(b"%PDF", maintype="application", subtype="pdf", filename="real.pdf")
    p = parse_message(m.as_bytes())
    assert "data:image/png;base64," in p.body_html
    assert [a[1] for a in p.attachments] == ["real.pdf"]


def test_svg_inline_images_are_not_embedded():
    from email.utils import make_msgid

    m = EmailMessage()
    m["From"], m["Subject"] = "a@b.c", "svg"
    cid = make_msgid()[1:-1]
    m.set_content("text")
    m.add_alternative(f'<img src="cid:{cid}">', subtype="html")
    m.get_payload()[1].add_related(b"<svg onload='x()'/>", maintype="image", subtype="svg+xml", cid=f"<{cid}>")
    assert "data:image/svg" not in parse_message(m.as_bytes()).body_html


def test_unsubscribe_headers():
    from beseder.mail.parse import parse_unsubscribe

    assert parse_unsubscribe("<mailto:u@x.com?subject=stop>, <https://x.com/u?id=1>", "List-Unsubscribe=One-Click") == (
        "https://x.com/u?id=1", "mailto:u@x.com?subject=stop", True)
    assert parse_unsubscribe("<https://x.com/u>", "") == ("https://x.com/u", "", False)
    # Plain http, javascript: and friends are ignored.
    assert parse_unsubscribe("<http://x.com/u>, <javascript:alert(1)>", "List-Unsubscribe=One-Click") == ("", "", False)
    m = EmailMessage()
    m["From"], m["Subject"] = "News <news@x.com>", "Weekly"
    m["List-Unsubscribe"] = "<https://x.com/unsub/abc>"
    m["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"
    m.set_content("hi")
    p = parse_message(m.as_bytes())
    assert (p.unsub_url, p.unsub_one_click, p.list_unsubscribe) == ("https://x.com/unsub/abc", True, True)


def test_strip_quoted_keeps_only_the_new_text():
    from beseder.mail.parse import strip_quoted

    assert strip_quoted("Sounds good, Tuesday?\n\nSam\n\nOn Mon, 19 Oct 2026, Alice <a@x.com> wrote:\n> Hi") == \
        "Sounds good, Tuesday?\n\nSam"
    assert strip_quoted("Ok pour moi\n\nLe lun. 19 oct. 2026 à 09:00, Alice <a@x.com> a écrit :\n> Salut") == "Ok pour moi"
    assert strip_quoted("Yes\n\n-----Original Message-----\nFrom: Bob") == "Yes"
    assert strip_quoted("Inline:\n> question?\nanswer") == "Inline:\nanswer"
    assert strip_quoted("On it\n\nOn Mon, 19 Oct 2026 at 09:00, Alice Martin <alice@example.com>\nwrote:\n> x") == "On it"
