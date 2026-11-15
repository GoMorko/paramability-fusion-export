"""Extrude, revolve, hole and combine features as plain dicts (docs/capture-format.md).

Each feature type has a pair of readers. `before(feature, ctx)` runs with the timeline marker just before the item
and reads the inputs. `after(feature, ctx, data)` runs with the marker just after it and reads what the feature
produced (the measured values that check signs and flags). Both return dicts that go into the item's data.
A member that is missing or retired never stops the walk and never becomes a plausible value: it reads as None or as
an `other` entry (which the translator refuses), or the reader raises and the item gets a `read_error`. Only members
that feed a note, such as the participant bodies, fall back to an empty list.
"""
from ..geometry import vec
from . import read_geometry as geo
from . import read_intersect
from .param_refs import Params, with_params
from .placement import foreign_target_ref, from_assembly, ref_record
from .read_bodies import tool_ref
from .read_sketch import first_profile, profile_area, read_outlines, read_profiles
from .read_thread import thread_info

_OPERATIONS = [
    ("newcomponent", "newComponent"),
    ("newbody", "newBody"),
    ("join", "join"),
    ("cut", "cut"),
    ("intersect", "intersect"),
]
_EXTENT_TYPES = [("twosides", "two"), ("symmetric", "symmetric"), ("oneside", "one")]
_WALL_LOCATIONS = [("side1", "side1"), ("side2", "side2"), ("center", "center")]
_HOLE_TYPES = [("counterbore", "counterbore"), ("countersink", "countersink"), ("simple", "simple")]
_TAP_TYPES = [("taper", "taperTapped"), ("tapped", "tapped"), ("clearance", "clearance"), ("simple", "simple")]

_FULL_TURN_DEG = 360.0 - 1e-6


def operation_of(value):
    return geo.pick_by_text(geo.enum_name(value, "FeatureOperations"), _OPERATIONS, "other")


def _taper(feature, member):
    return geo.safe(lambda: geo.angle(getattr(feature, member)), None)


def construction_token(entity):
    """{ "token": ... } for a construction plane or axis (it names the parameters behind it), else {}."""
    if geo.type_name(entity) in ("ConstructionPlane", "ConstructionAxis"):
        token = geo.safe(lambda: entity.entityToken, "")
        if token:
            return {"token": token}
    return {}


def _target(definition, ctx, slot):
    """The face or plane an extrude starts from or reaches to: its plane, its type, its token, and a point on a face.
    One of another component is marked foreign and carries its measured reference (`ref`, see
    `placement.ref_record`)."""
    entity = geo.native_input(geo.safe(lambda: definition.entity, None), ctx)
    found = {"plane": geo.safe(lambda: geo.plane_of(entity), None),
             "entity_type": geo.safe(lambda: geo.type_name(entity), None)}
    found.update(construction_token(entity))
    if found["entity_type"] == "BRepFace":
        found["face_point"] = geo.safe(lambda: geo.point(entity.pointOnFace), None)
        body = geo.owner_body(entity, ctx)
        if body:
            found["body"] = body
    geo.mark_foreign(found, entity, ctx)
    if found.get("foreign"):
        foreign_target_ref(found, entity, ctx, slot)
    else:
        from .read_reference import describe_plane  # read_reference imports this module

        describe_plane(found, entity, ctx)
        if found["entity_type"] == "BRepFace":
            # The size probe finds the face again by its token and measures how it moves.
            token = geo.safe(lambda: entity.entityToken, "")
            if token:
                found["token"] = token
    return found


def _extent(definition, taper_deg, ctx, slot):
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
                    **_target(definition, ctx, slot))
    if name == "DistanceExtentDefinition":
        # Fusion can refuse the distance of a valid extrude; the step is then left out, not the whole copy stopped.
        distance = geo.safe(lambda: geo.length(definition.distance), None)
        if distance is None:
            return {"kind": "other", "type": name}
        return {"kind": "distance", "distance": distance, "taper_deg": taper_deg}
    return {"kind": "other", "type": name}


def _start(feature, ctx):
    definition = feature.startExtent
    name = geo.type_name(definition)
    if "Offset" in name:
        return {"kind": "offset", "offset": geo.length(definition.offset)}
    if "Entity" in name:
        return dict({"kind": "fromEntity"}, **_target(definition, ctx, "start"))
    if "ProfilePlane" in name:
        return {"kind": "profilePlane"}
    return {"kind": "other", "type": name}


def _extent_type(feature):
    name = geo.enum_name(feature.extentType, "FeatureExtentTypes")
    return geo.pick_by_text(name, _EXTENT_TYPES, "other")


def _holds_free_outline(profiles):
    """True when a profile record is sketch text or has a free curve (a spline): the shapes the translator rebuilds
    from samples and so checks against the part Fusion made."""
    return any(p.get("text") or any(c.get("kind") == "other" for loop in p.get("loops") or []
                                    for c in loop.get("curves") or []) for p in profiles)


def _new_bodies_volume(feature):
    """Summed volume in mm3 of the bodies a feature made, or None when one cannot be read."""
    bodies = geo.collection_items(geo.safe(lambda: feature.bodies, None))
    found = [geo.safe(lambda: round(b.volume * 1000.0, 6) + 0.0, None) for b in bodies]
    return None if not found or any(v is None for v in found) else round(sum(found), 6) + 0.0


def _first_profile_area(feature, profiles, areas):
    """Area in mm2 of the first sketch profile, or of the face when the first outline is a flat face."""
    if profiles and isinstance(profiles[0], dict) and profiles[0].get("face"):
        return areas[0] if areas else None
    first = first_profile(geo.safe(lambda: feature.profile, None))
    return profile_area(first) if first is not None else None


def _extent_distance(definition):
    """The distance parameter of a plain distance extent, else None."""
    return definition.distance if geo.type_name(definition) == "DistanceExtentDefinition" else None


def _wall_location(member):
    """"side1", "side2", "center" or "other" for a thin wall location; None when it cannot be read."""
    return geo.safe(lambda: geo.pick_by_text(geo.enum_name(member(), "ThinExtrudeWallLocation"), _WALL_LOCATIONS,
                                             "other"), None)


def _thin_wall(feature):
    """The wall of a thin extrude: where it sits against the outline and how thick it is, for side one and side two
    (side two only counts for an extrude that goes two ways), and the type of the input the extrude takes its outline
    from (`profile_type`, to see what an open line comes back as). A member that cannot be read is null."""
    return {
        "location": _wall_location(lambda: feature.thinExtrudeWallLocationOne),
        "thickness": geo.safe(lambda: geo.length(feature.thinExtrudeWallThicknessOne), None),
        "location_two": _wall_location(lambda: feature.thinExtrudeWallLocationTwo),
        "thickness_two": geo.safe(lambda: geo.length(feature.thinExtrudeWallThicknessTwo), None),
        "profile_type": geo.safe(lambda: geo.type_name(feature.profile), None),
    }


def _extrude_params(feature, extent_type, thin=False):
    found = Params()
    if thin:
        found.add("thin.thickness", lambda: feature.thinExtrudeWallThicknessOne)
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
    thin = geo.safe(lambda: bool(feature.isThinExtrude), None)
    side_one = side_two = symmetric = None
    if extent_type == "other":
        side_one = {"kind": "other", "type": "FeatureExtentTypes"}
    elif extent_type == "symmetric":
        sym = feature.symmetricExtent
        distance = geo.safe(lambda: geo.length(sym.distance), None)
        symmetric = None if distance is None else {
            "distance": distance,
            "full_length": geo.safe(lambda: bool(sym.isFullLength), None),
            "taper_deg": geo.safe(lambda: geo.angle(sym.taperAngle), None),
        }
        if distance is None:
            # A symmetric extrude through all has no distance: its extent reads like one side's, with its own taper.
            taper = geo.safe(lambda: geo.angle(sym.taperAngle), None)
            side = geo.safe(lambda: _extent(feature.extentOne, taper, ctx, "side_one"), None)
            if side and side.get("kind") in ("throughAll", "all"):
                side_one = side
    else:
        side_one = _extent(feature.extentOne, _taper(feature, "taperAngleOne"), ctx, "side_one")
        if extent_type == "two":
            side_two = _extent(feature.extentTwo, _taper(feature, "taperAngleTwo"), ctx, "side_two")
    operation = operation_of(feature.operation)
    profiles, areas = read_outlines(feature.profile, ctx, before=geo.safe(lambda: feature.timelineObject.index, None))
    data = {
        "operation": operation,
        "profiles": profiles,
        "start": geo.safe(lambda: _start(feature, ctx), {"kind": "other", "type": "unreadable"}),
        "extent_type": extent_type,
        "side_one": side_one,
        "side_two": side_two,
        "symmetric": symmetric,
        "thin": thin,
        "participants": geo.safe(lambda: geo.body_refs(feature.participantBodies, ctx), []),
        "target_box_before": ctx.target_box(),
        "end_offset": None,
        "profile_area": _first_profile_area(feature, profiles, areas),
        "end_area": None,
    }
    if thin:
        data["thin_wall"] = _thin_wall(feature)
    if _holds_free_outline(profiles):
        data["areas"] = areas
        data["volume_before"] = 0.0 if operation == "newBody" else geo.target_volume(ctx)
        data["volume_after"] = None
    return with_params(data, _extrude_params(feature, extent_type, thin))


MAX_SIDE_FACES = 256


def _side_leans(feature, z):
    """Per side face, its outward normal along the sketch normal `z` (the sine of how far the wall leans), or
    None when a side face cannot be measured."""
    leans = []
    for face in geo.collection_items(geo.safe(lambda: feature.sideFaces, None))[:MAX_SIDE_FACES]:
        ok, normal = face.evaluator.getNormalAtPoint(face.pointOnFace)
        if not ok:
            return None
        leans.append(round(vec.dot(geo.unit_vector(normal), z), 9) + 0.0)
    return leans or None


def extrude_after(feature, ctx, data):
    """end_offset: signed distance from the first profile's sketch plane to a point on the first end face.

    end_area: the area of that face in mm2 (with profile_area, it shows which way a taper goes). side_leans: how
    far each side face leans along the first profile's sketch normal (the taper check for several outlines).
    volume_after: for an extrude of text or spline outlines, the volume that was measured before the item is
    compared with (the target's, or the new bodies' summed for a new body).
    """
    faces = geo.collection_items(geo.safe(lambda: feature.endFaces, None))
    profiles = data.get("profiles") or []
    frame = profiles[0].get("frame") if profiles and isinstance(profiles[0], dict) else None
    out = {}
    if "volume_before" in data:
        out["volume_after"] = (_new_bodies_volume(feature) if data.get("operation") == "newBody"
                               else geo.target_volume(ctx))
    if frame is not None:
        leans = geo.safe(lambda: _side_leans(feature, frame["z"]), None)
        if leans is not None:
            out["side_leans"] = leans
    if not faces:
        return out
    out["end_area"] = geo.safe(lambda: round(faces[0].area * 100.0, 6) + 0.0, None)
    if frame is None:
        return out
    p = geo.safe(lambda: geo.point(faces[0].pointOnFace), None)
    if p is None:
        return out
    offset = vec.dot([a - b for a, b in zip(p, frame["origin"])], frame["z"])
    out["end_offset"] = round(offset, 6) + 0.0
    return out


class _Delta:
    def __init__(self, a, b):
        self.x, self.y, self.z = b.x - a.x, b.y - a.y, b.z - a.z


def line_axis(line):
    """{ point, dir } of a Line3D: its start point and unit direction."""
    return {"point": geo.point(line.startPoint), "dir": geo.unit_vector(_Delta(line.startPoint, line.endPoint))}


def _sketch_line_axis(entity):
    """A sketch line as an axis, with the tokens of the line and its sketch and the sketch name."""
    found = line_axis(entity.worldGeometry)
    for key, read in (("entity", lambda: entity.entityToken), ("sketch_token", lambda: entity.parentSketch.entityToken),
                      ("sketch", lambda: entity.parentSketch.name)):
        value = geo.safe(read, "")
        if value:
            found[key] = value
    return found


def axis_of(entity):
    """Axis of a revolve from a sketch line, construction axis, linear edge or cylindrical face."""
    name = geo.type_name(entity)
    if name == "SketchLine":
        return _sketch_line_axis(entity)
    if name == "ConstructionAxis":
        line = entity.geometry
        return dict({"point": geo.point(line.origin), "dir": geo.unit_vector(line.direction)},
                    **construction_token(entity))
    if name == "BRepEdge":
        line = entity.geometry
        if geo.type_name(line) == "Line3D":
            return line_axis(line)
        return {"kind": "other", "type": name, "geometry": geo.type_name(line)}
    if name == "BRepFace":
        cylinder = entity.geometry
        if geo.type_name(cylinder) == "Cylinder":
            return {"point": geo.point(cylinder.origin), "dir": geo.unit_vector(cylinder.axis)}
        return {"kind": "other", "type": name, "geometry": geo.type_name(cylinder)}
    return {"kind": "other", "type": name}


def axis_record(entity, ctx, slot="axis"):
    """`axis_of` with "foreign": true when the axis entity is not the target component's. An axis seen through an
    occurrence or owned by the root is brought into the target's coordinates instead and marked `assembly`, with its
    measured reference (`ref`, in `slot`)."""
    entity = geo.native_input(entity, ctx)
    return from_assembly(geo.mark_foreign(axis_of(entity), entity, ctx), entity, ctx, "point", "dir", slot)


def revolve_axis(feature, ctx):
    """`axis_record` of a revolve's axis. One that cannot be read is `{ kind: "other" }` with the entity `type` and the
    `error`, so the reason can say what the axis is."""
    entity = geo.safe(lambda: feature.axis, None)
    if entity is None:
        return {"kind": "other", "type": "none", "error": "Fusion gave no axis"}
    try:
        return axis_record(entity, ctx)
    except Exception as exc:
        return {"kind": "other", "type": geo.type_name(entity), "error": ("%s: %s" % (type(exc).__name__, exc))[:200]}


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
        "operation": operation_of(feature.operation),
        "profiles": read_profiles(feature.profile, ctx),
        "axis": revolve_axis(feature, ctx),
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


def _sketch_points(feature, ctx):
    """The sketch points of a hole placed on sketch points, else None."""
    definition = geo.safe(lambda: feature.holePositionDefinition, None)
    if "SketchPoints" not in geo.type_name(definition):
        return None
    return [geo.native_input(p, ctx) for p in geo.collection_items(definition.sketchPoints)]


def _hole_sketch(points):
    """`sketch_token`, `sketch` and `point_tokens` (one per position) of the sketch points of a hole. Points on several
    sketches give only the first sketch's token: the hole then cannot be followed and keeps that sketch fixed."""
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
    point_tokens = [geo.safe(lambda: p.entityToken, "") or "" for p in points]
    if found and all(point_tokens) and len(set(tokens)) == 1:
        found["point_tokens"] = point_tokens
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
    return dict({"positions": [geo.point(p.worldGeometry) for p in points]}, **geo.safe(lambda: _hole_sketch(points), {}))


def _hole_extent(feature, ctx):
    definition = feature.extentDefinition
    name = geo.type_name(definition)
    if "ThroughAll" in name or name.startswith("All"):
        return {"kind": "throughAll"}
    if name == "DistanceExtentDefinition":
        return {"kind": "distance", "depth": geo.length(definition.distance)}
    if "ToEntity" in name:
        return dict({"kind": "toEntity"}, **_target(definition, ctx, "extent"))
    return {"kind": "other", "type": name}


def _hole_thread(feature, tapped):
    """The thread of a tapped hole as `read_thread.thread_info` gives it, plus `full_length` and `depth` (how deep the
    thread runs). The Fusion API stub of July 2025 has no tapped hole members at all, so where they live (`thread`,
    `threadInfo` or the hole itself) is hand check TD2; each is tried, and what is missing reads as null (a gap)."""
    if not tapped:
        return None
    source = geo.safe(lambda: feature.thread, None)
    found = thread_info(source, geo.safe(lambda: feature.threadInfo, None), feature)
    full = geo.safe(lambda: source.isFullLength, None)
    if full is None:
        full = geo.safe(lambda: feature.isFullLength, None)
    found["full_length"] = full if isinstance(full, bool) else None
    depth = geo.safe(lambda: geo.length(source.threadDepth), None)
    found["depth"] = depth if depth is not None else geo.safe(lambda: geo.length(feature.threadDepth), None)
    return found


def _hole_params(feature, hole_type, tapped):
    found = Params()
    found.add("diameter", lambda: feature.holeDiameter)
    found.add("tip_angle_deg", lambda: feature.tipAngle, "angle")
    found.add("extent.depth", lambda: _extent_distance(feature.extentDefinition))
    if tapped:
        found.add("thread.depth", lambda: feature.thread.threadDepth)
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


def _tool_bodies(collection, ctx):
    """The tool body refs of a Combine, each with its `volume` in mm3 (null when unreadable). A tool of another
    component is `foreign` and also names its native token, its component and the occurrence path
    (`read_bodies.tool_ref`), so the steps that made it can be read there."""
    out = []
    for body in geo.collection_items(collection):
        ref = tool_ref(body, ctx)
        ref["volume"] = geo.volume_mm3(body)
        out.append(ref)
    return out


def combine_before(feature, ctx):
    operation = operation_of(feature.operation)
    tools = _tool_bodies(feature.toolBodies, ctx)
    data = {
        "target": geo.body_ref(feature.targetBody, ctx),
        "tools": tools,
        "operation": operation,
        "keep_tools": geo.safe(lambda: bool(feature.isKeepToolBodies), False),
        "volume_before": geo.target_volume(ctx),
        "volume_after": None,
    }
    if operation == "intersect" and len(tools) >= 2:
        data["intersect_volumes"] = read_intersect.volumes(feature, tools)
    return data


def combine_after(feature, ctx, data):
    """volume_after: the target's volume in mm3 with the marker after the Combine (null when it cannot be read).
    intersect_model: for an intersect of several tools, which shape the Combine made (`read_intersect.model`)."""
    found = {"volume_after": geo.target_volume(ctx)}
    if "intersect_volumes" in data:
        found["intersect_model"] = read_intersect.model(data["intersect_volumes"], found["volume_after"])
    return found


# type name -> (before, after); either may be None
READERS = {
    "ExtrudeFeature": (extrude_before, extrude_after),
    "RevolveFeature": (revolve_before, revolve_after),
    "HoleFeature": (hole_before, hole_after),
    "CombineFeature": (combine_before, combine_after),
}
