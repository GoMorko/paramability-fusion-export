"""Which ticked sizes the model parameters of the design reach: the dimensions of a sketch, a construction plane or
axis, a joint, the height of a sketch text, an offset plane whose own distance one size sets, the sizes a step
reads through its own parameters, and the makers of the model parameters behind one size (`makers_of`). `reach`
gives these names too and adds what moves the places a step uses.
"""
# model parameter created_by kind -> what it moves, for the reason text
STATIC_KINDS = {
    "sketchDimension": "a sketch",
    "constructionPlane": "a construction plane",
    "constructionAxis": "a construction axis",
    "joint": "a joint",
}
CONSTRUCTION_KINDS = {"ConstructionPlane": "constructionPlane", "ConstructionAxis": "constructionAxis"}
CONSTRUCTION_WORDS = {"constructionPlane": "construction plane", "constructionAxis": "construction axis"}


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


def makers_of(table, name):
    """`{(kind, sketch)}` of the model parameters of the table that read the free size `name`, at any depth: the kind
    of each one's maker (`feature`, `sketchDimension`, `constructionPlane`, `joint`, `other` and so on) and, for a
    sketch dimension, the name of its sketch ("" for the other kinds)."""
    out = set()
    for param in table.model_params.values():
        if name in table.depends(param["name"]):
            kind = _kind(param) or "other"
            sketch = ((param.get("created_by") or {}).get("sketch") or "") if kind == "sketchDimension" else ""
            out.add((kind, sketch))
    return out


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
        kind = CONSTRUCTION_KINDS.get(node.get("entity_type"))
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
                CONSTRUCTION_WORDS[kind], item.get("name") or "a step")))
    return out


# ---- sizes that may move the plane a sketch sits on -----------------------------------------------------------
