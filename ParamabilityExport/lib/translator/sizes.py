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
            if key not in ("participants", "tools", "bodies_after", "bodies_before", "target", "profiles", "ref"):
                _construction_records(value, found)
    elif isinstance(node, list):
        for value in node:
            _construction_records(value, found)
    return found


def construction_fixes(table, item):
    """[(Fusion names, reason)] for the ticked sizes behind each construction plane or axis that the step uses itself
    (to start from, reach to, turn about or mirror across). A record without a token stands for every one of its kind.
    The reason follows "<name> stays fixed: "."""
    out = []
    data = item.get("data") if isinstance(item.get("data"), dict) else {}
    for kind, token in _construction_records(data, []):
        names = []
        for param in table.model_params.values():
            made = param.get("created_by") or {}
            if _kind(param) == kind and (not token or made.get("token") == token):
                names += [n for n in table.depends(param["name"]) if n in table.ticked]
        if names:
            out.append((tuple(dict.fromkeys(names)), "it moves the %s that %s uses" % (
                _CONSTRUCTION_WORDS[kind], item.get("name") or "a step")))
    return out


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
