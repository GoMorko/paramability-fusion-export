"""Reachability: which ticked sizes may move something a step uses, and what that something is.

Every function takes the size table and reads the capture; none of them says what a copy does about a size. A
destination (the recipe, the Orca output, the probe plan) decides that. The facts:

- through the model parameters of the design (`sketch_params`, `construction_sizes`, `reasons`): the sizes behind the
  dimensions of a sketch, behind a construction plane or axis, behind a joint (`joint_reasons`) and behind the height
  of a sketch text (`text_reasons`). These live in `param_reach.py` with the offset plane of one size
  (`offset_param`), the construction geometry a step uses itself (`construction_fixes`) and the sizes a step reads
  (`step_sizes`); this module names them too;
- through the geometry of another component (`linked_sizes`, `table.links`);
- the plane a sketch sits on (`placement_sizes`, `sketch_plane_sizes`, `hole_plane_sizes`, and for a sketch of another
  component `borrowed_plane_sizes`): the sizes behind its construction plane and, for a plane on a face or on
  geometry built on the part, every size an earlier step reads;
- a face or plane a step starts from or reaches to (`moving_reaches`, `reach_sizes`, `any_face_sizes`), and any
  other plane, axis or face of the body's component that a step uses as a place (`reference_sizes`, for a sketch line
  `sketch_line_sizes`), and what may turn the direction of a rectangular pattern (`direction_sizes`);
- the offset plane whose own distance one size sets (`offset_param`, `on_part`), and the construction geometry a
  step uses itself (`construction_fixes`);
- the sizes a step reads (`step_sizes`, `item_reads`) and the sizes the probe has to try (`probed_sizes`,
  `placement_driven`, `reach_driven`).
"""
from .param_reach import (  # noqa: F401 - the reach of model parameters, named here as well
    CONSTRUCTION_KINDS, PROBED_KINDS, STATIC_KINDS, construction_fixes, construction_sizes, joint_reasons,
    linked_sizes, offset_param, placed_offsets, probed_sizes, profile_sizes, reasons, sketch_params, sketch_sizes,
    step_sizes, text_sizes)


def on_part(ref):
    """True when a plane or axis description sits on geometry of the part (a face, an edge, a sketch) or on
    construction geometry built on such, at any depth. Origin planes and axes, geometry of another component, and
    construction geometry built on origin geometry alone do not. Construction geometry that does not say what it is
    built on (none could be read, or the chain is deeper than the reader goes) counts as on the part, and so does an
    entry of `built_on` of another component or of an unknown kind: their moves are not measured."""
    if ref.get("origin") or ref.get("foreign"):
        return False
    if ref.get("entity_type") in CONSTRUCTION_KINDS:
        built = ref.get("built_on")
        if not built:
            return True
        return any(not isinstance(entry, dict) or entry.get("foreign") or on_part(entry) for entry in built)
    return True


def _looks_like_origin(frame):
    """True when a sketch frame lies on an origin plane: through the origin, its normal along an axis. Used for a
    sketch reference that does not say what its plane is built on (an older capture)."""
    if not isinstance(frame, dict) or not all(isinstance(frame.get(k), list) for k in ("origin", "z")):
        return False
    z, origin = frame["z"], frame["origin"]
    return abs(sum(a * b for a, b in zip(origin, z))) <= 1e-6 and sorted(abs(c) for c in z)[-2] <= 1e-9


def plane_fixed(table, timeline, profile, before):
    """True only when the plane the sketch of `profile` (`sketch`, `frame`, `reference`) sits on is shown to move with
    no ticked size: an origin plane, or a construction plane whose own sizes and the sizes of what it is built on
    (`built_on`) are all unticked and, for a plane on the part, the sizes read before the sketch were found and none
    is ticked. Unknown is False: no table, no reference, a sketch of another component (`foreign`, `borrowed`), a face
    used as an outline, an outline that follows the face its extrude starts from (`on_start_face`), something built
    on another component, or a sketch whose timeline item is not found. The projections of the origin of the
    sketch's own component sit still in the sketch only on such a plane (`sketch_solve.constants.own_origin`)."""
    if table is None or not isinstance(profile, dict) or any(
            profile.get(key) for key in ("foreign", "borrowed", "face", "on_start_face")):
        return False
    reference = profile.get("reference")
    if not isinstance(reference, dict):
        return False
    if reference.get("kind") == "constructionPlane" and reference.get("origin"):
        return True
    if reference.get("kind") == "constructionPlane" and not _built_without_sizes(table, reference):
        return False
    if reference.get("kind") == "constructionPlane" and not _plane_on_part(reference, profile.get("frame")):
        return True
    bound = _sketch_item(timeline, profile.get("sketch"), before)
    if bound is None:
        return False
    if isinstance(reference.get("made_by"), int):
        bound = min(bound, reference["made_by"])
    return not any(name in table.ticked for name in _reads_before(table, timeline, bound))


def _built_without_sizes(table, record, depth=8):
    """True when no ticked size is behind the construction plane or axis `record` (a `reference` or one of its
    `built_on` entries) or behind what it is built on; False for a record of another component or one past `depth`."""
    if record.get("foreign") or depth < 0:
        return False
    kind = CONSTRUCTION_KINDS.get(record.get("entity_type")) or (
        "constructionPlane" if record.get("kind") == "constructionPlane" else None)
    if kind and record.get("token") and construction_sizes(table, kind, record["token"]):
        return False
    return all(_built_without_sizes(table, entry, depth - 1) for entry in record.get("built_on") or ()
               if isinstance(entry, dict))


def _plane_on_part(reference, frame):
    """True when the plane of a sketch reference may move with the part's geometry: a face, or a construction plane
    built on the part. A construction plane described by an older capture (a token only) counts as built on the part
    unless its sketch frame lies on an origin plane."""
    kind = reference.get("kind")
    if kind != "constructionPlane":
        return kind in ("face", "other")
    if reference.get("origin"):
        return False
    if "definition" in reference or "built_on" in reference:
        return on_part(dict(reference, entity_type="ConstructionPlane"))
    return not _looks_like_origin(frame)


def _maker_sizes(table, item):
    """Fusion names of the ticked sizes behind the model parameters a construction item made (by name)."""
    kind = CONSTRUCTION_KINDS.get(item.get("type"))
    names = set()
    for param in table.model_params.values() if kind else ():
        made = param.get("created_by") or {}
        if made.get("kind") == kind and made.get("name") == item.get("name"):
            names |= table.depends(param["name"])
    return names


def item_reads(table, item):
    """Fusion names of the free sizes a timeline item reads: the values in its `data.params`, a sketch's
    dimensions, the parameters a construction plane or axis made."""
    found = set()
    params = (item.get("data") or {}).get("params")
    for ref in (params.values() if isinstance(params, dict) else ()):
        if isinstance(ref, dict) and ref.get("expression"):
            tr = table.translate(ref["expression"])
            found |= set(tr.reads)
            if not tr.ok and not tr.reads:
                found |= table.depends(ref.get("name") or "")
    if item.get("type") == "Sketch":
        found |= set(sketch_sizes(table, item.get("name") or ""))
    return found | _maker_sizes(table, item)


def _sketch_item(timeline, sketch, before):
    """Timeline index of the sketch item named `sketch` before index `before`, the last one when several match."""
    found = None
    for item in timeline:
        index = item.get("index")
        if (item.get("type") == "Sketch" and item.get("name") == sketch and isinstance(index, int)
                and (before is None or index < before)):
            found = index
    return found


def placement_sizes(table, timeline, profile, before):
    """Fusion names of the ticked sizes that may move the plane the sketch of `profile` sits on, in table order: the
    sizes behind the construction plane itself and, for a plane on a face or on construction geometry built on the
    part (a chain of planes included), every size an item of the body's component reads before the plane was made.
    `before` is the timeline index of the step that uses the sketch. Empty for an origin plane, a sketch of another
    component, still `foreign` or brought in (`borrowed`: its links and its own sizes say what moves it), or an outline
    the recipe places on the face its extrude starts from (`on_start_face`, an emboss), which follows that face. A sketch
    whose reference Fusion did not give counts as one on a face of the part, unless its frame lies on an origin plane
    (Fusion gives no reference for some sketches on faces; older captures give none for any sketch)."""
    if table is None or not isinstance(profile, dict) or profile.get("foreign") or profile.get("borrowed") \
            or profile.get("face") or profile.get("on_start_face"):
        return []
    reference = profile.get("reference")
    if not isinstance(reference, dict):
        if not profile.get("sketch") or _looks_like_origin(profile.get("frame")):
            return []
        reference = {"kind": "other"}
    names = set()
    if reference.get("kind") == "constructionPlane" and reference.get("token"):
        names |= set(construction_sizes(table, "constructionPlane", reference["token"]))
    if _plane_on_part(reference, profile.get("frame")):
        bound = _sketch_item(timeline, profile.get("sketch"), before)
        bound = before if bound is None else bound
        if isinstance(reference.get("made_by"), int):
            bound = min(bound, reference["made_by"]) if bound is not None else reference["made_by"]
        names |= _reads_before(table, timeline, bound)
    return [name for name in table.ticked if name in names]


def _reads_before(table, timeline, bound):
    """Fusion names of the sizes the items of the body's component read before timeline index `bound`."""
    names = set()
    for item in timeline:
        index = item.get("index")
        if (isinstance(index, int) and bound is not None and index < bound and not item.get("suppressed")
                and (item.get("in_target_component") is not False or item.get("helper_of"))):
            names |= item_reads(table, item)
    return names


def borrowed_plane_sizes(table, timeline, item, reference, frame):
    """Fusion names of the ticked sizes that may move the plane a sketch of another component sits on, in table order.
    `reference` is what the sketch sits on (the profile's `reference`), `frame` the sketch frame in its own
    component. A face, or a construction plane built on geometry, may belong to the part: every size an item of the
    body's component reads before the step `item` counts. The sizes that act on the sketch's own component come from
    where they act (`refs.acting_sizes`). Empty without a reference, as for a sketch of the part."""
    if table is None or not isinstance(reference, dict) or not _plane_on_part(reference, frame):
        return []
    return any_face_sizes(table, timeline, item)


def placement_driven(capture, table, profiles):
    """Fusion names of the ticked sizes that may move the plane of any of `profiles` (`(item index, profile)`
    pairs), in table order: the sizes the probe must try so the sketch plane is measured."""
    timeline = capture.get("items") or []
    found = set()
    for index, profile in profiles:
        found |= set(placement_sizes(table, timeline, profile, index))
    return [name for name in table.ticked if name in found]


# ---- sizes that may move a face or plane an extrude starts from or reaches to -------------------------------------

REACH_SLOTS = ("start", "side_one", "side_two")


def _vector(value):
    return isinstance(value, (list, tuple)) and len(value) == 3 and all(
        isinstance(v, (int, float)) and not isinstance(v, bool) for v in value)


def _may_move(record):
    """True for a face, or a construction plane built on the part (or one an older capture does not describe)."""
    if record.get("entity_type") == "BRepFace":
        return True
    if record.get("entity_type") != "ConstructionPlane" or record.get("origin"):
        return False
    return on_part(record) if "definition" in record or "built_on" in record else True


def moving_reaches(item):
    """`(slot, record)` for each flat face or construction plane of the body's component that the step `item` starts
    from or reaches to and that may move with the part, when the probe can find it again (it has a token and a flat
    place). A face or plane of another component has its own measured reference (`ref`) instead."""
    data = item.get("data")
    if (item.get("suppressed") or item.get("in_target_component") is False or not isinstance(data, dict)
            or "read_error" in data):
        return []
    out = []
    for slot in REACH_SLOTS:
        record = data.get(slot)
        if not isinstance(record, dict) or record.get("kind") not in ("fromEntity", "toEntity"):
            continue
        plane = record.get("plane")
        if (record.get("foreign") or record.get("assembly") or not record.get("token") or not isinstance(plane, dict)
                or not _vector(plane.get("point")) or not _vector(plane.get("normal"))):
            continue
        if _may_move(record):
            out.append((slot, record))
    return out


def reach_sizes(table, timeline, item, record):
    """Fusion names of the ticked sizes that may move the face or construction plane `record` that the step `item`
    starts from or reaches to, in table order: every size an item of the body's component reads before the step (for
    a plane, before the plane was made), and the sizes behind the planes of a chain."""
    if table is None:
        return []
    bound = item.get("index")
    if record.get("entity_type") == "ConstructionPlane" and isinstance(record.get("made_by"), int):
        bound = record["made_by"] if bound is None else min(bound, record["made_by"])
    names = _reads_before(table, timeline, bound)
    pending = [record]
    while pending:
        entry = pending.pop()
        if isinstance(entry, dict) and entry.get("entity_type") == "ConstructionPlane":
            if entry.get("token"):
                names |= set(construction_sizes(table, "constructionPlane", entry["token"]))
            pending.extend(entry.get("built_on") or ())
    return [name for name in table.ticked if name in names]


def _record_kind(record):
    """The Fusion type a place record stands for: its `entity_type`, else `SketchLine` for a record that names a line
    of a sketch (`entity`, `sketch_token`), a construction plane or axis for one with a token and a place (an older
    capture), else None."""
    if record.get("entity_type"):
        return record["entity_type"]
    if record.get("entity") and record.get("sketch_token"):
        return "SketchLine"
    if record.get("token") and ("normal" in record or "dir" in record):
        return "ConstructionAxis" if "dir" in record else "ConstructionPlane"
    return None


def sketch_line_sizes(table, timeline, item, sketch, reference, projected):
    """Fusion names of the ticked sizes that may move or turn a line of the sketch named `sketch` that the step `item`
    uses as a place (a turning axis, a pattern direction), as a set: the sizes of that sketch and those that may move
    the plane it sits on (`reference`, as for a profile, `placement_sizes`; a reference that was not read counts as a
    face of the part). A sketch that holds projections, or may (`projected` not false), also takes every size read
    before it: projected geometry of the part moves with them."""
    names = set(sketch_sizes(table, sketch))
    on = reference if isinstance(reference, dict) else {"kind": "other"}
    names |= set(placement_sizes(table, timeline, {"sketch": sketch, "reference": on}, item.get("index")))
    if projected is not False:
        bound = _sketch_item(timeline, sketch, item.get("index"))
        names |= _reads_before(table, timeline, item.get("index") if bound is None else bound)
    return names


def reference_sizes(table, timeline, item, record):
    """Fusion names of the ticked sizes that may move a plane, axis or face of the body's component that the step
    `item` uses as a place (a split plane, a mirror plane, a turning axis, the face a thread is cut on), in table order:
    - the sizes behind the construction planes and axes of `record` and of what it is built on (a record without a
      token stands for every one of its kind);
    - for a line or point of a sketch, those of `sketch_line_sizes`;
    - for a face, an edge, construction geometry built on the part (`on_part`) and a record that does not say what it
      is, also every size an item of the body's component reads before the step (for construction geometry, before
      it was made).
    Empty for an origin plane or axis, for a record of another component (`assembly`, `foreign`: its sizes come from
    its measured reference, `refs.mark_all`) and for a place worked out from another record of the step (`fixed`, the
    axis of a sweep path arc: the step marks the sizes of that record)."""
    if (table is None or not isinstance(record, dict) or record.get("origin") or record.get("assembly")
            or record.get("foreign") or record.get("fixed")):
        return []
    names = set()
    pending = [record]
    while pending:
        entry = pending.pop()
        if not isinstance(entry, dict) or entry.get("origin"):
            continue
        kind = CONSTRUCTION_KINDS.get(_record_kind(entry))
        if kind is not None:
            names |= set(construction_sizes(table, kind, entry.get("token") or ""))
            pending.extend(entry.get("built_on") or ())
    entity = _record_kind(record)
    if entity in ("SketchLine", "SketchPoint") and record.get("sketch"):
        names |= sketch_line_sizes(table, timeline, item, record["sketch"], record.get("sketch_reference"),
                                   record.get("sketch_projected"))
    elif entity not in CONSTRUCTION_KINDS or on_part(dict(record, entity_type=entity)):
        bound = item.get("index")
        if entity in CONSTRUCTION_KINDS and isinstance(record.get("made_by"), int):
            bound = record["made_by"] if bound is None else min(bound, record["made_by"])
        names |= _reads_before(table, timeline, bound)
    return [name for name in table.ticked if name in names]


def _direction_used(data, which):
    """True when the rectangular pattern data `data` places copies along the direction `which`: it has the direction
    and more than one copy along it."""
    direction = data.get("direction_%s" % which)
    count = data.get("quantity_%s" % which)
    return (isinstance(direction, (list, tuple)) and any(direction)
            and (not isinstance(count, (int, float)) or count > 1))


def direction_sizes(table, timeline, item, which):
    """Fusion names of the ticked sizes that may turn the direction `which` ("one" or "two") of the rectangular
    pattern `item`, in table order: for a direction taken from an edge, axis or face of the body's component
    (`direction_<which>_place` with `own`), the sizes that may move it (`reference_sizes`); for one taken from a
    sketch line (`direction_<which>_sketch`), those of `sketch_line_sizes`. Empty for a direction of another component
    (its measured reference says what moves it). A direction the pattern uses whose source is unknown (the place says
    `unknown`, or the capture names neither a place nor a sketch) may turn with every size an item of the body's
    component reads before the step."""
    if table is None:
        return []
    data = item.get("data") if isinstance(item.get("data"), dict) else {}
    place = data.get("direction_%s_place" % which)
    source = data.get("direction_%s_sketch" % which)
    if isinstance(place, dict) and place.get("own"):
        return reference_sizes(table, timeline, item, place)
    if isinstance(place, dict) and (place.get("assembly") or place.get("foreign")):
        return []
    if not isinstance(place, dict) and isinstance(source, dict) and source.get("sketch"):
        names = sketch_line_sizes(table, timeline, item, source["sketch"], source.get("reference"),
                                  source.get("projected"))
    elif isinstance(place, dict) or _direction_used(data, which):
        names = _reads_before(table, timeline, item.get("index"))
    else:
        return []
    return [name for name in table.ticked if name in names]


def direction_kind(item, which):
    """The Fusion type of what the direction `which` of the rectangular pattern `item` is taken from: the type of an
    edge, axis or face of the body's component, "SketchLine" for a sketch line, else None."""
    data = item.get("data") if isinstance(item.get("data"), dict) else {}
    place = data.get("direction_%s_place" % which)
    if isinstance(place, dict) and place.get("own"):
        return place.get("entity_type")
    return "SketchLine" if isinstance(data.get("direction_%s_sketch" % which), dict) else None


def hole_end_sizes(table, timeline, item, data):
    """Fusion names of the ticked sizes that may move the faces where the holes of `item` (its `data`) go in and come
    out of the part, in table order: every size an item of the body's component reads before the step. The sizes of
    the hole's own sketch count too: they move the hole centres, and on a part that is not equally thick everywhere a
    hole that moves goes in and comes out at other faces."""
    if table is None:
        return []
    names = _reads_before(table, timeline, item.get("index"))
    return [name for name in table.ticked if name in names]


def any_face_sizes(table, timeline, item):
    """Fusion names of the ticked sizes that may move or change a face of the body that the step `item` uses, in
    table order: every size an item of the body's component reads before the step."""
    return reach_sizes(table, timeline, item, {"entity_type": "BRepFace"})


def projection_sizes(table, timeline, item, sketch):
    """Fusion names of the ticked sizes that may move geometry projected into the sketch named `sketch` that the step
    `item` uses, in table order: every size an item of the body's component reads before that sketch (before the step
    when no such sketch comes before it). A sketch takes its projections where it sits in the timeline, so its own
    dimensions and later steps do not move them."""
    if table is None:
        return []
    bound = _sketch_item(timeline, sketch, item.get("index"))
    names = _reads_before(table, timeline, item.get("index") if bound is None else bound)
    return [name for name in table.ticked if name in names]


def sketch_plane_sizes(table, timeline, item, profile):
    """Fusion names of the ticked sizes that may move the plane the sketch of `profile` sits on, or, for a profile
    that is a face of the body (`face`), that may move or change that face (`any_face_sizes`), in table order."""
    if table is None:
        return []
    if profile.get("face"):
        return any_face_sizes(table, timeline, item)
    return placement_sizes(table, timeline, profile, item.get("index"))


def hole_plane_sizes(table, timeline, item, data):
    """Fusion names of the ticked sizes that may move the plane the holes of `item` sit on, in table order. For a
    sketch, those that may move what it sits on (`reference`, as for the sketch of an extrude); a sketch whose
    reference was not read counts as one on a face of the part (every size read before the sketch). For holes placed
    on a face without a sketch, every size read before the step."""
    if table is None:
        return []
    if not data.get("sketch"):
        return any_face_sizes(table, timeline, item)
    reference = data.get("reference")
    sketch = {"sketch": data["sketch"], "frame": data.get("sketch_frame"),
              "reference": reference if isinstance(reference, dict) else {"kind": "other"}}
    return placement_sizes(table, timeline, sketch, item.get("index"))


def reach_driven(capture, table):
    """Fusion names of the ticked sizes that may move a face or plane an extrude starts from or reaches to
    (`moving_reaches`), in table order: the sizes the probe must try so that face or plane is measured."""
    timeline = capture.get("items") or []
    found = set()
    for item in timeline:
        for _, record in moving_reaches(item):
            found |= set(reach_sizes(table, timeline, item, record))
    return [name for name in table.ticked if name in found]


