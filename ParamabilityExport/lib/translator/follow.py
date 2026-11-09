"""Picks and reaches that follow sizes.

Rounds, chamfers and shells pick edges and faces by points measured in Fusion, and an extrude can reach to a face or
start from one. When an earlier extrude's length follows a size, the faces it made move with that size, so a fixed
point would pick another face once the size changes.

Every extrude step is kept as a `Slab`: its placement, its profile and its length. A point that lies on an end face
of a slab, or on a side edge at a profile corner, is placed against it. When that place moves with a size, the pick
names the extrude (`featureFace`, `featureEdges`) or its coordinates become formulas of the length. A point that no
slab places may sit on geometry that moves, so the sizes of the steps written before it become fixed numbers.

A pattern or mirror copy of an extrude is a slab too, with the `Motion` that carries the original to the copy. A
point on a copy is placed on the original and moved back: its coordinates follow the length and the spacing.
"""
from . import picks, vec
from .footprint import Footprint
from .values import Quantity, Sized

IDENTITY_ROWS = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
ROW_SNAP = 1e-12

AXIAL_TOL = 1e-3
LATERAL_TOL = 1e-3
FACTOR_DIGITS = 6
CONSTANT_TOL = 1e-6


def _snap(value):
    for target in (0.0, 1.0, -1.0):
        if abs(value - target) <= ROW_SNAP:
            return target
    return float(value)


def as_quantity(value):
    """A written number or formula as a Quantity."""
    if isinstance(value, Sized):
        return Quantity(value.n, value["expr"], value.reads)
    if isinstance(value, Quantity):
        return value
    return Quantity(float(value))


def _no_noise(q):
    return Quantity(0.0) if not q.sized and abs(q.n) <= 1e-9 else q


class Motion:
    """A rigid map p -> rows * p + shift that carries an original to one copy.

    `rows` are numbers (a turn or a mirror); `shift` holds three Quantities, so a spacing may follow sizes. `needs`
    are the Fusion names of sizes that must stay fixed when a pick lands on the copy (the count that makes it, an
    angle that turns it); `by` names the pattern or mirror for the reason.
    """

    def __init__(self, rows=IDENTITY_ROWS, shift=None, needs=(), by=""):
        self.rows = tuple(tuple(_snap(c) for c in row) for row in rows)
        self.shift = [_no_noise(as_quantity(v)) for v in (shift or (0.0, 0.0, 0.0))]
        self.needs = tuple(needs)
        self.by = by

    @classmethod
    def mirror(cls, origin, normal, by=""):
        n = vec.unit(normal)
        rows = [[(1.0 if i == j else 0.0) - 2.0 * n[i] * n[j] for j in range(3)] for i in range(3)]
        return cls(rows, vec.scale(n, 2.0 * vec.dot(origin, n)), by=by)

    @classmethod
    def turn(cls, axis_point, axis, angle_deg, needs=(), by=""):
        rows = [vec.rotate(e, axis, angle_deg) for e in ([1, 0, 0], [0, 1, 0], [0, 0, 1])]
        rows = [[rows[j][i] for j in range(3)] for i in range(3)]
        return cls(rows, vec.rotate([0.0, 0.0, 0.0], axis, angle_deg, axis_point), needs, by)

    @property
    def moves(self):
        return any(q.sized for q in self.shift)

    def turn_vector(self, d):
        return [sum(self.rows[i][j] * d[j] for j in range(3)) for i in range(3)]

    def numbers(self, p):
        """The copy of point `p` at the measured sizes."""
        return [v + self.shift[i].n for i, v in enumerate(self.turn_vector(p))]

    def back(self, p):
        """The original of point `p` of the copy, at the measured sizes."""
        d = [p[i] - self.shift[i].n for i in range(3)]
        return [sum(self.rows[j][i] * d[j] for j in range(3)) for i in range(3)]

    def quantities(self, coords):
        """The copy of a position whose coordinates are written numbers, formulas or Quantities."""
        coords = [as_quantity(c) for c in coords]
        out = []
        for i in range(3):
            total = None
            for coef, coord in zip(self.rows[i], coords):
                if coef:
                    term = coord.scaled(coef)
                    total = term if total is None else total.plus(term)
            total = Quantity(0.0) if total is None else total
            out.append(total.plus(self.shift[i]) if self.shift[i].sized or self.shift[i].n else total)
        return out

    def then(self, other):
        """The motion that applies `self` first, then `other`."""
        rows = [[sum(other.rows[i][k] * self.rows[k][j] for k in range(3)) for j in range(3)] for i in range(3)]
        return Motion(rows, other.quantities(self.shift), tuple(dict.fromkeys(self.needs + other.needs)),
                      other.by or self.by)


class Slab:
    """One extrude step: `on` is its written placement (it grows along `on.normal`), `length` a Quantity.

    `owner` is the id of the step that made it: the extrude, or the pattern or mirror for a copy, whose `motion`
    carries the extrude to it.
    """

    def __init__(self, step_id, on, extent, length, profile, motion=None, owner=None):
        self.id = step_id
        self.owner = owner or step_id
        self.on, self.profile = on, profile
        self.axis = vec.unit(on["normal"])
        self.origin = [as_quantity(c) for c in on["origin"]]
        self.base = vec.dot([q.n for q in self.origin], self.axis)
        self.extent = extent
        self.length = length
        self.frame = profile["frame"]
        self.footprint = Footprint(profile)
        self.motion = motion or Motion()

    @property
    def is_copy(self):
        return self.owner != self.id

    def copied(self, owner, motion):
        """This slab carried on by `motion`, made by step `owner`."""
        return Slab(self.id, self.on, self.extent, self.length, self.profile, self.motion.then(motion), owner)

    def place(self, p, edge):
        """The Place of point `p` on this slab, or None when `p` is not on its end faces or side corners.

        `edge` asks for a side edge: on a side face it must sit at a profile corner.
        """
        if self.is_copy:
            p = self.motion.back(p)
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
        slab = self.slab
        return (bool(slab.length.sized and self.factor != 0) or slab.motion.moves
                or any(q.sized for q in slab.origin))

    def quantities(self, p):
        """`p` as three Quantities that follow the slab's start, its length and the spacing of a copy."""
        motion = self.slab.motion
        if self.slab.is_copy:
            p = motion.back(p)
        out = []
        for i, value in enumerate(p):
            a, origin = self.slab.axis[i], self.slab.origin[i]
            if abs(a) < 1e-9 or not (self.slab.length.sized and self.factor != 0 or origin.sized):
                out.append(Quantity(value))
                continue
            if abs(abs(a) - 1) < 1e-9:
                a = 1.0 if a > 0 else -1.0
            moved = self.slab.length.scaled(self.factor * a) if self.slab.length.sized and self.factor else Quantity(0.0)
            if origin.sized:
                moved = origin.plus(moved)
            rest = value - moved.n
            out.append(moved.plus(rest if abs(rest) > CONSTANT_TOL else 0.0))
        return motion.quantities(out) if self.slab.is_copy else out

    def coordinates(self, p):
        """`p` as a position whose coordinates follow the slab length (numbers where nothing moves them)."""
        return [_cleaned(q) for q in self.quantities(p)]


def _cleaned(q):
    """A Quantity as written: a plain number is rounded like a measured point."""
    return q.json() if q.sized else round(q.n, 9) + 0.0


def cleaned_all(quantities):
    return [_cleaned(q) for q in quantities]


def locate(ctx, p, edge=False):
    """The Place of a measured point on the latest slab that has it, or None."""
    for slab in reversed(ctx.slabs):
        found = slab.place(p, edge)
        if found is not None:
            return found
    return None


def _name(item):
    return item.get("name", "a step")


def _keep_copies(ctx, item, found):
    """A pick on a copy of a pattern needs that copy: the sizes that count or turn the copies stay."""
    motion = found.slab.motion
    if motion.needs:
        ctx.fix(motion.needs, "%s picks a copy made by %s, so its copies must stay as they are"
                % (_name(item), motion.by or "a pattern"))


def follow_points(ctx, item, points, edge=True, what="edges"):
    """Points as positions that follow sizes; None when a point cannot be placed (its sizes are then fixed)."""
    out = []
    for p in points:
        found = locate(ctx, p, edge)
        if found is None:
            ctx.fix(ctx.written_reads, "the %s that %s picks may move with it, and the copy cannot follow them"
                    % (what, _name(item)))
            return None
        _keep_copies(ctx, item, found)
        out.append(found.coordinates(p) if found.moves else p)
    return out


def edges_near(ctx, item, edge_list):
    """`{ near }` for a group of capture edges, with points that follow sizes where they move."""
    points = picks.near_points(edge_list)
    if not ctx.written_reads:
        return {"near": points}
    followed = follow_points(ctx, item, points, True, "edges")
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
        if first.slab.is_copy or any(f.slab is not first.slab or f.which != first.which for f in found):
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
        if found is not None and found.moves and found.which in ("start", "end") and not found.slab.is_copy:
            return {"featureFace": found.slab.id, "which": found.which}
    followed = follow_points(ctx, item, points, False, "faces")
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
    _keep_copies(ctx, item, found)
    slab = found.slab
    if not slab.is_copy and not any(q.sized for q in slab.origin):
        return slab.length.scaled(found.factor * vec.dot(slab.axis, direction))
    shift = zero
    for q, p, d in zip(found.quantities(point), point, direction):
        if abs(d) > 1e-9:
            shift = shift.plus(q.plus(-p).scaled(d))
    return shift
