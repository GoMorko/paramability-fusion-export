"""Combine feature handler (CombineFeature).

A tool body that Fusion builds on its own and then joins, cuts or intersects with the exported body is written at
the Combine's place: its one step (a new body extrude or revolve, held in `ctx.pending_tools` by the driver) takes
the Combine's operation. Any other history on the tool body cannot be replayed, so it refuses.
"""
import copy

from .capture import outside_component, same_body
from .result import Refusal

TYPES = ("CombineFeature",)

COMBINE = {"join": "add", "cut": "cut", "intersect": "intersect"}
TOOL_KINDS = ("extrude", "revolve")
NON_GEOMETRY = ("Sketch", "ConstructionPlane", "ConstructionAxis", "ConstructionPoint", "none")


def _pending_for(ctx, body):
    for key in (body.get("token"), body.get("name")):
        if key and key in ctx.pending_tools:
            return key
    return None


def _touches(item, body):
    return any(same_body(b, body) for b in item.get("bodies_after") or [])


def _items_on(ctx, body, before):
    """Timeline items before `before` that built or changed `body`."""
    return [
        other for other in ctx.capture["items"]
        if other["index"] < before and not other.get("suppressed") and not outside_component(other)
        and other.get("type") not in NON_GEOMETRY and _touches(other, body)
    ]


def _tool_step(ctx, body, item):
    """The one pending step that builds `body`, or None when the body has any other history."""
    key = _pending_for(ctx, body)
    if key is None:
        return None
    steps = ctx.pending_tools[key]
    if len(steps) != 1 or steps[0].get("kind") not in TOOL_KINDS or steps[0].get("combine") != "new":
        return None
    if len(_items_on(ctx, body, item["index"])) != 1:
        return None
    return key, steps[0]


def handle(item, ctx):
    data = item.get("data") or {}
    combine = COMBINE.get(data.get("operation"))
    if combine is None:
        return Refusal("This combine works in a way that is not copied yet.")
    if not ctx.is_target(data.get("target")):
        return Refusal("This combine changes a body other than the exported one.")
    tools = data.get("tools") or []
    if not tools:
        return Refusal("This combine has no tool bodies.")

    found = []
    for body in tools:
        if body.get("foreign"):
            return Refusal("The tool body of %s is in another component, which is not copied yet."
                           % (body.get("name") or "a body"))
        tool = _tool_step(ctx, body, item)
        if tool is None:
            name = body.get("name") or "a body"
            return Refusal("The tool body of %s is built in a way that cannot be copied." % name)
        found.append(tool)
    if len({key for key, _ in found}) != len(found):
        return Refusal("This combine lists the same tool body twice.")

    steps = []
    for key, step in found:
        placed = copy.deepcopy(step)
        placed["combine"] = combine
        steps.append(placed)
        del ctx.pending_tools[key]
    if data.get("keep_tools"):
        ctx.note("Fusion kept the tool bodies next to the part. Only the part is copied.")
    return steps
