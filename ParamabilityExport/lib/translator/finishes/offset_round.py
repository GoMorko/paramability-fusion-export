"""Round faces of an offset (press pull): a whole pin, boss or bore whose radius changes by the distance.

Fusion moves the face along its outward normal, so the radius of a pin becomes r + distance and the radius of a bore
r - distance. The app (recipe version 17) moves such a face only when it goes all the way round and both its ends meet
flat faces square to its axis, and it refuses a ring that would run into other faces. The capture holds the outlines
of the two end faces, so a ring that would reach another edge of an end face is left out here. A distance that
follows a size is checked over the size range the same way (`clear_over_range`).
"""
import math

from ...design_model.values import Quantity
from ...geometry import vec
from ...geometry.footprint import arc_span, curve_distance, is_full, polyline
from ..faces.offset_faces import Ring
from ..result import Refusal
from ..values import stays_positive

# The recipe version whose app moves a round face.
VERSION = 17
PARALLEL_TOL = 1e-6
# How close, in mm, an end circle must lie to the axis and to the radius, and a cylinder Fusion left after the step
# to the expected one.
ON_TOL_MM = 1e-3
# How far, in mm, the ring must stay from every other edge of its end faces, before and after the move.
CLEAR_MM = 1e-2

UNREADABLE = "The round face of this offset could not be read, so it is not copied."
NOT_WHOLE = ("A round face is copied only when it goes all the way round and both its ends are flat faces square "
             "to its axis.")
MEETS = "This offset also moves a face next to the round face, so it is not copied."
CLOSES = "This offset would close the round face, so it is not copied."
RUNS_INTO = "The round face of this offset would run into other edges of the faces at its ends, so it is not copied."
NOT_MEASURED = "The offset of this step could not be measured, so it is not copied."


def is_round(face):
    return isinstance(face, dict) and face.get("kind") == "round"


def _parallel(a, b):
    return abs(vec.dot(vec.unit(a), vec.unit(b))) >= 1.0 - PARALLEL_TOL


def _off_axis(ring, p):
    """How far `p` lies from the axis of `ring`, in mm."""
    return vec.length(ring.local(p)[1])


def _farthest(curve, p):
    """The largest distance from `p` to a point of the curve: exact for lines, circles and arcs, else on its polyline."""
    kind = curve["kind"]
    if kind == "line":
        return max(math.dist(p, curve["start"]), math.dist(p, curve["end"]))
    if kind in ("circle", "arc"):
        c, r = curve["center"], curve["radius"]
        if is_full(curve):
            return math.dist(p, c) + r
        found = [math.dist(p, curve["start"]), math.dist(p, curve["end"])]
        a0, sweep = arc_span(curve)
        away = math.atan2(c[1] - p[1], c[0] - p[0])
        turned = (away - a0) % (2 * math.pi)
        if (turned <= sweep) if sweep >= 0 else (turned >= 2 * math.pi + sweep or turned == 0):
            found.append(math.dist(p, c) + r)
        return max(found)
    return max(math.dist(p, q) for q in polyline(curve))


def _end_circle(ring, face, end):
    """(uv of the end circle's centre in the end face's plane, index of that circle among the face's curves), or None
    when the end is not a circle of the ring on a flat face square to the axis."""
    plane = end.get("face")
    if not (isinstance(plane, dict) and isinstance(plane.get("frame"), dict) and plane.get("loops")):
        return None
    frame = plane["frame"]
    if not (_parallel(end["normal"], ring.axis) and _parallel(frame["z"], ring.axis)
            and _off_axis(ring, end["center"]) <= ON_TOL_MM and abs(end["radius"] - face["radius"]) <= ON_TOL_MM):
        return None
    local = vec.frame_to_local(frame, end["center"])
    if abs(local[2]) > ON_TOL_MM:
        return None
    uv = local[:2]
    curves = [c for loop in plane["loops"] for c in loop.get("curves") or []]
    for n, curve in enumerate(curves):
        if (curve["kind"] == "circle" and math.dist(curve["center"], uv) <= ON_TOL_MM
                and abs(curve["radius"] - face["radius"]) <= ON_TOL_MM):
            return uv, n
    return None


def _limits(face, ring, circles):
    """(lowest, highest) radius the ring may take without meeting another edge of its end faces, or None when an edge
    already meets the ring. `circles` are the `_end_circle` of its ends."""
    low, high = 0.0, math.inf
    for end, (uv, own) in zip(face["ends"], circles):
        curves = [c for loop in end["face"]["loops"] for c in loop.get("curves") or []]
        for n, curve in enumerate(curves):
            if n == own:
                continue
            near, far = curve_distance(curve, uv), _farthest(curve, uv)
            if far < face["radius"]:
                low = max(low, far)
            elif near > face["radius"]:
                high = min(high, near)
            else:
                return None
    return low, high


def _shape_reason(face):
    """Why a round face record cannot be moved as a whole ring, or None."""
    ends = face.get("ends")
    if (any(face.get(k) is None for k in ("origin", "axis", "radius", "point", "outward"))
            or not isinstance(ends, list) or not all(ends)):
        return UNREADABLE
    if len(ends) != 2 or any(end.get("kind") != "circle" for end in ends):
        return NOT_WHOLE
    if any(end.get(k) is None for end in ends for k in ("center", "normal", "radius")):
        return UNREADABLE
    return None


def ring_limits(face):
    """(Ring, (lowest, highest) radius) of a round face that can be moved as a whole ring, else (None, reason)."""
    reason = _shape_reason(face)
    if reason:
        return None, reason
    ring = Ring(face)
    circles = [_end_circle(ring, face, end) for end in face["ends"]]
    if any(c is None for c in circles):
        return None, NOT_WHOLE
    limits = _limits(face, ring, circles)
    return (ring, limits) if limits is not None else (None, RUNS_INTO)


def _measured(ring, face, radius, after):
    """True when Fusion left a cylinder on the face's axis with the radius the move gives."""
    for found in after:
        if not all(found.get(k) is not None for k in ("origin", "axis", "radius")):
            continue
        if (_parallel(found["axis"], ring.axis) and _off_axis(ring, found["origin"]) <= ON_TOL_MM
                and abs(found["radius"] - radius) <= ON_TOL_MM):
            return True
    return False


def refusal(face, distance, after):
    """The Refusal for a round face the recipe cannot move by `distance`, or None. `after` holds the cylinders Fusion
    left after the step (`rounds_after`)."""
    ring, limits = ring_limits(face)
    if ring is None:
        return Refusal(limits)
    if face.get("meets_offset"):
        return Refusal(MEETS)
    radius = ring.moved_radius(distance)
    if radius <= CLEAR_MM:
        return Refusal(CLOSES)
    low, high = limits
    if not (low + CLEAR_MM < min(face["radius"], radius) and max(face["radius"], radius) < high - CLEAR_MM):
        return Refusal(RUNS_INTO)
    if not _measured(ring, face, radius, after):
        return Refusal(NOT_MEASURED)
    return None


def near_point(face):
    """A point on the round face halfway between its ends, on the side of the point Fusion gave; None when that point
    lies on the axis."""
    ring = Ring(face)
    out = ring.local(face["point"])[1]
    size = vec.length(out)
    if size <= ON_TOL_MM:
        return None
    middle = ring.middle()
    return [round(middle[i] + out[i] * face["radius"] / size, 9) + 0.0 for i in range(3)]


def clear_over_range(table, faces, q):
    """True when the radius of every round face moved by the sized distance `q` stays clear of the other edges of its
    end faces (and above zero) over the size range."""
    for face in faces:
        ring, (low, high) = ring_limits(face)
        radius = Quantity(face["radius"]).plus(q.scaled(ring.sign))
        if not stays_positive(table, radius.plus(-(low + CLEAR_MM))):
            return False
        if math.isfinite(high) and not stays_positive(table, radius.scaled(-1).plus(high - CLEAR_MM)):
            return False
    return True
