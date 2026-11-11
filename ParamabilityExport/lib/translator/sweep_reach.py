"""Whether the outline of a sweep can outgrow the tightest bend of its path as sizes change.

The path planner refuses an outline that reaches as far from the path as its tightest bend's radius at the captured
sizes. The written outline follows sizes, so at other values it can reach past that radius, which the app refuses.
`outgrown_reads` tests the written outer loop at the settings `range_check` builds and names the sizes behind it when
any setting reaches too far.
"""
import math

from ..params.expressions import ExpressionError, evaluate
from . import range_check
from .paths import REACH_SHARE


def _value(node, env):
    return evaluate(node["expr"], env) if isinstance(node, dict) else float(node)


def _point(point, env):
    return [_value(point[0], env), _value(point[1], env)]


def _reads(node, found):
    """The Fusion names of every size a written value reads."""
    if isinstance(node, dict):
        found.extend(getattr(node, "reads", ()))
        for value in node.values():
            _reads(value, found)
    elif isinstance(node, list):
        for value in node:
            _reads(value, found)
    return tuple(dict.fromkeys(found))


def _corners(loop, env):
    """The four corners of a rect loop, turned by its angle."""
    cx, cy = _point(loop["center"], env)
    half_w, half_h = _value(loop["width"], env) / 2.0, _value(loop["height"], env) / 2.0
    angle = math.radians(_value(loop.get("angleDeg", 0.0), env))
    c, s = math.cos(angle), math.sin(angle)
    return [[cx + c * x - s * y, cy + s * x + c * y] for x in (-half_w, half_w) for y in (-half_h, half_h)]


def _reach(loop, env, start):
    """How far a written loop reaches from `start` (2D, the outline's frame): the loop's farthest point, or for a
    loop of lines, arcs and splines its farthest end or through point."""
    def away(point):
        return math.dist(point, start)

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
        points += [_point(p, env) for p in segment.get("through") or []] + [_point(segment["to"], env)]
    return max(away(p) for p in points)


def outgrown_reads(table, loop, start, limit):
    """The Fusion names of the sizes behind the written outer `loop` when some setting of them makes it reach `limit`
    (the radius of the path's tightest bend) from `start`, else an empty tuple. A loop that cannot be worked out at
    some setting counts as one that can."""
    reads = _reads(loop, [])
    if not reads or limit == math.inf:
        return ()
    try:
        for setting in range_check.corners(table, reads):
            if _reach(loop, range_check.size_env(table, setting), start) >= limit * REACH_SHARE:
                return reads
    except (ExpressionError, KeyError, TypeError, ValueError, ZeroDivisionError):
        return reads
    return ()
