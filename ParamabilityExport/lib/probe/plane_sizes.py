"""The sizes the probe tries because they may move the plane a followed sketch sits on, the face or plane an extrude
starts from or reaches to, or a flat face a step uses as its outline. Pure: no Fusion imports.

A sketch drawn on a face, or on a construction plane built on the part (offset from a face, at an angle to one,
through an edge, a midplane, tangent to a face, a chain of such planes), moves when the geometry under it moves. The
probe reads the sketch frame at every state, so the plane's move is measured and fitted like any sketch value once a
size that may move it is tried. A face or plane of the part that an extrude starts from or reaches to is read again
at every state as well (`translator.sizes.moving_reaches`, `plan.refs`). A size that only feeds the length of an
earlier step gets no row of its own (`plan.probe_rows`), so without this list the plane or face would stay where the
capture has it. A face used as an outline may change with every size read before its step (`plan.outline_face`). A
revolve axis on a sketch line is read at every state too, so the sizes that may move or turn that line are tried
(`axis_sizes`).
"""
from ..design_model.reach import placement_driven, reach_driven, reach_sizes, reference_sizes
from .plan.covered import AXIS, FACE, scan


def plane_driven(capture, table):
    """Fusion names of the ticked sizes that may move the plane of a covered sketch outline or sweep path
    (`translator.sizes.placement_sizes`), or a face or plane an extrude starts from or reaches to
    (`translator.sizes.reach_sizes`), or a face a step uses as its outline, in table order."""
    targets = scan(capture).targets
    records = [(t["item"], t.get("profile") or t.get("path")) for t in targets if t["kind"] in ("profile", "path")]
    found = set(placement_driven(capture, table, records)) | set(reach_driven(capture, table))
    for names in face_sizes(capture, table).values():
        found |= names
    found |= axis_sizes(capture, table)
    return [name for name in table.ticked if name in found]


def axis_sizes(capture, table):
    """Fusion names of the ticked sizes that may move or turn a revolve axis on a line of a sketch of the part
    (`design_model.reach.reference_sizes`): the line's sketch, the plane it sits on and geometry projected into it.
    The probe reads the line at every try, so a size tried here is followed."""
    timeline = capture.get("items") or []
    found = set()
    for target in scan(capture).targets:
        if target["kind"] == AXIS:
            found |= set(reference_sizes(table, timeline, {"index": target["item"]}, target["axis"]))
    return found


def face_sizes(capture, table):
    """`{face key: Fusion names}` of the ticked sizes that may change each face a step uses as its outline: every size
    an item reads before that step (`translator.sizes.reach_sizes`)."""
    timeline = capture.get("items") or []
    return {t["sketch_token"]: set(reach_sizes(table, timeline, {"index": t["item"]}, t["profile"]))
            for t in scan(capture).targets if t["kind"] == FACE}
