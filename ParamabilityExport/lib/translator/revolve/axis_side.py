"""The outline of a revolve stays on one side of its axis over the size ranges.

Fusion turns a one sided revolve toward one side of the sketch plane. When a size moves the axis (or the outline) so
that the outline reaches the axis or passes to its other side, Fusion keeps turning toward the same side of the plane,
so the turn about the axis reverses (or the step builds with a warning while the outline crosses the axis). The
recipe writes one fixed turn about the axis, and the app refuses an outline that crosses it. A copy is right only
while the outline stays on the side of the axis it is on now.

`keep_side` works out each written revolve step (its outline and axis point as numbers or formulas) at the size
settings over the ranges of the sizes they read: the ends and corners of the ranges (`range_check.corners`), and
inner settings too when a formula is more than sums and products (`range_check.needs_inner`). Where the outline would
reach the axis, the ranges are cut to just before that (`kept_ranges.holding_ranges_where`); the outline moves
straight with the sizes in most designs, and the halvings then find that place to the form's step. An outline that
touches the axis now (a vase drawn from its centre line) may stay on it, but not pass it. When no shorter ranges keep
the outline on its side (every size read has a range the person typed), the step is left out.
"""
import math

from ...capture_model import gap_hints
from ...geometry.footprint import arc_span, is_full
from ..ranges import kept_ranges, range_check
from ..result import Refusal
from ..sketch.written_loops import curves_at, point, written_reads

# How close (mm) the outline may come to the axis and still count as off it, and how far it may reach across it.
SIDE_TOL_MM = 1e-4
_FAILURES = (ArithmeticError, ValueError, KeyError, TypeError)


def _along(curve, n):
    """(lowest, highest) of p . n over a capture curve (sketch 2D mm)."""
    kind = curve["kind"]
    if kind == "line":
        values = [curve["start"][0] * n[0] + curve["start"][1] * n[1],
                  curve["end"][0] * n[0] + curve["end"][1] * n[1]]
        return min(values), max(values)
    if kind == "ellipse":
        c, d = curve["center"], curve["major_dir"]
        size = math.hypot(d[0], d[1]) or 1.0
        u = (d[0] / size, d[1] / size)
        a = curve["major_radius"] * (u[0] * n[0] + u[1] * n[1])
        b = curve["minor_radius"] * (-u[1] * n[0] + u[0] * n[1])
        mid, half = c[0] * n[0] + c[1] * n[1], math.hypot(a, b)
        return mid - half, mid + half
    if kind in ("circle", "arc"):
        c, r = curve["center"], curve["radius"]
        mid = c[0] * n[0] + c[1] * n[1]
        if kind == "circle" or is_full(curve):
            return mid - r, mid + r
        values = [curve["start"][0] * n[0] + curve["start"][1] * n[1],
                  curve["end"][0] * n[0] + curve["end"][1] * n[1]]
        start, sweep = arc_span(curve)
        toward = math.atan2(n[1], n[0])
        for angle, value in ((toward, mid + r), (toward + math.pi, mid - r)):
            past = (angle - start) % (2.0 * math.pi) if sweep >= 0 else (start - angle) % (2.0 * math.pi)
            if past <= abs(sweep):
                values.append(value)
        return min(values), max(values)
    points = curve.get("samples") or []
    values = [p[0] * n[0] + p[1] * n[1] for p in points]
    return (min(values), max(values)) if values else (0.0, 0.0)


def _reach(outer, axis_point, axis_dir, env):
    """(lowest, highest) distance of the outline from the axis, across it (positive to the left of `axis_dir`), at
    `env`."""
    size = math.hypot(axis_dir[0], axis_dir[1])
    n = (-axis_dir[1] / size, axis_dir[0] / size)
    at = point(axis_point, env)
    base = at[0] * n[0] + at[1] * n[1]
    spans = [_along(c, n) for c in curves_at(outer, env)]
    return min(s[0] for s in spans) - base, max(s[1] for s in spans) - base


class _Side:
    """One written revolve step: the side of the axis its outline is on now, and whether it touches the axis now."""

    def __init__(self, step, env):
        self.outer, self.axis = step["sketch"]["outer"], step["axis"]
        low, high = _reach(self.outer, self.axis["point"], self.axis["dir"], env)
        self.side = 1 if low >= -SIDE_TOL_MM and high > SIDE_TOL_MM else (
            -1 if high <= SIDE_TOL_MM and low < -SIDE_TOL_MM else 0)
        self.touches = (low if self.side > 0 else -high) <= SIDE_TOL_MM

    def holds(self, env):
        """True when the outline is on its side at `env` (on the axis only where it touches it now)."""
        low, high = _reach(self.outer, self.axis["point"], self.axis["dir"], env)
        near = low if self.side > 0 else -high
        return near >= -SIDE_TOL_MM if self.touches else near > SIDE_TOL_MM


def _settings(table, reads, bounds, only, inner):
    if only is not None:
        return [{only[0]: bounds[only[0]][only[1]]}]
    out = range_check.corners(table, reads, bounds)
    return out + range_check.inner_settings(table, reads, bounds) if inner else out


def keep_side(ctx, item, steps):
    """Cut the ranges so the outline of each written revolve step in `steps` stays on its side of the axis; None when
    it does (or nothing moves), a Refusal when no cut keeps it there."""
    if ctx.table is None:
        return None
    checked = [s for s in steps if s.get("kind") == "revolve" and written_reads(s["sketch"]["outer"], s["axis"])]
    if not checked:
        return None
    reads = written_reads(*[[s["sketch"]["outer"], s["axis"]] for s in checked])
    try:
        now = range_check.recipe_size_values(ctx.table, {})
        sides = [_Side(s, now) for s in checked]
    except _FAILURES:
        return None
    sides = [s for s in sides if s.side]
    if not sides:
        return None
    inner = any(range_check.needs_inner(text) for text in _formulas([[s.outer, s.axis] for s in sides]))

    def holds(bounds, only=None):
        try:
            for setting in _settings(ctx.table, reads, bounds, only, inner):
                env = range_check.recipe_size_values(ctx.table, setting)
                if not all(s.holds(env) for s in sides):
                    return False
        except _FAILURES:
            return False
        return True

    found = kept_ranges.holding_ranges_where(ctx.table, reads, holds)
    if found is None:
        return Refusal("The outline of this revolve would reach or cross its axis at other sizes, and the copy "
                       "cannot follow that.", cause=gap_hints.REVOLVE_AXIS_SIDE)
    if found:
        ctx.cut(found, "the outline of %s would reach its axis" % item.get("name", "a revolve"))
    return None


def _formulas(node, out=None):
    """The formula texts of the written values in `node`."""
    out = [] if out is None else out
    if isinstance(node, dict):
        if isinstance(node.get("expr"), str):
            out.append(node["expr"])
        for value in node.values():
            _formulas(value, out)
    elif isinstance(node, list):
        for value in node:
            _formulas(value, out)
    return out
