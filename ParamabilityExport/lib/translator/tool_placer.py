"""What the steps after a tool step know about it, for picks that follow sizes (see follow.py).

A tool step holds a list of steps of its own. Seen from the list that holds it, it is one placer: a point is placed on
the placers of the tool's walk, and the material it leaves comes from the tool's solid and its `combine`. Its slabs are
copies owned by the tool step, so a selector outside the tool never names a step inside it.
"""
from . import follow
from .moved_placer import carried
from .placer import ADD, CUT, Placer
from .result import Entry
from .slabs import Motion
from .values import reads_in


class ToolPlacer(Placer):
    """One tool step. `owner` is its id, `placers` the placers of its walk as seen from outside, `combine` how it meets
    the part, `unrelated` the sizes only steps before it read."""

    def __init__(self, owner, placers, combine, unrelated):
        self.owner, self.placers, self.combine, self.unrelated = owner, placers, combine, unrelated
        self.opaque = any(placer.opaque for placer in placers)

    def copied(self, owner, motion):
        """This tool carried on by `motion`, made by step `owner`. A size the motion reads now moves the tool."""
        moved_by = set(motion.needs).union(*(q.reads for q in motion.shift))
        return ToolPlacer(owner, [carried(p, owner, motion) for p in self.placers], self.combine,
                          set(self.unrelated) - moved_by)

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
        placers = [carried(placer, step_id, self.motion) for placer in self.walk.placers]
        ctx.add_placer(ToolPlacer(step_id, placers, step["combine"], unrelated))
        ctx.join_walk(self.walk)


class JoinedWalk:
    """Steps of the walk `walk` are written in this list as they are: the ids of its steps count for the items that
    made them."""

    def __init__(self, walk):
        self.walk = walk

    def make(self, ctx, step_id, step):
        ctx.join_walk(self.walk)


class WrittenFor:
    """The step carries the values of the timeline item at `index`, which another item writes."""

    def __init__(self, index):
        self.index = index

    def make(self, ctx, step_id, step):
        ctx.credit(self.index, step_id)


def wrap_body(step_id, label):
    """For `StepResult.wraps_body`: gathers everything written so far into one tool step that starts the body."""
    def wrap(ctx):
        held = ctx.set_aside()
        step = {"kind": "toolBody", "combine": "new", "features": held.steps}
        return Entry(step, [ToolMaker(held)], label=label, step_id=step_id)
    return wrap
