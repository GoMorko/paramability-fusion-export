"""What the steps of a capture tell the geometry links (`params.geometry_links`): the measured references they hold and
the items that may place an occurrence. Pure: it reads capture dicts only.

`params.geometry_links` works out where user parameters act and which links follow from that. It does not read the
data of a step. This module reads it and hands plain values down:

- `item_refs` and `capture_refs`: the measured references (`ref`, agent-docs/capture-format.md) of the steps;
- `places_item`, `moves_occurrence`, `places_occurrence` and `placing`: the items that may place an occurrence (a joint,
  another assembly item, a Move whose inputs are not known to be bodies or faces), and the user parameters that act on
  one;
- `reach`, `reference_links` and `outside`: the links and the parameters to try of `params.geometry_links`, with these
  facts read from the capture.
"""
from ..capture_model import step_kinds
from ..params import geometry_links
from . import design

# The inputs of a Move that moves bodies or faces of its own component. A Move with other inputs moves occurrences.
_BODY_MOVES = ("bodies", "faces")


def places_item(item):
    """True for a timeline item that may place an occurrence: an assembly item (a joint, a rigid group, a motion
    link and the like), or a Move whose inputs are not known to be bodies or faces."""
    kind = item.get("type")
    if step_kinds.is_assembly(kind):
        return True
    spec = step_kinds.step_type(kind)
    return spec is not None and spec.moves_bodies and design.data_of(item).get("input_kind") not in _BODY_MOVES


def moves_occurrence(capture, dependent):
    """True when a model parameter that reads a user parameter (`dependent`, a record of `dependents`) belongs to an
    item that may place an occurrence: a joint (also a joint origin), or an item of the timeline that may
    (`places_item`), found by its name in the dependent's component."""
    if dependent.get("kind") == "joint":
        return True
    name, component = dependent.get("feature"), str(dependent.get("component") or "")
    return bool(name) and any(
        item.get("name") == name and (not component or str(item.get("component") or "") == component)
        and places_item(item) for item in capture.get("items") or [])


def places_occurrence(capture, param):
    """True when the user parameter `param` acts on an item that may place an occurrence (`moves_occurrence`)."""
    return any(moves_occurrence(capture, d) for d in param.get("dependents") or [])


def placing(capture):
    """Fusion names of the user parameters that act on an item that may place an occurrence (`places_occurrence`)."""
    return frozenset(p["name"] for p in ((capture.get("parameters") or {}).get("user") or [])
                     if places_occurrence(capture, p))


def _collect(node, found):
    """The `ref` records under `node`, then the `position_refs` of a hole (their slot is their place in the list)."""
    if isinstance(node, dict):
        ref = node.get("ref")
        if isinstance(ref, dict) and ref.get("slot"):
            found.append(ref)
        for key, value in node.items():
            if key == "position_refs" and isinstance(value, list):
                found.extend(dict(r, slot="positions.%d" % n) for n, r in enumerate(value) if isinstance(r, dict))
            elif key != "ref":
                _collect(value, found)
    elif isinstance(node, list):
        for value in node:
            _collect(value, found)


def item_refs(item):
    """The measured references of one step: `{ "key", "item", "slot", "name", "ref" }` each, in data order. A step
    that is suppressed, lies in another component or could not be read has none. A slot used twice keeps the first."""
    data = design.data_of(item)
    if item.get("suppressed") or item.get("in_target_component") is False or "read_error" in data:
        return []
    found = []
    _collect(data, found)
    out, seen = [], set()
    for ref in found:
        key = geometry_links.ref_key(item.get("index"), ref["slot"])
        if key not in seen:
            seen.add(key)
            out.append({"key": key, "item": item.get("index"), "slot": ref["slot"], "name": item.get("name") or "",
                        "ref": ref})
    return out


def capture_refs(capture, items=None):
    """The measured references of the capture's steps (`items`: only these steps, default all), in step order."""
    out = []
    for item in (capture.get("items") or []) if items is None else items:
        out.extend(item_refs(item))
    return out


def reach(capture, sketches=None):
    """`params.geometry_links.reach` of the capture: the links of the user parameters that may reach a sketch of the
    body through another component. `sketches` limits the sketches to these names."""
    return geometry_links.reach(capture, sketches, placing(capture))


def reference_links(capture, items=None):
    """`params.geometry_links.reference_links` of the measured references of `items` (default all steps)."""
    return geometry_links.reference_links(capture, capture_refs(capture, items), placing(capture))


def outside(capture, sketches=None, items=None):
    """`params.geometry_links.outside` for the sketches named in `sketches` and the measured references of `items`."""
    return geometry_links.outside(capture, sketches, capture_refs(capture, items))
