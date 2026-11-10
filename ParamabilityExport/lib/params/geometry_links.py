"""User parameters that may reach the exported body through the geometry of another component. Pure: capture dicts.

A sketch of the body can follow another component without any parameter of the body in between: a circle projected
from a pipe, or an arc constrained to such a projection. The capture records, per sketch the body's steps use, the
other components its geometry is tied to (`sketch_links`), and per user parameter the components that hold the model
parameters which read it (`dependent_components`). A user parameter may reach the body when one of those components
is one a sketch of the body is tied to.

Such a parameter is offered as a size and tried by the size probe like one behind a sketch dimension. Whether the
sketch really moves with it is what the probe measures; the link only says it is worth trying.

A link is `{ "param": Fusion name, "sketch": sketch name, "component": component name }`.
"""


def _component_key(record):
    """(token, name) of a component record; either may be empty."""
    if not isinstance(record, dict):
        return "", ""
    return str(record.get("token") or ""), str(record.get("name") or "")


def _same_component(a, b):
    """True when two component records name one component: by token when both have one, else by name."""
    (ta, na), (tb, nb) = a, b
    if ta and tb:
        return ta == tb
    return bool(na) and na == nb


def _target_component(capture):
    target = capture.get("target") if isinstance(capture, dict) else None
    return _component_key((target or {}).get("component"))


def sketch_components(capture, sketches=None):
    """{ sketch name: [(token, name)] } of the target's sketches tied to the geometry of another component.

    `sketches` limits the answer to these sketch names (the ones the body's own steps use); None keeps every one."""
    own = _target_component(capture)
    out = {}
    for record in (capture.get("sketch_links") or []) if isinstance(capture, dict) else []:
        if not isinstance(record, dict) or not record.get("sketch"):
            continue
        if sketches is not None and record["sketch"] not in sketches:
            continue
        for link in record.get("links") or []:
            key = _component_key(link)
            if not any(key) or _same_component(key, own):
                continue
            found = out.setdefault(record["sketch"], [])
            if not any(_same_component(key, k) for k in found):
                found.append(key)
    return out


def reach(capture, sketches=None):
    """The links of a capture: each user parameter with model parameters in a component that a sketch of the body is
    tied to, once per sketch and component, in parameter order. `sketches` as in `sketch_components`."""
    tied = sketch_components(capture, sketches)
    if not tied:
        return []
    out = []
    for param in ((capture.get("parameters") or {}).get("user") or []):
        homes = [_component_key(c) for c in param.get("dependent_components") or []]
        for sketch, components in tied.items():
            for key in components:
                if any(_same_component(key, home) for home in homes):
                    out.append({"param": param["name"], "sketch": sketch, "component": key[1] or "another component"})
    return out


def linked_names(links):
    """Fusion names of the parameters in `links`, in order, once each."""
    return list(dict.fromkeys(link["param"] for link in links))
