"""A flat face of a body as an outline record (docs/capture-format.md, section 4).

The face's plane becomes the record's frame: z is the outward normal, x the plane's u direction. Its loops are the
face's edges as curves in that plane, read like sketch curves, in the target component's coordinates. `made_by` names
the earlier extrude whose start, end or side faces hold the face, read with the marker before the step that uses it.

`read_faces` reads such faces again for the size probe: the step that uses a face changes or removes it, so each face
is read with the timeline marker moved before its step, and the marker goes back after (or stays, for a caller that
brings it back itself).
"""
import math

from ..design_edit.marker import MARKER_LOST, put_back, read_marker
from ..timing.timer import span_on
from . import read_geometry as geo
from .read_finish import strict_items
from .read_sketch import read_curve

# Earlier extrudes looked at for the one that made a face, the latest first.
MAX_EARLIER_EXTRUDES = 200
_FACE_LISTS = (("start", "startFaces"), ("end", "endFaces"), ("side", "sideFaces"))
_NAMED_CURVES = ("Line3D", "Arc3D", "Circle3D", "Ellipse3D")


def _dot(a, b):
    return sum(x * y for x, y in zip(a, b))


def _cross(a, b):
    return [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]


class FaceSpace:
    """Maps model points (cm) into the 2D frame of a face (mm), like a sketch space."""

    def __init__(self, frame):
        self.frame = frame

    def xy(self, p):
        rel = [a - b for a, b in zip(geo.point(p), self.frame["origin"])]
        return [round(_dot(rel, self.frame["x"]), 6) + 0.0, round(_dot(rel, self.frame["y"]), 6) + 0.0]

    def direction(self, vector, at):
        v = geo.unit_vector(vector)
        dx, dy = _dot(v, self.frame["x"]), _dot(v, self.frame["y"])
        n = math.hypot(dx, dy) or 1.0
        return [round(dx / n, 9) + 0.0, round(dy / n, 9) + 0.0]


def face_frame(face, plane):
    """The face plane as a frame: origin on the plane, z the outward normal, x along the plane's u direction."""
    z = geo.outward_normal(face)
    x = geo.unit_vector(plane.uDirection)
    y = _cross(z, x)
    return {"origin": geo.point(plane.origin), "x": x, "y": y, "z": z}


class _EdgeCurve:
    """A free edge curve evaluated over the edge's own parameter range (`BRepEdge.evaluator`), since the curve
    Fusion gives for the edge may run past the edge."""

    def __init__(self, edge, geometry):
        self.objectType = geometry.objectType
        self.evaluator = edge.evaluator
        self.controlPointCount = geo.safe(lambda: geometry.controlPointCount, None)
        self.degree = geo.safe(lambda: geometry.degree, None)


def edge_curve(edge, space):
    """One edge as a capture curve in the face's 2D frame."""
    geometry = edge.geometry
    if geo.type_name(geometry) in _NAMED_CURVES:
        return read_curve(geometry, space)
    return read_curve(_EdgeCurve(edge, geometry), space)


def _loops(face, space):
    return [{"outer": bool(loop.isOuter), "curves": [edge_curve(e, space) for e in strict_items(loop.edges)]}
            for loop in strict_items(face.loops)]


def _same_face(a, b, token):
    if geo.same_entity(a, b):
        return True
    return bool(token) and geo.safe(lambda: a.entityToken, None) == token


def made_by(face, ctx, before):
    """{ index, name, which } of the latest extrude before timeline index `before` that lists the face among its
    start, end or side faces; None when no such extrude is found or the timeline cannot be read."""
    component = geo.component_of(face) or (ctx.component if ctx is not None else None)
    extrudes = geo.collection_items(geo.safe(lambda: component.features.extrudeFeatures, None))
    earlier = []
    for extrude in extrudes:
        index = geo.safe(lambda: extrude.timelineObject.index, None)
        if isinstance(index, int) and index < before:
            earlier.append((index, extrude))
    earlier.sort(key=lambda pair: pair[0], reverse=True)
    token = geo.safe(lambda: face.entityToken, "")
    for index, extrude in earlier[:MAX_EARLIER_EXTRUDES]:
        for which, member in _FACE_LISTS:
            faces = geo.collection_items(geo.safe(lambda: getattr(extrude, member), None))
            if any(_same_face(geo.native_input(f, ctx), face, token) for f in faces):
                return {"index": index, "name": geo.safe(lambda: extrude.name, "") or "", "which": which}
    return None


def face_loops(face, ctx=None):
    """{ frame, loops } of a flat BRepFace as `face_outline` gives them, or None when it is not flat or does not
    read."""
    with span_on(ctx, "faces"):
        return _face_loops(face, ctx)


def _face_loops(face, ctx):
    face = geo.native_input(face, ctx)
    if geo.safe(lambda: geo.surface_kind(face), None) != "Plane":
        return None
    frame = geo.safe(lambda: face_frame(face, face.geometry), None)
    loops = geo.safe(lambda: _loops(face, FaceSpace(frame)), None) if frame is not None else None
    return {"frame": frame, "loops": loops} if loops else None


FACE_NOT_FOUND = "The face was not found before its step."
NO_MARKER = "The timeline marker could not be moved before the step."
NOT_BACK = "The timeline marker did not go back after the face was read."


def read_faces(design, ctx, wanted, stay=False):
    """`(found, unread)` for `wanted` ({ key: { token, before } }): `found` maps a key to the face's `face_loops` read
    with the timeline marker at `before` (the step that uses it not built yet, as when it was captured), `unread` a key
    to why it was left out. A position after the marker now is not read. The marker goes back to where it was, which
    rebuilds the steps after the earliest position read; when it does not, no face counts and `unread` also holds
    `MARKER_LOST`, so the caller stops reading. With `stay` the marker is left at the last position read: the caller
    moves it back after its next parameter change, so the later steps are rebuilt once instead of twice, and checks
    that it went back. Never raises."""
    found, unread = {}, {}
    timeline = geo.safe(lambda: design.timeline, None)
    home = read_marker(timeline) if timeline is not None else None
    groups = {}
    for key, hint in wanted.items():
        before = hint.get("before") if isinstance(hint, dict) else None
        if home is None or not isinstance(before, int) or not 0 < before <= min(home["position"], home["count"]):
            unread[key] = NO_MARKER
        else:
            groups.setdefault(before, []).append((key, hint.get("token") or ""))
    if not groups:
        return found, unread
    back = True
    try:
        for before in sorted(groups):
            if not put_back(timeline, before):
                unread.update((key, NO_MARKER) for key, _ in groups[before])
                continue
            for key, token in groups[before]:
                face = geo.find_native(design, token) if token else None
                record = geo.safe(lambda: face_loops(face, ctx), None) if face is not None else None
                if record is None:
                    unread[key] = FACE_NOT_FOUND
                else:
                    found[key] = record
    finally:
        if not stay:
            back = put_back(timeline, home)
    if not back:
        return {}, dict({key: NOT_BACK for key in wanted}, **{MARKER_LOST: NOT_BACK})
    return found, unread


def face_outline(face, ctx=None, before=None):
    with span_on(ctx, "faces"):
        return _face_outline(face, ctx, before)


def _face_outline(face, ctx, before):
    """(record, area) of a BRepFace used as an outline. A flat face gives { face, type, surface, token, frame, space,
    loops, face_point, body, made_by }; a curved one only { face, type, surface }; a face whose surface, plane or
    edges cannot be read adds `problem: "unread"` instead of the frame and loops (`surface` null when unknown).
    `area` is the face area in mm2 or None. `before` is the timeline index of the step that uses the face (no
    `made_by` without it)."""
    face = geo.native_input(face, ctx)
    record = {"face": True, "type": "BRepFace", "surface": geo.safe(lambda: geo.surface_kind(face), None)}
    geo.mark_foreign(record, face, ctx)
    if record["surface"] not in ("Plane", None):
        return record, None
    frame = geo.safe(lambda: face_frame(face, face.geometry), None) if record["surface"] else None
    loops = geo.safe(lambda: _loops(face, FaceSpace(frame)), None) if frame is not None else None
    if not loops:
        record["problem"] = "unread"
        return record, None
    record.update(frame=frame, space="sketch", loops=loops)
    token = geo.safe(lambda: face.entityToken, "")
    if token:
        record["token"] = token
    point = geo.safe(lambda: geo.point(face.pointOnFace), None)
    if point is not None:
        record["face_point"] = point
    body = geo.owner_body(face, ctx)
    if body:
        record["body"] = body
    if isinstance(before, int):
        maker = geo.safe(lambda: made_by(face, ctx, before), None)
        if maker:
            record["made_by"] = maker
    return record, geo.safe(lambda: round(face.area * 100.0, 6) + 0.0, None)
