"""The end faces (and side walls) of a sweep or loft, for picks that follow sizes.

A sweep or loft has a start face and an end face, each the outline of one section. The recipe names them
(`featureFace`, `featureEdges` with `which` start or end), so a pick on a whole face or on all edges of one follows
every size that moves it. A point alone cannot be placed with formulas: the pick keeps its measured number and marks
the sizes the step reads, which are the only ones that move its faces.

The faces of a hollow section do not exist in the recipe's kernel, so a step with holes has no placer. A sweep's side
wall is placed only when the path has a `sweep_frames.SideWalk`; a loft's side walls are not placed.
"""
from ...design_model.values import Quantity
from ...geometry import vec
from ...geometry.footprint import Footprint
from .placer import Placer
from .slabs import AXIAL_TOL, LATERAL_TOL, cleaned_all


class Cap:
    """One end face: the frame of its outline and the outline's `Footprint`."""

    def __init__(self, frame, profile):
        self.frame = frame
        self.footprint = Footprint(profile)

    def local(self, p):
        """(u, v, height): `p` in the outline's own coordinates and its height above the face."""
        return vec.frame_to_local(self.frame, p)

    def depth_in(self, uv):
        """(nearest curve, signed depth): how far `uv` lies inside the outline, negative outside."""
        curve, gap = self.footprint.nearest_curve(uv)
        return curve, gap if self.footprint.covers(uv) else -gap


class CapPlace:
    """Where a point sits on a sweep or loft: `which` is start, end or side. `curve` is the outline curve it lies on
    (None inside a face), `corner` the outline corner of a side edge. `slab` is the placer (read for its `id`
    and `is_copy`)."""

    factor = 0.0
    lateral = None

    def __init__(self, placer, which, curve=None, corner=None):
        self.slab = placer
        self.which, self.curve, self.corner = which, curve, corner
        self.slabs = []
        self.blocked = []

    @property
    def moves(self):
        return bool(self.slab.reads)

    @property
    def keeps(self):
        """(sizes, what) that must stay as they are when the pick is a plain point: every size the step reads."""
        return ((self.slab.reads, "a face of %s" % self.slab.label),) if self.slab.reads else ()

    def quantities(self, p):
        return [Quantity(float(c)) for c in p]

    def coordinates(self, p):
        return cleaned_all(self.quantities(p))


class EndCaps(Placer):
    """The faces of one sweep or loft step. `caps` maps start and end to a `Cap` (an end that is not known is left out),
    `reads` are the sizes the written step reads, `label` its name, `walk` the sweep's `sweep_frames.SideWalk` or None.
    The step's material is not known (`material_at`)."""

    is_copy = False
    taper = None

    def __init__(self, step_id, label, reads, caps, walk=None):
        self.id = step_id
        self.label = label
        self.reads = tuple(reads)
        self.caps = caps
        self.walk = walk

    @property
    def followed_reads(self):
        return self.reads

    def edge_count(self, which):
        """How many edges the face `which` has; None for the side walls, whose edge set is the kernel's own."""
        cap = self.caps.get(which)
        return None if cap is None else len(cap.footprint.curves)

    def material_at(self, p):
        return None

    def place(self, p, edge):
        """The CapPlace of point `p` on an end face (an edge on its outline) or, for a sweep, on a side wall (an edge
        at an outline corner), or None."""
        for which in ("end", "start"):
            cap = self.caps.get(which)
            found = self._on_cap(which, cap, p, edge) if cap is not None else None
            if found is not None:
                return found
        return self._on_side(p, edge)

    def _on_cap(self, which, cap, p, edge):
        u, v, height = cap.local(p)
        if abs(height) > AXIAL_TOL:
            return None
        curve, depth = cap.depth_in([u, v])
        if abs(depth) <= LATERAL_TOL:
            return CapPlace(self, which, curve)
        return None if edge or depth < 0 else CapPlace(self, which)

    def _on_side(self, p, edge):
        cap = self.caps.get("start")
        if self.walk is None or cap is None:
            return None
        for uv in self.walk.sections(p):
            curve, depth = cap.depth_in(uv)
            if abs(depth) > LATERAL_TOL:
                continue
            corner = cap.footprint.corner_at(uv, LATERAL_TOL)
            if edge and corner is None:
                return None
            return CapPlace(self, "side", curve, corner)
        return None
