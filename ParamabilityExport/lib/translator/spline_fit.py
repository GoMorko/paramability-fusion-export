"""Free curves as the recipe's spline segments. Pure: no Fusion imports.

The recipe's `spline` segment is not Fusion's curve. It is a clamped cubic through the listed points with chord
length parameters and natural ends (zero second derivative), the same definition as the app's `interpolateCurve`
(`@packages/curve-interp`). `interpolate` and `evaluate` port that definition (`tests/fixtures/spline_vectors.json`
holds values from the app's own code, which the port matches to 1e-9 mm).

`fit` chooses the points. The capture holds a dense polyline of the Fusion curve (`samples`, within a small chord
error of it). Points are added where the app's curve through the chosen ones is farthest from that polyline until the
two stay within `TOLERANCE_MM`; a run that needs more than `MAX_THROUGH` points inside one segment is split in two
segments. The app has no tangent field on a segment, so the ends are always natural: an end that bends away from
that is caught by the deviation test and gets points near it.
"""
import math
from functools import lru_cache

TOLERANCE_MM = 0.005   # the app's own sampling floor for a spline outline
MAX_THROUGH = 64       # `through` points of one segment (recipe cap)
MIN_SPAN = 1e-9
_DEGREE = 3
_PIVOT = 1e-12


# ---- the app's interpolation -------------------------------------------------------------------------------------

def _find_span(knots, u):
    n = len(knots) - _DEGREE - 2
    if u >= knots[n + 1]:
        return n
    if u <= knots[_DEGREE]:
        return _DEGREE
    lo, hi = _DEGREE, n + 1
    while hi - lo > 1:
        mid = (lo + hi) >> 1
        if u < knots[mid]:
            hi = mid
        else:
            lo = mid
    return lo


def _basis(knots, span, u, order):
    """Nonzero cubic basis functions and their derivatives up to `order`: `ders[k][j]` of function `span - 3 + j`."""
    d = _DEGREE
    ndu = [[0.0] * (d + 1) for _ in range(d + 1)]
    left, right = [0.0] * (d + 1), [0.0] * (d + 1)
    ndu[0][0] = 1.0
    for j in range(1, d + 1):
        left[j] = u - knots[span + 1 - j]
        right[j] = knots[span + j] - u
        saved = 0.0
        for r in range(j):
            ndu[j][r] = right[r + 1] + left[j - r]
            temp = ndu[r][j - 1] / ndu[j][r]
            ndu[r][j] = saved + right[r + 1] * temp
            saved = left[j - r] * temp
        ndu[j][j] = saved
    ders = [[0.0] * (d + 1) for _ in range(order + 1)]
    for j in range(d + 1):
        ders[0][j] = ndu[j][d]
    a = [[0.0] * (d + 1), [0.0] * (d + 1)]
    for r in range(d + 1):
        s1, s2 = 0, 1
        a[0] = [0.0] * (d + 1)
        a[1] = [0.0] * (d + 1)
        a[0][0] = 1.0
        for k in range(1, order + 1):
            value = 0.0
            rk, pk = r - k, d - k
            if r >= k:
                a[s2][0] = a[s1][0] / ndu[pk + 1][rk]
                value = a[s2][0] * ndu[rk][pk]
            j1 = 1 if rk >= -1 else -rk
            j2 = k - 1 if r - 1 <= pk else d - r
            for j in range(j1, j2 + 1):
                a[s2][j] = (a[s1][j] - a[s1][j - 1]) / ndu[pk + 1][rk + j]
                value += a[s2][j] * ndu[rk + j][pk]
            if r <= pk:
                a[s2][k] = -a[s1][k - 1] / ndu[pk + 1][r]
                value += a[s2][k] * ndu[r][pk]
            ders[k][r] = value
            s1, s2 = s2, s1
    factor = d
    for k in range(1, order + 1):
        for j in range(d + 1):
            ders[k][j] *= factor
        factor *= d - k
    return ders


class Curve:
    """A clamped cubic in 2D: `poles`, `knots` and the parameter of each interpolated point."""

    def __init__(self, poles, knots, params, chord):
        self.poles, self.knots, self.params, self.chord = poles, knots, params, chord

    def at(self, u, order=0):
        u = min(1.0, max(0.0, u))
        span = _find_span(self.knots, u)
        ders = _basis(self.knots, span, u, order)[order]
        x = y = 0.0
        for j in range(_DEGREE + 1):
            pole = self.poles[span - _DEGREE + j]
            x += ders[j] * pole[0]
            y += ders[j] * pole[1]
        return [x, y]


def _solve(rows, rhs):
    """Gaussian elimination with partial pivoting for a matrix whose rows hold few non zero entries."""
    n = len(rows)
    a = [list(row) + list(r) for row, r in zip(rows, rhs)]
    cols = len(a[0])
    for c in range(n):
        pivot = max(range(c, n), key=lambda r: abs(a[r][c]))
        if abs(a[pivot][c]) < _PIVOT:
            return None
        a[c], a[pivot] = a[pivot], a[c]
        for r in range(c + 1, n):
            f = a[r][c] / a[c][c]
            if f != 0.0:
                row, top = a[r], a[c]
                for k in range(c, cols):
                    row[k] -= f * top[k]
    out = [[0.0] * (cols - n) for _ in range(n)]
    for k in range(n, cols):
        for r in range(n - 1, -1, -1):
            total = a[r][k]
            for c in range(r + 1, n):
                total -= a[r][c] * out[c][k - n]
            out[r][k - n] = total / a[r][r]
    return out


def interpolate(points):
    """The app's curve through 2D `points` (natural ends), or None for fewer than two points, a repeated point in
    a row or a singular system."""
    m = len(points)
    if m < 2:
        return None
    chords = []
    for p, q in zip(points, points[1:]):
        d = math.hypot(q[0] - p[0], q[1] - p[1])
        if not d > 0:
            return None
        chords.append(d)
    total = sum(chords)
    params, run = [0.0], 0.0
    for i, d in enumerate(chords):
        run += d
        params.append(1.0 if i == m - 2 else run / total)
    knots = [0.0] * 4 + params[1:m - 1] + [1.0] * 4
    size = m + 2

    def row(u, order):
        span = _find_span(knots, u)
        ders = _basis(knots, span, u, order)[order]
        out = [0.0] * size
        for j in range(_DEGREE + 1):
            out[span - _DEGREE + j] = ders[j]
        return out

    rows = [row(u, 0) for u in params] + [row(0.0, 2), row(1.0, 2)]
    rhs = [list(p) for p in points] + [[0.0, 0.0], [0.0, 0.0]]
    poles = _solve(rows, rhs)
    return None if poles is None else Curve(poles, knots, params, total)


# ---- choosing the points -----------------------------------------------------------------------------------------

def _to_segment(p, a, b):
    dx, dy = b[0] - a[0], b[1] - a[1]
    size = dx * dx + dy * dy
    t = 0.0 if size <= 0 else max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / size))
    return math.hypot(p[0] - a[0] - t * dx, p[1] - a[1] - t * dy)


def _near_polyline(p, line, lo, hi):
    """Distance from `p` to the segments `lo..hi` of a polyline (indices clipped to the line)."""
    lo, hi = max(lo, 0), min(hi, len(line) - 2)
    if hi < lo:
        return math.inf
    px, py = p
    best = math.inf
    for k in range(lo, hi + 1):
        ax, ay = line[k]
        dx, dy = line[k + 1][0] - ax, line[k + 1][1] - ay
        size = dx * dx + dy * dy
        t = ((px - ax) * dx + (py - ay) * dy) / size if size > 0 else 0.0
        t = 0.0 if t < 0.0 else (1.0 if t > 1.0 else t)
        ex, ey = px - ax - t * dx, py - ay - t * dy
        gap = ex * ex + ey * ey
        if gap < best:
            best = gap
    return math.sqrt(best)


def _local(p, line, k, wide):
    """Distance from `p` to `line` near index `k`: a short window first, the wide one `wide` only when that is
    not already within tolerance."""
    near = _near_polyline(p, line, k - 3, k + 2)
    return near if near <= TOLERANCE_MM else min(near, _near_polyline(p, line, wide[0], wide[1]))


def _deviations(dense, chosen, curve):
    """For each dense point, the larger of its distance to the fitted curve and the distance of the fitted curve
    point at the same arc length to the dense polyline. The fitted curve is read at the arc length of each dense
    point inside its span, so a point far along the curve from its twin is only found by the wide window."""
    arc = [0.0]
    for p, q in zip(dense, dense[1:]):
        arc.append(arc[-1] + math.hypot(q[0] - p[0], q[1] - p[1]))
    on_curve = [None] * len(dense)
    span_of = [0] * len(dense)
    for s, (i, j) in enumerate(zip(chosen, chosen[1:])):
        u0, u1 = curve.params[s], curve.params[s + 1]
        length = arc[j] - arc[i]
        for k in range(i, j + 1):
            f = (arc[k] - arc[i]) / length if length > 0 else 0.0
            on_curve[k] = curve.at(u0 + (u1 - u0) * f)
            span_of[k] = s
    out = [0.0] * len(dense)
    for k, p in enumerate(dense):
        s = span_of[k]
        wide = (chosen[max(s - 1, 0)] - 1, chosen[min(s + 2, len(chosen) - 1)])
        out[k] = max(_local(p, on_curve, k, wide), _local(on_curve[k], dense, k, wide))
    return out


def _closed(dense):
    return math.hypot(dense[0][0] - dense[-1][0], dense[0][1] - dense[-1][1]) <= 1e-6


def _run(dense):
    """The indices of `dense` to pass through, or None when the points cannot be fitted inside `MAX_THROUGH`."""
    last = len(dense) - 1
    chosen = [0, last] if not _closed(dense) else [0, last // 2, last]
    while True:
        curve = interpolate([dense[i] for i in chosen])
        if curve is None:
            return None
        if len(chosen) <= 2:
            gaps = [_to_segment(p, dense[0], dense[last]) for p in dense]
        else:
            gaps = _deviations(dense, chosen, curve)
        added = _worst_per_span(gaps, chosen)
        if not added:
            return chosen
        room = MAX_THROUGH - (len(chosen) - 2)
        if room <= 0:
            return None
        chosen = sorted(chosen + added[:room])


def _worst_per_span(gaps, chosen):
    """The dense index of the largest gap inside each span that is over tolerance, worst gap first."""
    found = []
    for i, j in zip(chosen, chosen[1:]):
        if j - i < 2:
            continue
        worst = max(range(i + 1, j), key=lambda k: gaps[k])
        if gaps[worst] > TOLERANCE_MM:
            found.append(worst)
    return sorted(found, key=lambda k: -gaps[k])


def _dedupe(samples):
    out = []
    for p in samples:
        if not out or math.hypot(p[0] - out[-1][0], p[1] - out[-1][1]) > MIN_SPAN:
            out.append([float(p[0]), float(p[1])])
    return out


def _pieces(dense, depth=0):
    if len(dense) <= 2:
        return [dense]
    chosen = _run(dense)
    if chosen is not None:
        return [[dense[i] for i in chosen]]
    if depth > 12 or len(dense) < 5:
        return None
    mid = len(dense) // 2
    left, right = _pieces(dense[:mid + 1], depth + 1), _pieces(dense[mid:], depth + 1)
    return None if left is None or right is None else left + right


@lru_cache(maxsize=512)
def _fit(samples, limit):
    """`fit` for hashable samples; `limit` (the through point cap) is part of the cache key."""
    dense = _dedupe(samples)
    if len(dense) < 2:
        return None
    found = _pieces(dense)
    return None if found is None else tuple(tuple(tuple(p) for p in piece) for piece in found)


def fit(samples):
    """Pieces of points for one free curve: a list of point lists, each piece one spline segment from its first
    point through the middle ones to its last (a two point piece is a straight line); the last point of a piece is
    the first of the next. `samples` is the dense polyline `[[x, y], ...]` in mm. None when no fit is found."""
    if not samples or len(samples) < 2:
        return None
    found = _fit(tuple((float(p[0]), float(p[1])) for p in samples), MAX_THROUGH)
    return None if found is None else [[list(p) for p in piece] for piece in found]


def max_error(samples, pieces):
    """The largest distance in mm between the dense polyline and the app's curve through `pieces`, read both ways.
    For tests and checks; `fit` already keeps this under its tolerance."""
    worst, start = 0.0, 0
    dense = _dedupe(samples)
    for piece in pieces:
        if len(piece) == 2:
            end = _index_of(dense, piece[1], start)
            worst = max([worst] + [_to_segment(p, piece[0], piece[1]) for p in dense[start:end + 1]])
            start = end
            continue
        end = _index_of(dense, piece[-1], start)
        chosen = [start] + [_index_of(dense, p, start) for p in piece[1:-1]] + [end]
        curve = interpolate(piece)
        run = dense[start:end + 1]
        gaps = _deviations(run, [i - start for i in chosen], curve)
        worst = max(worst, max(gaps))
        start = end
    return worst


def _index_of(dense, point, at):
    return min(range(at, len(dense)), key=lambda k: math.hypot(dense[k][0] - point[0], dense[k][1] - point[1]))
