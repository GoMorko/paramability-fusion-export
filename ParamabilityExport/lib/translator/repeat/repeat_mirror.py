"""Mirrors (MirrorFeature) of features and of the whole body.

A mirror plane that sits on a face or edge of the part moves when a size moves it (`follow.place_plane`), and the
copies move twice as far. A mirror of the whole body repeats every earlier step when that equals the body joined with
its image (`repeat/repeat_mirror_reach.py`). Otherwise (a round, chamfer, shell or Move among the steps, a step left out, a
cut across the plane, a body on both sides) everything written so far is gathered into one tool step and the mirror
repeats that, which is the body joined with its image by definition.
"""
from ...capture_model.step_kinds import SOLID, recipe_kind
from ...design_model.steps.repeat import mirror_plane
from ...design_model.values import Quantity
from ...design_model import words as shared
from ..combine import tool_walk
from ..faces import follow
from ..faces.follow import Motion
from ..faces.tool_placer import wrap_body
from ..result import Refusal
from ..step_walk import nesting
from .repeat_build import build
from .repeat_mirror_reach import body_mirror_problem, keep_one_side, side_of_plane
from .repeat_sources import MAX_REFERENCES, split_sources


def _mirror_plane_at(plane, shift):
    """The plane as written and the shift it was given: with a sized `shift` (how far the plane moves along its normal)
    the origin becomes formulas and the shift is returned; with none the plane and None."""
    if not shift.sized:
        return plane, None
    return dict(plane, origin=follow.shifted_origin(plane["origin"], plane["normal"], shift)), shift


def _mirror_motion(plane, shift, name):
    """The Motion of a mirror across `plane`; a plane that moves along its normal by `shift` moves the copies twice
    as far."""
    base = Motion.mirror(plane["origin"], plane["normal"], name)
    if shift is None:
        return base
    return Motion(base.rows, [shift.scaled(2.0 * c).plus(base.shift[i].n) if abs(c) > 1e-9 else base.shift[i]
                              for i, c in enumerate(plane["normal"])], by=name)


def _step_by_step(ctx, item, data, plane, written):
    """The ids of the steps to mirror one by one, or None when the mirror of every step would not equal the body
    joined with its image."""
    if ctx.gaps or any(recipe_kind(step["kind"]).repeat != SOLID for step in ctx.steps):
        return None
    if body_mirror_problem(data, plane, ctx.steps) or len(ctx.steps) > MAX_REFERENCES:
        return None
    keep_one_side(ctx, item, written, ctx.steps, side_of_plane(data["target_box_before"], plane["origin"],
                                                                 plane["normal"]))
    return [step["id"] for step in ctx.steps]


def mirror(item, ctx, sources=None):
    """`sources` is `(solid step ids, finish steps)` when the caller wrote what the mirror repeats."""
    data = item.get("data") or {}
    plane = mirror_plane(data)
    if plane is None:
        return Refusal(shared.MIRROR_PLANE)
    shift = follow.place_plane(ctx, item, data["plane"], plane["normal"], "mirrors across")
    written, moved = _mirror_plane_at(plane, shift if shift is not None else Quantity(0.0))
    entity = data.get("entity_type")
    if sources is not None:
        solids, finishes = sources
    elif entity == "bodies":
        if not data.get("combine"):
            return Refusal("A mirrored body is only copied when it is joined to the part.")
        solids, finishes = _step_by_step(ctx, item, data, plane, written), []
        if solids is None:
            if ctx.depth + 1 + nesting(ctx.steps) > tool_walk.MAX_DEPTH:
                return Refusal("The body %s is built from tools nested too deep to mirror." % tool_walk.name_of(ctx.target))
            wrapped = "%sbody_%s" % (ctx.id_prefix, item["index"])
            out = build(ctx, item, [wrapped], [], [({"kind": "mirror", "plane": written},
                                                    [_mirror_motion(plane, moved, item.get("name", ""))])], "mirror")
            if not isinstance(out, Refusal):
                out.wraps_body = wrap_body(wrapped, ctx.target.get("name"))
            return out
    elif entity == "features":
        sources = split_sources(data, ctx, "mirror")
        if isinstance(sources, Refusal):
            return sources
        solids, finishes = sources
    else:
        return Refusal(shared.MIRROR_FACES)
    motion = _mirror_motion(plane, moved, item.get("name", ""))
    return build(ctx, item, solids, finishes, [({"kind": "mirror", "plane": written}, [motion])], "mirror")
