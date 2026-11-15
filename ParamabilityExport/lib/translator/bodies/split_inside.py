"""Which pieces of a split by a solid body lie inside that body, when the reader could not say.

The reader tests each piece with the tool body (`read_split.inside`). A capture that lacks that answer is decided from
the boxes: a piece whose box is not inside the tool's box cannot lie inside it. The pieces of such a split lie on
opposite sides, so one side is possible for the kept piece only when the boxes allow it and rule the other one out.
"""
from ...geometry import vec

# A box may reach this far (mm) past the tool's box and still count as inside it.
BOX_TOL_MM = 0.01
# A piece inside the tool is no larger than the tool, within this share of its volume.
VOLUME_RELATIVE = 1e-3


def _box_inside(inner, outer):
    """True when the box `inner` lies within the box `outer`, give or take BOX_TOL_MM."""
    return all(lo >= olo - BOX_TOL_MM and hi <= ohi + BOX_TOL_MM
               for lo, hi, olo, ohi in zip(inner["min"], inner["max"], outer["min"], outer["max"]))


def _may_lie_inside(piece, tool):
    """False when the piece's box or volume shows it cannot lie inside the tool body."""
    if not (isinstance(piece.get("box"), dict) and _box_inside(piece["box"], tool["box"])):
        return False
    volume, held = piece.get("volume"), tool.get("volume")
    return not (isinstance(volume, (int, float)) and isinstance(held, (int, float))
                and volume > held * (1.0 + VOLUME_RELATIVE))


def _boxed(record):
    box = record.get("box") if isinstance(record, dict) else None
    return isinstance(box, dict) and all(isinstance(box.get(k), list) and len(box[k]) == 3 for k in ("min", "max"))


def decide(tool, piece, others):
    """Whether the kept `piece` lies inside the `tool` body (True) or outside it (False), from the boxes and volumes
    of the tool, the piece and the other pieces (each with `box` and `volume`); None when they do not settle it. A tool
    of another component is not decided: its box is in other coordinates."""
    if not isinstance(tool, dict) or tool.get("foreign") or not _boxed(tool) or not _boxed(piece):
        return None
    if not all(_boxed(p) for p in others) or not others:
        return None
    kept_inside = _may_lie_inside(piece, tool)
    kept_outside = all(_may_lie_inside(p, tool) for p in others)
    if kept_inside == kept_outside:
        return None
    return kept_inside
