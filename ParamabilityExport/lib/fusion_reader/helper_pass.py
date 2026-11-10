"""The second reading pass: the steps of tool bodies that live in other components.

The main walk reads feature data only for items of the target's component. A Combine there can take a tool body made
in another component; `tool_place` records where that component sits, and this pass reads the items that made the
tool (`translator/tool_items.py` picks them) with the same feature readers, in the tool component's own frame: a
`ReadContext` whose target is the tool body, so the tool component's sketches, planes and faces are not foreign.
Only those items are rolled to and read, at most `tool_items.MAX_ITEMS`. Nothing here raises: a tool that cannot be
found gets `place.error`, an item that cannot be read keeps `read_error`, and items past the cap keep `helper_unread`.
The caller restores the timeline marker.
"""
from ..translator import tool_items
from . import read_geometry as geo
from .parameters import list_model_parameters
from .placement import find_occurrence, tool_place


def _tool_context(design, timeline, combine, tool):
    """`(ReadContext, body)` of the tool body with the marker just before its Combine, or `(None, reason)`."""
    timeline.markerPosition = combine["index"]
    body = geo.safe(lambda: geo.find_native(design, tool.get("token") or ""), None)
    if body is None:
        return None, "The tool body could not be found."
    ctx = geo.safe(lambda: geo.ReadContext(design, body), None)
    if ctx is None or ctx.component is None:
        return None, "The component of the tool body could not be read."
    return ctx, body


def _entity(timeline, native_entity, index):
    """The native entity of timeline item `index`, or None when it cannot be read."""
    return geo.safe(lambda: native_entity(timeline.item(index))[0], None)


def _read_start(entity, item, hctx, readers, component_bodies):
    item["helper_of"] = hctx.target_ref["token"]
    bodies = geo.safe(lambda: component_bodies(hctx), None)
    if bodies is not None:
        item["bodies_before"] = bodies
    before = (readers.get(item["type"]) or (None, None))[0]
    if before is None:
        return
    try:
        item["data"] = before(entity, hctx)
    except Exception as exc:
        item["data"] = {"read_error": str(exc) or type(exc).__name__}


def _read_finish(entity, item, hctx, readers):
    after = (readers.get(item["type"]) or (None, None))[1]
    if after is None or "read_error" in item["data"]:
        return
    try:
        item["data"].update(after(entity, hctx, item["data"]) or {})
    except Exception as exc:
        item["data"] = {"read_error": str(exc) or type(exc).__name__}


def read_helpers(design, ctx, timeline, items, readers, native_entity, component_bodies):
    """Read the tool bodies of other components that Combines of the target take. `items` maps a timeline index to its
    item dict (changed in place: `data`, `helper_of`, `bodies_before`, `helper_unread`); each foreign tool of a
    Combine gets `place` (`placement.tool_place`). Returns the components whose model parameters the size table needs
    (the tool components and those above them)."""
    ordered = [items[i] for i in sorted(items)]
    wanted, left = tool_items.plan(ordered)
    for item, _ in left:
        item["helper_unread"] = tool_items.TOO_MANY
    contexts, components = {}, []
    tools = tool_items.foreign_tools(ordered)[:tool_items.MAX_TOOLS]
    for combine, tool in tools:
        number = combine["data"]["tools"].index(tool)
        hctx, body = _tool_context(design, timeline, combine, tool)
        if hctx is None:
            tool["place"] = {"error": body}
            continue
        contexts[id(tool)] = hctx
        place = geo.safe(lambda: tool_place(ctx, hctx.component, tool.get("path") or "", number),
                         {"error": "The place of the tool's component could not be read."})
        tool["place"] = place
        components.append(hctx.component)
        components.extend(_above(ctx, hctx.component, tool.get("path") or ""))
    reading = {}
    for item, tool in wanted:
        if id(tool) in contexts and "error" not in (tool.get("place") or {}):
            reading[item["index"]] = (item, contexts[id(tool)])
        else:
            item["helper_unread"] = "the tool body or the place of its component could not be read"
    starts = set(reading)
    finishes = {i + 1 for i in reading}
    for position in sorted(starts | finishes):
        timeline.markerPosition = position
        if position - 1 in reading:
            item, hctx = reading[position - 1]
            entity = _entity(timeline, native_entity, position - 1)
            if entity is not None:
                _read_finish(entity, item, hctx, readers)
        if position in reading:
            item, hctx = reading[position]
            entity = _entity(timeline, native_entity, position)
            if entity is None:
                item["data"] = {"read_error": "The step could not be read."}
            else:
                _read_start(entity, item, hctx, readers, component_bodies)
    return components


def _above(ctx, component, path_name):
    """Components of the occurrences above the one that shows `component` (its parents out to the root's children)."""
    path = geo.safe(lambda: find_occurrence(ctx.root, component, path_name), None) or []
    return [c for c in (geo.safe(lambda: o.component, None) for o in path[1:]) if c is not None]


def model_parameters(components):
    """Model parameters of `components`, merged by name (the first wins)."""
    merged = {}
    for component in components:
        for parameter in geo.safe(lambda: list_model_parameters(component), []):
            merged.setdefault(parameter["name"], parameter)
    return list(merged.values())
