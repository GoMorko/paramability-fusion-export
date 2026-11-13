"""The outlines of an extrude as the recipe writes them: sketch outlines and flat faces, merged and checked."""
from .. import gap_hints, loops, notes, sketch_motion, thin_wall, values
from ...geometry import outlines, vec
from ..result import Refusal
from .common import parallel


PLANE_TOL = 1e-4


def _same_plane(profiles):
    """True when every profile frame has the first one's normal and lies in its plane."""
    first = profiles[0]["frame"]
    z = vec.unit(first["z"])
    for profile in profiles[1:]:
        other = profile["frame"]
        if not parallel(other["z"], z) or vec.dot(vec.unit(other["z"]), z) < 0:
            return False
        if abs(vec.dot(vec.sub(other["origin"], first["origin"]), z)) > PLANE_TOL:
            return False
    return True


def _parts(profile, sources):
    """(index, capture profile) of the item's profiles that make `profile`: its merged parts, or itself."""
    if "merged_from" in profile:
        return [(n, sources[n]) for n in profile["merged_from"]]
    return [(sketch_motion.profile_number(profile, next(n for n, p in enumerate(sources) if p is profile)), profile)]


def thin_wall_step(ctx, item, data, wall, profile):
    """`(side, thickness Quantity)` of a thin extrude's wall, or a Refusal when the measured end face does not fit the
    outline and thickness. The thickness follows its parameter and must stay above zero."""
    decided = thin_wall.decide(thin_wall.outer_curves(profile), wall, data.get("end_area"))
    if isinstance(decided, Refusal):
        return decided
    side, rounded = decided
    if rounded:
        ctx.note("Fusion keeps the corners of this wall sharp. The copy rounds them.")
    return side, values.quantity(ctx, item, "thin.thickness", wall["thickness"], absolute=True)


def _sketch_built(ctx, item, profiles, thin):
    """`(profile, (outer, inners), drawn)` per outline of sketch profiles (touching ones merged), or a Refusal."""
    if any(not isinstance(p.get("frame"), dict) for p in profiles):
        return Refusal("A sketch outline has no readable position.")
    if not _same_plane(profiles):
        return Refusal("This extrude uses outlines on different planes, which is not copied yet.")
    built = []
    for profile in outlines.merge_touching(profiles):
        outcome = loops.profile_loops(profile)
        if isinstance(outcome, Refusal):
            return outcome
        if thin and outcome[1]:
            return Refusal("A thin extrude of an outline with holes is not copied yet.", cause=gap_hints.THIN_OUTLINE)
        drawn = sketch_motion.outline(ctx, item, profile, outcome[0], outcome[1], _parts(profile, profiles))
        built.append((profile, outcome, drawn))
    sketch_motion.planes_apart(ctx, [drawn for _, _, drawn in built], item)
    return built


def _face_built(face, thin):
    """The one outline of a flat face (face_outline.py), as `_sketch_built` gives it, or a Refusal."""
    if thin and face.loops[1]:
        return Refusal("A thin extrude of an outline with holes is not copied yet.", cause=gap_hints.THIN_OUTLINE)
    return [(face.profile, face.loops, face.drawn)]


def outlines_built(ctx, item, face, drawn, thin):
    """`(profile, (outer, inners), drawn)` per outline: the flat face first, then the sketch outlines; or a Refusal.
    Sketch outlines beside a face must lie on its plane. The face keeps its measured plane there, so the sizes that
    move a sketch plane are marked."""
    built = []
    if face is not None:
        built = _face_built(face, thin)
        if isinstance(built, Refusal) or not drawn:
            return built
    sketches = _sketch_built(ctx, item, drawn, thin)
    if isinstance(sketches, Refusal) or face is None:
        return sketches
    if not _same_plane([face.profile] + drawn):
        return Refusal("This extrude uses outlines on different planes, which is not copied yet.")
    names = [n for _, _, one in sketches if one is not None for n in sketch_motion.movers(ctx.table, one.plane)]
    if names:
        ctx.doubt(names, notes.stuck_reason("apart", item.get("name") or ""))
    return built + sketches
