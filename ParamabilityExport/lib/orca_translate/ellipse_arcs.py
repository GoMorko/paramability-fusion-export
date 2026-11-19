"""An elliptical arc of a sketch outline as an Orca elliptical arc entity, exactly.

Fusion gives an elliptical arc of an outline as a rational B-spline of degree two (`nurbs` of a capture curve). Each
span of such a curve is a conic: a rational Bezier piece with poles P0, P1, P2 and weights w0, w1, w2. With the
weights scaled so that w0 = w2 = 1 (`w` is then w1 over the root of w0 times w2), the piece is an arc of an ellipse
when `w` lies between 0 and 1: its centre is O = (M - w^2 P1) / (1 - w^2) (M is the middle of P0 and P2), and with
a = w (P1 - O) and b = (P2 - P0) / (2 root(1 - w^2)) the points are O + a cos t + b sin t for t from minus to plus
the half sweep acos(w). The principal axes of that pair of conjugate half diameters give the centre, the radii and
the direction of the major axis. The sweep of the piece is twice acos(w), counter clockwise or clockwise as a x b is
positive or negative.

Orca draws the entity (`SketchEngine::entities_to_wires`, `make_elips`) counter clockwise from `start_angle` to
`end_angle`, both parametric angles in the frame of the major axis, with `radius` the major radius. A curve that runs
clockwise in the sketch is written with its two ends swapped.

Left as None (the outline stays out of the copy): a curve that is not rational, of degree other than two, closed, or
with a span that is not an ellipse arc; spans that are not arcs of one ellipse; ends or measured points (`samples`)
that the entity does not give within the tolerances below.
"""
import math

from ..orca_recipe.enums import EntityType
from ..orca_recipe.sketch import SketchEntity
from . import splines

# The entity's ends must be this close (mm) to the ends the capture measured.
END_TOL = 1e-6
# Spans of one curve must give the same centre and radii within this (mm), and measured points lie this close (mm).
SPAN_TOL = 1e-6
SAMPLE_TOL = 1e-4
# A measured point may lie this far (radians) outside the arc's angles.
ANGLE_TOL = 1e-6
_MIN_SAMPLES = 3


def _piece(poles):
    """`(centre, a, b, half_sweep)` of one rational Bezier piece (poles of x w, y w, w), or None when it is not an arc
    of an ellipse. `a` and `b` are the conjugate half diameters."""
    (x0, y0, w0), (x1, y1, w1), (x2, y2, w2) = poles
    if min(w0, w1, w2) <= 0:
        return None
    p0, p1, p2 = (x0 / w0, y0 / w0), (x1 / w1, y1 / w1), (x2 / w2, y2 / w2)
    w = w1 / math.sqrt(w0 * w2)
    if not 0 < w < 1 - 1e-9:
        return None
    mid = ((p0[0] + p2[0]) / 2.0, (p0[1] + p2[1]) / 2.0)
    centre = tuple((m - w * w * q) / (1 - w * w) for m, q in zip(mid, p1))
    a = tuple(w * (q - c) for q, c in zip(p1, centre))
    root = math.sqrt(1 - w * w)
    b = ((p2[0] - p0[0]) / (2 * root), (p2[1] - p0[1]) / (2 * root))
    return centre, a, b, math.acos(w)


def _axes(a, b):
    """`(radius, minor radius, direction)` of the ellipse O + a cos t + b sin t: the principal axes of the pair of
    conjugate half diameters, or None when it has no area."""
    aa, bb, ab = a[0] * a[0] + a[1] * a[1], b[0] * b[0] + b[1] * b[1], a[0] * b[0] + a[1] * b[1]
    spread = math.hypot((aa - bb) / 2.0, ab)
    big, small = (aa + bb) / 2.0 + spread, (aa + bb) / 2.0 - spread
    if small <= 1e-12:
        return None
    t = math.atan2(ab, (aa - bb) / 2.0) / 2.0
    major = (a[0] * math.cos(t) + b[0] * math.sin(t), a[1] * math.cos(t) + b[1] * math.sin(t))
    size = math.hypot(*major)
    return math.sqrt(big), math.sqrt(small), (major[0] / size, major[1] / size)


def _unit(point, centre, major, minor, direction):
    """A point of the plane in the frame of the ellipse, scaled by its radii: (cos t, sin t) when it lies on it."""
    dx, dy = point[0] - centre[0], point[1] - centre[1]
    return ((dx * direction[0] + dy * direction[1]) / major, (-dx * direction[1] + dy * direction[0]) / minor)


def _angle(point, centre, major, minor, direction):
    """The parametric angle of a point on the ellipse."""
    c, s = _unit(point, centre, major, minor, direction)
    return math.atan2(s, c)


def _on(centre, major, minor, direction, angle):
    c, s = major * math.cos(angle), minor * math.sin(angle)
    return (centre[0] + c * direction[0] - s * direction[1], centre[1] + c * direction[1] + s * direction[0])


def entity(curve):
    """The Orca elliptical arc entity for a capture curve of kind `other` with its `nurbs` (sketch 2D mm), or None."""
    nurbs = curve.get("nurbs")
    if not isinstance(nurbs, dict) or not nurbs.get("rational") or nurbs.get("degree") != 2:
        return None
    start, end, samples = curve.get("start"), curve.get("end"), curve.get("samples") or []
    if not start or not end or len(samples) < _MIN_SAMPLES or curve.get("truncated"):
        return None
    try:
        weights = [float(w) for w in nurbs["weights"]]
        homogeneous = [(float(p[0]) * w, float(p[1]) * w, w) for p, w in zip(nurbs["poles"], weights)]
        if len(homogeneous) != len(nurbs["poles"]):
            return None
        pieces = splines.bezier_pieces(dict(nurbs, poles=homogeneous, rational=False))
    except (KeyError, TypeError, ValueError, IndexError):
        return None
    if not pieces:
        return None
    found = [_piece(p) for p in pieces]
    if any(f is None for f in found):
        return None
    centre, a, b, _ = found[0]
    axes = _axes(a, b)
    if axes is None:
        return None
    major, minor, direction = axes
    turn = 0.0
    signs = set()
    for c, pa, pb, half in found:
        other = _axes(pa, pb)
        if other is None or math.dist(c, centre) > SPAN_TOL or abs(other[0] - major) > SPAN_TOL \
                or abs(other[1] - minor) > SPAN_TOL:
            return None
        if major - minor > SPAN_TOL and abs(other[2][0] * direction[1] - other[2][1] * direction[0]) > SPAN_TOL / major:
            return None
        sign = 1.0 if pa[0] * pb[1] - pa[1] * pb[0] > 0 else -1.0
        signs.add(sign)
        turn += sign * 2.0 * half
    if len(signs) != 1 or abs(turn) >= 2 * math.pi - 1e-9:
        return None
    first = _angle(start, centre, major, minor, direction)
    # The arc as Orca draws it: counter clockwise from `lo` to `lo + sweep`.
    lo, sweep = (first, turn) if turn > 0 else (first + turn, -turn)
    p0, p1 = (start, end) if turn > 0 else (end, start)
    if math.dist(_on(centre, major, minor, direction, lo), p0) > END_TOL or \
            math.dist(_on(centre, major, minor, direction, lo + sweep), p1) > END_TOL:
        return None
    for p in samples:
        ratio = math.hypot(*_unit(p, centre, major, minor, direction))
        if abs(ratio - 1.0) * min(major, minor) > SAMPLE_TOL:
            return None
        inside = (_angle(p, centre, major, minor, direction) - lo) % (2 * math.pi)
        if inside > sweep + ANGLE_TOL and 2 * math.pi - inside > ANGLE_TOL:
            return None
    return SketchEntity(type=EntityType.ELLIPSE_ARC, center=tuple(centre), p0=(float(p0[0]), float(p0[1])),
                        p1=(float(p1[0]), float(p1[1])), radius=major, rminor=minor,
                        rotation=math.atan2(direction[1], direction[0]), start_angle=lo, end_angle=lo + sweep)

