"""Hole features as plain dicts (docs/capture-format.md): the kind, the thread of a tapped hole, the extent, where the
centres sit, and the faces the hole made. The pair `hole_before` and `hole_after` follows the rules of `read_solid`.
"""
from . import read_extent
from . import read_geometry as geo
from .param_refs import Params, with_params
from .placement import ref_record
from .read_sketch import sketch_reference
from .read_thread import thread_info


_HOLE_TYPES = [("counterbore", "counterbore"), ("countersink", "countersink"), ("simple", "simple")]


_TAP_TYPES = [("taper", "taperTapped"), ("tapped", "tapped"), ("clearance", "clearance"), ("simple", "simple")]


def _cylinder(face):
    """A side face of a hole that is a cylinder: its `origin`, unit `axis`, `radius`, and the `span` of its vertices
    along the axis from the origin (where the face starts and ends; None when the vertices cannot be read)."""
    geometry = face.geometry
    if geo.type_name(geometry) != "Cylinder":
        return None
    found = {
        "origin": geo.point(geometry.origin),
        "axis": geo.unit_vector(geometry.axis),
        "radius": geo.length(geometry.radius),
    }
    found["span"] = geo.safe(lambda: geo.axial_span(found["origin"], found["axis"], geo.face_vertices(face)), None)
    return found


def _sketch_points(feature, ctx):
    """The sketch points of a hole placed on sketch points, else None. Fusion gives a hole on one sketch point a
    `SketchPointHolePositionDefinition` (`sketchPoint`), one on several a `SketchPointsHolePositionDefinition`
    (`sketchPoints`)."""
    definition = geo.safe(lambda: feature.holePositionDefinition, None)
    kind = geo.type_name(definition)
    if kind == "SketchPointHolePositionDefinition":
        point = geo.safe(lambda: definition.sketchPoint, None)
        return [geo.native_input(point, ctx)] if point is not None else None
    if "SketchPoints" not in kind:
        return None
    return [geo.native_input(p, ctx) for p in geo.collection_items(definition.sketchPoints)]


def _hole_sketch(points, ctx):
    """`sketch_token`, `sketch` and `point_tokens` (one per position) of the sketch points of a hole, the frame of
    that sketch (`sketch_frame`, as a profile's `frame`) and what it sits on (`reference`, as a profile's
    `reference`). Points on several sketches give only the first sketch's token: the hole then cannot be followed and
    keeps that sketch fixed."""
    if not points:
        return {}
    sketches = [geo.safe(lambda: p.parentSketch, None) for p in points]
    tokens = [geo.safe(lambda: s.entityToken, "") or "" for s in sketches]
    found = {}
    if tokens[0]:
        found["sketch_token"] = tokens[0]
        name = geo.safe(lambda: sketches[0].name, "")
        if name:
            found["sketch"] = name
        reference = geo.safe(lambda: sketch_reference(sketches[0], ctx), None)
        if reference is not None:
            found["reference"] = reference
    point_tokens = [geo.safe(lambda: p.entityToken, "") or "" for p in points]
    if found and all(point_tokens) and len(set(tokens)) == 1:
        found["point_tokens"] = point_tokens
        frame = geo.safe(lambda: geo.frame_of(sketches[0].transform), None)
        if frame is not None:
            found["sketch_frame"] = frame
    return found


def _foreign_sketch_points(points, ctx):
    """`positions` of sketch points of another component, brought into the target's coordinates, with one measured
    reference per point (`position_refs`). The sketch is not named, so the size probe leaves it alone. When a point
    cannot be brought in (the target's or the point's place cannot be read) the positions stay as Fusion gives them and
    the hole is marked foreign."""
    worlds = [geo.point(p.worldGeometry) for p in points]
    refs = [ref_record(p, ctx, "positions.%d" % n, {"point": world}) for n, (p, world) in enumerate(zip(points, worlds))]
    if all("point" in ref for ref in refs):
        return {"positions": [ref["point"] for ref in refs], "position_refs": refs}
    return {"positions": worlds, "position_refs": refs, "foreign": True}


# Members of each hole position definition type that hold the faces, planes, edges or points it is placed on. A
# definition of any other type (an edge placement among them, whose member names are not fixed) is read through
# every member named in _ALL_PLACE_MEMBERS; a member a type lacks reads as nothing.
_PLACE_MEMBERS = {
    "PointHolePositionDefinition": ("planarEntity", "point"),
    "PlaneAndOffsetsHolePositionDefinition": ("planarEntity", "edgeOne", "edgeTwo"),
    "AtCenterHolePositionDefinition": ("planarEntity", "centerEdge"),
}


_ALL_PLACE_MEMBERS = ("planarEntity", "edge", "edges", "referenceEdge", "centerEdge", "edgeOne", "edgeTwo", "point",
                      "face", "faces", "plane", "planeEntity", "entity")


def _foreign_place(feature, ctx):
    """`foreign` and `position_refs` of a hole placed on a face, plane, edge or point of another component, else {}."""
    definition = geo.safe(lambda: feature.holePositionDefinition, None)
    members = _PLACE_MEMBERS.get(geo.type_name(definition), _ALL_PLACE_MEMBERS)
    placed = []
    for member in members:
        value = geo.safe(lambda: getattr(definition, member), None)
        if value is None:
            continue
        placed += geo.collection_items(value) if geo.is_sequence(value) else [value]
    outside = [geo.native_input(e, ctx) for e in placed]
    outside = [e for e in outside if geo.foreign(e, ctx)]
    if not outside:
        return {}
    return {"foreign": True, "position_refs": [ref_record(e, ctx, "positions.0") for e in outside]}


def hole_place(feature, ctx):
    """The hole centres (`positions`) and what they sit on. Sketch points give their sketch and point tokens (the size
    probe follows them); those of another component's sketch are brought into the target's coordinates and give
    `position_refs` instead. A face, plane or edge of another component marks the hole foreign."""
    points = _sketch_points(feature, ctx)
    if points is None:
        return dict({"positions": [geo.point(feature.position)]}, **geo.safe(lambda: _foreign_place(feature, ctx), {}))
    if any(geo.foreign(p, ctx) for p in points):
        return _foreign_sketch_points(points, ctx)
    return dict({"positions": [geo.point(p.worldGeometry) for p in points]},
                **geo.safe(lambda: _hole_sketch(points, ctx), {}))


def _hole_extent(feature, ctx):
    definition = feature.extentDefinition
    name = geo.type_name(definition)
    if "ThroughAll" in name or name.startswith("All"):
        return {"kind": "throughAll"}
    if name == "DistanceExtentDefinition":
        return {"kind": "distance", "depth": geo.length(definition.distance)}
    if "ToEntity" in name:
        return dict({"kind": "toEntity"}, **read_extent.target(definition, ctx, "extent"))
    return {"kind": "other", "type": name}


def _hole_thread(feature, tapped):
    """The thread of a tapped hole as `read_thread.thread_info` gives it, plus `full_length`, `depth` (how deep the
    thread runs when it is not full length) and `offset`. Fusion keeps the numbers of a tapped hole in
    `HoleFeature.tappedHoleInfo` and in the hidden thread feature `HoleFeature.thread` (its `threadInfo`,
    `isFullLength`, `threadLength` and `threadOffset`); the older guesses `threadInfo` and `threadDepth` on the hole
    are still tried. What is missing reads as null (a gap)."""
    if not tapped:
        return None
    source = geo.safe(lambda: feature.thread, None)
    found = thread_info(geo.safe(lambda: feature.tappedHoleInfo, None), geo.safe(lambda: source.threadInfo, None),
                        source, geo.safe(lambda: feature.threadInfo, None), feature)
    full = geo.safe(lambda: source.isFullLength, None)
    if full is None:
        full = geo.safe(lambda: feature.isFullLength, None)
    found["full_length"] = full if isinstance(full, bool) else None
    depth = geo.safe(lambda: geo.length(source.threadLength), None)
    found["depth"] = depth if depth is not None else geo.safe(lambda: geo.length(feature.threadDepth), None)
    found["offset"] = geo.safe(lambda: geo.length(source.threadOffset), None)
    return found


def _thread_span(feature, data):
    """[low, high]: how deep below the mouth of the first hole the faces of a tapped hole's modeled thread reach, along
    the hole's direction, from their vertices; None when they cannot be read."""
    positions, direction = data.get("positions") or [], data.get("direction")
    if not positions or not direction:
        return None
    points = []
    for face in geo.collection_items(geo.safe(lambda: feature.thread.faces, None)):
        points += geo.safe(lambda: geo.face_vertices(face), [])
    return geo.axial_span(positions[0], direction, points)


def _hole_params(feature, hole_type, tapped):
    found = Params()
    found.add("diameter", lambda: feature.holeDiameter)
    found.add("tip_angle_deg", lambda: feature.tipAngle, "angle")
    found.add("extent.depth", lambda: read_extent.extent_distance(feature.extentDefinition))
    if tapped:
        found.add("thread.depth", lambda: feature.thread.threadLength)
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
        "thread": _hole_thread(feature, tapped),
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
        **hole_place(feature, ctx),
        "extent": geo.safe(lambda: _hole_extent(feature, ctx), {"kind": "other", "type": "unreadable"}),
        "side_cylinders": [],
        "end_points": [],
        "end_face_types": [],
        "participants": geo.safe(lambda: geo.body_refs(feature.participantBodies, ctx), []),
    }, _hole_params(feature, hole_type, tapped))


# The surfaces a hole can end in: a flat end (its normal along the hole) and a drill point (its axis along the hole).
_END_FACE_TYPES = {"Plane": ("plane", "normal"), "Cone": ("cone", "axis")}
# How far from 1 the cosine between an end face's normal or axis and the hole's direction may be.
_ALONG_TOL = 1e-5


def _end_face(face, direction):
    """(`pointOnFace`, "plane" or "cone") of an end face of a hole that is a flat end square to the hole's direction or
    a cone about it, else None. Fusion also lists other faces as end faces: the helical faces of a modeled thread
    (whose geometry has no type) are neither the bottom of the hole nor where it comes out."""
    geometry = face.geometry
    kind, member = _END_FACE_TYPES.get(geo.type_name(geometry), (None, None))
    if kind is None or not direction:
        return None
    along = geo.unit_vector(getattr(geometry, member))
    if abs(abs(sum(along[i] * direction[i] for i in range(3))) - 1.0) > _ALONG_TOL:
        return None
    return geo.point(face.pointOnFace), kind


def hole_after(feature, ctx, data):
    side = []
    for face in geo.collection_items(geo.safe(lambda: feature.sideFaces, None)):
        cylinder = geo.safe(lambda: _cylinder(face), None)
        if cylinder is not None:
            side.append(cylinder)
    ends, end_types = [], []
    for face in geo.collection_items(geo.safe(lambda: feature.endFaces, None)):
        found = geo.safe(lambda: _end_face(face, data.get("direction")), None)
        if found is not None:
            ends.append(found[0])
            end_types.append(found[1])
    found = {"side_cylinders": side, "end_points": ends, "end_face_types": end_types}
    if isinstance(data.get("thread"), dict) and data.get("thread_modeled"):
        found["thread"] = dict(data["thread"], made_span=_thread_span(feature, data))
    return found


READERS = {"HoleFeature": (hole_before, hole_after)}
