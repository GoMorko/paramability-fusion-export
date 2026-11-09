"""Picks and reaches that follow sizes.

Rounds, chamfers and shells pick edges and faces by points measured in Fusion, and an extrude can reach to a face or
start from one. When an earlier extrude's length follows a size, the faces it made move with that size, so a fixed
point would pick another face once the size changes.

Every extrude step is kept as a `Slab`: its placement, its profile and its length. A point that lies on an end face
of a slab, or on a side edge at a profile corner, is placed against it. When that place moves with a size, the pick
names the extrude (`featureFace`, `featureEdges`) or its coordinates become formulas of the length. A point that no
slab places may sit on geometry that moves, so the sizes of the steps written before it become fixed numbers.
"""
from . import picks, vec
from .footprint import Footprint
from .values import Quantity, number

AXIAL_TOL = 1e-3
LATERAL_TOL = 1e-3
FACTOR_DIGITS = 6
CONSTANT_TOL = 1e-6


class Slab:
    """One extrude step: `on` is its written placement (it grows along `on.normal`), `length` a Quantity."""

    def __init__(self, step_id, on, extent, length, profile):
        self.id = step_id
        self.axis = vec.unit(on["normal"])
        self.base = vec.dot([number(c) for c in on["origin"]], self.axis)
        self.extent = extent
        self.length = length
        self.frame = profile["frame"]
        self.footprint = Footprint(profile)

    def place(self, p, edge):
        """The Place of point `p` on this slab, or None when `p` is not on its end faces or side corners.

        `edge` asks for a side edge: on a side face it must sit at a profile corner.
        """
        full = self.length.n
        if not full > 0:
            return None
        h = vec.dot(p, self.axis) - self.base
        low, high = (0.0, full) if self.extent == "oneSide" else (-full / 2.0, full / 2.0)
        local = vec.frame_to_local(self.frame, p)
        uv = [local[0], local[1]]
        curve, gap = self.footprint.nearest_curve(uv)
        on_outline = gap <= LATERAL_TOL
        for which, at in (("end", high), ("start", low)):
            if abs(h - at) <= AXIAL_TOL and (on_outline or self.footprint.covers(uv)):
                return Place(self, which, at / full, curve if on_outline else None)
        if low + AXIAL_TOL < h < high - AXIAL_TOL and on_outline:
            corner = self.footprint.corner_at(uv, LATERAL_TOL)
            if edge and corner is None:
                return None
            return Place(self, "side", round(h / full, FACTOR_DIGITS), None, corner)
        return None


class Place:
    """Where a point sits on a slab: `which` is start, end or side; it moves `factor` times the slab length."""

    def __init__(self, slab, which, factor, curve=None, corner=None):
        self.slab, self.which, self.factor = slab, which, factor
        self.curve, self.corner = curve, corner

    @property
    def moves(self):
        return self.slab.length.sized and self.factor != 0

    def coordinates(self, p):
        """`p` as a position whose coordinates follow the slab length (numbers where the axis has no part)."""
        out = []
        for i, value in enumerate(p):
            a = self.slab.axis[i]
            if abs(a) < 1e-9:
                out.append(value)
                continue
            if abs(abs(a) - 1) < 1e-9:
                a = 1.0 if a > 0 else -1.0
            moved = self.slab.length.scaled(self.factor * a)
            rest = value - moved.n
            out.append(moved.plus(rest if abs(rest) > CONSTANT_TOL else 0.0).json())
        return out


def locate(ctx, p, edge=False):
    """The Place of a measured point on the latest slab that has it, or None."""
    for slab in reversed(ctx.slabs):
        found = slab.place(p, edge)
        if found is not None:
            return found
    return None


def _name(item):
    return item.get("name", "a step")


def _follow_points(ctx, item, points, edge, what):
    """Points as positions that follow sizes; None when a point cannot be placed (its sizes are then fixed)."""
    out = []
    for p in points:
        found = locate(ctx, p, edge)
        if found is None:
            ctx.fix(ctx.written_reads, "the %s that %s picks may move with it, and the copy cannot follow them"
                    % (what, _name(item)))
            return None
        out.append(found.coordinates(p) if found.moves else p)
    return out


def edges_near(ctx, item, edge_list):
    """`{ near }` for a group of capture edges, with points that follow sizes where they move."""
    points = picks.near_points(edge_list)
    if not ctx.written_reads:
        return {"near": points}
    followed = _follow_points(ctx, item, points, True, "edges")
    return {"near": followed if followed is not None else points}


def whole_edges(ctx, edge_list):
    """`{ featureEdges, which }` when the edges are exactly the side edges, or the edges of a moving end face, of one
    extrude step whose length follows a size; else None."""
    if not ctx.written_reads or not edge_list:
        return None
    keys, first = [], None
    for edge in edge_list:
        found = [locate(ctx, p, True) for p in edge.get("points") or []]
        if not found or any(f is None for f in found):
            return None
        first = first or found[0]
        if any(f.slab is not first.slab or f.which != first.which for f in found):
            return None
        edge_keys = {f.corner if f.which == "side" else f.curve for f in found}
        if len(edge_keys) != 1 or None in edge_keys:
            return None
        keys.append(edge_keys.pop())
    slab = first.slab
    wanted = len(slab.footprint.corners) if first.which == "side" else len(slab.footprint.curves)
    if not first.moves or len(set(keys)) != len(keys) or len(keys) != wanted:
        return None
    return {"featureEdges": slab.id, "which": "sides" if first.which == "side" else first.which}


def faces(ctx, item, face_list):
    """The selector for faces a shell opens: `featureFace` for one moving end face, else `{ near }`."""
    points = picks.face_points(face_list)
    if not ctx.written_reads:
        return {"near": points}
    if len(points) == 1:
        found = locate(ctx, points[0])
        if found is not None and found.moves and found.which in ("start", "end"):
            return {"featureFace": found.slab.id, "which": found.which}
    followed = _follow_points(ctx, item, points, False, "faces")
    return {"near": followed if followed is not None else points}


def target_shift(ctx, item, target, direction, what="reaches to"):
    """How a face an extrude starts from or reaches to moves along unit `direction`: a Quantity whose formula gives
    the face's offset and whose number is that offset at the measured sizes (plain zero when it does not move); None
    when it cannot follow (its sizes are then fixed). `what` words the reason.

    A construction plane stays where it is (a size that moves it is fixed with the sketches). A face is placed by
    its `face_point`.
    """
    zero = Quantity(0.0)
    if not ctx.written_reads or target.get("entity_type") == "ConstructionPlane":
        return zero
    point = target.get("face_point")
    found = locate(ctx, point) if point else None
    if found is None or found.which == "side":
        ctx.fix(ctx.written_reads, "%s %s a face that may move with it, and the copy cannot follow that"
                % (_name(item), what))
        return None
    if not found.moves:
        return zero
    return found.slab.length.scaled(found.factor * vec.dot(found.slab.axis, direction))
