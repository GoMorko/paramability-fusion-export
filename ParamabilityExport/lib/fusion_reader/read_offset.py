"""Offset faces (press pull) as plain dicts (docs/capture-format.md).

Before the item: the faces it moves, each as a flat outline on its plane (the same record as a sketch profile, with
the outward normal as z) and whether its side walls stand square to it. After the item: the flat faces the feature
left, so the translator can check which way and how far the faces moved.

The moved faces come from `inputFaces` (a list in newer Fusion versions, a collection in older ones). When Fusion
gives none before the item, they are read after it from the faces the feature made, moved back by the distance.
"""
import math

from . import read_geometry as geo
from .param_refs import Params, with_params
from .read_finish import strict_items
from .read_sketch import _read_curve

SQUARE_TOL = 1e-6


class _FaceSpace:
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


def _dot(a, b):
    return sum(x * y for x, y in zip(a, b))


def _cross(a, b):
    return [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]


def _outward_normal(face):
    ok, normal = face.evaluator.getNormalAtPoint(face.pointOnFace)
    if not ok:
        raise ValueError("The normal of a face could not be read.")
    return geo.unit_vector(normal)


def _frame(face, plane):
    """The face plane as a frame: origin on the plane, z the outward normal, x along the plane's u direction."""
    z = _outward_normal(face)
    x = geo.unit_vector(plane.uDirection)
    y = _cross(z, x)
    return {"origin": geo.point(plane.origin), "x": x, "y": y, "z": z}


def _square_to(neighbour, normal):
    """True when a side face stands square to a face with this normal: a plane across it or a cylinder along it."""
    geometry = neighbour.geometry
    name = geo.type_name(geometry)
    if name == "Plane":
        return abs(_dot(geo.unit_vector(geometry.normal), normal)) <= SQUARE_TOL
    if name == "Cylinder":
        return math.sqrt(sum(c * c for c in _cross(geo.unit_vector(geometry.axis), normal))) <= SQUARE_TOL
    return False


def _face_record(face, inputs, ctx):
    """One moved face: { token, frame, space, loops, sides, meets_offset } or { kind: other, type } when not flat."""
    face = geo.native_input(face, ctx)
    plane = face.geometry
    if geo.type_name(plane) != "Plane":
        return geo.mark_foreign({"kind": "other", "type": geo.type_name(plane)}, face, ctx)
    frame = _frame(face, plane)
    space = _FaceSpace(frame)
    loops, square, meets = [], True, False
    for loop in strict_items(face.loops):
        edges = strict_items(loop.edges)
        loops.append({"outer": bool(loop.isOuter), "curves": [_read_curve(e.geometry, space) for e in edges]})
        for edge in edges:
            for neighbour in strict_items(edge.faces):
                if geo.same_entity(geo.native_input(neighbour, ctx), face):
                    continue
                if any(geo.same_entity(geo.native_input(neighbour, ctx), other) for other in inputs):
                    meets = True
                square = square and geo.safe(lambda: _square_to(neighbour, frame["z"]), False)
    record = {"token": geo.safe(lambda: face.entityToken, ""), "frame": frame, "space": "sketch", "loops": loops,
              "sides": "square" if square else "other", "meets_offset": meets}
    return geo.mark_foreign(record, face, ctx)


UNREADABLE = "The faces of this offset could not be read."


def _items(value):
    """Items of a Fusion collection (count and item(i)) or of a plain list; empty when neither."""
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return list(value)
    return geo.safe(lambda: strict_items(value), None) or []


def _input_faces(feature):
    """The faces the step moves, read before it: `inputFaces`, else `faces` (empty when Fusion gives none)."""
    for member in ("inputFaces", "faces"):
        found = _items(geo.safe(lambda: getattr(feature, member), None))
        if found:
            return found
    return []


def _moved_back(record, distance):
    """A face record read after the step, put back on the plane it was offset from."""
    if "frame" in record:
        frame = record["frame"]
        record["frame"] = dict(frame, origin=[round(o - distance * z, 9) + 0.0 for o, z in zip(frame["origin"], frame["z"])])
    return record


def offset_faces_before(feature, ctx):
    faces = _input_faces(feature)
    inputs = [geo.native_input(f, ctx) for f in faces]
    data = {"distance": geo.length(feature.distance), "faces": [_face_record(f, inputs, ctx) for f in faces],
            "faces_after": []}
    if not faces:
        data["faces_from_after"] = True
    return with_params(data, Params().add("distance", lambda: feature.distance).found)


def _made_faces(feature):
    return geo.collection_items(geo.safe(lambda: feature.faces, None))


def offset_faces_after(feature, ctx, data):
    """faces_after: { point, normal } of each flat face the feature lists once it is computed. When the faces could not
    be read before the item, `faces` holds the flat faces it made, moved back by the distance."""
    out = {}
    if data.pop("faces_from_after", False):
        made = [f for f in _made_faces(feature)
                if geo.safe(lambda: geo.type_name(f.geometry), None) == "Plane"]
        if not made:
            raise ValueError(UNREADABLE)
        inputs = [geo.native_input(f, ctx) for f in made]
        out["faces"] = [_moved_back(_face_record(f, inputs, ctx), data["distance"]) for f in made]
    found = []
    for face in _made_faces(feature):
        face = geo.native_input(face, ctx)
        if geo.safe(lambda: geo.type_name(face.geometry), None) != "Plane":
            continue
        point = geo.safe(lambda: geo.point(face.pointOnFace), None)
        normal = geo.safe(lambda: _outward_normal(face), None)
        if point is not None and normal is not None:
            found.append({"point": point, "normal": normal})
    out["faces_after"] = found
    return out


# type name -> (before, after); either may be None
READERS = {
    "OffsetFacesFeature": (offset_faces_before, offset_faces_after),
}
