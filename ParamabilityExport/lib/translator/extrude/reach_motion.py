"""A face or construction plane of the part that an extrude starts from or reaches to, followed through the probe.

The slabs place most such faces (`follow.target_shift`): an end face of an earlier extrude moves with its length, a
plane offset from it with both. A face they cannot place (a side wall whose sketch line moves, a face of a step the
copy does not model, a face of another body, a plane built on such a face) would mark every size read before the step.
The probe reads the face or plane again at every try (`sizes.moving_reaches`) and fits how far it moves along its
normal (`<item>/r/<slot>/offset` in the motion file, like a measured reference of another component, `ref_motion`):

- the slabs follow it without a doubt, and their move agrees with the measured one at every try that built and set
  the free sizes inside their ranges (`_agrees`): their formula is written, as before;
- else the measured move is written as a formula of the sizes, a size that does not move it is not marked, and only a
  size that moves it in a way no formula fits (or that was not tried) is marked with the step named.

So a move the slabs work out never wins over what the probe saw: a face the slabs take to stand still while the probe
saw it move follows the probe.

Without a measurement (no probe, an older export, a face the probe could not read) the slabs decide alone.
"""
from ...design_model.values import Quantity
from ...geometry import vec
from ...params.expressions.errors import ExpressionError
from ...params.expressions.evaluation import evaluate
from ...params.geometry_links import ref_key
from ...design_model import refs
from .. import ref_motion
from ..faces import follow
from ..ranges.range_check import recipe_size_values
from ...design_model.reach import reach_sizes

# How far (mm) the move the slabs work out may be from the measured move at a try before the two disagree.
AGREE_TOL = 1e-3

_FAILURES = (ExpressionError, ValueError, ZeroDivisionError, OverflowError, TypeError)


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
    clean = followed is not None and not seen.doubts and _agrees(ctx, item, slot, record, direction, followed)
    ctx.replay(seen, doubts=clean)
    return followed if clean else _measured_shift(ctx, item, slot, record, direction, what)


def _agrees(ctx, item, slot, record, direction, followed):
    """True when the move `followed` (along unit `direction`) is the probe's measured move of the face or plane at every
    try that built and set free sizes inside their ranges. False when they differ at one try, or when the measured move
    cannot be written (it is stuck) or the face is parallel to `direction`."""
    found = ref_motion.measured_offset(ctx, item, slot)
    cosine = vec.dot(vec.unit(record["plane"]["normal"]), direction)
    if found is None or abs(cosine) < 1e-9:
        return False
    if not followed.sized and not found.sized:
        return True
    start = _values(ctx.table, {}, followed, found)
    if start is None:
        return False
    for setting in _settings(ctx):
        now = _values(ctx.table, setting, followed, found)
        if now is None or abs((now[0] - start[0]) - (now[1] - start[1]) / cosine) > AGREE_TOL:
            return False
    return True


def _settings(ctx):
    """The free size values (by recipe name) of each try of the probe that built and set a free size to another value
    inside its range; sizes fixed by now stay at their values."""
    table, out = ctx.table, []
    for state in getattr(ctx.motion, "states", None) or ():
        if not state.get("built", True):
            continue
        setting = {}
        for name, value in (state.get("values") or {}).items():
            size = table.sizes.get(table.size_name(name) or "", {})
            if "value" in size and abs(value - size["value"]) > 1e-9:
                setting[table.size_name(name)] = value
        if setting and all(table.sizes[n].get("min", v) - 1e-9 <= v <= table.sizes[n].get("max", v) + 1e-9
                           for n, v in setting.items()):
            out.append(setting)
    return out


def _values(table, setting, *quantities):
    """The numbers of `quantities` at the free size values `setting`, or None when one cannot be worked out."""
    try:
        env = recipe_size_values(table, setting)
        return [float(evaluate(q.text, env)) if q.sized else q.n for q in quantities]
    except _FAILURES:
        return None


def _measured_shift(ctx, item, slot, record, direction, what):
    """The probe's move of the face or plane along `direction`, as a Quantity whose number is zero."""
    ref = {"slot": slot, "type": record.get("entity_type"), "own": True}
    names = reach_sizes(ctx.table, ctx.timeline, item, record)
    offset = ref_motion.moves(ctx, item, ref, refs.PLANE, what, names)[0]
    if not offset.sized:
        return Quantity(0.0)
    cosine = vec.dot(vec.unit(record["plane"]["normal"]), direction)
    if abs(abs(cosine) - 1.0) > 1e-9:
        # The handlers refuse a slanted face; the move along a slanted line would not be a fixed multiple anyway.
        ctx.doubt(offset.reads, "%s %s a face that is not square to it, and the copy cannot follow that"
                  % (item.get("name", "a step"), what))
        return None
    return offset.scaled(cosine)
