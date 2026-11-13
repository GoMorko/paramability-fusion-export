"""Which parameters are offered as sizes, which are ticked, and the label, kind and range of each.

The goal is a dialog that needs no typing: favourites the model reads are ticked, every size gets a range that
suits its kind, and a comment such as `Wall [1..6]` sets the range.
"""
import re

from ..package.units import unit_kind
from .dependencies import Graph, names_in
from .expressions.translation import unit_scale
from .expressions.units import internal_factor

LABEL_MAX = 120
COUNT_CAP = 64

_RANGE_COMMENT = re.compile(r"\s*\[\s*(-?(?:\d+\.?\d*|\.\d+))\s*\.\.\s*(-?(?:\d+\.?\d*|\.\d+))\s*\]\s*$")


def dim_of_unit(unit):
    """Unit powers (length, angle) of a Fusion unit, or None for a unit that is not built from lengths and angles."""
    found = unit_scale(unit)
    return found[0] if found is not None else None


def is_numeric(p):
    return p.get("value_type", "numeric") != "text"


def size_value(p):
    """The number a parameter stands for in a formula: mm, degrees (or a power of them) or the plain number."""
    dim = dim_of_unit(p.get("unit"))
    return p["value"] if dim is None else p["value"] * internal_factor(dim)


def split_comment(comment):
    """(text, (min, max) or None): the comment without a trailing `[min..max]` and that range."""
    text = (comment or "").strip()
    m = _RANGE_COMMENT.search(text)
    if not m:
        return text, None
    return text[:m.start()].strip(), (float(m.group(1)), float(m.group(2)))


def label_for(p):
    """The label of a recipe size: the parameter name as Fusion shows it (cut to 120 characters). The comment stays
    in the manifest `parameters` list, where Paramability reads it as the description."""
    return p["name"][:LABEL_MAX].strip() or p["name"]


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


def reads_of(p, known=None):
    """Names a parameter reads: the Fusion dependency list plus the names found in its expression
    (`dependencies.names_in`; `known` lets a formula the parser refuses still give the names it holds)."""
    return list(dict.fromkeys(list(p.get("dependency_parameters", ())) + names_in(p.get("expression", ""), known)))


def names_read_by(params, model_params):
    """Names of user parameters that any model parameter of the body reads, through formulas, transitively."""
    graph = Graph(params, model_params)
    return graph.closure([m["name"] for m in model_params]) & {p["name"] for p in params}


def count_names(params, model_params, quantity_refs=()):
    """User parameters read by a model parameter that sets a pattern quantity.

    `quantity_refs` are the model parameters the steps use as a pattern quantity (`{ name, expression }`, from the
    capture). A model parameter whose role text names a quantity counts as well; the role strings of Fusion are not
    all verified, so that match is on the word "quantity".
    """
    refs = {ref["name"]: ref for ref in quantity_refs}
    model = list(model_params) + [ref for name, ref in refs.items() if name not in {m["name"] for m in model_params}]
    graph = Graph(params, model)
    starts = list(refs) + [m["name"] for m in model_params if "quantity" in (m.get("role") or "").lower()]
    return graph.closure(starts) & {p["name"] for p in params}


def is_offered(p):
    """A plain number parameter in a length, angle or no unit: one the person can tick as a size."""
    return (is_numeric(p) and p.get("kind") in ("length", "angle", "count")
            and dim_of_unit(p.get("unit")) is not None)


def body_usage(params, model_params=(), linked=()):
    """`dependencies.Usage` of a body: the user parameters its model parameters read at any depth, and `linked`, the
    parameters that may reach one of its sketches through the geometry of another component
    (`geometry_links.linked_names`), with the bases of a derived one among them."""
    return Graph(params, model_params).usage([m["name"] for m in model_params], linked)


def default_ticked(params, model_params=(), linked=(), usage=None):
    """Favourites the body uses. With no favourite among them, every plain parameter the body uses.

    The body uses what its model parameters read and what `linked` names, at any depth (`body_usage`, or `usage`
    when given). A plain parameter that only a favourite formula reads counts as a favourite: the formula cannot
    change without it."""
    usage = usage or body_usage(params, model_params, linked)
    graph = Graph(params)
    offered = [p for p in params if is_offered(p) and p["name"] in usage.used]
    chosen = {p["name"] for p in params if p.get("is_favorite") and p["name"] in usage.used}
    for p in params:
        if p["name"] in chosen and graph.is_derived(p["name"]):
            chosen.update(graph.user_reads(p["name"]))
    favourites = [p["name"] for p in offered if p["name"] in chosen]
    if favourites:
        return favourites
    return [p["name"] for p in offered]
