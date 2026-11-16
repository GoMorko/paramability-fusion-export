"""Checks of the planned extrude against what Fusion measured: its length, its side walls and the volume it made.
The facts come from the shared reader (`design_model/steps/extrude.py`); this module turns them into refusals."""
from ...design_model.steps import extrude as dm
from ...design_model.values import Quantity
from ...geometry import vec
from ..result import Refusal
from .common import LENGTH_TOL
from .taper import FUSION_TAPER_SIGN


def _beyond_part(box, start, direction, length):
    """True when a cut of `length` from `start` along `direction` ends past the whole box."""
    if not box:
        return False
    lo, hi = box["min"], box["max"]
    corners = ([hi[0] if i & 1 else lo[0], hi[1] if i & 2 else lo[1], hi[2] if i & 4 else lo[2]] for i in range(8))
    return length > max(vec.dot(vec.sub(c, start), direction) for c in corners) + LENGTH_TOL


def check_measured_length(plan, data, start, z, combine):
    """Refuse when the measured end face is not where the planned lengths put it (`end_check`); None when it agrees
    or is unknown. `start` is where the extrude starts and `z` the unit sketch normal.

    A side of a cut that ends past the part makes no end face of its own; the face Fusion lists then is a wall the cut
    went through, nearer than the planned end on either side. Such a face is accepted when a side passes the whole
    part (not for a symmetric cut).
    """
    reads = [entry.read for entry in plan if entry.read is not None]
    found = dm.end_check(reads)
    if found is None or found.fact == dm.AT_END:
        return None
    box = data.get("target_box_before")
    if found.fact == dm.SHORT and combine == "cut" and found.side.kind != dm.SYMMETRIC and any(
            side.length is not None and _beyond_part(box, start, vec.scale(z, side.sign), side.length.n)
            for side in reads):
        return None
    return Refusal("The measured end of this extrude does not match its length, so it is not copied.")


def facts_of(plan):
    """The recipe sides of `plan` as the shared layer's `SidePlan`s, for its measured checks: the direction, the
    length and Fusion's taper of each."""
    return [dm.SidePlan(dm.SYMMETRIC if e.extent == "symmetric" else dm.DISTANCE, "", e.sign,
                        None if e.distance is None else Quantity(e.distance), FUSION_TAPER_SIGN * (e.taper or 0.0))
            for e in plan]


def _refusal(found):
    return None if found is None else Refusal(found.words, cause=found.cause)


def check_taper(plan, data, operation, outlines):
    """Refuse a taper whose sign disagrees with the measured side walls (or, for one outline, the end face area),
    or that cannot be measured (`design_model.steps.extrude.taper_problem`). `operation` is Fusion's."""
    return _refusal(dm.taper_problem(facts_of(plan), data, operation, outlines))


def volume_refusal(data, plan, operation, profiles, thin):
    """Refuse when the part Fusion made from text or spline outlines is not the outline area times the length
    (`design_model.steps.extrude.volume_problem`)."""
    return _refusal(dm.volume_problem(data, facts_of(plan), operation, profiles, thin))
