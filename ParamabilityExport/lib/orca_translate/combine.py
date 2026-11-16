"""Combine steps as Orca Booleans: each tool body is written from the steps that made it (`tools.build`), then a
Boolean adds it to the part, cuts it away or keeps what both share.

Orca drops the tool body after the Boolean even when Fusion keeps it: only the exported part is copied, and a later
Combine that takes the same tool writes it again. An intersect with several tools follows the rule the capture
measured: keep what the part shares with every tool (one Boolean per tool), or with any of them (the tools joined
first). A Combine that changes another body and keeps the part as a tool does not change the part.
"""
from ..capture_model import gap_hints
from ..capture_model.capture import same_body
from ..orca_recipe.enums import BooleanMode
from . import causes
from .steps import Skip
from .tools import OPERATIONS, Pass, boolean, build, data_of, label


def combine(ctx, item):
    data = data_of(item)
    tools = [t for t in data.get("tools") or [] if isinstance(t, dict)]
    if not same_body(data.get("target"), ctx.target):
        if data.get("keep_tools") and any(same_body(t, ctx.target) for t in tools):
            return Pass("It changes another body and keeps this part as it is.")
        return Skip("This Combine adds the part to another body, which is not copied.", causes.OTHER_BODY)
    mode = OPERATIONS.get(data.get("operation"))
    if mode is None:
        return Skip("This kind of Combine is not copied.")
    if not ctx.has_body:
        return Skip("The part this Combine works on is not in the copy.", gap_hints.AFTER_GAP)
    if not tools:
        return Skip("The tool bodies of this Combine could not be read.")
    joined = False
    if mode == BooleanMode.INTERSECT and len(tools) > 1:
        model = data.get("intersect_model")
        if model not in ("every", "any"):
            return Skip("It is not known whether this Combine keeps what the part shares with every tool or with "
                        "any of them, so it is not copied.", causes.INTERSECT_RULE)
        joined = model == "any"
    start = len(ctx.features)
    mark = ctx.checkpoint()
    built = []
    for tool in tools:
        body = build(ctx, tool, item)
        if isinstance(body, Skip):
            ctx.rollback(mark)
            return body
        built.append(body)
    name = label(item)
    if joined:
        first = built[0]
        ctx.push(first)
        for n, other in enumerate(built[1:], start=2):
            boolean(ctx, other, BooleanMode.ADD, "%s (tools %d)" % (name, n))
        ctx.pop()
        built = [first]
    for n, body in enumerate(built, start=1):
        boolean(ctx, body, mode, name if len(built) == 1 else "%s (%d)" % (name, n))
    return ctx.features[start:]


HANDLERS = {"CombineFeature": combine}
