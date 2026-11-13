"""The parameter list of the main dialog, and the sizes the sketch probe runs over. Pure: no Fusion imports.

The size table decides what each parameter becomes. This module turns it into dialog lines and into the size dicts of
the probe.
"""
from ..package.units import display_from_manifest, unit_kind
from ..params import defaults, geometry_links, size_table
from ..params.expressions import format_number
from ..params.size_table import CONSTANT, DERIVED, FIXED, FREE, MAX_SIZES
from ..translator.notes import loose_reason
from ..translator.sizes import joint_reasons
from .body_scope import body_links, body_outside, scope_inputs

# The most sizes one recipe holds.
MAX_TICKED = MAX_SIZES


def limit_message(limit=MAX_TICKED):
    return "You can tick up to %d sizes. Untick one to tick another." % limit


def initial_table(params, model_params=(), design_unit="mm", quantity_params=(), limit=MAX_TICKED, links=()):
    """The table for the first look at the dialog (or after another body is picked).

    The sensible default parameters are ticked, at most `limit`. A parameter that a joint reads is not ticked to
    start with: it can be a size, but the part does not follow it in the assembly (`doubts`). Sketch dimensions and
    construction planes are offered as well: the export tries them at other values. So is a parameter that may reach
    a sketch of the body through the geometry of another component (`links`, `params.geometry_links`). A plain
    parameter the body reads only through formulas of other parameters, at any depth, counts as read (`body_usage`).
    """
    offered = [p["name"] for p in params if defaults.is_offered(p)]
    every = size_table.build(params, offered, model_params, design_unit, None, quantity_params, links=links)
    doubtful = joint_reasons(every, offered)
    if model_params or links:
        wanted = defaults.default_ticked(params, usage=body_usage(every))
    else:
        # Without the model parameters nothing tells what the body reads: start from the favourites.
        wanted = [p["name"] for p in params if defaults.is_offered(p) and p.get("is_favorite")] or offered
    return every.with_ticked([n for n in wanted if n not in doubtful][:limit])


def link_text(links):
    """Why a parameter is offered although no step of the body reads it: the other component it changes, which a
    sketch of the body follows or which owns a plane, axis or point a step of the body uses. Empty without links."""
    if not links:
        return ""
    first = links[0]
    if first.get("via") == "reference":
        return ("It changes %s, and the step %s of this part uses a plane, axis or point of %s. The export tries it "
                "to see if the part follows." % (first["component"], first.get("step") or "a step", first["component"]))
    return ("It changes %s, and the sketch %s of this part is drawn around %s. The export tries it to see if the "
            "part follows." % (first["component"], first["sketch"], first["component"]))


# The formulas a "used through" line names; past it the rest is counted.
MAX_THROUGH_NAMES = 2


def through_text(names):
    """Why a parameter no step reads itself is offered: the formulas of other parameters it reaches the part
    through. Empty without names."""
    names = list(names)
    if not names:
        return ""
    shown = names[:MAX_THROUGH_NAMES]
    rest = len(names) - len(shown)
    if rest:
        listed = "%s and %d more" % (", ".join(shown), rest)
    else:
        listed = " and ".join(shown)
    return "This part uses it through the formula%s %s." % ("s" if len(names) > 1 else "", listed)


def body_usage(table):
    """`dependencies.Usage` of the body the table was built for: what its model parameters and geometry links read."""
    return table.graph.usage(list(table.model_params), geometry_links.linked_names(table.links))


def doubts(table, params):
    """{Fusion name: reason} of the offered parameters that a joint reads. Such a size stays free, with a warning."""
    offered = [p["name"] for p in params if defaults.is_offered(p)]
    found = joint_reasons(table.with_ticked(offered), offered)
    return {name: loose_reason(name, why) for name, why in found.items()}


def table_for_body(params, design_unit, fallback_model, capture, limit=MAX_TICKED):
    """`initial_table` over the model parameters and pattern quantities of the picked body in `capture`.

    `capture` is the body's capture, or anything else (None, an exception) to use the whole root's parameters.
    """
    model, quantities = scope_inputs(capture, fallback_model)
    return initial_table(params, model, design_unit, quantities, limit, body_links(capture))


def table_for_bodies(params, design_unit, fallback_model, captures, limit=MAX_TICKED):
    """The dialog table for several picked bodies: the default ticks of each body's own table joined
    (`size_table.merged`), so a parameter any body uses is ticked. A body whose steps could not be read is left out
    unless no body could be read. One capture gives `table_for_body`'s table."""
    captures = list(captures)
    readable = [c for c in captures if isinstance(c, dict)] or captures[:1]
    tables = [table_for_body(params, design_unit, fallback_model, c, limit) for c in readable]
    return size_table.merged(tables, limit)


def range_unit(kind, design_unit="mm"):
    """The unit the Min, Max and Now cells use: the design's length unit, deg for an angle, '' for a count."""
    if kind == "length":
        return design_unit if unit_kind(design_unit) == "length" else "mm"
    return "deg" if kind == "angle" else ""


def value_text(entry, design_unit="mm"):
    unit = range_unit(entry.kind, design_unit)
    return format_number(display_from_manifest(entry.value, unit)) + (" " + unit if unit else "")


def offers(table, params, design_unit="mm"):
    """One dict per parameter the dialog lists, in parameter order.

    Keys: param (Fusion name), ticked, enabled, reason (why it is greyed or what the tick does), doubt (why a size
    may give unexpected results, else ''), link (why a parameter no step reads is offered: `link_text`, else ''),
    through (the formulas the part reads it through: `through_text`, else ''),
    state ('size' or 'keep' for a plain number, 'formula', 'locked'), now (value with unit), comment, formula (the
    Fusion expression of a formula), kind, value, min and max (the default range of a plain number, else None),
    range_unit (the unit of the Now, Min and Max cells). value, min and max are mm, deg or plain numbers; the cells
    show them in `design_unit` for a length.
    A parameter that is a formula is listed without a tick. A fixed one is greyed with its reason. A parameter
    that cannot be a size at all (text, units other than a length, an angle or none) is not listed.
    """
    by_name = {p["name"]: p for p in params}
    doubtful = doubts(table, params)
    through = body_usage(table).through
    out = []
    for entry in table.entries:
        p = by_name.get(entry.name)
        if p is None:
            continue
        plain = p.get("kind") in ("length", "angle", "count")
        if entry.state == CONSTANT and not plain and p.get("kind") != "derived":
            continue
        common = {"param": entry.name, "now": value_text(entry, design_unit),
                  "comment": (p.get("comment") or "").strip(), "formula": p.get("expression") or "",
                  "kind": entry.kind, "value": entry.value,
                  "range_unit": range_unit(entry.kind, design_unit), "min": None, "max": None,
                  "doubt": doubtful.get(entry.name, ""), "link": link_text(table.links_of(entry.name)),
                  "through": through_text(through.get(entry.name, ()))}
        if entry.state == DERIVED or (entry.state == CONSTANT and not plain):
            out.append({**common, "ticked": False, "enabled": False,
                        "state": "formula", "reason": "A formula. It follows the parameters it reads."})
        elif entry.state == FIXED:
            out.append({**common, "ticked": False, "enabled": False, "state": "locked", "reason": entry.reason})
        elif entry.state in (FREE, CONSTANT):
            lo, hi = defaults.size_range(p, entry.kind, entry.value)
            out.append({**common, "ticked": entry.state == FREE, "enabled": True, "min": lo, "max": hi,
                        "state": "size" if entry.state == FREE else "keep",
                        "reason": "Tick to change this number in Paramability. Untick to keep it fixed."})
    return out


def probe_sizes(table, params, keep=None):
    """The free sizes as the probe reads them: param (Fusion name), size (recipe name), unit, kind, value, min, max
    (manifest numbers) and favorite.

    `keep` limits them to these recipe size names (the sizes the recipe still has after translation).
    """
    by_name = {p["name"]: p for p in params}
    sizes = []
    for entry in table.entries:
        if entry.state != FREE or entry.name not in by_name or (keep is not None and entry.size_name not in keep):
            continue
        size = table.sizes[entry.size_name]
        sizes.append({
            "param": entry.name, "size": entry.size_name, "unit": by_name[entry.name]["unit"], "kind": entry.kind,
            "value": entry.value, "min": size["min"], "max": size["max"],
            "favorite": bool(by_name[entry.name].get("is_favorite")),
        })
    return sizes


def discovery_sizes(table, params, capture):
    """The unticked plain parameters that act on another component a sketch of the body is tied to, or on any
    other component (`body_scope.body_outside`), as probe size dicts plus `end`: the end of the range that differs
    from the value now (the upper one when both do). In that order; the probe caps them (`plan.MAX_DISCOVERY`)."""
    by_name = {p["name"]: p for p in params}
    ticked = set(table.ticked)
    out = []
    for name in body_outside(capture):
        entry, p = table.entry(name), by_name.get(name)
        if p is None or entry is None or name in ticked or entry.state != CONSTANT or not defaults.is_offered(p):
            continue
        lo, hi = defaults.size_range(p, entry.kind, entry.value)
        end = hi if abs(hi - entry.value) > 1e-9 else lo
        if abs(end - entry.value) <= 1e-9:
            continue
        out.append({"param": name, "size": entry.size_name or name, "unit": p["unit"], "kind": entry.kind,
                    "value": entry.value, "min": lo, "max": hi, "end": end})
    return out


def labels(table):
    """{recipe size name: the label the person knows it by}."""
    return {e.size_name: e.label or e.name for e in table.entries if e.state in (FREE, DERIVED)}
