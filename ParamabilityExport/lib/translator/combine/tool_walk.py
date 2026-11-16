"""Building a tool body of a Combine on its own.

`build` walks the items that made the tool with the normal item loop, in a child context whose target is the tool, so
each handler works on the tool and not on the exported body. The tool's steps, placers and doubts stay in the child
until the Combine decides how to write them.

Steps written one by one onto the part are a different matter: they meet the part, not the tool. `on_part` works such
steps out again against the part as it stood at each step.
"""
from ...design_model import design, tool_chains
from .. import walk
from ..gaps.finishing import is_finishing
from ..result import Refusal, StepResult, TranslateResult
from ...design_model.words import ToolStop

MAX_DEPTH = 3


class ToolBuild:
    """A tool body walked on its own.

    body: the tool's record in the Combine. chain: the items that made it, as the walk saw them. ctx: the child
    context, with the tool's steps, placers, doubts and gaps. verdicts: the verdict of each item of the chain. notes:
    the plain remarks of the walk.
    """

    def __init__(self, body, chain, ctx, verdicts, notes=()):
        self.body, self.chain, self.ctx, self.verdicts, self.notes = body, chain, ctx, verdicts, list(notes)

    @property
    def steps(self):
        return self.ctx.steps

    @property
    def doubts(self):
        return self.ctx.doubts

    @property
    def asked(self):
        return self.ctx.asked

    @property
    def items(self):
        return self.ctx.copied_items

    @property
    def gaps(self):
        """The steps of the tool left out of its copy (`gaps.stops.Gap`)."""
        return self.ctx.gaps

    def entries_of(self, item):
        """The `Entry` records the walk wrote for one item of the chain."""
        return self.ctx.entries_by_index.get(item["index"], [])

    @property
    def entries(self):
        return [entry for item in self.chain for entry in self.entries_of(item)]

    def hand_over(self, out):
        """The steps of this tool are written in `out`: what the walk recorded counts from now on."""
        out.doubts.extend(self.doubts)
        out.items.extend(self.items)
        out.asked |= self.asked
        out.notes.extend(self.notes)
        out.tool_steps.extend(self.verdicts)
        out.gaps.extend(self.gaps)


def cannot_copy(body, item, why, cause=None, inner=None):
    """The refusal that names the step of a tool that stops the copy, and why (`why`, a sentence). `cause` is that
    step's `gap_hints` cause, so the gap gets its hint. `inner` is the `ToolStop` of that step when it is a Combine
    whose own tool cannot be built."""
    stop = ToolStop.through(tool_chains.name_of(body), item.get("name"), why, inner)
    return Refusal(stop.reason, cause=cause, stop=stop)


def shaping_gap(gaps):
    """The first of `gaps` (`gaps.stops.Gap`) whose missing step does more than finish surfaces, or None. Such a step
    (a Move, an extrude, a Combine of its own) can change the place or the material of a tool body, so a join, cut or
    intersect with the tool as written gives a wrong part. A missing round, bevel or draft (`gaps/finishing.py`) only
    finishes the tool, and the gap in the tool's list says so."""
    return next((gap for gap in gaps if not is_finishing(gap.item.get("type"), design.as_read(gap.item).brought_data)),
                None)


def unfinished(tool):
    """A Refusal that names the step a walked `tool` misses when that step can change its place or material
    (`shaping_gap`), else None. The gaps inside the tool are then dropped with it."""
    gap = shaping_gap(tool.gaps)
    return None if gap is None else cannot_copy(tool.body, gap.item, gap.reason, gap.cause)


def _exported(ctx, body):
    while ctx.outer is not None:
        ctx = ctx.outer
    return ctx.is_target(body)


def build(ctx, body, before, depth, place=0):
    """Walk the tool `body` up to timeline index `before`: a `ToolBuild`, or a Refusal that names the step that stops
    it. `depth` is the tool's nesting level, 1 for a tool of the exported body. `place` is its place among the tools
    of its Combine, which keeps the ids of its steps apart from those of the other tools."""
    if depth > MAX_DEPTH:
        return Refusal("The tool body %s is built from tools nested too deep to copy." % tool_chains.name_of(body))
    found = tool_chains.read(ctx.timeline, body, before, ctx.component, _exported(ctx, body))
    if found.unseen is not None:
        return cannot_copy(body, *found.unseen)
    chain = list(found.items)
    if not chain:
        return Refusal("The tool body %s is built in a way that cannot be copied." % tool_chains.name_of(body))
    for item in chain:
        if item.get("helper_unread"):
            return cannot_copy(body, item, "This step could not be read: %s" % item["helper_unread"])
    child = ctx.child(body, "%st%s_%s_" % (ctx.id_prefix, before, place), chain, depth)
    child.lineage = list(found.links)
    walked = TranslateResult()
    if not walk.walk_items(child, walked):
        if walked.over_gap_cap:
            return Refusal(walked.refusal["reason"], over_gap_cap=True, tool_steps=walked.items)
        stopped = next(item for item in chain if item["index"] == walked.refusal["index"])
        return cannot_copy(body, stopped, walked.refusal["reason"], walked.refusal_cause, walked.refusal_stop)
    if not child.steps:
        return Refusal("The tool body %s is built in a way that cannot be copied." % tool_chains.name_of(body))
    return ToolBuild(body, chain, child, walked.items, walked.notes)


def on_part(ctx, tool):
    """The `StepResult` of a walked tool whose steps are written one by one onto the part, or a Refusal. Each step is
    worked out against the part as it stood at that step: a tool that reaches to a face of the part follows that face,
    and outlines are ordered so that each one meets what is built. Doubts count only once the Combine writes them. A
    tool with gaps is never written this way, since its left out steps have no handler result to replay."""
    out = StepResult()
    for item in tool.chain:
        with ctx.as_of(item):
            with ctx.recording() as construction:
                walk.fix_construction(ctx, item)
            outcome = walk.run_handler(ctx.handlers[item["type"]], design.as_read(item), ctx)
        if isinstance(outcome, Refusal):
            return cannot_copy(tool.body, item, outcome.reason, outcome.cause, outcome.stop)
        out.extend(outcome.entries)
        out.doubts.extend(construction.doubts + outcome.doubts)
        out.asked |= outcome.asked
        out.items.append(item)
    return out
