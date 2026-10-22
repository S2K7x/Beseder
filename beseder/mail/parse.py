"""Raw message parsing and HTML sanitizing."""

import base64
import html as html_lib
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
from email.utils import getaddresses, parsedate_to_datetime

import nh3

_TAGS = set(nh3.ALLOWED_TAGS) | {"font"}
_ATTRS = {
    "*": {"style", "align", "valign", "width", "height", "bgcolor", "color", "dir", "title"},
    "a": {"href"},
    "img": {"src", "alt"},
    "td": {"colspan", "rowspan"},
    "th": {"colspan", "rowspan"},
    "table": {"border", "cellpadding", "cellspacing"},
    "font": {"face", "size"},
}


def sanitize_html(raw: str) -> str:
    """Strips scripts, event handlers, forms, iframes... Keeps the formatting."""
    return nh3.clean(
        raw,
        tags=_TAGS,
        clean_content_tags={"script", "style", "title"},
        attributes=_ATTRS,
        url_schemes={"http", "https", "mailto", "cid", "data"},
        link_rel="noopener noreferrer nofollow",
        set_tag_attribute_values={"a": {"target": "_blank"}},
        strip_comments=True,
    )


def html_to_text(raw: str) -> str:
    text = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</tr>|</h\d>|</li>", "\n", raw)
    text = nh3.clean(text, tags=set(), clean_content_tags={"script", "style", "title"})
    text = html_lib.unescape(text)
    text = re.sub(r"[ \t ]+", " ", text)
    return re.sub(r"\n\s*\n+", "\n\n", text).strip()


def _addr_list(msg: EmailMessage, header: str) -> list[tuple[str, str]]:
    values = msg.get_all(header, [])
    try:
        return [(n, a) for n, a in getaddresses([str(v) for v in values]) if a]
    except Exception:
        return []


def _fmt_addrs(pairs: list[tuple[str, str]]) -> str:
    return ", ".join(f"{n} <{a}>" if n else a for n, a in pairs)


def _get_content(part) -> str:
    try:
        return part.get_content()
    except Exception:
        payload = part.get_payload(decode=True) or b""
        return payload.decode("utf-8", errors="replace")


@dataclass
class ParsedMessage:
    message_id: str
    in_reply_to: str
    refs: str
    subject: str
    from_name: str
    from_addr: str
    reply_to: str
    to_addrs: str
    cc_addrs: str
    date: str
    snippet: str
    body_text: str
    body_html: str
    list_unsubscribe: bool
    truncated: bool
    attachments: list = field(default_factory=list)  # [(idx, filename, content_type, size)]


# Images embedded in the HTML (logos, signatures) referenced as cid:...
INLINE_TYPES = {"image/png", "image/jpeg", "image/gif", "image/webp"}  # no SVG: it can carry scripts
MAX_INLINE_IMAGE = 512 * 1024
MAX_INLINE_TOTAL = 2 * 1024 * 1024


def _content_id(part) -> str:
    return str(part.get("Content-ID", "") or "").strip().strip("<>")


def _is_inline_image(part) -> bool:
    return (part.get_content_type().startswith("image/") and bool(_content_id(part))
            and part.get_content_disposition() != "attachment")


def _attachment_parts(msg: EmailMessage) -> list:
    """Real attachments only: images embedded in the HTML are shown in the message instead."""
    try:
        return [p for p in msg.iter_attachments() if not _is_inline_image(p)]
    except Exception:
        return []


def embed_inline_images(msg: EmailMessage, html: str) -> str:
    """Replaces cid: references with data: URIs, so logos and signatures show up offline."""
    wanted = set(re.findall(r"cid:([^\"'\s>)]+)", html, re.I))
    if not wanted:
        return html
    found, total = {}, 0
    for part in msg.walk():
        cid = _content_id(part)
        if cid not in wanted or part.get_content_type() not in INLINE_TYPES:
            continue
        try:
            data = part.get_payload(decode=True) or b""
        except Exception:
            continue
        if len(data) > MAX_INLINE_IMAGE or total + len(data) > MAX_INLINE_TOTAL:
            continue
        total += len(data)
        found[cid] = f"data:{part.get_content_type()};base64,{base64.b64encode(data).decode()}"
    return re.sub(r"cid:([^\"'\s>)]+)", lambda m: found.get(m.group(1), m.group(0)), html, flags=re.I)


def list_attachments(msg: EmailMessage) -> list[tuple[int, str, str, int]]:
    out = []
    for idx, part in enumerate(_attachment_parts(msg)):
        try:
            data = part.get_payload(decode=True) or b""
        except Exception:
            data = b""
        name = part.get_filename() or f"attachment-{idx + 1}"
        out.append((idx, name[:200], part.get_content_type(), len(data)))
    return out


def extract_attachment(raw: bytes, idx: int) -> tuple[str, bytes]:
    """Returns (filename, bytes) of one attachment, using the same numbering as list_attachments."""
    msg = BytesParser(policy=policy.default).parsebytes(raw)
    parts = _attachment_parts(msg)
    if not 0 <= idx < len(parts):
        raise LookupError("Attachment not found")
    part = parts[idx]
    return (part.get_filename() or f"attachment-{idx + 1}"), (part.get_payload(decode=True) or b"")


def parse_message(raw: bytes, fallback_date: datetime | None = None, headers_only: bool = False) -> ParsedMessage:
    msg = BytesParser(policy=policy.default).parsebytes(raw)

    def header(name: str) -> str:
        try:
            return str(msg.get(name, "") or "").strip()
        except Exception:
            return ""

    from_pairs = _addr_list(msg, "from")
    from_name, from_addr = from_pairs[0] if from_pairs else ("", "")

    try:
        dt = parsedate_to_datetime(header("date"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
    except Exception:
        dt = fallback_date or datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)

    text, html = "", ""
    if not headers_only:
        try:
            part = msg.get_body(preferencelist=("plain",))
            if part is not None:
                text = _get_content(part)
            part = msg.get_body(preferencelist=("html",))
            if part is not None:
                html = embed_inline_images(msg, _get_content(part))
        except Exception:
            pass
    if html and not text:
        text = html_to_text(html)
    text = text.replace("\r\n", "\n").strip()

    snippet = re.sub(r"\s+", " ", text)[:200]
    if headers_only:
        snippet = "(Large message: only the headers were imported. Open it in your mail app.)"

    return ParsedMessage(
        message_id=header("message-id"),
        in_reply_to=header("in-reply-to"),
        refs=header("references"),
        subject=header("subject"),
        from_name=from_name,
        from_addr=from_addr.lower(),
        reply_to=_fmt_addrs(_addr_list(msg, "reply-to")),
        to_addrs=_fmt_addrs(_addr_list(msg, "to")),
        cc_addrs=_fmt_addrs(_addr_list(msg, "cc")),
        date=dt.astimezone(timezone.utc).isoformat(timespec="seconds"),
        snippet=snippet,
        body_text=text,
        body_html=sanitize_html(html) if html else "",
        list_unsubscribe=bool(header("list-unsubscribe")),
        truncated=headers_only,
        attachments=[] if headers_only else list_attachments(msg),
    )
