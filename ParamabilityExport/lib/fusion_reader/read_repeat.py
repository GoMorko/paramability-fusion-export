"""Rectangular pattern, circular pattern and mirror features as plain dicts (docs/capture-format.md).

The inputs and numbers are read with the timeline marker just before the item. The pattern elements (the measured
transform of every copy) exist only once the feature is computed, so they are read with the marker just after it.
The elements are required: when the collection cannot be read the item gets a read_error, because an empty list
would look like a pattern with every copy suppressed.
"""
from . import read_geometry as geo
from . import read_solid
from .read_finish import strict_items

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
    name = geo.safe(lambda: geo.enum_name(feature.patternEntityType, "PatternEntityTypes"), "")
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


def _common(feature):
    inputs = _inputs(feature)
    entity_type = _entity_type(feature, inputs)
    return {"entity_type": entity_type, "sources": _sources(inputs, entity_type)}


def _direction(entity):
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


def _direction_member(feature, vector_name, entity_name):
    """The direction of a rectangular pattern: a vector member when the API has one, else the direction entity."""
    for name in (vector_name, entity_name):
        found = geo.safe(lambda: _direction(getattr(feature, name)), None)
        if found is not None:
            return found
    return None


def _number(parameter, default):
    return geo.safe(lambda: int(round(geo.value_of(parameter))), default)


def _elements(feature):
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
    data = _common(feature)
    quantity_two = geo.safe(lambda: _number(feature.quantityTwo, 1), 1)
    direction_two = _direction_member(feature, "directionTwo", "directionTwoEntity")
    data.update({
        "direction_one": _direction_member(feature, "directionOne", "directionOneEntity"),
        "quantity_one": _number(feature.quantityOne, 1),
        "distance_one": geo.length(feature.distanceOne),
        "direction_two": direction_two,
        "quantity_two": quantity_two if direction_two is not None else 1,
        "distance_two": geo.safe(lambda: geo.length(feature.distanceTwo), 0.0) if direction_two is not None else 0.0,
        "distance_type": geo.pick_by_text(
            geo.safe(lambda: geo.enum_name(feature.patternDistanceType, "PatternDistanceTypes"), ""),
            _DISTANCE_TYPES, "other"),
        "symmetric_one": geo.safe(lambda: bool(feature.isSymmetricInDirectionOne), False),
        "symmetric_two": geo.safe(lambda: bool(feature.isSymmetricInDirectionTwo), False),
        "elements": [],
        "suppressed_ids": [],
    })
    return data


def circular_before(feature, ctx):
    data = _common(feature)
    data.update({
        "axis": geo.safe(lambda: read_solid.axis_of(feature.axis), {"kind": "other"}),
        "quantity": _number(feature.quantity, 1),
        "total_angle_deg": geo.angle(feature.totalAngle),
        "symmetric": geo.safe(lambda: bool(feature.isSymmetric), False),
        "elements": [],
        "suppressed_ids": [],
    })
    return data


def pattern_after(feature, ctx, data):
    return {"elements": _elements(feature), "suppressed_ids": _suppressed_ids(feature)}


def mirror_before(feature, ctx):
    data = _common(feature)
    data.update({
        "plane": geo.safe(lambda: geo.plane_of(feature.mirrorPlane), None),
        "combine": geo.safe(lambda: bool(feature.isCombine), False),
        "target_box_before": ctx.target_box(),
    })
    return data


# type name -> (before, after); either may be None
READERS = {
    "RectangularPatternFeature": (rectangular_before, pattern_after),
    "CircularPatternFeature": (circular_before, pattern_after),
    "MirrorFeature": (mirror_before, None),
}
