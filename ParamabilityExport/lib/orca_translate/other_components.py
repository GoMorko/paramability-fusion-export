"""Geometry of other components that a step uses, in the Orca copy.

The Orca copy reads no motion file, so it writes every such entity where the capture places it, as numbers in the
part's coordinates:

- a step is first brought in by the shared layer (`design_model.design`; the walk and `tools.build` replay what that
  recorded inside the step's checkpoint): an outline of another component's sketch with a known place
  (`design_model.borrowed`) and a flat face or plane of another component that an extrude starts from or reaches to,
  or that a hole sits on (`design_model.refs`), lose `foreign`. The reader already gives mirror planes, split planes
  and pattern or revolve axes and directions of other components that way (`assembly: true`). A record that stays `foreign` (a curved face, an edge, no known place) is
  refused by the handler that meets it;
- once a step is copied, every measured reference it holds (`design_model.step_links.item_refs`) marks the sizes that
  act on the component that owns it (`refs.mark_all`): the copy keeps the entity where it is, so those sizes cannot
  follow there, and no such size reads as unused. Outlines of other sketches mark the sizes of that sketch when they
  are brought in (`borrowed.bring_in`).
"""
from ..capture_model import step_kinds
from ..design_model import refs, step_links, tool_chains

# What a step does with a reference, by its slot (`agent-docs/capture-format.md`, "Measured references").
_VERBS = {"start": "starts from", "side_one": "reaches to", "side_two": "reaches to",
          "direction_one": "spreads copies along", "direction_two": "spreads copies along", "positions": "is placed on"}


def _verb(item, slot):
    head = slot.split(".")[0]
    spec = step_kinds.step_type(item.get("type"))
    if head == "plane":
        return "cuts along" if spec is not None and spec.splits_bodies else "mirrors across"
    if head == "axis":
        return "turns copies about" if spec is not None and spec.repeats_sources else "turns about"
    return _VERBS.get(head, "uses")


def mark_refs(ctx, item):
    """Mark the sizes that may move each entity of another component the copied step uses (`refs.mark_all`). The
    origin planes that place a Combine's tool of another component are its place, which `tools.build` marks."""
    for entry in step_links.item_refs(item):
        if tool_chains.is_place_slot(entry["slot"]):
            continue
        refs.mark_all(ctx, item, entry["ref"], _verb(item, entry["slot"]))
