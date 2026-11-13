"""The end face a sweep made, checked against the end of the planned path. The volume check cannot see a path that
starts at the wrong end or leaves the wrong way, since those keep the volume; the made end face does. Pure."""
import math

from ..geometry import vec
from . import path_curves
from .path_limits import SQUARE_TOL_DEG
from .result import Refusal
from .sweep_limits import NOT_MATCHING

END_PLANE_TOL = 1e-3      # a made end face lies this close to the plane square to the path end (mm)
REACH_TOLERANCE = 0.01    # share of the outline's reach a point of the end face may lie beyond (arcs are sampled)

END_UNCHECKED = "The end of the path of %s could not be checked against the shape Fusion made."


def _readable(faces):
    """The faces with a point and a normal, or None when the list is missing or one face lacks either."""
    if not isinstance(faces, list):
        return None
    for face in faces:
        if not isinstance(face, dict) or not _vector(face.get("point")) or not _vector(face.get("normal")):
            return None
    return faces


def _vector(value):
    return isinstance(value, (list, tuple)) and len(value) == 3 and all(
        isinstance(v, (int, float)) and not isinstance(v, bool) for v in value)


def _end_facing(profile, found, fixed):
    """The unit normal the end face has: square to the path's end, or the outline's own normal when it keeps its
    direction."""
    if fixed:
        return vec.unit(profile["frame"]["z"])
    return path_curves.tangents(found.curves[-1])[1]


def end_check(data, combine, profile, found, points, fixed, tapered):
    """`(Refusal or None, note or None)`: a Refusal when a made end face is not where the planned path ends (not on the
    plane square to it, not facing along it, or, for a new body's one end face, beyond the outline's reach from the
    path end); a note text when the faces were not readable. Nothing for a path with no end face (closed, a full
    circle) or for a capture without them."""
    faces = data.get("faces_after")
    if found.closed or found.kind == "circle" or not isinstance(faces, dict) or "end" not in faces:
        return None, None
    ends = _readable(faces["end"])
    if ends is None:
        return None, END_UNCHECKED
    if not ends:
        return None, None
    facing = _end_facing(profile, found, fixed)
    for face in ends:
        normal = vec.unit(face["normal"])
        if math.degrees(math.asin(min(1.0, vec.length(vec.cross(normal, facing))))) > SQUARE_TOL_DEG:
            return Refusal(NOT_MATCHING), None
        if abs(vec.dot(vec.sub(face["point"], found.end), facing)) > END_PLANE_TOL:
            return Refusal(NOT_MATCHING), None
    if combine == "new" and not tapered and len(ends) == 1 and points:
        reach = max(vec.length(vec.sub(p, found.start)) for p in points)
        if vec.length(vec.sub(ends[0]["point"], found.end)) > reach * (1.0 + REACH_TOLERANCE) + END_PLANE_TOL:
            return Refusal(NOT_MATCHING), None
    return None, None
