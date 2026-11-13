"""Copy Paste Body handler (CopyPasteBody).

A pasted body starts here: its steps are those of its source, as the source stood at the paste, written again with ids
of their own (`tool_walk.build`). A paste of a body that is itself pasted repeats this. A paste of several bodies makes
several results, paired with their sources by their points. The first vertices of the source and of the result say
where the result sits. In one component that is the same place; any other place is written as a
`move` in plain numbers, and the sizes that could change it are marked.
"""
from ...capture_model import tool_items
from .. import ref_motion
from ..combine import tool_walk
from ..faces import follow
from ..faces.moved_placer import MoveMaker
from ..faces.slabs import Motion
from ..faces.tool_placer import JoinedWalk
from ..result import Refusal, StepResult
from . import move

PLACE = "Place"
WHAT = "puts its body at"


def rebuild(ctx, item, source, place=0):
    """The `ToolBuild` of `source` as it stood before `item`, or a Refusal."""
    return tool_walk.build(ctx, source, item["index"], ctx.depth + 1, place)


def written_again(tool):
    """A `StepResult` that writes the steps of the walked `tool` in the list of the walk that holds it. Their ids stay,
    since steps name each other by them."""
    out = StepResult(tool.entries)
    out.entries[0].placers.append(JoinedWalk(tool.ctx))
    tool.hand_over(out)
    return out


def _place_of(source, result):
    """The `Motion` from the source to the result, or a Refusal."""
    before, after = source.get("points") or [], result.get("points") or []
    if not before or len(before) != len(after):
        return Refusal("The corners of the pasted body could not be read, so its place cannot be checked.")
    if move.carries(Motion(), before, after):
        return Motion()
    found = move.fit(before, after)
    return found if found is not None else Refusal("The pasted body does not match the body it was copied from.")


def _source_of(result, sources, results):
    """The source of the pasted body `result`, or None when sources and results do not pair up one to one. A source at
    the same place wins over one that only has the same shape."""
    if len(sources) != len(results):
        return None
    if len(sources) == 1:
        return sources[0]
    paired = [(r, _candidates(r, sources)) for r in results]
    if any(len(found) != 1 for _, found in paired) or len({id(found[0]) for _, found in paired}) != len(paired):
        return None
    return next(found[0] for r, found in paired if r is result)


def _candidates(result, sources):
    """The sources `result` can be a copy of: those at its place, else those of its shape."""
    places = [(source, _place_of(source, result)) for source in sources]
    fitting = [(source, place) for source, place in places if not isinstance(place, Refusal)]
    return [source for source, place in fitting if place.is_identity] or [source for source, _ in fitting]


def _mark_place(ctx, item, source, tool):
    """The result sits away from its source. Its place is a number, so the sizes that could move it are marked."""
    if tool_items.is_foreign_tool(source):
        ref_motion.mark_all(ctx, item, {"component": source.get("component"), "type": PLACE}, WHAT)
    else:
        ctx.doubt(follow.reads_with_outer(tool.ctx, item), "%s puts its body at a place that may move with it"
                  % (item.get("name") or "A paste"))


def handle(item, ctx):
    data = item.get("data") or {}
    sources, results = data.get("sources") or [], data.get("result_bodies")
    if not sources:
        return Refusal("The body this paste copies could not be read.")
    result = next((r for r in results if ctx.is_target(r)), None) if isinstance(results, list) else None
    if result is None:
        return Refusal("The body this paste makes could not be read.")
    if ctx.steps:
        return Refusal("This paste lands on a body that already has steps, which is not copied yet.")
    source = _source_of(result, sources, results)
    if source is None:
        return Refusal("The bodies this paste copies could not be paired with the bodies it made.")
    motion = _place_of(source, result)
    if isinstance(motion, Refusal):
        return motion
    tool = rebuild(ctx, item, source)
    if isinstance(tool, Refusal):
        return tool
    out = written_again(tool)
    if not motion.is_identity:
        _mark_place(ctx, item, source, tool)
        out.add(move.written(motion), [MoveMaker(motion)])
    return out
