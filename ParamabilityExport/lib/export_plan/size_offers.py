"""The parameter list of the main dialog, and the sizes the checks run over. Pure: no Fusion imports.

The size table (lib/params) decides what each parameter becomes. This module turns it into dialog lines and into
the size dicts of size_checks.
"""
from ..params import defaults, size_table
from ..params.size_table import CONSTANT, DERIVED, FIXED, FREE


def initial_table(params, model_params=(), design_unit="mm"):
    """The table for the first look at the dialog: the sensible default parameters are ticked."""
    if model_params:
        ticked = defaults.default_ticked(params, model_params)
    else:
        # Without the model parameters nothing tells what the body reads: start from the favourites.
        offered = [p for p in params if defaults.is_offered(p)]
        ticked = [p["name"] for p in offered if p.get("is_favorite")] or [p["name"] for p in offered]
    return size_table.build(params, ticked, model_params, design_unit)


def _plain_user(entry, by_name):
    p = by_name.get(entry.name)
    return p is not None and entry.source == "user" and p.get("kind") in ("length", "angle", "count")


def value_text(entry):
    suffix = {"length": " mm", "angle": " deg"}.get(entry.kind, "")
    return ("%.10g" % entry.value) + suffix


def offers(table, params):
    """One dict per parameter the dialog lists, in parameter order.

    Keys: param (Fusion name), text (the line), ticked, enabled, reason (tooltip, '' when none).
    A parameter that is a formula is listed without a tick. A fixed one is greyed with its reason. A parameter
    that cannot be a size at all (text, other units) is not listed.
    """
    by_name = {p["name"]: p for p in params}
    out = []
    for entry in table.entries:
        if entry.source != "user" or entry.name not in by_name:
            continue
        if entry.state == DERIVED or (entry.state == CONSTANT and not _plain_user(entry, by_name)):
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


def sizes_for_checks(table, params):
    """The free sizes in the shape size_checks.plan_checks reads."""
    by_name = {p["name"]: p for p in params}
    sizes = []
    for entry in table.entries:
        if entry.state != FREE or entry.source != "user" or entry.name not in by_name:
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
    return {e.size_name: e.label or e.name for e in table.entries if e.size_name}
