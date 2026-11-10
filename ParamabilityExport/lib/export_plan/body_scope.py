"""What of a capture belongs to the picked body: its steps, the sketches they use and the model parameters behind
them. Pure: it reads the capture dict only.

Model parameters and sketches are read for the picked body's component and the components above it. A parameter or
sketch that belongs to a step of another body must not decide the sizes of this export. Something is left out only
when it is matched to such a step by name; anything that cannot be matched stays, as if no scoping existed.

Sketch and feature names repeat across components (each has its own `Sketch1`), so they are matched together with
the component token the capture records (`item.component`, `created_by.component`). Those tokens come from one read
and are only compared with each other. Captures without component tokens match by name alone.
"""
from ..params import geometry_links
from ..params.defaults import reads_of
from ..translator.capture import same_body

QUANTITY_PATHS = ("quantity", "quantity_one", "quantity_two")


def _data(item):
    data = item.get("data")
    return data if isinstance(data, dict) else {}


def _touches(item, wanted):
    """The step lists a wanted body among its bodies, or its own data names one as the body it works on."""
    if item.get("bodies_after") is None:
        return True  # unknown bodies: counted, so nothing is dropped for lack of information
    if any(same_body(b, w) for b in item["bodies_after"] for w in wanted):
        return True
    data = _data(item)
    if any(same_body(data.get("target"), w) for w in wanted):
        return True
    if data.get("operation") != "newBody":
        return any(same_body(b, w) for b in data.get("participants") or [] for w in wanted)
    return False


def body_items(capture):
    """The timeline items that build the picked body: those that touch it, or touch a tool body combined into it."""
    wanted = [capture["target"]]
    used = {}
    changed = True
    while changed:
        changed = False
        for item in capture["items"]:
            index = item.get("index")
            if index in used or item.get("suppressed") or not _touches(item, wanted):
                continue
            used[index] = item
            changed = True
            wanted.extend(b for b in _data(item).get("tools") or [] if isinstance(b, dict))
    return [used[i] for i in sorted(used, key=lambda k: (k is None, k))]


def _sketch_names(node, found, component):
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "sketch" and isinstance(value, str):
                found.add((component or "", value))
            else:
                _sketch_names(value, found, component)
    elif isinstance(node, list):
        for value in node:
            _sketch_names(value, found, component)


def _sketches_of(items):
    found = set()
    for item in items:
        _sketch_names(_data(item), found, item.get("component"))
    return found


def _step_key(item):
    return (item.get("component"), item.get("name"))


def _split(capture):
    used = body_items(capture)
    used_ids = {id(i) for i in used}
    return used, [i for i in capture["items"] if id(i) not in used_ids]


def other_sketches(capture):
    """(component token, sketch name) of the sketches that only steps outside the picked body use. The token is ''
    when the capture does not know it. A sketch no step names (hole positions, a revolve axis) is not listed, so it
    still counts as used."""
    used, rest = _split(capture)
    return _sketches_of(rest) - _sketches_of(used)


def _made_by(param):
    return param.get("created_by") or {}


def scoped_model_params(capture):
    """The model parameters of the capture that the picked body can read.

    A parameter is dropped only when it is matched to a step or sketch that the body does not use: made by a step of
    another body, or by a dimension of a sketch only other bodies use. Every other parameter stays (construction
    planes, axes and joints cannot be matched). A parameter that a kept one reads stays too.
    """
    model = list(((capture.get("parameters") or {}).get("model")) or [])
    used, rest = _split(capture)
    other_steps = {_step_key(i) for i in rest} - {_step_key(i) for i in used}
    other_sketch = other_sketches(capture)

    def drop(param):
        made = _made_by(param)
        if made.get("kind") == "feature":
            return (made.get("component"), made.get("name")) in other_steps
        if made.get("kind") == "sketchDimension":
            return (made.get("component") or "", made.get("sketch")) in other_sketch
        return False

    kept = {p["name"]: p for p in model if not drop(p)}
    lookup = {p["name"]: p for p in model}
    pending = list(kept.values())
    while pending:
        for dep in reads_of(pending.pop()):
            if dep in lookup and dep not in kept:
                kept[dep] = lookup[dep]
                pending.append(lookup[dep])
    return [p for p in model if p["name"] in kept]


def quantity_refs(capture):
    """Model parameters that drive a pattern quantity in the steps of the picked body, as read in `data.params`."""
    found = {}
    for item in body_items(capture):
        params = _data(item).get("params")
        if not isinstance(params, dict):
            continue
        for path in QUANTITY_PATHS:
            ref = params.get(path)
            if isinstance(ref, dict) and ref.get("name"):
                found[ref["name"]] = ref
    return list(found.values())


def _body_sketch_names(capture):
    return {name for _, name in _sketches_of(body_items(capture))}


def _own_items(capture):
    """The steps of the picked body, or None (all steps) when the capture does not say which body is picked."""
    try:
        return body_items(capture)
    except (KeyError, TypeError):
        return None


def body_links(capture):
    """The geometry links (`params.geometry_links`) of the picked body: those of the sketches its own steps use
    (`reach`), then those of the references of other components its steps use (`reference_links`)."""
    if not isinstance(capture, dict):
        return []
    found = []
    if capture.get("sketch_links"):
        found = geometry_links.reach(capture, _body_sketch_names(capture))
    return found + geometry_links.reference_links(capture, _own_items(capture))


def body_outside(capture):
    """Fusion names of the user parameters worth a try to find links the reader cannot see
    (`params.geometry_links.outside`), for the sketches and the references of other components the picked body's own
    steps use."""
    if not isinstance(capture, dict):
        return []
    items = _own_items(capture)
    names = None if items is None else {name for _, name in _sketches_of(items)}
    return geometry_links.outside(capture, names, items)


def scope_inputs(capture, fallback_model=()):
    """(model parameters, quantity refs) for the size table. Without a capture, the fallback model parameters of the
    whole root component are used and no quantity is known."""
    if not isinstance(capture, dict):
        return list(fallback_model), []
    return scoped_model_params(capture), quantity_refs(capture)
