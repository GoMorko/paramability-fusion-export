"""User and model parameters as plain dicts. Uses the objects it is given and imports no adsk (tests use fakes)."""
from ..export_plan.expressions import is_plain_number
from ..package.units import internal_to_unit, unit_kind
from .read_geometry import enum_name, safe, type_name


def _kind_of_value(expression, unit):
    """derived for a formula, else the unit kind (length, angle, count) or unsupported."""
    if not is_plain_number(expression):
        return "derived"
    kind = unit_kind(unit)
    return "unsupported" if kind == "unknown" else kind


def _names(collection):
    """Names of the parameters in a Fusion collection or list; empty when it cannot be read."""
    def read():
        if hasattr(collection, "count") and hasattr(collection, "item"):
            return [collection.item(i).name for i in range(collection.count)]
        return [x.name for x in collection]
    return safe(read, []) if collection is not None else []


def _value_type(parameter):
    """numeric or text. Fusion's ParameterValueTypes names are not all verified, so the match is on the word text."""
    raw = safe(lambda: parameter.valueType, None)
    if raw is None:
        return "numeric"
    return "text" if "text" in enum_name(raw, "ParameterValueTypes").lower() else "numeric"


def _common(p):
    unit = p.unit or ""
    expression = p.expression or ""
    return {
        "name": p.name,
        "expression": expression,
        "value": p.value,
        "display_value": internal_to_unit(p.value, unit),
        "unit": unit,
        "kind": _kind_of_value(expression, unit),
        "is_favorite": bool(safe(lambda: p.isFavorite, False)),
        "value_type": _value_type(p),
        "dependency_parameters": _names(safe(lambda: p.dependencyParameters, None)),
    }


def list_user_parameters(design):
    """One dict per numeric user parameter (text parameters are left out).

    Keys: name, expression, value (Fusion internal cm or rad), display_value (in the parameter's own unit),
    unit, comment, is_favorite, kind (length, angle, count; derived when the expression is a formula; unsupported
    when the unit is not in the unit tables), value_type ("numeric"), dependency_parameters and
    dependent_parameters (names).
    """
    out = []
    params = design.userParameters
    for i in range(params.count):
        p = params.item(i)
        d = _common(p)
        if d["value_type"] == "text":
            continue
        d["comment"] = p.comment or ""
        d["dependent_parameters"] = _names(safe(lambda: p.dependentParameters, None))
        out.append(d)
    return out


_CREATED_BY_KINDS = (
    ("dimension", "sketchDimension"),
    ("constructionplane", "constructionPlane"),
    ("constructionaxis", "constructionAxis"),
    ("joint", "joint"),
    ("feature", "feature"),
)


def created_by_kind(entity):
    """feature, sketchDimension, constructionPlane, constructionAxis, joint or other, from the entity's type name."""
    text = type_name(entity).lower()
    for key, kind in _CREATED_BY_KINDS:
        if key in text:
            return kind
    return "other"


def _created_by(p, owner_token):
    """Who made the parameter. `component` is the token of the component the maker lives in: the sketch's component
    for a sketch dimension, else the component the parameter is listed from."""
    entity = safe(lambda: p.createdBy, None)
    if entity is None:
        return {"kind": "other", "token": "", "name": "", "component": owner_token}
    return {
        "kind": created_by_kind(entity),
        "token": safe(lambda: entity.entityToken, "") or "",
        "name": safe(lambda: entity.name, "") or "",
        "sketch": safe(lambda: entity.parentSketch.name, "") or "",
        "component": safe(lambda: entity.parentSketch.parentComponent.entityToken, "") or owner_token,
    }


def list_model_parameters(component):
    """One dict per numeric model parameter of a component (read through Component.modelParameters).

    Keys: as for user parameters, plus role and created_by ({ kind, token, name, sketch, component }; `sketch` is the
    sketch name of a sketch dimension, else empty; `component` is a component token). Unreadable members are skipped.
    """
    out = []
    owner_token = safe(lambda: component.entityToken, "") or ""
    params = safe(lambda: component.modelParameters, None)
    if params is None:
        return out
    for i in range(params.count):
        p = safe(lambda: params.item(i), None)
        if p is None:
            continue
        try:
            d = _common(p)
        except Exception:
            continue
        if d["value_type"] == "text":
            continue
        d["role"] = safe(lambda: p.role, "") or ""
        d["created_by"] = _created_by(p, owner_token)
        out.append(d)
    return out
