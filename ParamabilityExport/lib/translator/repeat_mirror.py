"""Mirrors (MirrorFeature) of features and of the whole body.

A mirror plane that sits on a face or edge of the part moves when a size moves it (`follow.place_plane`), and the
copies move twice as far. A mirror of the whole body is only written when it equals the body joined with its image
(`repeat_mirror_reach.py`).
"""
from . import follow, notes as wording, vec
from .follow import Motion
from .repeat_build import build, round_vec
from .repeat_mirror_reach import body_mirror_problem, keep_one_side, side_of_plane
from .repeat_sources import MAX_REFERENCES, split_sources
from .result import Refusal
from .step_kinds import SOLID, recipe_kind
from .values import Quantity


def mirror_plane(data):
    plane = data.get("plane")
    if not plane or "point" not in plane or "normal" not in plane or vec.length(plane["normal"]) < 1e-9:
        return None
    return {"origin": round_vec(plane["point"]), "normal": round_vec(vec.unit(plane["normal"]))}


def _mirror_plane_at(plane, shift):
    """The plane as written and the shift it was given: with a sized `shift` (how far the plane moves along its normal)
    the origin becomes formulas and the shift is returned; with none the plane and None."""
    normal, origin = plane["normal"], plane["origin"]
    if not shift.sized:
        return plane, None
    moved = [shift.scaled(c).plus(o).json() if abs(c) > 1e-9 else o for o, c in zip(origin, normal)]
    return dict(plane, origin=moved), shift


def _mirror_motion(plane, shift, name):
    """The Motion of a mirror across `plane`; a plane that moves along its normal by `shift` moves the copies twice
    as far."""
    base = Motion.mirror(plane["origin"], plane["normal"], name)
    if shift is None:
        return base
    return Motion(base.rows, [shift.scaled(2.0 * c).plus(base.shift[i].n) if abs(c) > 1e-9 else base.shift[i]
                              for i, c in enumerate(plane["normal"])], by=name)


def mirror(item, ctx, sources=None):
    """`sources` is `(solid step ids, finish steps)` when the caller wrote what the mirror repeats."""
    data = item.get("data") or {}
    plane = mirror_plane(data)
    if plane is None:
        return Refusal("The mirror plane could not be read as a flat plane.")
    shift = follow.place_plane(ctx, item, data["plane"], plane["normal"], "mirrors across")
    written, moved = _mirror_plane_at(plane, shift if shift is not None else Quantity(0.0))
    entity = data.get("entity_type")
    if sources is not None:
        solids, finishes = sources
    elif entity == "bodies":
        if not data.get("combine"):
            return Refusal("A mirrored body is only copied when it is joined to the part.")
        if ctx.gaps:
            # The mirror repeats the written steps one by one and checks them against the plane, so it cannot
            # hold a step left out of the copy.
            return Refusal(wording.repeats_gap_reason([gap.name for gap in ctx.gaps]), [gap.id for gap in ctx.gaps])
        if any(recipe_kind(step["kind"]).repeat != SOLID for step in ctx.steps):
            return Refusal("A mirror of the whole body after a round, chamfer, shell or Move is not copied yet.")
        problem = body_mirror_problem(data, plane, ctx.steps)
        if problem:
            return Refusal(problem)
        keep_one_side(ctx, item, written, ctx.steps, side_of_plane(data["target_box_before"], plane["origin"],
                                                                     plane["normal"]))
        solids, finishes = [step["id"] for step in ctx.steps], []
        if len(solids) > MAX_REFERENCES:
            return Refusal("This mirror repeats more than %d steps." % MAX_REFERENCES)
    elif entity == "features":
        sources = split_sources(data, ctx, "mirror")
        if isinstance(sources, Refusal):
            return sources
        solids, finishes = sources
    else:
        return Refusal("Mirrors of faces are not copied yet.")
    motion = _mirror_motion(plane, moved, item.get("name", ""))
    return build(ctx, item, solids, finishes, [({"kind": "mirror", "plane": written}, [motion])], "mirror")
