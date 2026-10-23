"""Calendar invites (iCalendar, RFC 5545): the event of a text/calendar part, for a card in
the reader. Only reading: Beseder never answers an invite (that would mean sending mail)."""

import re
from datetime import datetime, timezone
from email.message import EmailMessage
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

MAX_ICS = 256 * 1024
FIELD = 300  # longest text kept per field


def calendar_part(msg: EmailMessage):
    for part in msg.walk():
        if part.get_content_type() == "text/calendar":
            return part
    return None


def calendar_bytes(msg: EmailMessage) -> bytes | None:
    part = calendar_part(msg)
    if part is None:
        return None
    try:
        data = part.get_payload(decode=True) or b""
    except Exception:
        return None
    return data[:MAX_ICS] or None


def _unescape(value: str) -> str:
    value = re.sub(r"\\[nN]", "\n", value)
    return re.sub(r"\\([,;\\])", r"\1", value).strip()[:FIELD]


def _when(params: dict, value: str) -> dict | None:
    """{"iso": ..., "all_day": bool} or None. Times without a zone are kept as they are."""
    value = value.strip()
    try:
        if params.get("VALUE") == "DATE" or re.fullmatch(r"\d{8}", value):
            return {"iso": datetime.strptime(value, "%Y%m%d").date().isoformat(), "all_day": True}
        dt = datetime.strptime(value.rstrip("Z"), "%Y%m%dT%H%M%S")
    except ValueError:
        return None
    if value.endswith("Z"):
        dt = dt.replace(tzinfo=timezone.utc)
    elif params.get("TZID"):
        try:
            dt = dt.replace(tzinfo=ZoneInfo(params["TZID"].strip('"')))
        except (ZoneInfoNotFoundError, ValueError):
            pass  # Outlook names like "Romance Standard Time": keep the local time as written
    return {"iso": dt.isoformat(), "all_day": False}


def parse_invite(data: bytes) -> dict | None:
    """The first VEVENT: {title, start, end, location, organizer, method, status} or None."""
    text = data.decode("utf-8", errors="replace").replace("\r\n", "\n")
    text = re.sub(r"\n[ \t]", "", text)  # unfold long lines
    method, event, in_event = "", {}, False
    for line in text.split("\n"):
        if ":" not in line:
            continue
        head, value = line.split(":", 1)
        name, *raw_params = head.split(";")
        name = name.upper()
        params = dict(p.split("=", 1) for p in raw_params if "=" in p)
        params = {k.upper(): v for k, v in params.items()}
        if name == "METHOD":
            method = value.strip().upper()[:20]
        elif name == "BEGIN" and value.strip().upper() == "VEVENT":
            in_event = True
        elif name == "END" and value.strip().upper() == "VEVENT":
            break
        elif in_event and name not in event:
            event[name] = (params, value)
    if "DTSTART" not in event:
        return None
    start = _when(*event["DTSTART"])
    if start is None:
        return None
    organizer = ""
    if "ORGANIZER" in event:
        params, value = event["ORGANIZER"]
        addr = re.sub(r"(?i)^mailto:", "", value.strip())
        organizer = (_unescape(params.get("CN", "").strip('"')) or addr)[:FIELD]
    return {
        "title": _unescape(event.get("SUMMARY", ({}, ""))[1]) or "(no title)",
        "start": start,
        "end": _when(*event["DTEND"]) if "DTEND" in event else None,
        "location": _unescape(event.get("LOCATION", ({}, ""))[1]),
        "organizer": organizer,
        "method": method,  # REQUEST (invitation), CANCEL, REPLY...
        "status": event.get("STATUS", ({}, ""))[1].strip().upper()[:20],
    }
