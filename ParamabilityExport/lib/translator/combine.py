"""Combine feature handler (CombineFeature).

A tool body that Fusion builds on its own and then joins, cuts or intersects with the exported body is written at
the Combine's place. The walk keeps the steps of every other body in `ctx.pending_tools`, but only while they add
material to it (`adds_only`): a first step that makes the body and later steps that join to it. Written one after the
other with the Combine's operation, such steps give what the Combine gives: cutting A and then B removes the union of
A and B, and joining them adds it. A tool body with any other history (a cut, a round, a hole, a shell, a step that
cannot be copied) cannot be replayed, so the Combine refuses and names it.

An intersect keeps only the shared part of the tool, which is not a sequence of intersects with its steps, so it
takes a tool of one step. A tool the Combine keeps stays pending, so a later Combine can use it again.
"""
import copy

from . import step_kinds
from .capture import outside_component, same_body
from .combine_volume import exceeds
from .result import Refusal, StepResult
from .words import type_words


COMBINE = {"join": "add", "cut": "cut", "intersect": "intersect"}


def adds_only(entries, joining):
    """True when the steps only add material to a tool body. `joining` is True when the body already has steps, so
    the first of these must join it; otherwise the first makes the body and the rest join it."""
    for n, entry in enumerate(entries):
        step = entry.step
        if not step_kinds.recipe_kind(step.get("kind")).combine_tool:
            return False
        if step.get("combine") != ("add" if joining or n else "new"):
            return False
    return bool(entries)


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
        and not step_kinds.skipped(other.get("type")) and _touches(other, body)
    ]


def _what(item, refusal):
    """The item that stops the copy, in plain words: its name and what it is. `refusal` is the reason the walk gave
    when it could not copy the item as a step, or None."""
    operation = (item.get("data") or {}).get("operation")
    kind = operation if operation in ("cut", "intersect") else type_words(item.get("type") or "")
    found = "%s (%s)" % (item.get("name"), kind)
    return "%s, which cannot be copied: %s" % (found, refusal.rstrip(". ").lower()) if refusal else found


def _reaches_face(item):
    data = item.get("data") or {}
    kinds = ((data.get("start") or {}).get("kind"), (data.get("side_one") or {}).get("kind"),
             (data.get("side_two") or {}).get("kind"))
    return "fromEntity" in kinds or "toEntity" in kinds


def _tool_chain(ctx, body, item):
    """(key, StepResult) of the pending steps that build `body`, or a Refusal that says why they cannot be copied."""
    name = body.get("name") or "a body"
    key = _pending_for(ctx, body)
    held = ctx.pending_tools.get(key) if key else None
    made = {other["index"] for other in held.items} if held else set()
    for other in _items_on(ctx, body, item["index"]):
        if other["index"] not in made:
            return Refusal("The tool body %s has %s. A tool is copied only when every step on it adds material."
                           % (name, _what(other, ctx.tool_refusals.get(other["index"]))))
    if held is None:
        return Refusal("The tool body %s is built in a way that cannot be copied." % name)
    if len(held.entries) > 1 and any(_reaches_face(other) for other in held.items):
        return Refusal("The tool body %s has a step that starts from or reaches to a face, and a tool of more than "
                       "one step cannot tell its faces apart." % name)
    return key, held


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
        chain = _tool_chain(ctx, body, item)
        if isinstance(chain, Refusal):
            return chain
        found.append(chain)
    if len({key for key, _ in found}) != len(found):
        return Refusal("This combine lists the same tool body twice.")
    if combine == "intersect" and any(len(held.entries) > 1 for _, held in found):
        return Refusal("A combine that keeps only the shared part is copied only for a tool of one step.")
    if combine != "intersect" and exceeds(data, [other for _, held in found for other in held.items]):
        return Refusal("This combine changes the part by more than the steps of its tool body fill, so the tool "
                       "cannot be copied exactly.")

    out = StepResult()
    for key, held in found:
        for entry in held.entries:
            placed = copy.deepcopy(entry.step)
            placed["combine"] = combine
            out.add(placed, entry.placers, entry.picks, entry.repeatable)
        out.join(held)
        if not data.get("keep_tools"):
            del ctx.pending_tools[key]
    if data.get("keep_tools"):
        ctx.note("Fusion kept the tool bodies next to the part. Only the part is copied.")
    return out
