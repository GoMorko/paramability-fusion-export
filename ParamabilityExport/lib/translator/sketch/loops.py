"""The recipe loops of a sketch outline as the translator asks for them: the shared loop writer
(`design_model.loops`) with each of its problems turned into a Refusal. The helpers that cannot fail (`flip_y`,
`segments_cost`, the caps) are read from `design_model.loops` itself."""
from ...design_model import loops as shared
from ...design_model.problem import is_problem
from ..result import Refusal

# The recipe's own words for two outlines it does not copy yet, by problem code. The other problems keep the shared
# sentence (`design_model.words`).
FACE_OUTLINE = "A flat face used as a sketch outline is not copied yet."
TEXT_OVERLAP = "This text has overlapping outlines, so it is not copied yet."
OWN_WORDS = {"face": FACE_OUTLINE, "text_overlap": TEXT_OVERLAP}


def _refused(found):
    """`found` with a problem of the loop writer turned into its Refusal; anything else as it is."""
    if not is_problem(found):
        return found
    return Refusal(OWN_WORDS.get(found.code, found.words), cause=found.cause)


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
