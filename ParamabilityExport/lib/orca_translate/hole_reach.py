"""The depth of a hole that goes up to a face or plane ("To" extent), for the Orca copy.

Orca's hole has a depth, or goes through all; its "up to face" names a face by Orca's own numbering, which the copy
cannot know. So the depth is a distance, worked out as the length of an extrude up to a face is (`extents.reach`):

- The face or plane must be flat and square to the hole's axis, and the depth is the measured one, from each hole's
  position to its flat end, which must lie on the plane of the face (`hole_facts.to_face_depth`, shared with the
  Paramability copy). A tilted or curved face, a hole that ends elsewhere, and a body, a point or a face of another
  component (which the Orca copy does not place) leave the hole out.
- The depth follows the sizes that move the face where the extrude logic follows them (`extents.plane_move`: an
  offset plane with its own distance and its base, an end face of a copied extrude). Orca keeps the plane the hole
  sits on as a number, so the depth is the measured one plus how far the face moves along the drilling direction.
  Sizes that may move the face in any other way keep the measured depth, and those sizes are marked.
- A face Fusion may join with the faces next to it (`chained` true or not read) may end the hole elsewhere at other
  sizes, so the sizes that may move it are marked (`hole_facts.end_face_sizes`).
- The depth must stay above zero, and above the depth of a counterbore or countersink (`guard`, also for a hole of a
  given depth with a counterbore or countersink).
"""
import math

from ..capture_model import gap_hints
from ..design_model import words
from ..design_model.problem import Problem
from ..design_model.steps import extrude as dm, hole as hole_facts
from ..design_model.values import Quantity
from . import extents, limits
from .skip import Skip
from .tools import label


def _face_skip(record):
    """The Skip for a face or plane the copy cannot use as the end of a hole, or None."""
    if record.get("foreign"):
        return Skip("This hole goes up to a face or plane of another component, which is not copied.",
                    gap_hints.OTHER_COMPONENT)
    if record.get("entity_type") not in hole_facts.FLAT_TARGETS or hole_facts.target_plane(record) is None:
        return Skip.of(Problem("holeFaceNotFlat", words.HOLE_FACE_NOT_FLAT, gap_hints.EXTRUDE_END_FACE))
    return None


def depth(ctx, item, data, unit):
    """The depth (a `Quantity`, mm along the unit drilling direction `unit`) of the hole step `data` whose extent goes
    up to a face or plane, or a Skip."""
    record = data.get("extent") or {}
    refused = _face_skip(record)
    if refused is not None:
        return refused
    measured = hole_facts.to_face_depth(data, unit)
    if isinstance(measured, Problem):
        return Skip.of(measured)
    names = hole_facts.end_face_sizes(ctx.table, ctx.capture.get("items") or [], item, record)
    if names:
        ctx.doubt(names, "%s goes up to a face that Fusion joins with the faces next to it, and at other values "
                  "the hole may end on another face" % label(item))
    move = extents.plane_move(ctx, item, record, unit, "goes up to")
    return Quantity(measured) if move is None else Quantity(measured).plus(move)


def _recess_depth(numbers, style):
    """How deep the counterbore (`style` 1: `numbers` are the depth and the counterbore depth) or the countersink
    (`style` 2: the depth, the hole diameter, the countersink diameter and its angle in degrees) of a hole reaches."""
    if style == 1:
        return numbers[1]
    half = math.tan(math.radians(numbers[3]) / 2.0)
    return (numbers[2] - numbers[1]) / 2.0 / half if half > 0 else math.inf


_RECESS_FIELDS = {1: ("hole_cbore_depth",), 2: ("hole_diameter", "hole_csink_diameter", "hole_csink_angle")}
# How `holes.hole` words each field where it binds it (`Context.bind`), after the feature's name.
_WHERE = {"hole_depth": "depth", "hole_cbore_depth": "counterbore depth", "hole_diameter": "diameter",
          "hole_csink_diameter": "countersink diameter", "hole_csink_angle": "countersink angle"}


def guard(ctx, feature):
    """Tell how far the variables behind the depth of a written hole may go: past zero Orca drills it the wrong way or
    not at all, and with a counterbore or countersink (`hole_style` 1 or 2) the depth must stay above how deep that
    reaches, else the hole is only the recess. Orca gives no error in either case."""
    style = feature.hole_style if feature.hole_style in _RECESS_FIELDS else 0
    fields = ["hole_depth"] + list(_RECESS_FIELDS.get(style, ()))
    if not any(f in feature.expr for f in fields):
        return
    name = feature.name

    def ok(numbers):
        return not style or limits.stop(numbers[0] > _recess_depth(numbers, style) + dm.LENGTH_TOL,
                                        limits.HOLE_SHALLOW)

    limits.guard(ctx, [(feature, f, "%s %s" % (name, _WHERE[f])) for f in fields], ok,
                 "%s: the Orca copy cannot tell how far this may change before Orca drills the hole wrong" % name)
