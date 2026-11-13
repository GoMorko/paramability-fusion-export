"""What a pattern or a mirror repeats: the steps its source features wrote.

The sources split into solid steps, which one `pattern` or `mirror` step repeats, and rounds and chamfers, which get
their own copies. A Combine among the sources is repeated by the steps it wrote, with every item that built its tools.
Sources the copy cannot repeat give a Refusal.
"""
from . import notes as wording, tool_walk
from .result import Refusal
from ..capture_model import gap_hints, tool_items
from ..capture_model.step_kinds import FINISH, SOLID, recipe_kind
from .step_walk import moved_later

MAX_REFERENCES = 64

# Finish fields that a copy cannot carry; the translator never writes them.
UNCOPYABLE_FINISH_KEYS = ("sizeEnd",)


def _tools_of(item):
    """The tool bodies of a Combine item (its data lists `tools`), else an empty list."""
    tools = (item.get("data") or {}).get("tools")
    return [tool for tool in tools if isinstance(tool, dict)] if isinstance(tools, list) else []


def _combines(ctx):
    """`(item, [(tool name, indexes that built the tool)])` for each Combine of the timeline (`tool_items.built_by`).
    It depends on the capture alone, so it is worked out once per translation."""
    cache = ctx.cache.setdefault(__name__, {})
    if "combines" not in cache:
        cache["combines"] = [
            (item, [(tool_walk.name_of(tool), tool_items.built_by(ctx.timeline, tool, item)) for tool in tools])
            for item, tools in ((item, _tools_of(item)) for item in ctx.timeline) if tools]
    return cache["combines"]


def _written_combines(ctx):
    """The `_combines` entries of the Combines of this walk's body that wrote steps."""
    for item, tools in _combines(ctx):
        if ctx.steps_of(item["index"]) and ctx.is_target(item["data"].get("target")):
            yield item, tools


def _combined_tools(indexes, ctx, what):
    """The source items a Combine among the sources writes, or a Refusal.

    Fusion repeats a Combine with the items that built its tools when all of them are sources, and the copy repeats
    what the Combine wrote. Only some of those items, or the items without their Combine, give a result the copy cannot
    follow. A Combine that keeps only what its tools share with the part cannot be repeated."""
    chosen, covered = set(indexes), set()
    combines = list(_written_combines(ctx))
    for item, tools in combines:
        if item["index"] not in chosen:
            continue
        if (item.get("data") or {}).get("operation") == "intersect":
            return Refusal("%s keeps only what its tool shares with the part, so this %s cannot repeat it."
                           % (item.get("name") or "A Combine", what))
        for name, found in tools:
            if not found or not found <= chosen:
                return Refusal("This %s copies %s but not every step that builds its tool body %s, which is not "
                               "copied yet." % (what, item.get("name") or "a Combine", name))
            covered |= found
    for item, tools in combines:
        for name, found in tools:
            if item["index"] not in chosen and any(not ctx.steps_of(i) for i in (found & chosen) - covered):
                return Refusal("This %s copies steps that build the tool body %s without %s, which uses it. That is "
                               "not copied yet." % (what, name, item.get("name") or "the Combine"))
    return covered


def split_sources(data, ctx, what):
    """Split the source items into (solid step ids, finish steps), or a Refusal."""
    if data.get("entity_type") != "features":
        return Refusal("Patterns of faces or bodies are not copied yet.",
                       cause=gap_hints.REPEAT_FACES if data.get("entity_type") == "faces" else None)
    indexes = data.get("sources") or []
    if not indexes:
        return Refusal("This %s has no features to copy." % what)
    covered = _combined_tools(indexes, ctx, what)
    if isinstance(covered, Refusal):
        return covered
    by_id = {step["id"]: step for step in ctx.steps}
    solids, finishes = [], []
    for index in indexes:
        ids = ctx.steps_of(index)
        if not ids and index in ctx.folded and any(ctx.folded[index] in ctx.steps_of(i) for i in indexes):
            # A round drawn into the outline of a step this repeat copies too: the copies carry it.
            continue
        if not ids and index in covered:
            # A step that built a tool of a Combine this repeat copies: the Combine's steps carry it.
            continue
        if not ids:
            missing = [gap for gap in (ctx.gap_of(i) for i in indexes) if gap is not None]
            if missing:
                return Refusal(wording.repeats_gap_reason([gap.name for gap in missing]), [gap.id for gap in missing])
            return Refusal("A step this %s copies is not part of the exported body." % what)
        if any(moved_later(ctx.steps, step_id) for step_id in ids):
            return Refusal("A step this %s copies was moved by a later Move, which is not copied yet." % what)
        if any(step_id in ctx.not_repeatable for step_id in ids):
            return Refusal("A step that reaches to the part or to a face grows with the part, so its copies are not "
                           "copied yet.")
        for step_id in ids:
            step = by_id[step_id]
            repeat = recipe_kind(step["kind"]).repeat
            if repeat == FINISH:
                near = (step.get("edges") or {}).get("near")
                plain = ctx.plain_picks.get(step_id) or {"near": near, "reads": (), "written": near}
                if plain["near"] is None or any(k in step for k in UNCOPYABLE_FINISH_KEYS):
                    return Refusal("A rounded or chamfered step of this %s cannot be repeated." % what)
                finishes.append(dict(step, near=plain["near"], reads=plain["reads"], written=plain.get("written")))
            elif repeat == SOLID:
                if step.get("combine") == "intersect":
                    return Refusal("A step that trims the part cannot be repeated.")
                if step.get("combine") == "new":
                    return Refusal("A step that makes a separate body cannot be repeated.")
                if step_id not in solids:
                    solids.append(step_id)
            else:
                return Refusal("A step of this %s cannot be repeated." % what)
    if len(solids) > MAX_REFERENCES:
        return Refusal("This %s repeats more than %d steps." % (what, MAX_REFERENCES))
    return solids, finishes
