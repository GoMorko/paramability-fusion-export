"""Planes, axes and faces of the part's own component that a step writes as numbers.

Orca writes a split plane, a mirror plane, a turning axis, the axis of a Move and the cylinder a thread is cut on
where the capture measured them. A size that may move one of them cannot follow there, so it is marked with the
reason (`mark`), and it never reads as unused or as following. Which sizes may move such a record is a fact of the
shared layer (`design_model.reach.reference_sizes`). Geometry of another component is marked by
`other_components.mark_refs`.
"""
from ..design_model import reach
from ..design_model import words as shared


def _noun_type(record):
    """The Fusion type that names the record in the reason: its own, else a plane or an axis by its shape."""
    return record.get("entity_type") or ("ConstructionAxis" if "dir" in record else "ConstructionPlane")


def mark(ctx, item, record, what):
    """Mark the sizes that may move `record`, which the step `item` uses as a place Orca keeps where it is now.
    `what` words what the step does with it ("cuts along", "mirrors across", "turns about")."""
    if ctx.table is None or not isinstance(record, dict):
        return
    names = reach.reference_sizes(ctx.table, ctx.capture.get("items") or [], item, record)
    if names:
        phrase = shared.ref_phrase(item, {"type": _noun_type(record), "own": True}, what)
        ctx.doubt(names, shared.kept_in_place(phrase))


def on_face(item, what):
    """The reason of the sizes that may move a face of the part the step `item` uses: `what` words what it does there
    ("is cut on")."""
    return shared.kept_in_place(shared.ref_phrase(item, {"type": "BRepFace", "own": True}, what))


def mark_faces(ctx, item, why):
    """Mark with `why` the sizes that may move or change the faces of the part that the step `item` uses where Orca
    keeps them as they are now (`reach.any_face_sizes`): every size an item of the part's component reads before the
    step."""
    if ctx.table is None:
        return
    names = reach.any_face_sizes(ctx.table, ctx.capture.get("items") or [], item)
    if names:
        ctx.doubt(names, why)
