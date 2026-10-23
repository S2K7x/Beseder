"""Static checks on the front end (no browser needed)."""

import re
from pathlib import Path

APP = (Path(__file__).resolve().parent.parent / "web" / "app.js").read_text()


def _calls(name):
    for m in re.finditer(rf"\.{name}\(", APP):
        i = j = m.end()
        depth = 1
        while depth:
            depth += APP[j] in "([{"
            depth -= APP[j] in ")]}"
            j += 1
        top, depth = "", 0
        for ch in APP[i:j - 1]:  # the arguments, without what's nested inside them
            depth += ch in "([{"
            depth -= ch in ")]}"
            if depth == 0:
                top += ch
        yield APP[:m.start()].count("\n") + 1, top


def test_dom_calls_never_get_null():
    """replaceChildren() and append() print "null" for a null argument: use put() instead."""
    bad = [line for name in ("replaceChildren", "append") for line, top in _calls(name)
           if re.search(r"[?:]\s*null\b|&&", top)]
    assert not bad, f"web/app.js lines {bad}: pass possibly-null children through put()"


def test_no_inner_html():
    assert not re.search(r"\.(innerHTML|outerHTML)\s*=|insertAdjacentHTML|document\.write", APP)
