"""Placers of tool steps that were written in another component's frame and carried into the exported body's frame.

The steps of a tool body from another component are written where that component sits and then moved by a rigid map
(`place.place`). The placers their handlers made still hold the original frame. A slab is copied with the map
(`Slab.copied`), so a pick on its faces follows sizes. Any other placer becomes a `MovedPlacer`, which asks the original
about the point carried back, so `material_at` and the checks that rely on it (`follow.inside`, `meets_part`) keep
working. It cannot place a pick on its faces, so a round or chamfer that picks one marks its sizes instead of landing on
a guessed face.
"""
from .placer import Placer
from .slabs import Motion, Slab
from .values import Quantity


def motion_of(move, shift=None):
    """The `Motion` of a `place.Move`. `shift` is three Quantities added to the offset: a move that follows sizes."""
    offsets = [Quantity(o) if shift is None else shift[i].plus(o) for i, o in enumerate(move.offset)]
    return Motion(move.rows, offsets)


class MovedPlacer(Placer):
    """`inner`, a placer in the frame the step was written in, seen through `motion` (a `slabs.Motion` from that frame
    to the one the recipe is written in)."""

    def __init__(self, inner, motion):
        self.inner = inner
        self.motion = motion
        self.opaque = inner.opaque

    def place(self, p, edge):
        return None

    def material_at(self, p):
        return self.inner.material_at(self.motion.back(p))


class MovedMaker:
    """The placer maker of a moved step: it lets the original makers of the step build their placers in the original
    frame, and registers each of them carried by `motion`."""

    def __init__(self, makers, motion):
        self.makers, self.motion = list(makers), motion

    def make(self, ctx, step_id, step):
        made = _Collector()
        for maker in self.makers:
            # The original gets an id of its own, so its copy counts as a copy and no pick names it.
            maker.make(made, step_id + "_source", step)
        for placer in made.placers:
            if isinstance(placer, Slab):
                ctx.add_slab(placer.copied(step_id, self.motion))
            else:
                ctx.add_placer(MovedPlacer(placer, self.motion))


class _Collector:
    """Stands in for the context while the original makers run."""

    def __init__(self):
        self.placers = []
        self.slabs = []

    def add_placer(self, placer):
        self.placers.append(placer)

    def add_slab(self, slab):
        self.placers.append(slab)
        self.slabs.append(slab)
