"""A face or construction plane of the part that an extrude starts from or reaches to, followed through the probe.

The slabs place most such faces (`follow.target_shift`): an end face of an earlier extrude moves with its length, a
plane offset from it with both. A face they cannot place (a side wall whose sketch line moves, a face of a step the
copy does not model, a plane built on such a face) would mark every size read before the step. The probe reads the
face or plane again at every try (`sizes.moving_reaches`) and fits how far it moves along its normal
(`<item>/r/<slot>/offset` in the motion file, like a measured reference of another component, `ref_motion`):

- the slabs follow it without a doubt: their formula is written, as before;
- else the measured move is written as a formula of the sizes, a size that does not move it is not marked, and only a
  size that moves it in a way no formula fits (or that was not tried) is marked with the step named.

Without a measurement (no probe, an older export, a face the probe could not read) the slabs decide alone.
"""
from ..params.geometry_links import ref_key
from . import follow, ref_motion, vec
from .sizes import reach_sizes
from .values import Quantity


def measured(ctx, item, slot):
    """True when the motion file holds the measured move of the face or plane in `slot` of `item`."""
    motion = ctx.motion
    return (ctx.table is not None and motion is not None and not getattr(motion, "optimistic", False)
            and getattr(motion, "refs", {}).get(ref_key(item.get("index"), slot)) == "")


def target_shift(ctx, item, slot, record, direction, what="reaches to"):
    """How the face or plane `record` in `slot` (`start`, `side_one`, `side_two`) of `item` moves along unit
    `direction`, as `follow.target_shift` gives it: a Quantity, or None when it cannot follow (its sizes are marked)."""
    if record.get("assembly") or not measured(ctx, item, slot):
        return follow.target_shift(ctx, item, record, direction, what)
    with ctx.recording() as seen:
        followed = follow.target_shift(ctx, item, record, direction, what)
    clean = followed is not None and not seen.doubts
    ctx.replay(seen, doubts=clean)
    return followed if clean else _measured_shift(ctx, item, slot, record, direction, what)


def _measured_shift(ctx, item, slot, record, direction, what):
    """The probe's move of the face or plane along `direction`, as a Quantity whose number is zero."""
    ref = {"slot": slot, "type": record.get("entity_type"), "own": True}
    names = reach_sizes(ctx.table, ctx.timeline, item, record)
    offset = ref_motion.moves(ctx, item, ref, ref_motion.PLANE, what, names)[0]
    if not offset.sized:
        return Quantity(0.0)
    cosine = vec.dot(vec.unit(record["plane"]["normal"]), direction)
    if abs(abs(cosine) - 1.0) > 1e-9:
        # The handlers refuse a slanted face; the move along a slanted line would not be a fixed multiple anyway.
        ctx.doubt(offset.reads, "%s %s a face that is not square to it, and the copy cannot follow that"
                  % (item.get("name", "a step"), what))
        return None
    return offset.scaled(cosine)
