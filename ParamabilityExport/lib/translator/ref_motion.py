"""How planes, faces, axes, directions and points of other components move as sizes change, followed through the
probe.

What is known about such a reference without the probe (its place, the sizes that may move it, `mark_all`) is in
`design_model/refs.py`. The probe moves the sizes that act on the component that owns it and fits how far the entity
moves from its place (`sketch_values.coverage.ref_answer`). A step asks here for the move of one reference and gets
formulas of the sizes, or a doubt that names the step and the other component:

- measured and still: the size is not marked for that reference;
- measured and moved: the move is a formula of the sizes, written into the step, and the sizes stay free;
- stuck (the reference turns, or the move is no exact formula): the sizes behind it are loose with the reason and the
  reference stays where it is;
- not measured, or no motion file: every size that acts on the owning component is loose (`refs.mark_all`).

The first translation of an export (`OPTIMISTIC`) writes the measured place and marks nothing.

`reach_motion` reads a face or plane of the part itself the same way (`own` records, with the sizes it names).
"""
from ..design_model import reach, refs, words
from ..design_model.values import Quantity
from ..design_model.refs import AXIS, DIRECTION, PLANE, PLANE_TYPES, POINT
from ..geometry import vec
from ..params import geometry_links
from ..sketch_values import coverage, keys
from ..sketch_values.motion import Affine, Stuck
from .sketch import sketch_motion
from .sketch.curved import Curved, Poly

_KEYS = {PLANE: 1, AXIS: 3, POINT: 3, DIRECTION: 1}


# ---- the move of one reference ------------------------------------------------------------------------------------

def key_names(item, ref, shape):
    """The motion keys of a reference of this `shape`, in order."""
    index, slot = item.get("index"), ref.get("slot")
    if shape == PLANE:
        return [keys.reference_offset(index, slot)]
    if shape == DIRECTION:
        return [keys.reference_dir(index, slot)]
    return [keys.reference_point(index, slot, c) for c in range(3)]


def _stuck_reason(item, ref, what, cause):
    phrase = refs.phrase(item, ref, what)
    if cause == "turns":
        return "%s that turns with it, and the copy cannot follow that" % phrase
    if cause == "unread":
        return "%s that could not be read at other values, and the copy cannot follow that" % phrase
    return "%s that moves in a way the copy cannot follow" % phrase


def _unmeasured_reason(item, ref, what, why):
    phrase = refs.phrase(item, ref, what)
    if why == coverage.NOT_TRIED:
        return "%s that may move with it, and it was not tried at other values" % phrase
    if why in (coverage.NOT_LOOKED, ""):
        return words.kept_in_place(phrase)
    return "%s that may move with it, and it could not be measured (%s)" % (phrase, why)


def raw_moves(ctx, item, ref, shape, what, names=None):
    """How far the reference moves from where the capture has it, one raw value per motion key of its `shape`: an
    `Affine` of the sizes (zero at the current sizes), or a constant zero. Sizes the move cannot follow are doubted
    here, naming the step and the other component, and their key is a constant zero. `names` are the sizes that may
    move it; by default those that act on the component that owns it."""
    zero = [Affine(0.0) for _ in range(_KEYS[shape])]
    motion = ctx.motion
    if ctx.table is None or (motion is not None and motion.optimistic):
        return zero
    names, known = refs.acting_sizes(ctx, ref) if names is None else (names, True)
    if not known or motion is None:
        refs.mark_all(ctx, item, ref, what)
        return zero
    key = geometry_links.ref_key(item.get("index"), ref.get("slot"))
    lost = {}
    for name in names:
        answer = coverage.ref_answer(ctx.table, motion, key, name)
        if answer.kind == coverage.NOT_MEASURED:
            lost.setdefault(answer.reason, []).append(name)
    for why, sizes in lost.items():
        ctx.doubt(sizes, _unmeasured_reason(item, ref, what, why))
    if motion.refs.get(key) != "":
        return zero
    out, seen = [], set()
    for name in key_names(item, ref, shape):
        value = sketch_motion.raw(ctx, name, 0.0)
        if isinstance(value, Stuck):
            movers = sketch_motion.movers(ctx.table, value)
            if (value.cause, movers) not in seen:
                seen.add((value.cause, movers))
                ctx.doubt(movers, _stuck_reason(item, ref, what, value.cause))
            value = Affine(0.0)
        out.append(value)
    if not ref.get("own") and any(sketch_motion.movers(ctx.table, v) for v in out):
        ctx.follow_component(ref.get("component"))
    return out


def _constant_apart(value):
    """`(value less its constant, the constant)` of an Affine or Curved raw value."""
    if isinstance(value, Affine):
        return Affine(0.0, value.terms, value.sketch), value.const
    if isinstance(value, Curved):
        rest = Poly({m: c for m, c in value.poly.terms.items() if m})
        return Curved(rest, value.nodes, value.sketch), value.poly.terms.get((), 0.0)
    return value, 0.0


def moves(ctx, item, ref, shape, what, names=None):
    """`raw_moves` as Quantities: formulas of the sizes whose number is zero, or a plain zero for a reference that
    stays. The constant of a formula is kept apart, so a number a step adds later folds into it."""
    out = []
    for value in raw_moves(ctx, item, ref, shape, what, names):
        rest, const = _constant_apart(value)
        written = sketch_motion.rendered(ctx.table, rest, -const) if ctx.table is not None else Quantity(0.0)
        if isinstance(written, Stuck):
            ctx.doubt(sketch_motion.movers(ctx.table, written) or written.movers,
                      _stuck_reason(item, ref, what, written.cause))
            written = Quantity(0.0)
        out.append(written.plus(const) if written.sized else Quantity(0.0))
    return out


def _normal(record, ref):
    for found in (ref.get("normal"), record.get("normal"), (record.get("plane") or {}).get("normal")):
        if refs.is_vector(found) and vec.length(found) > 1e-9:
            return vec.unit(found)
    return None


def plane_shift(ctx, item, record, direction, what):
    """How far the plane or face `record` of another component (`assembly: true`, with its `ref`) moves along unit
    `direction` as sizes change: a Quantity whose number is zero, a plain zero when it stays."""
    ref = record.get("ref") or {}
    offset = moves(ctx, item, ref, PLANE, what)[0]
    normal = _normal(record, ref)
    cosine = vec.dot(normal, direction) if normal is not None else 0.0
    if not offset.sized or abs(cosine) < 1e-9:
        return Quantity(0.0)
    if abs(abs(cosine) - 1.0) > 1e-9:
        # The offset is along the plane normal; along a slanted line the move is offset / cosine, which is no
        # fixed multiple of the sizes the way the callers write it, so the sizes are marked instead.
        refs.mark_all(ctx, item, ref, what)
        return Quantity(0.0)
    return offset.scaled(cosine)


def axis_moves(ctx, item, record, what):
    """How far the axis `record` of another component moves across its direction, one Quantity per coordinate."""
    return moves(ctx, item, record.get("ref") or {}, AXIS, what)


def shift_along(ctx, item, record, direction, what):
    """The move of a plane or axis record of another component along unit `direction` (an axis moves by the part of
    its point move along `direction`)."""
    if "dir" in record and "normal" not in record:
        shift = Quantity(0.0)
        for q, d in zip(axis_moves(ctx, item, record, what), direction):
            if q.sized and abs(d) > 1e-9:
                shift = shift.plus(q.scaled(d))
        return shift
    return plane_shift(ctx, item, record, direction, what)


def check_direction(ctx, item, place, what):
    """Marks the sizes that turn a direction taken from another component (`direction_one_place` of a rectangular
    pattern). The direction itself stays a number."""
    moves(ctx, item, place.get("ref") or {}, DIRECTION, what)


def check_own_direction(ctx, item, which, what):
    """Marks the sizes that may turn the direction `which` ("one" or "two") of a rectangular pattern taken from the part
    itself: an edge, an axis or a sketch line (`reach.direction_sizes`). The direction itself stays a number. The first
    translation of an export marks nothing, as for a direction of another component."""
    if ctx.table is None or getattr(ctx.motion, "optimistic", False):
        return
    names = reach.direction_sizes(ctx.table, ctx.capture.get("items") or [], item, which)
    if names:
        noun = reach.direction_kind(item, which)
        ctx.doubt(names, words.kept_in_place(words.ref_phrase(item, {"type": noun, "own": True}, what)))


def hole_moves(ctx, item, data, what="is placed on"):
    """One `[x, y, z]` move (Quantities) per hole position: the move of the sketch point or the vertex a position
    sits on, or of the flat face or plane the hole is placed on along its normal. A place that cannot be matched to
    the positions marks the sizes that may move it (`refs.mark_all`)."""
    count = len(data.get("positions") or ())
    out = [[Quantity(0.0)] * 3 for _ in range(count)]
    placed = [r for r in data.get("position_refs") or () if isinstance(r, dict)]
    planes = [r for r in placed if r.get("type") in PLANE_TYPES]
    points = [r for r in placed if r.get("type") not in PLANE_TYPES]
    if points and not planes and len(points) == count:
        return [moves(ctx, item, ref, POINT, what) for ref in points]
    if planes and not points and len(planes) == 1:
        ref = planes[0]
        normal = _normal({}, ref)
        offset = moves(ctx, item, ref, PLANE, what)[0]
        if normal is None or not offset.sized:
            return out
        shift = [offset.scaled(c) if abs(c) > 1e-9 else Quantity(0.0) for c in normal]
        return [list(shift) for _ in range(count)]
    seen = set()
    for ref in placed:
        key = ((ref.get("component") or {}).get("token"), ref.get("type"))
        if key not in seen:
            seen.add(key)
            refs.mark_all(ctx, item, ref, what)
    return out
