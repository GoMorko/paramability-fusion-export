"""Extrude, revolve, hole, combine and thread features as plain dicts (docs/capture-format.md).

Each feature type has a pair of readers. `before(feature, ctx)` runs with the timeline marker just before the item
and reads the inputs. `after(feature, ctx, data)` runs with the marker just after it and reads what the feature
produced (the measured values that check signs and flags). Both return dicts that go into the item's data.
A member that is missing or retired falls back to a default or to an `other` entry; it never stops the walk.
"""
from . import read_geometry as geo
from .read_sketch import read_profiles

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
    return geo.safe(lambda: geo.angle(getattr(feature, member)), 0.0)


def _extent(definition, taper_deg):
    """One side of an extrude as { kind, ... }."""
    name = geo.type_name(definition)
    if "ThroughAll" in name:
        return {
            "kind": "throughAll",
            "positive": geo.safe(lambda: bool(definition.isPositiveDirection), True),
            "taper_deg": taper_deg,
        }
    if name.startswith("All"):
        return {"kind": "all"}
    if "ToEntity" in name:
        return {
            "kind": "toEntity",
            "plane": geo.safe(lambda: geo.plane_of(definition.entity), None),
            "offset": geo.safe(lambda: geo.length(definition.offset), 0.0),
        }
    if name == "DistanceExtentDefinition":
        return {"kind": "distance", "distance": geo.length(definition.distance), "taper_deg": taper_deg}
    return {"kind": "other", "type": name}


def _start(feature):
    definition = feature.startExtent
    name = geo.type_name(definition)
    if "Offset" in name:
        return {"kind": "offset", "offset": geo.length(definition.offset)}
    if "Entity" in name:
        return {"kind": "fromEntity", "plane": geo.safe(lambda: geo.plane_of(definition.entity), None)}
    if "ProfilePlane" in name or name == "none":
        return {"kind": "profilePlane"}
    return {"kind": "other", "type": name}


def _extent_type(feature):
    name = geo.enum_name(feature.extentType, "FeatureExtentTypes")
    found = geo.pick_by_text(name, _EXTENT_TYPES, "")
    if found:
        return found
    return "two" if geo.safe(lambda: bool(feature.hasTwoExtents), False) else "one"


def extrude_before(feature, ctx):
    extent_type = _extent_type(feature)
    side_one = side_two = symmetric = None
    if extent_type == "symmetric":
        sym = feature.symmetricExtent
        symmetric = {
            "distance": geo.length(sym.distance),
            "full_length": geo.safe(lambda: bool(sym.isFullLength), False),
            "taper_deg": geo.safe(lambda: geo.angle(sym.taperAngle), 0.0),
        }
    else:
        side_one = _extent(feature.extentOne, _taper(feature, "taperAngleOne"))
        if extent_type == "two":
            side_two = _extent(feature.extentTwo, _taper(feature, "taperAngleTwo"))
    return {
        "operation": _operation(feature.operation),
        "profiles": read_profiles(feature.profile),
        "start": geo.safe(lambda: _start(feature), {"kind": "profilePlane"}),
        "extent_type": extent_type,
        "side_one": side_one,
        "side_two": side_two,
        "symmetric": symmetric,
        "thin": geo.safe(lambda: bool(feature.isThinExtrude), False),
        "participants": geo.safe(lambda: geo.body_refs(feature.participantBodies), []),
        "target_box_before": ctx.target_box(),
        "end_offset": None,
    }


def _dot(a, b):
    return sum(x * y for x, y in zip(a, b))


def extrude_after(feature, ctx, data):
    """end_offset: signed distance from the first profile's sketch plane to a point on the first end face."""
    profiles = data.get("profiles") or []
    if not profiles or "frame" not in profiles[0]:
        return {}
    frame = profiles[0]["frame"]
    faces = geo.collection_items(geo.safe(lambda: feature.endFaces, None))
    if not faces:
        return {}
    p = geo.safe(lambda: geo.point(faces[0].pointOnFace), None)
    if p is None:
        return {}
    offset = _dot([a - b for a, b in zip(p, frame["origin"])], frame["z"])
    return {"end_offset": round(offset, 6) + 0.0}


class _Delta:
    def __init__(self, a, b):
        self.x, self.y, self.z = b.x - a.x, b.y - a.y, b.z - a.z


def _line_axis(line):
    return {"point": geo.point(line.startPoint), "dir": geo.unit_vector(_Delta(line.startPoint, line.endPoint))}


def _axis(entity):
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


def _revolve_extent(definition):
    name = geo.type_name(definition)
    if name == "AngleExtentDefinition":
        return {
            "kind": "angle",
            "angle_deg": geo.angle(definition.angle),
            "symmetric": geo.safe(lambda: bool(definition.isSymmetric), False),
        }
    if name == "TwoSidesAngleExtentDefinition":
        return {
            "kind": "twoSidesAngle",
            "angle_one_deg": geo.angle(definition.angleOne),
            "angle_two_deg": geo.angle(definition.angleTwo),
        }
    return {"kind": "other", "type": name}


def revolve_before(feature, ctx):
    return {
        "operation": _operation(feature.operation),
        "profiles": read_profiles(feature.profile),
        "axis": geo.safe(lambda: _axis(feature.axis), {"kind": "other"}),
        "project_axis": geo.safe(lambda: bool(feature.isProjectAxis), False),
        "extent": _revolve_extent(feature.extentDefinition),
        "participants": geo.safe(lambda: geo.body_refs(feature.participantBodies), []),
        "start_face_normal": None,
    }


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


def hole_before(feature, ctx):
    hole_type = geo.pick_by_text(geo.enum_name(feature.holeType, "HoleTypes"), _HOLE_TYPES, "simple")
    tap_type = geo.pick_by_text(geo.enum_name(feature.holeTapType, "HoleTapTypes"), _TAP_TYPES, "simple")
    tapped = tap_type in ("tapped", "taperTapped")
    return {
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
        "positions": geo.safe(lambda: _hole_positions(feature), []),
        "extent": geo.safe(lambda: _hole_extent(feature), {"kind": "other", "type": "unreadable"}),
        "side_cylinders": [],
        "end_points": [],
        "participants": geo.safe(lambda: geo.body_refs(feature.participantBodies), []),
    }


def hole_after(feature, ctx, data):
    side = []
    for face in geo.collection_items(geo.safe(lambda: feature.sideFaces, None)):
        cylinder = geo.safe(lambda: _cylinder(face), None)
        if cylinder is not None:
            side.append(cylinder)
    ends = []
    for face in geo.collection_items(geo.safe(lambda: feature.endFaces, None)):
        p = geo.safe(lambda: geo.point(face.pointOnFace), None)
        if p is not None:
            ends.append(p)
    return {"side_cylinders": side, "end_points": ends}


def combine_before(feature, ctx):
    return {
        "target": geo.body_ref(feature.targetBody),
        "tools": geo.body_refs(feature.toolBodies),
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
