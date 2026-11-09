"""Texts and checks for the rows of the export dialog's parameter table. Pure: no Fusion imports.

A row is one offer from size_offers.offers plus what the person did to it: the tick, and the typed Min and Max.
The Fusion side only puts these texts into table cells.
"""
import html
import math
import re

from ..package.units import display_from_manifest, manifest_from_display, unit_kind
from ..params.defaults import COUNT_CAP
from ..params.expressions import format_number
from .size_offers import MAX_TICKED, limit_message, range_unit

SIZE, KEEP, LOCKED, FORMULA = "size", "keep", "locked", "formula"

HEADERS = {"tick": "", "name": "Parameter", "now": "Now", "used_by": "Used by", "min": "Min", "max": "Max",
           "status": "In Paramability"}
RATIOS = {"tick": 1, "name": 6, "now": 2, "used_by": 3, "min": 2, "max": 2, "status": 4}

NAME_WIDTH = 26
NAME_LINES = 3
HINT = ("Click a row to see its comment, formula or why it stays fixed. The export changes nothing in your design "
        "unless \"Check sizes in Fusion\" is ticked.")
_TYPED = re.compile(r"^\s*([-+]?[0-9.,]+)\s*([a-z]*)\s*$", re.I)
# A comma that starts exactly three digits ("2,500") reads as a thousands mark or a decimal comma: not guessed.
_AMBIGUOUS_COMMA = re.compile(r"^[-+]?[1-9][0-9]*,[0-9]{3}$")
# Typed ranges are compared with the number now at the precision the cells show.
RANGE_SLACK = 1e-4
_REASON_CHANGES = re.compile(r"\bit (changes|moves) ([^.,]+)[.,]", re.I)
CHECK_SIZES_TEXT = "Check sizes in Fusion (slower)"
CHECK_SIZES_TIP = ("Off: nothing in your design is changed. Every ticked size the copied steps use is saved with "
                   "the range in the table; a size that moves a sketch, a plane or a joint is marked \"may give "
                   "unexpected results\". On: each size is also tried in Fusion, so sketches follow the sizes and "
                   "a size that does not match is kept fixed or its range is shortened. This takes longer.")
KEEP_DOUBTFUL_TEXT = "Keep doubtful sizes fixed"
KEEP_DOUBTFUL_TIP = ("A size that the export cannot follow in every step stays a fixed number, instead of a size "
                     "marked \"may give unexpected results\".")


def columns(used_by=False):
    """Column keys left to right. A component export shows which parts read a parameter in place of Now."""
    return ("tick", "name", "used_by" if used_by else "now", "min", "max", "status")


def header(key, design_unit="mm"):
    """The column title. Min and Max name the design's length unit, since lengths are typed in it."""
    unit = design_unit if unit_kind(design_unit) == "length" else "mm"
    return "%s (%s)" % (HEADERS[key], unit) if key in ("min", "max") else HEADERS[key]


def column_ratio(keys):
    return ":".join(str(RATIOS[k]) for k in keys)


def number_text(value):
    return "" if value is None else format_number(value)


def _unit_of(offer):
    """The unit of the range cells of an offer: the design's length unit, deg, or '' for a count."""
    return offer["range_unit"] if "range_unit" in offer else range_unit(offer.get("kind"))


def cell_text(offer, value):
    """A range value (mm, deg or plain) as the cell shows it: lengths in the design's unit, angles with deg."""
    if value is None:
        return ""
    unit = _unit_of(offer)
    text = number_text(display_from_manifest(value, unit))
    return text + " deg" if unit_kind(unit) == "angle" else text


def range_text(offer, lo, hi):
    unit = {"length": " mm", "angle": " deg"}.get(offer.get("kind"), "")
    text = "%s to %s%s" % (number_text(lo), number_text(hi), unit)
    return text + ", whole numbers" if offer.get("kind") == "count" else text


def parse_number(text, unit=""):
    """The number typed in a Min or Max cell as manifest numbers (mm, deg or plain), else None.

    `unit` is the unit of a bare number. A typed unit that fits the kind is converted ("2 in"), a comma mark is
    accepted as a decimal point; text with more than one mark or an unclear "2,500" is refused.
    """
    found = _TYPED.match(text or "")
    if not found:
        return None
    number, typed = found.group(1), found.group(2).lower()
    if number.count(",") + number.count(".") > 1 or _AMBIGUOUS_COMMA.match(number):
        return None
    try:
        value = float(number.replace(",", "."))
    except ValueError:
        return None
    if not math.isfinite(value):
        return None
    if typed and unit_kind(typed) != unit_kind(unit):
        return None
    result = manifest_from_display(value, typed or unit) if (typed or unit) else value
    return round(result, 9) + 0.0 if result is not None and math.isfinite(result) else None


def short_reason(reason):
    """A few words for the table: 'changes a sketch' from the full reason."""
    found = _REASON_CHANGES.search(reason or "")
    if found:
        return "%s %s" % (found.group(1).lower(), found.group(2).strip())
    first = (reason or "").split(". ")[0].strip().rstrip(".")
    return first[:1].lower() + first[1:] if len(first) <= 30 else "see below"


def state_of(offer, ticked):
    if offer["state"] in (LOCKED, FORMULA):
        return offer["state"]
    return SIZE if ticked else KEEP


def status_text(offer, ticked, keep_doubtful=False):
    """What the row becomes. A doubtful size (`offer["doubt"]`) says so, or is fixed with `keep_doubtful`."""
    state = state_of(offer, ticked)
    if state == SIZE and offer.get("doubt"):
        return "fixed, " + short_reason(offer["doubt"]) if keep_doubtful else "size, may be unexpected"
    if state == SIZE:
        return "size"
    if state == KEEP:
        return "stays " + offer["now"]
    if state == LOCKED:
        return "fixed, " + short_reason(offer["reason"])
    return "formula"


def default_range_texts(offer):
    return cell_text(offer, offer["min"]), cell_text(offer, offer["max"])


def row_cells(offer, ticked, lo_text=None, hi_text=None, keep_doubtful=False):
    """What one row shows: now, status, min, max texts and whether the tick and the range cells can be used."""
    plain = offer["state"] in (SIZE, KEEP)
    default_lo, default_hi = default_range_texts(offer) if plain else ("", "")
    return {
        "now": offer["now"],
        "status": status_text(offer, ticked, keep_doubtful),
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
        unit = _unit_of(offer)
        unit = " " + unit if unit_kind(unit) == "length" else ""
        lines.append("Size in Paramability from %s to %s%s." % (html.escape(lo), html.escape(hi), unit))
    else:
        lines.append("Stays a fixed number. Tick it to make it a size.")
    if offer.get("doubt"):
        lines.append(html.escape(offer["doubt"]))
    return "<br>".join(lines)


def count_line(count, problem="", over=False, limit=MAX_TICKED):
    """The line under the details: a problem first, then the limit message, else the count."""
    if problem:
        return problem
    if over:
        return limit_message(limit)
    return "%d of %d sizes ticked. Every parameter also comes along as a variable." % (count, limit)


def _typed_or_default(offer, text, key):
    """The typed number, or the exact default when the cell still shows the default text."""
    if text is not None and text.strip() == default_range_texts(offer)[0 if key == "min" else 1]:
        return offer[key]
    return parse_number(text, _unit_of(offer))


def check_range(offer, lo_text, hi_text):
    """(problem, (min, max)) for the typed range of a ticked row, in manifest numbers (mm, deg or plain).

    The problem is '' when the range is fine.
    """
    name = offer["param"]
    lo, hi = _typed_or_default(offer, lo_text, "min"), _typed_or_default(offer, hi_text, "max")
    if lo is None or hi is None:
        return "%s: type a number for Min and Max." % name, None
    if lo >= hi:
        return "%s: Min must be below Max." % name, None
    value = offer["value"]
    if not lo - RANGE_SLACK <= value <= hi + RANGE_SLACK:
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
