"""The flat faces of the target body that lie square to an extrude's sketch normal, read before the extrude.

A join through all ends at the far side of the body. A flat face of the body on the plane of the measured end shows
that the body reaches that plane, so its box is not looser than the body there (`translator/extrude/through.py`).
Members: `BRepBody.faces`, `BRepFace.geometry`, `BRepFace.pointOnFace`, `BRepFace.evaluator.getNormalAtPoint`.
"""
from ..geometry import vec
from . import read_geometry as geo

# Faces read at most per body; a body with more faces gives None (not read).
MAX_FACES = 2000
# A face normal this close to the sketch normal (1 - |cos|) is square to the sketch plane.
_PARALLEL_TOL = 1e-6


def _flat_face(face, origin, z):
    """[offset, facing] of a flat face square to unit `z`: its signed distance (mm) along `z` from `origin` and the
    sign of its outward normal along `z`; None for any other face."""
    if geo.surface_kind(face) != "Plane":
        return None
    normal = geo.outward_normal(face)
    along = vec.dot(normal, z)
    if abs(abs(along) - 1.0) > _PARALLEL_TOL:
        return None
    offset = vec.dot(vec.sub(geo.point(face.pointOnFace), origin), z)
    return [round(offset, 6) + 0.0, 1 if along > 0 else -1]


def target_flat_faces(ctx, frame):
    """[[offset, facing], ...] for each flat face of the target body (at the current marker) square to the sketch
    normal of `frame` (the first outline's sketch frame), or None when the body or a face cannot be read."""
    body = ctx.find_target()
    if body is None or not isinstance(frame, dict):
        return None
    faces = geo.collection_items(geo.safe(lambda: body.faces, None))
    if not faces or len(faces) > MAX_FACES:
        return None
    z, origin = vec.unit(frame["z"]), frame["origin"]
    out = []
    for face in faces:
        found = geo.safe(lambda: _flat_face(face, origin, z), False)
        if found is False:
            return None
        if found is not None:
            out.append(found)
    return out
