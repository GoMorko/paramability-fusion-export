"""User and model parameters as plain dicts. Uses the objects it is given and imports no adsk (tests use fakes)."""
from ..params.expressions import is_plain_number
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


def _cast_is_sketch_dimension(entity):
    """True when adsk.fusion can cast the entity to a SketchDimension. False without adsk (tests) or on failure."""
    try:
        import adsk.fusion
        return adsk.fusion.SketchDimension.cast(entity) is not None
    except Exception:
        return False


def _is_sketch_dimension(entity):
    """A sketch dimension by its type name, else by a cast, else by the members only a dimension has."""
    if created_by_kind(entity) == "sketchDimension" or _cast_is_sketch_dimension(entity):
        return True
    return hasattr(entity, "parentSketch") and hasattr(entity, "parameter")


def _dimension_index(component):
    """A lookup from parameter name to (sketch, dimension) over the sketches of a component. Built once, on first use."""
    cache = {}

    def build():
        found = {}
        sketches = safe(lambda: component.sketches, None)
        for i in range(safe(lambda: sketches.count, 0) or 0):
            sketch = safe(lambda: sketches.item(i), None)
            dims = safe(lambda: sketch.sketchDimensions, None)
            for j in range(safe(lambda: dims.count, 0) or 0):
                dim = safe(lambda: dims.item(j), None)
                name = safe(lambda: dim.parameter.name, "")
                if name:
                    found.setdefault(name, (sketch, dim))
        return found

    def find(name):
        if "index" not in cache:
            cache["index"] = build()
        return cache["index"].get(name)

    return find


def _sketch_made(dimension, sketch, owner_token):
    sketch = sketch or safe(lambda: dimension.parentSketch, None)
    return {
        "kind": "sketchDimension",
        "token": safe(lambda: dimension.entityToken, "") or "",
        "name": safe(lambda: dimension.name, "") or "",
        "sketch": safe(lambda: sketch.name, "") or "",
        "component": safe(lambda: sketch.parentComponent.entityToken, "") or owner_token,
    }


def _created_by(p, owner_token, find_dimension=None):
    """Who made the parameter. `component` is the token of the component the maker lives in: the sketch's component
    for a sketch dimension, else the component the parameter is listed from.

    A sketch dimension is recognised through `createdBy` (type name, cast, members) and, when that gives nothing
    usable, through the sketch dimension whose own parameter is this one (`find_dimension(name)`).
    """
    entity = safe(lambda: p.createdBy, None)
    if entity is not None:
        if _is_sketch_dimension(entity):
            return _sketch_made(entity, None, owner_token)
        kind = created_by_kind(entity)
        if kind != "other":
            return {
                "kind": kind,
                "token": safe(lambda: entity.entityToken, "") or "",
                "name": safe(lambda: entity.name, "") or "",
                "sketch": "",
                "component": owner_token,
            }
    if find_dimension is not None:
        found = find_dimension(p.name)
        if found is not None:
            return _sketch_made(found[1], found[0], owner_token)
    if entity is None:
        return {"kind": "other", "token": "", "name": "", "component": owner_token}
    return {"kind": "other", "token": safe(lambda: entity.entityToken, "") or "",
            "name": safe(lambda: entity.name, "") or "", "sketch": "", "component": owner_token}


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
    find_dimension = _dimension_index(component)
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
        d["created_by"] = _created_by(p, owner_token, find_dimension)
        out.append(d)
    return out
