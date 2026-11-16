"""The recipe's caps on a sweep path and how the recipe output asks the shared path planner
(`design_model.paths.planner`) for a path: with these caps and free curves fitted as the recipe's spline segments.
A problem the planner finds becomes a refusal here. Pure: no Fusion imports."""
from ...design_model.paths.model import PathOptions
from ...design_model.problems import is_problem
from ...geometry import spline_fit
from ..result import Refusal

MAX_SEGMENTS = 64         # segments of a flat path (recipe cap)
MAX_POINTS = 64           # points of a corners path (recipe cap)


def options(**asked):
    """The `PathOptions` of a recipe sweep step: what the sweep asks (`asked`), the recipe's caps and its spline fit."""
    return PathOptions(max_segments=MAX_SEGMENTS, max_points=MAX_POINTS, splines=spline_fit, **asked)


def refusal(problem):
    """The Refusal of a problem of the shared layer (`design_model.problems.Problem`, of a path or a sweep): its words
    and its gap cause."""
    return Refusal(problem.words, cause=problem.cause)


def refused(found):
    """`found` with a path problem turned into its Refusal; anything else as it is."""
    return refusal(found) if is_problem(found) else found
