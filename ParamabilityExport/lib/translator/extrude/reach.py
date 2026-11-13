"""How far an extrude goes: the distance of a side, where it starts and the length of a side that reaches to a face."""
from .. import gap_hints, kept_ranges, placement, reach_motion, values
from ...geometry import vec
from ..result import Refusal
from ..values import Quantity
from .common import LENGTH_TOL, UNREADABLE, parallel, sign_of


def distance_quantity(ctx, item, path, raw):
    """The length of one side. The recipe writes the absolute value, so a negative parameter is written negated."""
    return values.quantity(ctx, item, path, abs(raw), sign=sign_of(raw), absolute=True)


def start_shift(start, frame, ctx, item, plane_q):
    """Signed distance along the sketch normal from the sketch plane to where the extrude starts, as a Quantity that
    follows sizes (an offset parameter, or a face that moves with an earlier extrude); or a Refusal.

    An offset starts from the sketch plane and moves with it. A start on a face is measured from the plane too, so the
    plane's own move (`plane_q`, along the sketch normal) comes off the face's move: the written origin adds it back."""
    if start is None:
        return Refusal(UNREADABLE)
    kind = start.get("kind", "profilePlane")
    if kind == "profilePlane":
        return Quantity(0.0)
    if kind == "offset":
        if start.get("offset") is None:
            return Refusal(UNREADABLE)
        return values.quantity(ctx, item, "start.offset", float(start["offset"]))
    if kind == "fromEntity":
        values.pin(ctx, item, "start.offset", "it sets how far %s starts from its face" % item.get("name", "a step"))
        plane = start.get("plane")
        if not plane:
            return Refusal("This extrude starts from a surface that is not flat, which is not copied yet.",
                           cause=gap_hints.EXTRUDE_END_FACE)
        if not parallel(plane["normal"], frame["z"]):
            return Refusal("This extrude starts from a tilted surface, which is not copied yet.",
                           cause=gap_hints.EXTRUDE_END_FACE)
        shift = vec.dot(vec.sub(plane["point"], frame["origin"]), vec.unit(frame["z"]))
        moved = reach_motion.target_shift(ctx, item, "start", start, vec.unit(frame["z"]), "starts from")
        face = Quantity(shift) if moved is None or not moved.sized else moved.plus(shift - moved.n)
        if not plane_q.sized:
            return face
        if face.sized and (face.text == plane_q.text or face.core == plane_q.core):
            return Quantity(face.n - plane_q.n)
        return face.plus(plane_q.scaled(-1))
    return Refusal("This extrude starts in a way that is not copied yet.")


def sketch_origin(frame, shift_q):
    """The sketch origin moved along its normal by the start shift: a position that may follow sizes."""
    z = vec.unit(frame["z"])
    if not shift_q.sized:
        return placement.moved_along(placement.from_frame(frame), shift_q.n, z)["origin"]
    out = []
    for o, d in zip(frame["origin"], z):
        moved = shift_q.scaled(d).plus(float(o)) if abs(d) > 1e-12 else Quantity(float(o))
        out.append(moved.json() if moved.sized else round(moved.n, 9) + 0.0)
    return out


def reach_quantity(ctx, item, which, side, z, reach, offset, plane_q, shift_q):
    """The length of the side `which` that reaches to a face, as a Quantity that follows the face when it moves with
    sizes: the face's move less the moves of the sketch plane (`plane_q`, along the sketch normal) and of the start
    (`shift_q`, from the sketch plane). A face the copy cannot follow counts as staying (its sizes are marked)."""
    plain = Quantity(abs(reach) + float(offset))
    moved = reach_motion.target_shift(ctx, item, which, side, z) or Quantity(0.0)
    for part in (plane_q, shift_q):
        if part.sized and moved.sized and moved.core == part.core:
            moved = Quantity(moved.n - part.n)
        elif part.sized:
            moved = moved.plus(part.scaled(-1))
    if not moved.sized:
        return plain
    return moved.plus(reach - moved.n).scaled(sign_of(reach)).plus(float(offset))


def keep_reaches_positive(ctx, item, sides):
    """The lengths of the `sides` that follow a moving face must stay above zero. Where one would pass zero, the ranges
    are cut to where all of them stay positive, in one search, so the cut for one side does not shorten a range only
    the other side would need; their sizes are marked only when no cut keeps them."""
    reaching = [s for s in sides if s.get("reaches") and s["q"].sized]
    if all(values.stays_positive(ctx.table, s["q"]) for s in reaching):
        return
    why = "%s would reach past the face it starts from" % item.get("name", "a step")
    found = kept_ranges.holding_ranges(ctx.table, [(s["q"], 1) for s in reaching], LENGTH_TOL)
    if found:
        ctx.cut(found, why)
        return
    for side in reaching:
        if not values.stays_positive(ctx.table, side["q"]):
            ctx.doubt(side["q"].reads, why)
            side["q"] = Quantity(side["distance"])
