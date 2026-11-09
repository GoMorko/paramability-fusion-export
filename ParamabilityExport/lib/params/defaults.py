"""Which parameters are offered as sizes, which are ticked, and the label, kind and range of each.

The goal is a dialog that needs no typing: favourites the model reads are ticked, every size gets a range that
suits its kind, and a comment such as `Wall [1..6]` sets the range and is cut from the label.
"""
import math
import re

from ..package.units import unit_kind
from .expressions import ANGLE, LENGTH, SCALAR, referenced_names

LABEL_MAX = 120
COUNT_CAP = 64

_RANGE_COMMENT = re.compile(r"\s*\[\s*(-?(?:\d+\.?\d*|\.\d+))\s*\.\.\s*(-?(?:\d+\.?\d*|\.\d+))\s*\]\s*$")


def dim_of_unit(unit):
    """Unit powers (length, angle) of a Fusion unit, or None for a unit that is not offered."""
    return {"length": LENGTH, "angle": ANGLE, "count": SCALAR}.get(unit_kind(unit))


def is_numeric(p):
    return p.get("value_type", "numeric") != "text"


def size_value(p):
    """The number a parameter stands for in a formula: mm, degrees or the plain number."""
    kind = unit_kind(p.get("unit"))
    value = p["value"]
    if kind == "length":
        return value * 10.0
    if kind == "angle":
        return math.degrees(value)
    return value


def split_comment(comment):
    """(text, (min, max) or None): the comment without a trailing `[min..max]` and that range."""
    text = (comment or "").strip()
    m = _RANGE_COMMENT.search(text)
    if not m:
        return text, None
    return text[:m.start()].strip(), (float(m.group(1)), float(m.group(2)))


def label_for(p):
    """The comment (cut to 120 characters) or else the Fusion name."""
    text, _ = split_comment(p.get("comment"))
    return (text or p["name"])[:LABEL_MAX].strip() or p["name"]


def size_kind(p, count_names=()):
    """Recipe size kind: length, angle, count (whole number read as a pattern quantity) or number."""
    kind = unit_kind(p.get("unit"))
    if kind in ("length", "angle"):
        return kind
    value = p["value"]
    if p["name"] in count_names and value >= 1 and float(value).is_integer():
        return "count"
    return "number"


def _clean(x):
    return round(x, 6)


def default_range(kind, value):
    """(min, max) around the value: 50 to 200 percent, plus or minus 45 degrees, 1 to twice a count."""
    if kind == "count":
        return 1.0, float(max(value, min(COUNT_CAP, 2 * value)))
    if kind == "angle":
        lo, hi = value - 45.0, value + 45.0
        if 0.0 <= value <= 360.0:
            lo, hi = max(lo, 0.0), min(hi, 360.0)
        return _clean(lo), _clean(hi)
    if value == 0:
        return 0.0, 10.0
    a, b = value * 0.5, value * 2.0
    return _clean(min(a, b)), _clean(max(a, b))


def size_range(p, kind, value):
    """The range from the comment when it holds the value, else the default one."""
    _, found = split_comment(p.get("comment"))
    if found and found[0] <= value <= found[1]:
        return found
    return default_range(kind, value)


def reads_of(p):
    """Names a parameter reads: the Fusion dependency list plus the names found in its expression."""
    return list(dict.fromkeys(list(p.get("dependency_parameters", ())) + referenced_names(p.get("expression", ""))))


def _closure(start, lookup):
    """Names reached from the start parameters through formulas, transitively."""
    seen = set()
    stack = list(start)
    while stack:
        p = stack.pop()
        for dep in reads_of(p):
            if dep not in seen:
                seen.add(dep)
                if dep in lookup:
                    stack.append(lookup[dep])
    return seen


def _lookup(params, model_params):
    table = {m["name"]: m for m in model_params}
    table.update({p["name"]: p for p in params})
    return table


def names_read_by(params, model_params):
    """Names of user parameters that any model parameter of the body reads, through formulas, transitively."""
    user = {p["name"] for p in params}
    return _closure(model_params, _lookup(params, model_params)) & user


def count_names(params, model_params, quantity_refs=()):
    """User parameters read by a model parameter that sets a pattern quantity.

    `quantity_refs` are the model parameters the steps use as a pattern quantity (`{ name, expression }`, from the
    capture). A model parameter whose role text names a quantity counts as well; the role strings of Fusion are not
    all verified, so that match is on the word "quantity".
    """
    user = {p["name"] for p in params}
    lookup = _lookup(params, model_params)
    quantities = [lookup.get(ref["name"], ref) for ref in quantity_refs]
    quantities += [m for m in model_params if "quantity" in (m.get("role") or "").lower()]
    return _closure(quantities, lookup) & user


def is_offered(p):
    """A plain number parameter in a length, angle or no unit."""
    return (is_numeric(p) and p.get("kind") in ("length", "angle", "count")
            and dim_of_unit(p.get("unit")) is not None)


def default_ticked(params, model_params=()):
    """Favourites the body reads. With no favourite among them, every plain parameter the body reads."""
    read = names_read_by(params, model_params)
    offered = [p for p in params if is_offered(p) and p["name"] in read]
    favourites = [p["name"] for p in offered if p.get("is_favorite")]
    if favourites:
        return favourites
    return [p["name"] for p in offered]
