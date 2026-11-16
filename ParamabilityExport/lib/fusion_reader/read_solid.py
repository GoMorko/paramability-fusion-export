"""Extrude, revolve and combine features as plain dicts (docs/capture-format.md).

Each feature type has a pair of readers. `before(feature, ctx)` runs with the timeline marker just before the item
and reads the inputs. `after(feature, ctx, data)` runs with the marker just after it and reads what the feature
produced (the measured values that check signs and flags). Both return dicts that go into the item's data.
A member that is missing or retired never stops the walk and never becomes a plausible value: it reads as None or as
an `other` entry (which the translator refuses), or the reader raises and the item gets a `read_error`. Only members
that feed a note, such as the participant bodies, fall back to an empty list.
"""
from ..geometry import vec
from . import read_geometry as geo
from . import read_extent, read_face_rays, read_intersect
from .param_refs import Params, with_params
from .placement import from_assembly
from .read_bodies import tool_ref
from .read_sketch import first_profile, profile_area, read_outlines, read_profiles

_OPERATIONS = [
    ("newcomponent", "newComponent"),
    ("newbody", "newBody"),
    ("join", "join"),
    ("cut", "cut"),
    ("intersect", "intersect"),
]
_EXTENT_TYPES = [("twosides", "two"), ("symmetric", "symmetric"), ("oneside", "one")]
_WALL_LOCATIONS = [("side1", "side1"), ("side2", "side2"), ("center", "center")]

_FULL_TURN_DEG = 360.0 - 1e-6


def operation_of(value):
    return geo.pick_by_text(geo.enum_name(value, "FeatureOperations"), _OPERATIONS, "other")


def _taper(feature, member):
    return geo.safe(lambda: geo.angle(getattr(feature, member)), None)


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
        found.add("side_one.distance", lambda: read_extent.extent_distance(feature.extentOne))
        found.add("side_one.taper_deg", lambda: feature.taperAngleOne, "angle")
        found.add("side_one.offset", lambda: feature.extentOne.offset)
        if extent_type == "two":
            found.add("side_two.distance", lambda: read_extent.extent_distance(feature.extentTwo))
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
            side = geo.safe(lambda: read_extent.extent(feature.extentOne, taper, ctx, "side_one"), None)
            if side and side.get("kind") in ("throughAll", "all"):
                side_one = side
    else:
        side_one = read_extent.extent(feature.extentOne, _taper(feature, "taperAngleOne"), ctx, "side_one")
        if extent_type == "two":
            side_two = read_extent.extent(feature.extentTwo, _taper(feature, "taperAngleTwo"), ctx, "side_two")
    operation = operation_of(feature.operation)
    profiles, areas = read_outlines(feature.profile, ctx, before=geo.safe(lambda: feature.timelineObject.index, None))
    if extent_type == "one":
        read_face_rays.mark_side(side_one, geo.native_input(geo.safe(lambda: feature.extentOne.entity, None), ctx),
                                 profiles)
    data = {
        "operation": operation,
        "profiles": profiles,
        "start": geo.safe(lambda: read_extent.start(feature, ctx), {"kind": "other", "type": "unreadable"}),
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


def _face_normal(face):
    """The unit normal of a face at `pointOnFace` (`SurfaceEvaluator.getNormalAtPoint`), or None when it cannot be
    read."""
    found = geo.safe(lambda: face.evaluator.getNormalAtPoint(face.pointOnFace), None)
    if not isinstance(found, (tuple, list)) or len(found) != 2 or not found[0] or found[1] is None:
        return None
    return geo.safe(lambda: geo.unit_vector(found[1]), None)


def _end_face(faces, z):
    """The face of `endFaces` to measure, with its normal: the first one whose normal is parallel to the sketch
    normal `z` (an end cap), else the first one. Fusion can list a face that is not a cap first, such as a wall a cut
    made where it went through a rib."""
    normals = [_face_normal(face) for face in faces[:MAX_SIDE_FACES]]
    for face, normal in zip(faces, normals):
        if normal is not None and z is not None and abs(abs(vec.dot(normal, z)) - 1.0) <= _PARALLEL_TOL:
            return face, normal
    return faces[0], normals[0] if normals else None


# A face normal this close to the sketch normal (1 - |cos|) is parallel to it.
_PARALLEL_TOL = 1e-6


def _start_offset(feature, z, origin):
    """Signed distance along the sketch normal `z` from the sketch plane through `origin` to the first face of
    `startFaces` that is parallel to the sketch plane, or None when there is none or it cannot be read."""
    faces = geo.collection_items(geo.safe(lambda: feature.startFaces, None))
    if not faces:
        return None
    face, normal = _end_face(faces, z)
    if normal is None or abs(abs(vec.dot(normal, z)) - 1.0) > _PARALLEL_TOL:
        return None
    p = geo.safe(lambda: geo.point(face.pointOnFace), None)
    return None if p is None else round(vec.dot(vec.sub(p, origin), z), 6) + 0.0


def extrude_after(feature, ctx, data):
    """end_offset: signed distance from the first profile's sketch plane to a point on the end face (`_end_face`: the
    first face of `endFaces` parallel to the sketch plane, else the first one). start_offset, for an extrude that
    starts from a face or plane: the same distance to the start face (`_start_offset`), null when none was measured.

    end_area: the area of that face in mm2 (with profile_area, it shows which way a taper goes), and end_normal its
    unit normal at that point (null when it cannot be read). side_leans: how far each side face leans along the first
    profile's sketch normal (the taper check for several outlines). volume_after: for an extrude of text or spline
    outlines, the volume that was measured before the item is compared with (the target's, or the new bodies' summed
    for a new body).
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
        if (data.get("start") or {}).get("kind") == "fromEntity":
            out["start_offset"] = geo.safe(lambda: _start_offset(feature, vec.unit(frame["z"]), frame["origin"]), None)
    if not faces:
        return out
    face, normal = _end_face(faces, vec.unit(frame["z"]) if frame is not None else None)
    out["end_area"] = geo.safe(lambda: round(face.area * 100.0, 6) + 0.0, None)
    out["end_normal"] = normal
    if frame is None:
        return out
    p = geo.safe(lambda: geo.point(face.pointOnFace), None)
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
                    **read_extent.construction_token(entity))
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
    """`axis_record` of a revolve's axis with what it is (`read_reference.axis_with_reference`), so the translators
    can tell which sizes may move it. One that cannot be read is `{ kind: "other" }` with the entity `type` and the
    `error`, so the reason can say what the axis is."""
    from .read_reference import axis_with_reference  # read_reference imports this module

    entity = geo.safe(lambda: feature.axis, None)
    if entity is None:
        return {"kind": "other", "type": "none", "error": "Fusion gave no axis"}
    try:
        return axis_with_reference(entity, ctx)
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
    }, Params().add("extent.angle_deg", lambda: feature.extentDefinition.angle, "angle")
       .add("extent.angle_one_deg", lambda: feature.extentDefinition.angleOne, "angle")
       .add("extent.angle_two_deg", lambda: feature.extentDefinition.angleTwo, "angle").found)


def _cap_normal(faces):
    """The outward normal of the first of `faces` at a point on it, or None."""
    def normal():
        face = faces[0]
        ok, n = face.evaluator.getNormalAtPoint(face.pointOnFace)
        return geo.unit_vector(n) if ok else None

    return geo.safe(normal, None) if faces else None


def _faces_box(faces):
    """{ min, max } in mm around the boxes of `faces`, or None when one cannot be read."""
    boxes = [geo.safe(lambda: geo.box_of(face), None) for face in faces]
    if not boxes or any(box is None for box in boxes):
        return None
    return {"min": [min(box["min"][i] for box in boxes) for i in range(3)],
            "max": [max(box["max"][i] for box in boxes) for i in range(3)]}


def revolve_after(feature, ctx, data):
    """The measured caps of a revolve that is not a full turn: `start_face_normal` and `end_face_normal`, the outward
    normals of the first start and end face (null when Fusion gives none, as when a join merged the cap into a face
    of the part), and `made_box`, the box around the faces the revolve made."""
    extent = data.get("extent") or {}
    if extent.get("kind") == "angle" and extent.get("angle_deg", 0) >= _FULL_TURN_DEG:
        return {}
    def faces(name):
        return [geo.native_input(f, ctx) for f in geo.collection_items(geo.safe(lambda: getattr(feature, name), None))]

    return {"start_face_normal": _cap_normal(faces("startFaces")), "end_face_normal": _cap_normal(faces("endFaces")),
            "made_box": _faces_box(faces("faces"))}


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
    "CombineFeature": (combine_before, combine_after),
}
