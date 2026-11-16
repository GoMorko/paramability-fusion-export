"""Whether one 2D region lies inside another, as an outline that must land on a face.

A region is a list of closed loops (`{ curves }`, outer loop and holes alike) of capture curves in one 2D frame: lines,
arcs and circles are exact, ellipses and free curves are their polylines (`footprint.polyline`). `inside` splits each
boundary where it meets the other boundary and tests the middle of every piece, so a straight edge that crosses the
other region between two corners is found. `moved_loops` brings the loops of one frame into another along a map of
points. `sample_points` spreads points over a region, along its curves and on a grid inside it.
"""
import math

from .footprint import arc_span, is_full, polyline

# The largest gap (mm) between an arc and the chords that stand for it in the inside test (`_ring_segments`).
SAG = 1e-5
MAX_ARC_CHORDS = 20000
# A run of a curve shorter than this share of its parameter range has no middle to test.
TINY = 1e-9
PARALLEL = 1e-12


class _Seg:
    def __init__(self, a, b):
        self.a, self.b = a, b
        self.box = (min(a[0], b[0]), min(a[1], b[1]), max(a[0], b[0]), max(a[1], b[1]))

    def at(self, t):
        return [self.a[0] + t * (self.b[0] - self.a[0]), self.a[1] + t * (self.b[1] - self.a[1])]

    def ends(self):
        return [self.a, self.b]

    def length(self):
        return math.hypot(self.b[0] - self.a[0], self.b[1] - self.a[1])

    def normal(self, t):
        dx, dy = self.b[0] - self.a[0], self.b[1] - self.a[1]
        size = math.hypot(dx, dy)
        return [-dy / size, dx / size] if size > 0 else None

    def param(self, p):
        dx, dy = self.b[0] - self.a[0], self.b[1] - self.a[1]
        size = dx * dx + dy * dy
        return 0.0 if size <= 0 else max(0.0, min(1.0, ((p[0] - self.a[0]) * dx + (p[1] - self.a[1]) * dy) / size))

    def distance(self, p):
        q = self.at(self.param(p))
        return math.hypot(p[0] - q[0], p[1] - q[1])

    def chords(self):
        return [(self.a, self.b)]


class _Arc:
    def __init__(self, center, radius, a0, sweep):
        self.c, self.r, self.a0, self.sweep = center, radius, a0, sweep
        self.full = abs(abs(sweep) - 2 * math.pi) <= 1e-12
        self.box = (center[0] - radius, center[1] - radius, center[0] + radius, center[1] + radius)

    def at(self, t):
        angle = self.a0 + t * self.sweep
        return [self.c[0] + self.r * math.cos(angle), self.c[1] + self.r * math.sin(angle)]

    def ends(self):
        return [] if self.full else [self.at(0.0), self.at(1.0)]

    def length(self):
        return self.r * abs(self.sweep)

    def normal(self, t):
        angle = self.a0 + t * self.sweep
        return [math.cos(angle), math.sin(angle)]

    def param_of_angle(self, angle):
        """The parameter of the point at `angle` on the circle, or None when it lies off the arc."""
        turned = (angle - self.a0) % (2 * math.pi)
        if self.sweep < 0:
            turned = turned - 2 * math.pi if turned > 0 else 0.0
        t = turned / self.sweep if self.sweep else 0.0
        if -TINY <= t <= 1 + TINY:
            return min(max(t, 0.0), 1.0)
        return None

    def param(self, p):
        t = self.param_of_angle(math.atan2(p[1] - self.c[1], p[0] - self.c[0]))
        if t is not None:
            return t
        a, b = self.at(0.0), self.at(1.0)
        return 0.0 if math.hypot(p[0] - a[0], p[1] - a[1]) <= math.hypot(p[0] - b[0], p[1] - b[1]) else 1.0

    def distance(self, p):
        q = self.at(self.param(p))
        return math.hypot(p[0] - q[0], p[1] - q[1])

    def chords(self):
        step = 2 * math.acos(max(-1.0, 1 - SAG / self.r)) if self.r > SAG else math.pi
        n = max(8, min(MAX_ARC_CHORDS, int(math.ceil(abs(self.sweep) / step))))
        points = [self.at(k / n) for k in range(n + 1)]
        return list(zip(points, points[1:]))


def _pieces(curve):
    """The exact pieces of one capture curve: `_Seg`s and `_Arc`s. Raises KeyError or TypeError on a curve that does
    not read."""
    kind = curve["kind"]
    if kind == "line":
        return [_Seg(list(curve["start"]), list(curve["end"]))]
    if kind in ("arc", "circle"):
        if is_full(curve):
            return [_Arc(list(curve["center"]), float(curve["radius"]), 0.0, 2 * math.pi)]
        a0, sweep = arc_span(curve)
        return [_Arc(list(curve["center"]), float(curve["radius"]), a0, sweep)]
    points = polyline(curve)
    if not points or len(points) < 2:
        raise ValueError("a curve without points")
    return [_Seg(list(a), list(b)) for a, b in zip(points, points[1:])]


class _Region:
    def __init__(self, loops):
        self.pieces = [piece for loop in loops for curve in loop.get("curves") or [] for piece in _pieces(curve)]
        self.chords = [chord for piece in self.pieces for chord in piece.chords()]

    def distance(self, p):
        return min((piece.distance(p) for piece in self.pieces), default=math.inf)

    def covers(self, p):
        """True when `p` lies inside the region (even-odd rule over chords no farther than `SAG` from the curves)."""
        crossings = 0
        for a, b in self.chords:
            if (a[1] > p[1]) != (b[1] > p[1]):
                if a[0] + (p[1] - a[1]) * (b[0] - a[0]) / (b[1] - a[1]) > p[0]:
                    crossings += 1
        return crossings % 2 == 1


def _boxes_meet(a, b, tol):
    return a[0] <= b[2] + tol and b[0] <= a[2] + tol and a[1] <= b[3] + tol and b[1] <= a[3] + tol


def _seg_seg(s, q):
    rx, ry = s.b[0] - s.a[0], s.b[1] - s.a[1]
    qx, qy = q.b[0] - q.a[0], q.b[1] - q.a[1]
    den = rx * qy - ry * qx
    if abs(den) <= PARALLEL * max(1.0, math.hypot(rx, ry) * math.hypot(qx, qy)):
        return []
    wx, wy = q.a[0] - s.a[0], q.a[1] - s.a[1]
    t, u = (wx * qy - wy * qx) / den, (wx * ry - wy * rx) / den
    if -TINY <= t <= 1 + TINY and -TINY <= u <= 1 + TINY:
        return [(min(max(t, 0.0), 1.0), min(max(u, 0.0), 1.0))]
    return []


def _seg_arc(s, arc):
    """(t on the segment, t on the arc) of each point where they meet."""
    dx, dy = s.b[0] - s.a[0], s.b[1] - s.a[1]
    fx, fy = s.a[0] - arc.c[0], s.a[1] - arc.c[1]
    a = dx * dx + dy * dy
    if a <= 0:
        return []
    b = 2 * (fx * dx + fy * dy)
    c = fx * fx + fy * fy - arc.r * arc.r
    disc = b * b - 4 * a * c
    if disc < 0:
        return []
    root = math.sqrt(disc)
    out = []
    for t in {(-b - root) / (2 * a), (-b + root) / (2 * a)}:
        if -TINY <= t <= 1 + TINY:
            p = s.at(t)
            u = arc.param_of_angle(math.atan2(p[1] - arc.c[1], p[0] - arc.c[0]))
            if u is not None:
                out.append((min(max(t, 0.0), 1.0), u))
    return out


def _arc_arc(one, two):
    dx, dy = two.c[0] - one.c[0], two.c[1] - one.c[1]
    d = math.hypot(dx, dy)
    if d <= PARALLEL or d > one.r + two.r or d < abs(one.r - two.r):
        return []
    a = (one.r * one.r - two.r * two.r + d * d) / (2 * d)
    h = math.sqrt(max(one.r * one.r - a * a, 0.0))
    mx, my = one.c[0] + a * dx / d, one.c[1] + a * dy / d
    out = []
    for p in {(mx - h * dy / d, my + h * dx / d), (mx + h * dy / d, my - h * dx / d)}:
        t = one.param_of_angle(math.atan2(p[1] - one.c[1], p[0] - one.c[0]))
        u = two.param_of_angle(math.atan2(p[1] - two.c[1], p[0] - two.c[0]))
        if t is not None and u is not None:
            out.append((t, u))
    return out


def _meets(p, q):
    if isinstance(p, _Seg) and isinstance(q, _Seg):
        return _seg_seg(p, q)
    if isinstance(p, _Seg):
        return _seg_arc(p, q)
    if isinstance(q, _Seg):
        return [(t, u) for u, t in _seg_arc(q, p)]
    return _arc_arc(p, q)


def _cuts(one, two, tol):
    """Per piece of `one` and of `two`, the parameters where it is cut: its ends, where it meets a piece of the other
    region, and where a corner of the other region lies on it (within `tol`)."""
    cuts_one = [{0.0, 1.0} for _ in one.pieces]
    cuts_two = [{0.0, 1.0} for _ in two.pieces]
    for i, p in enumerate(one.pieces):
        for j, q in enumerate(two.pieces):
            if not _boxes_meet(p.box, q.box, tol):
                continue
            for t, u in _meets(p, q):
                cuts_one[i].add(t)
                cuts_two[j].add(u)
            for corner in q.ends():
                if p.distance(corner) <= tol:
                    cuts_one[i].add(p.param(corner))
            for corner in p.ends():
                if q.distance(corner) <= tol:
                    cuts_two[j].add(q.param(corner))
    return cuts_one, cuts_two


def _middles(piece, cuts):
    """(middle point, parameter) of each run of `piece` between two of its cuts."""
    ts = sorted(cuts)
    return [(piece.at((a + b) / 2), (a + b) / 2) for a, b in zip(ts, ts[1:]) if b - a > TINY]


def inside(inner_loops, outer_loops, tol):
    """Whether the region of `inner_loops` lies in the region of `outer_loops` (outer loop less its holes), touching
    its boundary allowed: True or False. Both are loops of capture curves in one 2D frame; `tol` (mm) is how far a
    point may lie past the boundary and still count as on it.

    Each boundary is cut where it meets the other one and at the other's corners. Then every run of the inner
    boundary must lie in the outer region or on its boundary, and no run of the outer boundary may lie inside the
    inner region. A run of the inner boundary that lies on the outer boundary must have the outer region on its inner
    side, else the inner region fills a hole (or the outside) of the outer one. Raises ValueError, KeyError or
    TypeError on a curve that does not read."""
    one, two = _Region(inner_loops), _Region(outer_loops)
    if not one.pieces or not two.pieces:
        raise ValueError("a region without curves")
    cuts_one, cuts_two = _cuts(one, two, tol)
    step = 10 * tol
    for piece, cuts in zip(one.pieces, cuts_one):
        for middle, t in _middles(piece, cuts):
            if two.distance(middle) > tol:
                if not two.covers(middle):
                    return False
                continue
            normal = piece.normal(t)
            if normal is None:
                continue
            sides = [[middle[0] + k * step * normal[0], middle[1] + k * step * normal[1]] for k in (1, -1)]
            inner = [p for p in sides if one.covers(p) and one.distance(p) > step / 2]
            if len(inner) == 1 and two.distance(inner[0]) > step / 2 and not two.covers(inner[0]):
                return False
    for piece, cuts in zip(two.pieces, cuts_two):
        for middle, _ in _middles(piece, cuts):
            if one.distance(middle) > tol and one.covers(middle):
                return False
    return True


def _moved_curve(curve, move, exact):
    """`curve` with its points moved by `move`. With `exact` the move keeps lengths, so an arc or circle stays one;
    otherwise every curve that is not a line becomes its points (a free curve)."""
    kind = curve["kind"]
    if kind == "line":
        return {"kind": "line", "start": move(curve["start"]), "end": move(curve["end"])}
    if exact and kind == "circle":
        return {"kind": "circle", "center": move(curve["center"]), "radius": curve["radius"]}
    if exact and kind == "arc":
        return dict({key: move(curve[key]) for key in ("start", "mid", "end", "center")}, kind="arc",
                    radius=curve["radius"])
    if kind in ("arc", "circle"):
        arc = _pieces(curve)[0]
        points = [arc.at(0.0)] + [b for _, b in arc.chords()]
    else:
        points = polyline(curve)
    moved = [move(p) for p in points]
    return {"kind": "other", "start": moved[0], "end": moved[-1], "samples": moved}


def moved_loops(loops, move, exact):
    """The loops with every point moved by `move` (a 2D point to a 2D point, or None); None when a point does not
    move. `exact` says the move keeps lengths (see `_moved_curve`)."""
    out = []
    for loop in loops:
        curves = [_moved_curve(curve, move, exact) for curve in loop.get("curves") or []]
        if any(_has_none(curve) for curve in curves):
            return None
        out.append(dict(loop, curves=curves))
    return out


def _has_none(curve):
    return any(value is None for key, value in curve.items() if key != "kind") or (
        curve["kind"] == "other" and any(p is None for p in curve["samples"]))


def sample_points(loops, most, tol):
    """At most `most` points of the region of `loops`: up to two thirds of them evenly spaced along its curves, then
    the points of an even grid over the region's box that lie inside it farther than `tol` from its curves. Raises
    ValueError, KeyError or TypeError on a curve that does not read."""
    region = _Region(loops)
    total = sum(piece.length() for piece in region.pieces)
    if not region.pieces or total <= 0:
        raise ValueError("a region without curves")
    spacing = total / max(1, most * 2 // 3)
    edge = []
    for piece in region.pieces:
        count = max(1, int(math.ceil(piece.length() / spacing - 1e-9)))
        edge += [piece.at(k / count) for k in range(count)]
    edge = edge[:most * 2 // 3] if len(edge) > most * 2 // 3 else edge
    lo_x = min(piece.box[0] for piece in region.pieces)
    lo_y = min(piece.box[1] for piece in region.pieces)
    hi_x = max(piece.box[2] for piece in region.pieces)
    hi_y = max(piece.box[3] for piece in region.pieces)
    side = max(1, int(math.sqrt(max(0, most - len(edge)))))
    grid = [[lo_x + (hi_x - lo_x) * (i + 0.5) / side, lo_y + (hi_y - lo_y) * (j + 0.5) / side]
            for i in range(side) for j in range(side)]
    return edge + [p for p in grid if region.covers(p) and region.distance(p) > tol]
