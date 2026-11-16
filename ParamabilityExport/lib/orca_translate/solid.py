"""The part the Orca copy has built so far, kept as simple shapes, so a cut can be checked and the copy's box measured
without a geometry kernel.

Every copied step is one of a few shapes: an outline swept along its plane normal between two heights (`Prism`, an
extrude or a hole), an outline swept the same way while it grows or shrinks (`Tapered`, a tapered extrude), an
outline turned about an axis (`Turned`, a revolve), the half of space on one side of a plane (`HalfSpace`, a plane
cut), or another body moved rigidly (`Moved`, a pattern or mirror copy, a Move). A body
(`Solid`) is the run of these: an added shape adds its material, a cut takes it away, an intersect keeps only what
lies in both. A body is itself a shape, so a Combine takes another body as its tool and a pattern adds moved copies.

Everything is asked through lines: `span` gives the parts of a line inside a shape. A prism or half space answers
exactly (arcs as fine polylines); a turned or tapered outline is sampled along the line. A tapered outline (and a
loft, `lofts.Lofted`) steps no further than its nearest wall allows (`traced`), so it misses no part of the line wider
than a small floor; a turned outline takes even samples (`sampled`). From that:
- `meets`: whether a tool shares material with the body along lines through it. Orca stops the whole rebuild on a
  cut that removes nothing, so the copy leaves such a step out, and a one way cut through all whose stored direction
  meets no material is turned to the side that holds the part.
- `box`: the box of the body, from lines along each axis, so the copy can be placed on the bed by its own shape.

Coordinates are the capture's (component, mm), the same as the outlines and frames.
"""
import math

from ..geometry import vec
from ..geometry.footprint import Footprint, curve_distance, polyline

ADD, CUT, INTERSECT = "add", "cut", "intersect"

# A tool meets the part when a line through it runs inside material for longer than this (mm).
MEET_TOL = 1e-3
# Sample lines per side of the box of a tool outline, at most, and their spacing at least (mm).
_GRID_MAX = 32
_GRID_STEP = 0.5
# How far inside an outline (mm) the samples next to its curves sit.
_EDGE_INSET = 1e-3
_EPS = 1e-12
# Where between two crossings a line is tested for inside: off the middle, since a test point level with a corner of
# the outline (a circle's polyline starts and ends at its rightmost point) can be counted wrong.
_OFF_CENTRE = 0.4870813
# Lines per side of a box when a shape that is not a prism is tested, or a box is measured.
_PROBE_LINES = 16
_BOX_LINES = 24
# Rounds of finer lines around the line that reached furthest, and how much finer each round is.
_BOX_ROUNDS = 6
_BOX_ZOOM = 4.0
# Samples along a line through a turned outline, and halvings to place each crossing.
_TURN_SAMPLES = 120
_TURN_HALVINGS = 40
# The same for a tapered outline, whose walls a line crosses only a few times. A step along such a line is no longer
# than the distance to the nearest wall allows, and no shorter than the line's reach through the shape's box over
# `_TAPER_STEPS`: a part of the line inside or outside the shape is missed only when it is shorter than that and lies
# next to a wall.
_TAPER_HALVINGS = 30
_TAPER_STEPS = 4096
# How far (mm) a measured point may lie from the end face of a prism and still be on it.
_CAP_TOL = 1e-4


def _unit(v):
    return vec.unit([float(c) for c in v])


class Prism:
    """An outline (loops of capture curves in the plane of `frame`) swept along the frame's normal from height `low`
    to `high` (either may be infinite).

    A copied extrude also says how its end faces follow variables, so a later step that reaches to one of them can
    follow it: `ends` holds the `Quantity` of `low` and `high` (None for a hole or a cut through all), and
    `plane_sizes` the Fusion names of the sizes that may move its sketch plane, which Orca keeps in place."""

    def __init__(self, frame, loops, low, high):
        self.origin = [float(c) for c in frame["origin"]]
        self.x, self.y, self.z = _unit(frame["x"]), _unit(frame["y"]), _unit(frame["z"])
        self.loops = [list(curves) for curves in loops]
        self.footprint = Footprint({"loops": [{"curves": curves} for curves in self.loops]})
        lines = [polyline(c) for curves in self.loops for c in curves]
        self.segments = [(a, b) for points in lines for a, b in zip(points, points[1:])]
        self.low, self.high = min(low, high), max(low, high)
        self.ends = None
        self.plane_sizes = ()
        # (sketches.SketchOut, extrude feature) of the copied extrude that wrote the prism, so a later round of a
        # side edge can redraw its outline (`outline_rounds`); None for other prisms.
        self.sketch = None
        # The `outline_cuts.Planned` outline when the copy built the prism from plane cuts, which a round of a side
        # edge must not redraw; None for other prisms.
        self.built = None
        # For a copied extrude: (the number of Orca bodies, the index of the body it went into, None when it started
        # it) just before its extrude feature was written, so corner tools can be cut from it (`corner_hosts`).
        self.slot = None

    def _local(self, p):
        d = vec.sub(p, self.origin)
        return vec.dot(d, self.x), vec.dot(d, self.y), vec.dot(d, self.z)

    def cap_at(self, p):
        """0 when `p` lies on the end face at `low`, 1 on the one at `high`, else None."""
        u, v, w = self._local(p)
        if not self.footprint.covers((u, v)):
            return None
        for n, height in enumerate((self.low, self.high)):
            if math.isfinite(height) and abs(w - height) <= _CAP_TOL:
                return n
        return None

    def _turn(self, d):
        return vec.dot(d, self.x), vec.dot(d, self.y), vec.dot(d, self.z)

    def span(self, start, direction):
        """The parts of the line `start + t * direction` inside the prism, as sorted `(t0, t1)` pairs."""
        u0, v0, w0 = self._local(start)
        du, dv, dw = self._turn(direction)
        if abs(dw) < _EPS:
            if not self.low <= w0 <= self.high:
                return []
            along = (-math.inf, math.inf)
        else:
            a, b = (self.low - w0) / dw, (self.high - w0) / dw
            along = (min(a, b), max(a, b))
        if abs(du) < _EPS and abs(dv) < _EPS:
            flat = [(-math.inf, math.inf)] if self.footprint.covers((u0, v0)) else []
        else:
            flat = self._flat_span(u0, v0, du, dv)
        return intersect(flat, [along])

    def _flat_span(self, u0, v0, du, dv):
        cuts = []
        for a, b in self.segments:
            ex, ey = b[0] - a[0], b[1] - a[1]
            den = du * ey - dv * ex
            if abs(den) < _EPS:
                continue
            ax, ay = a[0] - u0, a[1] - v0
            t = (ax * ey - ay * ex) / den
            s = (ax * dv - ay * du) / den
            if -1e-9 <= s <= 1 + 1e-9:
                cuts.append(t)
        cuts = sorted(set(cuts))
        if not cuts:
            return [(-math.inf, math.inf)] if self.footprint.covers((u0, v0)) else []
        bounds = [-math.inf] + cuts + [math.inf]
        out = []
        for t0, t1 in zip(bounds, bounds[1:]):
            mid = t1 - 1.0 if t0 == -math.inf else (t0 + 1.0 if t1 == math.inf else t0 + (t1 - t0) * _OFF_CENTRE)
            if self.footprint.covers((u0 + mid * du, v0 + mid * dv)):
                out.append((t0, t1))
        return union(out, [])

    def samples(self):
        """Points of the outline in its plane (2D): a grid over its box, and points just inside each curve."""
        points = [p for a, b in self.segments for p in (a, b)]
        if not points:
            return []
        lo = [min(p[0] for p in points), min(p[1] for p in points)]
        hi = [max(p[0] for p in points), max(p[1] for p in points)]
        out = []
        counts = [max(3, min(_GRID_MAX, int(math.ceil((hi[k] - lo[k]) / _GRID_STEP)))) for k in range(2)]
        for i in range(counts[0]):
            for j in range(counts[1]):
                uv = (lo[0] + (hi[0] - lo[0]) * (i + 0.5) / counts[0], lo[1] + (hi[1] - lo[1]) * (j + 0.5) / counts[1])
                if self.footprint.covers(uv):
                    out.append(uv)
        for a, b in self.segments:
            length = math.hypot(b[0] - a[0], b[1] - a[1])
            if length <= _EDGE_INSET * 4:
                continue
            mid = ((a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0)
            n = (-(b[1] - a[1]) / length, (b[0] - a[0]) / length)
            for sign in (1.0, -1.0):
                uv = (mid[0] + sign * _EDGE_INSET * n[0], mid[1] + sign * _EDGE_INSET * n[1])
                if self.footprint.covers(uv):
                    out.append(uv)
                    break
        return out

    def point(self, uv):
        return vec.add(self.origin, vec.add(vec.scale(self.x, uv[0]), vec.scale(self.y, uv[1])))

    def bounds(self):
        """The box around the prism, or None when it has no end."""
        if not (math.isfinite(self.low) and math.isfinite(self.high)) or not self.segments:
            return None
        flat = [p for a, b in self.segments for p in (a, b)]
        return box_of(vec.add(self.point(p), vec.scale(self.z, h)) for p in flat for h in (self.low, self.high))


class HalfSpace:
    """Everything on the side of the plane through `point` that its `normal` points to."""

    def __init__(self, point, normal):
        self.origin = [float(c) for c in point]
        self.normal = _unit(normal)

    def span(self, start, direction):
        height = vec.dot(vec.sub(start, self.origin), self.normal)
        rate = vec.dot(direction, self.normal)
        if abs(rate) < _EPS:
            return [(-math.inf, math.inf)] if height >= 0 else []
        t = -height / rate
        return [(t, math.inf)] if rate > 0 else [(-math.inf, t)]

    def bounds(self):
        return None


class Turned:
    """An outline (loops of capture curves in the plane of `frame`) turned about an axis that lies in that plane, by
    `sweep` degrees (0 to 360) by the right hand rule about `axis_dir`, starting `start` degrees from the outline."""

    def __init__(self, frame, loops, axis_point, axis_dir, sweep, start=0.0):
        self.point = [float(c) for c in axis_point]
        self.axis = _unit(axis_dir)
        self.sweep = min(abs(float(sweep)), 360.0)
        self.start = float(start)
        origin, x, y = [float(c) for c in frame["origin"]], _unit(frame["x"]), _unit(frame["y"])
        flat = []
        reference = None
        for curves in loops:
            for c in curves:
                points = []
                for p in polyline(c):
                    world = vec.add(origin, vec.add(vec.scale(x, p[0]), vec.scale(y, p[1])))
                    v = vec.sub(world, self.point)
                    along = vec.dot(v, self.axis)
                    radial = vec.sub(v, vec.scale(self.axis, along))
                    radius = vec.length(radial)
                    if reference is None and radius > 1e-9:
                        reference = vec.scale(radial, 1.0 / radius)
                    points.append([along, radius])
                flat.append([{"kind": "line", "start": a, "end": b} for a, b in zip(points, points[1:])])
        self.e1 = reference or _perpendicular(self.axis)
        self.e2 = vec.cross(self.axis, self.e1)
        self.footprint = Footprint({"loops": [{"curves": curves} for curves in flat]})
        corners = [p for curves in flat for c in curves for p in (c["start"], c["end"])]
        self.z_low = min(p[0] for p in corners) if corners else 0.0
        self.z_high = max(p[0] for p in corners) if corners else 0.0
        self.r_high = max(p[1] for p in corners) if corners else 0.0

    def _inside(self, p):
        v = vec.sub(p, self.point)
        along = vec.dot(v, self.axis)
        if not self.z_low <= along <= self.z_high:
            return False
        radial = vec.sub(v, vec.scale(self.axis, along))
        radius = vec.length(radial)
        if radius > self.r_high:
            return False
        if self.sweep < 360.0 - 1e-9 and radius > 1e-12:
            angle = math.degrees(math.atan2(vec.dot(radial, self.e2), vec.dot(radial, self.e1)))
            if (angle - self.start) % 360.0 > self.sweep + 1e-9:
                return False
        return self.footprint.covers((along, radius))

    def _reach(self, start, direction):
        """The part of the line inside the cylinder around the turned outline, or None."""
        v0 = vec.sub(start, self.point)
        z0, dz = vec.dot(v0, self.axis), vec.dot(direction, self.axis)
        w0 = vec.sub(v0, vec.scale(self.axis, z0))
        wd = vec.sub(direction, vec.scale(self.axis, dz))
        a, b, c = vec.dot(wd, wd), vec.dot(w0, wd), vec.dot(w0, w0) - self.r_high ** 2
        if a < _EPS:
            if c > 0:
                return None
            lo, hi = -math.inf, math.inf
        else:
            disc = b * b - a * c
            if disc < 0:
                return None
            root = math.sqrt(disc)
            lo, hi = (-b - root) / a, (-b + root) / a
        if abs(dz) < _EPS:
            if not self.z_low <= z0 <= self.z_high:
                return None
        else:
            t0, t1 = (self.z_low - z0) / dz, (self.z_high - z0) / dz
            lo, hi = max(lo, min(t0, t1)), min(hi, max(t0, t1))
        return (lo, hi) if hi > lo and math.isfinite(lo) and math.isfinite(hi) else None

    def span(self, start, direction):
        reach = self._reach(start, direction)
        if reach is None:
            return []
        return sampled(lambda t: self._inside(vec.add(start, vec.scale(direction, t))), reach[0], reach[1],
                        _TURN_SAMPLES, _TURN_HALVINGS)

    def bounds(self):
        ends = [vec.add(self.point, vec.scale(self.axis, z)) for z in (self.z_low, self.z_high)]
        reach = [self.r_high * math.sqrt(max(0.0, 1.0 - self.axis[i] ** 2)) for i in range(3)]
        return {"min": [min(e[i] for e in ends) - reach[i] for i in range(3)],
                "max": [max(e[i] for e in ends) + reach[i] for i in range(3)]}


def sampled(inside, lo, hi, samples, halvings):
    """The parts of `[lo, hi]` where `inside(t)` holds, as sorted `(t0, t1)` pairs: `samples` even steps, then
    `halvings` halvings to place each change. A part shorter than a step can be missed."""
    ts = [lo + (hi - lo) * k / samples for k in range(samples + 1)]
    return _changes(inside, ts, [inside(t) for t in ts], halvings)


def traced(probe, lo, hi, halvings, steps):
    """The parts of `[lo, hi]` inside a shape, as sorted `(t0, t1)` pairs. `probe(t)` gives whether `t` is inside and
    how far along the line (at least) the answer cannot change; each step goes that far, and at least
    `(hi - lo) / steps`. Then `halvings` halvings place each change."""
    floor = (hi - lo) / steps
    ts, states = [], []
    t = lo
    while True:
        state, clear = probe(t)
        ts.append(t)
        states.append(state)
        if t >= hi:
            break
        t = min(hi, t + max(clear, floor))
    return _changes(lambda x: probe(x)[0], ts, states, halvings)


def _changes(inside, ts, states, halvings):
    """The parts inside from the states at the sorted points `ts`, each change placed by `halvings` halvings."""
    lo, hi = ts[0], ts[-1]
    out, begin = [], (lo if states[0] else None)
    for k in range(1, len(ts)):
        if states[k] == states[k - 1]:
            continue
        a, b = ts[k - 1], ts[k]
        for _ in range(halvings):
            mid = (a + b) / 2.0
            if inside(mid) == states[k - 1]:
                a = mid
            else:
                b = mid
        edge = (a + b) / 2.0
        if states[k]:
            begin = edge
        else:
            out.append((begin, edge))
            begin = None
    if begin is not None:
        out.append((begin, hi))
    return out


class Tapered:
    """One loop of capture curves in the plane of `frame`, swept along the frame's normal from height `low` to `high`
    (finite; the outline lies at height 0, the sketch plane), its outline moved outward by `rate` times the distance
    from the sketch plane (a negative rate moves it inward): a tapered extrude, or a part of one between two heights.

    A point is inside when it lies inside the outline, or outside it by no more than that move (inside it by at least
    the move, for a negative rate). That is the tapered outline where every corner the move rounds off is smooth
    (`extents.taper_gap` copies only such outlines), the same walls Fusion and Orca build."""

    def __init__(self, frame, loop, low, high, rate):
        self.base = Prism(frame, [loop], low, high)
        self.rate = float(rate)
        self.low, self.high = self.base.low, self.base.high
        self.reach = abs(self.rate) * max(abs(self.low), abs(self.high))
        # How far (mm) the polylines the inside test reads lie from the curves the distances are measured to (the
        # middle of each chord of an arc). The level `_probe` gives can be off by that much at each end of a step, so
        # a step takes twice this off the distance to a wall.
        self.slack = max([curve_distance(c, ((a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0))
                          for c in loop for a, b in zip(polyline(c), polyline(c)[1:])] + [0.0]) + 1e-9

    def _inside(self, p):
        return self._probe(p)[0]

    def _probe(self, p):
        """Whether `p` is inside, with two levels that are 0 on the walls and below 0 inside them: `side`, the
        signed distance in the plane to the outline less the move at that height, and `end`, the distance past the
        nearer end (negative between the ends)."""
        u, v, w = self.base._local(p)
        move = self.rate * abs(w)
        gap = self.base.footprint.nearest_curve((u, v))[1]
        covered = self.base.footprint.covers((u, v))
        side, end = (-gap if covered else gap) - move, max(self.low - w, w - self.high)
        if not self.low - _EPS <= w <= self.high + _EPS:
            return False, side, end
        if covered:
            return move >= 0 or gap >= -move, side, end
        return move > 0 and gap <= move, side, end

    def _box2(self):
        """The box of the outline in its plane, grown by the largest outward move."""
        points = [p for a, b in self.base.segments for p in (a, b)]
        grow = max(0.0, self.rate) * max(abs(self.low), abs(self.high))
        return (min(p[0] for p in points) - grow, min(p[1] for p in points) - grow,
                max(p[0] for p in points) + grow, max(p[1] for p in points) + grow)

    def _reach(self, start, direction):
        """The part of the line inside the box around the shape, or None."""
        u0, v0, w0 = self.base._local(start)
        du, dv, dw = self.base._turn(direction)
        box = self._box2()
        lo, hi = -math.inf, math.inf
        for p0, d, a, b in ((u0, du, box[0], box[2]), (v0, dv, box[1], box[3]), (w0, dw, self.low, self.high)):
            if abs(d) < _EPS:
                if not a - _EPS <= p0 <= b + _EPS:
                    return None
                continue
            t0, t1 = (a - p0) / d, (b - p0) / d
            lo, hi = max(lo, min(t0, t1)), min(hi, max(t0, t1))
        return (lo, hi) if hi > lo else None

    def span(self, start, direction):
        reach = self._reach(start, direction)
        if reach is None:
            return []
        # Along the line, `side` changes at most `side_rate` per unit of t (by the move in the plane, and by the
        # growth of the outline along the normal) and `end` at most `end_rate`. Inside, the answer holds until either
        # level can reach 0; outside, until every level above 0 can.
        du, dv, dw = self.base._turn(direction)
        side_rate, end_rate = math.hypot(du, dv) + abs(self.rate * dw), abs(dw)

        def probe(t):
            inside, side, end = self._probe(vec.add(start, vec.scale(direction, t)))
            clear = (ahead(abs(side) - 2.0 * self.slack, side_rate), ahead(abs(end) - _EPS, end_rate))
            if inside:
                return True, min(clear)
            return False, max((a for a, level in zip(clear, (side, end)) if level > 0), default=0.0)

        return traced(probe, reach[0], reach[1], _TAPER_HALVINGS, _TAPER_STEPS)

    def bounds(self):
        box = self._box2()
        flat = [(box[0], box[1]), (box[2], box[1]), (box[0], box[3]), (box[2], box[3])]
        return box_of(vec.add(self.base.point(p), vec.scale(self.base.z, h)) for p in flat
                      for h in (self.low, self.high))


def ahead(distance, rate):
    """How far along a line a level `distance` from 0 cannot reach 0, when it changes at most `rate` per unit."""
    if distance <= 0:
        return 0.0
    return math.inf if rate <= _EPS else distance / rate


class Moved:
    """A shape moved rigidly: a point `p` of the shape lands on `rows * p + offset` (a turn or a mirror and a
    move)."""

    def __init__(self, shape, rows, offset):
        self.shape = shape
        self.rows = [[float(c) for c in row] for row in rows]
        self.offset = [float(c) for c in offset]

    def _back(self, v):
        return [sum(self.rows[k][i] * v[k] for k in range(3)) for i in range(3)]

    def span(self, start, direction):
        return self.shape.span(self._back(vec.sub(start, self.offset)), self._back(direction))

    def apply(self, p):
        return [sum(self.rows[i][k] * p[k] for k in range(3)) + self.offset[i] for i in range(3)]

    def bounds(self):
        box = self.shape.bounds()
        if box is None:
            return None
        lo, hi = box["min"], box["max"]
        return box_of(self.apply([x, y, z]) for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2]))


def union(a, b):
    spans = sorted(a + b)
    out = []
    for t0, t1 in spans:
        if out and t0 <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], t1))
        else:
            out.append((t0, t1))
    return out


def intersect(a, b):
    out = []
    for a0, a1 in a:
        for b0, b1 in b:
            lo, hi = max(a0, b0), min(a1, b1)
            if hi > lo:
                out.append((lo, hi))
    return sorted(out)


def subtract(a, b):
    out = list(a)
    for b0, b1 in b:
        kept = []
        for a0, a1 in out:
            if b1 <= a0 or b0 >= a1:
                kept.append((a0, a1))
                continue
            if a0 < b0:
                kept.append((a0, b0))
            if b1 < a1:
                kept.append((b1, a1))
        out = kept
    return out


def _length(spans):
    return sum(t1 - t0 for t0, t1 in spans)


def box_of(points):
    """`{min, max}` of 3D points, or None when there are none."""
    points = list(points)
    if not points:
        return None
    return {"min": [min(p[i] for p in points) for i in range(3)], "max": [max(p[i] for p in points) for i in range(3)]}


def _box_union(a, b):
    if a is None or b is None:
        return a or b
    return {"min": [min(a["min"][i], b["min"][i]) for i in range(3)],
            "max": [max(a["max"][i], b["max"][i]) for i in range(3)]}


def _perpendicular(n):
    helper = [0.0, 0.0, 1.0] if abs(n[2]) < 0.9 else [1.0, 0.0, 0.0]
    return vec.unit(vec.cross(helper, n))


_AXES = ([1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0])


def _grid(lo, hi, count):
    """`count` evenly spread values from just inside `lo` to just inside `hi`."""
    if hi - lo < 1e-9:
        return [(lo + hi) / 2.0]
    return [lo + (hi - lo) * (k + 0.5) / count for k in range(count)]


class Solid:
    """A body: shapes with how each acts (ADD, CUT or INTERSECT), in recipe order. A Solid is a shape too."""

    def __init__(self, pieces=None):
        self.pieces = list(pieces or [])
        # Shapes whose material a cut may not count on: the copy's shapes do not show what they took (the edges of
        # rounds and chamfers, `finish_body.Rounded`).
        self.unsure = []

    @property
    def empty(self):
        return not any(mode == ADD for mode, _ in self.pieces)

    def add(self, mode, shape):
        self.pieces.append((mode, shape))

    def copy(self):
        """The body as it stands now; later steps of this body do not change the copy."""
        return Solid(self.pieces)

    def moved(self, rows, offset):
        """Carry the whole body by a rigid move."""
        self.pieces = [(ADD, Moved(self.copy(), rows, offset))]

    def material(self, start, direction):
        """The parts of a line inside the part, as sorted `(t0, t1)` pairs."""
        held = []
        for mode, shape in self.pieces:
            spans = shape.span(start, direction)
            if mode == ADD:
                held = union(held, spans)
            elif mode == CUT:
                held = subtract(held, spans)
            else:
                held = intersect(held, spans)
        return held

    span = material

    def firm(self, start, direction):
        """The parts of a line inside the part that no `unsure` shape covers."""
        held = self.material(start, direction)
        for shape in self.unsure:
            held = subtract(held, shape.span(start, direction))
        return held

    def bounds(self):
        """A box that holds the body (the boxes of what it adds), or None when an added shape has no end."""
        found = None
        for mode, shape in self.pieces:
            if mode != ADD:
                continue
            box = shape.bounds()
            if box is None:
                return None
            found = _box_union(found, box)
        return found

    def meets(self, tool, sure=True):
        """True when the tool and the part share firm material (`firm`) along some line through the tool. With
        `sure` False, any material counts, also material a round or chamfer may have taken."""
        if self.empty:
            return False
        held = self.firm if sure else self.material
        if not isinstance(tool, Prism):
            return self._meets_by_lines(tool, held)
        for uv in tool.samples():
            start = tool.point(uv)
            inside = intersect(held(start, tool.z), [(tool.low, tool.high)])
            if _length(inside) > MEET_TOL:
                return True
        return False

    def _meets_by_lines(self, tool, held):
        mine, theirs = self.bounds(), tool.bounds()
        area = theirs if mine is None else (mine if theirs is None else {
            "min": [max(mine["min"][i], theirs["min"][i]) for i in range(3)],
            "max": [min(mine["max"][i], theirs["max"][i]) for i in range(3)]})
        if area is None or any(area["max"][i] < area["min"][i] for i in range(3)):
            return False
        for axis in range(3):
            others = [i for i in range(3) if i != axis]
            for a in _grid(area["min"][others[0]], area["max"][others[0]], _PROBE_LINES):
                for b in _grid(area["min"][others[1]], area["max"][others[1]], _PROBE_LINES):
                    start = [0.0, 0.0, 0.0]
                    start[others[0]], start[others[1]] = a, b
                    shared = intersect(held(start, _AXES[axis]), tool.span(start, _AXES[axis]))
                    if _length(shared) > MEET_TOL:
                        return True
        return False

    def box(self):
        """The box of the body's material `{min, max}`, or None when it is empty or has no end. Lines along each
        axis find how far the material reaches, and finer lines around the furthest one place a curved end."""
        area = self.bounds()
        if area is None:
            return None
        found = {"min": [None] * 3, "max": [None] * 3}
        for axis in range(3):
            others = [i for i in range(3) if i != axis]
            lo = [area["min"][others[0]], area["min"][others[1]]]
            hi = [area["max"][others[0]], area["max"][others[1]]]
            coarse = self._furthest(axis, others, _grid(lo[0], hi[0], _BOX_LINES), _grid(lo[1], hi[1], _BOX_LINES))
            for end in ("min", "max"):
                best = coarse[end]
                if best is None:
                    return None
                step = [(hi[k] - lo[k]) / _BOX_LINES for k in range(2)]
                for _ in range(_BOX_ROUNDS):
                    near = [[max(lo[k], best[1 + k] - step[k]), min(hi[k], best[1 + k] + step[k])] for k in range(2)]
                    finer = self._furthest(axis, others, _grid(near[0][0], near[0][1], 9),
                                           _grid(near[1][0], near[1][1], 9))[end]
                    if finer is not None and (finer[0] < best[0] if end == "min" else finer[0] > best[0]):
                        best = finer
                    step = [v / _BOX_ZOOM for v in step]
                found[end][axis] = best[0]
        return found

    def _furthest(self, axis, others, a_values, b_values):
        """`{min, max}`: `(how far, a, b)` of the lines along `axis` (through the points a, b of the other two
        axes) whose material reaches furthest each way, or None when no line meets material."""
        best = {"min": None, "max": None}
        for a in a_values:
            for b in b_values:
                start = [0.0, 0.0, 0.0]
                start[others[0]], start[others[1]] = a, b
                spans = [s for s in self.material(start, _AXES[axis]) if s[1] - s[0] > 1e-9]
                if not spans:
                    continue
                if best["min"] is None or spans[0][0] < best["min"][0]:
                    best["min"] = (spans[0][0], a, b)
                if best["max"] is None or spans[-1][1] > best["max"][0]:
                    best["max"] = (spans[-1][1], a, b)
        return best

