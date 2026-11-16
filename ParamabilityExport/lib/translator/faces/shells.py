"""The inner walls a shell leaves, for picks that follow sizes (see faces/follow.py).

A shell moves every face of the part inward by its thickness, except the faces it opens. A point on an inner wall is
the point of an outer face (or edge, where two inner walls meet) moved inward by the thickness. So the point is moved
back out, placed on the slab that made the outer face, and its coordinates follow that slab and the thickness.

A shell that grows outward leaves the faces of the part where they are, as the walls of its hollow, and adds a wall
outside them. Those new outer faces are not placed (`OutsideShell`).
"""
from ...geometry import vec
from .placer import ADD, CUT, Placer
from .slabs import AXIAL_TOL, LATERAL_TOL, Place, as_quantity

# Offset directions are written with this many digits, so a formula holds no rounding noise.
DIRECTION_DIGITS = 9


def _clean(v):
    return [0.0 if abs(c) < 1e-12 else round(c, DIRECTION_DIGITS) + 0.0 for c in v]


class InnerPlace(Place):
    """A point on an inner wall of a shell: `outer` is the Place of the outer point it was moved from, `offset` the
    move per millimetre of thickness (outward, in model space)."""

    def __init__(self, outer, outer_point, offset, thickness):
        Place.__init__(self, outer.slab, "inner", outer.factor)
        self.outer, self.outer_point = outer, outer_point
        self.offset, self.thickness = offset, thickness
        self.blocked = list(outer.blocked)

    @property
    def moves(self):
        return self.outer.moves or self.thickness.sized

    @property
    def single(self):
        """The unit normal of the inner wall when the point sits on one face (not an edge), else None."""
        size = vec.length(self.offset)
        return vec.scale(self.offset, 1.0 / size) if abs(size - 1.0) <= 1e-9 else None

    def quantities(self, p):
        out = []
        for q, o in zip(self.outer.quantities(self.outer_point), self.offset):
            out.append(q.plus(self.thickness.scaled(-o)) if o else q)
        return out


class Shell(Placer):
    """One shell step: `thickness` a Quantity, `slabs` the solid slabs of the part when it was made, `opened` the
    Places of the faces it opens."""

    def __init__(self, thickness, slabs, opened):
        self.thickness = as_quantity(thickness)
        self.slabs = [s for s in slabs if s.combine in ("new", "add") and s.taper is None]
        self.opened = opened

    def material_at(self, p):
        return CUT if self.hollows(p) else None

    @property
    def wall_offsets(self):
        return (self.thickness.n, -self.thickness.n)

    def _open(self, slab, which, curve=None):
        for place in self.opened:
            if place.slab is slab and place.which == which and (which != "side" or place.curve == curve):
                return True
        return False

    def hollows(self, p, tol=LATERAL_TOL):
        """True when `p` lies in or on the hollow the shell left."""
        t = self.thickness.n
        for slab in self.slabs:
            h, uv = slab.local(p)
            low, high = slab.span
            low = low if self._open(slab, "start") else low + t
            high = high if self._open(slab, "end") else high - t
            if low - tol <= h <= high + tol and slab.depth_in(uv)[1] >= t - tol:
                return True
        return False

    def place(self, p, edge):
        """The InnerPlace of point `p` on an inner wall, or None."""
        t = self.thickness.n
        for slab in reversed(self.slabs):
            found = self._place_on(slab, p, edge, t)
            if found is not None:
                return found
        return None

    def _place_on(self, slab, p, edge, t):
        h, uv = slab.local(p)
        low, high = slab.span
        gaps = slab.footprint.gaps(uv)
        if not gaps or not slab.footprint.covers(uv) or min(gaps) < t - LATERAL_TOL:
            return None
        walls = [n for n, gap in enumerate(gaps) if abs(gap - t) <= LATERAL_TOL]
        if len(walls) > 2 or any(self._open(slab, "side", n) for n in walls):
            return None
        end_open, start_open = self._open(slab, "end"), self._open(slab, "start")
        top = high if end_open else high - t
        bottom = low if start_open else low + t
        if not bottom - AXIAL_TOL <= h <= top + AXIAL_TOL:
            return None
        axial = 0.0
        if not end_open and abs(h - top) <= AXIAL_TOL:
            axial = 1.0
        elif not start_open and abs(h - bottom) <= AXIAL_TOL:
            axial = -1.0
        if not walls and not axial:
            return None
        lateral = [0.0, 0.0]
        normals = [slab.footprint.outward(n, uv) for n in walls]
        if any(n is None for n in normals):
            return None
        if len(normals) == 1:
            lateral = normals[0]
        elif len(normals) == 2:
            a, b = normals
            # Two walls at an angle: the corner moves along their bisector, further for a sharp corner.
            g = a[0] * b[0] + a[1] * b[1]
            if g <= -1 + 1e-6:
                return None
            lateral = [(a[0] + b[0]) / (1 + g), (a[1] + b[1]) / (1 + g)]
        frame = slab.frame
        offset = [lateral[0] * frame["x"][i] + lateral[1] * frame["y"][i] + axial * slab.axis[i] for i in range(3)]
        offset = _clean(slab.motion.turn_vector(offset))
        outer_point = vec.add(p, vec.scale(offset, t))
        outer = slab.place(outer_point, edge)
        if outer is None:
            return None
        return InnerPlace(outer, outer_point, offset, self.thickness)


class OutsideShell(Placer):
    """A shell that grows outward by `thickness` (a Quantity): the part before it becomes the hollow, and the wall lies
    outside it. `before` are the placers that held the part when the shell was made.

    The hollow is known (`material_at`), the wall is not, and its faces are not placed: a pick on one (a point that
    lies outside the part as it was) is claimed, so no earlier step places it by chance. `opaque` makes a step on
    another part's sketch say it cannot check that it still meets the wall."""

    opaque = True

    def __init__(self, thickness, before):
        self.thickness = as_quantity(thickness)
        self.before = list(before)

    def _was_material(self, p):
        held = False
        for placer in self.before:
            material = placer.material_at(p)
            if material is not None:
                held = material == ADD
        return held

    def place(self, p, edge):
        return None

    def claims(self, p):
        return not self._was_material(p)

    def material_at(self, p):
        return CUT if self._was_material(p) else None

    @property
    def wall_offsets(self):
        return (self.thickness.n, -self.thickness.n)
