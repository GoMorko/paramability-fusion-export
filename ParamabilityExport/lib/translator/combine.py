"""Combine feature handler (CombineFeature).

A tool body that Fusion builds on its own and then joins, cuts or intersects with the exported body is written at
the Combine's place. The walk keeps the steps of every other body in `ctx.pending_tools`, but only while they add
material to it (`adds_only`): a first step that makes the body and later steps that join to it. Written one after the
other with the Combine's operation, such steps give what the Combine gives: cutting A and then B removes the union of
A and B, and joining them adds it. A tool body with any other history (a cut, a round, a hole, a shell, a step that
cannot be copied) cannot be replayed, so the Combine refuses and names it.

An intersect keeps only the shared part of the tool, which is not a sequence of intersects with its steps, so it
takes a tool of one step. A tool the Combine keeps stays pending, so a later Combine can use it again.

A tool body made in another component (`foreign`) is handled the same way. Its steps were read in that component's
frame (`helper_of` items) and wait in `ctx.pending_tools`; the Combine carries them into the exported body's frame
with the tool's place in the assembly (`tool_move`) before it writes them. The place follows the sizes that move the
tool's component, or marks them.
"""
import copy

from . import place, ref_motion, step_kinds, tool_items
from .capture import outside_component, same_body
from .combine_volume import exceeds
from .moved_placer import MovedMaker
from .result import Refusal, StepResult
from .values import Quantity
from .words import type_words


COMBINE = {"join": "add", "cut": "cut", "intersect": "intersect"}
# How the place of a tool's component is worded in a reason: "<step> puts its tool at the place of <component> ...".
PLACE = "Place"
WHAT = "puts its tool at"


def _vector(value):
    return isinstance(value, (list, tuple)) and len(value) == 3 and all(
        isinstance(v, (int, float)) and not isinstance(v, bool) for v in value)


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


def pending_key(body, component=None):
    """The key a body's steps wait under in `ctx.pending_tools`: its token, else its name (with the token of its
    component when it lives in another one, since names repeat between components)."""
    if body.get("token"):
        return body["token"]
    name = body.get("name")
    return "%s/%s" % (component, name) if component and name else name


def _pending_for(ctx, body):
    component = tool_items.component_token(body) if tool_items.is_foreign_tool(body) else None
    for key in (body.get("token"), pending_key(body, component), body.get("name")):
        if key and key in ctx.pending_tools:
            return key
    return None


def _touches(item, body):
    return any(same_body(b, body) for b in item.get("bodies_after") or [])


def _items_on(ctx, body, before):
    """Timeline items before `before` that built or changed `body`. For a tool of another component, those of that
    component."""
    if tool_items.is_foreign_tool(body):
        return tool_items.chain(ctx.capture["items"], body, before)
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
    if tool_items.is_foreign_tool(body):
        name = "%s of %s" % (name, tool_items.component_name(body))
    key = _pending_for(ctx, body)
    held = ctx.pending_tools.get(key) if key else None
    made = {other["index"] for other in held.items} if held else set()
    for other in _items_on(ctx, body, item["index"]):
        if other["index"] not in made:
            reason = ctx.tool_refusals.get(other["index"]) or other.get("helper_unread")
            return Refusal("The tool body %s has %s. A tool is copied only when every step on it adds material."
                           % (name, _what(other, reason)))
    if held is None:
        return Refusal("The tool body %s is built in a way that cannot be copied." % name)
    if len(held.entries) > 1 and any(_reaches_face(other) for other in held.items):
        return Refusal("The tool body %s has a step that starts from or reaches to a face, and a tool of more than "
                       "one step cannot tell its faces apart." % name)
    return key, held


def _frame_refusal(name, problem):
    return Refusal("The place of %s in the assembly cannot be used. %s" % (name, problem))


def tool_move(ctx, item, tool):
    """`(Move, shift)` that carries the steps of a tool body of another component into the frame of the exported
    body's component, or a Refusal. The Move is the tool component's place read at the Combine, then the inverse of
    the exported body's own place at that time. `shift` is three Quantities: the move of the tool's component that
    sizes cause, from the measured origin planes of the component (zero at the current sizes), or None when it does
    not move. A size that moves it in a way the probe could not follow is marked, never kept fixed silently."""
    name = tool_items.component_name(tool)
    found = tool.get("place")
    if not isinstance(found, dict) or "frame" not in found:
        why = found.get("error") if isinstance(found, dict) else None
        return _frame_refusal(name, why or "It was not read.")
    if found.get("target_error"):
        return _frame_refusal("the exported body", found["target_error"])
    problem = place.frame_problem(found["frame"])
    if problem:
        return _frame_refusal(name, problem)
    move = place.move_from_frame(found["frame"])
    if found.get("target_frame") is not None:
        problem = place.frame_problem(found["target_frame"])
        if problem:
            return _frame_refusal("the exported body", problem)
        move = move.then(place.move_from_frame(found["target_frame"]).inverse())
    return move, _follow_place(ctx, item, tool, found)


def _follow_place(ctx, item, tool, found):
    """The sized move of a tool component along the normals of its origin planes, or None. Without usable
    references on a component that is not the root, the sizes that act on the component are marked."""
    if found.get("source") == "root":
        return None
    refs = [found[slot]["ref"] for slot in ("xy", "xz", "yz")
            if isinstance(found.get(slot), dict) and isinstance(found[slot].get("ref"), dict)]
    normals = [ref.get("normal") for ref in refs]
    if len(refs) < 3 or not all(_vector(n) for n in normals):
        ref_motion.mark_all(ctx, item, {"component": tool.get("component"), "type": PLACE}, WHAT)
        return None
    shift = [Quantity(0.0)] * 3
    for ref in refs:
        offset = ref_motion.moves(ctx, item, dict(ref, type=PLACE), ref_motion.PLANE, WHAT)[0]
        if offset.sized:
            shift = [shift[i].plus(offset.scaled(ref["normal"][i])) if abs(ref["normal"][i]) > 1e-9 else shift[i]
                     for i in range(3)]
    return shift if any(q.sized for q in shift) else None


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
        if body.get("foreign") and not (tool_items.is_foreign_tool(body) and isinstance(body.get("place"), dict)):
            return Refusal("The tool body of %s is in another component, which is not copied yet."
                           % (body.get("name") or "a body"))
        chain = _tool_chain(ctx, body, item)
        if isinstance(chain, Refusal):
            return chain
        moved = tool_move(ctx, item, body) if tool_items.is_foreign_tool(body) else (None, None)
        if isinstance(moved, Refusal):
            return moved
        found.append((chain[0], chain[1], moved))
    if len({key for key, _, _ in found}) != len(found):
        return Refusal("This combine lists the same tool body twice.")
    if combine == "intersect" and any(len(held.entries) > 1 for _, held, _ in found):
        return Refusal("A combine that keeps only the shared part is copied only for a tool of one step.")
    if combine != "intersect" and exceeds(data, [other for _, held, _ in found for other in held.items]):
        return Refusal("This combine changes the part by more than the steps of its tool body fill, so the tool "
                       "cannot be copied exactly.")

    out = StepResult()
    for key, held, (move, shift) in found:
        for entry in held.entries:
            placed = copy.deepcopy(entry.step)
            placers = entry.placers
            if move is not None:
                placed = place.place({"features": [placed]}, move, shift)["features"][0]
                placers = [MovedMaker(entry.placers, move)]
            placed["combine"] = combine
            out.add(placed, placers, entry.picks, entry.repeatable)
        out.join(held)
        if not data.get("keep_tools"):
            del ctx.pending_tools[key]
    if data.get("keep_tools"):
        ctx.note("Fusion kept the tool bodies next to the part. Only the part is copied.")
    return out
