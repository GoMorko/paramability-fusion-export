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

- else, the parameter acts on an item that may place an occurrence (`design_model.step_links.places_occurrence`: a
  joint, another assembly item, a Move of occurrences): the capture does not say which occurrence that item places, so it may move any other
  component against the body, and every link to another component counts.

The link only says the parameter is worth trying: whether the sketch really moves with it is what the size probe
measures. A link is `{ "param", "sketch", "component", "via" }`, `via` one of "sketch", "body", "component" or
"assembly".

A step can also use the plane, axis, face or point of another component directly. The reader records it as a measured
reference (`ref`, docs/capture-format.md). A parameter that acts on the component that owns such a reference may move
it, so it gets a link with `via` "reference" (`reference_links`): `sketch` is empty, `step` names the step that uses the
reference and `ref` is its key (`<item index>.<slot>`).

This module does not read the data of a step. The measured references of the steps and the parameters that may place
an occurrence come from `design_model.step_links`, which also gives `reach`, `reference_links` and `outside` with
these facts read from the capture.
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


# ---- measured references of the steps ------------------------------------------------------------------------

def ref_key(index, slot):
    """The key of a measured reference: the timeline index of the step and the slot the step uses it in."""
    return "%s.%s" % (index, slot)


def _owners(refs):
    """The (token, name) keys of the components that own the references, once each."""
    out = []
    for r in refs:
        key = _key(r["ref"].get("component"))
        if any(key) and not any(_same(key, k) for k in out):
            out.append(key)
    return out


def _placed_against_part(capture, ref, owner):
    """True when a reference of `owner` moves with the place of its occurrence against the part: it is not a
    reference of the part's own component (`own`, or the target's component)."""
    return not ref.get("own") and not _same(owner, _target_component(capture))


def reference_links(capture, refs, placing):
    """The links of the user parameters that may move one of the measured references `refs` of the steps
    (`design_model.step_links.capture_refs`), once per parameter and component, in parameter order: `via` "reference"
    for a parameter that acts on the component that owns it, else "assembly" for one in `placing` (the names of the
    parameters that may place an occurrence) when the reference moves with the place of its occurrence
    (`_placed_against_part`). Without `dependents` in the capture there is nothing to say about where parameters act,
    so no links."""
    if not refs:
        return []
    out = []
    for param in ((capture.get("parameters") or {}).get("user") or []):
        where = acts(capture, param)
        places = param["name"] in placing
        seen = []
        for r in refs:
            owner = _key(r["ref"].get("component"))
            if not any(owner) or any(_same(owner, k) for k in seen):
                continue
            if any(_same(owner, c) for c in where.components):
                via = "reference"
            elif places and _placed_against_part(capture, r["ref"], owner):
                via = "assembly"
            else:
                continue
            seen.append(owner)
            out.append({"param": param["name"], "sketch": "", "component": owner[1] or "another component",
                        "via": via, "step": r["name"], "ref": r["key"]})
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


def reach(capture, sketches, placing):
    """The links of a capture: each user parameter that may reach a sketch of the body through another component,
    once per sketch and component, in parameter order. `sketches` as in `tied_sketches`. `placing` are the names of
    the parameters that may place an occurrence (`design_model.step_links.placing`): they reach every tied sketch."""
    tied = tied_sketches(capture, sketches)
    if not any(tied.values()):
        return []
    out = []
    for param in ((capture.get("parameters") or {}).get("user") or []):
        where = acts(capture, param)
        places = param["name"] in placing
        for sketch, links in tied.items():
            for link in links:
                via = _via(capture, sketch, link, where) or ("assembly" if places else None)
                if via is not None:
                    out.append({"param": param["name"], "sketch": sketch,
                                "component": link.get("name") or "another component", "via": via})
    return out


def outside(capture, sketches, refs):
    """Fusion names of the user parameters that act on another component than the body's, when a sketch of the body
    is tied to another component (`tied_sketches`) or a step uses a reference of one (`refs`, the measured references
    of the steps, `design_model.step_links.capture_refs`);
    else empty. The ones that act on a component a sketch is tied to or that owns a reference come first, then the
    rest, each in parameter order. The size probe tries them to find links the reader cannot see."""
    tied = tied_sketches(capture, sketches)
    owners = _owners(refs)
    if not tied and not owners:
        return []
    own = _target_component(capture)
    linked = [_key(link) for links in tied.values() for link in links] + owners
    near, far = [], []
    for param in ((capture.get("parameters") or {}).get("user") or []):
        others = [c for c in acts(capture, param).components if not _same(c, own)]
        if others:
            (near if any(_same(k, c) for c in others for k in linked) else far).append(param["name"])
    return near + far


def linked_names(links):
    """Fusion names of the parameters in `links`, in order, once each."""
    return list(dict.fromkeys(link["param"] for link in links))
