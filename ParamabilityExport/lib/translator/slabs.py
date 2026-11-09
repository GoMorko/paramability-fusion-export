"""Extrude steps as slabs, and where a measured point sits on one (see follow.py).

A `Slab` is one extrude step: its placement, its profile, its length and its taper. A pattern or mirror copy is a slab
too, with the `Motion` that carries the original to the copy. A `Place` says where a point sits on a slab and gives
its coordinates as Quantities that follow the slab's start, its length and the spacing of a copy.
"""
import math

from ..probe.motion import Stuck
from . import vec
from .footprint import Footprint
from .sketch_motion import combine, rendered
from .values import Quantity, Sized

IDENTITY_ROWS = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
ROW_SNAP = 1e-12

AXIAL_TOL = 1e-3
LATERAL_TOL = 1e-3
FACTOR_DIGITS = 6
# A point within this many mm of where its formula puts it keeps the formula alone.
CONSTANT_TOL = 1e-4


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
    are the Fusion names of sizes that must stay fixed when a pick lands on the copy (a count or an angle that turns
    it); `by` names the pattern or mirror for the reason. `requires` lists `(count, least, by)`: a pick on the copy
    needs the count (a Quantity) to stay at `least` or more, since the copy only exists then.
    """

    def __init__(self, rows=IDENTITY_ROWS, shift=None, needs=(), by="", requires=()):
        self.rows = tuple(tuple(_snap(c) for c in row) for row in rows)
        self.shift = [_no_noise(as_quantity(v)) for v in (shift or (0.0, 0.0, 0.0))]
        self.needs = tuple(needs)
        self.by = by
        self.requires = tuple(requires)

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
                      other.by or self.by, self.requires + other.requires)


class Slab:
    """One extrude step: `on` is its written placement (it grows along `on.normal`), `length` a Quantity.

    `owner` is the id of the step that made it: the extrude, or the pattern or mirror for a copy, whose `motion`
    carries the extrude to it. `combine` is the step's combine (new, add, cut, intersect). `taper` is the written taper
    as a Quantity (degrees, positive leans the walls in going away from the start) or None. `outline` is the
    sketch_motion.Outline of its profile when the sketch follows sizes, else None.
    """

    def __init__(self, step_id, on, extent, length, profile, motion=None, owner=None, combine="add", taper=None,
                 outline=None):
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
        self.combine = combine
        self.taper = taper if taper is not None and abs(taper.n) > 0 else None
        self.outline = outline

    @property
    def is_copy(self):
        return self.owner != self.id

    @property
    def span(self):
        """(low, high): where the slab runs along its axis from its base, at the measured length."""
        full = self.length.n
        return (0.0, full) if self.extent == "oneSide" else (-full / 2.0, full / 2.0)

    def copied(self, owner, motion):
        """This slab carried on by `motion`, made by step `owner`."""
        return Slab(self.id, self.on, self.extent, self.length, self.profile, self.motion.then(motion), owner,
                    self.combine, self.taper, self.outline)

    def local(self, p):
        """(h, uv) of a point of this slab: its height above the base and its sketch position, on the original."""
        if self.is_copy:
            p = self.motion.back(p)
        local = vec.frame_to_local(self.frame, p)
        return vec.dot(p, self.axis) - self.base, [local[0], local[1]]

    def inset(self, h):
        """How far the outline lies inside the profile at height `h` (the taper), in mm."""
        if self.taper is None:
            return 0.0
        return math.tan(math.radians(self.taper.n)) * (h - self.span[0] if self.extent == "oneSide" else abs(h))

    def depth_in(self, uv):
        """(nearest curve, signed depth): how far `uv` lies inside the profile, negative outside."""
        curve, gap = self.footprint.nearest_curve(uv)
        return curve, gap if self.footprint.covers(uv) else -gap

    def lateral(self, uv, curve):
        """The outward normal of `curve` at `uv` in model space (on this copy), or None."""
        normal = self.footprint.outward(curve, uv)
        if normal is None:
            return None
        n = [normal[0] * self.frame["x"][i] + normal[1] * self.frame["y"][i] for i in range(3)]
        return self.motion.turn_vector(n)

    def holds(self, p, tol=LATERAL_TOL):
        """True when `p` lies in or on the slab's solid (or the space a cut takes)."""
        h, uv = self.local(p)
        low, high = self.span
        if not low - tol <= h <= high + tol:
            return False
        return self.depth_in(uv)[1] >= self.inset(h) - tol

    def place(self, p, edge):
        """The Place of point `p` on this slab, or None when `p` is not on its end faces or side corners.

        `edge` asks for a side edge: on a side face it must sit at a profile corner. A tapered slab has no corners.
        """
        full = self.length.n
        if not full > 0:
            return None
        h, uv = self.local(p)
        low, high = self.span
        curve, depth = self.depth_in(uv)
        for which, at in (("end", high), ("start", low)):
            if abs(h - at) > AXIAL_TOL:
                continue
            inset = self.inset(at)
            on_outline = abs(depth - inset) <= LATERAL_TOL
            if on_outline or depth > inset:
                return Place(self, which, at / full, curve if on_outline else None, uv=uv)
        if low + AXIAL_TOL < h < high - AXIAL_TOL and abs(depth - self.inset(h)) <= LATERAL_TOL:
            corner = None if self.taper is not None else self.footprint.corner_at(uv, LATERAL_TOL)
            if edge and corner is None:
                return None
            return Place(self, "side", round(h / full, FACTOR_DIGITS), None, corner, uv=uv)
        return None


class Place:
    """Where a point sits on a slab: `which` is start, end or side; it moves `factor` times the slab length.

    A taper leans the outline: a point on it follows the taper and the length. `lateral` holds the point's place in the sketch plane as three model coordinates when the outline moves it with
    sizes (sketch_motion.py), else None; `blocked` holds a `Stuck` when the outline moves it in a way that cannot be
    followed.
    """

    def __init__(self, slab, which, factor, curve=None, corner=None, uv=None):
        self.slab, self.which, self.factor = slab, which, factor
        self.curve, self.corner = curve, corner
        self.slabs = [slab]
        self.lateral = None
        self.blocked = []
        if uv is not None and slab.outline is not None:
            self._follow_outline(uv)

    def _follow_outline(self, uv):
        slab = self.slab
        found = slab.outline.follow(slab.footprint, self.which, self.curve, self.corner, uv)
        if isinstance(found, Stuck):
            self.blocked.append(found)
            return
        if found is None:
            return
        frame, out = slab.frame, []
        for i in range(3):
            value = combine([(frame["x"][i], found[0]), (frame["y"][i], found[1]), (1.0, frame["origin"][i])],
                            slab.outline.sketch)
            q = rendered(slab.outline.table, value, frame["origin"][i] + uv[0] * frame["x"][i] + uv[1] * frame["y"][i])
            if isinstance(q, Stuck):
                self.blocked.append(q)
                return
            out.append(q)
        if any(q.sized for q in out):
            self.lateral = out

    @property
    def moves(self):
        slab = self.slab
        leans = slab.taper is not None and slab.taper.sized and self.factor != 0 and (
            self.which == "side" or self.curve is not None)
        return (bool(slab.length.sized and self.factor != 0) or slab.motion.moves
                or any(q.sized for q in slab.origin) or self.lateral is not None or leans)

    def _inward(self, p):
        """The inward unit normal of the outline at `p` on the original, when a taper shifts it with the length or a
        taper that follows sizes."""
        slab = self.slab
        if slab.taper is None or not (slab.length.sized or slab.taper.sized) or (
                self.which != "side" and self.curve is None):
            return None
        h, uv = slab.local(p)
        curve, _ = slab.footprint.nearest_curve(uv)
        normal = slab.footprint.outward(curve, uv)
        if normal is None:
            return None
        return [-(normal[0] * slab.frame["x"][i] + normal[1] * slab.frame["y"][i]) for i in range(3)]

    def quantities(self, p):
        """`p` as three Quantities that follow the slab's start, its length and the spacing of a copy."""
        motion = self.slab.motion
        inward = self._inward(p)
        if self.slab.is_copy:
            p = motion.back(p)
        out = []
        slab = self.slab
        stretch = slab.length.sized and self.factor != 0
        # A taper that follows sizes leans the wall by tan(taper) times the height along the slab.
        lean_q = None
        if inward is not None and slab.taper.sized and self.factor:
            height = slab.length.scaled(self.factor if slab.extent == "oneSide" else abs(self.factor))
            lean_q = Quantity(math.tan(math.radians(slab.taper.n)), "tan(%s)" % slab.taper.text,
                              slab.taper.reads).times(height)
        for i, value in enumerate(p):
            a, origin = slab.axis[i], slab.origin[i]
            if abs(a) < 1e-9:
                a = 0.0
            elif abs(abs(a) - 1) < 1e-9:
                a = 1.0 if a > 0 else -1.0
            lean = 0.0
            if inward is not None and stretch and lean_q is None:
                lean = inward[i] * math.tan(math.radians(slab.taper.n)) * (
                    self.factor if slab.extent == "oneSide" else abs(self.factor))
            along = (self.factor * a if stretch else 0.0) + lean
            along = 0.0 if abs(along) < 1e-12 else along
            shifted = a and origin.sized
            lateral = self.lateral[i] if self.lateral is not None and self.lateral[i].sized else None
            leaning = lean_q is not None and abs(inward[i]) > 1e-12
            if not along and not shifted and lateral is None and not leaning:
                out.append(Quantity(value))
                continue
            moved = slab.length.scaled(along) if along else Quantity(0.0)
            if leaning:
                moved = moved.plus(lean_q.scaled(inward[i]))
            if shifted:
                moved = origin.plus(moved)
            if lateral is not None:
                moved = moved.plus(lateral)
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


