"""Combine feature handler (CombineFeature).

A tool body that Fusion builds on its own and then joins, cuts or intersects with the exported body is written at the
Combine's place. Each tool is walked on its own (`tool_walk.build`).

Steps that only add material to the tool (a first step that makes the body and later steps that join to it) are written
one after the other with the Combine's operation, which gives what the Combine gives: cutting A and then B removes the
union of A and B, and joining them adds it. An intersect keeps only the shared part of the tool, so this holds for one
tool of one step. Such recipes open in older versions of the app.

Any other tool (with a cut, a round, a hole, a shell, a Move, a Paste or a Combine of its own) becomes one `toolBody`
step that holds the tool's steps. A pattern of bodies the Combine takes whole becomes a tool per source and one step
that repeats them (`body_copies.py`). A tool whose walk leaves a step out (a gap) is always a `toolBody` step. A tool
that cannot be built refuses the Combine, and the reason names the step that stops it. A tool the Combine keeps can be
used again by a later Combine.

Fusion's help does not say what an intersect of several tools keeps, so the export measures it (`intersect_model`):
what every tool holds is one `toolBody` per tool, what any tool holds is one `toolBody` that holds the tools. When the
measures cannot tell the two apart, the sizes the tools read are marked.

A tool body made in another component (`foreign`) is handled the same way. Its steps were read in that component's
frame (`helper_of` items); the Combine carries them into the exported body's frame with the tool's place in the
assembly (`tool_move`) before it writes them. The place follows the sizes that move the tool's component, or marks
them.
"""
import copy

from . import body_copies, place, ref_motion, step_kinds, tool_items, tool_walk
from .combine_volume import exceeds, exceeds_tools, rule_unproven
from .moved_placer import MovedMaker, motion_of
from .result import Refusal, StepResult
from .tool_placer import ToolMaker
from .values import Quantity, reads_in
from .walk import copies_bodies, is_foreign


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


def tool_key(body):
    """What tells tool bodies apart: the token, else the name (with the component when it lives in another one, since
    names repeat between components)."""
    if body.get("token"):
        return body["token"]
    component = tool_items.component_token(body) if tool_items.is_foreign_tool(body) else None
    name = body.get("name")
    return "%s/%s" % (component, name) if component and name else name


def _uses_face(item):
    """True when a step starts from or reaches to a face, or takes a flat face as its outline."""
    data = item.get("data") or {}
    kinds = ((data.get("start") or {}).get("kind"), (data.get("side_one") or {}).get("kind"),
             (data.get("side_two") or {}).get("kind"))
    drawn_on_face = any(isinstance(p, dict) and p.get("face") for p in data.get("profiles") or [])
    return "fromEntity" in kinds or "toEntity" in kinds or drawn_on_face


def _writes_flat(tool):
    """True when the steps of a walked tool can be written one by one onto the part. A tool with a step left out
    (a gap) is not: the missing step belongs in the tool's own list."""
    if tool.gaps:
        return False
    joining = False
    for item in tool.chain:
        data = item.get("data") or {}
        if (data.get("tools") or len(item.get("bodies_after") or []) != 1 or is_foreign(data) or copies_bodies(item)
                or not adds_only(tool.entries_of(item), joining)):
            return False
        joining = True
    reaches = any(_uses_face(item) for item in tool.chain)
    # A step written onto the part is worked out in the part's frame, which is not the frame of another component,
    # and against the part alone, which does not hold the faces of the tool's earlier steps.
    return not (reaches and (len(tool.entries) > 1 or tool_items.is_foreign_tool(tool.body)))


def _unusable(ctx, body):
    """A Refusal when the tool `body` cannot be taken by this Combine, else None."""
    if body.get("foreign") and not (tool_items.is_foreign_tool(body) and isinstance(body.get("place"), dict)):
        return Refusal("The tool body of %s is in another component, which is not copied yet."
                       % (body.get("name") or "a body"))
    if tool_items.is_foreign_tool(body) and ctx.component is not None:
        return Refusal("The tool body %s is taken by a Combine inside a tool body of another component, which is not "
                       "copied yet." % tool_walk.name_of(body))
    if tool_key(body) in ctx.used_tools:
        return Refusal("The tool body %s was used up by an earlier combine." % tool_walk.name_of(body))
    return None


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


def _flat(ctx, found, combine):
    """The steps of every tool, written one by one with the Combine's operation, or a Refusal."""
    out = StepResult()
    for tool, (move, shift) in found:
        held = tool_walk.on_part(ctx, tool)
        if isinstance(held, Refusal):
            return held
        for entry in held.entries:
            placed = copy.deepcopy(entry.step)
            placers = entry.placers
            if move is not None:
                placed = place.place({"features": [placed]}, move, shift)["features"][0]
                placers = [MovedMaker(entry.placers, motion_of(move, shift))]
            placed["combine"] = combine
            out.add(placed, placers, entry.picks, entry.repeatable)
        out.join(held)
    return out


def _tool_steps(found, combine):
    """One step per tool that holds the tool's own steps."""
    out = StepResult()
    for tool, (move, shift) in found:
        step = {"kind": "toolBody", "combine": combine, "features": tool.steps}
        if move is not None:
            step = place.place({"features": [step]}, move, shift)["features"][0]
        out.add(step, [ToolMaker(tool.ctx, motion_of(move, shift) if move is not None else None)],
                label=tool.body.get("name"))
        tool.hand_over(out)
    return out


def _union_tool(ctx, item, found):
    """One intersecting step that holds the tools: the part keeps what any of them holds."""
    inner = _tool_steps(found, "add")
    inner.steps[0]["combine"] = "new"
    held = ctx.child({"name": item.get("name")}, "%st%s_any_" % (ctx.id_prefix, item["index"]), depth=ctx.depth + 1)
    held.add_steps(item, inner)
    out = StepResult()
    out.add({"kind": "toolBody", "combine": "intersect", "features": held.steps}, [ToolMaker(held)])
    out.join(inner)
    return out


def _whole_patterns(ctx, item, tools, combine):
    """`(results, tools left)`: the steps of each pattern this Combine takes whole, and the tools still to walk; or a
    Refusal."""
    results, left = [], list(tools)
    for number, group in enumerate(body_copies.groups(ctx, item, tools, combine)):
        written = body_copies.write(ctx, item, group, combine, number)
        if isinstance(written, Refusal):
            return written
        if written is not None:
            results.append(written)
            left = [tool for tool in left if not group.holds(tool)]
    return results, left


def handle(item, ctx):
    data = item.get("data") or {}
    combine = COMBINE.get(data.get("operation"))
    if combine is None:
        return Refusal("This combine works in a way that is not copied yet.")
    tools = data.get("tools") or []
    if not ctx.is_target(data.get("target")):
        if data.get("keep_tools") and item.get("target_changed") is not True and any(ctx.is_target(t) for t in tools):
            return StepResult()  # This body is only a tool here, and the Combine keeps it as it is.
        return Refusal("This combine changes a body other than the exported one.")
    if not tools:
        return Refusal("This combine has no tool bodies.")
    # Fusion may list one tool body twice; taking it once gives the same shape.
    tools = list({tool_key(body): body for body in tools}.values())
    data = dict(data, tools=tools)
    model = data.get("intersect_model")
    if combine == "intersect" and len(tools) > 1 and model not in ("every", "any"):
        return Refusal("This combine keeps a shared part that the copy could not work out.")
    out = write_tools(ctx, item, data, combine)
    if isinstance(out, Refusal):
        return out
    if data.get("keep_tools"):
        ctx.note("Fusion kept the tool bodies next to the part. Only the part is copied.")
    else:
        ctx.used_tools.update(tool_key(body) for body in tools)
    return out


def write_tools(ctx, item, data, combine):
    """The steps that join, cut or intersect (`combine`: add, cut, intersect) the tool bodies `data.tools` with the
    body the walk builds, at the place of `item`; or a Refusal. `data` holds the measures the checks read
    (`volume_before`, `volume_after`, the tools' `volume`, `intersect_model`, `intersect_volumes`)."""
    tools = data["tools"]
    model = data.get("intersect_model")
    for body in tools:
        problem = _unusable(ctx, body)
        if problem is not None:
            return problem

    patterns = _whole_patterns(ctx, item, tools, combine)
    if isinstance(patterns, Refusal):
        return patterns
    patterns, left = patterns
    # Tools kept where any of them reaches sit inside one more tool step (`_union_tool`), so they are a level deeper.
    union = combine == "intersect" and model == "any" and len(left) > 1
    found = []
    for number, body in enumerate(left):
        tool = tool_walk.build(ctx, body, item["index"], ctx.depth + (2 if union else 1), number)
        if isinstance(tool, Refusal):
            return tool
        moved = tool_move(ctx, item, body) if tool_items.is_foreign_tool(body) else (None, None)
        if isinstance(moved, Refusal):
            return moved
        found.append((tool, moved))

    flat = not patterns and all(_writes_flat(tool) for tool, _ in found) and (
        combine != "intersect" or (len(found) == 1 and len(found[0][0].entries) == 1))
    if flat and combine != "intersect" and exceeds(data, [other for tool, _ in found for other in tool.chain]):
        return Refusal("This combine changes the part by more than the steps of its tool body fill, so the tool "
                       "cannot be copied exactly.")
    if not flat and exceeds_tools(combine, data):
        return Refusal("This combine changes the part by more than its tool bodies hold, so the tools cannot be "
                       "copied exactly.")
    if flat:
        out = _flat(ctx, found, combine)
    elif union:
        out = _union_tool(ctx, item, found)
    else:
        out = _tool_steps(found, combine)
    if isinstance(out, Refusal):
        return out
    if combine == "intersect" and len(tools) > 1 and rule_unproven(data.get("intersect_volumes")):
        ctx.doubt(reads_in(out.steps), "%s keeps the same shape under both rules for several tools at these sizes, and "
                  "at other sizes the rules can differ" % (item.get("name") or "This combine"))
    for written in patterns:
        out.extend(written.entries)
        out.join(written)
        out.wraps_body = out.wraps_body or written.wraps_body
    return out
