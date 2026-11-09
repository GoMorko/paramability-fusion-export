"""Extrude, revolve, hole, combine and thread features as plain dicts (docs/capture-format.md).

Each feature type has a pair of readers. `before(feature, ctx)` runs with the timeline marker just before the item
and reads the inputs. `after(feature, ctx, data)` runs with the marker just after it and reads what the feature
produced (the measured values that check signs and flags). Both return dicts that go into the item's data.
A member that is missing or retired never stops the walk and never becomes a plausible value: it reads as None or as
an `other` entry (which the translator refuses), or the reader raises and the item gets a `read_error`. Only members
that feed a note, such as the participant bodies, fall back to an empty list.
"""
from . import read_geometry as geo
from .param_refs import Params, with_params
from .read_sketch import first_profile, profile_area, read_profiles

_OPERATIONS = [
    ("newcomponent", "newComponent"),
    ("newbody", "newBody"),
    ("join", "join"),
    ("cut", "cut"),
    ("intersect", "intersect"),
]
_EXTENT_TYPES = [("twosides", "two"), ("symmetric", "symmetric"), ("oneside", "one")]
_HOLE_TYPES = [("counterbore", "counterbore"), ("countersink", "countersink"), ("simple", "simple")]
_TAP_TYPES = [("taper", "taperTapped"), ("tapped", "tapped"), ("clearance", "clearance"), ("simple", "simple")]

_FULL_TURN_DEG = 360.0 - 1e-6


def _operation(value):
    return geo.pick_by_text(geo.enum_name(value, "FeatureOperations"), _OPERATIONS, "other")


def _taper(feature, member):
    return geo.safe(lambda: geo.angle(getattr(feature, member)), None)


def _target(definition, ctx):
    """The face or plane an extrude starts from or reaches to: its plane, its type, and a point on a face."""
    entity = geo.safe(lambda: definition.entity, None)
    found = {"plane": geo.safe(lambda: geo.plane_of(entity), None),
             "entity_type": geo.safe(lambda: geo.type_name(entity), None)}
    if found["entity_type"] == "BRepFace":
        found["face_point"] = geo.safe(lambda: geo.point(entity.pointOnFace), None)
    return geo.mark_foreign(found, entity, ctx)


def _extent(definition, taper_deg, ctx):
    """One side of an extrude as { kind, ... }."""
    name = geo.type_name(definition)
    if "ThroughAll" in name:
        return {
            "kind": "throughAll",
            "positive": geo.safe(lambda: bool(definition.isPositiveDirection), None),
            "taper_deg": taper_deg,
        }
    if name.startswith("All"):
        return {"kind": "all"}
    if "ToEntity" in name:
        return dict({"kind": "toEntity", "offset": geo.safe(lambda: geo.length(definition.offset), None)},
                    **_target(definition, ctx))
    if name == "DistanceExtentDefinition":
        return {"kind": "distance", "distance": geo.length(definition.distance), "taper_deg": taper_deg}
    return {"kind": "other", "type": name}


def _start(feature, ctx):
    definition = feature.startExtent
    name = geo.type_name(definition)
    if "Offset" in name:
        return {"kind": "offset", "offset": geo.length(definition.offset)}
    if "Entity" in name:
        return dict({"kind": "fromEntity"}, **_target(definition, ctx))
    if "ProfilePlane" in name:
        return {"kind": "profilePlane"}
    return {"kind": "other", "type": name}


def _extent_type(feature):
    name = geo.enum_name(feature.extentType, "FeatureExtentTypes")
    return geo.pick_by_text(name, _EXTENT_TYPES, "other")


def _first_profile_area(feature):
    first = first_profile(geo.safe(lambda: feature.profile, None))
    return profile_area(first) if first is not None else None


def _extent_distance(definition):
    """The distance parameter of a plain distance extent, else None."""
    return definition.distance if geo.type_name(definition) == "DistanceExtentDefinition" else None


def _extrude_params(feature, extent_type):
    found = Params()
    if extent_type == "symmetric":
        sym = feature.symmetricExtent
        found.add("symmetric.distance", lambda: sym.distance)
        found.add("symmetric.taper_deg", lambda: sym.taperAngle, "angle")
    elif extent_type in ("one", "two"):
        found.add("side_one.distance", lambda: _extent_distance(feature.extentOne))
        found.add("side_one.taper_deg", lambda: feature.taperAngleOne, "angle")
        found.add("side_one.offset", lambda: feature.extentOne.offset)
        if extent_type == "two":
            found.add("side_two.distance", lambda: _extent_distance(feature.extentTwo))
            found.add("side_two.taper_deg", lambda: feature.taperAngleTwo, "angle")
            found.add("side_two.offset", lambda: feature.extentTwo.offset)
    found.add("start.offset", lambda: feature.startExtent.offset)
    return found.found


def extrude_before(feature, ctx):
    extent_type = _extent_type(feature)
    side_one = side_two = symmetric = None
    if extent_type == "other":
        side_one = {"kind": "other", "type": "FeatureExtentTypes"}
    elif extent_type == "symmetric":
        sym = feature.symmetricExtent
        symmetric = {
            "distance": geo.length(sym.distance),
            "full_length": geo.safe(lambda: bool(sym.isFullLength), None),
            "taper_deg": geo.safe(lambda: geo.angle(sym.taperAngle), None),
        }
    else:
        side_one = _extent(feature.extentOne, _taper(feature, "taperAngleOne"), ctx)
        if extent_type == "two":
            side_two = _extent(feature.extentTwo, _taper(feature, "taperAngleTwo"), ctx)
    return with_params({
        "operation": _operation(feature.operation),
        "profiles": read_profiles(feature.profile, ctx),
        "start": geo.safe(lambda: _start(feature, ctx), {"kind": "other", "type": "unreadable"}),
        "extent_type": extent_type,
        "side_one": side_one,
        "side_two": side_two,
        "symmetric": symmetric,
        "thin": geo.safe(lambda: bool(feature.isThinExtrude), None),
        "participants": geo.safe(lambda: geo.body_refs(feature.participantBodies, ctx), []),
        "target_box_before": ctx.target_box(),
        "end_offset": None,
        "profile_area": _first_profile_area(feature),
        "end_area": None,
    }, _extrude_params(feature, extent_type))


def _dot(a, b):
    return sum(x * y for x, y in zip(a, b))


def extrude_after(feature, ctx, data):
    """end_offset: signed distance from the first profile's sketch plane to a point on the first end face.

    end_area: the area of that face in mm2 (with profile_area, it shows which way a taper goes).
    """
    faces = geo.collection_items(geo.safe(lambda: feature.endFaces, None))
    if not faces:
        return {}
    out = {"end_area": geo.safe(lambda: round(faces[0].area * 100.0, 6) + 0.0, None)}
    profiles = data.get("profiles") or []
    if not profiles or "frame" not in profiles[0]:
        return out
    frame = profiles[0]["frame"]
    p = geo.safe(lambda: geo.point(faces[0].pointOnFace), None)
    if p is None:
        return out
    offset = _dot([a - b for a, b in zip(p, frame["origin"])], frame["z"])
    out["end_offset"] = round(offset, 6) + 0.0
    return out


class _Delta:
    def __init__(self, a, b):
        self.x, self.y, self.z = b.x - a.x, b.y - a.y, b.z - a.z


def _line_axis(line):
    return {"point": geo.point(line.startPoint), "dir": geo.unit_vector(_Delta(line.startPoint, line.endPoint))}


def axis_of(entity):
    """Axis of a revolve from a sketch line, construction axis, linear edge or cylindrical face."""
    name = geo.type_name(entity)
    if name == "SketchLine":
        return _line_axis(entity.worldGeometry)
    if name == "ConstructionAxis":
        line = entity.geometry
        return {"point": geo.point(line.origin), "dir": geo.unit_vector(line.direction)}
    if name == "BRepEdge":
        line = entity.geometry
        if geo.type_name(line) == "Line3D":
            return _line_axis(line)
    if name == "BRepFace":
        cylinder = entity.geometry
        if geo.type_name(cylinder) == "Cylinder":
            return {"point": geo.point(cylinder.origin), "dir": geo.unit_vector(cylinder.axis)}
    return {"kind": "other"}


def axis_record(entity, ctx):
    """`axis_of` with "foreign": true when the axis entity is not the target component's."""
    return geo.mark_foreign(axis_of(entity), entity, ctx)


def _revolve_extent(definition):
    name = geo.type_name(definition)
    if name == "AngleExtentDefinition":
        return {
            "kind": "angle",
            "angle_deg": geo.angle(definition.angle),
            "symmetric": geo.safe(lambda: bool(definition.isSymmetric), None),
        }
    if name == "TwoSidesAngleExtentDefinition":
        return {
            "kind": "twoSidesAngle",
            "angle_one_deg": geo.angle(definition.angleOne),
            "angle_two_deg": geo.angle(definition.angleTwo),
        }
    return {"kind": "other", "type": name}


def revolve_before(feature, ctx):
    return with_params({
        "operation": _operation(feature.operation),
        "profiles": read_profiles(feature.profile, ctx),
        "axis": geo.safe(lambda: axis_record(feature.axis, ctx), {"kind": "other"}),
        "project_axis": geo.safe(lambda: bool(feature.isProjectAxis), None),
        "extent": _revolve_extent(feature.extentDefinition),
        "participants": geo.safe(lambda: geo.body_refs(feature.participantBodies, ctx), []),
        "start_face_normal": None,
    }, Params().add("extent.angle_deg", lambda: feature.extentDefinition.angle, "angle").found)


def revolve_after(feature, ctx, data):
    """start_face_normal: the normal of the first start face at a point on it; null for a full turn."""
    extent = data.get("extent") or {}
    if extent.get("kind") == "angle" and extent.get("angle_deg", 0) >= _FULL_TURN_DEG:
        return {}
    faces = geo.collection_items(geo.safe(lambda: feature.startFaces, None))
    if not faces:
        return {}

    def normal():
        face = faces[0]
        ok, n = face.evaluator.getNormalAtPoint(face.pointOnFace)
        return geo.unit_vector(n) if ok else None

    return {"start_face_normal": geo.safe(normal, None)}


def _cylinder(face):
    geometry = face.geometry
    if geo.type_name(geometry) != "Cylinder":
        return None
    return {
        "origin": geo.point(geometry.origin),
        "axis": geo.unit_vector(geometry.axis),
        "radius": geo.length(geometry.radius),
    }


def _hole_positions(feature):
    definition = geo.safe(lambda: feature.holePositionDefinition, None)
    if "SketchPoints" in geo.type_name(definition):
        return [geo.point(p.worldGeometry) for p in geo.collection_items(definition.sketchPoints)]
    return [geo.point(feature.position)]


def _hole_extent(feature):
    definition = feature.extentDefinition
    name = geo.type_name(definition)
    if "ThroughAll" in name or name.startswith("All"):
        return {"kind": "throughAll"}
    if name == "DistanceExtentDefinition":
        return {"kind": "distance", "depth": geo.length(definition.distance)}
    if "ToEntity" in name:
        return {"kind": "toEntity"}
    return {"kind": "other", "type": name}


def _hole_params(feature, hole_type):
    found = Params()
    found.add("diameter", lambda: feature.holeDiameter)
    found.add("tip_angle_deg", lambda: feature.tipAngle, "angle")
    found.add("extent.depth", lambda: _extent_distance(feature.extentDefinition))
    if hole_type == "counterbore":
        found.add("counterbore.diameter", lambda: feature.counterboreDiameter)
        found.add("counterbore.depth", lambda: feature.counterboreDepth)
    elif hole_type == "countersink":
        found.add("countersink.diameter", lambda: feature.countersinkDiameter)
        found.add("countersink.angle_deg", lambda: feature.countersinkAngle, "angle")
    return found.found


def hole_before(feature, ctx):
    hole_type = geo.pick_by_text(geo.enum_name(feature.holeType, "HoleTypes"), _HOLE_TYPES, "other")
    tap_type = geo.pick_by_text(geo.enum_name(feature.holeTapType, "HoleTapTypes"), _TAP_TYPES, "other")
    tapped = tap_type in ("tapped", "taperTapped")
    return with_params({
        "hole_type": hole_type,
        "tap_type": tap_type,
        "thread_modeled": geo.safe(lambda: bool(feature.thread.isModeled), None) if tapped else None,
        "diameter": geo.length(feature.holeDiameter),
        "tip_angle_deg": geo.safe(lambda: geo.angle(feature.tipAngle), None),
        "counterbore": {
            "diameter": geo.length(feature.counterboreDiameter),
            "depth": geo.length(feature.counterboreDepth),
        } if hole_type == "counterbore" else None,
        "countersink": {
            "diameter": geo.length(feature.countersinkDiameter),
            "angle_deg": geo.angle(feature.countersinkAngle),
        } if hole_type == "countersink" else None,
        "direction": geo.safe(lambda: geo.unit_vector(feature.direction), None),
        "positions": _hole_positions(feature),
        "extent": geo.safe(lambda: _hole_extent(feature), {"kind": "other", "type": "unreadable"}),
        "side_cylinders": [],
        "end_points": [],
        "end_face_types": [],
        "participants": geo.safe(lambda: geo.body_refs(feature.participantBodies, ctx), []),
    }, _hole_params(feature, hole_type))


_END_FACE_TYPES = {"Plane": "plane", "Cone": "cone"}


def hole_after(feature, ctx, data):
    side = []
    for face in geo.collection_items(geo.safe(lambda: feature.sideFaces, None)):
        cylinder = geo.safe(lambda: _cylinder(face), None)
        if cylinder is not None:
            side.append(cylinder)
    ends, end_types = [], []
    for face in geo.collection_items(geo.safe(lambda: feature.endFaces, None)):
        p = geo.safe(lambda: geo.point(face.pointOnFace), None)
        if p is not None:
            ends.append(p)
            end_types.append(_END_FACE_TYPES.get(geo.safe(lambda: geo.type_name(face.geometry), None)))
    return {"side_cylinders": side, "end_points": ends, "end_face_types": end_types}


def combine_before(feature, ctx):
    return {
        "target": geo.body_ref(feature.targetBody, ctx),
        "tools": geo.body_refs(feature.toolBodies, ctx),
        "operation": _operation(feature.operation),
        "keep_tools": geo.safe(lambda: bool(feature.isKeepToolBodies), False),
    }


def thread_before(feature, ctx):
    return {"modeled": geo.safe(lambda: bool(feature.isModeled), True)}


# type name -> (before, after); either may be None
READERS = {
    "ExtrudeFeature": (extrude_before, extrude_after),
    "RevolveFeature": (revolve_before, revolve_after),
    "HoleFeature": (hole_before, hole_after),
    "CombineFeature": (combine_before, None),
    "ThreadFeature": (thread_before, None),
}
