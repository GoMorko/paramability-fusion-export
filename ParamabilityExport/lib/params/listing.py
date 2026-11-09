"""The design's user parameters as the manifest `parameters` list, whatever the shape of the package.

Every entry holds the recipe style name (the same one the size table gives), the Fusion name as the label, the
current value in mm, degrees or a plain number, and its unit. A formula parameter also holds `expr`, the Fusion
expression written over the names of other entries, when the size table can translate it.
"""
import math
from dataclasses import dataclass, field

from ..package.manifest import MAX_PARAMETER_COMMENT, MAX_PARAMETER_LABEL, MAX_PARAMETERS
from ..package.units import manifest_unit
from . import defaults, names, size_table
from .expressions import tokenize_formula

UNIT_REASON = size_table.UNIT_REASON
CAP_REASON = "The list holds at most %d parameters." % MAX_PARAMETERS
VALUE_REASON = "The value is not a finite number."
LARGE_REASON = "The value is too large."
# Largest value the list keeps, in mm, degrees or as is.
MAX_VALUE = 1e9


@dataclass
class ParameterListing:
    """entries: manifest parameter dicts. left_out: [{'name' (Fusion), 'reason'}] not listed at all.
    no_formula: the same for listed formula parameters that carry only their value. renames: Fusion name to entry name.
    """
    entries: list = field(default_factory=list)
    left_out: list = field(default_factory=list)
    no_formula: list = field(default_factory=list)
    renames: dict = field(default_factory=dict)

    def report(self):
        return {"listed": len(self.entries), "left_out": [dict(x) for x in self.left_out],
                "no_formula": [dict(x) for x in self.no_formula]}


def _names_in(formula):
    """Names a written formula reads (identifiers that are not function calls)."""
    tokens = tokenize_formula(formula)
    return {t[1] for i, t in enumerate(tokens)
            if t[0] == "id" and tokens[i + 1] != ("op", "(")}


def list_parameters(params, model_params=(), design_unit="mm"):
    """ParameterListing of the reader's user parameters (Fusion internal values), in Fusion order."""
    candidates = [p for p in params if defaults.is_numeric(p)]
    offered = [p["name"] for p in candidates if defaults.is_offered(p)]
    assigned = names.assign([p["name"] for p in candidates])
    out = ParameterListing()
    try:
        # Every plain parameter is a size here, so each formula is written over the names of the list.
        table = size_table.build(candidates, offered, model_params, design_unit, max_sizes=len(candidates))
    except Exception:
        # Without the table the values and names still go in, only the formulas are lost.
        table = None
    listed = []
    for p in candidates:
        if defaults.dim_of_unit(p.get("unit")) is None:
            out.left_out.append({"name": p["name"], "reason": UNIT_REASON})
            continue
        value = defaults.size_value(p)
        if not math.isfinite(value):
            out.left_out.append({"name": p["name"], "reason": VALUE_REASON})
            continue
        if abs(value) > MAX_VALUE:
            out.left_out.append({"name": p["name"], "reason": LARGE_REASON})
            continue
        item = {
            "name": assigned[p["name"]],
            "label": p["name"][:MAX_PARAMETER_LABEL].strip(),
            "value": round(value, 9),
            "unit": manifest_unit(p.get("unit")),
        }
        entry = table.entry(p["name"]) if table is not None else None
        if entry is not None and entry.state in (size_table.DERIVED, size_table.CONSTANT) and entry.formula:
            item["expr"] = entry.formula
        elif p.get("kind") == "derived" and entry is not None and entry.state == size_table.NOT_OFFERED:
            out.no_formula.append({"name": p["name"], "reason": entry.reason})
        comment = (p.get("comment") or "").strip()
        if comment:
            item["comment"] = comment[:MAX_PARAMETER_COMMENT].strip()
        listed.append((p["name"], item))

    if len(listed) > MAX_PARAMETERS:
        cut = listed[:MAX_PARAMETERS]
        kept_names = {x[0] for x in cut}
        out.left_out += [{"name": n, "reason": CAP_REASON} for n, _ in listed[MAX_PARAMETERS:]]
        listed = cut
        out.no_formula = [x for x in out.no_formula if x["name"] in kept_names]

    present = {item["name"] for _, item in listed}
    for name, item in listed:
        # A formula that reads an entry cut from the list cannot stand alone.
        if "expr" in item and not _names_in(item["expr"]) <= present:
            del item["expr"]
            out.no_formula.append({"name": name, "reason": "It reads a parameter that is not in the list."})
        out.entries.append(item)
        out.renames[name] = item["name"]
    return out
