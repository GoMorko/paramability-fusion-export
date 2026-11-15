"""Crossing points of sketch curves as exact formulas.

An outline drawn from several sketch curves has corners where two curves cross: two lines, a line and a circle, or
two circles. The probe measures the curves themselves (a line's offset from the sketch origin, an arc's centre and
radius), which follow sizes as `Affine` values even where the crossing points do not. Here a corner is rebuilt from
the two curves through it: two lines meet at an affine point, a line and a circle or two circles at a point with a
square root (`curved.Curved`). An arc's middle point becomes a fixed direction from its centre, which stays on the
arc.

`keeps_order` checks that the rebuilt outline keeps its shape over the size range and the probe's states: every
crossing still exists and the corners keep their order. `order_ranges` gives the ranges inside which it does, for an
outline that crosses itself only in a corner of the ranges (a leg turned while shorter than another).

`simple_ranges` checks any outline whose corners follow sizes, also with straight formulas only: at each setting of
the ranges it works out the corners as the copy writes them (a value that cannot follow stays its number) and looks
for two edges of the loops that cross. A corner that follows a size while the curve it meets stays where it is (a
value that moves along a curve the probe could not fit) can pass that curve inside the ranges.
"""
import math

from ...geometry.vec import POINT_TOL
from ...params.expressions.errors import ExpressionError
from ...params.expressions.formula import parse_formula
from ...sketch_values import keys
from ...sketch_values.motion import CURVE, Affine, Stuck
from ..ranges import kept_ranges, range_check
from .curved import Curved, combine, names_of, render, times

FIT_TOL = 1e-4
ORDER_STEPS = 20  # halvings that find where a range stops keeping the order: a millionth of the range
_FAILURES = (ExpressionError, ValueError, ZeroDivisionError, OverflowError)
TURN_TOL = 1e-9
LEAST = 1e-9
MAX_SIMPLE_EDGES = 160  # loops with more edges than this are not checked (the check grows with their square)
CROSS_TOL = 1e-9  # how far (mm squared) an edge end must lie off the other edge for the two to cross
END_TOL = 1e-6  # a crossing this close (mm) to the end of an edge is the corner the two edges share
ANGLE_TOL = 1e-9


def _unit(v):
    size = math.hypot(v[0], v[1])
    return None if size <= 1e-12 else [v[0] / size, v[1] / size]


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1]


def _moves(value):
    return isinstance(value, Stuck) or bool(names_of(value))


class _Line:
    def __init__(self, curve, offset, turn):
        self.d = _unit([curve["end"][i] - curve["start"][i] for i in range(2)])
        self.n = [-self.d[1], self.d[0]]
        self.c0 = _dot(self.n, curve["start"])
        self.c = offset
        self.turn = turn

    def stuck(self):
        if isinstance(self.c, Stuck):
            return self.c
        if _moves(self.turn):
            return Stuck(names_of(self.turn), CURVE)
        return None


class _Circle:
    def __init__(self, curve, center, radius):
        self.c0, self.r0 = [float(v) for v in curve["center"]], float(curve["radius"])
        self.c, self.r = center, radius

    def stuck(self):
        found = [v for v in list(self.c) + [self.r] if isinstance(v, Stuck)]
        return found[0] if found else None


class Sources:
    """The sketch curves of the profiles an outline is drawn from, by sketch entity, with their raw values.

    `lookup(key, number)` gives the raw value of a probe key (the captured number as a constant when it did not move).
    `parts` are `(key prefix, capture profile)`.
    """

    def __init__(self, lookup, parts, sketch=""):
        self.sketch = sketch
        self.curves, self.ends, self.mids = {}, [], []
        for prefix, profile in parts:
            for k, loop in enumerate(profile.get("loops") or []):
                for j, curve in enumerate(loop.get("curves") or []):
                    entity, kind = curve.get("entity"), curve.get("kind")
                    if not entity or kind not in ("line", "arc"):
                        continue
                    key = keys.curve(prefix, k, j)
                    if entity not in self.curves:
                        self.curves[entity] = self._source(lookup, key, curve)
                    self.ends += [(curve["start"], entity), (curve["end"], entity)]
                    if kind == "arc":
                        self.mids.append((curve["mid"], entity))

    @staticmethod
    def _source(lookup, key, curve):
        if curve["kind"] == "line":
            if _unit([curve["end"][i] - curve["start"][i] for i in range(2)]) is None:
                return None
            line = _Line(curve, None, None)
            line.c = lookup(key + "offset", line.c0)
            line.turn = lookup(key + "turn", 0.0)
            return line
        center = [lookup(key + "center.%d" % i, float(curve["center"][i])) for i in range(2)]
        return _Circle(curve, center, lookup(key + "radius", float(curve["radius"])))

    def _at(self, found, uv):
        return list(dict.fromkeys(e for p, e in found if math.hypot(p[0] - uv[0], p[1] - uv[1]) <= POINT_TOL))

    def point(self, uv):
        """The raw (x, y) of the corner at `uv` from the two curves that cross there, a Stuck when no pair of curves
        that can follow gives it and one that cannot is involved, or None when no pair of curves gives this corner."""
        sources = [self.curves[e] for e in self._at(self.ends, uv) if self.curves.get(e) is not None]
        pairs = [(a, b) for i, a in enumerate(sources) for b in sources[i + 1:]]
        pairs.sort(key=lambda p: sum(isinstance(s, _Circle) for s in p))
        blocked = None
        for a, b in pairs:
            stuck = a.stuck() or b.stuck()
            if stuck is not None:
                blocked = blocked or Stuck(stuck.movers, stuck.cause, self.sketch)
                continue
            if isinstance(a, _Circle) and isinstance(b, _Line):
                a, b = b, a
            if isinstance(a, _Line) and isinstance(b, _Line):
                found = _line_line(a, b, uv, self.sketch)
            elif isinstance(a, _Line):
                found = _line_circle(a, b, uv, self.sketch)
            else:
                found = _circle_circle(a, b, uv, self.sketch)
            if found is not None:
                return found
        return blocked

    def circle(self, center, radius):
        """The raw (centre, radius) of the sketch circle at `center` with `radius`, a Stuck, or None."""
        for found in self.curves.values():
            if isinstance(found, _Circle) and math.hypot(found.c0[0] - center[0], found.c0[1] - center[1]) <= FIT_TOL \
                    and abs(found.r0 - radius) <= FIT_TOL:
                stuck = found.stuck()
                if stuck is not None:
                    return Stuck(stuck.movers, stuck.cause, self.sketch)
                return list(found.c), found.r
        return None

    def through(self, uv):
        """The raw (x, y) of an arc's middle point at `uv`: a fixed direction from its centre, at its radius."""
        for e in self._at(self.mids, uv):
            circle = self.curves.get(e)
            if not isinstance(circle, _Circle):
                continue
            stuck = circle.stuck()
            if stuck is not None:
                return Stuck(stuck.movers, stuck.cause, self.sketch)
            w = _unit([uv[i] - circle.c0[i] for i in range(2)])
            if w is not None and abs(math.hypot(uv[0] - circle.c0[0], uv[1] - circle.c0[1]) - circle.r0) <= FIT_TOL:
                return tuple(combine([(1.0, circle.c[i]), (w[i], circle.r)], self.sketch) for i in range(2))
        return None


def _near(p, uv):
    return math.hypot(p[0] - uv[0], p[1] - uv[1]) <= FIT_TOL


def _line_line(a, b, uv, sketch):
    det = a.n[0] * b.n[1] - a.n[1] * b.n[0]
    if abs(det) <= TURN_TOL:
        return None
    p0 = [(a.c0 * b.n[1] - b.c0 * a.n[1]) / det, (a.n[0] * b.c0 - b.n[0] * a.c0) / det]
    if not _near(p0, uv):
        return None
    return (combine([(b.n[1] / det, a.c), (-a.n[1] / det, b.c)], sketch),
            combine([(-b.n[0] / det, a.c), (a.n[0] / det, b.c)], sketch))


def _root(square, number):
    """The square root of a raw value whose captured number is `number`: a plain number when it does not move."""
    if not names_of(square):
        return math.sqrt(number)
    return square.sqrt() if isinstance(square, Curved) else Curved(square).sqrt()


def _line_circle(line, circle, uv, sketch):
    n, d = line.n, line.d
    s0 = line.c0 - _dot(n, circle.c0)
    h0 = circle.r0 ** 2 - s0 ** 2
    if h0 <= FIT_TOL ** 2:
        return None
    foot0 = [circle.c0[i] + s0 * n[i] for i in range(2)]
    sign = 1.0 if _dot(d, [uv[i] - foot0[i] for i in range(2)]) >= 0 else -1.0
    if not _near([foot0[i] + sign * math.sqrt(h0) * d[i] for i in range(2)], uv):
        return None
    s = combine([(1.0, line.c), (-n[0], circle.c[0]), (-n[1], circle.c[1])], sketch)
    h = _root(combine([(1.0, times(circle.r, circle.r)), (-1.0, times(s, s))], sketch), h0)
    return tuple(combine([(1.0, circle.c[i]), (n[i], s), (sign * d[i], h)], sketch) for i in range(2))


def _same(a, b):
    if isinstance(a, Affine) and isinstance(b, Affine):
        return a.terms.keys() == b.terms.keys() and all(abs(a.terms[k] - b.terms[k]) <= 1e-9 for k in a.terms) and abs(
            a.const - b.const) <= 1e-9
    return False


def _circle_circle(one, two, uv, sketch):
    delta0 = [two.c0[i] - one.c0[i] for i in range(2)]
    u = _unit(delta0)
    if u is None:
        return None
    v = [-u[1], u[0]]
    delta = [combine([(1.0, two.c[i]), (-1.0, one.c[i])], sketch) for i in range(2)]
    if names_of(combine([(v[0], delta[0]), (v[1], delta[1])])):
        return None  # the centres turn about each other
    dist0 = _dot(u, delta0)
    a0 = (dist0 ** 2 + one.r0 ** 2 - two.r0 ** 2) / (2 * dist0)
    h0 = one.r0 ** 2 - a0 ** 2
    if h0 <= FIT_TOL ** 2:
        return None
    base0 = [one.c0[i] + a0 * u[i] for i in range(2)]
    sign = 1.0 if _dot(v, [uv[i] - base0[i] for i in range(2)]) >= 0 else -1.0
    if not _near([base0[i] + sign * math.sqrt(h0) * v[i] for i in range(2)], uv):
        return None
    dist = combine([(u[0], delta[0]), (u[1], delta[1])], sketch)
    if _same(one.r, two.r):
        a = combine([(0.5, dist)], sketch)
    else:
        top = combine([(1.0, times(dist, dist)), (1.0, times(one.r, one.r)), (-1.0, times(two.r, two.r))], sketch)
        a = top.divided(combine([(2.0, dist)], sketch)) if names_of(dist) else combine([(0.5 / dist0, top)], sketch)
    h = _root(combine([(1.0, times(one.r, one.r)), (-1.0, times(a, a))], sketch), h0)
    return tuple(combine([(1.0, one.c[i]), (u[i], a), (sign * v[i], h)], sketch) for i in range(2))


# ---- does the rebuilt outline keep its shape -------------------------------------------------------------------

def _chain(loop, raw_loop):
    """(uv, raw xy, is a middle point) along a profile or polygon loop, or [] for other kinds."""
    if loop["kind"] == "polygon":
        return [(p, r, False) for p, r in zip(loop["points"], raw_loop["points"])]
    if loop["kind"] != "profile":
        return []
    out = [(loop["start"], raw_loop["start"], False)]
    for seg, rseg in zip(loop["segments"], raw_loop["segments"]):
        if "through" in seg:
            out.append((seg["through"], rseg["through"], True))
        out.append((seg["to"], rseg["to"], False))
    return out


def _curved(xy):
    return any(isinstance(c, Curved) for c in xy)


def _checks(loop, raw_loop, sketch):
    """Values that stay above zero while the loop keeps its shape: each step along it keeps its direction, and each
    arc keeps its turning sense."""
    chain = _chain(loop, raw_loop)
    if loop["kind"] == "polygon" and chain:
        chain = chain + chain[:1]
    out = []
    for (a, ra, _), (b, rb, _) in zip(chain, chain[1:]):
        step = [b[i] - a[i] for i in range(2)]
        if math.hypot(*step) <= POINT_TOL or not (_curved(ra) or _curved(rb)):
            continue
        out.append(combine([(step[i], rb[i]) for i in range(2)] + [(-step[i], ra[i]) for i in range(2)], sketch))
    for at, (t, rt, middle) in enumerate(chain):
        if not middle or not any(_curved(r) for _, r, _ in chain[at - 1:at + 2]):
            continue
        (s, rs, _), (e, re_, _) = chain[at - 1], chain[at + 1]
        sense = 1.0 if (t[0] - s[0]) * (e[1] - t[1]) - (t[1] - s[1]) * (e[0] - t[0]) >= 0 else -1.0
        d1 = [combine([(1.0, rt[i]), (-1.0, rs[i])], sketch) for i in range(2)]
        d2 = [combine([(1.0, re_[i]), (-1.0, rt[i])], sketch) for i in range(2)]
        out.append(combine([(sense, times(d1[0], d2[1])), (-sense, times(d1[1], d2[0]))], sketch))
    return out


def _states(table, motion):
    """The probe's built states as size settings (recipe size name to value)."""
    out = []
    for state in getattr(motion, "states", None) or []:
        if state.get("built") is False:
            continue
        found = {}
        for name, value in (state.get("values") or {}).items():
            size = table.size_name(name)
            if size and "value" in table.sizes.get(size, {}):
                found[size] = value
        if found:
            out.append(found)
    return out


def _stays_above_zero(table, motion, value):
    q = render(value, table)
    if isinstance(q, Stuck):
        return False
    if not q.sized:
        return q.n > LEAST
    return range_check.sweep(table, q.text, q.reads, extra=_states(table, motion)).above(LEAST)


def _inside(setting, bounds):
    return all(bounds[name][0] - 1e-9 <= value <= bounds[name][1] + 1e-9
               for name, value in setting.items() if name in bounds)


def order_ranges(table, loops, raw_loops, sketch="", motion=None):
    """`{Fusion name: (min, max)}` inside which every rebuilt loop keeps the order of its corners: each check of
    `_checks` stays above zero over the ranges by the same settings as `keeps_order` (`range_check.sweep`, with the
    middles of the ranges and the probe's built states that fall inside them), the ranges cut by
    `kept_ranges.holding_ranges_where`. None when no shorter ranges keep it (a check that cannot be written, or one
    that fails at the values now)."""
    texts = {}
    for loop, raw_loop in zip(loops, raw_loops):
        for check in _checks(loop, raw_loop, sketch):
            q = None if isinstance(check, Stuck) else render(check, table)
            if q is None or isinstance(q, Stuck) or (not q.sized and q.n <= LEAST):
                return None
            if q.sized:
                texts[q.text] = q.reads
    if not texts:
        return {}
    reads = list(dict.fromkeys(r for found in texts.values() for r in found))
    trees = [parse_formula(text) for text in texts]
    states = _states(table, motion)

    def above_at(setting):
        try:
            env = range_check.size_env(table, setting)
            return all(range_check.value_of(tree, env) > LEAST for tree in trees)
        except _FAILURES:
            return False

    def holds(bounds, only=None):
        if only is not None:
            return above_at({only[0]: bounds[only[0]][only[1]]})
        inside = [state for state in states if _inside(state, bounds)]
        return all(range_check.sweep(table, text, found, bounds=bounds,
                                     extra=range_check.middles(table, found, bounds) + inside).above(LEAST)
                   for text, found in texts.items())

    return kept_ranges.holding_ranges_where(table, reads, holds, steps=ORDER_STEPS)


def keeps_order(table, motion, loops, raw_loops, sketch=""):
    """True when every rebuilt loop keeps its crossings and the order of its corners over the size range."""
    for loop, raw_loop in zip(loops, raw_loops):
        for check in _checks(loop, raw_loop, sketch):
            if isinstance(check, Stuck) or not _stays_above_zero(table, motion, check):
                return False
    return True


# ---- does the written outline stay one loop that does not cross itself ----------------------------------------

def _written(value, number, table):
    """A parsed formula of a raw value that moves with the sizes, with the sizes it reads, else `(number, ())`: the
    number the copy writes for a value that does not move or cannot follow. None when `number` is no number."""
    if isinstance(value, (Affine, Curved)) and names_of(value):
        q = render(value, table)
        if not isinstance(q, Stuck) and q.sized:
            return parse_formula(q.text), tuple(q.reads)
    if not isinstance(number, (int, float)) or isinstance(number, bool):
        return None
    return float(number), ()


def _circle(a, m, b):
    """`(centre, radius, start angle, signed turn)` of the arc from `a` through `m` to `b`, or None when they line up."""
    d = 2.0 * (a[0] * (m[1] - b[1]) + m[0] * (b[1] - a[1]) + b[0] * (a[1] - m[1]))
    if abs(d) <= 1e-12:
        return None
    sq = [p[0] * p[0] + p[1] * p[1] for p in (a, m, b)]
    c = ((sq[0] * (m[1] - b[1]) + sq[1] * (b[1] - a[1]) + sq[2] * (a[1] - m[1])) / d,
         (sq[0] * (b[0] - m[0]) + sq[1] * (a[0] - b[0]) + sq[2] * (m[0] - a[0])) / d)
    t0, tm, t1 = (math.atan2(p[1] - c[1], p[0] - c[0]) for p in (a, m, b))
    turn = (t1 - t0) % (2 * math.pi)
    if (tm - t0) % (2 * math.pi) > turn:
        turn -= 2 * math.pi
    return c, math.hypot(a[0] - c[0], a[1] - c[1]), t0, turn


def _edges(chain_points):
    """The edges of one closed loop from `(point, is a middle point)` along it: `("line", a, b)` or `("arc", a, b,
    circle)`; an arc whose points line up is two lines."""
    out, last, at = [], chain_points[0][0], 1
    while at < len(chain_points):
        point, middle = chain_points[at]
        if middle and at + 1 < len(chain_points):
            end = chain_points[at + 1][0]
            circle = _circle(last, point, end)
            out += [("arc", last, end, circle)] if circle else [("line", last, point), ("line", point, end)]
            last, at = end, at + 2
            continue
        out.append(("line", last, point))
        last, at = point, at + 1
    first = chain_points[0][0]
    if math.hypot(first[0] - last[0], first[1] - last[1]) > POINT_TOL:
        out.append(("line", last, first))
    return [e for e in out if math.hypot(e[2][0] - e[1][0], e[2][1] - e[1][1]) > POINT_TOL]


def _on_arc(edge, p):
    """True when `p`, a point of the arc's circle, lies on the arc between its ends."""
    (cx, cy), _, t0, turn = edge[3]
    along = (math.atan2(p[1] - cy, p[0] - cx) - t0) % (2 * math.pi)
    if turn < 0:
        along = (2 * math.pi - along) % (2 * math.pi)
    return ANGLE_TOL < along < abs(turn) - ANGLE_TOL


def _on_line(edge, p):
    (ax, ay), (bx, by) = edge[1], edge[2]
    dx, dy = bx - ax, by - ay
    t = ((p[0] - ax) * dx + (p[1] - ay) * dy) / (dx * dx + dy * dy)
    return 0.0 <= t <= 1.0


def _meets(edge):
    return _on_arc if edge[0] == "arc" else _on_line


def _line_line_cross(e, f):
    def side(a, b, c):
        return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
    (p, q), (r, t) = e[1:3], f[1:3]
    return side(p, q, r) * side(p, q, t) < -CROSS_TOL and side(r, t, p) * side(r, t, q) < -CROSS_TOL


def _circle_points(e, f):
    """Where the line or circle of `e` meets the circle of `f` (an arc), leaving out a touch."""
    (cx, cy), r = f[3][0], f[3][1]
    if e[0] == "line":
        (ax, ay), (bx, by) = e[1], e[2]
        dx, dy, fx, fy = bx - ax, by - ay, ax - cx, ay - cy
        qa, qb, qc = dx * dx + dy * dy, 2 * (fx * dx + fy * dy), fx * fx + fy * fy - r * r
        disc = qb * qb - 4 * qa * qc
        if disc <= CROSS_TOL * qa:
            return []
        root = math.sqrt(disc)
        return [(ax + t * dx, ay + t * dy) for t in ((-qb - root) / (2 * qa), (-qb + root) / (2 * qa))]
    (ox, oy), s = e[3][0], e[3][1]
    dist = math.hypot(cx - ox, cy - oy)
    if dist <= POINT_TOL or dist >= r + s or dist <= abs(r - s):
        return []
    a = (s * s - r * r + dist * dist) / (2 * dist)
    h = math.sqrt(max(0.0, s * s - a * a))
    if h <= POINT_TOL:
        return []
    ux, uy = (cx - ox) / dist, (cy - oy) / dist
    return [(ox + a * ux - h * uy, oy + a * uy + h * ux), (ox + a * ux + h * uy, oy + a * uy - h * ux)]


def _cross(e, f):
    """True when two edges cross at a point that is not an end of either (edges that meet at a corner do not)."""
    if e[0] == "line" and f[0] == "line":
        return _line_line_cross(e, f)
    if e[0] == "arc" and f[0] == "line":
        e, f = f, e
    ends = (e[1], e[2], f[1], f[2])
    for p in _circle_points(e, f):
        if any(math.hypot(p[0] - q[0], p[1] - q[1]) <= END_TOL for q in ends):
            continue
        if _meets(e)(e, p) and _meets(f)(f, p):
            return True
    return False


def _crossing(loops_edges):
    """True when two edges of the loops cross."""
    flat = [e for edges in loops_edges for e in edges]
    return any(_cross(e, f) for at, e in enumerate(flat) for f in flat[at + 1:])


def simple_ranges(table, loops, raw_loops, motion=None):
    """`{Fusion name: (min, max)}` inside which the written loops cross neither themselves nor each other, at every
    setting `order_ranges` tests (corners and middles of the ranges and the probe's built states inside them); `{}`
    when they hold over the whole ranges or nothing in them moves; None when no shorter ranges keep them (they cross
    at the values now, or a size they read has a typed range). Loops other than profiles and polygons are not
    checked."""
    chains = []
    for loop, raw_loop in zip(loops, raw_loops):
        chain = _chain(loop, raw_loop)
        if chain:
            chains.append([([_written(v, n, table) for v, n in zip(raw_xy, uv)], middle)
                           for uv, raw_xy, middle in chain])
    if any(v is None for chain in chains for xy, _ in chain for v in xy):
        return {}
    reads = list(dict.fromkeys(r for chain in chains for xy, _ in chain for _, found in xy for r in found))
    if not reads or sum(len(chain) for chain in chains) > MAX_SIMPLE_EDGES:
        return {}
    states = _states(table, motion)

    def simple_at(setting):
        try:
            env = range_check.size_env(table, setting)
            loops_edges = [_edges([(tuple(range_check.value_of(v, env) if found else v for v, found in xy), middle)
                                   for xy, middle in chain]) for chain in chains]
        except _FAILURES:
            return False
        return not _crossing(loops_edges)

    def holds(bounds, only=None):
        if only is not None:
            return simple_at({only[0]: bounds[only[0]][only[1]]})
        settings = (range_check.corners(table, reads, bounds) + range_check.middles(table, reads, bounds)
                    + [state for state in states if _inside(state, bounds)])
        return all(simple_at(setting) for setting in settings)

    return kept_ranges.holding_ranges_where(table, reads, holds, steps=ORDER_STEPS)
