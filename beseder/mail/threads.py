"""Conversations: every message gets a thread key shared by the whole exchange.

The key is the thread's root Message-ID when the headers allow it. A reply whose headers
point at a message Beseder already knows takes that message's key, so threads hold
together even when a mail client cuts the References header short.
"""

import re

_SUBJECT_PREFIX = re.compile(r"^\s*((re|fwd?|tr|aw|wg|sv|antw)\s*(\[\d+\])?\s*:\s*)+", re.I)


def ids_in(*headers: str) -> list[str]:
    """Message-IDs found in References / In-Reply-To, oldest first, without duplicates."""
    found = re.findall(r"<[^<>\s]+>", " ".join(h or "" for h in headers))
    return list(dict.fromkeys(found))


def normalize_subject(subject: str) -> str:
    return re.sub(r"\s+", " ", _SUBJECT_PREFIX.sub("", subject or "")).strip().lower()


def fallback_key(message_id: str, subject: str, addr: str) -> str:
    return message_id or f"subject:{normalize_subject(subject)}|{(addr or '').lower()}"


def thread_key(c, message_id: str, in_reply_to: str, refs: str, subject: str, addr: str) -> str:
    """Key for a new message. c is an open database connection."""
    parents = ids_in(refs, in_reply_to)
    if parents:
        marks = ",".join("?" * len(parents))
        row = c.execute(
            f"SELECT thread_key FROM thread_index WHERE message_id IN ({marks}) AND thread_key!=''"
            f" UNION ALL SELECT thread_key FROM sent_messages WHERE message_id IN ({marks}) AND thread_key!='' LIMIT 1",
            (*parents, *parents),
        ).fetchone()
        return row[0] if row else parents[0]
    if message_id:
        # Someone may already have answered a message we see only now.
        row = c.execute("SELECT thread_key FROM thread_index WHERE message_id=? AND thread_key!=''"
                        " UNION ALL SELECT thread_key FROM sent_messages WHERE message_id=? AND thread_key!='' LIMIT 1",
                        (message_id, message_id)).fetchone()
        if row:
            return row[0]
    return fallback_key(message_id, subject, addr)


def backfill(c) -> None:
    """One-time: gives a thread key to everything stored before conversations existed."""
    items = [("r", r["message_id"], r["in_reply_to"], r["refs"], r["date"])
             for r in c.execute("SELECT message_id, in_reply_to, refs, date FROM thread_index")]
    items += [("s", r["id"], r["message_id"], r["in_reply_to"], r["refs"], r["date"], r["subject"], r["to_addr"])
              for r in c.execute("SELECT id, message_id, in_reply_to, refs, date, subject, to_addr FROM sent_messages")]
    items.sort(key=lambda it: it[4] if it[0] == "r" else it[5])
    keys: dict[str, str] = {}
    for it in items:
        if it[0] == "r":
            _k, mid, irt, refs, _d = it
            subject = addr = ""
        else:
            _k, _id, mid, irt, refs, _d, subject, addr = it
        parents = ids_in(refs, irt)
        key = next((keys[p] for p in parents if p in keys), None) or (parents[0] if parents else None) \
            or keys.get(mid) or fallback_key(mid, subject, addr)
        if mid:
            keys[mid] = key
        if it[0] == "r":
            c.execute("UPDATE thread_index SET thread_key=? WHERE message_id=?", (key, mid))
        else:
            c.execute("UPDATE sent_messages SET thread_key=? WHERE id=?", (key, it[1]))
    for r in c.execute("SELECT id, message_id, subject, from_addr FROM messages WHERE thread_key=''").fetchall():
        c.execute("UPDATE messages SET thread_key=? WHERE id=?",
                  (keys.get(r["message_id"] or "") or fallback_key(r["message_id"] or "", r["subject"], r["from_addr"]), r["id"]))
