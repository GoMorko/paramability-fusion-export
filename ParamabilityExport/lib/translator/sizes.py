"""The recipe `sizes` and the sizes that cannot follow, around the size table.

The size table lists every size the person ticked. The recipe keeps only the sizes that a written formula reads, and
the sizes those formulas read in turn. A size that moves a joint cannot be followed. Sketch values follow sizes through
the probe's motion file; without one, no size that moves a sketch or construction geometry can be followed, and with
one, neither can a size behind a sketch the probe did not measure (`sketch_answer`). The driver keeps such sizes free
with a warning (`translate`).
"""
from ..params.expressions import tokenize_formula
from ..sketch_values.coverage import MOVED, NOT_MEASURED, NOT_TRIED, STILL, Answer
from ..sketch_values.motion import Affine, Stuck, Terms

# model parameter created_by kind -> what it moves, for the reason text
_STATIC_KINDS = {
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


def _reasons(table, kinds, why, names=None):
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
                found[name] = why(_STATIC_KINDS[kind])
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


def construction_only(table):
    """Fusion names of the ticked sizes that reach a model parameter made by a construction plane, but none made by a
    sketch dimension and no geometry of another component, in table order: they move the plane alone, and each step
    that uses it follows it or marks them (`construction_fixes`)."""
    sketch, plane = set(), set()
    for m in table.model_params.values():
        kind = _kind(m)
        if kind == "sketchDimension":
            sketch |= table.depends(m["name"])
        elif kind == "constructionPlane":
            plane |= table.depends(m["name"])
    for link in table.links:
        sketch |= table.depends(link["param"])
    return [name for name in table.ticked if name in plane and name not in sketch]


def joint_reasons(table, names=None):
    """{ Fusion name: why } for each ticked size (or each of `names`) that a joint reads. A joint is not copied, so
    the part does not follow such a size in the assembly."""
    return _reasons(table, ("joint",), lambda what: "it moves %s" % what, names)


def untried_reasons(table):
    """{ Fusion name: why } for each ticked size that a sketch dimension, construction plane or axis, or joint
    reads. Used when the export could not try sketches at other values, so their numbers stay as measured."""
    return _reasons(table, tuple(_STATIC_KINDS),
                    lambda what: "it changes %s, which could not be tried at other values" % what)


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


def text_reasons(table, capture):
    """{ Fusion name: why } for each ticked size that reaches a parameter of a sketch text (its height). The copy
    keeps the letters as outlines at their current size, so such a size cannot follow."""
    out = {}
    for sketch, info in _text_sketches(capture.get("items") or [], {}).items():
        reached = set()
        for name in _text_param_names(table, sketch, info):
            reached |= table.depends(name)
        for size in table.ticked:
            if size in reached:
                out.setdefault(size, "it changes the size of the text in %s, which is copied as it is now" % sketch)
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


def _driven(table, value):
    """Fusion names of the free sizes behind a motion value (an Affine's terms, a Stuck's movers and its rest)."""
    if isinstance(value, Stuck):
        names = set(value.movers) | (set(value.rest.terms) if value.rest is not None else set())
    elif isinstance(value, Affine):
        names = set(value.terms)
    elif isinstance(value, Terms):
        names = set(value.names())
    else:
        names = set()
    out = set()
    for name in names:
        out |= table.depends(name)
    return out


def sketch_answer(table, motion, sketch, size):
    """What the motion file says about size `size` (a Fusion name) and the sketch named `sketch`: an `Answer` of
    `STILL`, `MOVED` or `NOT_MEASURED`. A size the sketch does not read (`sketch_sizes`) cannot move it, so it is
    still whatever the probe did."""
    if size not in sketch_sizes(table, sketch):
        return Answer(STILL)
    reason = getattr(motion, "unmeasured", {}).get(sketch)
    if reason:
        return Answer(NOT_MEASURED, reason=reason)
    if size in getattr(motion, "untried", ()):
        return Answer(NOT_MEASURED, reason=NOT_TRIED)
    moved = [key for key, value in motion.values.items()
             if getattr(value, "sketch", "") == sketch and size in _driven(table, value)]
    return Answer(MOVED, moved) if moved else Answer(STILL)


def unmeasured_sizes(table, motion, sketch):
    """Fusion names of the free sizes whose effect on the sketch named `sketch` the probe did not measure."""
    if not getattr(motion, "unmeasured", {}).get(sketch):
        return []
    return [size for size in sketch_sizes(table, sketch)
            if sketch_answer(table, motion, sketch, size).kind == NOT_MEASURED]


def _construction_records(node, found):
    """Records of construction planes and axes in a step's data: `(kind, token)`, the token empty when unknown. A
    record of another component (`assembly`) is left out: its sizes come from its measured reference
    (`ref_motion`)."""
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
    distance as a formula (`follow._own_offset`), which checks it against where the plane was measured."""
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
    """The plane records of a step that its handler places with `follow.place_plane` or an extrude reach, which
    follow an offset plane's own distance: where an extrude starts and what each side reaches to, the plane a mirror
    or a draft uses, and the plane a split cuts along."""
    tool = data.get("tool") if isinstance(data.get("tool"), dict) else {}
    return [data.get(key) for key in ("start", "side_one", "side_two", "plane")] + [tool.get("plane")]


def construction_fixes(table, item):
    """[(Fusion names, reason)] for the ticked sizes behind each construction plane or axis that the step uses itself
    (to start from, reach to, turn about or mirror across). A record without a token stands for every one of its kind.
    An offset plane the step places (`_placed_planes`) follows its own distance (`offset_param`) and is left out.
    The reason follows "<name> stays fixed: "."""
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
    construction geometry made from parameters alone do not."""
    if ref.get("origin") or ref.get("foreign"):
        return False
    if ref.get("entity_type") in _CONSTRUCTION:
        return any(on_part(entry) for entry in ref.get("built_on") or ())
    return True


def _looks_like_origin(frame):
    """True when a sketch frame lies on an origin plane: through the origin, its normal along an axis. Used for a
    sketch reference that does not say what its plane is built on (an older capture)."""
    if not isinstance(frame, dict) or not all(isinstance(frame.get(k), list) for k in ("origin", "z")):
        return False
    z, origin = frame["z"], frame["origin"]
    return abs(sum(a * b for a, b in zip(origin, z))) <= 1e-6 and sorted(abs(c) for c in z)[-2] <= 1e-9


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
        return any(on_part(entry) for entry in reference.get("built_on") or ())
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


def _item_reads(table, item):
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
    component (its links say what moves it) or a profile that does not say what its sketch sits on."""
    reference = profile.get("reference") if isinstance(profile, dict) else None
    if table is None or not isinstance(reference, dict) or profile.get("foreign") or profile.get("face"):
        return []
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
            names |= _item_reads(table, item)
    return names


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


def reach_driven(capture, table):
    """Fusion names of the ticked sizes that may move a face or plane an extrude starts from or reaches to
    (`moving_reaches`), in table order: the sizes the probe must try so that face or plane is measured."""
    timeline = capture.get("items") or []
    found = set()
    for item in timeline:
        for _, record in moving_reaches(item):
            found |= set(reach_sizes(table, timeline, item, record))
    return [name for name in table.ticked if name in found]


def _identifiers(node, found):
    if isinstance(node, dict):
        expr = node.get("expr")
        if isinstance(expr, str):
            found.update(tok[1] for tok in tokenize_formula(expr) if tok[0] == "id")
        for value in node.values():
            _identifiers(value, found)
    elif isinstance(node, list):
        for value in node:
            _identifiers(value, found)


def used_sizes(features, sizes):
    """The entries of `sizes` (recipe name to size dict) that the written steps read, directly or through formulas."""
    wanted = set()
    _identifiers(features, wanted)
    used = {}
    pending = [name for name in sizes if name in wanted]
    while pending:
        name = pending.pop()
        if name in used:
            continue
        used[name] = sizes[name]
        reads = set()
        _identifiers({"expr": sizes[name].get("expr")}, reads)
        pending.extend(n for n in sizes if n in reads and n not in used)
    return {name: used[name] for name in sizes if name in used}
