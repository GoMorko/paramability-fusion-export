"""Which pieces of a split by a solid body lie inside that body, when the reader could not say.

The reader tests each piece with the tool body (`read_split.inside`). A capture that lacks that answer for a piece of a
split into exactly two pieces is decided from the boxes: a piece whose box is not inside the tool's box cannot lie
inside it, and the two pieces lie on opposite sides. With more pieces the sides are not certain (a disc split by a tube
leaves a core, a ring inside the tube and an outer ring), so the reader's answers are the only ones used.
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
    """Whether the kept `piece` lies inside the `tool` body (True) or outside it (False), from the boxes and volumes of
    the tool and the two pieces (each with `box` and `volume`); None when they do not settle it or the split has more
    than two pieces. A tool of another component is not decided: its box is in other coordinates."""
    if len(others) != 1 or not isinstance(tool, dict) or tool.get("foreign") or not _boxed(tool):
        return None
    if not (_boxed(piece) and _boxed(others[0])):
        return None
    kept_inside = _may_lie_inside(piece, tool)
    kept_outside = _may_lie_inside(others[0], tool)
    if kept_inside == kept_outside:
        return None
    return kept_inside


def resolve(tool, piece, others):
    """Whether the kept `piece` lies inside the `tool` body, from the reader's `inside` answers, or None when they do
    not settle it.

    Every other piece must lie on the opposite side. A missing answer is filled in only for a split into two pieces:
    from the other piece's answer, else from the boxes (`decide`). The boxes never replace an answer the reader gave: a
    disagreement gives None."""
    inside = piece.get("inside")
    answers = [p.get("inside") for p in others]
    if inside is not None and None not in answers:
        return None if any(a is inside for a in answers) else inside
    if len(others) != 1:
        return None
    guess = decide(tool, piece, others)
    reader = inside if inside is not None else (None if answers[0] is None else not answers[0])
    if reader is None:
        return guess
    return None if guess is not None and guess != reader else reader
