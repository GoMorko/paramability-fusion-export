"""The plain words of the problems of a sweep path (`problems.Problem.words`). Pure. `problem` gives the record of
one of these texts with its code."""
from ...capture_model import gap_hints
from ..problem import Problem

TURNS_BACK = "The outline keeps one direction along a path that turns back past its plane, which cannot be built."
UNREADABLE = "A curve of the path of this sweep could not be read closely enough to copy."
UNKNOWN_CURVE = "The path of this sweep uses a kind of curve that is not copied yet."
NOT_ONE_CHAIN = "The curves of the path of this sweep do not join end to end into one line."
CLOSED = "The path of this sweep is closed, but its curves do not make one closed line."
CLOSED_3D = "Sweeps along a closed path that bends in 3D are not copied yet."
CLOSED_AT_CORNER = "The outline of this sweep sits on a sharp corner of its closed path."
CLOSED_NOT_SMOOTH = ("The closed path of this sweep cannot be copied closely enough to run smoothly through the "
                     "place where its outline sits.")
CLOSED_TAPER = "Tapered sweeps along a closed path are not copied."
CLOSED_PARALLEL = "Sweeps that keep their outline in one direction along a closed path are not copied."
BOTH_SIDES = "This sweep runs to both sides of its outline, which is not copied yet."
OFF_PLANE = "The path of this sweep does not start on the plane of its outline."
NOT_SQUARE = "The outline is not square to the path at its start."
TURNED_ROUND = "The path of this sweep would leave its outline the other way round."
SHARP_CORNER = "The path of this sweep has a sharp corner."
CORNER_TOO_TIGHT = ("A sharp corner of the path of this sweep is too close to the next one for its outline: the "
                    "outline needs %.2f mm of straight path there and has %.2f mm.")
BENDS_3D = "The path of this sweep bends in 3D in a way that is not copied yet."
TOO_MANY = "The path of this sweep has too many parts to copy."
CROSSES = "The path of this sweep crosses itself."
OVERLAP = ("Two parts of the path pass %.2f mm apart, but the outline reaches %.2f mm from the path, "
           "so the sweep would run into itself.")
REACHES_BEND = "The outline reaches %.2f mm from the path, but the path bends in a radius of %.2f mm."
TOO_COMPLEX = "The path of this sweep has a curve that is too complex to copy closely enough."
NOT_SKETCH = "The path of this sweep is not made of sketch lines or edges."

# The code of each text, and the gap cause of the texts that have a tip.
_CODES = {
    TURNS_BACK: "turns_back", UNREADABLE: "unreadable", UNKNOWN_CURVE: "unknown_curve", NOT_ONE_CHAIN: "not_one_chain",
    CLOSED: "closed", CLOSED_3D: "closed_3d", CLOSED_AT_CORNER: "closed_at_corner",
    CLOSED_NOT_SMOOTH: "closed_not_smooth", CLOSED_TAPER: "closed_taper", CLOSED_PARALLEL: "closed_parallel",
    BOTH_SIDES: "both_sides", OFF_PLANE: "off_plane", NOT_SQUARE: "not_square", TURNED_ROUND: "turned_round",
    SHARP_CORNER: "sharp_corner", CORNER_TOO_TIGHT: "corner_too_tight", BENDS_3D: "bends_3d", TOO_MANY: "too_many",
    CROSSES: "crosses", OVERLAP: "overlap", REACHES_BEND: "reaches_bend", TOO_COMPLEX: "too_complex",
    NOT_SKETCH: "not_sketch",
}


def problem(text, *numbers, cause=None):
    """The `Problem` of one of the texts above, with the numbers its text takes."""
    return Problem(_CODES[text], text % numbers if numbers else text, cause)


def sharp_corner(text=SHARP_CORNER):
    """A sharp corner (`SHARP_CORNER` or `CLOSED_AT_CORNER`) with its tip."""
    return problem(text, cause=gap_hints.SHARP_CORNER)
