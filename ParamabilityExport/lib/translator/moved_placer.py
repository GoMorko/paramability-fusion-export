"""Placers of tool steps that were written in another component's frame and carried into the exported body's frame.

The steps of a tool body from another component are written where that component sits and then moved by a rigid map
(`place.place`). The placers their handlers made still hold the original frame. A `MovedPlacer` asks the original
placer about the point carried back by the map, so `material_at` and the checks that rely on it (`follow.inside`,
`meets_part`) keep working. It cannot place a pick on the faces of such a step, so a round or chamfer that picks one
marks its sizes instead of landing on a guessed face.
"""
from .placer import Placer


class MovedPlacer(Placer):
    """`inner`, a placer in the frame the step was written in, seen through `move` (a `place.Move` from that frame to
    the one the recipe is written in)."""

    def __init__(self, inner, move):
        self.inner = inner
        self.back = move.inverse()
        self.opaque = inner.opaque

    def _carried_back(self, p):
        rows, offset = self.back.rows, self.back.offset
        return [sum(rows[i][k] * p[k] for k in range(3)) + offset[i] for i in range(3)]

    def place(self, p, edge):
        return None

    def material_at(self, p):
        return self.inner.material_at(self._carried_back(p))


class MovedMaker:
    """The placer maker of a moved step: it lets the original makers of the step build their placers in the original
    frame, and registers each of them as a `MovedPlacer`."""

    def __init__(self, makers, move):
        self.makers, self.move = list(makers), move

    def make(self, ctx, step_id, step):
        made = _Collector()
        for maker in self.makers:
            maker.make(made, step_id, step)
        for placer in made.placers:
            ctx.add_placer(MovedPlacer(placer, self.move))


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
