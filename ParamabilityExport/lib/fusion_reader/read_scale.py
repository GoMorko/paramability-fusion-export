"""Scale features as plain dicts (docs/capture-format.md).

`inputEntities` may hold bodies, sketches and (outside parametric modelling) components. Only bodies are copied, so
`input_kind` is `bodies` when every input is a body, else `sketches` (some input is a sketch) or `other`. Each body
among them is measured with the marker just before the item (`box_before`, `volume_before`) and again just after it
(`after`, found by token), so the translator can check that the scale did what its factors and point say.

The point that stays in place (`point`) is a sketch point, a construction point or a corner of a body. Its record
gives its place in the component's coordinates and what it is, so the translator can tell which sizes may move it:
`origin` for the component's origin point; `entity_type`, the sketch name and what the sketch sits on for a sketch
point; the token and the timeline index of the feature that made it for a construction point; the body for a corner.
A point of another component is marked `foreign`. The factor is `factor` for a uniform scale and `factors` (x, y, z)
for a scale that differs per axis. A member that cannot be read is null (or `other` for a type), and the translator
leaves the step out.
"""
from . import read_geometry as geo
from .param_refs import Params, with_params
from .read_sketch import sketch_place

_POINT_TYPES = ("SketchPoint", "ConstructionPoint", "BRepVertex")
_AXES = ("xScale", "yScale", "zScale")


def _input_kind(entities):
    names = {geo.type_name(e) for e in entities}
    if names == {"BRepBody"}:
        return "bodies"
    return "sketches" if "Sketch" in names else "other"


def _measured(body):
    """`{ box, volume }` of a body at the current marker position; a value that cannot be read is null."""
    return {"box": geo.safe(lambda: geo.box_of(body), None), "volume": geo.volume_mm3(body)}


def _body_record(entity, ctx):
    native = geo.native_object(entity)
    found = _measured(native)
    record = geo.body_ref(entity, ctx)
    record.update(box_before=found["box"], volume_before=found["volume"])
    return record


def _sketch_point(entity, ctx, record):
    sketch = geo.safe(lambda: entity.parentSketch, None)
    name = geo.safe(lambda: sketch.name, "")
    if name:
        record["sketch"] = name
    place = sketch_place(sketch, ctx)
    record["sketch_reference"], record["sketch_projected"] = place["reference"], place["projected"]
    return geo.point(entity.worldGeometry)


def _construction_point(entity, record):
    token = geo.safe(lambda: entity.entityToken, "")
    if token:
        record["token"] = token
    made_by = geo.safe(lambda: int(entity.timelineObject.index), None)
    if made_by is not None:
        record["made_by"] = made_by
    return geo.point(entity.geometry)


def point_record(entity, ctx):
    """The record of the point a scale keeps in place (see the module text)."""
    entity = geo.native_input(entity, ctx)
    name = geo.type_name(entity)
    if name not in _POINT_TYPES:
        return {"kind": "other", "type": name}
    if geo.foreign(entity, ctx):
        return {"kind": "other", "type": name, "foreign": True}
    origin = geo.safe(lambda: ctx.component.originConstructionPoint, None)
    if name == "ConstructionPoint" and geo.same_entity(entity, origin):
        return {"origin": True, "point": [0.0, 0.0, 0.0]}
    record = {"entity_type": name}
    if name == "SketchPoint":
        place = geo.safe(lambda: _sketch_point(entity, ctx, record), None)
    elif name == "ConstructionPoint":
        place = geo.safe(lambda: _construction_point(entity, record), None)
    else:
        place = geo.safe(lambda: geo.point(entity.geometry), None)
        body = geo.owner_body(entity, ctx)
        if body:
            record["body"] = body
    if place is None:
        return {"kind": "other", "type": name}
    record["point"] = place
    return record


def _factors(feature):
    """`(uniform, factor, factors, params)`: the factor of a uniform scale or the three of one that differs per axis.
    One that cannot be read is null."""
    uniform = geo.safe(lambda: bool(feature.isUniform), None)
    found = Params()
    factor, factors = None, None
    if uniform is True:
        factor = geo.safe(lambda: float(geo.value_of(feature.scaleFactor)), None)
        found.add("factor", lambda: feature.scaleFactor, "scalar")
    elif uniform is False:
        factors = [geo.safe(lambda: float(geo.value_of(getattr(feature, name))), None) for name in _AXES]
        for n, name in enumerate(_AXES):
            found.add("factors.%d" % n, lambda: getattr(feature, name), "scalar")
    return uniform, factor, factors, found.found


def scale_before(feature, ctx):
    entities = geo.collection_items(geo.safe(lambda: feature.inputEntities, None))
    kind = _input_kind(entities) if entities else "other"
    point = geo.safe(lambda: feature.point, None)
    uniform, factor, factors, params = _factors(feature)
    data = {
        "input_kind": kind,
        "bodies": [_body_record(e, ctx) for e in entities if geo.type_name(e) == "BRepBody"],
        "point": point_record(point, ctx) if point is not None else None,
        "uniform": uniform,
        "factor": factor,
        "factors": factors,
        "after": [],
    }
    return with_params(data, params)


def scale_after(feature, ctx, data):
    after = []
    for body in data.get("bodies") or []:
        found = geo.find_native(ctx.design, body.get("token")) if body.get("token") else None
        after.append(_measured(found))
    return {"after": after}


# type name -> (before, after); either may be None
READERS = {
    "ScaleFeature": (scale_before, scale_after),
}
