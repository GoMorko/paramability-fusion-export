"""The parameter list of the main dialog, and the sizes the checks run over. Pure: no Fusion imports.

The size table decides what each parameter becomes. This module turns it into dialog lines and into
the size dicts of size_checks.
"""
from ..params import defaults, size_table
from ..params.expressions import format_number
from ..params.size_table import CONSTANT, DERIVED, FIXED, FREE
from ..translator.sizes import sketch_fixes
from .body_scope import scope_inputs
from .size_checks import MAX_CHECKS

# Every ticked size gets one check, so the dialog allows as many ticks as there are check slots.
MAX_TICKED = MAX_CHECKS


def limit_message(limit=MAX_TICKED):
    return "You can tick up to %d sizes. Untick one to tick another." % limit


def initial_table(params, model_params=(), design_unit="mm", quantity_params=(), limit=MAX_TICKED):
    """The table for the first look at the dialog (or after another body is picked).

    The sensible default parameters are ticked, at most `limit`. A parameter that a sketch dimension, construction
    plane or axis, or joint reads is fixed whether it was a default or not, so the dialog can grey it out.
    """
    def build(ticked, fixed=None):
        return size_table.build(params, ticked, model_params, design_unit, fixed, quantity_params)

    offered = [p["name"] for p in params if defaults.is_offered(p)]
    fixes = sketch_fixes(build(offered))
    if model_params:
        wanted = defaults.default_ticked(params, model_params)
    else:
        # Without the model parameters nothing tells what the body reads: start from the favourites.
        wanted = [p["name"] for p in params if defaults.is_offered(p) and p.get("is_favorite")] or offered
    return build([n for n in wanted if n not in fixes][:limit], fixes)


def table_for_body(params, design_unit, fallback_model, capture, limit=MAX_TICKED):
    """`initial_table` over the model parameters and pattern quantities of the picked body in `capture`.

    `capture` is the body's capture, or anything else (None, an exception) to use the whole root's parameters.
    """
    model, quantities = scope_inputs(capture, fallback_model)
    return initial_table(params, model, design_unit, quantities, limit)


def value_text(entry):
    suffix = {"length": " mm", "angle": " deg"}.get(entry.kind, "")
    return format_number(entry.value) + suffix


def offers(table, params):
    """One dict per parameter the dialog lists, in parameter order.

    Keys: param (Fusion name), text (the line), ticked, enabled, reason (tooltip, '' when none).
    A parameter that is a formula is listed without a tick. A fixed one is greyed with its reason. A parameter
    that cannot be a size at all (text, other units) is not listed.
    """
    by_name = {p["name"]: p for p in params}
    out = []
    for entry in table.entries:
        p = by_name.get(entry.name)
        if p is None:
            continue
        plain = p.get("kind") in ("length", "angle", "count")
        if entry.state == DERIVED or (entry.state == CONSTANT and not plain):
            out.append({"param": entry.name, "text": "%s (formula)" % entry.name, "ticked": False,
                        "enabled": False, "reason": "A formula. It follows the parameters it reads."})
        elif entry.state == FIXED:
            out.append({"param": entry.name, "text": "%s, %s" % (entry.name, value_text(entry)), "ticked": False,
                        "enabled": False, "reason": entry.reason})
        elif entry.state in (FREE, CONSTANT):
            out.append({"param": entry.name, "text": "%s, %s" % (entry.name, value_text(entry)),
                        "ticked": entry.state == FREE, "enabled": True,
                        "reason": "Tick to change this number in Paramability. Untick to keep it fixed."})
    return out


def sizes_for_checks(table, params, keep=None):
    """The free sizes in the shape size_checks.plan_checks reads.

    `keep` limits them to these recipe size names (the sizes the recipe still has after translation).
    """
    by_name = {p["name"]: p for p in params}
    sizes = []
    for entry in table.entries:
        if entry.state != FREE or entry.name not in by_name or (keep is not None and entry.size_name not in keep):
            continue
        size = table.sizes[entry.size_name]
        sizes.append({
            "param": entry.name, "size": entry.size_name, "unit": by_name[entry.name]["unit"],
            "value": entry.value, "min": size["min"], "max": size["max"],
            "favorite": bool(by_name[entry.name].get("is_favorite")),
        })
    return sizes


def labels(table):
    """{recipe size name: the label the person knows it by}."""
    return {e.size_name: e.label or e.name for e in table.entries if e.state in (FREE, DERIVED)}
