"""Patterns and mirrors of bodies, and the handlers of every pattern and mirror item.

A pattern of features goes to the `repeat` package. A pattern of bodies makes new bodies. `PatternElement` does not say which body
is which copy, so copies are matched by their points (`match`).

In the walk of one body, a pattern that has the body among its sources leaves it as it is. A body that is a copy is
written like a pasted body: the steps of its source, then a `move` for its element. Those numbers cannot follow the
layout, so the sizes behind it are marked.

A Combine that takes a whole pattern is written better (`groups`, `write`): the sources become tool steps and the
pattern one `pattern` or `mirror` step that repeats them, so the layout can follow sizes. A source that is the Combine's
own target is repeated by its steps when they only add material; otherwise its steps are gathered into one tool first.
A subset of the copies, or a layout the `repeat` package refuses, falls back to one tool per copy.

A Combine holds a fixed list of bodies, and it is not known whether Fusion adds new copies to it when a count changes,
so the sizes a count reads are marked. Spacing and angle only move the same copies, so they follow without a mark.
"""
from dataclasses import dataclass

from ...capture_model.capture import outside_component, same_body
from ...capture_model.step_kinds import SOLID, recipe_kind
from ...geometry import vec
from ...geometry.rigid import move_from_frame
from ...design_model import refs, roles, tool_chains
from ...results.verdicts import TRANSLATED
from ...design_model.steps.repeat import is_identity, kept_elements, mirror_plane
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


@dataclass
class Group:
    """A pattern item a Combine takes whole: its `sources` and its `copies`."""

    item: dict
    sources: list
    copies: list

    def holds(self, body):
        return any(same_body(body, other) for other in self.sources + [c.result for c in self.copies])


def _is_mirror(data):
    return "plane" in data


def _element_motions(data):
    """The `Motion` of each copy a pattern or mirror keeps, the original left out; None when they were not read."""
    if _is_mirror(data):
        plane = mirror_plane(data)
        return None if plane is None else [Motion.mirror(plane["origin"], plane["normal"])]
    kept = kept_elements(data)
    if kept is None:
        return None
    moves = [move_from_frame(e["frame"]) for e in kept if not is_identity(e["frame"])]
    return [Motion(found.rows, found.offset) for found in moves]


def _lands_on(motion, source, result):
    """True when `motion` puts every point of `source` on a point of `result`, in any order."""
    before, after = source.get("points") or [], result.get("points") or []
    return bool(before) and len(before) == len(after) and all(
        any(vec.close(motion.numbers(p), q, move.FIT_TOL_MM) for q in after) for p in before)


def match(data):
    """A `Copy` for each body the pattern made, or None when the bodies and the copies do not pair up."""
    sources, results = data.get("source_bodies"), data.get("result_bodies")
    motions = _element_motions(data)
    if not sources or not isinstance(results, list) or motions is None:
        return None
    left = [r for r in results if not any(same_body(r, s) for s in sources)]
    copies = []
    for source in sources:
        for motion in motions:
            found = next((r for r in left if _lands_on(motion, source, r)), None)
            if found is None:
                return None
            left = [r for r in left if r is not found]
            copies.append(Copy(found, source, motion))
    return None if left else copies


# ---------------------------------------------------------------- one body at a time


def _mark_layout(item, ctx, paths):
    """The copy's place is written as numbers: every size behind the layout is marked."""
    data = item.get("data") or {}
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


def _in_walk(item, ctx, paths):
    """The pattern as the walk of one body sees it."""
    data = item.get("data") or {}
    if any(ctx.is_target(source) for source in data.get("source_bodies") or ()):
        return StepResult()
    copies = match(data)
    found = next((c for c in copies or () if ctx.is_target(c.result)), None)
    if found is None:
        return Refusal("The copies of this pattern could not be matched to the bodies it made.")
    if ctx.steps:
        return Refusal("This pattern lands on a body that already has steps, which is not copied yet.")
    if _is_mirror(data):
        return Refusal("A mirrored body is only copied when a Combine takes it together with its source.")
    tool = paste.rebuild(ctx, item, found.source)
    if isinstance(tool, Refusal):
        return tool
    with tool.ctx.recording() as marked:
        _mark_layout(item, tool.ctx, paths)
    out = paste.written_again(tool)
    out.join(marked)
    out.add(move.written(found.motion), [MoveMaker(found.motion)])
    return out


def _of_bodies(item):
    return (item.get("data") or {}).get("entity_type") == "bodies"


def rectangular(item, ctx):
    return _in_walk(item, ctx, GRID_PATHS) if _of_bodies(item) else repeat.rectangular(item, ctx)


def circular(item, ctx):
    return _in_walk(item, ctx, TURN_PATHS) if _of_bodies(item) else repeat.circular(item, ctx)


def mirror(item, ctx):
    if _of_bodies(item) and not (item.get("data") or {}).get("combine"):
        return _in_walk(item, ctx, ())
    return repeat.mirror(item, ctx)


# ---------------------------------------------------------------- a whole pattern in a Combine


def _listed(body, tools):
    return any(same_body(body, tool) for tool in tools)


def _pattern_that_made(ctx, tool, before):
    """The pattern item that made the copy `tool`, when nothing changed the copy since; else None."""
    chain = tool_chains.made_by(ctx.timeline, tool, before, ctx.component)
    if len(chain) != 1 or not _of_bodies(chain[0]) or not roles.copies_bodies(chain[0]):
        return None
    if tool_chains.unseen_change(ctx.timeline, tool, before, ctx.component) is not None:
        return None
    results = (chain[0].get("data") or {}).get("result_bodies") or []
    return chain[0] if _listed(tool, results) else None


def _stays_as_copied(ctx, body, pattern, before):
    """True when no item after the pattern and before `before` changed the source `body`."""
    chain = tool_chains.made_by(ctx.timeline, body, before, ctx.component)
    return all(item["index"] <= pattern["index"] for item in chain)


def _whole(ctx, combine_item, pattern, tools, combine):
    """The `Group` of a pattern whose every body the Combine takes, or None."""
    data = pattern.get("data") or {}
    copies = match(data)
    if copies is None or outside_component(pattern) or refs.is_foreign(data):
        return None
    for source in data["source_bodies"]:
        if ctx.is_target(source):
            if combine != "add" or ctx.wrote_after(pattern["index"]):
                return None
        elif not _listed(source, tools) or not _stays_as_copied(ctx, source, pattern, combine_item["index"]):
            return None
    if not all(_listed(c.result, tools) and _pattern_that_made(ctx, c.result, combine_item["index"]) for c in copies):
        return None
    return Group(pattern, list(data["source_bodies"]), copies)


def groups(ctx, combine_item, tools, combine):
    """The `Group`s of the patterns this Combine takes whole. An intersect cannot be repeated."""
    if combine == "intersect":
        return []
    patterns = {}
    for tool in tools:
        found = _pattern_that_made(ctx, tool, combine_item["index"])
        if found is not None:
            patterns[found["index"]] = found
    out = []
    for pattern in patterns.values():
        group = _whole(ctx, combine_item, pattern, tools, combine)
        if group is not None and not any(group.holds(tool) and other.holds(tool) for other in out for tool in tools):
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
    if _is_mirror(data):
        return repeat.mirror
    return repeat.circular if "axis" in data else repeat.rectangular


def _mark_counts(ctx, item):
    """The recipe repeats the tools for any count, and Fusion may keep the Combine's list as it is."""
    why = "%s makes more or fewer copies with it, and Fusion may not change what its Combine takes" % (
        item.get("name") or "A pattern")
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
        refused = tool_refusal(tool.steps)
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
        copies = _repeater(group.item["data"])(group.item, where, (ids, []))
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
