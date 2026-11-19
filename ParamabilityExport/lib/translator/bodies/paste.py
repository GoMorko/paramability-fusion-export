"""Copy Paste Body handler (CopyPasteBody).

A pasted body starts here: its steps are those of its source, as the source stood at the paste, written again with ids
of their own (`tool_walk.build`). A paste of a body that is itself pasted repeats this. A paste of several bodies makes
several results, paired with their sources by their points. The first vertices of the source and of the result say
where the result sits (`design_model/steps/paste.py`). In one component that is the same place; any other place is written as a
`move` in plain numbers, and the sizes that could change it are marked.
"""
from ...capture_model import tool_items
from ...design_model import refs
from ...design_model.problem import is_problem
from ...design_model.steps import paste as pasted
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


def _mark_place(ctx, item, source, tool):
    """The result sits away from its source. Its place is a number, so the sizes that could move it are marked."""
    if tool_items.is_foreign_tool(source):
        refs.mark_all(ctx, item, {"component": source.get("component"), "type": PLACE}, WHAT)
    else:
        ctx.doubt(follow.reads_with_outer(tool.ctx, item), "%s puts its body at a place that may move with it"
                  % (item.get("name") or "A paste"))


def handle(ctx, step):
    item, data = step.brought, step.brought_data
    result = pasted.result_of(data, ctx.is_target)
    if is_problem(result):
        return Refusal(result.words)
    if ctx.steps:
        return Refusal("This paste lands on a body that already has steps, which is not copied yet.")
    found = pasted.pair(data, result)
    if is_problem(found):
        return Refusal(found.words)
    source = found.source
    motion = Motion() if found.move.is_identity else Motion(found.move.rows, found.move.offset)
    tool = rebuild(ctx, item, source)
    if isinstance(tool, Refusal):
        return tool
    out = written_again(tool)
    if not motion.is_identity:
        _mark_place(ctx, item, source, tool)
        out.add(move.written(motion), [MoveMaker(motion)])
    return out
