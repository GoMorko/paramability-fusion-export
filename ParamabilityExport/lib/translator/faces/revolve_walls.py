"""The inner walls that a shell going inward leaves on a revolve, for picks that follow sizes (see faces/shells.py).

A face of a revolve is one outline curve turned about the axis, and its normal lies in the plane of the outline. So a
shell of thickness t makes the inner wall of that face from the curve moved t into the outline, turned about the axis.
A point on an inner wall is moved back out onto the outer face (or corner), placed there by the revolve
(faces/revolve_placer.py), and moved in again by the thickness as a formula. These points are placed:

- a point inside one inner wall: the outer point lies on the curve, the move is the curve's normal;
- an edge where the inner walls of two straight curves meet at a corner of the outline: the outer point is the
  corner, the move runs along the bisector of the two normals, further for a sharp corner (as for an extrude);
- an edge where an inner wall meets a face the shell opens (the inner rim of a cup), and a point on the rim that is
  left of the opened face: the outer point is the corner of the wall and the opened curve, the move runs along the
  opened curve.

The move must be the same at every size, so a straight curve that a size turns is not placed. The ranges are cut
where an inner wall would shrink to nothing, or the opening would close.

Not placed: a revolve that does not turn a full circle; a point near a corner where an inner wall rounds off, meets
a curved wall at an angle or ends on the axis away from a line on it; a point closer than the thickness to a kept
face; a point whose outer face, or the face next to it, another step covers (an extrude joined to it, or a second
outline of the same revolve that has no joined outline with it); a point that a step before the shell places or
claims. The shell claims such a point (`RevolvePlacer.hollowed`), so its sizes are marked. Outlines of one revolve
that share a curve are placed as the one outline they make together (faces/revolve_joined.py), so an inner wall that
runs across them is placed there.
"""
import math

from ...design_model.values import Quantity
from ...geometry.footprint import curve_distance, nearest_point
from .placer import ADD
from .revolve_placer import LENGTH_TOL_MM, RevolvePlace, RevolvePlacer
from .slabs import LATERAL_TOL

# How far past an outer face (mm) a point is tested for the material of other steps.
OUT_STEP = 0.01
# Two unit directions whose dot product is this close to 1 count as the same.
SAME_TOL = 1e-9
# A curved wall must end square to its corner within this (dot product).
SQUARE_TOL = 1e-6


class InnerTurnPlace(RevolvePlace):
    """A point on an inner wall of a shelled revolve: `outer` is the RevolvePlace of the outer point it was moved
    from, `offset` the model move from the inner point to the outer one per millimetre of `thickness` (a Quantity),
    `cuts` the rules that keep the inner wall there."""

    def __init__(self, outer, offset, thickness, cuts=()):
        RevolvePlace.__init__(self, outer.slab, outer.curve, outer.corner, outer.quantities(None), outer.blocked,
                              list(outer.cuts) + list(cuts))
        self.offset, self.thickness = offset, thickness

    @property
    def moves(self):
        return RevolvePlace.moves.fget(self) or self.thickness.sized

    def quantities(self, p):
        out = []
        for q, o in zip(RevolvePlace.quantities(self, p), self.offset):
            out.append(q.plus(self.thickness.scaled(-o)) if abs(o) > SAME_TOL else q)
        return out


def _unit(a, b):
    """The unit direction from `a` to `b`, or None when they meet."""
    d = [b[0] - a[0], b[1] - a[1]]
    size = math.hypot(d[0], d[1])
    return None if size <= LENGTH_TOL_MM else [d[0] / size, d[1] / size]


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1]


def _gap(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _mid(curve):
    if curve["kind"] == "line":
        return [(curve["start"][0] + curve["end"][0]) / 2.0, (curve["start"][1] + curve["end"][1]) / 2.0]
    return curve.get("mid")


def inner_place(revolve, p, edge, opened, thickness, others):
    """The InnerTurnPlace of point `p` on an inner wall that a shell going inward by `thickness` (a Quantity) leaves on
    `revolve` (a RevolvePlacer), or None. `opened` holds the outline curves of the faces the shell opens, `others` the
    placers written before the shell besides `revolve`. `edge` asks for a point on an edge."""
    if revolve.turn.total is not None or not thickness.n > 0:
        return None
    spot = revolve.spot(p)
    walls = _Walls(revolve, opened, thickness, others, spot.angle)
    found = walls.place(spot, edge)
    if found is None or any(o.place(p, False) is not None or o.claims(p) for o in others):
        return None
    return found


class _Walls:
    """The outline of `revolve` as a shell of `thickness` sees it in the half plane `angle` degrees about the axis:
    `opened` the outline curves of the faces it opens, `others` the placers written before the shell besides it."""

    def __init__(self, revolve, opened, thickness, others, angle):
        self.revolve, self.opened, self.thickness, self.others = revolve, set(opened), thickness, others
        self.angle, self.t = angle, thickness.n
        self.curves = revolve.turn.footprint.curves
        self.foot = revolve.turn.footprint
        self.kept = [k for k in revolve.face_curves if k not in self.opened]

    # ---- which place the point is

    def place(self, spot, edge):
        uv, on = spot.uv, spot.curves
        if any(k not in self.opened for k in on) or len(on) > 1:
            return None
        gaps = {k: curve_distance(self.curves[k], uv) for k in self.kept}
        walls = [k for k, gap in gaps.items() if abs(gap - self.t) <= LATERAL_TOL]
        if on:
            if not edge:
                return self._on_rim(uv, on[0])
            if len(walls) != 1 or min(gaps.values()) < self.t - LATERAL_TOL:
                return None
            return self._rim_edge(uv, walls[0], on[0])
        if not self.foot.covers(uv) or not gaps or min(gaps.values()) < self.t - LATERAL_TOL:
            return None
        if not edge and len(walls) == 1:
            return self._on_wall(uv, walls[0])
        if edge and len(walls) == 2:
            return self._corner(uv, walls[0], walls[1])
        return None

    def _on_wall(self, uv, k):
        """A point inside the inner wall of curve `k`."""
        curve = self.curves[k]
        if curve["kind"] not in ("line", "arc") or not self.revolve.keeps_direction(k):
            return None
        f, _ = nearest_point(curve, uv)
        n = self.normal(k, f)
        if n is None or _gap([f[0] - self.t * n[0], f[1] - self.t * n[1]], uv) > LATERAL_TOL or self.covered(k, f):
            return None
        cuts = self._arc_cuts(k, f, n) if curve["kind"] == "arc" else self._line_cuts(k, f)
        if cuts is None:
            return None
        return self._placed(f, False, k, None, n, cuts)

    def _corner(self, uv, k, j):
        """An edge where the inner walls of the straight curves `k` and `j` meet at their corner."""
        v = self.shared(k, j)
        if v is None or not (self.is_line(k) and self.is_line(j)) or self.covered_near(k, v) or self.covered_near(j, v):
            return None
        move = self.end_move(k, v)
        u_j, n_k = self.into(j, v), self.normal(k, v)
        if move is None or u_j is None or n_k is None or _dot(n_k, u_j) >= -SAME_TOL:
            return None
        if _gap([v[0] - self.t * move[0], v[1] - self.t * move[1]], uv) > LATERAL_TOL:
            return None
        rooms = [self._wall_room(k, {tuple(v): move}), self._wall_room(j, {tuple(v): move})]
        if any(room is None for room in rooms):
            return None
        return self._placed(v, True, None, v, move, [self._wall_rule(room) for room in rooms])

    def _rim_edge(self, uv, k, o):
        """An edge where the inner wall of curve `k` meets the opened curve `o`."""
        v = self.shared(k, o)
        move = self.end_move(k, v) if v is not None and self.is_line(k) and self.is_line(o) else None
        if move is None or _gap([v[0] - self.t * move[0], v[1] - self.t * move[1]], uv) > LATERAL_TOL:
            return None
        return self._rim(v, k, o, move, 1.0)

    def _on_rim(self, uv, o):
        """A point on the rim the shell leaves of the opened curve `o`: between a corner of `o` with a kept curve and
        the end of that curve's inner wall."""
        if not self.is_line(o):
            return None
        found = []
        for v in self.ends(o):
            k = self.neighbour(o, v)
            move = self.end_move(k, v) if k is not None and k in self.kept and self.is_line(k) else None
            if move is None:
                continue
            reach = self.t * math.hypot(move[0], move[1])
            share = _gap(uv, v) / reach if reach > LENGTH_TOL_MM else 0.0
            if _gap(uv, v) > LATERAL_TOL and reach - _gap(uv, v) > LATERAL_TOL:
                found.append((v, k, move, share))
        if len(found) != 1:
            return None
        v, k, move, share = found[0]
        return self._rim(v, k, o, move, share)

    def _rim(self, v, k, o, move, share):
        """The place `share` of the way from the corner `v` of the kept curve `k` and the opened curve `o` to the end
        of the inner wall of `k`."""
        wall = self._wall_room(k, {tuple(v): move})
        opening = self._opening_room(o)
        if wall is None or opening is None or self.covered_near(k, v):
            return None
        rules = [self._wall_rule(wall), self._opening_rule(opening)]
        return self._placed(v, True, None, v, [share * move[0], share * move[1]], rules)

    # ---- the outline in its plane

    def ends(self, k):
        return [self.curves[k]["start"], self.curves[k]["end"]]

    def neighbour(self, k, v):
        """The one other outline curve with an end at `v`, or None."""
        found = [j for j, curve in enumerate(self.curves)
                 if j != k and any(_gap(end, v) <= LATERAL_TOL for end in (curve["start"], curve["end"]))]
        return found[0] if len(found) == 1 else None

    def shared(self, k, j):
        """The end of curve `k` where `j` is its only neighbour, or None."""
        for v in self.ends(k):
            if self.neighbour(k, v) == j:
                return v
        return None

    def normal(self, k, uv):
        """The unit normal of curve `k` at its point nearest `uv`, out of the outline. The side is read at the middle
        of the curve, away from its corners."""
        curve, mid = self.curves[k], _mid(self.curves[k])
        out = self.foot.outward(k, mid) if mid is not None else None
        if out is None or curve["kind"] == "line":
            return out
        if curve["kind"] != "arc":
            return None
        radial, at_mid = _unit(curve["center"], nearest_point(curve, uv)[0]), _unit(curve["center"], mid)
        if radial is None or at_mid is None:
            return None
        sign = 1.0 if _dot(out, at_mid) > 0 else -1.0
        return [sign * radial[0], sign * radial[1]]

    def into(self, k, v):
        """The unit direction along curve `k` from its end `v` into the curve."""
        curve = self.curves[k]
        if curve["kind"] == "line":
            other = curve["end"] if _gap(curve["start"], v) <= LATERAL_TOL else curve["start"]
            return _unit(v, other)
        radial = _unit(curve["center"], v)
        toward = _unit(v, curve["mid"])
        if radial is None or toward is None:
            return None
        along = [-radial[1], radial[0]]
        return along if _dot(along, toward) > 0 else [-along[0], -along[1]]

    def is_axis(self, j):
        return self.revolve.on_axis(self.curves[j])

    def is_line(self, k):
        return self.curves[k]["kind"] == "line" and self.revolve.keeps_direction(k)

    def end_move(self, k, v):
        """The move `m` (per millimetre of thickness) from the corner `v` of curve `k` to the end of its inner wall,
        which lies at `v - t * m`; None when it cannot be told. Against a kept straight curve the two walls meet on
        the bisector; against an opened curve or the axis the wall runs on to that line; a curved neighbour must meet
        `k` smoothly. A corner on the axis must have a line on the axis next to it."""
        j = self.neighbour(k, v)
        n_k = self.normal(k, v)
        if j is None or n_k is None:
            return None
        if j in self.opened or self.is_axis(j):
            u = self.into(j, v) if self.is_axis(j) or self.is_line(j) else None
            d = _dot(n_k, u) if u is not None else 0.0
            return None if d >= -SAME_TOL else [u[0] / d, u[1] / d]
        if j not in self.kept or self.revolve.from_axis(v) <= LATERAL_TOL or self.covered(j, _mid(self.curves[j])):
            return None
        n_j = self.normal(j, v)
        if n_j is None or not self.revolve.keeps_direction(j):
            return None
        g = _dot(n_k, n_j)
        if abs(g - 1.0) > SAME_TOL and not (self.is_line(k) and self.is_line(j)):
            return None
        if g <= -1.0 + 1e-6:
            return None
        return [(n_k[0] + n_j[0]) / (1.0 + g), (n_k[1] + n_j[1]) / (1.0 + g)]

    def setback(self, k, v, move):
        """How far the inner wall of curve `k` ends from its corner `v`, along `k`, per millimetre of thickness (0
        where it runs on past the corner); None when it cannot be told. A curved wall must end square to the corner."""
        u = self.into(k, v)
        if move is None or u is None:
            return None
        c = -_dot(move, u)
        if self.curves[k]["kind"] != "line":
            return 0.0 if abs(c) <= SQUARE_TOL else None
        return max(c, 0.0)

    # ---- other steps

    def covered(self, k, uv):
        """True when another step adds material just outside curve `k` at the sketch point `uv`: the face is not a face
        of the part there."""
        n = self.normal(k, uv) if uv is not None else None
        if n is None:
            return True
        p = self.revolve.point_at([uv[0] + OUT_STEP * n[0], uv[1] + OUT_STEP * n[1]], self.angle)
        for other in self.others:
            if isinstance(other, RevolvePlacer):
                if other.combine != "cut" and other.holds(p):
                    return True
            elif other.material_at(p) == ADD:
                return True
        return False

    def covered_near(self, k, v):
        """True when another step covers the straight curve `k` next to its corner `v` or at its middle."""
        u = self.into(k, v)
        if u is None:
            return True
        step = min(_gap(*self.ends(k)) / 4.0, max(self.t, LATERAL_TOL))
        return self.covered(k, [v[0] + step * u[0], v[1] + step * u[1]]) or self.covered(k, _mid(self.curves[k]))

    # ---- the rules that keep a pick on its wall

    def _length(self, k):
        """The length of curve `k` as a Quantity (a formula when sizes change it), or None when it cannot follow."""
        curve = self.curves[k]
        found = self.revolve.length_of(curve)
        if found is None:
            return Quantity(_gap(curve["start"], curve["end"]))
        return found if isinstance(found, Quantity) else None

    def _wall_room(self, k, moves, foot=None):
        """How long the inner wall of straight curve `k` is (from `foot`, its pick's place on `k`, to each end when
        given), as Quantities; None when it cannot be told or there is no room now. `moves` gives the end move of a
        corner that is already known. An end on a line on the axis where the wall ends square needs no room: a pick
        there stays on the axis."""
        length = self._length(k)
        if length is None:
            return None
        size = _gap(*self.ends(k))
        backs = []
        for v in self.ends(k):
            move = moves.get(tuple(v)) or self.end_move(k, v)
            back = self.setback(k, v, move)
            if back is None:
                return None
            backs.append((v, back))
        if foot is None:
            room = self._less(length, backs[0][1] + backs[1][1])
            return [room] if room.n > LATERAL_TOL else None
        rooms = []
        for v, back in backs:
            share = _gap(foot, v) / size
            if share * size <= LATERAL_TOL and back == 0.0 and self.is_axis(self.neighbour(k, v)):
                continue
            room = self._less(length.scaled(share), back)
            if room.n <= LATERAL_TOL:
                return None
            rooms.append(room)
        return rooms

    def _opening_room(self, o):
        """How wide the opening of the opened straight curve `o` stays between the inner walls at its ends, as a
        Quantity; None when it cannot be told or there is none now."""
        length = self._length(o)
        if length is None:
            return None
        width = length
        for v in self.ends(o):
            k = self.neighbour(o, v)
            if k is None:
                return None
            if k in self.opened or self.is_axis(k):
                continue
            move = self.end_move(k, v)
            u = self.into(o, v)
            if move is None or u is None:
                return None
            width = self._less(width, -_dot(move, u))
        return width if width.n > LATERAL_TOL else None

    def _less(self, value, per_mm):
        """`value` less `per_mm` times the thickness."""
        return value if per_mm == 0.0 else value.plus(self.thickness.scaled(-per_mm))

    def _wall_rule(self, rooms):
        why = lambda picker: "the inside wall of %s that %s picks would shrink to nothing" % (self.revolve.label,
                                                                                              picker)
        return [(room, LENGTH_TOL_MM, why) for room in rooms if room.sized]

    def _opening_rule(self, width):
        why = lambda picker: "the opening of %s next to the place %s picks would close" % (self.revolve.label, picker)
        return [(width, LENGTH_TOL_MM, why)] if width.sized else []

    def _line_cuts(self, k, f):
        rooms = self._wall_room(k, {}, f)
        return None if rooms is None else [self._wall_rule(rooms)]

    def _arc_cuts(self, k, f, n):
        """The rules of a pick inside the inner wall of arc `k` at `f` (normal `n`): the wall ends square at both ends
        of the arc, and an arc whose centre lies inside the outline keeps a radius above the thickness."""
        curve = self.curves[k]
        if any(_gap(f, v) <= LATERAL_TOL or self.setback(k, v, self.end_move(k, v)) is None for v in self.ends(k)):
            return None
        radius = self._less(Quantity(curve["radius"]), 1.0)
        if _dot(n, _unit(curve["center"], f) or n) < 0:
            return []
        if radius.n <= LATERAL_TOL:
            return None
        return [self._wall_rule([radius])]

    # ---- the place

    def _placed(self, uv, edge, curve, corner, move, rules):
        """The InnerTurnPlace whose outer point is the sketch point `uv` (on `curve`, or the corner `corner`), moved in
        by `move` per millimetre of thickness."""
        q = self.revolve.point_at(uv, self.angle)
        outer = self.revolve.place(q, edge)
        if outer is None:
            return None
        if curve is not None and outer.curve != curve:
            return None
        if corner is not None and (outer.corner is None or _gap(self.foot.corners[outer.corner], corner) > LATERAL_TOL):
            return None
        offset = self.revolve.model_vector(move, self.angle)
        return InnerTurnPlace(outer, offset, self.thickness, [rule for group in rules for rule in group])
