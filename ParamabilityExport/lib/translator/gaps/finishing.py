"""Whether a missing step only finishes surfaces, the `finishing` flag of a gap.

A finishing step changes neither the size of the part nor which bodies exist, so the app may show the copy as the part
when only such steps are missing. Which types count is in the step kind table (`StepType.finishing`); it matches the
rule the Paramability app applies to older gaps files.
"""
from ...capture_model import step_kinds


def is_finishing(step_type, data):
    """True for a round, a bevel, a draft, an emboss or deboss, and a thread drawn as a cosmetic thread (its data says
    `modeled` is false). Any other type, and a thread whose data does not say so, can change the part's size."""
    spec = step_kinds.step_type(step_type)
    found = spec.finishing if spec is not None else None
    if found == step_kinds.FINISHING_UNMODELED:
        return isinstance(data, dict) and data.get("modeled") is False
    return found == step_kinds.FINISHING_ALWAYS
