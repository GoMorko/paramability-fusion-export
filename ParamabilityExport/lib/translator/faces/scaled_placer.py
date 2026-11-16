"""Placers of the steps written before a `scale` step.

A scale stretches everything built before it in its list about one point, so the faces of those steps no longer lie
where their placers say, and a scale whose factor follows sizes moves them by an amount no placer can follow. After a
scale every earlier placer becomes a `ScaledPlacer`: it answers `material_at` by carrying the point back through the
scale at the measured sizes, and it places no pick, so a later round, chamfer or offset on one of those faces marks its
sizes instead of landing on a guessed face. It is opaque, so a step on another part's sketch says it cannot check
that it still meets the part.
"""
from .placer import Placer


class ScaledPlacer(Placer):
    """`inner`, a placer of a step before the scale, seen after the scale about `center` by `factors` (x, y, z, the
    measured numbers)."""

    opaque = True

    def __init__(self, inner, center, factors):
        self.inner, self.center, self.factors = inner, list(center), list(factors)

    def back(self, p):
        """The point before the scale that the scale carries to `p`."""
        return [c + (v - c) / f for v, c, f in zip(p, self.center, self.factors)]

    def place(self, p, edge):
        return None

    def material_at(self, p):
        return self.inner.material_at(self.back(p))


class ScaleMaker:
    """The placer maker of a `scale` step: every placer written before it is seen through the scale."""

    def __init__(self, center, factors):
        self.center, self.factors = center, factors

    def make(self, ctx, step_id, step):
        ctx.placers = [ScaledPlacer(placer, self.center, self.factors) for placer in ctx.placers]
        for order, placer in enumerate(ctx.placers):
            placer.order = order
        ctx.slabs = []
