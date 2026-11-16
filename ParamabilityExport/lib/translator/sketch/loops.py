"""The recipe loops of a sketch outline as the translator asks for them: the shared loop writer
(`design_model.loops`) with each of its problems turned into a Refusal. The helpers that cannot fail (`flip_y`,
`segments_cost`, the caps and the text words) are read from `design_model.loops` itself."""
from ...design_model import loops as shared
from ...design_model.problem import is_problem
from ..result import Refusal


def _refused(found):
    """`found` with a problem of the loop writer turned into its Refusal; anything else as it is."""
    return Refusal(found.words, cause=found.cause) if is_problem(found) else found


def loop_of(curves, sketch="", text=False):
    """One recipe loop dict of a profile loop's capture curves, or a Refusal (`design_model.loops.loop_of`)."""
    return _refused(shared.loop_of(curves, sketch, text))


def outline_refusal(profile):
    """A Refusal when a capture profile record is not a drawn sketch outline, else None
    (`design_model.loops.outline_problem`)."""
    return _refused(shared.outline_problem(profile))


def profile_loops(profile):
    """One capture profile's `(outer, inners)` recipe loops, or a Refusal (`design_model.loops.profile_loops`)."""
    return _refused(shared.profile_loops(profile))
