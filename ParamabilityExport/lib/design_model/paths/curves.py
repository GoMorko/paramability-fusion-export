"""Curves of a sweep path: arcs, directions, points along a curve, and chaining curves end to end. Pure."""
import math

from ...geometry import spline_joints, vec
from ...geometry.tolerances import CHAIN_TOL
from ...package.numbers import round9

from .tolerances import ARC_SAMPLE_DEG, STRAIGHT_DEG


def near(a, b, tol=CHAIN_TOL):
    return vec.length(vec.sub(a, b)) <= tol


def arc_of(curve):
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


def readable(curve):
    """True when a curve has what the chain and the fit need."""
    if not isinstance(curve, dict):
        return False
    kind = curve.get("kind")
    if kind == "line":
        return is_point(curve.get("start")) and is_point(curve.get("end")) and not near(curve["start"], curve["end"])
    if kind == "arc":
        return all(is_point(curve.get(k)) for k in ("start", "mid", "end"))
    if kind == "circle":
        return (is_point(curve.get("center")) and is_point(curve.get("normal"))
                and isinstance(curve.get("radius"), (int, float)))
    if kind == "other":
        samples = curve.get("samples")
        return (isinstance(samples, list) and len(samples) >= 2 and all(is_point(p) for p in samples)
                and is_point(curve.get("start")) and is_point(curve.get("end")) and not curve.get("truncated"))
    return False


def is_point(p):
    return isinstance(p, (list, tuple)) and len(p) == 3 and all(isinstance(x, (int, float)) for x in p)


def flip(curve):
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


def tangents(curve):
    """Unit directions of travel at the start and at the end of a line, arc or free curve."""
    kind = curve["kind"]
    if kind == "line":
        d = vec.unit(vec.sub(curve["end"], curve["start"]))
        return d, d
    if kind == "arc":
        centre, _, normal, _ = arc_of(curve)
        return (vec.unit(vec.cross(normal, vec.sub(curve["start"], centre))),
                vec.unit(vec.cross(normal, vec.sub(curve["end"], centre))))
    samples = curve["samples"]
    first = curve.get("tangent_start")
    last = curve.get("tangent_end")
    return (vec.unit(first if first is not None else vec.sub(samples[1], samples[0])),
            vec.unit(last if last is not None else vec.sub(samples[-1], samples[-2])))


def inner_turn(curve):
    """The sharpest turn (degrees) at a joint inside a free curve, read from its spline definition (`flat.nurbs`,
    `spline_joints.joint_turns`): 0.0 for a line, an arc, a circle and a free curve without a definition (an edge
    of a body), None when the definition cannot be read."""
    flat = curve.get("flat") if curve.get("kind") == "other" else None
    nurbs = flat.get("nurbs") if isinstance(flat, dict) else None
    if nurbs is None:
        return 0.0
    turns = spline_joints.joint_turns(nurbs)
    return None if turns is None else max(turns, default=0.0)


def polyline(curve):
    """Points along a curve from its start to its end (arcs every few degrees, free curves by their samples)."""
    kind = curve["kind"]
    if kind == "line":
        return [curve["start"], curve["end"]]
    if kind == "other":
        return [list(p) for p in curve["samples"]]
    centre, _, normal, turn = arc_of(curve)
    steps = max(2, int(math.ceil(math.degrees(turn) / ARC_SAMPLE_DEG)))
    points = [curve["start"]]
    for k in range(1, steps):
        points.append(vec.rotate(curve["start"], normal, math.degrees(turn) * k / steps, centre))
    points.append(curve["end"])
    return points


def curve_length(curve):
    if curve["kind"] == "arc":
        _, radius, _, turn = arc_of(curve)
        return radius * turn
    points = polyline(curve)
    return sum(vec.length(vec.sub(b, a)) for a, b in zip(points, points[1:]))


def chain(curves):
    """`(ordered, closed)`: the curves ordered and oriented end to end, or None when they do not form one chain
    (a gap, a branch or two pieces). An open chain starts at the free end of the earliest curve in the list; a
    closed one (a ring of curves) at the start of the first curve."""
    nodes, ends = [], []
    for curve in curves:
        pair = []
        for point in (curve["start"], curve["end"]):
            at = next((n for n, node in enumerate(nodes) if near(node, point)), None)
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
        ordered.append(curves[found] if forward else flip(curves[found]))
        at = ends[found][1] if forward else ends[found][0]
    return ordered, closed


def turned_round(curves):
    """The chain run from its other end."""
    return [flip(c) for c in reversed(curves)]


def turn_deg(a, b):
    """The angle in degrees between two unit directions."""
    return math.degrees(math.atan2(vec.length(vec.cross(a, b)), vec.dot(a, b)))


def joined_lines(ordered):
    """The chain with neighbouring lines that continue straight written as one line."""
    out = []
    for curve in ordered:
        if out and out[-1]["kind"] == curve["kind"] == "line" \
                and turn_deg(tangents(out[-1])[1], tangents(curve)[0]) <= STRAIGHT_DEG:
            out[-1] = dict(out[-1], end=curve["end"])
        else:
            out.append(curve)
    return out


def round_point(p):
    return [round9(x) for x in p]


def round_point2(p):
    return [round9(p[0]), round9(p[1])]


def points_along(curves):
    """Points along a chain of curves, in order (arcs every few degrees, free curves by their samples)."""
    return [p for curve in curves for p in polyline(curve)]


def turn_degrees(arc):
    """The angle in degrees an arc turns from its start through its middle to its end."""
    return math.degrees(arc_of(arc)[3])


def swept_degrees(arc):
    """The angle in degrees an arc (`start`, `mid`, `end`, `center` in 2D) turns from its start through its middle to
    its end, read from the points of the capture."""
    a, m, e = ([arc[k][c] - arc["center"][c] for c in range(2)] for k in ("start", "mid", "end"))

    def turn(u, v):
        return math.atan2(u[0] * v[1] - u[1] * v[0], u[0] * v[0] + u[1] * v[1])

    return math.degrees(abs(turn(a, m)) + abs(turn(m, e)))


def tightest_radius(curves):
    """The radius of the tightest arc of a chain of lines and arcs (infinity when it has none)."""
    return min([arc_of(c)[1] for c in curves if c["kind"] == "arc"] or [math.inf])
