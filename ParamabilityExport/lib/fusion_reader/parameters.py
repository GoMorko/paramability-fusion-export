"""User and model parameters as plain dicts. Uses the objects it is given and imports no adsk (tests use fakes)."""
from ..params.expressions.text import is_constant_expression, is_plain_number
from ..package.units import internal_to_unit, unit_kind
from .read_geometry import collection_items, component_of, enum_name, safe, type_name

# At most this many dependents are visited per user parameter.
MAX_DEPENDENTS = 2000


def _kind_of_value(expression, unit):
    """derived for a formula that reads another parameter (or the text cannot be read), else the unit kind (length,
    angle, count) or unsupported. A formula of plain numbers (`3 * 0.4 mm`) has the kind of its unit: it is a number
    that can be changed like a plain one."""
    if not is_plain_number(expression) and not is_constant_expression(expression):
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


def _token(entity):
    return safe(lambda: entity.entityToken, "") or ""


def _native(entity):
    """The native object of an entity seen through an occurrence, else the entity."""
    if safe(lambda: entity.assemblyContext, None) is None:
        return entity
    return safe(lambda: entity.nativeObject, None) or entity


def _owned_by_sketch(sketch, name):
    """"sketchDimension" or "sketchText" when `sketch` holds a dimension whose parameter is `name`, or a text whose
    height parameter is `name`; else None. Fusion answers the owning Sketch, not the dimension, as the `createdBy` of
    a sketch dimension's parameter."""
    if not name or type_name(sketch) != "Sketch":
        return None
    for members, parameter_of, kind in (("sketchDimensions", lambda d: d.parameter, "sketchDimension"),
                                        ("sketchTexts", lambda t: t.heightParameter, "sketchText")):
        for item in collection_items(safe(lambda: getattr(sketch, members), None)):
            if safe(lambda: parameter_of(item).name, "") == name:
                return kind
    return None


def dependent_record(parameter):
    """Where one model parameter acts: `{ name, kind, component }` plus, for a sketch dimension or text, `sketch` and
    `sketch_token` of its sketch, and for a feature or other maker, `feature` (its name). `component` is the token of
    the component its maker lives in (the sketch's, the feature's), else of `ModelParameter.component`.

    A sketch dimension's parameter may name the Sketch as its maker: it counts as a sketch dimension (or sketch text)
    of that sketch when one of the sketch's own dimensions (texts) has this parameter."""
    name = safe(lambda: parameter.name, "") or ""
    entity = _native(safe(lambda: parameter.createdBy, None))
    record = {"name": name, "kind": "other", "component": ""}
    sketch_kind = _owned_by_sketch(entity, name) if entity is not None else None
    if sketch_kind:
        record.update(kind=sketch_kind, sketch=safe(lambda: entity.name, "") or "", sketch_token=_token(entity),
                      component=_token(safe(lambda: entity.parentComponent, None)))
    elif entity is not None and (_is_sketch_dimension(entity) or _is_sketch_text(entity)):
        sketch = _native(safe(lambda: entity.parentSketch, None))
        record.update(kind="sketchText" if _is_sketch_text(entity) and not _is_sketch_dimension(entity)
                      else "sketchDimension",
                      sketch=safe(lambda: sketch.name, "") or "", sketch_token=_token(sketch),
                      component=_token(safe(lambda: sketch.parentComponent, None)))
    elif entity is not None:
        record.update(kind=created_by_kind(entity), feature=safe(lambda: entity.name, "") or "",
                      component=_token(component_of(entity)))
    if not record["component"]:
        record["component"] = _token(safe(lambda: parameter.component, None))
    return record


def dependents(parameter):
    """`[dependent_record]` of every model parameter that reads `parameter`, directly or through other parameters
    that read it (`dependentParameters`, walked transitively, at most MAX_DEPENDENTS visits). Empty when unreadable."""
    found, seen = [], set()
    stack = collection_items(safe(lambda: parameter.dependentParameters, None))
    visits = 0
    while stack and visits < MAX_DEPENDENTS:
        dependent = stack.pop()
        visits += 1
        kind = safe(lambda: type_name(dependent), "")
        name = safe(lambda: dependent.name, None)
        if name is None or (kind, name) in seen:
            continue
        seen.add((kind, name))
        if "UserParameter" not in kind:
            found.append(safe(lambda: dependent_record(dependent), {"name": name, "kind": "other", "component": ""}))
        stack.extend(collection_items(safe(lambda: dependent.dependentParameters, None)))
    return found


def list_user_parameters(design):
    """One dict per numeric user parameter (text parameters are left out).

    Keys: name, expression, value (Fusion internal cm or rad), display_value (in the parameter's own unit),
    unit, comment, is_favorite, kind (length, angle, count; derived when the expression is a formula; unsupported
    when the unit is not in the unit tables), value_type ("numeric"), dependency_parameters and
    dependent_parameters (names), and dependents (`dependents`: where each model parameter that reads it acts).
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
        d["dependents"] = dependents(p)
        out.append(d)
    return out


_CREATED_BY_KINDS = (
    ("sketchtext", "sketchText"),
    ("dimension", "sketchDimension"),
    ("constructionplane", "constructionPlane"),
    ("constructionaxis", "constructionAxis"),
    ("joint", "joint"),
    ("feature", "feature"),
)


def created_by_kind(entity):
    """feature, sketchDimension, sketchText, constructionPlane, constructionAxis, joint or other, from the entity's type
    name."""
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


class _SketchIndex:
    """Lookups from parameter name over the sketches of a component: to (sketch, dimension) for the parameter of a
    sketch dimension, to (sketch, text) for the height of a sketch text. Built once, on first use."""

    def __init__(self, component):
        self._component = component
        self._dimensions = self._texts = None

    def _build(self):
        self._dimensions, self._texts = {}, {}
        sketches = safe(lambda: self._component.sketches, None)
        for i in range(safe(lambda: sketches.count, 0) or 0):
            sketch = safe(lambda: sketches.item(i), None)
            self._collect(sketch, "sketchDimensions", lambda d: d.parameter.name, self._dimensions)
            self._collect(sketch, "sketchTexts", lambda t: t.heightParameter.name, self._texts)

    @staticmethod
    def _collect(sketch, members, name_of, found):
        items = safe(lambda: getattr(sketch, members), None)
        for j in range(safe(lambda: items.count, 0) or 0):
            item = safe(lambda: items.item(j), None)
            name = safe(lambda: name_of(item), "")
            if name:
                found.setdefault(name, (sketch, item))

    def dimension(self, name):
        if self._dimensions is None:
            self._build()
        return self._dimensions.get(name)

    def text(self, name):
        if self._texts is None:
            self._build()
        return self._texts.get(name)


def _is_sketch_text(entity):
    """A sketch text by its type name, else by the members only a text has."""
    return created_by_kind(entity) == "sketchText" or (
        hasattr(entity, "heightParameter") and hasattr(entity, "parentSketch"))


def _sketch_made(dimension, sketch, owner_token):
    sketch = sketch or safe(lambda: dimension.parentSketch, None)
    return {
        "kind": "sketchDimension",
        "token": safe(lambda: dimension.entityToken, "") or "",
        "name": safe(lambda: dimension.name, "") or "",
        "sketch": safe(lambda: sketch.name, "") or "",
        "component": safe(lambda: sketch.parentComponent.entityToken, "") or owner_token,
    }


def _text_made(text, sketch, owner_token):
    sketch = sketch or safe(lambda: text.parentSketch, None)
    return {
        "kind": "sketchText",
        "token": safe(lambda: text.entityToken, "") or "",
        "name": "",
        "sketch": safe(lambda: sketch.name, "") or "",
        "component": safe(lambda: sketch.parentComponent.entityToken, "") or owner_token,
    }


def _created_by(p, owner_token, index=None):
    """Who made the parameter. `component` is the token of the component the maker lives in: the sketch's component
    for a sketch dimension or text, else the component the parameter is listed from.

    A sketch dimension is recognised through `createdBy` (type name, cast, members) and, when that gives nothing
    usable, through the sketch dimension whose own parameter is this one (`index.dimension(name)`). A sketch text
    (its height parameter) is recognised the same way, through `index.text(name)`.
    """
    entity = safe(lambda: p.createdBy, None)
    if entity is not None:
        if _is_sketch_dimension(entity):
            return _sketch_made(entity, None, owner_token)
        if _is_sketch_text(entity):
            return _text_made(entity, None, owner_token)
        kind = created_by_kind(entity)
        if kind != "other":
            return {
                "kind": kind,
                "token": safe(lambda: entity.entityToken, "") or "",
                "name": safe(lambda: entity.name, "") or "",
                "sketch": "",
                "component": owner_token,
            }
    if index is not None:
        found = index.dimension(p.name)
        if found is not None:
            return _sketch_made(found[1], found[0], owner_token)
        found = index.text(p.name)
        if found is not None:
            return _text_made(found[1], found[0], owner_token)
    if entity is None:
        return {"kind": "other", "token": "", "name": "", "component": owner_token}
    return {"kind": "other", "token": safe(lambda: entity.entityToken, "") or "",
            "name": safe(lambda: entity.name, "") or "", "sketch": "", "component": owner_token}


def list_model_parameters(component):
    """One dict per numeric model parameter of a component (read through Component.modelParameters).

    Keys: as for user parameters, plus role and created_by ({ kind, token, name, sketch, component }; `sketch` is the
    sketch name of a sketch dimension or text, else empty; `component` is a component token). Unreadable members are skipped.
    """
    out = []
    owner_token = safe(lambda: component.entityToken, "") or ""
    params = safe(lambda: component.modelParameters, None)
    if params is None:
        return out
    index = _SketchIndex(component)
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
        d["created_by"] = _created_by(p, owner_token, index)
        out.append(d)
    return out
