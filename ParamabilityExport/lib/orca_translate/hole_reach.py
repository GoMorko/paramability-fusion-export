"""The depth of a hole that goes up to a face or plane ("To" extent), for the Orca copy.

Orca's hole has a depth, or goes through all; its "up to face" names a face by Orca's own numbering, which the copy
cannot know. So the depth is a distance, worked out as the length of an extrude up to a face is (`extents.reach`):

- The face or plane must be flat and square to the hole's axis. A tilted or curved one, one of another component and
  one the capture does not place leave the hole out.
- The depth is the measured one, from each hole's position to its flat end (`hole_facts.reach_depth`), and it must be
  the distance from that position to the plane of the face: a hole that ends elsewhere is left out.
- The depth follows the sizes that move the face where the extrude logic follows them (`extents.plane_move`: an
  offset plane with its own distance and its base, an end face of a copied extrude). Orca keeps the plane the hole
  sits on as a number, so the depth is the measured one plus how far the face moves along the drilling direction.
  Sizes that may move the face in any other way keep the measured depth, and those sizes are marked.
- A face Fusion may join with the faces next to it (the capture does not say whether the hole does) may end the hole
  elsewhere at other sizes, so the sizes that may move it are marked.
- The depth must stay above zero (`guard`).
"""
from ..capture_model import gap_hints
from ..design_model import reach
from ..design_model.problem import Problem
from ..design_model.steps import extrude as dm, hole as hole_facts
from ..design_model.values import Quantity
from ..geometry import vec
from . import extents, limits
from .skip import Skip
from .tools import label


def _face_skip(record):
    """The Skip for a face or plane the copy cannot use as the end of a hole, or None."""
    if record.get("foreign"):
        return Skip("This hole goes up to a face or plane of another component, which is not copied.",
                    gap_hints.OTHER_COMPONENT)
    plane = record.get("plane")
    flat = isinstance(plane, dict) and plane.get("point") and plane.get("normal")
    if not flat or record.get("surface") in dm.CURVED_SURFACES:
        return Skip("This hole goes up to a surface that is not flat, which is not copied.", gap_hints.EXTRUDE_END_FACE)
    return None


def depth(ctx, item, data, unit):
    """The depth (a `Quantity`, mm along the unit drilling direction `unit`) of the hole step `data` whose extent goes
    up to a face or plane, or a Skip."""
    record = data.get("extent") or {}
    refused = _face_skip(record)
    if refused is not None:
        return refused
    plane = record["plane"]
    if not dm.parallel(plane["normal"], unit):
        return Skip("This hole goes up to a tilted surface, which is not copied.", gap_hints.EXTRUDE_END_FACE)
    measured = hole_facts.reach_depth(data, unit)
    if isinstance(measured, Problem):
        return Skip.of(measured)
    for position in data["positions"]:
        if abs(vec.dot(vec.sub(list(plane["point"]), list(position)), unit) - measured) > dm.LENGTH_TOL:
            return Skip("The measured end of this hole is not on the face it goes up to, so it is not copied.")
    if ctx.table is not None and dm.joins_next_faces(record):
        names = reach.reach_sizes(ctx.table, ctx.capture.get("items") or [], item, record)
        if names:
            ctx.doubt(names, "%s goes up to a face that Fusion joins with the faces next to it, and at other values "
                      "the hole may end on another face" % label(item))
    move = extents.plane_move(ctx, item, record, unit, "goes up to")
    return Quantity(measured) if move is None else Quantity(measured).plus(move)


def guard(ctx, feature):
    """Tell how far the variables behind the depth of a written hole may go: past zero Orca drills it the wrong way or
    not at all, without an error."""
    if "hole_depth" not in feature.expr:
        return
    name = feature.name
    limits.guard(ctx, [(feature, "hole_depth", "%s depth" % name)], lambda numbers: True,
                 "%s: the Orca copy cannot tell how far this may change before Orca drills the hole wrong" % name)
