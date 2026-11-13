"""A loop as the recipe writes it (`rect`, `circle`, `ellipse`, `polygon`, `profile`; numbers or `{ "expr" }`
formulas), worked out at one size setting.

`env` holds the size values by recipe name (`range_check.size_env`). `curves_at` gives the loop as capture curves
(sketch 2D mm), so the checks made on captured outlines (`footprint.Footprint`) run on it at other sizes too.
"""
import math

from ..params.expressions import evaluate
from . import spline_fit

SPLINE_STEPS = 16   # readings of a fitted spline between two of its points
_LINE_TOL = 1e-12


def value(node, env):
    """A written number or formula at `env`."""
    return evaluate(node["expr"], env) if isinstance(node, dict) else float(node)


def point(node, env):
    return [value(node[0], env), value(node[1], env)]


def _reads(node, found):
    if isinstance(node, dict):
        found.extend(getattr(node, "reads", ()))
        for item in node.values():
            _reads(item, found)
    elif isinstance(node, list):
        for item in node:
            _reads(item, found)
    return found


def written_reads(*loops):
    """The Fusion names of every size the written `loops` read."""
    return tuple(dict.fromkeys(_reads(list(loops), [])))


def rect_corners(loop, env):
    """The four corners of a rect loop, turned by its angle: (-w, -h), (-w, h), (w, -h), (w, h)."""
    cx, cy = point(loop["center"], env)
    half_w, half_h = value(loop["width"], env) / 2.0, value(loop["height"], env) / 2.0
    angle = math.radians(value(loop.get("angleDeg", 0.0), env))
    c, s = math.cos(angle), math.sin(angle)
    return [[cx + c * x - s * y, cy + s * x + c * y] for x in (-half_w, half_w) for y in (-half_h, half_h)]


def spline_points(points):
    """Points along the app's curve through `points` (the chords when it cannot be fitted)."""
    curve = spline_fit.interpolate(points)
    if curve is None:
        return points
    steps = SPLINE_STEPS * (len(points) - 1)
    return [curve.at(i / steps) for i in range(steps + 1)]


def _line(a, b):
    return {"kind": "line", "start": a, "end": b}


def _arc(a, b, c):
    """The capture arc from `a` through `b` to `c`, or the chord when the three are in a line."""
    d = 2.0 * (a[0] * (b[1] - c[1]) + b[0] * (c[1] - a[1]) + c[0] * (a[1] - b[1]))
    if abs(d) < _LINE_TOL:
        return _line(a, c)
    a2, b2, c2 = (p[0] * p[0] + p[1] * p[1] for p in (a, b, c))
    centre = [(a2 * (b[1] - c[1]) + b2 * (c[1] - a[1]) + c2 * (a[1] - b[1])) / d,
              (a2 * (c[0] - b[0]) + b2 * (a[0] - c[0]) + c2 * (b[0] - a[0])) / d]
    return {"kind": "arc", "start": a, "mid": b, "end": c, "center": centre,
            "radius": math.hypot(a[0] - centre[0], a[1] - centre[1])}


def _closed(points):
    return [_line(a, b) for a, b in zip(points, points[1:] + points[:1])]


def curves_at(loop, env):
    """The capture curves of a written loop at `env`. Raises when a formula cannot be worked out there."""
    kind = loop["kind"]
    if kind == "circle":
        return [{"kind": "circle", "center": point(loop["center"], env), "radius": value(loop["radius"], env)}]
    if kind == "ellipse":
        angle = math.radians(value(loop.get("angleDeg", 0.0), env))
        return [{"kind": "ellipse", "center": point(loop["center"], env), "major_dir": [math.cos(angle),
                                                                                       math.sin(angle)],
                 "major_radius": value(loop["radiusX"], env), "minor_radius": value(loop["radiusY"], env)}]
    if kind == "rect":
        low_low, low_high, high_low, high_high = rect_corners(loop, env)
        return _closed([low_low, low_high, high_high, high_low])
    if kind == "polygon":
        return _closed([point(p, env) for p in loop["points"]])
    at, out = point(loop["start"], env), []
    for segment in loop["segments"]:
        to = point(segment["to"], env)
        if segment["kind"] == "arc":
            out.append(_arc(at, point(segment["through"], env), to))
        elif segment["kind"] == "spline":
            through = spline_points([at] + [point(p, env) for p in segment.get("through") or []] + [to])
            out += [_line(a, b) for a, b in zip(through, through[1:])]
        else:
            out.append(_line(at, to))
        at = to
    return out


def profile_at(outer, inners, env):
    """A capture profile (`{ loops: [{ curves }] }`, outer first) of written loops at `env`."""
    return {"loops": [{"curves": curves_at(loop, env)} for loop in [outer] + list(inners)]}
