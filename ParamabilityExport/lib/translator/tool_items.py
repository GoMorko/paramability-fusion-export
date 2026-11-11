"""Which timeline items build the tool bodies of the exported body's Combines. Pure: capture dicts only.

A Combine of the exported body takes tool bodies, from its own component or another. To copy a tool, the steps that
made it are needed, and so are the steps behind it: the bodies a Paste or a body pattern copies (`sources`,
`source_bodies`) and the tools of a Combine that changed the tool. The reader records every such body with its
component (`foreign`, `component`) and reads the steps that made it: `body_states` for all of them, and the feature
data too for steps of another component (`helper_of`). The same rules (`makers`, `built_by`) pick those items for the
reader, for the translator's patterns of a Combine (`repeat.py`) and for the reach read (`read_gap_reach.py`).

`plan` is a pure function of the items read so far. The reader calls it again after each round of reading, since the
steps it reads name more source bodies. A body held by several items (a kept tool used again, a source pasted later)
is followed up to the latest of them, so steps added between those items are read too.
"""
from dataclasses import dataclass, field

from . import step_kinds
from .capture import same_body

MAX_TOOLS = 32
MAX_ITEMS = 120
MAX_DEPTH = 3
TOO_MANY = "the export reads at most %d steps of tool bodies" % MAX_ITEMS
TOO_MANY_TOOLS = "the export reads at most %d tool bodies" % MAX_TOOLS
TOO_DEEP = "the export follows tool bodies at most %d levels deep" % MAX_DEPTH


def component_token(tool):
    return ((tool or {}).get("component") or {}).get("token") or ""


def component_name(tool):
    return ((tool or {}).get("component") or {}).get("name") or "another component"


def is_foreign_tool(tool):
    """A tool body of another component that names its component, so the steps that made it can be found."""
    return isinstance(tool, dict) and tool.get("foreign") is True and bool(component_token(tool))


def _readable(item):
    data = item.get("data")
    return isinstance(data, dict) and "read_error" not in data


def source_records(item):
    """`[(record, number)]`: the body records a read item takes its result from. A Combine lists its tools, a Paste
    its source body, a body pattern or mirror the bodies it copies. A pattern of features lists timeline indices
    where the others list bodies; those are not records."""
    if item.get("suppressed") or not _readable(item):
        return []
    found = []
    for key in ("tools", "sources", "source_bodies"):
        records = item["data"].get(key)
        if isinstance(records, list):
            found.extend((r, n) for n, r in enumerate(records) if isinstance(r, dict))
    return found


def combine_tools(items, target=None):
    """`(combine item, tool record, number)` for each tool body of a Combine of the exported body's component, in
    timeline order. With `target` (a body ref), only Combines that change that body count."""
    out = []
    for item in items:
        data = item.get("data")
        if item.get("suppressed") or item.get("in_target_component") is False or not isinstance(data, dict):
            continue
        tools = data.get("tools")
        if not isinstance(tools, list) or (target is not None and not same_body(data.get("target"), target)):
            continue
        out.extend((item, tool, n) for n, tool in enumerate(tools) if isinstance(tool, dict))
    return out


def chain(items, tool, before, owner=None):
    """The items before timeline index `before` that made or changed the body `tool`: not suppressed, modeling steps
    of the body's component whose bodies include it. Sketches and construction geometry are left out. `owner` is the
    token of the component to look in; without it, the component the body names."""
    owner = component_token(tool) if owner is None else owner
    found = []
    for item in items:
        if item["index"] >= before or item.get("suppressed") or step_kinds.skipped(item.get("type")):
            continue
        if owner and item.get("component") and item["component"] != owner:
            continue
        if any(same_body(b, tool) for b in item.get("bodies_after") or []):
            found.append(item)
    return found


def _is_copy(item, body):
    """The item made `body` as a copy of another body (a Paste, a body pattern, a mirror of bodies)."""
    results = item["data"].get("result_bodies") if _readable(item) else None
    return isinstance(results, list) and any(same_body(r, body) for r in results if isinstance(r, dict))


@dataclass
class Source:
    """A body record to follow: the `anchor` item holds it (the Combine of a tool, the Paste of a source) and `number`
    is its place in that item's list. `depth` counts the links from a tool of the exported body's Combines."""

    record: dict
    anchor: dict
    number: int
    depth: int


@dataclass
class Plan:
    """What to read for the tool bodies.

    sources: the body records to follow. The place of one that lives in another component is read with the marker
      just before its anchor item.
    wanted: `(item, [body records])` in the order the items were found: each item to read, with the bodies it serves.
      One item serves several bodies when a pattern makes copies of one body.
    left: `(item, reason)` of items past a limit, in timeline order.
    refused: `(record, reason)` of body records past a limit; none of their steps are read.
    """

    sources: list = field(default_factory=list)
    wanted: list = field(default_factory=list)
    left: list = field(default_factory=list)
    refused: list = field(default_factory=list)


def makers(items, record, anchor):
    """The items before the `anchor` item (the Combine, Paste or pattern that holds `record`) that made or changed the
    body `record`, in the component whose steps made it: the one a foreign record names, else the anchor's. When that
    component cannot be read and the anchor sits in the exported body's component, items of other components do not
    count."""
    owner = component_token(record) if is_foreign_tool(record) else anchor.get("component") or ""
    found = chain(items, record, anchor["index"], owner)
    if owner or anchor.get("in_target_component") is False:
        return found
    return [item for item in found if item.get("in_target_component") is not False]


def built_by(items, record, anchor, max_depth=MAX_DEPTH):
    """Timeline indexes of every item that built the body `record` before `anchor`: its `makers`, and the makers of
    the bodies those items take (a Combine's tools, a Paste's sources, a pattern's source bodies), `max_depth` bodies
    deep at most."""
    reached = {}  # item index -> the shallowest depth it was reached at

    def follow(body, holder, depth):
        for item in makers(items, body, holder):
            if reached.get(item["index"], max_depth + 1) <= depth:
                continue
            reached[item["index"]] = depth
            if depth < max_depth:
                for child, _ in source_records(item):
                    follow(child, item, depth + 1)

    follow(record, anchor, 1)
    return set(reached)


def plan(items, target=None, max_items=MAX_ITEMS, max_tools=MAX_TOOLS, max_depth=MAX_DEPTH):
    """The `Plan` for the tool bodies of `items`. `target` is the exported body's ref: it is never followed, its
    steps are read already.

    Bodies are followed breadth first from the tools of the Combines. Copies made by a Paste or a body pattern do not
    count against `max_tools`, since their steps are those of their source: the limit counts distinct source bodies.
    Bodies past `max_tools`, deeper than `max_depth`, and items past `max_items` give no step to read."""
    result = Plan()
    queue = [(tool, combine, n, 1) for combine, tool, n in combine_tools(items, target)]
    if target is not None:
        # An exported body that is itself a copy is built from the steps of its source.
        queue += [(source, item, n, 1) for item in items if _readable(item) and _is_copy(item, target)
                  for source, n in source_records(item)]
    visited, built, found, why = [], 0, {}, {}  # visited: (record, indices of the items that serve it)
    while queue:
        record, anchor, number, depth = queue.pop(0)
        if target is not None and same_body(record, target):
            continue
        steps = makers(items, record, anchor)
        served = next((indices for other, indices in visited if same_body(record, other)), None)
        if served is None:
            if depth > max_depth:
                why.update((item["index"], TOO_DEEP) for item in steps)
                continue
            copy = any(_is_copy(item, record) for item in steps)
            if not copy and built >= max_tools:
                result.refused.append((record, TOO_MANY_TOOLS))
                why.update((item["index"], TOO_MANY_TOOLS) for item in steps)
                continue
            built += 0 if copy else 1
            served = set()
            visited.append((record, served))
        for item in steps if depth <= max_depth else ():
            if item["index"] not in served:
                served.add(item["index"])
                found.setdefault(item["index"], (item, []))[1].append(record)
                queue.extend((child, item, n, depth + 1) for child, n in source_records(item))
        result.sources.append(Source(record, anchor, number, depth))
    kept = list(found)[:max_items]
    left = {index: reason for index, reason in why.items() if index not in kept}
    left.update((index, TOO_MANY) for index in found if index not in kept)
    by_index = {item["index"]: item for item in items}
    result.wanted = [found[index] for index in kept]
    result.left = [(by_index[index], reason) for index, reason in sorted(left.items())]
    return result
