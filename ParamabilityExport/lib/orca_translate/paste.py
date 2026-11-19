"""Copy Paste Body steps: a pasted body starts as its source stood just before the paste.

Fusion keeps a pasted body tied to its source up to the paste, so the steps that built the source before the paste
are written again as a new Orca body (`tools.build` with the paste as the anchor), with the same bound fields. That
body then is the body the walk builds: the exported part when the part is pasted, or a tool body when a Combine takes
the pasted body. Later steps of the pasted body (a Move, a cut) are copied by their own handlers on it, and a Combine
adds it to the part or cuts it away as it does with any tool. Steps of the source after the paste do not reach the
copy.

Which source a pasted body copies and where the copy sits are facts of the shared layer
(`design_model/steps/paste.py`). Left out:
- a paste whose bodies cannot be read or paired with their sources (the reason of the shared layer);
- a source of another component (cause `madeInOtherComponent`);
- a pasted body that does not sit where its source sat (cause `pastePlace`): Fusion pastes in place, and the copy does
  not know what else puts it elsewhere;
- a source that the Orca copy cannot build up to the paste (cause `afterGap`): the reason names the step that stops it.

A later step of the pasted body does not look up the features of the source's steps by their timeline index
(`Body.pasted`): a pattern of features that repeats one of them is left out (`repeat`). Rounds and chamfers find the
outline they change by its shape, so they work on the pasted body's own features.
"""
from ..capture_model import gap_hints
from ..capture_model.capture import same_body
from ..design_model.problem import is_problem
from ..design_model.steps import paste as pasted
from . import causes
from .steps import Skip
from .tools import build


def paste(ctx, step):
    item, data = step.brought, step.brought_data
    result = pasted.result_of(data, lambda record: same_body(record, ctx.target))
    if is_problem(result):
        return Skip.of(result)
    if ctx.has_body:
        return Skip("This paste lands on a body that already has steps, which is not copied to Orca yet.")
    found = pasted.pair(data, result)
    if is_problem(found):
        return Skip.of(found)
    if found.source.get("foreign"):
        return Skip("The body this paste copies is in another component, which is not copied to Orca yet.",
                    gap_hints.MADE_IN_OTHER_COMPONENT)
    if not found.move.is_identity:
        return Skip("The pasted body does not sit where the body it copies sat, which is not copied to Orca yet.",
                    causes.PASTE_PLACE)
    start = len(ctx.features)
    kept = dict(ctx.written), dict(ctx.shapes)
    body = build(ctx, found.source, item)
    again = {index for index, made in ctx.written.items() if kept[0].get(index) is not made}
    _keep_earlier(ctx, *kept)
    if isinstance(body, Skip):
        return Skip(body.reason, gap_hints.AFTER_GAP, body.stop)
    _take_over(ctx, body, again)
    return ctx.features[start:]


def _keep_earlier(ctx, written, shapes):
    """A source step that the walk wrote before (the part pasted onto itself) keeps the features it wrote then: later
    steps of the part (a round drawn into an outline, a pattern of features) work on those, not on the copy."""
    for index, made in written.items():
        ctx.written[index] = made
    for index, made in shapes.items():
        ctx.shapes[index] = made


def _take_over(ctx, built, again):
    """The body the walk builds becomes the body `tools.build` wrote: it takes its place in Orca's list of bodies and
    its shape, so later steps work on it. `again` holds the indexes of the steps written into it: their features in
    `ctx.written` may be those of the source (`_keep_earlier`), so a later step of the body must not look them up by
    index (`Body.pasted`)."""
    scope = ctx.scope
    scope.pasted |= again | built.pasted
    scope.index, scope.has_body = built.index, True
    scope.solid.pieces = list(built.solid.pieces)
    scope.solid.unsure = list(built.solid.unsure)
    scope.finishes = list(built.finishes)
    ctx.bodies[built.index] = scope


HANDLERS = {"CopyPasteBody": paste}
