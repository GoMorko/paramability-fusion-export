"""The sides of an extrude as the recipe writes them. The shared reader (`design_model/steps/extrude.py`) gives how
each side ends, which way it goes and how long it is; this module turns each side into a `RecipeSide`:
its extent, its length and taper as values that follow sizes, and the recipe's own limits (no taper on a cut through
all both ways, a taper under `MAX_TAPER_DEG`). A side up to a tilted or curved face is written by `up_to.py`."""
from ...capture_model import gap_hints
from ...design_model.problem import is_problem
from ...design_model.steps import extrude as dm
from ...geometry import vec
from .. import values
from ..result import Refusal
from .reach import distance_quantity, keep_reaches_positive, reach_quantity
from .side import RecipeSide
from .taper import taper_degrees, taper_quantity
from .up_to import up_to_side


def _from_problem(found):
    return Refusal(found.words, cause=found.cause)


def _through_both(ctx, item, sides):
    """The plan of a cut through all both ways, or a Refusal when a side is tapered. The taper of each side is
    pinned: a taper of zero cannot follow a size."""
    for side in sides:
        if side.taper:
            return Refusal("A tapered cut through all both ways is not copied yet.", cause=gap_hints.TAPER_CUT_BOTH)
        values.pin(ctx, item, side.taper_path, "a taper of zero cannot follow it")
    return [RecipeSide("through", 1, None, 0.0, read=sides[0])]


def _recipe_side(ctx, item, data, side, z, plane_q, shift_q):
    """The `RecipeSide` of one side with a distance, through all or up to a face or plane, or a Refusal."""
    if side.kind == dm.UP_TO:
        return up_to_side(ctx, item, side)
    taper = taper_degrees(side.taper)
    if isinstance(taper, Refusal):
        return taper
    if side.kind == dm.THROUGH:
        return RecipeSide("through-one", side.sign, None, taper,
                        taper_q=taper_quantity(ctx, item, side.taper_path, taper), adjusts=True, read=side)
    taper_q = taper_quantity(ctx, item, side.taper_path, taper)
    if side.kind == dm.DISTANCE:
        given = (data.get(side.which) or {}).get("quantity")
        return RecipeSide("oneSide", side.sign, side.length.n, taper, taper_q=taper_q, read=side,
                        q=given or distance_quantity(ctx, item, side.path, side.value))
    values.pin(ctx, item, side.offset_path, "it sets how far %s reaches" % item.get("name", "a step"))
    return RecipeSide("oneSide", side.sign, side.length.n, taper, taper_q=taper_q, adjusts=True, reaches=True,
                    read=side, q=reach_quantity(ctx, item, side.which, side.reach.record, z, side.reach.distance,
                                                side.offset, plane_q, shift_q))


def plan_sides(item, data, frame, shift_q, ctx, plane_q):
    """The sides to extrude, as `RecipeSide` records; or a Refusal.

    `shift_q` is where the extrude starts along the sketch normal (`reach.start_shift`) and `plane_q` the move of the
    sketch plane. A distance side that carries `quantity` (a `Quantity`, from a step written again as an extrude)
    writes that for its distance instead of a parameter's.
    """
    read = dm.read_sides(data, frame, shift_q.n, faces=True)
    if is_problem(read):
        return _from_problem(read)
    first = read[0]
    if first.kind == dm.THROUGH_BOTH:
        return _through_both(ctx, item, read)
    if first.kind == dm.SYMMETRIC:
        taper = taper_degrees(first.taper)
        if isinstance(taper, Refusal):
            return taper
        half = distance_quantity(ctx, item, first.path, first.value)
        return [RecipeSide("symmetric", 1, first.length.n, taper,
                         taper_q=taper_quantity(ctx, item, first.taper_path, taper),
                         q=half.scaled(first.scale) if first.scale != 1.0 else half, read=first)]
    z = vec.unit(frame["z"])
    out = []
    for side in read:
        entry = _recipe_side(ctx, item, data, side, z, plane_q, shift_q)
        if isinstance(entry, Refusal):
            return entry
        out.append(entry)
    if any(side.turned for side in read):
        ctx.note("Fusion stored the extrude direction two ways; the measured end of the extrude was used.")
    keep_reaches_positive(ctx, item, out)
    return out


