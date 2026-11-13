"""Building a tool body of a Combine on its own.

`build` walks the items that made the tool with the normal item loop, in a child context whose target is the tool, so
each handler works on the tool and not on the exported body. The tool's steps, placers and doubts stay in the child
until the Combine decides how to write them.

Steps written one by one onto the part are a different matter: they meet the part, not the tool. `on_part` works such
steps out again against the part as it stood at each step.
"""
from . import body_states, lineage, step_kinds, tool_items, walk
from .capture import outside_component, renamed_target, same_body
from .result import Refusal, StepResult, TranslateResult
from .words import type_words

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
        """The steps of the tool left out of its copy (`gaps.Gap`)."""
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


def name_of(body):
    """The tool in plain words, with its component when it lives in another one."""
    name = body.get("name") or "a body"
    return "%s of %s" % (name, tool_items.component_name(body)) if tool_items.is_foreign_tool(body) else name


def cannot_copy(body, item, why, cause=None):
    """The refusal that names the step of a tool that stops the copy, and what it is. `cause` is that step's
    `gap_hints` cause, so the gap gets its hint."""
    operation = (item.get("data") or {}).get("operation")
    kind = operation if operation in ("cut", "intersect") else type_words(item.get("type") or "")
    return Refusal("The tool body %s cannot be copied: %s (%s): %s" % (name_of(body), item.get("name"), kind, why),
                   cause=cause)


def chain_of(ctx, body, before):
    """The items before `before` that made or changed `body`, in the component that holds it."""
    owner = tool_items.component_token(body) if tool_items.is_foreign_tool(body) else ctx.component
    found = tool_items.chain(ctx.timeline, body, before, owner or "")
    return found if owner else [item for item in found if not outside_component(item)]


def lineage_chain(ctx, body, before):
    """`(links, chain)` for a tool body that a split made: the splits it comes through (`lineage.of`) and the items
    that built it, those of the bodies it was split from up to each split included. Without such a split, no links
    and `chain_of`."""
    links = [] if tool_items.is_foreign_tool(body) else lineage.of({"target": body, "items": [
        item for item in ctx.timeline if item.get("index", 0) < before]})
    found, start = {}, -1
    for at, parent in links:
        for item in chain_of(ctx, parent, at + 1):
            if item["index"] > start:
                found[item["index"]] = item
        start = at
    for item in chain_of(ctx, body, before):
        if item["index"] >= start:
            found[item["index"]] = item
    return links, [found[i] for i in sorted(found)]


def _keeps(item, body):
    """The item only holds `body` as a tool it keeps, so it does not change it."""
    data = item.get("data") or {}
    return bool(data.get("keep_tools")) and any(same_body(t, body) for t in data.get("tools") or [])


def _names_foreign_twin(item, body):
    """The item takes a body of another component with the name of `body`: names repeat between components."""
    return any(record.get("foreign") and record.get("name") == body.get("name")
               for record, _ in tool_items.source_records(item))


def unseen_change(ctx, body, before):
    """`(item, why)` for an item before `before` that `chain_of` cannot see but that may have changed `body`: one of
    another component that lists it, or one that lists its name under another token after the body first appears.
    None when there is no such item."""
    owner = tool_items.component_token(body) if tool_items.is_foreign_tool(body) else ctx.component
    chain = chain_of(ctx, body, before)
    start = chain[0]["index"] if chain else before
    for item in ctx.timeline:
        if item["index"] >= before or item.get("suppressed") or step_kinds.skipped(item.get("type")):
            continue
        listed = item.get("bodies_after") or []
        elsewhere = item.get("component") and item["component"] != owner if owner else outside_component(item)
        if elsewhere:
            if body.get("token") and any(b.get("token") == body["token"] for b in listed) and not _keeps(item, body):
                return item, "This step changes the body from another component, which is not copied yet."
        elif (item["index"] > start and any(renamed_target(b, body) for b in listed)
              and not _names_foreign_twin(item, body)):
            return item, "The body could not be followed through the timeline."
    return None


def _exported(ctx, body):
    while ctx.outer is not None:
        ctx = ctx.outer
    return ctx.is_target(body)


def build(ctx, body, before, depth, place=0):
    """Walk the tool `body` up to timeline index `before`: a `ToolBuild`, or a Refusal that names the step that stops
    it. `depth` is the tool's nesting level, 1 for a tool of the exported body. `place` is its place among the tools
    of its Combine, which keeps the ids of its steps apart from those of the other tools."""
    if depth > MAX_DEPTH:
        return Refusal("The tool body %s is built from tools nested too deep to copy." % name_of(body))
    unseen = unseen_change(ctx, body, before)
    if unseen is not None:
        return cannot_copy(body, *unseen)
    exported = _exported(ctx, body)
    links, made = lineage_chain(ctx, body, before)
    chain = [body_states.seen_on(item, lineage.at(links, body, item["index"])[0], exported) for item in made]
    if not chain:
        return Refusal("The tool body %s is built in a way that cannot be copied." % name_of(body))
    for item in chain:
        if item.get("helper_unread"):
            return Refusal("The tool body %s cannot be copied: %s could not be read: %s"
                           % (name_of(body), item.get("name"), item["helper_unread"]))
    child = ctx.child(body, "%st%s_%s_" % (ctx.id_prefix, before, place), chain, depth)
    child.lineage = links
    walked = TranslateResult()
    if not walk.walk_items(child, walked):
        if walked.over_gap_cap:
            return Refusal(walked.refusal["reason"], over_gap_cap=True, tool_steps=walked.items)
        stopped = next(item for item in chain if item["index"] == walked.refusal["index"])
        return cannot_copy(body, stopped, walked.refusal["reason"], walked.refusal_cause)
    if not child.steps:
        return Refusal("The tool body %s is built in a way that cannot be copied." % name_of(body))
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
            outcome = walk.run_handler(ctx.handlers[item["type"]], item, ctx)
        if isinstance(outcome, Refusal):
            return cannot_copy(tool.body, item, outcome.reason, outcome.cause)
        out.extend(outcome.entries)
        out.doubts.extend(construction.doubts + outcome.doubts)
        out.asked |= outcome.asked
        out.items.append(item)
    return out
