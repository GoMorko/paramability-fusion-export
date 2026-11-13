"""Placer makers: what a handler hands the walk with a step so that later picks on the faces it makes follow sizes.

A handler cannot make the placers itself: a placer needs the step's id, and the step's final `combine`, which a Combine
sets later for a tool body. So the handler adds a maker to the step's `Entry` (`result.StepResult.add`), and the walk
calls `make(ctx, step_id, step)` once the step is written. A maker registers its placers on the context
(`Context.add_placer`, `Context.add_slab`).
"""
from . import follow, meets_part
from .end_caps import Cap, EndCaps
from .offset_faces import MovedFaces
from .picks import face_points
from .shells import Shell
from .slabs import Slab
from .thin_wall import ThinWall
from .values import reads_in


class SlabMaker:
    """An extrude that runs one side or both sides by a length: `on` its written placement, `extent`, `length` and
    `taper` Quantities, `profile` the capture profile and `outline` the sketch_motion.Outline when the sketch follows
    sizes. A step drawn on another component's sketch is also checked to keep meeting the part (meets_part.py)."""

    def __init__(self, on, extent, length, profile, taper, outline):
        self.on, self.extent, self.length = on, extent, length
        self.profile, self.taper, self.outline = profile, taper, outline

    def make(self, ctx, step_id, step):
        combine = step.get("combine", "add")
        borrowed = self.profile.get("borrowed")
        if borrowed:
            label = step.get("label") or "a step"
            meets_part.check(ctx, step_id, self, combine, "%s (drawn on %s of %s)" % (
                label, self.profile.get("sketch") or "a sketch", borrowed))
        ctx.add_slab(Slab(step_id, self.on, self.extent, self.length, self.profile, combine=combine,
                          taper=self.taper, outline=self.outline))


class EndCapsMaker:
    """A sweep or loft: `faces` maps start (and end, when its place is known) to the `(frame, profile)` of that face's
    outline, `walk` is the sweep's `sweep_frames.SideWalk` or None. The faces follow the sizes the written step
    reads."""

    def __init__(self, faces, walk=None):
        self.faces, self.walk = faces, walk

    def make(self, ctx, step_id, step):
        caps = {which: Cap(frame, profile) for which, (frame, profile) in self.faces.items()}
        ctx.add_placer(EndCaps(step_id, step.get("label") or "a step", reads_in(step), caps, self.walk))


class ThinWallMaker:
    """A thin extrude: `on`, `extent`, `length` (a Quantity) and `profile` as for a SlabMaker, `side` where the wall sits
    against the outline and `thickness` its measured value in mm. It leaves material and no placeable faces."""

    def __init__(self, on, extent, length, profile, side, thickness):
        self.on, self.extent, self.length = on, extent, length
        self.profile, self.side, self.thickness = profile, side, thickness

    def make(self, ctx, step_id, step):
        ctx.add_placer(ThinWall(step_id, self.on, self.extent, self.length, self.profile, self.side, self.thickness,
                                step.get("combine", "add")))


class ShellMaker:
    """A shell: `thickness` a Quantity, `faces` the capture faces it opens."""

    def __init__(self, thickness, faces):
        self.thickness, self.faces = thickness, faces

    def make(self, ctx, step_id, step):
        opened = [follow.locate(ctx, p) for p in face_points(self.faces)]
        ctx.add_placer(Shell(self.thickness, ctx.slabs, [o for o in opened if o is not None]))


class MovedFacesMaker:
    """An offsetFaces step: `faces` the capture faces it moves. The distance is the step's written one."""

    def __init__(self, faces):
        self.faces = faces

    def make(self, ctx, step_id, step):
        moved = MovedFaces(self.faces, step["distance"])
        moved.earlier = lambda p, edge: follow.locate(ctx, p, edge, moved)
        ctx.add_placer(moved)


class CopiesMaker:
    """A pattern or mirror: `motions` carry the steps it repeats (`of`) to each copy, and the slabs and tools of those
    steps are copied with them."""

    def __init__(self, motions):
        self.motions = motions

    def make(self, ctx, step_id, step):
        sources = [s for of in step.get("of") or [] for s in ctx.placers_of(of)]
        for motion in self.motions:
            for source in sources:
                made = source.copied(step_id, motion)
                (ctx.add_slab if isinstance(made, Slab) else ctx.add_placer)(made)
