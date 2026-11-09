"""Emboss features (adsk.fusion.EmbossFeature) as plain dicts (docs/capture-format.md).

Before the item: the outlines it raises or sinks (sketch profiles, or a text marker), the faces they land on, the
depth and the shift and turn of the outline, and the size of the part. After the item: the size of the part again and
where the feature put its farthest face parallel to the input face. The translator checks the two against each other.

`EmbossFeature` is a recent addition to Fusion and marked as preview in the API reference. Each setting is read on its
own: one that cannot be read becomes null, and the translator then refuses the step.
"""
from . import read_geometry as geo
from .param_refs import Params, with_params
from .read_finish import strict_items
from .read_sketch import profile_areas, read_profiles

MAX_FACES = 256


def _face_record(face, ctx):
    """One input face: { entity_type, surface, plane, outward, face_point }; a member that cannot be read is null."""
    face = geo.native_input(face, ctx)
    record = {
        "entity_type": "BRepFace",
        "surface": geo.safe(lambda: geo.surface_kind(face), None),
        "plane": geo.safe(lambda: geo.plane_of(face), None),
        "outward": geo.safe(lambda: geo.outward_normal(face), None),
        "face_point": geo.safe(lambda: geo.point(face.pointOnFace), None),
    }
    return geo.mark_foreign(record, face, ctx)


def _input_faces(feature):
    """The faces the outline lands on: `inputFaces` as a list or as a collection. An unreadable list raises."""
    raw = feature.inputFaces
    faces = list(raw) if isinstance(raw, (list, tuple)) else strict_items(raw)
    return faces[:MAX_FACES]


def _participants(faces, ctx):
    """The bodies of the input faces, once each."""
    found = {}
    for face in faces:
        ref = geo.safe(lambda: geo.body_ref(geo.native_input(face, ctx).body, ctx), None)
        if ref is not None:
            found.setdefault(ref["token"] or ref["name"], ref)
    return list(found.values())


def _volume(ctx):
    """Volume of the target body in mm3 at the current marker position, or None."""
    body = ctx.find_target()
    return geo.safe(lambda: round(body.volume * 1000.0, 6) + 0.0, None) if body is not None else None


def _length(read):
    return geo.safe(lambda: geo.length(read()), None)


def emboss_before(feature, ctx):
    faces = _input_faces(feature)
    params = Params()
    params.add("depth", lambda: feature.depth)
    params.add("offset_x", lambda: feature.horizontalDistance)
    params.add("offset_y", lambda: feature.verticalDistance)
    params.add("rotation_deg", lambda: feature.rotationAngle, "angle")
    return with_params({
        "profiles": read_profiles(feature.profiles, ctx),
        "areas": profile_areas(feature.profiles),
        "faces": [_face_record(f, ctx) for f in faces],
        "tangent_chain": geo.safe(lambda: bool(feature.isTangentChain), None),
        "depth": _length(lambda: feature.depth),
        "offset_x": _length(lambda: feature.horizontalDistance),
        "offset_y": _length(lambda: feature.verticalDistance),
        "rotation_deg": geo.safe(lambda: geo.angle(feature.rotationAngle), None),
        "participants": _participants(faces, ctx),
        "target_box_before": ctx.target_box(),
        "volume_before": _volume(ctx),
        "volume_after": None,
        "end_offset": None,
        "end_area": None,
    }, params.found)


def _dot(a, b):
    return sum(x * y for x, y in zip(a, b))


def _parallel_faces(feature, normal):
    """The flat faces the feature made whose normal is parallel to `normal`."""
    found = []
    for face in geo.collection_items(geo.safe(lambda: feature.faces, None)):
        if geo.safe(lambda: geo.surface_kind(face), None) != "Plane":
            continue
        outward = geo.safe(lambda: geo.outward_normal(face), None)
        if outward is not None and abs(abs(_dot(outward, normal)) - 1.0) <= 1e-6:
            found.append(face)
    return found


def emboss_after(feature, ctx, data):
    """volume_after, and for the farthest made face parallel to the input face: end_offset, its signed distance along
    the first outline's sketch normal from the sketch plane, and end_area, its area in mm2."""
    out = {"volume_after": _volume(ctx)}
    frame = next((p["frame"] for p in data.get("profiles") or [] if isinstance(p.get("frame"), dict)), None)
    faces = data.get("faces") or []
    normal = faces[0].get("outward") if faces and isinstance(faces[0], dict) else None
    if frame is None or normal is None:
        return out
    measured = []
    for face in _parallel_faces(feature, normal):
        point = geo.safe(lambda: geo.point(face.pointOnFace), None)
        if point is not None:
            offset = _dot([a - b for a, b in zip(point, frame["origin"])], frame["z"])
            measured.append((offset, face))
    if measured:
        offset, face = max(measured, key=lambda found: abs(found[0]))
        out["end_offset"] = round(offset, 6) + 0.0
        out["end_area"] = geo.safe(lambda: round(face.area * 100.0, 6) + 0.0, None)
    return out


# type name -> (before, after); either may be None
READERS = {
    "EmbossFeature": (emboss_before, emboss_after),
}
