"""User parameters that may reach the exported body through the geometry of another component. Pure: capture dicts.

A sketch of the body can follow another component without any parameter of the body in between: a circle projected
from a pipe, or an arc constrained to such a projection. The capture records, per sketch the body's steps use, the
other components its geometry is tied to and the bodies and sketches the references point at (`sketch_links`).

Where a user parameter acts is followed through the model parameters that read it (`dependents`): a sketch
dimension acts on its sketch, on the component that owns the sketch, and on every step that takes an outline, path or
point from that sketch (`sketch_inputs` of the items) with that step's component; a feature value acts on its feature
and the feature's component.

A user parameter may reach the body through a link when:

- the link points at a sketch that one of the parameter's dimensions sits on;
- else, when the link names a body: a step that made or changed that body before the sketch is one the parameter
  drives;
- else, the link names a component the parameter acts on.

The link only says the parameter is worth trying: whether the sketch really moves with it is what the size probe
measures. A link is `{ "param", "sketch", "component", "via" }`, `via` one of "sketch", "body" or "component".
"""


def _key(record):
    """(token, name) of a component, body or sketch record; either may be empty."""
    if not isinstance(record, dict):
        return "", ""
    return str(record.get("token") or ""), str(record.get("name") or "")


def _same(a, b):
    """True when two (token, name) keys name one thing: by token when both have one, else by name."""
    (ta, na), (tb, nb) = a, b
    if ta and tb:
        return ta == tb
    return bool(na) and na == nb


def _target_component(capture):
    return _key(((capture.get("target") or {}).get("component")))


class _Sketch:
    """A sketch as a dimension names it: token, name and the token of the component it lives in."""

    def __init__(self, token, name, component):
        self.token, self.name, self.component = token or "", name or "", component or ""

    def matches(self, token, name, component=""):
        """True for the sketch with this token, or with this name in the same component."""
        if self.token and token and self.token == token:
            return True
        return bool(self.name) and self.name == name and (not self.component or not component
                                                          or self.component == component)


class Reach:
    """Where one user parameter acts: `components` ((token, name) keys), `items` (indexes of the timeline steps it
    drives) and `sketches` (the sketches its dimensions sit on)."""

    def __init__(self):
        self.components, self.items, self.sketches = [], set(), []

    def add_component(self, key):
        if any(key) and not any(_same(key, k) for k in self.components):
            self.components.append(key)


def acts(capture, param):
    """The `Reach` of a user parameter (a dict of `parameters.user`)."""
    out = Reach()
    items = capture.get("items") or []
    for dep in param.get("dependents") or []:
        component = str(dep.get("component") or "")
        out.add_component((component, ""))
        if dep.get("sketch") or dep.get("sketch_token"):
            sketch = _Sketch(dep.get("sketch_token"), dep.get("sketch"), component)
            out.sketches.append(sketch)
            for item in items:
                if any(sketch.matches(*_key(used), str(item.get("component") or ""))
                       for used in item.get("sketch_inputs") or []):
                    out.items.add(item.get("index"))
                    out.add_component((str(item.get("component") or ""), ""))
        elif dep.get("feature"):
            for item in items:
                if item.get("name") == dep["feature"] and (not component or item.get("component") == component):
                    out.items.add(item.get("index"))
    return out


def _sketch_index(capture, name):
    """Timeline index of the target's sketch named `name`, or None."""
    for item in capture.get("items") or []:
        if item.get("type") == "Sketch" and item.get("name") == name and item.get("in_target_component"):
            return item.get("index")
    return None


def _body_steps(capture, link, before):
    """Indexes of the steps that made or changed a body the link points at, before timeline index `before`."""
    bodies = [_key(b) for b in link.get("bodies") or []]
    found = set()
    for item in capture.get("items") or []:
        if before is not None and item.get("index") is not None and item["index"] >= before:
            continue
        if any(_same(_key(b), body) for b in item.get("bodies_after") or [] for body in bodies):
            found.add(item.get("index"))
    return found


def _via(capture, sketch, link, where):
    """How a parameter that acts as `where` gets to a target sketch through `link`, or None."""
    if any(s.matches(*_key(target)) for target in link.get("sketches") or [] for s in where.sketches):
        return "sketch"
    steps = _body_steps(capture, link, _sketch_index(capture, sketch))
    if steps:
        return "body" if steps & where.items else None
    return "component" if any(_same(_key(link), c) for c in where.components) else None


def tied_sketches(capture, sketches=None):
    """{ sketch name: [link record] } of the target's sketches tied to another component, also with only references
    that did not say what they point at (`unknown`; an empty list then). `sketches` limits the answer to these names
    (the ones the body's own steps use); None keeps every one."""
    own = _target_component(capture)
    out = {}
    for record in capture.get("sketch_links") or []:
        if not isinstance(record, dict) or not record.get("sketch"):
            continue
        if sketches is not None and record["sketch"] not in sketches:
            continue
        links = [link for link in record.get("links") or [] if any(_key(link)) and not _same(_key(link), own)]
        if links or record.get("unknown"):
            out[record["sketch"]] = links
    return out


def reach(capture, sketches=None):
    """The links of a capture: each user parameter that may reach a sketch of the body through another component,
    once per sketch and component, in parameter order. `sketches` as in `tied_sketches`."""
    tied = tied_sketches(capture, sketches)
    if not any(tied.values()):
        return []
    out = []
    for param in ((capture.get("parameters") or {}).get("user") or []):
        where = acts(capture, param)
        for sketch, links in tied.items():
            for link in links:
                via = _via(capture, sketch, link, where)
                if via is not None:
                    out.append({"param": param["name"], "sketch": sketch,
                                "component": link.get("name") or "another component", "via": via})
    return out


def outside(capture, sketches=None):
    """Fusion names of the user parameters that act on another component than the body's, when a sketch of the body
    is tied to another component (`tied_sketches`); else empty. The ones that act on a component a sketch is tied to
    come first, then the rest, each in parameter order. The size probe tries them to find links the reader cannot
    see."""
    tied = tied_sketches(capture, sketches)
    if not tied:
        return []
    own = _target_component(capture)
    linked = [_key(link) for links in tied.values() for link in links]
    near, far = [], []
    for param in ((capture.get("parameters") or {}).get("user") or []):
        others = [c for c in acts(capture, param).components if not _same(c, own)]
        if others:
            (near if any(_same(k, c) for c in others for k in linked) else far).append(param["name"])
    return near + far


def linked_names(links):
    """Fusion names of the parameters in `links`, in order, once each."""
    return list(dict.fromkeys(link["param"] for link in links))
