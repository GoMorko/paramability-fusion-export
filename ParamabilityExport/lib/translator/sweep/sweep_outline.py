"""The one outline of a sweep as the recipe takes it: a single sketch profile with a readable place. The points, loops
and centroid of an outline are read in `design_model.steps.sweep`."""
from ..result import Refusal
from ..sketch import loops
from .sweep_limits import FACE_OUTLINE, SEVERAL_OUTLINES, UNREADABLE


def outline_of(data):
    """The one outline profile, or a Refusal."""
    profiles = data.get("profiles")
    if not isinstance(profiles, list):
        return Refusal(UNREADABLE)
    if not profiles:
        return Refusal("This sweep has no sketch outline.")
    if len(profiles) > 1:
        return Refusal(SEVERAL_OUTLINES)
    profile = profiles[0]
    if not isinstance(profile, dict):
        return Refusal(UNREADABLE)
    if profile.get("face"):
        return Refusal(FACE_OUTLINE)
    refusal = loops.outline_refusal(profile)
    if refusal is not None:
        return refusal
    if not isinstance(profile.get("frame"), dict):
        return Refusal("A sketch outline has no readable position.")
    return profile
