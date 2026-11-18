"""A whole round face that an offset faces step (press pull) moves, as facts: a pin, a boss or a bore.

Fusion moves the face along its outward normal, so the radius of a pin or a boss becomes r + distance and the radius
of a bore r - distance. The face is moved as a whole only when it goes all the way round and both its ends lie on flat
faces square to its axis; the faces at its ends do not move. The capture holds the outlines of those end faces, so
`whole` gives the face as a `Ring` with the lowest and highest radius it may take before it reaches another edge of
an end face. `problem` checks a move by one distance: the face is whole, no face next to it moves too, the new
radius stays clear of the other edges and above zero (`radius_problem`), and Fusion left a cylinder of that radius
(`rounds_after`). Every problem has the cause of a curved face that is not copied (`OFFSET_CURVED`).

How an output writes the move, and how it keeps a distance that follows sizes inside `room`, is not here.
"""
import math
from typing import NamedTuple

from ...capture_model import gap_hints
from ...geometry import vec
from ...geometry.footprint import arc_span, curve_distance, is_full, polyline
from ..problem import Problem
from .. import words

PARALLEL_TOL = 1e-6
# How close, in mm, an end circle must lie to the axis and to the radius, and a cylinder Fusion left after the step
# to the expected one.
ON_TOL_MM = 1e-3
# How far, in mm, the face must stay from every other edge of its end faces (and from its axis), before and after the
# move.
CLEAR_MM = 1e-2

UNREAD, NOT_WHOLE, MEETS, CLOSES, RUNS_INTO, NOT_MEASURED = (
    "roundUnread", "roundNotWhole", "roundMeets", "roundCloses", "roundRunsInto", "roundNotMeasured")
_WORDS = {UNREAD: words.OFFSET_ROUND_UNREAD, NOT_WHOLE: words.OFFSET_ROUND_NOT_WHOLE, MEETS: words.OFFSET_ROUND_MEETS,
          CLOSES: words.OFFSET_ROUND_CLOSES, RUNS_INTO: words.OFFSET_ROUND_RUNS_INTO,
          NOT_MEASURED: words.OFFSET_NOT_MEASURED}


def _problem(code):
    return Problem(code, _WORDS[code], gap_hints.OFFSET_CURVED)


def is_round(face):
    return isinstance(face, dict) and face.get("kind") == "round"


def is_ring(face):
    """True for a round face record with an axis, a radius, a known side and two circle ends."""
    ends = face.get("ends") if is_round(face) else None
    return (isinstance(ends, list) and len(ends) == 2
            and all(isinstance(e, dict) and e.get("kind") == "circle" for e in ends)
            and all(face.get(k) is not None for k in ("axis", "radius", "outward")))


class Ring:
    """A whole round face (`is_ring`): the axis through the centre of its first end circle, its radius before the move,
    `sign` 1 when it faces away from the axis (a pin or a boss) and -1 when it faces the axis (a bore), and `span`, the
    places of its two end circles along the axis."""

    def __init__(self, face):
        self.axis = vec.unit(face["axis"])
        self.base = list(face["ends"][0]["center"])
        self.span = sorted(vec.dot(vec.sub(end["center"], self.base), self.axis) for end in face["ends"])
        self.radius = face["radius"]
        self.sign = 1.0 if face["outward"] else -1.0

    def moved_radius(self, distance):
        """The radius after a move of `distance` along the outward normal."""
        return self.radius + self.sign * distance

    def local(self, p):
        """(place along the axis, the vector from the axis out to `p`) of a point."""
        rel = vec.sub(p, self.base)
        along = vec.dot(rel, self.axis)
        return along, vec.sub(rel, vec.scale(self.axis, along))

    def middle(self):
        """The point of the axis halfway between the two ends."""
        return vec.add(self.base, vec.scale(self.axis, (self.span[0] + self.span[1]) / 2.0))

    def end_point(self, n):
        """The centre of the end circle at `span[n]` (0 the low end, 1 the high end along the axis)."""
        return vec.add(self.base, vec.scale(self.axis, self.span[n]))

    def box(self, radius):
        """The box (low corner, high corner) of the cylinder of `radius` between the two ends."""
        ends = [self.end_point(0), self.end_point(1)]
        reach = [radius * math.sqrt(max(0.0, 1.0 - a * a)) for a in self.axis]
        return ([min(e[i] for e in ends) - reach[i] for i in range(3)],
                [max(e[i] for e in ends) + reach[i] for i in range(3)])

    def crossings(self, q, n, radii):
        """Parameters t where q + t * n crosses the cylinder of one of `radii` or the plane of an end."""
        out = []
        dz = vec.dot(n, self.axis)
        along, w = self.local(q)
        if abs(dz) > 1e-9:
            out += [(h - along) / dz for h in self.span]
        m = vec.sub(n, vec.scale(self.axis, dz))
        a, b = vec.dot(m, m), 2.0 * vec.dot(w, m)
        if a <= 1e-12:
            return out
        for radius in radii:
            root = b * b - 4.0 * a * (vec.dot(w, w) - radius * radius)
            if root >= 0:
                out += [(-b - math.sqrt(root)) / (2.0 * a), (-b + math.sqrt(root)) / (2.0 * a)]
        return out


class Whole(NamedTuple):
    """A round face that can be moved as a whole: its `ring`, and `low` and `high`, the largest distance from its axis
    of the other edges of its end faces inside it (0 when none) and the smallest of those outside it (inf when none)."""

    ring: Ring
    low: float
    high: float


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


def _limits(face, circles):
    """(low, high) as `Whole` gives them, or None when an edge already meets the ring. `circles` are the `_end_circle`
    of its ends."""
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


def _shape_problem(face):
    """Why a round face record cannot be moved as a whole ring, or None."""
    ends = face.get("ends")
    if (any(face.get(k) is None for k in ("origin", "axis", "radius", "point", "outward"))
            or not isinstance(ends, list) or not all(ends)):
        return _problem(UNREAD)
    if len(ends) != 2 or any(end.get("kind") != "circle" for end in ends):
        return _problem(NOT_WHOLE)
    if any(end.get(k) is None for end in ends for k in ("center", "normal", "radius")):
        return _problem(UNREAD)
    return None


def whole(face):
    """The `Whole` of a round face record that can be moved as a whole ring, else a `Problem`."""
    found = _shape_problem(face)
    if found:
        return found
    ring = Ring(face)
    circles = [_end_circle(ring, face, end) for end in face["ends"]]
    if any(c is None for c in circles):
        return _problem(NOT_WHOLE)
    limits = _limits(face, circles)
    return Whole(ring, *limits) if limits is not None else _problem(RUNS_INTO)


def room(found):
    """(lowest, highest) radius, both excluded, that the face of the `Whole` and its moved radius must stay between."""
    return found.low + CLEAR_MM, found.high - CLEAR_MM


def radius_problem(found, radius):
    """The `Problem` of moving the face of the `Whole` to `radius`, or None: the face closes, or the face before or
    after the move does not stay inside `room`."""
    if radius <= CLEAR_MM:
        return _problem(CLOSES)
    low, high = room(found)
    if not (low < min(found.ring.radius, radius) and max(found.ring.radius, radius) < high):
        return _problem(RUNS_INTO)
    return None


def _measured(ring, radius, after):
    """True when Fusion left a cylinder on the face's axis with the radius the move gives."""
    for found in after:
        if not all(found.get(k) is not None for k in ("origin", "axis", "radius")):
            continue
        if (_parallel(found["axis"], ring.axis) and _off_axis(ring, found["origin"]) <= ON_TOL_MM
                and abs(found["radius"] - radius) <= ON_TOL_MM):
            return True
    return False


def problem(face, distance, after):
    """The `Problem` of moving the round face record `face` by `distance` (mm along its outward normal), or None.
    `after` holds the cylinders Fusion left after the step (`rounds_after`)."""
    found = whole(face)
    if isinstance(found, Problem):
        return found
    if face.get("meets_offset"):
        return _problem(MEETS)
    radius = found.ring.moved_radius(distance)
    moved = radius_problem(found, radius)
    if moved:
        return moved
    if not _measured(found.ring, radius, after):
        return _problem(NOT_MEASURED)
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
