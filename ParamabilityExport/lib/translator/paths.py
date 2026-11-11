"""The path of a sweep as the recipe holds it. Pure: no Fusion imports.

`plan` takes the path record of the capture (3D curves in the target component's coordinates) and the outline that
is swept, and returns a `PathPlan` or a `Refusal`. It

- chains the curves end to end and turns the chain so it starts on the plane of the outline;
- names what the path is: a `line`, an `arc`, a full `circle`, a `flat` chain (lines, arcs and free curves in one
  plane) or a `corners` chain (lines joined by tangent arcs, in any direction);
- writes the flat and corners forms the recipe's sweep step takes (`PathPlan.recipe`), with free curves fitted by
  `spline_fit`;
- checks what the app refuses to build: a closed path, a path that crosses itself, a sharp corner, an outline that
  reaches past the tightest bend, a path that does not start square on the outline.

A line, an arc and a circle carry the numbers that an extrude or a revolve needs instead (`direction`, `axis`,
`angle_deg`); they have no `recipe` path. Coordinates stay in the capture's frame: a flat path is written as its own
placement and 2D points, a corners path as 3D points that the caller moves into the recipe frame.
"""
import math
from dataclasses import dataclass
from typing import Optional

from ..package.numbers import round9

from . import spline_fit, vec
from .result import Refusal

CHAIN_TOL = 1e-4          # curve ends closer than this (mm) are one point
PLANE_TOL = 1e-4          # the path start must lie this close to the outline's plane (mm), as in the app
SQUARE_TOL_DEG = 0.1      # the path must leave the outline's plane at a right angle within this
STRAIGHT_DEG = 0.01       # a turn below this (degrees) is straight on: the app's own limit for a straight continuation
SMOOTH_JOIN_DEG = 2.0     # the app takes a join next to a curve as smooth up to this turn (degrees)
CORNER_MATCH_TOL = 1e-3   # where the legs of a bend meet, the two ways of finding the corner agree within this (mm)
TOUCH_TOL = 1e-4          # parts of a path closer than this (mm) touch
MAX_SEGMENTS = 64         # segments of a flat path (recipe cap)
MAX_POINTS = 64           # points of a corners path (recipe cap)
MAX_TURN_DEG = 179.5      # a bend turning more than this cannot be a rounded corner
ARC_SAMPLE_DEG = 3.0
MAX_OVERLAP_SAMPLES = 1500   # samples along a path when two far apart parts are checked for coming close
OVERLAP_STEP_SHARE = 0.5     # samples are at most this share of the outline's reach apart
OVERLAP_CORNER_DEG = 5.0     # a turn above this (degrees) at a vertex is a corner, whose mitre overlaps its arms
OVERLAP_MAX_CORNER_DEG = 160.0
OVERLAP_CLEAR_SHARE = 0.95   # parts closer than this share of twice the reach overlap
CURVATURE_SAMPLES = 129   # readings along a fitted spline when its tightest bend is looked for
REACH_SHARE = 1 - 1e-6    # an outline reaching this share of a bend's radius reaches its centre

UNREADABLE = "A curve of the path of this sweep could not be read closely enough to copy."
UNKNOWN_CURVE = "The path of this sweep uses a kind of curve that is not copied yet."
NOT_ONE_CHAIN = "The curves of the path of this sweep do not join end to end into one line."
CLOSED = "Sweeps along a closed path are not copied yet."
BOTH_SIDES = "This sweep runs to both sides of its outline, which is not copied yet."
OFF_PLANE = "The path of this sweep does not start on the plane of its outline."
NOT_SQUARE = "The outline is not square to the path at its start."
SHARP_CORNER = "The path of this sweep has a sharp corner."
BENDS_3D = "The path of this sweep bends in 3D in a way that is not copied yet."
TOO_MANY = "The path of this sweep has too many parts to copy."
CROSSES = "The path of this sweep crosses itself."
OVERLAP = ("Two parts of the path pass %.2f mm apart, but the outline reaches %.2f mm from the path, "
           "so the sweep would run into itself.")
TOO_COMPLEX = "The path of this sweep has a curve that is too complex to copy closely enough."
NOT_SKETCH = "The path of this sweep is not made of sketch lines or edges."


@dataclass
class PathPlan:
    """A path ready for the sweep handler.

    kind: `line`, `arc`, `circle`, `flat` or `corners`.
    curves: the chained curves, oriented along the path, the first one starting on the outline's plane.
    start, end: the path ends (3D). For a circle both are the point of the circle on the outline's plane.
    direction: unit direction of travel at `start`.
    length: path length in mm.
    reversed: the capture listed the path from the far end, so the chain was turned round.
    recipe: the `flat` or `corners` path of the sweep step, else None. `corners` points are 3D in capture
      coordinates, `bendRadius` one number when every bend has it, else one per inner point.
    axis: for an arc or circle, `{ "point": centre, "dir": unit }` with the path turning positively about `dir`.
    radius, angle_deg: for an arc or circle (360).
    """

    kind: str
    curves: list
    start: list
    end: list
    direction: list
    length: float
    reversed: bool = False
    recipe: Optional[dict] = None
    axis: Optional[dict] = None
    radius: Optional[float] = None
    angle_deg: Optional[float] = None


# ---- curves -----------------------------------------------------------------------------------------------------

def _near(a, b, tol=CHAIN_TOL):
    return vec.length(vec.sub(a, b)) <= tol


def _arc_of(curve):
    """Centre, radius, unit normal and turn (radians) of an arc, taken from its start, middle and end. The normal
    makes the arc run start to end counter clockwise."""
    start, mid, end = curve["start"], curve["mid"], curve["end"]
    centre = curve.get("center")
    if centre is None:
        centre = _circumcentre(start, mid, end)
    rs, rm, re = vec.sub(start, centre), vec.sub(mid, centre), vec.sub(end, centre)
    normal = vec.unit(vec.add(vec.cross(rs, rm), vec.cross(rm, re)))
    turn = (_angle(rs, rm, normal) + _angle(rm, re, normal)) % (2 * math.pi)
    return centre, vec.length(rs), normal, turn


def _angle(a, b, normal):
    return math.atan2(vec.dot(vec.cross(a, b), normal), vec.dot(a, b)) % (2 * math.pi)


def _circumcentre(a, b, c):
    ab, ac = vec.sub(b, a), vec.sub(c, a)
    n = vec.cross(ab, ac)
    size = vec.dot(n, n)
    if size <= 1e-18:
        raise ValueError("collinear points")
    first = vec.scale(vec.cross(n, ab), vec.dot(ac, ac))
    second = vec.scale(vec.cross(ac, n), vec.dot(ab, ab))
    return vec.add(a, vec.scale(vec.add(first, second), 1.0 / (2.0 * size)))


def _readable(curve):
    """True when a curve has what the chain and the fit need."""
    if not isinstance(curve, dict):
        return False
    kind = curve.get("kind")
    if kind == "line":
        return _point(curve.get("start")) and _point(curve.get("end")) and not _near(curve["start"], curve["end"])
    if kind == "arc":
        return all(_point(curve.get(k)) for k in ("start", "mid", "end"))
    if kind == "circle":
        return _point(curve.get("center")) and _point(curve.get("normal")) and isinstance(curve.get("radius"), (int, float))
    if kind == "other":
        samples = curve.get("samples")
        return (isinstance(samples, list) and len(samples) >= 2 and all(_point(p) for p in samples)
                and _point(curve.get("start")) and _point(curve.get("end")) and not curve.get("truncated"))
    return False


def _point(p):
    return isinstance(p, (list, tuple)) and len(p) == 3 and all(isinstance(x, (int, float)) for x in p)


def _flip(curve):
    """The curve run the other way: ends swapped, samples reversed, end directions turned round."""
    link = dict(curve, start=curve["end"], end=curve["start"])
    if "samples" in curve:
        link["samples"] = list(reversed(curve["samples"]))
    if curve.get("tangent_start") is not None or curve.get("tangent_end") is not None:
        link["tangent_start"] = _negated(curve.get("tangent_end"))
        link["tangent_end"] = _negated(curve.get("tangent_start"))
    if "normal" in curve:
        link["normal"] = vec.scale(curve["normal"], -1.0)
    return link


def _negated(direction):
    return None if direction is None else vec.scale(direction, -1.0)


def _tangents(curve):
    """Unit directions of travel at the start and at the end of a line, arc or free curve."""
    kind = curve["kind"]
    if kind == "line":
        d = vec.unit(vec.sub(curve["end"], curve["start"]))
        return d, d
    if kind == "arc":
        centre, _, normal, _ = _arc_of(curve)
        return (vec.unit(vec.cross(normal, vec.sub(curve["start"], centre))),
                vec.unit(vec.cross(normal, vec.sub(curve["end"], centre))))
    samples = curve["samples"]
    first = curve.get("tangent_start")
    last = curve.get("tangent_end")
    return (vec.unit(first if first is not None else vec.sub(samples[1], samples[0])),
            vec.unit(last if last is not None else vec.sub(samples[-1], samples[-2])))


def _polyline(curve):
    """Points along a curve from its start to its end (arcs every few degrees, free curves by their samples)."""
    kind = curve["kind"]
    if kind == "line":
        return [curve["start"], curve["end"]]
    if kind == "other":
        return [list(p) for p in curve["samples"]]
    centre, _, normal, turn = _arc_of(curve)
    steps = max(2, int(math.ceil(math.degrees(turn) / ARC_SAMPLE_DEG)))
    points = [curve["start"]]
    for k in range(1, steps):
        points.append(vec.rotate(curve["start"], normal, math.degrees(turn) * k / steps, centre))
    points.append(curve["end"])
    return points


def _length(curve):
    if curve["kind"] == "arc":
        _, radius, _, turn = _arc_of(curve)
        return radius * turn
    points = _polyline(curve)
    return sum(vec.length(vec.sub(b, a)) for a, b in zip(points, points[1:]))


# ---- chaining ---------------------------------------------------------------------------------------------------

def chain(curves):
    """`(ordered, closed)`: the curves ordered and oriented end to end, or None when they do not form one chain
    (a gap, a branch or two pieces). An open chain starts at the free end of the earliest curve in the list; a
    closed one (a ring of curves) at the start of the first curve."""
    nodes, ends = [], []
    for curve in curves:
        pair = []
        for point in (curve["start"], curve["end"]):
            at = next((n for n, node in enumerate(nodes) if _near(node, point)), None)
            if at is None:
                nodes.append(point)
                at = len(nodes) - 1
            pair.append(at)
        ends.append(pair)
    if any(a == b for a, b in ends):
        return None
    degree = [0] * len(nodes)
    for a, b in ends:
        degree[a] += 1
        degree[b] += 1
    if any(d > 2 for d in degree):
        return None
    free = [n for n, d in enumerate(degree) if d == 1]
    if len(free) not in (0, 2):
        return None
    closed = not free
    at = ends[0][0] if closed else next(n for pair in ends for n in pair if degree[n] == 1)
    left = list(range(len(curves)))
    ordered = []
    while left:
        found = next((i for i in left if at in ends[i]), None)
        if found is None:
            return None
        left.remove(found)
        forward = ends[found][0] == at
        ordered.append(curves[found] if forward else _flip(curves[found]))
        at = ends[found][1] if forward else ends[found][0]
    return ordered, closed


def turned_round(curves):
    """The chain run from its other end."""
    return [_flip(c) for c in reversed(curves)]


# ---- the plan ---------------------------------------------------------------------------------------------------

def plan(path, profile_frame, profile_points):
    """The `PathPlan` of a capture path record, or a `Refusal`.

    `profile_frame` is the outline's frame (`origin` and `z`, the plane it lies in); `profile_points` are points of
    the outline in the same coordinates (3D), used to measure how far the outline reaches from the path.
    """
    try:
        return _plan(path, profile_frame, profile_points)
    except ValueError:
        return Refusal(UNREADABLE)


def _plan(path, profile_frame, profile_points):
    if path.get("kind") == "other":
        return Refusal(NOT_SKETCH)
    curves = path.get("curves")
    if not isinstance(curves, list) or not curves or any(not isinstance(c, dict) for c in curves):
        return Refusal(UNREADABLE)
    if any(c.get("kind") not in ("line", "arc", "circle", "other") for c in curves):
        return Refusal(UNKNOWN_CURVE)
    if any(not _readable(c) for c in curves):
        return Refusal(UNREADABLE)
    ring = _circle_of(curves)
    if ring is not None:
        return _circle_plan(ring, curves, profile_frame, profile_points)
    if any(c["kind"] == "circle" for c in curves):
        return Refusal(NOT_ONE_CHAIN)
    found = chain(curves)
    if found is None:
        return Refusal(NOT_ONE_CHAIN)
    ordered, closed = found
    if closed or path.get("closed"):
        return Refusal(CLOSED)
    origin, normal = profile_frame["origin"], vec.unit(profile_frame["z"])
    oriented = _toward_plane(ordered, origin, normal)
    if isinstance(oriented, Refusal):
        return oriented
    ordered, reversed_ = oriented
    ordered = _joined_lines(ordered)
    start, end = ordered[0]["start"], ordered[-1]["end"]
    direction = _tangents(ordered[0])[0]
    if _off_square(direction, normal):
        return Refusal(NOT_SQUARE)
    kind = _kind_of(ordered)
    base = dict(curves=ordered, start=[round9(x) for x in start], end=[round9(x) for x in end],
                direction=[round9(x) for x in direction], length=round9(sum(_length(c) for c in ordered)),
                reversed=reversed_)
    if kind == "line":
        return PathPlan(kind="line", **base)
    if kind == "arc":
        return _arc_plan(base, ordered[0], profile_points)
    return _chain_plan(base, ordered, path, profile_points)


def _off_square(direction, normal):
    """True when the path direction is more than `SQUARE_TOL_DEG` away from the outline's normal."""
    return math.degrees(math.asin(min(1.0, vec.length(vec.cross(direction, normal))))) > SQUARE_TOL_DEG


def _kind_of(ordered):
    if len(ordered) == 1:
        return "line" if ordered[0]["kind"] == "line" else "arc" if ordered[0]["kind"] == "arc" else "flat"
    return "chain"


def _distances(ordered, origin, normal):
    return [vec.dot(vec.sub(p, origin), normal) for c in ordered for p in _polyline(c)]


def _toward_plane(ordered, origin, normal):
    """`(chain, reversed)` with the chain starting on the plane, or a Refusal when neither end lies on it. When both
    ends do, the one the path leaves at a right angle wins."""
    first = abs(vec.dot(vec.sub(ordered[0]["start"], origin), normal)) <= PLANE_TOL
    last = abs(vec.dot(vec.sub(ordered[-1]["end"], origin), normal)) <= PLANE_TOL
    if first and last:
        if _off_square(_tangents(ordered[0])[0], normal) and not _off_square(_tangents(ordered[-1])[1], normal):
            return turned_round(ordered), True
        return ordered, False
    if first:
        return ordered, False
    if last:
        return turned_round(ordered), True
    d = _distances(ordered, origin, normal)
    if min(d) < -PLANE_TOL and max(d) > PLANE_TOL or any(abs(x) <= PLANE_TOL for x in d):
        return Refusal(BOTH_SIDES)
    return Refusal(OFF_PLANE)


def _turn_deg(a, b):
    """The angle in degrees between two unit directions."""
    return math.degrees(math.atan2(vec.length(vec.cross(a, b)), vec.dot(a, b)))


def _joined_lines(ordered):
    """The chain with neighbouring lines that continue straight written as one line."""
    out = []
    for curve in ordered:
        if out and out[-1]["kind"] == curve["kind"] == "line" \
                and _turn_deg(_tangents(out[-1])[1], _tangents(curve)[0]) <= STRAIGHT_DEG:
            out[-1] = dict(out[-1], end=curve["end"])
        else:
            out.append(curve)
    return out


# ---- one arc and one circle -------------------------------------------------------------------------------------

def _arc_plan(base, curve, profile_points):
    centre, radius, normal, turn = _arc_of(curve)
    refusal = _reach_refusal(profile_points, curve["start"], normal, radius)
    if refusal:
        return refusal
    return PathPlan(kind="arc", axis={"point": _round(centre), "dir": _round(normal)}, radius=round9(radius),
                    angle_deg=round9(math.degrees(turn)), **base)


def _circle_of(curves):
    """`(centre, radius, normal)` when the curves are one full circle (a circle, or arcs of one circle that close
    up), else None."""
    if len(curves) == 1 and curves[0]["kind"] == "circle":
        c = curves[0]
        return c["center"], c["radius"], vec.unit(c["normal"])
    if not all(c["kind"] == "arc" for c in curves):
        return None
    if len(curves) == 1:
        c = curves[0]
        if not _near(c["start"], c["end"]) or "normal" not in c or "center" not in c:
            return None
        return c["center"], vec.length(vec.sub(c["start"], c["center"])), vec.unit(c["normal"])
    try:
        found = [_arc_of(c) for c in curves]
    except ValueError:
        return None
    centre, radius, normal, _ = found[0]
    same = all(_near(centre, f[0]) and abs(f[1] - radius) <= CHAIN_TOL and abs(abs(vec.dot(normal, f[2])) - 1) <= 1e-9
               for f in found)
    if not same or chain(curves) is None or not chain(curves)[1]:
        return None
    return centre, radius, normal


def _circle_plan(ring, curves, profile_frame, profile_points):
    """A full circle: it starts where it meets the plane of the outline nearest to the outline."""
    centre, radius, normal = ring
    origin, plane = profile_frame["origin"], vec.unit(profile_frame["z"])
    u = vec.unit(vec.cross(normal, [1, 0, 0] if abs(normal[0]) < 0.9 else [0, 1, 0]))
    v = vec.cross(normal, u)
    a, b = radius * vec.dot(plane, u), radius * vec.dot(plane, v)
    d = vec.dot(plane, vec.sub(origin, centre))
    size = math.hypot(a, b)
    if size <= 1e-12:
        return Refusal(NOT_SQUARE)
    if abs(d) > size + PLANE_TOL:
        return Refusal(OFF_PLANE)
    spread = math.acos(max(-1.0, min(1.0, d / size)))
    angles = [math.atan2(b, a) + spread, math.atan2(b, a) - spread]
    points = [vec.add(centre, vec.add(vec.scale(u, radius * math.cos(t)), vec.scale(v, radius * math.sin(t))))
              for t in angles]
    mean = [sum(p[i] for p in profile_points) / len(profile_points) for i in range(3)] if profile_points else origin
    at = min(range(2), key=lambda k: vec.length(vec.sub(points[k], mean)))
    start = points[at]
    direction = vec.unit(vec.cross(normal, vec.sub(start, centre)))
    if _off_square(direction, plane):
        return Refusal(NOT_SQUARE)
    refusal = _reach_refusal(profile_points, start, normal, radius)
    if refusal:
        return refusal
    return PathPlan(kind="circle", curves=curves, start=_round(start), end=_round(start), direction=_round(direction),
                    length=round9(2 * math.pi * radius), axis={"point": _round(centre), "dir": _round(normal)},
                    radius=round9(radius), angle_deg=360.0)


def _round(p):
    return [round9(x) for x in p]


# ---- chains of several curves ----------------------------------------------------------------------------------

def _chain_plan(base, ordered, path, profile_points):
    junctions = [(_turn_deg(_tangents(a)[1], _tangents(b)[0]), a["kind"] == b["kind"] == "line")
                 for a, b in zip(ordered, ordered[1:])]
    frame = _flat_frame(path.get("frame"), ordered)
    if frame is None:
        return _corners_plan(base, ordered, junctions, profile_points)
    if any(turn > (STRAIGHT_DEG if both_lines else SMOOTH_JOIN_DEG) for turn, both_lines in junctions):
        return Refusal(SHARP_CORNER)
    return _flat_plan(base, ordered, frame, profile_points)


def _flat_frame(given, ordered):
    """The frame of the plane all the chain's points lie in (the sketch's own when it fits), or None."""
    points = [p for c in ordered for p in _polyline(c)]
    if isinstance(given, dict) and all(k in given for k in ("origin", "x", "z")):
        z = vec.unit(given["z"])
        if all(abs(vec.dot(vec.sub(p, given["origin"]), z)) <= PLANE_TOL for p in points):
            x = vec.unit(given["x"])
            return {"origin": list(given["origin"]), "x": x, "y": vec.cross(z, x), "z": z}
    a = points[0]
    b = max(points, key=lambda p: vec.length(vec.sub(p, a)))
    ab = vec.sub(b, a)
    if vec.length(ab) <= PLANE_TOL:
        return None
    x = vec.unit(ab)

    def off_line(p):
        d = vec.sub(p, a)
        return vec.length(vec.sub(d, vec.scale(x, vec.dot(d, x))))

    c = max(points, key=off_line)
    if off_line(c) <= PLANE_TOL:
        return None
    z = vec.unit(vec.cross(ab, vec.sub(c, a)))
    if any(abs(vec.dot(vec.sub(p, a), z)) > PLANE_TOL for p in points):
        return None
    return {"origin": list(a), "x": x, "y": vec.cross(z, x), "z": z}


def _flat_plan(base, ordered, frame, profile_points):
    def local(p):
        d = vec.sub(p, frame["origin"])
        return [vec.dot(d, frame["x"]), vec.dot(d, frame["y"])]

    segments, tightest = [], math.inf
    at = local(ordered[0]["start"])
    for curve in ordered:
        end = local(curve["end"])
        if curve["kind"] == "line":
            segments.append({"kind": "line", "to": _round2(end)})
        elif curve["kind"] == "arc":
            segments.append({"kind": "arc", "through": _round2(local(curve["mid"])), "to": _round2(end)})
            tightest = min(tightest, _arc_of(curve)[1])
        else:
            drawn = _spline_segments([local(p) for p in curve["samples"]], at, end)
            if drawn is None:
                return Refusal(TOO_COMPLEX)
            segments.extend(drawn)
            tightest = min(tightest, _spline_radius(at, drawn))
        at = end
    if len(segments) > MAX_SEGMENTS:
        return Refusal(TOO_MANY)
    if _self_touch([p for c in ordered for p in _polyline(c)]):
        return Refusal(CROSSES)
    refusal = _reach_refusal(profile_points, ordered[0]["start"], frame["z"], tightest)
    if refusal:
        return refusal
    refusal = _overlap_refusal([p for c in ordered for p in _polyline(c)],
                               _reach(profile_points, ordered[0]["start"], frame["z"]))
    if refusal:
        return refusal
    recipe = {
        "kind": "flat",
        "on": {"origin": _round(frame["origin"]), "normal": _round(frame["z"]), "xDir": _round(frame["x"])},
        "start": _round2(local(ordered[0]["start"])),
        "segments": segments,
    }
    return PathPlan(kind="flat", recipe=recipe, **base)


def _round2(p):
    return [round9(p[0]), round9(p[1])]


def _spline_segments(samples, start, end):
    """Segments through the points `spline_fit` takes from the 2D `samples`; the ends are the curve's own."""
    pieces = spline_fit.fit(samples)
    if pieces is None:
        return None
    pieces[0][0], pieces[-1][-1] = list(start), list(end)
    return [{"kind": "spline", "through": [_round2(p) for p in piece[1:-1]], "to": _round2(piece[-1])}
            if len(piece) > 2 else {"kind": "line", "to": _round2(piece[-1])} for piece in pieces]


def _spline_radius(at, segments):
    """Tightest bend (mm) of the app's curve through the written spline segments, as the app reads it."""
    tightest, here = math.inf, at
    for seg in segments:
        if seg["kind"] == "spline":
            curve = spline_fit.interpolate([here] + seg["through"] + [seg["to"]])
            for k in range(CURVATURE_SAMPLES):
                u = k / (CURVATURE_SAMPLES - 1)
                (vx, vy), (ax, ay) = curve.at(u, 1), curve.at(u, 2)
                speed = math.hypot(vx, vy)
                if speed > 0 and abs(vx * ay - vy * ax) > 0:
                    tightest = min(tightest, speed ** 3 / abs(vx * ay - vy * ax))
        here = seg["to"]
    return tightest


def _reach(profile_points, start, normal):
    """How far the outline reaches from the path start across the plane whose unit `normal` is taken out."""
    reach = 0.0
    for p in profile_points or ():
        d = vec.sub(p, start)
        reach = max(reach, vec.length(vec.sub(d, vec.scale(normal, vec.dot(d, normal)))))
    return reach


def _reach_refusal(profile_points, start, normal, radius):
    """A Refusal when the outline reaches across the path's plane as far as the tightest bend's radius."""
    if not profile_points or radius == math.inf:
        return None
    reach = _reach(profile_points, start, normal)
    if reach >= radius * REACH_SHARE:
        return Refusal("The outline reaches %.2f mm from the path, but the path bends in a radius of %.2f mm."
                       % (reach, radius))
    return None


# ---- 3D chains of lines and tangent arcs -----------------------------------------------------------------------

def _corners_plan(base, ordered, junctions, profile_points):
    """Lines joined by tangent arcs, written as corner points: each line extended to where its neighbours cross it."""
    if any(turn > STRAIGHT_DEG and both_lines for turn, both_lines in junctions):
        return Refusal(SHARP_CORNER)
    kinds = [c["kind"] for c in ordered]
    if (kinds[0] != "line" or kinds[-1] != "line" or "other" in kinds or any(turn > STRAIGHT_DEG for turn, _ in junctions)
            or any(a == b == "arc" for a, b in zip(kinds, kinds[1:]))):
        return Refusal(BENDS_3D)
    points, radii, turns = [ordered[0]["start"]], [], []
    for before, arc, after in zip(ordered, ordered[1:], ordered[2:]):
        if arc["kind"] != "arc":
            continue
        _, radius, _, turn = _arc_of(arc)
        if math.degrees(turn) > MAX_TURN_DEG:
            return Refusal(BENDS_3D)
        d_in, d_out = _tangents(before)[1], _tangents(after)[0]
        tangent = radius * math.tan(turn / 2)
        corner = vec.add(arc["start"], vec.scale(d_in, tangent))
        if not _near(corner, vec.sub(arc["end"], vec.scale(d_out, tangent)), CORNER_MATCH_TOL):
            return Refusal(BENDS_3D)
        points.append(corner)
        radii.append(radius)
        turns.append((vec.unit(vec.cross(d_in, d_out)), turn))
    points.append(ordered[-1]["end"])
    if len(points) > MAX_POINTS:
        return Refusal(TOO_MANY)
    if _self_touch([p for c in ordered for p in _polyline(c)]):
        return Refusal(CROSSES)
    refusal = _carried_reach_refusal(profile_points, ordered[0]["start"], radii, turns)
    if refusal:
        return refusal
    start = ordered[0]["start"]
    refusal = _overlap_refusal([p for c in ordered for p in _polyline(c)],
                               max((vec.length(vec.sub(p, start)) for p in profile_points or ()), default=0.0))
    if refusal:
        return refusal
    recipe = {
        "kind": "corners",
        "points": [_round(p) for p in points],
        "bendRadius": round9(radii[0]) if max(radii) - min(radii) <= CHAIN_TOL else [round9(r) for r in radii],
    }
    return PathPlan(kind="corners", recipe=recipe, **base)


def _carried_reach_refusal(profile_points, start, radii, turns):
    """The outline is carried along the bends, turning with each; at a bend only the part of a point's offset in
    that bend's plane counts against its radius."""
    if not profile_points:
        return None
    carried = [vec.sub(p, start) for p in profile_points]
    for radius, (axis, turn) in zip(radii, turns):
        reach = max(vec.length(vec.sub(o, vec.scale(axis, vec.dot(o, axis)))) for o in carried)
        if reach >= radius * REACH_SHARE:
            return Refusal("The outline reaches %.2f mm from the path, but the path bends in a radius of %.2f mm."
                           % (reach, radius))
        carried = [vec.rotate(o, axis, math.degrees(turn)) for o in carried]
    return None


# ---- parts of the path that come close ------------------------------------------------------------------------

def _overlap_refusal(points, reach):
    """A Refusal when two parts of the path that are far apart along it pass closer than twice the outline's reach:
    the swept shape would run into itself. Pairs on the two arms of one corner are left to the corner's mitre."""
    points = _distinct(points)
    if not reach > 0 or len(points) < 3:
        return None
    total = sum(vec.length(vec.sub(b, a)) for a, b in zip(points, points[1:]))
    step = max(reach * OVERLAP_STEP_SHARE, total / MAX_OVERLAP_SAMPLES)
    samples, corners, along = [(points[0], 0.0)], [], 0.0
    for i in range(1, len(points)):
        a, b = points[i - 1], points[i]
        span = vec.length(vec.sub(b, a))
        parts = max(1, int(math.ceil(span / step)))
        for k in range(1, parts + 1):
            samples.append((vec.add(a, vec.scale(vec.sub(b, a), k / parts)), along + span * k / parts))
        along += span
        if i + 1 < len(points):
            turn = _turn_deg(vec.unit(vec.sub(b, a)), vec.unit(vec.sub(points[i + 1], b)))
            if turn > OVERLAP_CORNER_DEG:
                corners.append((along, math.tan(math.radians(min(turn, OVERLAP_MAX_CORNER_DEG)) / 2)))
    apart, needed = math.pi * reach, 2 * reach * OVERLAP_CLEAR_SHARE

    def covered(low, high):
        for at, fold in corners:
            mitre = 2 * reach * max(1.0, fold)
            if low < at < high and at - low <= mitre and high - at <= mitre:
                return True
        return False

    cells = {}
    for n, (point, _) in enumerate(samples):
        cells.setdefault(tuple(int(math.floor(c / needed)) for c in point), []).append(n)
    for i, (point, at) in enumerate(samples):
        cell = tuple(int(math.floor(c / needed)) for c in point)
        near = sorted(j for dx in (-1, 0, 1) for dy in (-1, 0, 1) for dz in (-1, 0, 1)
                      for j in cells.get((cell[0] + dx, cell[1] + dy, cell[2] + dz), ()) if j > i)
        for j in near:
            if samples[j][1] - at <= apart:
                continue
            gap = vec.length(vec.sub(point, samples[j][0]))
            if gap < needed and not covered(at, samples[j][1]):
                return Refusal(OVERLAP % (gap, reach))
    return None


def _distinct(points):
    """The points without repeats of the one before."""
    out = [points[0]]
    for p in points[1:]:
        if vec.length(vec.sub(p, out[-1])) > 1e-9:
            out.append(p)
    return out


# ---- crossing ---------------------------------------------------------------------------------------------------

def _thinned(points):
    """The points without those closer than a few touch distances to the one before, keeping the last."""
    step = 3 * TOUCH_TOL
    out = [points[0]]
    for p in points[1:]:
        if vec.length(vec.sub(p, out[-1])) > step:
            out.append(p)
        elif len(out) > 1:
            out[-1] = p
        else:
            out.append(p)
    return out


def _self_touch(points):
    """True when two parts of the polyline that are not neighbours cross or come within `TOUCH_TOL`."""
    points = _thinned(points)
    segments = [(points[i], points[i + 1]) for i in range(len(points) - 1)]
    lows = [min(a[0], b[0]) for a, b in segments]
    highs = [max(a[0], b[0]) for a, b in segments]
    order = sorted(range(len(segments)), key=lambda i: lows[i])
    for n, i in enumerate(order):
        for j in order[n + 1:]:
            if lows[j] > highs[i] + TOUCH_TOL:
                break
            if abs(i - j) > 1 and _segment_gap(*segments[i], *segments[j]) <= TOUCH_TOL:
                return True
    return False


def _segment_gap(p1, q1, p2, q2):
    """Smallest distance between segments p1-q1 and p2-q2."""
    d1, d2, r = vec.sub(q1, p1), vec.sub(q2, p2), vec.sub(p1, p2)
    a, e, f = vec.dot(d1, d1), vec.dot(d2, d2), vec.dot(d2, r)
    c, b = vec.dot(d1, r), vec.dot(d1, d2)
    denom = a * e - b * b
    s = min(1.0, max(0.0, (b * f - c * e) / denom)) if denom > 1e-18 else 0.0
    t = (b * s + f) / e if e > 1e-18 else 0.0
    if t < 0.0:
        t, s = 0.0, min(1.0, max(0.0, -c / a)) if a > 1e-18 else 0.0
    elif t > 1.0:
        t, s = 1.0, min(1.0, max(0.0, (b - c) / a)) if a > 1e-18 else 0.0
    near1, near2 = vec.add(p1, vec.scale(d1, s)), vec.add(p2, vec.scale(d2, t))
    return vec.length(vec.sub(near1, near2))
