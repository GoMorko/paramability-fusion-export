"""Planes, faces, axes, directions and points of other components that a step uses: what is known about them.

The reader records each such entity with its place in the part's coordinates and a measured reference (`ref`, see
docs/capture-format.md "Measured references"). This module states the facts every destination needs:

- which records a step can use as its own (`bring_in`): a flat face or plane of another component that an extrude
  starts from or reaches to, and the flat face or plane a hole is placed on, get their place from `ref` and the mark
  `assembly: true` instead of `foreign`. A mirror plane and a pattern or revolve axis come from the reader that way.
  Anything that cannot be placed stays `foreign` (`is_foreign`), and `why_foreign` says why;
- which ticked sizes may move a reference (`acting_sizes`, `reaching`): those whose user parameter acts on the
  component that owns it (`params.geometry_links.acts`), and those that act on an assembly item that may place an
  occurrence (a joint, another assembly item, a Move of occurrences). The capture does not say
  which occurrence such an item places, so these count for every reference of another component;
- the doubt for a reference the copy keeps where it is (`mark_all`): those sizes. When the capture cannot say which
  sizes those are, the recorder is told (`movers_unknown`) and each destination decides what to do;
- steps from add-ins before 0.10.6 that marked the part's own geometry as another component's (`from_old_export`).

How far a reference moves as sizes change is measured by the probe; the recipe translator reads that in
`translator/ref_motion.py`. A destination that has no measured motion keeps each reference where it is and calls
`mark_all`.
"""
from ..params import geometry_links
from . import step_links, words

PLANE, AXIS, POINT, DIRECTION = "plane", "axis", "point", "direction"
PLANE_TYPES = ("BRepFace", "ConstructionPlane")
# The slots of an extrude that start from or reach to a face or plane.
TARGET_SLOTS = ("start", "side_one", "side_two")
# Lists of the bodies a step takes or makes. A body of another component in one of them has its own rules.
BODY_LISTS = ("participants", "tools", "sources", "source_bodies", "result_bodies", "bodies", "pieces")
# What the current reader always adds to a record of another component it cannot bring in: a sketch outline carries
# its `component` and `placement`, a plane or axis its `ref`.
_PLACE_KEYS = ("component", "placement", "ref", "assembly")


def is_vector(value):
    """True for a list of three plain numbers."""
    return isinstance(value, (list, tuple)) and len(value) == 3 and all(
        isinstance(v, (int, float)) and not isinstance(v, bool) for v in value)


def is_foreign(node):
    """A record of the step's data marked `foreign` by the reader: it belongs to another component. The bodies a step
    lists are left to their own rules."""
    if isinstance(node, dict):
        if node.get("foreign") is True:
            return True
        return any(is_foreign(v) for k, v in node.items() if k not in BODY_LISTS)
    if isinstance(node, list):
        return any(is_foreign(v) for v in node)
    return False


# ---- who may move a reference -------------------------------------------------------------------------------------

def _acting(ctx):
    """{ component token: Fusion names of the user parameters that act on it } from the capture's parameter data
    (`geometry_links.acts`), or None when the capture does not say where parameters act (a capture without the
    parameter data)."""
    cache = ctx.cache.setdefault("refs", {})
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


def _assembly(ctx):
    """Fusion names of the user parameters that act on an item that may place an occurrence
    (`step_links.places_occurrence`), in parameter order. Only read when the capture says where parameters act
    (`_acting`)."""
    cache = ctx.cache.setdefault("refs", {})
    if "assembly" not in cache:
        users = (ctx.capture.get("parameters") or {}).get("user") or []
        cache["assembly"] = [p["name"] for p in users if step_links.places_occurrence(ctx.capture, p)]
    return cache["assembly"]


def _target_component(ctx):
    return (((ctx.capture.get("target") or {}).get("component")) or {}).get("token") or ""


def acting_sizes(ctx, ref):
    """`(names, known)`: the ticked sizes that may move `ref`, and whether the capture can say (it lists where
    parameters act, and `ref` names its owner). These are the sizes that act on the component that owns `ref`, then
    those that act on an item that may place an occurrence (`_assembly`): they may move that component against the
    exported body's. A reference of the exported
    body's own component (`own`, or that component's token) gets no sizes of the assembly. A reference marked `root`
    (the place of the root component, which has no place of its own) gets only those."""
    owner = ref.get("component") or {}
    found = _acting(ctx)
    if found is None or not owner.get("token"):
        return [], False
    names = [] if ref.get("root") else list(found.get(owner["token"], ()))
    if not ref.get("own") and owner["token"] != _target_component(ctx):
        names += [n for n in _assembly(ctx) if n not in names]
    return [n for n in names if n in ctx.table.ticked], True


def reaching(ctx, item):
    """`(entry, names)` for each measured reference of the step (`step_links.item_refs`) whose owning component
    some ticked size acts on: `names` are those sizes."""
    out = []
    for entry in step_links.item_refs(item):
        names, known = acting_sizes(ctx, entry["ref"])
        if known and names:
            out.append((entry, names))
    return out


def phrase(item, ref, what):
    """"<step> <what> <a plane> of <component>", for the reasons about a reference."""
    return words.ref_phrase(item, ref, what)


def mark_all(ctx, item, ref, what):
    """Marks every size that may move the reference: the copy keeps it where it is now. Without data on where sizes
    act, or without the owning component, the recorder is told that the sizes are not known (`movers_unknown`), and
    the destination decides. An origin plane or axis of another component moves with its occurrence, so it is marked
    like any other reference. `what` words what the step does with it ("reaches to", "mirrors across")."""
    if ctx.table is None:
        return
    names, known = acting_sizes(ctx, ref)
    if not known:
        ctx.movers_unknown(phrase(item, ref, what))
    elif names:
        ctx.doubt(names, words.kept_in_place(phrase(item, ref, what)))


# ---- records of other components that a step can read like its own --------------------------------------------

def _flat_ref(ref):
    return (isinstance(ref, dict) and ref.get("type") in PLANE_TYPES and is_vector(ref.get("point"))
            and is_vector(ref.get("normal")))


def _brought_target(record):
    """The extrude start or reach `record` on a flat face or plane of another component as an `assembly` record
    with its plane in the part's coordinates, or None when that is not possible."""
    ref = record.get("ref")
    if record.get("foreign") is not True or not _flat_ref(ref) or not record.get("plane"):
        return None
    out = {k: v for k, v in record.items() if k != "foreign"}
    out["plane"] = {"point": list(ref["point"]), "normal": list(ref["normal"])}
    if is_vector(ref.get("face_point")):
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
    for slot in TARGET_SLOTS:
        record = data.get(slot)
        brought = _brought_target(record) if isinstance(record, dict) else None
        if brought is not None:
            edits[slot] = brought
    return dict(item, data=dict(data, **edits)) if edits else item


def _foreign_records(node, found):
    """Fills `found` with the records of `node` marked `foreign`, leaving out the body lists and what sits inside a
    foreign record."""
    if isinstance(node, dict):
        if node.get("foreign") is True:
            found.append(node)
            return
        for key, value in node.items():
            if key not in BODY_LISTS:
                _foreign_records(value, found)
    elif isinstance(node, list):
        for value in node:
            _foreign_records(value, found)


def _outline_or_plane(record):
    return isinstance(record.get("loops"), list) or (is_vector(record.get("point"))
                                                     and (is_vector(record.get("normal")) or is_vector(record.get("dir"))))


def from_old_export(item):
    """True when every record of another component in the step is a sketch outline, a plane or an axis with none of the
    place data the current reader writes for it. Add-in versions before 0.10.6 marked the part's own sketches and
    planes, seen through an occurrence, as another component's, so such a step may be the part's own geometry. An edge
    or a face record cannot be told apart this way."""
    found = []
    _foreign_records(item.get("data"), found)
    return bool(found) and all(_outline_or_plane(r) and not any(k in r for k in _PLACE_KEYS) for r in found)


def why_foreign(item):
    """Why a record of another component in the step cannot be placed, when that is a flat-face or edge case this
    module knows, else None."""
    data = item.get("data") if isinstance(item.get("data"), dict) else {}
    for slot in TARGET_SLOTS:
        record = data.get(slot)
        if isinstance(record, dict) and record.get("foreign") is True:
            ref = record.get("ref") or {}
            if ref.get("type") == "BRepFace" and not record.get("plane"):
                return words.CURVED_TARGET
            if not _flat_ref(ref):
                return words.UNPLACED_TARGET
    if "positions" in data and data.get("foreign") is True:
        types = {r.get("type") for r in data.get("position_refs") or () if isinstance(r, dict)}
        if types - set(PLANE_TYPES):
            return words.HOLE_ON_EDGE
        return words.HOLE_UNPLACED
    return None
