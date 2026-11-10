"""Building a tool body of a Combine on its own.

`build` walks the items that made the tool with the normal item loop, in a child context whose target is the tool, so
each handler works on the tool and not on the exported body. The tool's steps, placers and doubts stay in the child
until the Combine decides how to write them.

Steps written one by one onto the part are a different matter: they meet the part, not the tool. `on_part` works such
steps out again against the part as it stood at each step.
"""
from . import tool_items, walk
from .capture import outside_component
from .result import Refusal, StepResult, TranslateResult
from .words import type_words

MAX_DEPTH = 3
# What the reader measured on the tool itself, under the names the handlers read for their target.
_BODY_STATE_FIELDS = (("box_before", "target_box_before"), ("volume_before", "volume_before"),
                      ("volume_after", "volume_after"))


class ToolBuild:
    """A tool body walked on its own.

    body: the tool's record in the Combine. chain: the items that made it, as the walk saw them. ctx: the child
    context, with the tool's steps, placers and doubts. verdicts: the verdict of each item of the chain.
    """

    def __init__(self, body, chain, ctx, verdicts):
        self.body, self.chain, self.ctx, self.verdicts = body, chain, ctx, verdicts

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

    def entries_of(self, item):
        """The `Entry` records the walk wrote for one item of the chain."""
        return self.ctx.entries_by_index.get(item["index"], [])

    @property
    def entries(self):
        return [entry for item in self.chain for entry in self.entries_of(item)]


def name_of(body):
    """The tool in plain words, with its component when it lives in another one."""
    name = body.get("name") or "a body"
    return "%s of %s" % (name, tool_items.component_name(body)) if tool_items.is_foreign_tool(body) else name


def cannot_copy(body, item, why):
    """The refusal that names the step of a tool that stops the copy, and what it is."""
    operation = (item.get("data") or {}).get("operation")
    kind = operation if operation in ("cut", "intersect") else type_words(item.get("type") or "")
    return Refusal("The tool body %s cannot be copied: %s (%s): %s" % (name_of(body), item.get("name"), kind, why))


def _chain(ctx, body, before):
    """The items before `before` that made or changed `body`, in the component that holds it."""
    owner = tool_items.component_token(body) if tool_items.is_foreign_tool(body) else ctx.component
    found = tool_items.chain(ctx.timeline, body, before, owner or "")
    return found if owner else [item for item in found if not outside_component(item)]


def _seen_from_tool(item, body):
    """The item as a walk of `body` reads it: in the body's component, with what was measured on the body itself. What
    the capture says about the exported body does not apply, and a capture without measures of the body keeps its
    fields."""
    data = item.get("data")
    state = (item.get("body_states") or {}).get(body.get("token"))
    if isinstance(state, dict) and isinstance(data, dict):
        data = dict(data, **{field: state.get(key) for key, field in _BODY_STATE_FIELDS})
    return dict(item, data=data, in_target_component=True, target_changed=None)


def build(ctx, body, before, depth, place=0):
    """Walk the tool `body` up to timeline index `before`: a `ToolBuild`, or a Refusal that names the step that stops
    it. `depth` is the tool's nesting level, 1 for a tool of the exported body. `place` is its place among the tools
    of its Combine, which keeps the ids of its steps apart from those of the other tools."""
    if depth > MAX_DEPTH:
        return Refusal("The tool body %s is built from tools nested too deep to copy." % name_of(body))
    chain = [_seen_from_tool(item, body) for item in _chain(ctx, body, before)]
    if not chain:
        return Refusal("The tool body %s is built in a way that cannot be copied." % name_of(body))
    for item in chain:
        if item.get("helper_unread"):
            return Refusal("The tool body %s cannot be copied: %s could not be read: %s"
                           % (name_of(body), item.get("name"), item["helper_unread"]))
    child = ctx.child(body, "%st%s_%d_" % (ctx.id_prefix, before, place), chain, depth)
    walked = TranslateResult()
    if not walk.walk_items(child, walked):
        stopped = next(item for item in chain if item["index"] == walked.refusal["index"])
        return cannot_copy(body, stopped, walked.refusal["reason"])
    return ToolBuild(body, chain, child, walked.items)


def on_part(ctx, tool):
    """The `StepResult` of a walked tool whose steps are written one by one onto the part, or a Refusal. Each step is
    worked out against the part as it stood at that step: a tool that reaches to a face of the part follows that face,
    and outlines are ordered so that each one meets what is built. Doubts count only once the Combine writes them."""
    out = StepResult()
    for item in tool.chain:
        with ctx.as_of(item):
            with ctx.recording() as construction:
                walk.fix_construction(ctx, item)
            outcome = walk.run_handler(ctx.handlers[item["type"]], item, ctx)
        if isinstance(outcome, Refusal):
            return cannot_copy(tool.body, item, outcome.reason)
        out.extend(outcome.entries)
        out.doubts.extend(construction.doubts + outcome.doubts)
        out.asked |= outcome.asked
        out.items.append(item)
    return out
