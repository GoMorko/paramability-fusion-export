"""Reachability: which ticked sizes may move something a step uses, and what that something is.

Every function takes the size table and reads the capture; none of them says what a copy does about a size. A
destination (the recipe, the Orca output, the probe plan) decides that. The facts:

- through the model parameters of the design (`sketch_params`, `construction_sizes`, `reasons`): the sizes behind the
  dimensions of a sketch, behind a construction plane or axis, behind a joint (`joint_reasons`) and behind the height
  of a sketch text (`text_reasons`);
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
# model parameter created_by kind -> what it moves, for the reason text
STATIC_KINDS = {
    "sketchDimension": "a sketch",
    "constructionPlane": "a construction plane",
    "constructionAxis": "a construction axis",
    "joint": "a joint",
}
_CONSTRUCTION = {"ConstructionPlane": "constructionPlane", "ConstructionAxis": "constructionAxis"}
_CONSTRUCTION_WORDS = {"constructionPlane": "construction plane", "constructionAxis": "construction axis"}


def _kind(param):
    """The kind of a model parameter's maker. Fusion may name a sketch dimension's creator as the sketch itself; its
    role ("Linear Dimension-2") still tells."""
    kind = (param.get("created_by") or {}).get("kind")
    if kind == "other" and "Dimension" in (param.get("role") or ""):
        kind = "sketchDimension"
    return kind


def reasons(table, kinds, why, names=None):
    """{ Fusion name: why } for each name (the ticked sizes by default) behind a model parameter made by `kinds`."""
    names = table.ticked if names is None else names
    found = {}
    for param in table.model_params.values():
        kind = _kind(param)
        if kind not in kinds:
            continue
        reads = table.depends(param["name"])
        for name in names:
            if name in reads and name not in found:
                found[name] = why(STATIC_KINDS[kind])
    return found


# Makers of the model parameters the size probe follows: a size that reads one may move a sketch.
PROBED_KINDS = ("sketchDimension", "constructionPlane")


def probed_sizes(table):
    """Fusion names of the ticked sizes that reach a model parameter made by a sketch dimension or a construction
    plane, or a sketch or a measured place through the geometry of another component (`table.links`), in table order:
    the sizes the probe must measure to follow them."""
    reached = set()
    for m in table.model_params.values():
        if (m.get("created_by") or {}).get("kind") in PROBED_KINDS:
            reached |= table.depends(m["name"])
    for link in table.links:
        reached |= table.depends(link["param"])
    return [name for name in table.ticked if name in reached]


def placed_offsets(table, capture):
    """Names of the model parameters that set the own distance of an offset plane a step of the capture places
    (`_placed_planes`, through chains of planes). A destination that writes such a distance as a formula follows those
    parameters."""
    found = set()

    def visit(ref):
        if isinstance(ref, dict) and ref.get("entity_type") == "ConstructionPlane":
            param = offset_param(table, ref)
            if param is not None:
                found.add(param["name"])
            for entry in ref.get("built_on") or ():
                visit(entry)

    for item in capture.get("items") or ():
        data = item.get("data") if isinstance(item.get("data"), dict) else {}
        for record in _placed_planes(data):
            visit(record)
    return found


def joint_reasons(table, names=None):
    """{ Fusion name: why } for each ticked size (or each of `names`) that a joint reads. A joint is not copied, so
    the part does not follow such a size in the assembly."""
    return reasons(table, ("joint",), lambda what: "it moves %s" % what, names)


def _text_sketches(node, found):
    """{ sketch name: { params: names, unknown: bool } } for the sketch text records in a step's data. `params` are the
    model parameters the reader found behind the text (its height); `unknown` is set when it could not read them (or the
    record has none)."""
    if isinstance(node, dict):
        if node.get("text") is True and node.get("sketch"):
            info = found.setdefault(node["sketch"], {"params": set(), "unknown": False})
            info["params"].update(n for n in node.get("text_params") or [] if isinstance(n, str))
            info["unknown"] = info["unknown"] or bool(node.get("text_params_unknown")) or not node.get("text_params")
        for key, value in node.items():
            if key not in ("participants", "tools", "bodies_after", "bodies_before", "target"):
                _text_sketches(value, found)
    elif isinstance(node, list):
        for value in node:
            _text_sketches(value, found)
    return found


def _text_param_names(table, sketch, info):
    """Names of the model parameters that belong to the text of `sketch`: the ones the reader named, the ones made by
    that text, and, when the reader could not tell which are the text's, every parameter with an unknown maker."""
    names = set(info["params"])
    for name, param in table.model_params.items():
        made = param.get("created_by") or {}
        kind = _kind(param)
        if kind == "sketchText" and made.get("sketch") == sketch:
            names.add(name)
        elif info["unknown"] and kind == "other" and not made.get("sketch"):
            names.add(name)
    return names


def text_sizes(table, capture):
    """{ Fusion name: sketch name } for each ticked size that reaches a parameter of a sketch text (its height). The
    text stays as outlines at the size it has now, so the first sketch text such a size reaches is named."""
    out = {}
    for sketch, info in _text_sketches(capture.get("items") or [], {}).items():
        reached = set()
        for name in _text_param_names(table, sketch, info):
            reached |= table.depends(name)
        for size in table.ticked:
            if size in reached:
                out.setdefault(size, sketch)
    return out


def sketch_params(table, sketch):
    """Fusion names of the model parameters made by the dimensions of the sketch named `sketch`."""
    if not sketch:
        return []
    return [name for name, param in table.model_params.items()
            if _kind(param) == "sketchDimension" and (param.get("created_by") or {}).get("sketch") == sketch]


def linked_sizes(table, sketch):
    """Fusion names of the free sizes that may reach the sketch named `sketch` through the geometry of another
    component (`table.links`), in table order."""
    reached = set()
    for name in table.linked(sketch) if sketch else ():
        reached |= table.depends(name)
    return [name for name in table.ticked if name in reached]


def sketch_sizes(table, sketch):
    """Fusion names of the free sizes that the sketch named `sketch` reads, in table order: through its dimensions,
    or through the geometry of another component it is drawn around (`linked_sizes`)."""
    reached = set(linked_sizes(table, sketch))
    for name in sketch_params(table, sketch):
        reached |= table.depends(name)
    return [name for name in table.ticked if name in reached]


def profile_sizes(table, profile, record=None):
    """Fusion names of the free sizes that move the sketch of an outline `profile`, in table order: its dimensions
    (those of `record`, the sketch graph of the profile, when given, else the model parameters the sketch made) and
    the geometry of another component it is drawn around (`linked_sizes`). An outline of another component's sketch
    (`foreign`, or `borrowed`) gives none: its sizes were marked when it was brought in
    (`design_model/borrowed.py`), and its sketch may share its name with one of the part's own."""
    if table is None or _other_sketch(profile):
        return []
    sketch = profile.get("sketch")
    if record is None:
        return sketch_sizes(table, sketch)
    reached = set(linked_sizes(table, sketch))
    reached |= _graph_reads(table, record)
    return [name for name in table.ticked if name in reached]


def _graph_reads(table, record):
    """Fusion names of the free sizes that the dimensions of a sketch graph record read: each dimension's parameter
    and the parameters its expression names."""
    reached = set()
    for dimension in record.get("dimensions") or []:
        if isinstance(dimension, dict):
            for name in [dimension.get("param")] + list(dimension.get("reads") or []):
                reached |= table.depends(name) if name else set()
    return reached


def _other_sketch(profile):
    return profile.get("foreign") is True or bool(profile.get("borrowed"))


def step_sizes(table, capture, item):
    """Fusion names of the free sizes a step reads, in table order: the values in its `data.params` and the
    dimensions of the sketches it uses (its own `sketch` and its outlines' sketches, with the graphs of the capture
    and the geometry of other components). An outline of another component's sketch names that sketch, which may
    share its name with one of the part's own: its sizes are the ones its dimensions read (`sketch_params` of the
    brought in profile)."""
    if table is None:
        return []
    data = item.get("data") if isinstance(item.get("data"), dict) else {}
    reached = set()
    for ref in (data.get("params") or {}).values():
        if isinstance(ref, dict) and ref.get("name"):
            reached |= table.depends(ref["name"])
    profiles = [p for p in data.get("profiles") or [] if isinstance(p, dict)]
    sketches = {p.get("sketch") for p in profiles if not _other_sketch(p)} | {data.get("sketch")}
    for profile in profiles:
        if _other_sketch(profile):
            for param in profile.get("sketch_params") or []:
                if isinstance(param, dict):
                    for name in [param.get("name")] + list(param.get("reads") or []):
                        reached |= table.depends(name) if name else set()
    for sketch in sketches:
        reached |= set(sketch_sizes(table, sketch))
    for record in capture.get("sketch_graphs") or []:
        if isinstance(record, dict) and record.get("sketch") in sketches:
            reached |= _graph_reads(table, record)
    return [name for name in table.ticked if name in reached]


def _construction_records(node, found):
    """Records of construction planes and axes in a step's data: `(kind, token)`, the token empty when unknown. A
    record of another component (`assembly`) is left out: its sizes come from its measured reference
    (`design_model/refs.py`)."""
    if isinstance(node, dict):
        if node.get("assembly"):
            return found
        kind = _CONSTRUCTION.get(node.get("entity_type"))
        if kind is None and node.get("token") and ("normal" in node or "dir" in node):
            kind = "constructionAxis" if "dir" in node else "constructionPlane"
        if kind is not None:
            found.append((kind, node.get("token") or ""))
        for key, value in node.items():
            if key not in ("participants", "tools", "bodies_after", "bodies_before", "target", "profiles", "ref",
                           "reference"):
                _construction_records(value, found)
    elif isinstance(node, list):
        for value in node:
            _construction_records(value, found)
    return found


def construction_sizes(table, kind, token=""):
    """Fusion names of the ticked sizes behind the construction planes or axes of `kind` (`constructionPlane` or
    `constructionAxis`): only the one named by `token` when given."""
    names = []
    for param in table.model_params.values():
        made = param.get("created_by") or {}
        if _kind(param) == kind and (not token or made.get("token") == token):
            names += [n for n in table.depends(param["name"]) if n in table.ticked]
    return tuple(dict.fromkeys(names))


def offset_param(table, ref):
    """The model parameter that sets how far an offset construction plane of the body's component lies from the one
    plane or face it is built on, when it is the only parameter the plane made that reads a ticked size (Fusion may
    give the plane a second one, a fixed extra offset); else None. A step that places such a plane writes that
    distance as a formula, which it checks against where the plane was measured."""
    if (table is None or not isinstance(ref, dict) or ref.get("entity_type") != "ConstructionPlane"
            or "offset" not in (ref.get("definition") or "").lower() or len(ref.get("built_on") or ()) != 1
            or not ref.get("token")):
        return None
    made = [p for p in table.model_params.values()
            if _kind(p) == "constructionPlane" and (p.get("created_by") or {}).get("token") == ref["token"]
            and table.depends(p["name"]) & set(table.ticked)]
    return made[0] if len(made) == 1 else None


def _followed_planes(table, ref, found):
    """Tokens of the offset planes in a chain (`ref` and what it is built on) whose own distance an extrude reach
    follows (`offset_param`)."""
    if isinstance(ref, dict) and ref.get("entity_type") == "ConstructionPlane":
        if offset_param(table, ref) is not None:
            found.add(ref["token"])
        for entry in ref.get("built_on") or ():
            _followed_planes(table, entry, found)
    return found


def _placed_planes(data):
    """The plane records of a step that a destination can place by an offset plane's own distance: where an extrude
    starts and what each side reaches to, the plane a mirror or a draft uses, and the plane a split cuts along."""
    tool = data.get("tool") if isinstance(data.get("tool"), dict) else {}
    return [data.get(key) for key in ("start", "side_one", "side_two", "plane")] + [tool.get("plane")]


def construction_fixes(table, item):
    """[(Fusion names, reason)] for the ticked sizes behind each construction plane or axis that the step uses itself
    (to start from, reach to, turn about or mirror across). A record without a token stands for every one of its kind.
    An offset plane the step places (`_placed_planes`) with its own distance (`offset_param`) is left out: a
    destination that writes that distance as a formula follows it. The reason is one plain clause."""
    out = []
    data = item.get("data") if isinstance(item.get("data"), dict) else {}
    followed = set()
    for record in _placed_planes(data):
        _followed_planes(table, record, followed)
    for kind, token in _construction_records(data, []):
        if token and token in followed:
            continue
        names = construction_sizes(table, kind, token)
        if names:
            out.append((names, "it moves the %s that %s uses" % (
                _CONSTRUCTION_WORDS[kind], item.get("name") or "a step")))
    return out


# ---- sizes that may move the plane a sketch sits on -----------------------------------------------------------

def on_part(ref):
    """True when a plane or axis description sits on geometry of the part (a face, an edge, a sketch) or on
    construction geometry built on such, at any depth. Origin planes and axes, geometry of another component, and
    construction geometry built on origin geometry alone do not. Construction geometry that does not say what it is
    built on (none could be read, or the chain is deeper than the reader goes) counts as on the part, and so does an
    entry of `built_on` of another component or of an unknown kind: their moves are not measured."""
    if ref.get("origin") or ref.get("foreign"):
        return False
    if ref.get("entity_type") in _CONSTRUCTION:
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
    """True when no ticked size moves or turns the plane the sketch of `profile` (`sketch`, `frame`, `reference`) sits
    on (`placement_sizes` gives none): the projections of the origin of the sketch's own component then sit still in
    the sketch (`sketch_solve.constants.own_origin`). False for a sketch of another component (`foreign`,
    `borrowed`) and a face used as an outline, whose plane this cannot tell."""
    if not isinstance(profile, dict) or profile.get("foreign") or profile.get("borrowed") or profile.get("face"):
        return False
    return not placement_sizes(table, timeline, profile, before)


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
    kind = _CONSTRUCTION.get(item.get("type"))
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
        kind = _CONSTRUCTION.get(_record_kind(entry))
        if kind is not None:
            names |= set(construction_sizes(table, kind, entry.get("token") or ""))
            pending.extend(entry.get("built_on") or ())
    entity = _record_kind(record)
    if entity in ("SketchLine", "SketchPoint") and record.get("sketch"):
        names |= sketch_line_sizes(table, timeline, item, record["sketch"], record.get("sketch_reference"),
                                   record.get("sketch_projected"))
    elif entity not in _CONSTRUCTION or on_part(dict(record, entity_type=entity)):
        bound = item.get("index")
        if entity in _CONSTRUCTION and isinstance(record.get("made_by"), int):
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


