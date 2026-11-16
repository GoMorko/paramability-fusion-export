"""Offset faces (press pull) as plain dicts (docs/capture-format.md).

Before the item: the faces it moves. A flat face is an outline on its plane (the same record as a sketch profile,
with the outward normal as z) and whether its side walls stand square to it. A round face (a cylinder) is its axis,
its radius, whether it faces away from the axis, and each of its edge loops: a loop of one circle edge gives the
circle and the face across that edge, with the outline of that face when it is flat. After the item: the flat faces
and the cylinders the feature left, so the translator can check which way and how far the faces moved.

The moved faces come from `inputFaces` (a list in newer Fusion versions, a collection in older ones). When Fusion
gives none before the item, they are read after it from the faces the feature made, moved back by the distance.
"""
import math

from ..geometry import vec
from . import read_geometry as geo
from .param_refs import Params, with_params
from .read_face import FaceSpace, face_frame
from .read_finish import strict_items
from .read_sketch import read_curve

SQUARE_TOL = 1e-6


def _square_to(neighbour, normal):
    """True when a side face stands square to a face with this normal: a plane across it or a cylinder along it."""
    geometry = neighbour.geometry
    name = geo.type_name(geometry)
    if name == "Plane":
        return abs(vec.dot(geo.unit_vector(geometry.normal), normal)) <= SQUARE_TOL
    if name == "Cylinder":
        return math.sqrt(sum(c * c for c in vec.cross(geo.unit_vector(geometry.axis), normal))) <= SQUARE_TOL
    return False


def _neighbours(face, edge, ctx):
    """The faces across `edge` from `face`."""
    return [n for n in strict_items(edge.faces) if not geo.same_entity(geo.native_input(n, ctx), face)]


def _edges(face):
    return [edge for loop in strict_items(face.loops) for edge in strict_items(loop.edges)]


def _meets(face, inputs, ctx):
    """True when a face next to `face` is moved by the same step."""
    return any(geo.same_entity(geo.native_input(n, ctx), other)
               for edge in _edges(face) for n in _neighbours(face, edge, ctx) for other in inputs)


def _outline(face, plane):
    """{ frame, space, loops } of a flat face: its loops in its own plane, z the outward normal."""
    frame = face_frame(face, plane)
    space = FaceSpace(frame)
    loops = [{"outer": bool(loop.isOuter), "curves": [read_curve(e.geometry, space) for e in strict_items(loop.edges)]}
             for loop in strict_items(face.loops)]
    return {"frame": frame, "space": "sketch", "loops": loops}


def _end(edge, face, ctx):
    """One end of a round face: { kind: circle, center, normal, radius, face } for a circle edge, where `face` is the
    face across it (its outline when flat, { kind: other, type } else, null when not one face); else
    { kind: other, type }."""
    circle = edge.geometry
    if geo.type_name(circle) != "Circle3D":
        return {"kind": "other", "type": geo.type_name(circle)}
    record = {"kind": "circle", "center": geo.point(circle.center), "normal": geo.unit_vector(circle.normal),
              "radius": geo.length(circle.radius), "face": None}
    across = _neighbours(face, edge, ctx)
    if len(across) == 1:
        other = geo.native_input(across[0], ctx)
        plane = other.geometry
        record["face"] = (_outline(other, plane) if geo.type_name(plane) == "Plane"
                          else {"kind": "other", "type": geo.type_name(plane)})
    return record


def _ends(face, ctx):
    """One entry per edge loop of a round face: its end (`_end`) for a loop of one edge, else { kind: other }. An entry
    that cannot be read is null."""
    out = []
    for loop in strict_items(face.loops):
        edges = strict_items(loop.edges)
        if len(edges) != 1:
            out.append({"kind": "other", "type": "edges"})
            continue
        out.append(geo.safe(lambda: _end(edges[0], face, ctx), None))
    return out


def _outward(point, origin, axis, normal):
    """True when the normal at a point of a cylinder points away from its axis (a pin or a boss), False when it points
    towards it (a bore)."""
    radial = vec.sub(point, origin)
    radial = vec.sub(radial, vec.scale(axis, vec.dot(radial, axis)))
    return vec.dot(radial, normal) > 0


def _round_record(face, inputs, ctx):
    """{ kind: round, token, origin, axis, radius, point, outward, ends, meets_offset } of a cylinder face; raises
    when its axis, radius or a point on it cannot be read."""
    cylinder = face.geometry
    origin, axis = geo.point(cylinder.origin), geo.unit_vector(cylinder.axis)
    point = geo.point(face.pointOnFace)
    outward = geo.safe(lambda: _outward(point, origin, axis, geo.outward_normal(face)), None)
    return {"kind": "round", "token": geo.safe(lambda: face.entityToken, ""), "origin": origin, "axis": axis,
            "radius": geo.length(cylinder.radius), "point": point, "outward": outward, "ends": _ends(face, ctx),
            "meets_offset": _meets(face, inputs, ctx)}


def _unread_round(face):
    """A round face whose geometry could not be read: the translator leaves its step out."""
    return {"kind": "round", "token": geo.safe(lambda: face.entityToken, "")}


def _face_record(face, inputs, ctx):
    """One moved face: { token, frame, space, loops, sides, meets_offset } when flat, a round record for a cylinder
    (`_round_record`), or { kind: other, type } for another surface."""
    face = geo.native_input(face, ctx)
    plane = face.geometry
    name = geo.type_name(plane)
    if name == "Cylinder":
        record = geo.safe(lambda: _round_record(face, inputs, ctx), None) or _unread_round(face)
        return geo.mark_foreign(record, face, ctx)
    if name != "Plane":
        return geo.mark_foreign({"kind": "other", "type": name}, face, ctx)
    record = dict({"token": geo.safe(lambda: face.entityToken, "")}, **_outline(face, plane))
    square = True
    for edge in _edges(face):
        for neighbour in _neighbours(face, edge, ctx):
            square = square and geo.safe(lambda: _square_to(neighbour, record["frame"]["z"]), False)
    record.update(sides="square" if square else "other", meets_offset=_meets(face, inputs, ctx))
    return geo.mark_foreign(record, face, ctx)


UNREADABLE = "The faces of this offset could not be read."


def _items(value):
    """Items of a Fusion collection or vector, or of a plain list; empty when none of these."""
    return geo.collection_items(value)


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


def _surface(face):
    return geo.safe(lambda: geo.type_name(face.geometry), None)


def _cylinder(face):
    """{ origin, axis, radius } of a cylinder face, or None when it cannot be read."""
    def read():
        cylinder = face.geometry
        return {"origin": geo.point(cylinder.origin), "axis": geo.unit_vector(cylinder.axis),
                "radius": geo.length(cylinder.radius)}
    return geo.safe(read, None)


def offset_faces_after(feature, ctx, data):
    """faces_after: { point, normal } of each flat face the feature lists once it is computed; rounds_after: the
    `_cylinder` of each cylinder face. When the faces could not be read before the item, `faces` holds the faces it
    made: the flat ones moved back by the distance, a cylinder as a round face without geometry (`_unread_round`) and
    any other as { kind: other, type }, so the step is not copied without them."""
    out = {}
    made = [geo.native_input(f, ctx) for f in _made_faces(feature)]
    if data.pop("faces_from_after", False):
        if not made:
            raise ValueError(UNREADABLE)
        out["faces"] = [_moved_back(_face_record(f, made, ctx), data["distance"]) if _surface(f) == "Plane"
                        else _unread_round(f) if _surface(f) == "Cylinder"
                        else {"kind": "other", "type": _surface(f) or "none"} for f in made]
    found, rounds = [], []
    for face in made:
        surface = _surface(face)
        if surface == "Cylinder":
            cylinder = _cylinder(face)
            if cylinder is not None:
                rounds.append(cylinder)
        if surface != "Plane":
            continue
        point = geo.safe(lambda: geo.point(face.pointOnFace), None)
        normal = geo.safe(lambda: geo.outward_normal(face), None)
        if point is not None and normal is not None:
            found.append({"point": point, "normal": normal})
    out["faces_after"] = found
    out["rounds_after"] = rounds
    return out


# type name -> (before, after); either may be None
READERS = {
    "OffsetFacesFeature": (offset_faces_before, offset_faces_after),
}
