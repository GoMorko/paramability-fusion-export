"""Whether the outlines of an extrude, moved along their sketch normal, all meet a curved face it ends on
(`outline_hits_face`, agent-docs/capture-format.md, `outline_hits_face`).

With Chain Faces off, Fusion ends such an extrude on the surface of the face, extended past the face's edges where an
outline reaches past them. The copy takes the face as it is, so it is copied only when every outline lands on the
face itself. The reader runs with the marker before the step: it casts a ray along the sketch normal, toward the face,
from points spread over each outline (`region_inside.sample_points`), and asks Fusion which faces each ray meets
(`Component.findBRepUsingRay`, hidden bodies included).
"""
from ..geometry import region_inside, vec
from . import read_geometry as geo

# Rays cast for all outlines of one extrude together.
MAX_RAYS = 200
# A point this near (mm) to an outline's curve is not a grid point inside it.
INSIDE_TOL = 1e-3
_FACE_ENTITY = 1  # BRepEntityTypes.BRepFaceEntityType


def _face_type():
    try:
        import adsk.fusion
        return adsk.fusion.BRepEntityTypes.BRepFaceEntityType
    except Exception:
        return _FACE_ENTITY


def _vector(v):
    import adsk.core
    return adsk.core.Vector3D.create(v[0], v[1], v[2])


def _is_face(found, face, token):
    if geo.same_entity(found, face) or geo.same_entity(geo.safe(lambda: found.nativeObject, None), face):
        return True
    return bool(token) and geo.safe(lambda: found.entityToken, None) == token


def _hits(component, face, token, start, way):
    """True when the ray from `start` (model mm) along `way` meets `face`; raises when Fusion gives no answer."""
    found = component.findBRepUsingRay(geo.point3d(start), _vector(way), _face_type(), -1.0, False)
    return any(_is_face(entity, face, token) for entity in geo.collection_items(found))


def _side(frame, toward):
    """The unit sketch normal of `frame` turned toward the point `toward`, or None when the point lies on the sketch
    plane."""
    z = vec.unit(frame["z"])
    along = vec.dot(vec.sub(toward, frame["origin"]), z)
    if abs(along) < 1e-9:
        return None
    return z if along > 0 else vec.scale(z, -1.0)


def _outline_hits(face, profiles, toward):
    component = geo.component_of(face)
    token = geo.safe(lambda: face.entityToken, "")
    if component is None or not profiles:
        return None
    each = MAX_RAYS // len(profiles)
    for profile in profiles:
        if not isinstance(profile, dict) or not isinstance(profile.get("frame"), dict) or not profile.get("loops"):
            return None
        way = _side(profile["frame"], toward)
        if way is None:
            return None
        for u, v in region_inside.sample_points(profile["loops"], each, INSIDE_TOL):
            if not _hits(component, face, token, vec.frame_apply(profile["frame"], [u, v, 0.0]), way):
                return False
    return True


def outline_hits_face(face, profiles, toward):
    """True when a ray from every sample point of every outline in `profiles` (capture outline records), along its
    sketch normal toward the point `toward` (the face's `face_point`), meets the curved BRepFace `face`; False when a
    ray misses it; None when it cannot be told. Never raises."""
    return geo.safe(lambda: _outline_hits(face, profiles, toward), None)


def mark_side(side, entity, profiles):
    """Adds `outline_hits_face` to the capture record `side` of a side up to a curved face of the part with Chain
    Faces off; `entity` is the face (Fusion's `entity` of the extent). Any other side is left as it is."""
    if (not isinstance(side, dict) or side.get("kind") != "toEntity" or side.get("entity_type") != "BRepFace"
            or side.get("surface") in ("Plane", None) or side.get("chained") is not False or side.get("foreign")
            or not isinstance(side.get("face_point"), list)):
        return
    side["outline_hits_face"] = outline_hits_face(entity, profiles, side["face_point"]) if entity is not None else None
