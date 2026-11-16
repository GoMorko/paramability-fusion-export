"""Corners inside a spline, read from its definition. Pure: no Fusion imports.

A spline (`nurbs` of a capture curve: `degree`, the full knot vector `knots`, `poles`, and `weights` that do not
change directions) is smooth everywhere except where an inner knot repeats as many times as the degree: there the
curve passes through one pole and may leave it in another direction. Every inner knot of a degree one spline is such
a joint, so a polyline drawn as a spline has a corner at each pole where it turns. At such a joint the curve arrives
along the line from the pole before and leaves along the line to the pole after (the nearest poles that differ from
it), with or without weights.

`joint_turns` gives the turn at each of these joints. A copy that cannot have a corner on its own inside a curve (a
sweep path, which fits a smooth curve through the spline) reads it to leave such a curve out.
"""
import math

# Knots this close (a share of the knot range) count as one; poles this close (mm) as one.
_KNOT_TOL = 1e-12
_POLE_TOL = 1e-9


def _usable(nurbs):
    """`(degree, knots, poles)` of a definition whose knot vector fits its poles, else None."""
    try:
        degree = int(nurbs["degree"])
        knots = [float(k) for k in nurbs["knots"]]
        poles = [(float(p[0]), float(p[1])) + ((float(p[2]),) if len(p) > 2 else ()) for p in nurbs["poles"]]
    except (KeyError, TypeError, ValueError, IndexError):
        return None
    if degree < 1 or len(poles) < degree + 1 or len(knots) != len(poles) + degree + 1:
        return None
    if any(b < a for a, b in zip(knots, knots[1:])) or knots[-1] - knots[0] <= 0:
        return None
    return degree, knots, poles


def _direction(poles, at, step):
    """The direction from pole `at` to the nearest pole along `step` (+1 or -1) that differs from it, or None."""
    n = at + step
    while 0 <= n < len(poles):
        d = [b - a for a, b in zip(poles[at], poles[n])]
        if math.sqrt(sum(c * c for c in d)) > _POLE_TOL:
            return d
        n += step
    return None


def _angle(a, b):
    """Degrees between two directions (2D or 3D)."""
    dot = sum(x * y for x, y in zip(a, b))
    if len(a) == 2:
        cross = abs(a[0] * b[1] - a[1] * b[0])
    else:
        c = (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])
        cross = math.sqrt(sum(x * x for x in c))
    return math.degrees(math.atan2(cross, dot))


def joint_turns(nurbs):
    """The turn (degrees) at each inner knot of the spline `nurbs` that repeats as many times as its degree, in order
    along the curve (a joint with no pole that differs on one side is passed by). None when the definition cannot be
    read, or when an inner knot repeats more often than the degree (the curve breaks there)."""
    found = _usable(nurbs) if isinstance(nurbs, dict) else None
    if found is None:
        return None
    degree, knots, poles = found
    low, high = knots[degree], knots[-degree - 1]
    tol = _KNOT_TOL * (knots[-1] - knots[0])
    turns, k = [], 0
    while k < len(knots):
        last = k
        while last + 1 < len(knots) and knots[last + 1] - knots[k] <= tol:
            last += 1
        u, count = knots[k], last - k + 1
        if low + tol < u < high - tol and count >= degree:
            if count > degree:
                return None
            at = last - degree
            before, after = _direction(poles, at, -1), _direction(poles, at, 1)
            if before is not None and after is not None:
                turns.append(_angle([-c for c in before], after))
        k = last + 1
    return turns
