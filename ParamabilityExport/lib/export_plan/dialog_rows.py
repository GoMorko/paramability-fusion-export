"""Texts and checks for the rows of the export dialog's parameter table. Pure: no Fusion imports.

A row is one offer from size_offers.offers plus what the person did to it: the tick, and the typed Min and Max.
The Fusion side only puts these texts into table cells.
"""
import html
import math
import re

from ..params.defaults import COUNT_CAP
from ..params.expressions import format_number
from .size_offers import MAX_TICKED, limit_message

SIZE, KEEP, LOCKED, FORMULA = "size", "keep", "locked", "formula"

HEADERS = {"tick": "", "name": "Parameter", "now": "Now", "used_by": "Used by", "min": "Min", "max": "Max",
           "status": "In Paramability"}
RATIOS = {"tick": 1, "name": 6, "now": 2, "used_by": 3, "min": 2, "max": 2, "status": 4}

NAME_WIDTH = 26
NAME_LINES = 3
HINT = "Click a row to see its comment, formula or why it stays fixed."
_UNIT_SUFFIX = re.compile(r"\s*(mm|deg)\s*$", re.I)
_REASON_CHANGES = re.compile(r"\bit (?:changes|moves) ([^.]+)\.", re.I)


def columns(used_by=False):
    """Column keys left to right. A component export shows which parts read a parameter in place of Now."""
    return ("tick", "name", "used_by" if used_by else "now", "min", "max", "status")


def column_ratio(keys):
    return ":".join(str(RATIOS[k]) for k in keys)


def number_text(value):
    return "" if value is None else format_number(value)


def range_text(offer, lo, hi):
    unit = {"length": " mm", "angle": " deg"}.get(offer.get("kind"), "")
    text = "%s to %s%s" % (number_text(lo), number_text(hi), unit)
    return text + ", whole numbers" if offer.get("kind") == "count" else text


def parse_number(text):
    """The number typed in a Min or Max cell (a trailing mm or deg and a comma mark are accepted), else None."""
    cleaned = _UNIT_SUFFIX.sub("", (text or "").strip()).replace(",", ".")
    try:
        value = float(cleaned)
    except ValueError:
        return None
    return value if math.isfinite(value) else None


def short_reason(reason):
    """A few words for the table: 'changes a sketch' from the full reason."""
    found = _REASON_CHANGES.search(reason or "")
    if found:
        return "changes " + found.group(1).strip()
    first = (reason or "").split(". ")[0].strip().rstrip(".")
    return first[:1].lower() + first[1:] if len(first) <= 30 else "see below"


def state_of(offer, ticked):
    if offer["state"] in (LOCKED, FORMULA):
        return offer["state"]
    return SIZE if ticked else KEEP


def status_text(offer, ticked):
    state = state_of(offer, ticked)
    if state == SIZE:
        return "size"
    if state == KEEP:
        return "stays " + offer["now"]
    if state == LOCKED:
        return "fixed, " + short_reason(offer["reason"])
    return "formula"


def default_range_texts(offer):
    return number_text(offer["min"]), number_text(offer["max"])


def row_cells(offer, ticked, lo_text=None, hi_text=None):
    """What one row shows: now, status, min, max texts and whether the tick and the range cells can be used."""
    plain = offer["state"] in (SIZE, KEEP)
    default_lo, default_hi = default_range_texts(offer) if plain else ("", "")
    return {
        "now": offer["now"],
        "status": status_text(offer, ticked),
        "min": default_lo if lo_text is None else lo_text,
        "max": default_hi if hi_text is None else hi_text,
        "tick_enabled": bool(offer["enabled"]),
        "range_enabled": plain and bool(offer["enabled"]) and bool(ticked),
    }


def used_by_text(offer):
    return offer.get("used_by", "")


def wrap_name(name, width=NAME_WIDTH, max_lines=NAME_LINES):
    """(html, line count) for a long name broken after an underscore, so it reads in a narrow cell."""
    lines, rest = [], name
    while len(rest) > width and len(lines) < max_lines - 1:
        cut = rest.rfind("_", 0, width) + 1
        cut = cut if cut > width // 3 else width
        lines.append(rest[:cut])
        rest = rest[cut:]
    lines.append(rest)
    return "<br>".join(html.escape(line) for line in lines), len(lines)


def details_html(offer, ticked, lo_text=None, hi_text=None):
    """Html for the box under the table: the name, then the comment, formula, range or reason of the row."""
    name = "<b>%s</b>" % html.escape(offer["param"])
    now = html.escape(offer["now"])
    if offer["state"] == LOCKED:
        return "%s, %s<br>%s" % (name, now, html.escape(offer["reason"]))
    if offer["state"] == FORMULA:
        formula = html.escape(offer["formula"])
        return "%s = %s<br>Now %s. It follows the parameters it reads." % (name, formula, now)
    lines = ["%s, %s" % (name, now)]
    if offer["comment"]:
        lines.append("Comment: %s" % html.escape(offer["comment"]))
    lo = default_range_texts(offer)[0] if lo_text is None else lo_text
    hi = default_range_texts(offer)[1] if hi_text is None else hi_text
    if ticked:
        lines.append("Size in Paramability from %s to %s." % (html.escape(lo), html.escape(hi)))
    else:
        lines.append("Stays a fixed number. Tick it to make it a size.")
    return "<br>".join(lines)


def count_line(count, problem="", over=False, limit=MAX_TICKED):
    """The line under the details: a problem first, then the limit message, else the count."""
    if problem:
        return problem
    if over:
        return limit_message(limit)
    return "%d of %d sizes ticked. Every parameter also comes along as a variable." % (count, limit)


def check_range(offer, lo_text, hi_text):
    """(problem, (min, max)) for the typed range of a ticked row. The problem is '' when the range is fine."""
    name = offer["param"]
    lo, hi = parse_number(lo_text), parse_number(hi_text)
    if lo is None or hi is None:
        return "%s: type a number for Min and Max." % name, None
    if lo >= hi:
        return "%s: Min must be below Max." % name, None
    value = offer["value"]
    if not lo <= value <= hi:
        return "%s: the number now, %s, must sit between Min and Max." % (name, offer["now"]), None
    if offer["kind"] == "count":
        if lo != int(lo) or hi != int(hi) or lo < 1:
            return "%s: a count needs whole numbers from 1 up." % name, None
        if hi > max(COUNT_CAP, value):
            return "%s: Max can be at most %d." % (name, max(COUNT_CAP, value)), None
    return "", (lo, hi)


def read_ranges(offers, ticks, lo_texts, hi_texts):
    """({Fusion name: (min, max)} of the ticked rows, the first problem text or '')."""
    ranges, problem = {}, ""
    for offer, ticked, lo_text, hi_text in zip(offers, ticks, lo_texts, hi_texts):
        if not ticked or state_of(offer, ticked) != SIZE:
            continue
        found, pair = check_range(offer, lo_text, hi_text)
        if found:
            problem = problem or found
        else:
            ranges[offer["param"]] = pair
    return ranges, problem
