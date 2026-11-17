"""The faces of a revolve, for picks that follow sizes (see faces/follow.py).

A revolve turns its outline about an axis in the sketch plane. Each face it makes is one outline curve turned about
the axis, and each edge between two such faces is one outline corner turned about it. A measured point is read as its
height along the axis, its distance from the axis and its angle about the axis from the sketch. The height and the
distance give a point of the sketch plane. A face point must lie on exactly one outline curve, an edge point at the
corner where two curves meet. At other sizes that sketch point moves with the outline as the probe measured it
(`sketch_motion.Outline.follow`: the same share along a line, an arc only when it keeps its shape), and the picked
point keeps its angle about the axis, which may move too.

A curve that lies on the axis makes no face. The end faces of a revolve that turns less than a full circle are not
placed. Nor are a point on two curves away from a corner they share, a face point at a corner, an edge point inside
one face, and a point that also lies on a face of an earlier step: where two faces meet, a mark is better than a
guess. Such a point is claimed, so its sizes are marked, when the face under it moves with sizes. On a face that
stays, the step that made the edge there (a cut through the face) still places it, as without the revolve.

A picked curve must keep its length over the size ranges, and the turn of a revolve that is not a full circle must
still reach the angle of the point: the ranges are cut where they would not (`RevolvePlace.cuts`).

The material of a revolve is not modelled (`material_at`): the checks that need all the material of the part
(`follow.inside`, faces/floating.py) treat a revolve as a step they bound on their own.
"""
import math

from ...design_model.values import Quantity
from ...geometry import vec
from ...geometry.footprint import Footprint, curve_distance, polyline
from ...sketch_values.motion import Affine, Stuck
from ..sketch.sketch_motion import PICK_TOL, combine, rendered
from .placer import Placer
from .slabs import CONSTANT_TOL, LATERAL_TOL, cleaned_all

# A picked curve must stay longer than this (mm), and a partial turn must pass the angle of a picked point by more
# than this (degrees).
LENGTH_TOL_MM = 1e-3
ANGLE_TOL_DEG = 1e-3

IN, CAP, OUT = "in", "cap", "out"


class Turn:
    """What a revolve step turns, as the translator wrote it: `profile` the capture profile (its frame and curves),
    `outline` the sketch_motion.Outline when the sketch follows sizes (else None), `table` the size table,
    `axis_point` the axis point in sketch coordinates (numbers) and `axis_raw` its raw (x, y) when it moves with
    sizes (else None), `axis_dir` the unit axis direction in sketch coordinates as written (the turn is by the right
    hand rule about it). The turn starts `back` degrees before the sketch plane and runs `total` degrees (a Quantity);
    `total` is None for a full circle."""

    def __init__(self, profile, outline, table, axis_point, axis_raw, axis_dir, back=0.0, total=None):
        self.frame = profile["frame"]
        self.footprint = Footprint(profile)
        self.outline, self.table = outline, table
        self.axis_point, self.axis_raw = list(axis_point), axis_raw
        size = math.hypot(axis_dir[0], axis_dir[1])
        self.axis_dir = [axis_dir[0] / size, axis_dir[1] / size]
        self.back, self.total = back, total

    @property
    def moves(self):
        """True when a size moves the outline, its plane or the axis, or changes the angle of the turn."""
        if self.total is not None and self.total.sized:
            return True
        if self.axis_raw is not None:
            return True
        outline = self.outline
        if outline is None:
            return False
        return outline.moves or not _constant(outline.plane)


def _constant(value):
    return isinstance(value, Affine) and value.is_constant


def _tidy(value):
    """A raw value with a constant left over from rounding dropped, so the formula holds no "+ 0"."""
    if isinstance(value, Affine) and value.terms and abs(value.const) <= CONSTANT_TOL:
        return Affine(0.0, value.terms, value.sketch)
    return value


class _Spot:
    """Where a point sits about the axis: `uv` the sketch point it turns from, `radius` its distance from the axis,
    `angle` its angle about the axis from the sketch plane (degrees), `span` IN, CAP or OUT of the turn, `curves` the
    face curves within reach of `uv`."""

    def __init__(self, uv, radius, angle, span, curves):
        self.uv, self.radius, self.angle, self.span, self.curves = uv, radius, angle, span, curves


class RevolvePlace:
    """Where a point sits on a revolve: on the face of outline curve `curve`, or on the edge of outline corner
    `corner`. `slab` is the placer (read for its `id` and `is_copy`). The coordinates are those of the point it was
    placed from. `cuts` are `(Quantity, floor, why)`: the pick holds only while the Quantity stays above the floor;
    `why(picker)` words the reason."""

    which = "revolve"
    factor = 0.0
    lateral = None
    keeps = ()

    def __init__(self, placer, curve, corner, coords, blocked=(), cuts=()):
        self.slab = placer
        self.curve, self.corner = curve, corner
        self.slabs = []
        self.blocked = list(blocked)
        self.cuts = list(cuts)
        self._coords = list(coords)

    @property
    def moves(self):
        return any(q.sized for q in self._coords)

    def quantities(self, p):
        return list(self._coords)

    def coordinates(self, p):
        return cleaned_all(self.quantities(p))


class RevolvePlacer(Placer):
    """The faces of one written revolve step `step_id` (named `label` in reasons): `turn` is its `Turn`, `before` the
    placers of the steps written before it, whose faces a point of the revolve may also lie on, `combine` how it
    meets the part (new, add or cut)."""

    is_copy = False
    taper = None

    def __init__(self, step_id, label, turn, before, combine="add"):
        self.id, self.label, self.combine = step_id, label, combine
        self.turn = turn
        self.before = list(before)
        self.moves = turn.moves
        foot, axis = turn.footprint, turn.axis_dir
        self._normal = [-axis[1], axis[0]]
        reach = [self._across(q) for curve in foot.curves for q in polyline(curve)]
        if reach and max(reach, key=abs) < 0:
            self._normal = [axis[1], -axis[0]]
        self._faces = [n for n, curve in enumerate(foot.curves) if not self._on_axis(curve)]

    # ---- the sketch plane and the axis

    def _across(self, uv):
        """How far the sketch point `uv` lies from the axis, positive on the side of `_normal`."""
        a, n = self.turn.axis_point, self._normal
        return (uv[0] - a[0]) * n[0] + (uv[1] - a[1]) * n[1]

    def _on_axis(self, curve):
        if curve["kind"] != "line":
            return False
        return all(abs(self._across(curve[end])) <= LATERAL_TOL for end in ("start", "end"))

    def _axes(self):
        """(A, W, N, B) in model space: the axis point, the axis direction, the direction from the axis toward the
        outline in the sketch plane, and W x N, where a right hand turn about W takes N."""
        frame, a, d, n = self.turn.frame, self.turn.axis_point, self.turn.axis_dir, self._normal
        on_plane = [frame["origin"][i] + a[0] * frame["x"][i] + a[1] * frame["y"][i] for i in range(3)]
        w = [d[0] * frame["x"][i] + d[1] * frame["y"][i] for i in range(3)]
        out = [n[0] * frame["x"][i] + n[1] * frame["y"][i] for i in range(3)]
        return on_plane, w, out, vec.cross(w, out)

    def _span(self, angle, radius):
        """IN when the turn covers `angle` (degrees from the sketch plane), CAP when the point lies on an end face of
        a partial turn, else OUT."""
        total = self.turn.total
        if total is None or radius <= LATERAL_TOL:
            return IN
        past = (angle + self.turn.back) % 360.0
        reach = math.radians(1.0) * radius
        if min(past, 360.0 - past) * reach <= LATERAL_TOL or abs(past - total.n) * reach <= LATERAL_TOL:
            return CAP
        return IN if past < total.n else OUT

    def _spot(self, p):
        a, w, n, b = self._axes()
        v = vec.sub(p, a)
        height, flat, out = vec.dot(v, w), vec.dot(v, n), vec.dot(v, b)
        radius = math.hypot(flat, out)
        angle = math.degrees(math.atan2(out, flat)) if radius > LATERAL_TOL else 0.0
        d, m, at = self.turn.axis_dir, self._normal, self.turn.axis_point
        uv = [at[0] + height * d[0] + radius * m[0], at[1] + height * d[1] + radius * m[1]]
        curves = [k for k in self._faces if curve_distance(self.turn.footprint.curves[k], uv) <= LATERAL_TOL]
        return _Spot(uv, radius, angle, self._span(angle, radius), curves)

    def _axis_stays(self):
        """True when no size moves the axis or the sketch plane."""
        outline = self.turn.outline
        return self.turn.axis_raw is None and (outline is None or _constant(outline.plane))

    def _still(self, k):
        """True when the face of outline curve `k` stays where it is at every size: the axis and the sketch plane stay,
        and the curve only slides along itself (a line) or does not move at all (any other curve)."""
        outline = self.turn.outline
        if not self._axis_stays():
            return False
        if outline is None or not outline.moves:
            return True
        curve = self.turn.footprint.curves[k]
        if curve["kind"] not in ("line", "arc"):
            return False
        ends = [outline.anchors.point(curve[end], PICK_TOL) for end in ("start", "mid", "end") if end in curve]
        if any(end is None for end in ends):
            return False
        if curve["kind"] == "arc":
            return all(_constant(c) for end in ends for c in end)
        a, b = curve["start"], curve["end"]
        gap = math.hypot(b[0] - a[0], b[1] - a[1])
        if gap <= LENGTH_TOL_MM:
            return False
        n = [-(b[1] - a[1]) / gap, (b[0] - a[0]) / gap]
        return all(_constant(combine([(n[0], end[0]), (n[1], end[1])], outline.sketch)) for end in ends)

    def _on_earlier(self, p):
        return any(placer.place(p, False) is not None or placer.claims(p) for placer in self.before)

    # ---- the placer protocol

    def edge_count(self, which):
        """None: a pick never names the edges of a revolve as a whole."""
        return None

    def material_at(self, p):
        return None

    def place(self, p, edge):
        """The RevolvePlace of point `p` on a face (`edge` False) or an edge (`edge` True) of this revolve, or None."""
        spot = self._spot(p)
        if spot.span != IN or not spot.curves:
            return None
        curve, corner = self._pick(spot, edge)
        if curve is None and corner is None:
            return None
        if self._on_earlier(p):
            return None
        return self._placed(p, spot, curve, corner, edge)

    def claims(self, p):
        """True when `p` lies on a face of this revolve (an end face too) that moves with sizes: a point `place` does
        not place there is marked, not left to an earlier step. On a face that stays, the other step that makes an edge
        there (a cut through the face) still places the point."""
        if not self.moves:
            return False
        spot = self._spot(p)
        moving = any(not self._still(k) for k in spot.curves)
        if spot.span == IN:
            return moving
        if spot.span != CAP or not (spot.curves or self.turn.footprint.covers(spot.uv)):
            return False
        total = self.turn.total
        return moving or not self._axis_stays() or (total is not None and total.sized)

    def hollowed(self, p, opened, thickness):
        """True when a shell that goes inward by `thickness` (mm) leaves no face of this revolve at `p` that it can
        place: `p` lies on an inner wall (inside the turned outline, `thickness` from the nearest face that stays), or
        only on faces of the outline curves in `opened` (the faces the shell opens). `opened` is None when one of them
        could not be told: any face may be open, and every point on or inside the revolve counts."""
        spot = self._spot(p)
        if spot.span == OUT:
            return False
        foot = self.turn.footprint
        if spot.curves:
            return opened is None or all(curve in opened for curve in spot.curves)
        if spot.span != IN or not foot.covers(spot.uv):
            return False
        if opened is None:
            return True
        kept = [curve_distance(foot.curves[k], spot.uv) for k in self._faces if k not in opened]
        return bool(kept) and abs(min(kept) - thickness) <= LATERAL_TOL

    # ---- placing a point

    def _pick(self, spot, edge):
        """(curve, corner): the one face curve under a face point, or the corner of two curves under an edge point;
        (None, None) when the point is not placed so."""
        foot = self.turn.footprint
        if len(spot.curves) == 1:
            return (None, None) if edge else (spot.curves[0], None)
        if len(spot.curves) != 2 or not edge:
            return None, None
        corner = foot.corner_at(spot.uv, LATERAL_TOL)
        if corner is None:
            return None, None
        at = foot.corners[corner]
        ends = [foot.curves[k][end] for k in spot.curves for end in ("start", "end")]
        if sum(1 for q in ends if math.hypot(q[0] - at[0], q[1] - at[1]) <= LATERAL_TOL) != 2:
            return None, None
        return None, corner

    def _moved_uv(self, spot, curve, corner, edge):
        """The raw (x, y) the sketch point of the spot moves to, or a Stuck."""
        outline = self.turn.outline
        found = outline.follow(self.turn.footprint, "revolve", curve, corner, spot.uv, edge) if outline else None
        if found is None:
            return [Affine(spot.uv[0]), Affine(spot.uv[1])]
        return found if isinstance(found, Stuck) else list(found)

    def _placed(self, p, spot, curve, corner, edge):
        moved = self._moved_uv(spot, curve, corner, edge)
        plain = [Quantity(float(c)) for c in p]
        if isinstance(moved, Stuck):
            return RevolvePlace(self, curve, corner, plain, [moved])
        turn, sketch = self.turn, (self.turn.outline.sketch if self.turn.outline else "")
        frame, d, m = turn.frame, turn.axis_dir, self._normal
        at = turn.axis_raw or [Affine(turn.axis_point[0]), Affine(turn.axis_point[1])]
        lift = Affine(0.0)
        if turn.outline is not None:
            lift = combine([(1.0, turn.outline.plane), (-1.0, turn.outline.plane0)], sketch)
        along = combine([(d[0], moved[0]), (d[1], moved[1]), (-d[0], at[0]), (-d[1], at[1])], sketch)
        across = combine([(m[0], moved[0]), (m[1], moved[1]), (-m[0], at[0]), (-m[1], at[1])], sketch)
        _, w, n, b = self._axes()
        cos, sin = math.cos(math.radians(spot.angle)), math.sin(math.radians(spot.angle))
        coords = []
        for i in range(3):
            value = combine([(1.0, frame["origin"][i]), (frame["z"][i], lift), (frame["x"][i], at[0]),
                             (frame["y"][i], at[1]), (w[i], along), (cos * n[i] + sin * b[i], across)], sketch)
            q = rendered(turn.table, _tidy(value), float(p[i]))
            if isinstance(q, Stuck):
                return RevolvePlace(self, curve, corner, plain, [q])
            coords.append(q)
        cuts, blocked = self._cuts(spot, curve, corner)
        return RevolvePlace(self, curve, corner, coords, blocked, cuts)

    def _cuts(self, spot, curve, corner):
        """(cuts, blocked) of a pick: each picked curve keeps its length, and a partial turn keeps reaching the
        point's angle."""
        turn, foot = self.turn, self.turn.footprint
        cuts, blocked = [], []
        picked = [curve] if curve is not None else spot.curves
        for k in picked:
            found = self._length(foot.curves[k])
            if isinstance(found, Stuck):
                blocked.append(found)
            elif found is not None:
                cuts.append((found, LENGTH_TOL_MM, lambda picker: "a side of the outline of %s that %s picks would "
                             "shrink to nothing" % (self.label, picker)))
        total = turn.total
        if total is not None and total.sized and spot.radius > LATERAL_TOL:
            past = (spot.angle + turn.back) % 360.0
            cuts.append((total.plus(-past), ANGLE_TOL_DEG, lambda picker: "%s would no longer turn as far as the "
                         "place %s picks" % (self.label, picker)))
        return cuts, blocked

    def _length(self, curve):
        """How far the ends of a line or arc lie apart along the direction they lie apart now, as a sized Quantity;
        None when the curve has no ends or nothing moves them, a Stuck when they cannot follow."""
        outline = self.turn.outline
        if outline is None or curve["kind"] not in ("line", "arc"):
            return None
        a, b = curve["start"], curve["end"]
        gap = math.hypot(b[0] - a[0], b[1] - a[1])
        if gap <= LENGTH_TOL_MM:
            return None
        u = [(b[0] - a[0]) / gap, (b[1] - a[1]) / gap]
        raw_a, raw_b = outline.anchors.point(a, PICK_TOL), outline.anchors.point(b, PICK_TOL)
        if raw_a is None or raw_b is None:
            return None
        value = combine([(u[0], raw_b[0]), (u[1], raw_b[1]), (-u[0], raw_a[0]), (-u[1], raw_a[1])], outline.sketch)
        q = rendered(self.turn.table, value, gap)
        if isinstance(q, Stuck):
            return q
        return q if q.sized else None
