"""Where the timeline marker waits while the sketch tries run. Pure: no Fusion imports.

Every try sets sizes and lets Fusion rebuild the design. Fusion rebuilds only the items before the timeline marker, so
moving the marker to just after the last item the part needs saves the rebuild of everything after it. An item only
depends on items before it, so the last item that is read directly is enough: whatever it was built from comes earlier.

`needed_position` works that position out from the captures. A try reads the sketches the steps use, the measured
references and the body box, so the position is just after the latest of:
- an item that may change the target body (anything but `target_changed` false);
- a sketch or construction item named by a record that carries a sketch token, a `sketch_inputs` entry or a sketch link;
- an item of another component that a sketch link, a measured reference or a tool body of a Combine depends on (the
  last item of that component, since a link gives the component and not the item);
- an assembly item that is not an occurrence (joint, rigid group and the like), which can move a component and so
  every place read at a try (an occurrence only adds a component; its own component is covered by the rules above);
- an item of a type the step kind table does not know.
When something cannot be matched (a sketch record without a name, a reference without a component, a link whose
reference has no source) the answer is "no roll": the tries keep the person's marker. The caller also checks that the
design reads the same at the rolled marker as before (`MarkerRoll.begin`).

`MarkerRoll` moves the marker through the parameter store (`DesignParameterStore.roll_marker`) for the tries and puts it
back (`unroll_marker`). The record it keeps goes to `report.json` under `probe.timeline`.
"""
from ..params import geometry_links
from ..translator import step_kinds

NO_ROLL_WHY = {
    "no_marker": "the capture does not say where the timeline marker was",
    "unnamed_sketch": "a sketch the steps use could not be matched to a timeline item",
    "nothing_to_skip": "every item before the marker is needed",
}


def _is_item(item):
    return isinstance(item, dict) and isinstance(item.get("index"), int)


ANY, OWN = None, "own"


def _sketch_uses(node, found, foreign=False):
    """Add (token, name, component) of every record under `node` that names a sketch by token. `component` is the
    token of the sketch's component when the record gives it, OWN for a record of the target's component (one not
    marked `foreign`), else ANY."""
    if isinstance(node, dict):
        foreign = foreign or node.get("foreign") is True
        token = node.get("sketch_token")
        if isinstance(token, str) and token:
            owner = node.get("component")
            owner = owner.get("token") if isinstance(owner, dict) and owner.get("token") else (ANY if foreign else OWN)
            found.append((token, node.get("sketch") or "", owner))
        for value in node.values():
            _sketch_uses(value, found, foreign)
    elif isinstance(node, list):
        for value in node:
            _sketch_uses(value, found, foreign)


def _used_sketches(capture):
    """[(token, name, component)] of the sketches the steps, the `sketch_inputs` and the links name."""
    found = []
    for item in capture.get("items") or []:
        if not _is_item(item) or item.get("suppressed"):
            continue
        _sketch_uses(item.get("data") or {}, found)
        if item.get("in_target_component") is not False or item.get("helper_of"):
            found.extend((u.get("token") or "", u.get("name") or "", ANY) for u in item.get("sketch_inputs") or []
                         if isinstance(u, dict))
    for record in capture.get("sketch_links") or []:
        if isinstance(record, dict):
            found.append((record.get("token") or "", record.get("sketch") or "", OWN))
            for link in record.get("links") or []:
                found.extend((s.get("token") or "", s.get("name") or "", ANY) for s in link.get("sketches") or []
                             if isinstance(s, dict))
    return found


def _linked_components(capture):
    """(tokens, all_other): the component tokens that links and references depend on, and whether some of them could
    not be named so that every other component counts."""
    tokens, unknown = set(), False
    for record in capture.get("sketch_links") or []:
        if not isinstance(record, dict):
            continue
        unknown = unknown or bool(record.get("unknown")) or bool(record.get("error"))
        for link in record.get("links") or []:
            token = link.get("token") if isinstance(link, dict) else None
            if token:
                tokens.add(token)
            else:
                unknown = True
    for entry in geometry_links.capture_refs(capture):
        component = entry["ref"].get("component")
        token = component.get("token") if isinstance(component, dict) else None
        if token:
            tokens.add(token)
        else:
            unknown = True
    return tokens, unknown


def _named(item, named):
    """True when a sketch or construction item is one of the `named` (name, component token) pairs."""
    return any(item.get("name") == name and (owner is ANY or item.get("component") == owner)
               for name, owner in named)


def _capture_position(capture):
    """`(position, reason)`: how many timeline items one capture needs (see the module docstring), or None and why not."""
    marker = capture.get("marker")
    if not isinstance(marker, dict) or not isinstance(marker.get("position"), int):
        return None, "no_marker"
    items = [i for i in capture.get("items") or [] if _is_item(i)]
    needed = 0
    named, unnamed = set(), False
    own = ((capture.get("target") or {}).get("component") or {}).get("token")
    for token, name, owner in _used_sketches(capture):
        if name:
            named.add((name, own if owner == OWN else owner))
        elif token:
            unnamed = True
    if unnamed or (own is None and any(owner == OWN for _, owner in named)):
        return None, "unnamed_sketch"
    components, all_other = _linked_components(capture)
    for item in items:
        if item.get("suppressed"):
            continue
        spec = step_kinds.step_type(item.get("type"))
        outside = item.get("in_target_component") is False
        needs = (item.get("target_changed") is not False
                 or spec is None or spec.role == step_kinds.UNREAD
                 or (spec.role == step_kinds.ASSEMBLY and item.get("type") != "Occurrence")
                 or (spec.role == step_kinds.SKETCH and _named(item, named))
                 or bool(item.get("helper_of"))
                 or (outside and (all_other or item.get("component") in components)))
        if needs:
            needed = max(needed, item["index"] + 1)
    return needed, ""


def needed_position(captures):
    """`(position, reason)`: the timeline position (items before the marker) the tries need for these captures, or
    `(None, key of NO_ROLL_WHY)` when the marker should stay where it is. Captures that are not dicts (a part saved as a
    fixed shape) have no tries and are left out."""
    found = [c for c in captures if isinstance(c, dict)]
    if not found:
        return None, "no_marker"
    ends, needed = set(), 0
    for capture in found:
        position, why = _capture_position(capture)
        if position is None:
            return None, why
        ends.add(capture["marker"]["position"])
        needed = max(needed, position)
    if len(ends) != 1:
        return None, "no_marker"
    end = ends.pop()
    return (needed, "") if 0 < needed < end else (None, "nothing_to_skip")


def marker_end(captures):
    """The marker position of the captures (the items the export works on), or None when they do not agree."""
    ends = {c["marker"]["position"] for c in captures
            if isinstance(c, dict) and isinstance(c.get("marker"), dict)
            and isinstance(c["marker"].get("position"), int)}
    return ends.pop() if len(ends) == 1 else None


class MarkerRoll:
    """The marker held at the position the tries need, for one export. `record` is what `report.json` keeps:
    `{ rolled, items, of, reason? }`: how many timeline items each try rebuilt, out of the items before the person's
    marker, and why the marker did not move.

    store: the parameter store; one without `roll_marker` (no timeline) never rolls. log(text): a line for the log."""

    def __init__(self, store, log):
        self.store, self.log = store, log
        self.record = None
        self._rolled = False

    def begin(self, captures, unchanged):
        """Roll the marker for the tries when that saves items. `unchanged()` is called with the marker rolled and says
        whether the design still reads as it did before (`SizeProbe.matches_start`); when it says no or raises, the
        marker goes back."""
        position, why = needed_position(captures)
        end = marker_end(captures)
        self.record = {"rolled": False, "items": end, "of": end}
        roll = getattr(self.store, "roll_marker", None)
        if position is None:
            self.record["reason"] = NO_ROLL_WHY[why]
            return
        if roll is None:
            self.record["reason"] = "the design has no timeline marker to move"
            return
        try:
            self._rolled = bool(roll(position))
            if not self._rolled:
                self.record["reason"] = "the timeline marker could not be moved"
                return
            if not unchanged():
                self.record["reason"] = "the design reads differently with the marker moved"
        except Exception as exc:
            self.log(f"marker roll failed: {exc!r}")
            self.record["reason"] = "the design could not be read with the marker moved"
        if "reason" in self.record:
            self.end()
        else:
            self.record.update(rolled=True, items=position)

    def end(self):
        """Put the marker back where it was and have Fusion build the items after the rolled position. Safe to call at
        any time and more than once."""
        if not self._rolled:
            return
        self._rolled = False
        try:
            self.store.unroll_marker()
        except Exception as exc:
            self.log(f"marker roll end failed: {exc!r}")
