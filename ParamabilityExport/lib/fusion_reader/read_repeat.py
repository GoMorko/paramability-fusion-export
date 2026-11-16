"""Rectangular pattern, circular pattern and mirror features as plain dicts (docs/capture-format.md).

The inputs and numbers are read with the timeline marker just before the item. The pattern elements (the measured
transform of every copy) exist only once the feature is computed, so they are read with the marker just after it.
The elements are required: when the collection cannot be read the item gets a read_error, because an empty list
would look like a pattern with every copy suppressed.

The mirror plane, the circular pattern axis and a rectangular pattern direction taken from an edge or construction
axis of the part also say what they are (origin, face, edge, construction geometry and what it is built on; see
read_reference.py), so the translators can tell whether sizes move them.
"""
from . import read_geometry as geo
from . import read_solid
from .placement import from_assembly, ref_record
from .param_refs import Params, with_params
from .read_bodies import result_bodies, with_points
from .read_finish import strict_items
from .read_reference import add_reference, axis_with_reference, reference_of
from .read_sketch import sketch_place

_ENTITY_TYPES = [
    ("feature", "features"),
    ("face", "faces"),
    ("bod", "bodies"),
    ("occurrence", "occurrences"),
]
_DISTANCE_TYPES = [("extent", "extent"), ("spacing", "spacing")]
_INPUT_TYPES = {
    "BRepFace": "faces",
    "BRepBody": "bodies",
    "Occurrence": "occurrences",
}


def _inputs(feature):
    return strict_items(feature.inputEntities)


def _entity_type(feature, inputs):
    """features, faces, bodies, occurrences or other. The enum name is tried first, then the type of the inputs."""
    name = geo.safe(lambda: geo.enum_name(feature.patternEntityType, "PatternEntityTypes", "PatternEntityType"), "")
    found = geo.pick_by_text(name, _ENTITY_TYPES, "")
    if found:
        return found
    kinds = {_INPUT_TYPES.get(geo.type_name(e), "features" if geo.type_name(e).endswith("Feature") else "other")
             for e in inputs}
    return kinds.pop() if len(kinds) == 1 else "other"


def _sources(inputs, entity_type):
    """Timeline index of each input feature; empty when the pattern is not of features."""
    if entity_type != "features":
        return []
    return [entity.timelineObject.index for entity in inputs]


def _common(feature, ctx):
    inputs = _inputs(feature)
    entity_type = _entity_type(feature, inputs)
    data = {"entity_type": entity_type, "sources": _sources(inputs, entity_type)}
    if entity_type == "bodies":
        data["source_bodies"] = [with_points(entity, ctx) for entity in inputs]
        data["result_bodies"] = None
    return data


def direction_of(entity):
    """Unit direction of a vector, sketch line, construction axis, linear edge or planar face; None otherwise."""
    if entity is None:
        return None
    if all(isinstance(getattr(entity, c, None), (int, float)) for c in "xyz"):
        return geo.unit_vector(entity)
    axis = read_solid.axis_of(entity)
    if "dir" in axis:
        return axis["dir"]
    plane = geo.plane_of(entity)
    return plane["normal"] if plane else None


def _direction_entity(feature, entity_name, ctx):
    """`(entity, foreign)` of the entity a rectangular pattern direction is taken from: `foreign` is True when it
    belongs to another component, False when it is the target's or there is none, and None when that cannot be
    told."""
    entity = geo.safe(lambda: geo.native_input(getattr(feature, entity_name), ctx), None)
    if entity is None:
        return None, False
    return entity, geo.safe(lambda: bool(geo.foreign(entity, ctx)), None)


def _foreign_direction(entity, ctx, slot):
    """`(direction, place)` of a pattern direction taken from an axis, edge or face of another component. The entity
    is seen in the root's coordinates, so its direction is turned into the target's. `place` holds the direction and
    its measured reference (`ref`) with `assembly: true`; when the direction cannot be brought in, `direction` is None
    and `place` is marked `foreign`, so the pattern is refused."""
    raw = geo.safe(lambda: direction_of(entity), None)
    ref = geo.safe(lambda: ref_record(entity, ctx, slot, {"dir": raw} if raw is not None else {}), None) or {}
    if "dir" in ref:
        return ref["dir"], {"assembly": True, "dir": ref["dir"], "ref": ref}
    return None, {"foreign": True, "ref": ref}


def _direction_member(feature, vector_name, entity_name, ctx):
    """The direction of a rectangular pattern: a vector member when the API has one, else the direction entity."""
    for name in (vector_name, entity_name):
        found = geo.safe(lambda: direction_of(geo.native_input(getattr(feature, name), ctx)), None)
        if found is not None:
            return found
    return None


def _own_direction(feature, entity_name, ctx):
    """`{ "own": true, ...what it is }` of a direction taken from an edge, construction axis or other entity of the
    target's component (`read_reference.reference_of`), else None. A sketch line is named by `_direction_sketch`
    instead, and an entity that cannot be described gives None."""
    entity = geo.safe(lambda: geo.native_input(getattr(feature, entity_name), ctx), None)
    if entity is None or geo.type_name(entity) in ("none", "SketchLine"):
        return None
    found = geo.safe(lambda: reference_of(entity, ctx), None)
    return dict(found, own=True) if found else None


def _direction_sketch(feature, entity_name, ctx):
    """{ sketch_token, sketch, reference, projected } of the sketch line a pattern direction is taken from
    (`read_sketch.sketch_place`), else None."""
    line = geo.safe(lambda: geo.native_input(getattr(feature, entity_name), ctx), None)
    if geo.type_name(line) != "SketchLine":
        return None
    found = {}
    for key, read in (("sketch_token", lambda: line.parentSketch.entityToken), ("sketch", lambda: line.parentSketch.name)):
        value = geo.safe(read, "")
        if value:
            found[key] = value
    if not found:
        return None
    found.update(sketch_place(geo.safe(lambda: line.parentSketch, None), ctx))
    return found


def _number(parameter, default):
    return geo.safe(lambda: int(round(geo.value_of(parameter))), default)


def pattern_elements(feature):
    return [
        {
            "id": int(element.id),
            "suppressed": bool(geo.safe(lambda: element.isSuppressed, False)),
            "frame": geo.frame_of(element.transform),
        }
        for element in strict_items(feature.patternElements)
    ]


def _suppressed_ids(feature):
    return geo.safe(lambda: [int(i) for i in feature.suppressedElementsIds], [])


def rectangular_before(feature, ctx):
    data = _common(feature, ctx)
    quantity_two = geo.safe(lambda: _number(feature.quantityTwo, 1), 1)
    places, found = {}, {}
    for which, vector_name, entity_name in (("one", "directionOne", "directionOneEntity"),
                                            ("two", "directionTwo", "directionTwoEntity")):
        entity, foreign = _direction_entity(feature, entity_name, ctx)
        if foreign:
            found[which], places[which] = _foreign_direction(entity, ctx, "direction_" + which)
            continue
        found[which] = _direction_member(feature, vector_name, entity_name, ctx)
        if found[which] is None:
            continue
        # A direction whose owner cannot be told is no place of the part: every size may turn it.
        own = _own_direction(feature, entity_name, ctx) if foreign is False else {"unknown": True}
        if own is not None:
            places[which] = own
    direction_two = found["two"]
    data.update({
        "direction_one": found["one"],
        "quantity_one": _number(feature.quantityOne, 1),
        "distance_one": geo.length(feature.distanceOne),
        "direction_two": direction_two,
        "quantity_two": quantity_two if direction_two is not None else 1,
        "distance_two": geo.safe(lambda: geo.length(feature.distanceTwo), 0.0) if direction_two is not None else 0.0,
        "distance_type": geo.pick_by_text(
            geo.safe(lambda: geo.enum_name(feature.patternDistanceType, "PatternDistanceType", "PatternDistanceTypes"), ""),
            _DISTANCE_TYPES, "other"),
        # Copies on both sides of the original; false when the flag cannot be read (the measured copies then decide).
        "symmetric_one": geo.safe(lambda: bool(feature.isSymmetricInDirectionOne), False),
        "symmetric_two": geo.safe(lambda: bool(feature.isSymmetricInDirectionTwo), False),
        "elements": [],
        "suppressed_ids": [],
    })
    for which, entity_name in (("one", "directionOneEntity"), ("two", "directionTwoEntity")):
        source = _direction_sketch(feature, entity_name, ctx) if which not in places else None
        if source is not None:
            data["direction_%s_sketch" % which] = source
    for which, place in places.items():
        data["direction_%s_place" % which] = place
    return with_params(data, Params().add("quantity_one", lambda: feature.quantityOne, "scalar")
                       .add("quantity_two", lambda: feature.quantityTwo, "scalar")
                       .add("distance_one", lambda: feature.distanceOne)
                       .add("distance_two", lambda: feature.distanceTwo).found)


def circular_before(feature, ctx):
    data = _common(feature, ctx)
    data.update({
        "axis": geo.safe(lambda: axis_with_reference(feature.axis, ctx), {"kind": "other"}),
        "quantity": _number(feature.quantity, 1),
        "total_angle_deg": geo.angle(feature.totalAngle),
        "symmetric": geo.safe(lambda: bool(feature.isSymmetric), False),
        "elements": [],
        "suppressed_ids": [],
    })
    return with_params(data, Params().add("quantity", lambda: feature.quantity, "scalar")
                       .add("total_angle_deg", lambda: feature.totalAngle, "angle").found)


def pattern_after(feature, ctx, data):
    found = {"elements": pattern_elements(feature), "suppressed_ids": _suppressed_ids(feature)}
    found.update(_result_bodies(feature, ctx, data))
    return found


def _result_bodies(feature, ctx, data):
    """`result_bodies` of a pattern or mirror of bodies: the copies with their points, read with the marker after."""
    return {"result_bodies": result_bodies(feature, ctx)} if data.get("entity_type") == "bodies" else {}


def plane_record(entity, ctx):
    """A plane (construction plane or flat face) as `{ point, normal }` with what it is built on; None when it is not
    flat."""
    entity = geo.native_input(entity, ctx)
    record = from_assembly(geo.mark_foreign(geo.plane_of(entity), entity, ctx), entity, ctx, slot="plane")
    if isinstance(record, dict):
        record.update(read_solid.construction_token(entity))
        add_reference(record, entity, ctx)
    return record


def mirror_before(feature, ctx):
    data = _common(feature, ctx)
    data.update({
        "plane": geo.safe(lambda: plane_record(feature.mirrorPlane, ctx), None),
        "combine": geo.safe(lambda: bool(feature.isCombine), False),
        "target_box_before": ctx.target_box(),
    })
    return data


def mirror_after(feature, ctx, data):
    return _result_bodies(feature, ctx, data)


# type name -> (before, after); either may be None
READERS = {
    "RectangularPatternFeature": (rectangular_before, pattern_after),
    "CircularPatternFeature": (circular_before, pattern_after),
    "MirrorFeature": (mirror_before, mirror_after),
}
