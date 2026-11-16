"""Tool bodies of a Combine: which timeline items build one, and where a tool of another component sits.

A Combine takes tool bodies. To copy a tool, a destination writes again the items that made it (`read`):

- the items of the tool's component that list the tool after them (`made_by`, the rule of `capture_model.tool_items`);
- for a tool that a Split Body made, the items that built each body it was split from, up to each split
  (`lineage_chain`, the links of `capture_model.lineage`);
- an item that may have changed the tool but that the rule above cannot see (`unseen_change`): a step of another
  component that lists the tool, or one that lists its name under another token.

A tool of another component (`tool_items.is_foreign_tool`) was read in that component's own coordinates (its steps
are `helper_of` items). `place_of` gives the rigid move that carries those coordinates into the coordinates of the
exported body's component at the Combine, or the problem that stops it, and the reference whose movers may move the
tool's component. `component_frame` gives the frame of the component that a walk builds in, for the capture data that
the reader keeps in assembly coordinates (the copies of a pattern).

These are facts only: each destination decides what to write from them. Pure: it reads capture dicts only.
"""
from dataclasses import dataclass

from ..capture_model import gap_hints, lineage, step_kinds, tool_items
from ..capture_model.capture import outside_component, renamed_target, same_body
from ..geometry import rigid
from . import roles
from .problem import Problem

# Why an item that `made_by` cannot see stops the copy of a tool.
CHANGED_ELSEWHERE = "This step changes the body from another component, which is not copied."
NOT_FOLLOWED = "The body could not be followed through the timeline."
# The codes of the problems of a tool's place (`place_of`).
PLACE_UNREAD = "placeUnread"
PLACE_UNUSABLE = "placeUnusable"
# The reference type of a component's place, for the sizes that may move it (`words.NOUNS`), and what a Combine does
# with it, for `refs.mark_all`: "<Combine> puts its tool at the place of <component>".
PLACE = "Place"
PLACE_VERB = "puts its tool at"


def name_of(body):
    """The tool in plain words, with its component when it lives in another one."""
    name = (body or {}).get("name") or "a body"
    return "%s of %s" % (name, tool_items.component_name(body)) if tool_items.is_foreign_tool(body) else name


def owner_of(body, component=None):
    """The token of the component whose steps made `body`: the one a tool of another component names, else
    `component`, the component the walk is in (None or "" for the exported body's component)."""
    return tool_items.component_token(body) if tool_items.is_foreign_tool(body) else component or ""


def made_by(timeline, body, before, component=None):
    """The items before timeline index `before` that made or changed `body`, in the component that holds it.
    `component` is the token of the component the walk is in, None for the exported body's component."""
    owner = owner_of(body, component)
    found = tool_items.chain(timeline, body, before, owner)
    return found if owner else [item for item in found if not outside_component(item)]


def lineage_chain(timeline, body, before, component=None):
    """`(links, items)` for a tool body that a split made: the splits it comes through (`lineage.of`) and the items
    that built it, those of the bodies it was split from up to each split included. Without such a split, no links
    and `made_by`. A tool of another component is not followed through splits."""
    links = [] if tool_items.is_foreign_tool(body) else lineage.of({"target": body, "items": [
        item for item in timeline if item.get("index", 0) < before]})
    found, start = {}, -1
    for at, parent in links:
        for item in made_by(timeline, parent, at + 1, component):
            if item["index"] > start:
                found[item["index"]] = item
        start = at
    for item in made_by(timeline, body, before, component):
        if item["index"] >= start:
            found[item["index"]] = item
    return links, [found[i] for i in sorted(found)]


def _keeps(item, body):
    """The item only holds `body` as a tool it keeps, so it does not change it."""
    data = item.get("data") or {}
    return bool(data.get("keep_tools")) and any(same_body(t, body) for t in data.get("tools") or [])


def _names_foreign_twin(item, body):
    """The item takes a body of another component with the name of `body`: names repeat between components."""
    return any(record.get("foreign") and record.get("name") == body.get("name")
               for record, _ in tool_items.source_records(item))


def unseen_change(timeline, body, before, component=None):
    """`(item, why)` for an item before `before` that `made_by` cannot see but that may have changed `body`: one of
    another component that lists it, or one that lists its name under another token after the body first appears.
    None when there is no such item."""
    owner = owner_of(body, component)
    chain = made_by(timeline, body, before, component)
    start = chain[0]["index"] if chain else before
    for item in timeline:
        if item["index"] >= before or item.get("suppressed") or step_kinds.skipped(item.get("type")):
            continue
        listed = item.get("bodies_after") or []
        elsewhere = item.get("component") and item["component"] != owner if owner else outside_component(item)
        if elsewhere:
            if body.get("token") and any(b.get("token") == body["token"] for b in listed) and not _keeps(item, body):
                return item, CHANGED_ELSEWHERE
        elif (item["index"] > start and any(renamed_target(b, body) for b in listed)
              and not _names_foreign_twin(item, body)):
            return item, NOT_FOLLOWED
    return None


@dataclass(frozen=True)
class Chain:
    """How a tool body is built, as a walk of the tool reads it.

    body: the tool's record. owner: the token of the component whose steps made it ("" for the exported body's
    component). links: the splits it comes through (`lineage.of`). items: the items that made it, in timeline order,
    each with what the reader measured on the body it built at that point (`roles.seen_on`). unseen: `(item, why)` of
    an item that may have changed the tool but is not among them (`unseen_change`), else None.
    """

    body: dict
    owner: str
    links: tuple
    items: tuple
    unseen: object

    @property
    def foreign(self):
        """The tool lives in another component, and its items were read in that component's coordinates."""
        return tool_items.is_foreign_tool(self.body)


def read(timeline, body, before, component=None, exported=False):
    """The `Chain` of `body` before timeline index `before`. `component`: the token of the component the walk that
    takes the tool is in, None for the exported body's component. `exported`: `body` is the exported body, whose
    measures are on the items already."""
    links, made = lineage_chain(timeline, body, before, component)
    items = tuple(roles.seen_on(item, lineage.at(links, body, item["index"])[0], exported) for item in made)
    return Chain(body, owner_of(body, component), tuple(links), items,
                 unseen_change(timeline, body, before, component))


def sketch_by_name_only(item):
    """True when an outline of the item names its sketch by name but not by token. In a tool of another component
    such a sketch cannot be told apart from a sketch of the part with the same name."""
    profiles = (item.get("data") or {}).get("profiles") if isinstance(item.get("data"), dict) else None
    return any(isinstance(p, dict) and p.get("sketch") and not p.get("sketch_token") for p in profiles or ())


# ---- where a tool of another component sits ----------------------------------------------------------------------

@dataclass(frozen=True)
class Place:
    """Where a tool body of another component sits, relative to the exported body's component, at the Combine.

    move: the `geometry.rigid.Move` that carries the tool's component coordinates into those of the exported body's
    component, or None with `problem`. problem: a `problem.Problem` (`PLACE_UNREAD`, `PLACE_UNUSABLE`, cause
    `otherComponent`) when the place cannot be used, else None. moves_with:
    the reference for the sizes that may move the tool's component (`refs.mark_all`: its `component`, type PLACE), or
    None for a tool of the root component, which has no place of its own. planes: the measured references of the
    component's origin planes (`xy`, `xz`, `yz`) that a size probe reads again, in that order where present.
    """

    move: object
    problem: object
    moves_with: object
    planes: tuple

    @property
    def stays(self):
        """The tool's coordinates are those of the exported body's component already."""
        return self.move is not None and self.move.is_identity


def _problem(code, name, why):
    words = "The place of %s in the assembly cannot be used. %s" % (name, why)
    return Place(None, Problem(code, words, gap_hints.OTHER_COMPONENT), None, ())


def place_of(body):
    """The `Place` of the tool `body` of another component, from its `place` record (the component's `frame` in the
    root's coordinates and the exported body's own `target_frame`, read with the marker at the Combine)."""
    name = tool_items.component_name(body)
    found = body.get("place")
    if not isinstance(found, dict) or "frame" not in found:
        why = found.get("error") if isinstance(found, dict) else None
        return _problem(PLACE_UNREAD, name, why or "It was not read.")
    if found.get("target_error"):
        return _problem(PLACE_UNREAD, "the exported body", found["target_error"])
    problem = rigid.frame_problem(found["frame"])
    if problem:
        return _problem(PLACE_UNUSABLE, name, problem)
    move = rigid.move_from_frame(found["frame"])
    if found.get("target_frame") is not None:
        problem = rigid.frame_problem(found["target_frame"])
        if problem:
            return _problem(PLACE_UNUSABLE, "the exported body", problem)
        move = move.then(rigid.move_from_frame(found["target_frame"]).inverse())
    root = found.get("source") == "root"
    planes = tuple(found[slot]["ref"] for slot in ("xy", "xz", "yz")
                   if isinstance(found.get(slot), dict) and isinstance(found[slot].get("ref"), dict))
    moves_with = None if root else {"component": body.get("component"), "type": PLACE}
    return Place(move, None, moves_with, () if root else planes)


def is_place_slot(slot):
    """True for the slot of an origin plane of a tool component's place (`tool<number>.<plane>`, the `planes` of
    `Place`): the reference stands for where the tool sits, not for geometry a step uses."""
    head = str(slot or "").split(".")[0]
    return head.startswith("tool") and head[4:].isdigit()


def component_frame(capture, bodies=()):
    """The place of the component a walk builds in (component to assembly frame), or None when it has none on record.
    `bodies` are the tool bodies the walk is inside, outermost first; the walk of the exported body has none. The
    innermost tool of another component gives its component's frame; a tool of the same component as the walk that
    holds it has that walk's place, and without such a tool the exported body's component place counts."""
    for body in reversed(list(bodies)):
        if tool_items.is_foreign_tool(body):
            return (body.get("place") or {}).get("frame")
    return ((capture.get("target") or {}).get("placement") or {}).get("frame")
