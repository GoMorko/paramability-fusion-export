"""Rib and web steps as Orca features: each wall is built as the thin extrude of an open line it is (`thin.py`).

The shared layer (`design_model/steps/rib_web.py`) finds the wall along each line from the settings and from the faces
Fusion made, or says why it cannot. A web of several lines writes the features of one thin extrude per line. The
thickness and a depth set as a distance follow their variables where the thin extrude lets them (`thin.py`: the
length of the extrude always, the width of the wall only for one straight line with the wall centred on it).

A depth that Fusion finds (To Next) is written as measured, and every size read before the step is marked: it may
move the faces the wall reaches. A web that Fusion extends to the part marks them too.
"""
from ..design_model import design, reach
from ..design_model.problem import is_problem
from ..design_model.steps import rib_web as shared
from .skip import Skip
from .steps import extrude
from .thin import faces_of_part


def rib_web(ctx, step):
    """The Orca features of a rib or web (`step`, a `design.ResolvedStep`), or a Skip."""
    item, data = step.brought, step.brought_data
    walls = shared.walls(data, faces_of_part(ctx, data))
    if is_problem(walls):
        return Skip.of(walls)
    name = item.get("name") or "the rib or web"
    for path in ("draft_deg", "fillet"):
        ctx.doubt(ctx.quantity(item, path, 0.0, "angle" if path == "draft_deg" else "length").reads,
                  "%s is copied without a draft or fillet" % name)
    out = []
    for wall in walls:
        made = extrude(ctx, design.as_read(dict(item, data=shared.as_extrude(data, wall))))
        if isinstance(made, Skip):
            return made
        out += made
    if walls[0].measured or data.get("extended"):
        why = ("%s reaches to the faces of the part, and the Orca copy keeps the depth Fusion measured" % name
               if walls[0].measured else "%s stretches its lines to the faces of the part, and the Orca copy keeps "
                                          "them as drawn" % name)
        ctx.doubt(reach.any_face_sizes(ctx.table, ctx.capture.get("items") or [], item), why)
    return out


HANDLERS = {"RibFeature": rib_web, "WebFeature": rib_web}
