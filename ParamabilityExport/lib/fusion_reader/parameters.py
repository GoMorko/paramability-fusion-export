"""User parameters as plain dicts."""
from ..export_plan.expressions import is_plain_number
from ..package.units import internal_to_unit, unit_kind


def list_user_parameters(design):
    """One dict per user parameter.

    Keys: name, expression, value (Fusion internal cm or rad), display_value (in the parameter's own unit),
    unit, comment, is_favorite, kind (length, angle, count, or derived when the expression is a formula).
    """
    out = []
    params = design.userParameters
    for i in range(params.count):
        p = params.item(i)
        unit = p.unit or ""
        expression = p.expression or ""
        kind = unit_kind(unit) if is_plain_number(expression) else "derived"
        out.append({
            "name": p.name,
            "expression": expression,
            "value": p.value,
            "display_value": internal_to_unit(p.value, unit),
            "unit": unit,
            "comment": p.comment or "",
            "is_favorite": bool(p.isFavorite),
            "kind": kind,
        })
    return out
