"""Sketch splines as Orca B-spline entities, exactly.

Orca's B-spline entity (`SketchEngine::entities_to_wires`, `make_bspline`) is clamped and uniform, of degree three
(fewer poles: one less than the poles), with no weights. A Fusion spline (`nurbs` of a capture curve: degree, knots,
poles and weights from `NurbsCurve3D.getData`) usually has other knots, so it is not one Orca entity. But a curve of
degree three or less without weights is, piece by piece, exactly a run of Bezier curves (the knots inserted until
each has the full count), and a Bezier curve of 4 poles (3, 2) is Orca's entity of 4 poles (3; 2 is a line). So the
copy writes one entity per piece, the same curve with no approximation.

Left as None (the outline stays out of the copy): a closed (periodic) spline, a rational one with weights that
differ, a degree over three, knots that are not clamped at both ends, and a curve whose pieces do not pass through
the points Fusion measured along it (`samples`), which catches a definition read wrong.

A spline may turn at a joint of its pieces: an inner knot as many times as the degree (three times in a cubic, every
inner knot of a degree one spline) lets the curve leave the joint in another direction. Orca draws the same corner,
so an outline keeps it; `joint_turns` gives these turns to a copy that must not have corners (a sweep path).
"""
import math

from ..orca_recipe.enums import EntityType
from ..orca_recipe.sketch import SketchEntity

# The measured points must lie this close (mm) to the curve the pieces draw, and the ends this close.
SAMPLE_TOL = 2e-3
END_TOL = 1e-4
# Points per piece when the pieces are drawn for that check.
_DRAW = 32
# Narrowing steps when the nearest point of a piece is looked for.
_NARROW = 40
_KNOT_TOL = 1e-12
# Two poles this close (mm) count as one when the direction a piece leaves a pole in is read.
_POLE_TOL = 1e-12
_WEIGHT_TOL = 1e-9


def _usable(nurbs):
    """`(degree, knots, poles)` of a spline Orca can draw piece by piece, or None."""
    if not isinstance(nurbs, dict) or nurbs.get("periodic") is not False:
        return None
    try:
        degree = int(nurbs["degree"])
        knots = [float(k) for k in nurbs["knots"]]
        poles = [(float(p[0]), float(p[1])) for p in nurbs["poles"]]
    except (KeyError, TypeError, ValueError, IndexError):
        return None
    if not 1 <= degree <= 3 or len(poles) < degree + 1 or len(knots) != len(poles) + degree + 1:
        return None
    if any(b < a for a, b in zip(knots, knots[1:])) or knots[-1] - knots[0] <= _KNOT_TOL:
        return None
    if nurbs.get("rational"):
        weights = nurbs.get("weights") or []
        if len(weights) != len(poles) or any(abs(w - weights[0]) > _WEIGHT_TOL * abs(weights[0]) for w in weights):
            return None
    span = knots[-1] - knots[0]
    if any(abs(k - knots[0]) > _KNOT_TOL * span for k in knots[:degree + 1]) or \
            any(abs(k - knots[-1]) > _KNOT_TOL * span for k in knots[-degree - 1:]):
        return None
    inner = knots[degree + 1:-degree - 1]
    if any(sum(1 for k in inner if abs(k - u) <= _KNOT_TOL * span) > degree for u in inner):
        return None  # a break in the curve
    return degree, knots, poles


def _insert(degree, knots, poles, u):
    """The knots and poles with the knot `u` inserted once (Boehm)."""
    k = max(i for i in range(len(knots) - 1) if knots[i] <= u < knots[i + 1])
    out = []
    for i in range(len(poles) + 1):
        if i <= k - degree:
            out.append(poles[i])
        elif i > k:
            out.append(poles[i - 1])
        else:
            a = (u - knots[i]) / (knots[i + degree] - knots[i])
            out.append(((1 - a) * poles[i - 1][0] + a * poles[i][0], (1 - a) * poles[i - 1][1] + a * poles[i][1]))
    return knots[:k + 1] + [u] + knots[k + 1:], out


def bezier_pieces(nurbs):
    """The pole lists of the Bezier pieces of a spline, in order (each `degree + 1` poles), or None when Orca cannot
    draw it exactly."""
    found = _usable(nurbs)
    if found is None:
        return None
    degree, knots, poles = found
    span = knots[-1] - knots[0]
    inner = sorted({k for k in knots[degree + 1:-degree - 1]})
    for u in inner:
        while sum(1 for k in knots if abs(k - u) <= _KNOT_TOL * span) < degree:
            knots, poles = _insert(degree, knots, poles, u)
    # After the inserts each distinct knot span is one Bezier piece: its poles start every `degree` poles.
    pieces = []
    distinct = [knots[0]] + inner + [knots[-1]]
    for n in range(len(distinct) - 1):
        piece = poles[n * degree:n * degree + degree + 1]
        if len(piece) == degree + 1:
            pieces.append(piece)
    if len(pieces) != len(distinct) - 1:
        return None
    return pieces


def _leaving(poles):
    """The direction a Bezier piece leaves its first pole in: toward the first pole that differs from it, or None."""
    for p in poles[1:]:
        if math.dist(p, poles[0]) > _POLE_TOL:
            return (p[0] - poles[0][0], p[1] - poles[0][1])
    return None


def joint_turns(nurbs):
    """The turn (degrees) at each joint between the Bezier pieces of a spline, in order (pieces of no length passed
    by), or None when Orca cannot draw the spline exactly."""
    pieces = bezier_pieces(nurbs)
    if not pieces:
        return None
    turns, arriving = [], None
    for piece in pieces:
        leaving = _leaving(piece)
        if leaving is None:
            continue
        if arriving is not None:
            cross = arriving[0] * leaving[1] - arriving[1] * leaving[0]
            turns.append(math.degrees(math.atan2(abs(cross), arriving[0] * leaving[0] + arriving[1] * leaving[1])))
        back = _leaving(list(reversed(piece)))
        arriving = (-back[0], -back[1])
    return turns


def _bezier(piece, t):
    points = list(piece)
    while len(points) > 1:
        points = [((1 - t) * a[0] + t * b[0], (1 - t) * a[1] + t * b[1]) for a, b in zip(points, points[1:])]
    return points[0]


def _nearest(piece, p, t0, t1):
    """The distance from `p` to the piece between parameters `t0` and `t1` (one bend at most), by narrowing."""
    def gap(t):
        q = _bezier(piece, t)
        return math.hypot(p[0] - q[0], p[1] - q[1])

    for _ in range(_NARROW):
        a, b = t0 + (t1 - t0) / 3.0, t1 - (t1 - t0) / 3.0
        if gap(a) < gap(b):
            t1 = b
        else:
            t0 = a
    return gap((t0 + t1) / 2.0)


def _matches(pieces, curve):
    """True when the pieces start and end where the capture curve does and pass through its measured points."""
    start, end, samples = curve.get("start"), curve.get("end"), curve.get("samples") or []
    if not start or not end or len(samples) < 2 or curve.get("truncated"):
        return False
    if math.dist(pieces[0][0], start) > END_TOL or math.dist(pieces[-1][-1], end) > END_TOL:
        return False
    drawn = [(n, k, _bezier(piece, k / _DRAW)) for n, piece in enumerate(pieces) for k in range(_DRAW + 1)]
    for p in samples:
        n, k, _ = min(drawn, key=lambda d: (d[2][0] - p[0]) ** 2 + (d[2][1] - p[1]) ** 2)
        near = [(n, k)]
        if k == _DRAW and n + 1 < len(pieces):
            near.append((n + 1, 0))  # the nearest drawn point is a joint: the next piece may hold the nearest point
        if k == 0 and n > 0:
            near.append((n - 1, _DRAW))
        if min(_nearest(pieces[m], p, max(0, j - 1) / _DRAW, min(_DRAW, j + 1) / _DRAW) for m, j in near) \
                > SAMPLE_TOL:
            return False
    return True


def entities(curve):
    """Orca entities for a capture curve of kind `other` with its `nurbs` (sketch 2D mm), or None."""
    pieces = bezier_pieces(curve.get("nurbs"))
    if not pieces or not _matches(pieces, curve):
        return None
    out = []
    for piece in pieces:
        if math.dist(piece[0], piece[-1]) <= END_TOL and all(math.dist(piece[0], p) <= END_TOL for p in piece):
            continue  # a piece of no length
        if len(piece) == 2:
            out.append(SketchEntity(type=EntityType.LINE, p0=piece[0], p1=piece[1]))
        else:
            out.append(SketchEntity(type=EntityType.BSPLINE, p0=piece[0], p1=piece[-1], ctrl=list(piece)))
    return out or None
