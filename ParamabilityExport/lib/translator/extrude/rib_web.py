"""Rib and web feature handler (RibFeature, WebFeature): each wall is written as a thin extrude of an open line.

The shared layer (`design_model/steps/rib_web.py`) finds the wall along each line from the settings and from the faces
Fusion made, or says why it cannot. Each wall goes to `extrude.handle` as the thin extrude it is (`as_extrude`), so
the line, the side, the corners and the sizes go the way of a thin extrude of an open line (`thin_line.py`). A web of
several lines writes one thin extrude per line, in the order of its lines.

A rib To Next that Fusion filled up to the part (a gusset in a corner, `design_model/steps/rib_fill.py`) goes to
`extrude.handle` as the extrude of the closed outline Fusion made, which keeps its numbers.

What follows sizes: the thickness, a depth set as a distance, and the line when the size probe followed it (a rib or
a web of one line). The shared layer says which sizes to mark (`marks`): every size read before the step, and the
values that make the wall longer, when a To Next depth is measured, when the wall may run into the part at other sizes
(it is not `clear`), when Fusion extends the lines of a web to the part, or when the outline of a filled rib is kept.
"""
from ...design_model import design, reach
from ...design_model.problem import is_problem
from ...design_model.steps import rib_fill
from ...design_model.steps import rib_web as shared
from .. import extrude, values
from ..result import Refusal, StepResult
from .thin_line import faces_of_built_body


def _built(ctx, item, extrudes):
    """The StepResult of the extrudes of `extrudes` (extrude data), or the first Refusal."""
    out = StepResult()
    for data in extrudes:
        outcome = extrude.handle(ctx, design.as_read(dict(item, data=data)))
        if isinstance(outcome, Refusal):
            return outcome
        out.extend(outcome.entries)
    return out


def handle(ctx, step):
    item, data = step.brought, step.brought_data
    before = faces_of_built_body(ctx, data)
    walls = shared.walls(data, before)
    filled = rib_fill.fill(data, before, walls) if is_problem(walls) else None
    if is_problem(filled):
        return Refusal(filled.words, cause=filled.cause)
    name = item.get("name", "the rib or web")
    for path in ("draft_deg", "fillet"):
        values.pin(ctx, item, path, "%s is copied without a draft or fillet" % name)
    if filled is not None:
        out = _built(ctx, item, [rib_fill.as_extrude(data, filled)])
        paths, marks = {"thickness": rib_fill.length_path(filled)}, rib_fill.marks(name)
    else:
        out = _built(ctx, item, [shared.as_extrude(data, wall) for wall in walls])
        paths, marks = shared.paths_of(data, walls[0]), shared.marks(data, walls[0], name)
    if isinstance(out, Refusal):
        return out
    for path, same in paths.items():
        values.handled(ctx, item, path, same_as=same)
    for names, why in marks:
        ctx.doubt(tuple(reach.any_face_sizes(ctx.table, ctx.capture.get("items") or [], item))
                  + tuple(n for path in names for n in values.reads(ctx, item, path)), why)
    return out
