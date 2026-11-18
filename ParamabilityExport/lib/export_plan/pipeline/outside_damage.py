"""A try that leaves steps of another component worse with the values back: whether the tries may end only the sizes
behind it and go on with the others (`OutsideDamage.judge`). Pure: no Fusion imports.

The tries may go on only when every step that stays worse is outside what they need:
- the timeline read names the step by its position, and the capture has an item with the same name at that position;
- no capture needs the item for its tries (`marker_roll.needed_items`: an item that may change a part, a sketch its
  steps use, an item of another component a link or a measured reference depends on, an assembly item, an item of an
  unknown type);
- no part of the export is built from it (`tried_ranges.part_step` of every capture of the export, also of a part
  whose sketches the tries do not follow);
- the item names its component.
When any of these cannot be shown, or a part of the export has no capture, the answer is None and the tries stop as
for any lasting change. The caller also
checks that the part reads as at the start with the values back before it goes on.

The sizes that end with such a try are the sizes the try moved and every user parameter that drives a step or a sketch
of a component of the worse steps (`geometry_links.acts`): more tries of them may damage that component again.
"""
from ...design_model import step_links
from ...design_model.tried_ranges import part_step
from ...params.geometry_links import acts
from ..marker_roll import needed_items

# The name of a component when the capture does not name it.
ANOTHER_COMPONENT = "another component"


def _named_components(captures):
    """Component token to its name, from the records of the captures that name a component: the target, the
    components that sketch links point at, and the components of the measured references."""
    names = {}

    def keep(record):
        if isinstance(record, dict) and record.get("token") and record.get("name"):
            names.setdefault(str(record["token"]), str(record["name"]))

    for capture in captures:
        keep((capture.get("target") or {}).get("component"))
        for record in capture.get("sketch_links") or []:
            for link in (record.get("links") or []) if isinstance(record, dict) else []:
                keep(link)
        for entry in step_links.capture_refs(capture):
            keep(entry["ref"].get("component"))
    return names


class OutsideDamage:
    """What the captures of one export tell about the steps a try left worse. `captures` are the captures of the parts
    the tries run for (their `needed_items`), `parts` every capture of the export, one per part (`captures` when
    None); an entry that is not a dict is a part whose read failed."""

    def __init__(self, captures, parts=None):
        self.captures = [c for c in captures if isinstance(c, dict)]
        parts = list(self.captures if parts is None else parts)
        self._parts_known = all(isinstance(c, dict) for c in parts)
        self._mine = [part_step(c) for c in parts if isinstance(c, dict)]
        self._needed = None  # positions of the items the tries need, worked out once; empty set and False: unknown
        self._items = {}
        for capture in self.captures:
            for item in capture.get("items") or []:
                if type(item.get("index")) is int:
                    self._items.setdefault(item["index"], item)

    def _needed_positions(self):
        """Positions of the items any capture needs for its tries, or None when one capture cannot tell."""
        if self._needed is None:
            found = set()
            for capture in self.captures:
                items, _ = needed_items(capture)
                if items is None:
                    found = False
                    break
                found.update(item["index"] for item in items)
            self._needed = found
        return self._needed if self._needed is not False else None

    def _outside(self, change):
        """The component token of the item of a worse step (`timeline_health.changes`) when it is outside what the
        tries need (see the module docstring), else None."""
        at, name = change.get("index"), change.get("name")
        item = self._items.get(at) if type(at) is int else None
        needed = self._needed_positions()
        if item is None or needed is None or item.get("name") != name or at in needed:
            return None
        if any(mine((at, name)) for mine in self._mine) or item.get("in_target_component") is not False:
            return None
        component = str(item.get("component") or "")
        return component or None

    def judge(self, worse, row):
        """`{ components, sizes, params }` when every step in `worse` (the changes still worse with the values back)
        is outside what the tries need: the names of their components, the Fusion names of the sizes `row` moved,
        and of every user parameter that drives a step or a sketch of those components. None when one step is not
        outside, or the row moved no size."""
        moved = list((row or {}).get("varied") or [])
        if not worse or not moved or not self.captures or not self._parts_known:
            return None
        tokens = []
        for change in worse:
            token = self._outside(change)
            if token is None:
                return None
            if token not in tokens:
                tokens.append(token)
        first = self.captures[0]
        params = [p["name"] for p in ((first.get("parameters") or {}).get("user") or [])
                  if any(key[0] in tokens for key in acts(first, p).components)]
        names = _named_components(self.captures)
        return {"components": list(dict.fromkeys(names.get(t, ANOTHER_COMPONENT) for t in tokens)),
                "sizes": list(dict.fromkeys(moved)), "params": list(dict.fromkeys(params))}
