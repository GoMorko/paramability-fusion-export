"""Rib and web feature handler (RibFeature, WebFeature): each wall is written as a thin extrude of an open line.

The shared layer (`design_model/steps/rib_web.py`) finds the wall along each line from the settings and from the faces
Fusion made, or says why it cannot. Each wall goes to `extrude.handle` as the thin extrude it is (`as_extrude`), so
the line, the side, the corners and the sizes go the way of a thin extrude of an open line (`thin_line.py`). A web of
several lines writes one thin extrude per line, in the order of its lines.

What follows sizes: the thickness, a depth set as a distance, and the line when the size probe followed it (a rib or
a web of one line). A depth that Fusion finds (To Next) is written as measured, and every size read before the step
is marked: it may move the faces the wall reaches. A web that Fusion extends to the part (`isExtended`) marks them
too: at other sizes Fusion may stretch its lines to faces that moved.
"""
from ...design_model import design, reach
from ...design_model.problem import is_problem
from ...design_model.steps import rib_web as shared
from .. import extrude, values
from ..result import Refusal, StepResult
from .thin_line import faces_of_built_body


def handle(ctx, step):
    item, data = step.brought, step.brought_data
    walls = shared.walls(data, faces_of_built_body(ctx, data))
    if is_problem(walls):
        return Refusal(walls.words, cause=walls.cause)
    name = item.get("name", "the rib or web")
    for path in ("draft_deg", "fillet"):
        values.pin(ctx, item, path, "%s is copied without a draft or fillet" % name)
    out = StepResult()
    for wall in walls:
        outcome = extrude.handle(ctx, design.as_read(dict(item, data=shared.as_extrude(data, wall))))
        if isinstance(outcome, Refusal):
            return outcome
        out.extend(outcome.entries)
    for path, same in shared.paths_of(data, walls[0]).items():
        values.handled(ctx, item, path, same_as=same)
    if walls[0].measured or data.get("extended"):
        why = ("%s reaches to the faces of the part, and the copy keeps the depth Fusion measured" % name
               if walls[0].measured else "%s stretches its lines to the faces of the part, and the copy keeps them as "
                                          "drawn" % name)
        ctx.doubt(reach.any_face_sizes(ctx.table, ctx.capture.get("items") or [], item), why)
    return out
