"""Patterns and mirrors of bodies, and the handlers of every pattern and mirror item.

A pattern of features goes to the `repeat` package. A pattern of bodies makes new bodies. Which body is which copy, and
whether a Combine takes a whole pattern, are facts of the shared layer (`design_model/steps/body_pattern.py`).

In the walk of one body, a pattern that has the body among its sources leaves it as it is. A body that is a copy is
written like a pasted body: the steps of its source, then a `move` for its element. Those numbers cannot follow the
layout, so the sizes behind it are marked.

A Combine that takes a whole pattern (`body_pattern.groups`) is written better (`groups`, `write`): the sources become tool steps and the
pattern one `pattern` or `mirror` step that repeats them, so the layout can follow sizes. A source that is the Combine's
own target is repeated by its steps when they only add material; otherwise its steps are gathered into one tool first.
A subset of the copies, or a layout the `repeat` package refuses, falls back to one tool per copy.

A Combine holds a fixed list of bodies, and it is not known whether Fusion adds new copies to it when a count changes,
so the sizes a count reads are marked. Spacing and angle only move the same copies, so they follow without a mark.
"""
from dataclasses import dataclass

from ...capture_model.step_kinds import SOLID, recipe_kind
from ...geometry import vec
from ...design_model import design, tool_chains
from ...design_model.problem import is_problem
from ...design_model import words as shared
from ...results.verdicts import TRANSLATED
from ...design_model.steps import body_pattern
from .. import ref_motion, repeat, values, walk
from ..bodies import move, paste
from ..combine import tool_walk
from ..faces.moved_placer import MoveMaker
from ..faces.slabs import Motion
from ..faces.tool_placer import ToolMaker, WrittenFor, wrap_body
from ..result import Refusal, StepResult, make_verdict
from ..step_walk import nesting, tool_refusal

GRID_PATHS = ("quantity_one", "quantity_two", "distance_one", "distance_two")
TURN_PATHS = ("quantity", "total_angle_deg")
COUNT_PATHS = ("quantity_one", "quantity_two", "quantity")


@dataclass
class Copy:
    """One body a pattern made: `result`, the `source` it copies and the `motion` that carries the source to it."""

    result: dict
    source: dict
    motion: Motion


def match(data):
    """A `Copy` for each body the pattern made, or None when the bodies and the copies do not pair up
    (`body_pattern.match`)."""
    found = body_pattern.match(data)
    if found is None:
        return None
    return [Copy(c.result, c.source, Motion(c.move.rows, c.move.offset)) for c in found]


# ---------------------------------------------------------------- one body at a time


def _mark_layout(item, data, ctx, paths):
    """The copy's place is written as numbers: every size behind the layout is marked. `data` is the data of the
    pattern `item`."""
    name = item.get("name") or "A pattern"
    why = "each copy of %s is written on its own, so it cannot follow this" % name
    for path in paths:
        values.pin(ctx, item, path, why)
    axis = data.get("axis")
    if isinstance(axis, dict) and "point" in axis and vec.length(axis.get("dir") or [0.0]) > 0:
        shifts = repeat.axis_shift(ctx, item, axis, vec.unit(axis["dir"]))
        ctx.doubt(tuple(dict.fromkeys(r for q in shifts for r in q.reads)), why)
    for which in ("one", "two"):
        found = data.get("direction_%s_place" % which)
        if isinstance(found, dict) and found.get("assembly"):
            ref_motion.check_direction(ctx, item, found, "spreads copies along")
        else:
            ref_motion.check_own_direction(ctx, item, which, "spreads copies along")


def _in_walk(ctx, step, paths):
    """The pattern of the resolved step `step` as the walk of one body sees it."""
    item, data = step.brought, step.brought_data
    if any(ctx.is_target(source) for source in data.get("source_bodies") or ()):
        return StepResult()
    copies = match(data)
    found = next((c for c in copies or () if ctx.is_target(c.result)), None)
    if found is None:
        return Refusal("The copies of this pattern could not be matched to the bodies it made.")
    if ctx.steps:
        return Refusal("This pattern lands on a body that already has steps, which is not copied yet.")
    if body_pattern.is_mirror(data):
        return Refusal("A mirrored body is only copied when a Combine takes it together with its source.")
    tool = paste.rebuild(ctx, item, found.source)
    if isinstance(tool, Refusal):
        return tool
    with tool.ctx.recording() as marked:
        _mark_layout(item, data, tool.ctx, paths)
    out = paste.written_again(tool)
    out.join(marked)
    out.add(move.written(found.motion), [MoveMaker(found.motion)])
    return out


def rectangular(ctx, step):
    return _in_walk(ctx, step, GRID_PATHS) if body_pattern.of_bodies(step.brought_data) else repeat.rectangular(ctx, step)


def circular(ctx, step):
    return _in_walk(ctx, step, TURN_PATHS) if body_pattern.of_bodies(step.brought_data) else repeat.circular(ctx, step)


def path(ctx, step):
    """A path pattern; one of bodies is refused by the pattern it is written as."""
    return repeat.path(ctx, step)


def mirror(ctx, step):
    if body_pattern.of_bodies(step.brought_data) and not step.brought_data.get("combine"):
        return _in_walk(ctx, step, ())
    return repeat.mirror(ctx, step)


# ---------------------------------------------------------------- a whole pattern in a Combine


def groups(ctx, combine_item, tools, combine):
    """The `body_pattern.Group`s of the patterns this Combine takes whole. An intersect cannot be repeated. A source
    that is the Combine's own target is repeated by its steps, so the Combine must join, and no step may have been
    written for the target since the pattern."""
    if combine == "intersect":
        return []
    out = []
    for pattern, group in body_pattern.groups(ctx.timeline, combine_item, tools, ctx.component, ctx.is_target):
        if is_problem(group):
            continue
        if any(ctx.is_target(source) for source in group.sources) and (
                combine != "add" or ctx.wrote_after(pattern["index"])):
            continue
        if not body_pattern.overlaps(group, out, tools):
            out.append(group)
    return out


def _adds_solid(ctx, step):
    return (recipe_kind(step["kind"]).repeat == SOLID and step.get("combine") in ("new", "add")
            and step["id"] not in ctx.not_repeatable)


def _own_steps(ctx, out, item):
    """The ids to repeat for the walk's own body, or a Refusal. Steps that only add can be repeated one by one;
    anything else must be finished first, so the steps so far are gathered into one tool. So is a body with a step
    left out (a gap): a step added there later is then repeated with the rest. Gathering puts the steps one tool level
    deeper, which must stay within the nesting the recipe allows."""
    if (not ctx.gaps and len(ctx.steps) <= repeat.MAX_REFERENCES
            and all(_adds_solid(ctx, step) for step in ctx.steps)):
        return [step["id"] for step in ctx.steps]
    refused = tool_refusal(ctx.steps)
    if refused:
        return refused
    if ctx.depth + 1 + nesting(ctx.steps) > tool_walk.MAX_DEPTH:
        return Refusal("The body %s is built from tools nested too deep to copy." % tool_chains.name_of(ctx.target))
    step_id = "%sbody_%s" % (ctx.id_prefix, item["index"])
    out.wraps_body = wrap_body(step_id, ctx.target.get("name"))
    return [step_id]


def _repeater(data):
    if body_pattern.is_mirror(data):
        return repeat.mirror
    return repeat.circular if "axis" in data else repeat.rectangular


def _mark_counts(ctx, item):
    """The recipe repeats the tools for any count, and Fusion may keep the Combine's list as it is."""
    why = shared.BODY_COPIES_COUNT % (item.get("name") or "A pattern")
    for path in COUNT_PATHS:
        values.pin(ctx, item, path, why)


def write(ctx, combine_item, group, combine, number):
    """A `StepResult` with the sources of `group` and the step that repeats them; None when the layout cannot be
    written as a pattern; a Refusal when a source cannot be copied."""
    out, walked, ids = StepResult(), [], []
    for place, source in enumerate(group.sources):
        if ctx.is_target(source):
            own = _own_steps(ctx, out, combine_item)
            if isinstance(own, Refusal):
                return own
            ids.extend(own)
            continue
        tool = tool_walk.build(ctx, source, group.item["index"], ctx.depth + 1,
                               "%s_%d_%d" % (combine_item["index"], number, place))
        if isinstance(tool, Refusal):
            return tool
        refused = tool_refusal(tool.steps) or tool_walk.unfinished(tool)
        if refused:
            return refused
        step_id = tool.ctx.id_prefix + "tool"
        out.add({"kind": "toolBody", "combine": combine, "features": tool.steps}, [ToolMaker(tool.ctx)],
                label=source.get("name"), step_id=step_id)
        ids.append(step_id)
        walked.append(tool)
    if len(ids) > repeat.MAX_REFERENCES:
        return None
    # A plane or axis can lie on a source, so it is followed in the source's own walk when there is one.
    where = walked[0].ctx if walked else ctx
    with ctx.recording() as recorded:
        walk.fix_construction(where, group.item)
        read = design.as_read(group.item)
        copies = _repeater(read.brought_data)(where, read, (ids, []))
        if not isinstance(copies, Refusal):
            _mark_counts(ctx, group.item)
    if isinstance(copies, Refusal):
        return None
    for entry in copies.entries:
        entry.placers.append(WrittenFor(group.item["index"]))
        entry.label = group.item.get("name")
    out.extend(copies.entries)
    for tool in walked:
        tool.hand_over(out)
    out.join(recorded)
    out.items.append(group.item)
    out.tool_steps.append(make_verdict(group.item, TRANSLATED))
    return out
