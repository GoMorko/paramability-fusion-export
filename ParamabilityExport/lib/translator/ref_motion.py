"""Planes, faces, axes, directions and points of other components that a step uses, followed through the probe.

The reader records each such entity with its place in the part's coordinates and a measured reference (`ref`, see
docs/capture-format.md). The probe moves the sizes that act on the component that owns it and fits how far the entity
moves from that place (`sketch_values.coverage.ref_answer`). A step asks here for the move of one reference and gets
formulas of the sizes, or a doubt that names the step and the other component:

- measured and still: the size is not marked for that reference;
- measured and moved: the move is a formula of the sizes, written into the step, and the sizes stay free;
- stuck (the reference turns, or the move is no exact formula): the sizes behind it are loose with the reason and the
  reference stays where it is;
- not measured, or no motion file: every size that acts on the owning component is loose (`mark_all`).

The first translation of an export (`OPTIMISTIC`) writes the measured place and marks nothing.

`bring_in` turns the face or plane of another component that an extrude starts from or reaches to, and the flat face
a hole is placed on, into records the handlers read like their own (`assembly: true`, geometry in the part's
coordinates). Anything it cannot bring in stays `foreign`, and `why_foreign` says why.
"""
from ..params import geometry_links
from ..sketch_values import coverage, keys
from ..sketch_values.motion import Affine, Stuck
from . import sketch_motion, vec
from .values import Quantity

PLANE, AXIS, POINT, DIRECTION = "plane", "axis", "point", "direction"
PLANE_TYPES = ("BRepFace", "ConstructionPlane")
_TARGET_SLOTS = ("start", "side_one", "side_two")
_KEYS = {PLANE: 1, AXIS: 3, POINT: 3, DIRECTION: 1}

_NOUNS = {"ConstructionPlane": "a plane", "ConstructionAxis": "an axis", "BRepFace": "a face", "BRepEdge": "an edge",
          "SketchPoint": "a sketch point", "SketchLine": "a sketch line", "BRepVertex": "a corner",
          "Place": "the place"}


def _name(item):
    return item.get("name", "a step")


def _vector(value):
    return isinstance(value, (list, tuple)) and len(value) == 3 and all(
        isinstance(v, (int, float)) and not isinstance(v, bool) for v in value)


# ---- who may move a reference -------------------------------------------------------------------------------------

def _acting(ctx):
    """{ component token: Fusion names of the user parameters that act on it } from the capture's parameter data
    (`geometry_links.acts`), or None when the capture does not say where parameters act (a capture without the parameter data)."""
    cache = ctx.cache.setdefault("ref_motion", {})
    if "acting" not in cache:
        users = (ctx.capture.get("parameters") or {}).get("user") or []
        found = None
        if any("dependents" in p for p in users):
            found = {}
            for p in users:
                for token, _ in geometry_links.acts(ctx.capture, p).components:
                    found.setdefault(token, []).append(p["name"])
        cache["acting"] = found
    return cache["acting"]


def acting_sizes(ctx, ref):
    """`(names, known)`: the ticked sizes that act on the component that owns `ref`, and whether the capture can say
    (it lists where parameters act, and `ref` names its owner)."""
    owner = ref.get("component") or {}
    found = _acting(ctx)
    if found is None or not owner.get("token"):
        return [], False
    return [n for n in found.get(owner["token"], ()) if n in ctx.table.ticked], True


def reaching(ctx, item):
    """`(entry, names)` for each measured reference of the step (`geometry_links.item_refs`) whose owning component
    some ticked size acts on: `names` are those sizes. The audit counts them as read by the step."""
    out = []
    for entry in geometry_links.item_refs(item):
        names, known = acting_sizes(ctx, entry["ref"])
        if known and names:
            out.append((entry, names))
    return out


def _phrase(item, ref, what):
    owner = (ref.get("component") or {}).get("name") or "another component"
    return "%s %s %s of %s" % (_name(item), what, _NOUNS.get(ref.get("type"), "geometry"), owner)


def mark_all(ctx, item, ref, what):
    """Marks every size that may move the reference: the copy keeps it where it is now. Without data on where sizes
    act, or without the owning component, the step gets a note instead. An origin plane or axis of another component
    moves with its occurrence, so it is marked like any other reference."""
    if ctx.table is None:
        return
    names, known = acting_sizes(ctx, ref)
    if not known:
        ctx.note("%s, and the sizes that may move it could not be found, so the copy keeps it where it is now."
                 % _phrase(item, ref, what))
    elif names:
        ctx.doubt(names, "%s that may move with it, and the copy cannot follow that" % _phrase(item, ref, what))


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
    phrase = _phrase(item, ref, what)
    if cause == "turns":
        return "%s that turns with it, and the copy cannot follow that" % phrase
    if cause == "unread":
        return "%s that could not be read at other values, and the copy cannot follow that" % phrase
    return "%s that moves in a way the copy cannot follow" % phrase


def _unmeasured_reason(item, ref, what, why):
    phrase = _phrase(item, ref, what)
    if why == coverage.NOT_TRIED:
        return "%s that may move with it, and it was not tried at other values" % phrase
    if why in (coverage.NOT_LOOKED, ""):
        return "%s that may move with it, and the copy cannot follow that" % phrase
    return "%s that may move with it, and it could not be measured (%s)" % (phrase, why)


def raw_moves(ctx, item, ref, shape, what):
    """How far the reference moves from where the capture has it, one raw value per motion key of its `shape`: an
    `Affine` of the sizes (zero at the current sizes), or a constant zero. Sizes the move cannot follow are doubted
    here, naming the step and the other component, and their key is a constant zero."""
    zero = [Affine(0.0) for _ in range(_KEYS[shape])]
    motion = ctx.motion
    if ctx.table is None or (motion is not None and motion.optimistic):
        return zero
    names, known = acting_sizes(ctx, ref)
    if not known or motion is None:
        mark_all(ctx, item, ref, what)
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
    return out


def moves(ctx, item, ref, shape, what):
    """`raw_moves` as Quantities: formulas of the sizes whose number is zero, or a plain zero for a reference that
    stays."""
    out = []
    for value in raw_moves(ctx, item, ref, shape, what):
        written = sketch_motion.rendered(ctx.table, value, 0.0) if ctx.table is not None else Quantity(0.0)
        if isinstance(written, Stuck):
            ctx.doubt(sketch_motion.movers(ctx.table, written) or written.movers,
                      _stuck_reason(item, ref, what, written.cause))
            written = Quantity(0.0)
        out.append(written)
    return out


def _normal(record, ref):
    for found in (ref.get("normal"), record.get("normal"), (record.get("plane") or {}).get("normal")):
        if _vector(found) and vec.length(found) > 1e-9:
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
        mark_all(ctx, item, ref, what)
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


def hole_moves(ctx, item, data, what="is placed on"):
    """One `[x, y, z]` move (Quantities) per hole position: the move of the sketch point or the vertex a position
    sits on, or of the flat face or plane the hole is placed on along its normal. A place that cannot be matched to
    the positions marks the sizes that may move it (`mark_all`)."""
    count = len(data.get("positions") or ())
    out = [[Quantity(0.0)] * 3 for _ in range(count)]
    refs = [r for r in data.get("position_refs") or () if isinstance(r, dict)]
    planes = [r for r in refs if r.get("type") in PLANE_TYPES]
    points = [r for r in refs if r.get("type") not in PLANE_TYPES]
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
    for ref in refs:
        key = ((ref.get("component") or {}).get("token"), ref.get("type"))
        if key not in seen:
            seen.add(key)
            mark_all(ctx, item, ref, what)
    return out


# ---- records of other components that the handlers can read -------------------------------------------------------

def _flat_ref(ref):
    return (isinstance(ref, dict) and ref.get("type") in PLANE_TYPES and _vector(ref.get("point"))
            and _vector(ref.get("normal")))


def _brought_target(record):
    """The extrude start or reach `record` on a flat face or plane of another component as an `assembly` record
    with its plane in the part's coordinates, or None when that is not possible."""
    ref = record.get("ref")
    if record.get("foreign") is not True or not _flat_ref(ref) or not record.get("plane"):
        return None
    out = {k: v for k, v in record.items() if k != "foreign"}
    out["plane"] = {"point": list(ref["point"]), "normal": list(ref["normal"])}
    if _vector(ref.get("face_point")):
        out["face_point"] = list(ref["face_point"])
    elif "face_point" in out:
        out["face_point"] = None
    out["assembly"] = True
    return out


def _brought_hole(data):
    """The hole `data` placed on a flat face or plane of another component without `foreign`, or None."""
    refs = data.get("position_refs")
    if data.get("foreign") is not True or not refs or not all(_flat_ref(r) for r in refs):
        return None
    return {k: v for k, v in data.items() if k != "foreign"}


def bring_in(item):
    """The item with the faces and planes of other components that its extrude start and reach, or its hole, uses
    turned into records without `foreign`, or the item itself when it uses none (or one that stays foreign)."""
    data = item.get("data")
    if not isinstance(data, dict):
        return item
    hole = _brought_hole(data) if "positions" in data else None
    if hole is not None:
        return dict(item, data=hole)
    edits = {}
    for slot in _TARGET_SLOTS:
        record = data.get(slot)
        brought = _brought_target(record) if isinstance(record, dict) else None
        if brought is not None:
            edits[slot] = brought
    return dict(item, data=dict(data, **edits)) if edits else item


def why_foreign(item):
    """Why a step stays refused for using another component's geometry, when that is a flat-face or edge case this
    module knows, else None (the generic reason applies)."""
    data = item.get("data") if isinstance(item.get("data"), dict) else {}
    for slot in _TARGET_SLOTS:
        record = data.get(slot)
        if isinstance(record, dict) and record.get("foreign") is True:
            ref = record.get("ref") or {}
            if ref.get("type") == "BRepFace" and not record.get("plane"):
                return "This step starts from or reaches to a curved face of another component, which is not copied."
            if not _flat_ref(ref):
                return ("This step starts from or reaches to a face or plane of another component whose place "
                        "could not be read, which is not copied.")
    if "positions" in data and data.get("foreign") is True:
        types = {r.get("type") for r in data.get("position_refs") or () if isinstance(r, dict)}
        if types - set(PLANE_TYPES):
            return "This hole is placed on an edge or point of another component, which is not copied."
        return "This hole is placed on a face of another component whose place could not be read, which is not copied."
    return None
