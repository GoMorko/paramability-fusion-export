"""Thread features (adsk.fusion.ThreadFeature) and the thread of a tapped hole as plain dicts (docs/capture-format.md).

A modeled thread is read as the numbers of its `ThreadInfo` (profile name, pitch, major and minor diameter, hand,
angle) and as the faces it sits on: for each input face its cylinder, the axial span between its end vertices, a point
on it and which way it faces. A cosmetic thread is only `{ "modeled": false }`. Every member is read on its own: one
that cannot be read becomes null, and the translator then leaves the thread out instead of guessing.
"""
from . import read_geometry as geo
from .param_refs import Params

MAX_FACES = 16


def _text(value):
    return value if isinstance(value, str) and value else None


def _bool(value):
    return value if isinstance(value, bool) else None


def thread_info(*sources):
    """The `ThreadInfo` numbers of the first source that gives each member. A source is a thread feature, a hole, or
    the thread object of either; the values come in Fusion's units and leave in mm and degrees."""
    def read(name):
        for source in sources:
            value = geo.safe(lambda: getattr(source, name), None)
            if value is not None:
                return value
        return None

    def length(name):
        return geo.safe(lambda: geo.length(read(name)), None)

    angle = read("threadAngle")
    return {
        "thread_type": _text(read("threadType")),
        "designation": _text(read("threadDesignation")),
        "thread_class": _text(read("threadClass")),
        "internal": _bool(read("isInternal")),
        "right_hand": _bool(read("isRightHanded")),
        "pitch": length("pitch"),
        "major_diameter": length("majorDiameter"),
        "minor_diameter": length("minorDiameter"),
        "angle_deg": None if angle is None else geo.safe(lambda: geo.angle(angle), None),
    }


def _face_vertices(face):
    return [geo.point(v.geometry) for v in geo.collection_items(face.vertices)]


def _span(origin, axis, points):
    """[low, high] of the points along the axis from the origin, or None when there are none."""
    along = [sum((p[i] - origin[i]) * axis[i] for i in range(3)) for p in points]
    return [round(min(along), 6) + 0.0, round(max(along), 6) + 0.0] if along else None


def _face_record(face, ctx):
    """One input face: its surface, and for a cylinder its axis, radius, the span of its end vertices along the axis,
    a point on it and whether it faces away from the axis (`outward`)."""
    face = geo.native_input(face, ctx)
    record = {"surface": geo.safe(lambda: geo.surface_kind(face), None),
              "face_point": geo.safe(lambda: geo.point(face.pointOnFace), None)}
    if record["surface"] == "Cylinder":
        geometry = face.geometry
        origin = geo.safe(lambda: geo.point(geometry.origin), None)
        axis = geo.safe(lambda: geo.unit_vector(geometry.axis), None)
        record.update(origin=origin, axis=axis, radius=geo.safe(lambda: geo.length(geometry.radius), None))
        if origin and axis:
            record["span"] = geo.safe(lambda: _span(origin, axis, _face_vertices(face)), None)
            normal = geo.safe(lambda: geo.outward_normal(face), None)
            if normal and record["face_point"]:
                radial = [record["face_point"][i] - origin[i] for i in range(3)]
                along = sum(radial[i] * axis[i] for i in range(3))
                radial = [radial[i] - along * axis[i] for i in range(3)]
                record["outward"] = sum(radial[i] * normal[i] for i in range(3)) > 0
    return geo.mark_foreign(record, face, ctx)


def thread_before(feature, ctx):
    modeled = geo.safe(lambda: bool(feature.isModeled), True)
    if not modeled:
        return {"modeled": False}
    info = geo.safe(lambda: feature.threadInfo, None)
    data = {"modeled": True}
    data.update(thread_info(info, feature))
    data["full_length"] = _bool(geo.safe(lambda: feature.isFullLength, None))
    data["length"] = geo.safe(lambda: geo.length(feature.threadLength), None)
    data["offset"] = geo.safe(lambda: geo.length(feature.threadOffset), None)
    faces = geo.collection_items(geo.safe(lambda: feature.inputFaces, None))[:MAX_FACES]
    data["faces"] = [_face_record(f, ctx) for f in faces]
    found = Params()
    found.add("length", lambda: feature.threadLength)
    found.add("offset", lambda: feature.threadOffset)
    if found.found:
        data["params"] = found.found
    return data


def thread_after(feature, ctx, data):
    """`made_span`: the axial span of the faces the thread made, along the axis of the first input face. A partial
    thread starts at the end of the cylinder its span touches."""
    faces = data.get("faces") or []
    first = faces[0] if faces else {}
    if not (first.get("origin") and first.get("axis")) or not data.get("modeled"):
        return {}
    points = []
    for face in geo.collection_items(geo.safe(lambda: feature.faces, None)):
        points += geo.safe(lambda: _face_vertices(face), [])
    return {"made_span": geo.safe(lambda: _span(first["origin"], first["axis"], points), None)}


READERS = {"ThreadFeature": (thread_before, thread_after)}
