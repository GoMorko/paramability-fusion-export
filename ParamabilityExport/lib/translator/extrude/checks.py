"""Checks of the planned extrude against what Fusion measured: its length, its side walls and the volume it made.
The facts come from the shared reader (`design_model/steps/extrude.py`); this module turns them into refusals."""
from dataclasses import replace

from ...design_model.steps import extrude as dm
from ...design_model.steps import extrude_checks as dmc
from ...design_model import words as shared
from ..result import Refusal


def check_measured_length(plan, data, start, z, combine):
    """Refuse when the measured end face is not where the planned lengths put it (`end_check`); None when it agrees
    or is unknown. `start` is where the extrude starts and `z` the unit sketch normal.

    A side of a cut that ends past the part makes no end face of its own; the face Fusion lists on that side is then a
    wall the cut went through, nearer than the side's end. Such a face is accepted only when the side it lies on ends
    past the whole part (`dmc.passes_box`): a side that passes says nothing about a face on the other side of the
    sketch, where the cut may end inside material.
    """
    reads = [entry.read for entry in plan if entry.read is not None]
    found = dmc.end_check(reads)
    if found is None or found.fact == dm.AT_END:
        return None
    if found.fact == dm.SHORT and combine == "cut" and dmc.passes_box(
            data.get("target_box_before"), start, z, found.way, found.length):
        return None
    return Refusal(shared.END_DIFFERS)


def facts_of(plan):
    """The sides of `plan` as the shared reader gave them (`RecipeSide.read`), for its measured checks, with the
    direction the plan settled on (a cut through all may turn to the side where its outlines meet the part)."""
    return [entry.read if entry.read.sign == entry.sign else replace(entry.read, sign=entry.sign) for entry in plan]


def _refusal(found):
    return None if found is None else Refusal(found.words, cause=found.cause)


def check_taper(plan, data, operation, outlines):
    """Refuse a taper whose sign disagrees with the measured side walls (or, for one outline, the end face area),
    or that cannot be measured (`design_model.steps.extrude_checks.taper_problem`). `operation` is Fusion's."""
    return _refusal(dmc.taper_problem(facts_of(plan), data, operation, outlines))


def volume_refusal(data, plan, operation, profiles, thin):
    """Refuse when the part Fusion made from text or spline outlines is not the outline area times the length
    (`design_model.steps.extrude_checks.volume_problem`)."""
    return _refusal(dmc.volume_problem(data, facts_of(plan), operation, profiles, thin))
