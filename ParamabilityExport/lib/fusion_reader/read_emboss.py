"""Emboss features (adsk.fusion.EmbossFeature) as plain dicts (docs/capture-format.md).

Before the item: the outlines it raises or sinks (sketch profiles, the outlines of sketch text, flat faces), the
faces they land on (a lone face with its edges as `outline`), the depth and the shift and turn of the outline, and the size of the part. After the item: the
size of the part again and where the feature put its farthest face parallel to the input face. For Tangent Chain it
also reads the faces that touch the input faces tangentially and the surface kinds of the faces the feature made. The
translator checks the two against each other.

`EmbossFeature` is marked as preview in the API reference. Each setting is read on its
own: one that cannot be read becomes null, and the translator then refuses the step.
"""
from ..geometry import vec
from . import read_geometry as geo
from .param_refs import Params, with_params
from .read_face import face_outline
from .read_finish import strict_items
from .read_sketch import read_outlines

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


def _face_records(faces, ctx, index):
    """The input face records. A lone face also carries `outline`, its edges as an outline record (read_face.py), for
    an emboss whose outline reaches past it; left out when the edges cannot be read."""
    records = [_face_record(f, ctx) for f in faces]
    if len(faces) == 1:
        outline = geo.safe(lambda: face_outline(faces[0], ctx, index)[0], None)
        if isinstance(outline, dict) and "loops" in outline:
            records[0]["outline"] = outline
    return records


def _input_faces(feature):
    """The faces the outline lands on: `inputFaces` as a list, a collection or a vector. An unreadable list raises."""
    return strict_items(feature.inputFaces)[:MAX_FACES]


def _surface_record(face):
    """Surface kind and plane of a face next to an input face; a member that cannot be read is null."""
    return {"surface": geo.safe(lambda: geo.surface_kind(face), None),
            "plane": geo.safe(lambda: geo.plane_of(face), None)}


def _tangent_faces(faces, ctx):
    """The faces that touch the input faces tangentially, as { surface, plane }; null when they cannot be listed."""
    def read():
        found = []
        for face in faces:
            raw = geo.native_input(face, ctx).tangentiallyConnectedFaces
            found.extend(_surface_record(n) for n in strict_items(raw)[:MAX_FACES])
        return found
    return geo.safe(read, None)


def _participants(faces, ctx):
    """The bodies of the input faces, once each."""
    found = {}
    for face in faces:
        ref = geo.safe(lambda: geo.body_ref(geo.native_input(face, ctx).body, ctx), None)
        if ref is not None:
            found.setdefault(ref["token"] or ref["name"], ref)
    return list(found.values())


def _length(read):
    return geo.safe(lambda: geo.length(read()), None)


def emboss_before(feature, ctx):
    faces = _input_faces(feature)
    params = Params()
    params.add("depth", lambda: feature.depth)
    params.add("offset_x", lambda: feature.horizontalDistance)
    params.add("offset_y", lambda: feature.verticalDistance)
    params.add("rotation_deg", lambda: feature.rotationAngle, "angle")
    index = geo.safe(lambda: feature.timelineObject.index, None)
    profiles, areas = read_outlines(feature.profiles, ctx, before=index)
    return with_params({
        "profiles": profiles,
        "areas": areas,
        "faces": _face_records(faces, ctx, index),
        "tangent_chain": geo.safe(lambda: bool(feature.isTangentChain), None),
        "tangent_faces": _tangent_faces(faces, ctx),
        "made_surfaces": None,
        "depth": _length(lambda: feature.depth),
        "offset_x": _length(lambda: feature.horizontalDistance),
        "offset_y": _length(lambda: feature.verticalDistance),
        "rotation_deg": geo.safe(lambda: geo.angle(feature.rotationAngle), None),
        "participants": _participants(faces, ctx),
        "target_box_before": ctx.target_box(),
        "volume_before": geo.target_volume(ctx),
        "volume_after": None,
        "end_offset": None,
        "end_area": None,
    }, params.found)


def _parallel_faces(feature, normal):
    """The flat faces the feature made whose normal is parallel to `normal`."""
    found = []
    for face in geo.collection_items(geo.safe(lambda: feature.faces, None)):
        if geo.safe(lambda: geo.surface_kind(face), None) != "Plane":
            continue
        outward = geo.safe(lambda: geo.outward_normal(face), None)
        if outward is not None and abs(abs(vec.dot(outward, normal)) - 1.0) <= 1e-6:
            found.append(face)
    return found


def _made_surfaces(feature):
    """Surface kind of every face the feature made; null when the faces cannot be listed."""
    faces = geo.safe(lambda: strict_items(feature.faces)[:MAX_FACES], None)
    if faces is None:
        return None
    return [geo.safe(lambda: geo.surface_kind(f), None) for f in faces]


def emboss_after(feature, ctx, data):
    """volume_after, and for the farthest made face parallel to the input face: end_offset, its signed distance along
    the first outline's sketch normal from the sketch plane, and end_area, its area in mm2."""
    out = {"volume_after": geo.target_volume(ctx), "made_surfaces": _made_surfaces(feature)}
    frame = next((p["frame"] for p in data.get("profiles") or [] if isinstance(p.get("frame"), dict)), None)
    faces = data.get("faces") or []
    normal = faces[0].get("outward") if faces and isinstance(faces[0], dict) else None
    if frame is None or normal is None:
        return out
    measured = []
    for face in _parallel_faces(feature, normal):
        point = geo.safe(lambda: geo.point(face.pointOnFace), None)
        if point is not None:
            offset = vec.dot([a - b for a, b in zip(point, frame["origin"])], frame["z"])
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
