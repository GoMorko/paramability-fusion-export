"""Whether the outline of a sweep can outgrow the tightest bend of its path as sizes change.

The path planner refuses an outline that reaches as far from the path as its tightest bend's radius at the captured
sizes. The written outline follows sizes, so at other values it can reach past that radius, which the app refuses.
`outgrown_reads` tests the written outer loop at the settings `range_check` builds and names the sizes behind it when
any setting reaches too far.
"""
import math

from ...params.expressions.errors import ExpressionError
from ..ranges import range_check
from ..paths.path_limits import REACH_SHARE
from ..sketch.written_loops import (
    point as _point, rect_corners as _corners, spline_points as _spline_points, value as _value, written_reads,
)

ARC_STEPS = 16      # points per arc, as the app samples an arc of an outline


def _arc_points(a, b, c):
    """Points along the arc from `a` through `b` to `c`, both ends included, as the app samples it; the chord when the
    three are in a line."""
    d = 2.0 * (a[0] * (b[1] - c[1]) + b[0] * (c[1] - a[1]) + c[0] * (a[1] - b[1]))
    if abs(d) < 1e-12:
        return [a, c]
    a2, b2, c2 = (p[0] * p[0] + p[1] * p[1] for p in (a, b, c))
    centre = [(a2 * (b[1] - c[1]) + b2 * (c[1] - a[1]) + c2 * (a[1] - b[1])) / d,
              (a2 * (c[0] - b[0]) + b2 * (a[0] - c[0]) + c2 * (b[0] - a[0])) / d]
    radius = math.hypot(a[0] - centre[0], a[1] - centre[1])
    start = math.atan2(a[1] - centre[1], a[0] - centre[0])
    end = math.atan2(c[1] - centre[1], c[0] - centre[0])
    counter = (b[0] - a[0]) * (c[1] - b[1]) - (b[1] - a[1]) * (c[0] - b[0]) > 0
    full = 2.0 * math.pi
    sweep = (end - start) % full if counter else -((start - end) % full)
    return [a] + [[centre[0] + radius * math.cos(start + sweep * i / ARC_STEPS),
                   centre[1] + radius * math.sin(start + sweep * i / ARC_STEPS)] for i in range(1, ARC_STEPS)] + [c]


def reach_of(loop, env, start, across=None, toward=None):
    """How far a written loop reaches from `start` (2D, the outline's frame): the loop's farthest point, or for a
    loop of lines, arcs and splines its farthest point, with the arcs and splines sampled as the app does. With `across` (a 2D unit direction) only the
    reach along the direction square to it counts: a flat path bends in the plane square to `across`, so the outline
    reaches toward a bend's centre only that way. With `toward` (a 2D unit direction) only the reach in that direction
    counts, and a point on the other side counts negative: an outline beside a revolved arc reaches the axis only
    toward it."""
    def away(point):
        d = [point[0] - start[0], point[1] - start[1]]
        if toward is not None:
            return d[0] * toward[0] + d[1] * toward[1]
        if across is not None:
            along = d[0] * across[0] + d[1] * across[1]
            d = [d[0] - along * across[0], d[1] - along * across[1]]
        return math.hypot(d[0], d[1])

    kind = loop["kind"]
    if kind in ("circle", "ellipse"):
        radius = (_value(loop["radius"], env) if kind == "circle"
                  else max(_value(loop["radiusX"], env), _value(loop["radiusY"], env)))
        return away(_point(loop["center"], env)) + radius
    if kind == "rect":
        return max(away(p) for p in _corners(loop, env))
    if kind == "polygon":
        return max(away(_point(p, env)) for p in loop["points"])
    points = [_point(loop["start"], env)]
    for segment in loop["segments"]:
        to = _point(segment["to"], env)
        if segment["kind"] == "arc":
            points += _arc_points(points[-1], _point(segment["through"], env), to)[1:]
        elif segment["kind"] == "spline":
            through = [_point(p, env) for p in segment.get("through") or []]
            points += _spline_points([points[-1]] + through + [to])[1:]
        else:
            points.append(to)
    return max(away(p) for p in points)


def outgrown_reads(table, loop, start, limit):
    """The Fusion names of the sizes behind the written outer `loop` when some setting of them makes it reach `limit`
    (the radius of the path's tightest bend) from `start`, else an empty tuple. A loop that cannot be worked out at
    some setting counts as one that can."""
    reads = written_reads(loop)
    if not reads or limit == math.inf:
        return ()
    try:
        for setting in range_check.corners(table, reads):
            if reach_of(loop, range_check.size_env(table, setting), start) >= limit * REACH_SHARE:
                return reads
    except (ExpressionError, KeyError, TypeError, ValueError, ZeroDivisionError):
        return reads
    return ()
