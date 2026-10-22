"""Raw message parsing and HTML sanitizing."""

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


def _attachment_parts(msg: EmailMessage) -> list:
    try:
        return list(msg.iter_attachments())
    except Exception:
        return []


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
                html = _get_content(part)
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
