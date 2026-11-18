"""Thin extrudes of a closed outline: the wall they leave, which side of the outline it sits on, and its placer.

The recipe's `thin` extrude draws a wall of one thickness along one closed outline, on the `inside` of it, on the
`outside`, or `middle` (half each way). The shared layer (`design_model/steps/thin.py`) reads the wall record
(`wall_of`) and decides the side from the measured end face (`closed_side`). The app rounds corners that Fusion keeps
sharp; where only the sharp reading fits, the copy says so in a note.
"""
from ...capture_model import gap_hints
from ...design_model.problem import is_problem
from ...design_model.steps import thin
from ..result import Refusal
from .placer import ADD, CUT, Placer
from .slabs import Slab

BAND_TOL = 1e-3


def _refusal(problem):
    return Refusal(problem.words, cause=problem.cause)


def prepare(data):
    """The thin wall record of an extrude's data, or a Refusal when it cannot be copied before looking at outlines
    (`thin.wall_of`)."""
    wall = thin.wall_of(data)
    return _refusal(wall) if is_problem(wall) else wall


def open_line_refusal(profiles):
    """A Refusal for a profile input that is not a closed sketch outline: an open line whose path was not read (a
    capture of an older add-in reads it as entities without a path)."""
    if any(p.get("kind") == "other" and "loops" not in p for p in profiles):
        return Refusal("The open line of this thin extrude could not be read, so it is not copied.",
                       cause=gap_hints.THIN_OUTLINE)
    return None


def decide(curves, wall, end_area):
    """`(side, rounded)` for a wall (`thin.closed_side`), or a Refusal."""
    found = thin.closed_side(curves, wall, end_area)
    return _refusal(found) if is_problem(found) else found


class ThinWall(Placer):
    """The wall of a thin extrude as material only: it says whether a point lies in the wall at the measured sizes.

    Its faces are not placed (`place` gives nothing), so a later pick on one of them is placed on earlier steps or its
    sizes are marked, and `opaque` makes a step on another part's sketch say it cannot check that it still meets the wall."""

    opaque = True

    def __init__(self, step_id, on, extent, length, profile, side, thickness, combine):
        self.slab = Slab(step_id, on, extent, length, profile, combine=combine)
        self.combine = combine
        reach = {"inside": (0.0, thickness), "outside": (-thickness, 0.0),
                 "middle": (-thickness / 2.0, thickness / 2.0)}[side]
        self.band = reach

    def place(self, p, edge):
        return None

    def material_at(self, p):
        if self.combine not in ("new", "add", "cut"):
            return None
        slab = self.slab
        h, uv = slab.local(p)
        low, high = slab.span
        if not low - BAND_TOL <= h <= high + BAND_TOL:
            return None
        depth = slab.depth_in(uv)[1]
        if not self.band[0] - BAND_TOL <= depth <= self.band[1] + BAND_TOL:
            return None
        return CUT if self.combine == "cut" else ADD
