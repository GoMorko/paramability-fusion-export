"""Pipe features (adsk.fusion.PipeFeature) as plain dicts (agent-docs/capture-format.md).

Before the item: the section (type, size, hollow and wall thickness), how much of the path the pipe covers, the
operation and the path as curves in the target component's coordinates (`read_sweep.path_record`). Fusion gives the
path only while the marker stands before the pipe, which is where this reader runs. After the item: a point and
normal on each start and end face the pipe made.

Each member is read on its own: one that cannot be read becomes null and the translator leaves the pipe out.
"""
from . import read_geometry as geo
from .param_refs import Params, with_params
from .read_solid import operation_of
from .read_sweep import faces_made, path_record

# "Circular", "Square" and "Triangular" in the PipeSectionTypes names.
_SECTIONS = [("circular", "circular"), ("square", "square"), ("triangular", "triangular")]


def _length(read):
    """A model parameter's value in mm, or null."""
    return geo.safe(lambda: geo.length(read()), None)


def _fraction(read):
    """A unitless model parameter's value, or null."""
    return geo.safe(lambda: round(float(geo.value_of(read())), 6) + 0.0, None)


def _distance_two(feature, data):
    """`distance_two`: null when Fusion gives none (an open path has none), else its value. A member that raises,
    or a value that cannot be read, sets `distance_two_unread`."""
    try:
        member = feature.distanceTwo
    except Exception:
        member, data["distance_two_unread"] = None, True
    if member is None:
        data["distance_two"] = None
        return
    data["distance_two"] = _fraction(lambda: member)
    if data["distance_two"] is None:
        data["distance_two_unread"] = True


def pipe_before(feature, ctx):
    params = Params()
    params.add("section_size", lambda: feature.sectionSize)
    params.add("section_thickness", lambda: feature.sectionThickness)
    params.add("distance_one", lambda: feature.distanceOne, "scalar")
    params.add("distance_two", lambda: feature.distanceTwo, "scalar")
    hollow = geo.safe(lambda: bool(feature.isHollow), None)
    data = {
        "operation": geo.safe(lambda: operation_of(feature.operation), None),
        "participants": geo.safe(lambda: geo.body_refs(feature.participantBodies, ctx), None),
        "target_box_before": ctx.target_box(),
        "section": geo.safe(lambda: geo.pick_by_text(
            geo.enum_name(feature.sectionType, "PipeSectionTypes"), _SECTIONS, "other"), None),
        "section_size": _length(lambda: feature.sectionSize),
        "hollow": hollow,
        "section_thickness": _length(lambda: feature.sectionThickness) if hollow else None,
        "distance_one": _fraction(lambda: feature.distanceOne),
        "path": geo.safe(lambda: path_record(feature.path, ctx), None),
    }
    _distance_two(feature, data)
    return with_params(data, params.found)


def pipe_after(feature, ctx, data):
    return {"faces_after": {"start": faces_made(lambda: feature.startFaces, ctx),
                            "end": faces_made(lambda: feature.endFaces, ctx)}}


# type name -> (before, after)
READERS = {"PipeFeature": (pipe_before, pipe_after)}
