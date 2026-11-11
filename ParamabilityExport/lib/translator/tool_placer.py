"""What the steps after a tool step know about it, for picks that follow sizes (see follow.py).

A tool step holds a list of steps of its own. Seen from the list that holds it, it is one placer: a point is placed on
the placers of the tool's walk, and the material it leaves comes from the tool's solid and its `combine`. Its slabs are
copies owned by the tool step, so a selector outside the tool never names a step inside it.
"""
from . import follow
from .moved_placer import MovedPlacer
from .placer import ADD, CUT, Placer
from .slabs import Motion
from .values import reads_in


def _carried(placer, owner, motion):
    """`placer` as the list that holds the tool sees it: carried by `motion`, owned by the step `owner`."""
    if hasattr(placer, "copied"):
        return placer.copied(owner, motion)
    return placer if motion.is_identity else MovedPlacer(placer, motion)


class ToolPlacer(Placer):
    """One tool step. `owner` is its id, `placers` the placers of its walk as seen from outside, `combine` how it meets
    the part, `unrelated` the sizes only steps before it read."""

    def __init__(self, owner, placers, combine, unrelated):
        self.owner, self.placers, self.combine, self.unrelated = owner, placers, combine, unrelated
        self.opaque = any(placer.opaque for placer in placers)

    def copied(self, owner, motion):
        """This tool carried on by `motion`, made by step `owner`."""
        return ToolPlacer(owner, [_carried(p, owner, motion) for p in self.placers], self.combine, self.unrelated)

    def place(self, p, edge):
        for placer in reversed(self.placers):
            found = placer.place(p, edge)
            if found is not None:
                return found
        return None

    def place_on_wall(self, p):
        for placer in reversed(self.placers):
            on_wall = getattr(placer, "place_on_wall", None)
            found = on_wall(p) if on_wall is not None else None
            if found is not None:
                return found
        return None

    def material_at(self, p):
        held = follow.inside(self, p)
        if self.combine == "intersect":
            return ADD if held else CUT
        if not held:
            return None
        return CUT if self.combine == "cut" else ADD

    def crossings(self, q, n, offsets):
        return [t for placer in self.placers for t in placer.crossings(q, n, offsets)]

    @property
    def wall_offsets(self):
        return tuple(k for placer in self.placers for k in placer.wall_offsets)

    def not_moved_by(self, p):
        # What an intersect keeps can be a face of the part inside the tool, so its points say nothing.
        return self.unrelated if self.combine != "intersect" and follow.inside(self, p) else ()


class ToolMaker:
    """The placer maker of a tool step: `walk` is the context that built the tool, `motion` carries it into the frame
    of the list that holds it (None when it is built there). Writing the step also joins the walk's ids to the list's."""

    def __init__(self, walk, motion=None):
        self.walk, self.motion = walk, motion or Motion()

    def make(self, ctx, step_id, step):
        unrelated = set(ctx.written_reads) - set(reads_in(step))
        placers = [_carried(placer, step_id, self.motion) for placer in self.walk.placers]
        ctx.add_placer(ToolPlacer(step_id, placers, step["combine"], unrelated))
        ctx.join_walk(self.walk)
