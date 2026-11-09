"""Model parameters behind feature values, read as plain dicts (docs/capture-format.md, "params").

A feature reader calls `ref(member, kind)` for each value that Fusion keeps as a model parameter. The result is
`{ name, expression, value }` with `value` in mm, degrees or as is, or None when the member is not a model parameter
(a plain number, a retired member or an unreadable one). No adsk import.
"""
from ..package.units import cm_to_mm, rad_to_deg
from .read_geometry import safe

_CONVERT = {"length": cm_to_mm, "angle": rad_to_deg, "scalar": float}


def ref(member, kind="length"):
    """{ name, expression, value } of a model parameter; kind is length, angle or scalar."""
    name = safe(lambda: member.name, None)
    expression = safe(lambda: member.expression, None)
    raw = safe(lambda: member.value, None)
    if not (isinstance(name, str) and name and isinstance(expression, str) and expression.strip()):
        return None
    if not isinstance(raw, (int, float)) or isinstance(raw, bool):
        return None
    return {"name": name, "expression": expression, "value": round(_CONVERT[kind](raw), 6) + 0.0}


class Params:
    """Collects the params map of one item: capture field path to its parameter."""

    def __init__(self):
        self.found = {}

    def add(self, path, read, kind="length"):
        """`read` is called in a try; a missing member adds nothing."""
        member = safe(read, None)
        found = ref(member, kind) if member is not None else None
        if found is not None:
            self.found[path] = found
        return self


def with_params(data, found):
    """`data` with the params map added when it holds anything (absent means no value follows a parameter)."""
    if found:
        data["params"] = found
    return data
