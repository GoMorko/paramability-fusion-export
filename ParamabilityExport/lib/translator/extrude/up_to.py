"""A side of an extrude up to a tilted or curved face of the part, written as `extent: { upTo: { near: [p] } }`.

The app grows the outline along the sketch normal until it meets the face that the point `p` picks: a flat face counts
as its whole plane, a curved face as it is (the face must then lie in front of the whole outline, else the app
refuses the step). A point off the face picks another face, which gives a wrong copy, so the side is left out when
that can happen:

- the face lies on another body, or a step left out before this one may have made it;
- a size that the person can change may move the face (`design_model.reach.reach_sizes`), and no step written before
  places the point on what it built (`faces.follow.placed_point`).

The app has no taper and no offset past the face for such a side, and it extends a flat face to its whole plane. So a
taper and an offset leave the side out too. Fusion may also stop at the faces next to a flat face (`chained` is not
false); the side is then copied only when every outline lands on the face itself (`outline_on_face`), and the sizes
that may carry it past the face are marked (`keep_on_face`, also for a side up to a face square to the sketch). A thin
extrude never gets here (`faces/thin_wall.prepare` refuses it).
"""
from ...capture_model import gap_hints
from ...design_model.reach import reach_sizes
from ...design_model.steps import extrude as dm
from .. import notes, values
from ..faces import follow, picks
from ..result import Refusal
from .side import RecipeSide
from .taper import taper_quantity

TAPER = "An extrude with a taper up to a tilted or curved face is not copied yet."
OFFSET = "An extrude that ends at a distance from a tilted or curved face is not copied yet."
OTHER_BODY = "This extrude ends on a tilted or curved face of another body, which is not copied."
MOVES = ("The tilted or curved face this extrude ends on may move when the sizes change, and the copy cannot "
         "follow it.")


def _refusal(text):
    return Refusal(text, cause=gap_hints.EXTRUDE_END_FACE)


def _earlier_gaps(ctx, item):
    """The gaps of this walk before `item`: any of them may have made the face."""
    return [gap for gap in ctx.gaps if gap.index is not None and gap.index < item.get("index", 0)]


def keep_on_face(ctx, item, record):
    """A side that ends on a face Fusion may chain to the faces next to it lands on that face alone at the measured
    sizes; other values may carry the outline past it. The sizes that may move the face or the outline are marked."""
    if not dm.joins_next_faces(record):
        return
    names = reach_sizes(ctx.table, ctx.timeline, item, record)
    if names:
        ctx.doubt(names, "%s ends on a face that Fusion joins with the faces next to it, and at other values its "
                  "outline may reach past that face" % item.get("name", "a step"))


def up_to_side(ctx, item, data, side, z):
    """The `RecipeSide` of an UP_TO side (`design_model.steps.extrude`), or a Refusal. `z` is the unit sketch
    normal."""
    record = side.reach.record
    if side.taper:
        return _refusal(TAPER)
    if side.offset:
        return _refusal(OFFSET)
    if side.reach.plane is not None and dm.joins_next_faces(record) and dm.outline_on_face(data, record, z) is not True:
        found = dm.problem(dm.CHAINED, side.which)
        return Refusal(found.words, cause=found.cause)
    body = record.get("body")
    if not body or not ctx.is_target(body):
        return _refusal(OTHER_BODY)
    gaps = _earlier_gaps(ctx, item)
    if gaps:
        return Refusal(notes.picks_gap_reason([gap.name for gap in gaps], False), [gap.id for gap in gaps],
                       cause=gap_hints.AFTER_GAP)
    point = record["face_point"]
    if reach_sizes(ctx.table, ctx.timeline, item, record):
        near = follow.placed_point(ctx, item, point)
        if near is None:
            return _refusal(MOVES)
    else:
        near = picks.face_points([{"point": point}])[0]
    if side.reach.plane is not None:
        keep_on_face(ctx, item, record)
    taper_quantity(ctx, item, side.taper_path, 0.0)
    values.pin(ctx, item, side.offset_path, "it sets how far %s reaches" % item.get("name", "a step"))
    return RecipeSide({"upTo": {"near": [near]}}, side.sign, None, 0.0, adjusts=True, read=side)
