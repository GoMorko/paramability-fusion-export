"""What an emboss step measured, as facts for any destination: whether the change of the part matches the outline
area times the depth, and the face an outline that runs past its face is trimmed to. A `Problem`
(`design_model/problem.py`) says why the emboss cannot be read. Pure: it reads capture dicts only."""
from ..problem import Problem
from .. import words

ZERO_TOL = 1e-6
VOLUME_RELATIVE_TOL = 0.01
VOLUME_ABSOLUTE_TOL = 1e-3

UNMEASURED = Problem("unmeasured", words.EMBOSS_UNMEASURED)
NOT_MATCHING = Problem("not_matching", words.EMBOSS_NOT_MATCHING)
WRONG_WAY = Problem("wrong_way", words.EMBOSS_WRONG_WAY)


def _matches(change, expected):
    return abs(abs(change) - expected) <= VOLUME_RELATIVE_TOL * expected + VOLUME_ABSOLUTE_TOL


def volume_check(data, depth):
    """`(problem, trimmed)`: a problem when the measured change of the part is neither the outline area times the
    depth nor, with an end face smaller than the outline, the end face area times the depth, or goes the way the sign
    of the depth does not say; `trimmed` is True when Fusion kept only what lies on the face."""
    areas, before, after = data.get("areas"), data.get("volume_before"), data.get("volume_after")
    if (not isinstance(areas, list) or len(areas) != len(data["profiles"]) or any(a is None for a in areas)
            or before is None or after is None):
        return UNMEASURED, False
    expected = sum(areas) * abs(depth)
    change = after - before
    trimmed = False
    if not _matches(change, expected):
        end = data.get("end_area")
        if not (isinstance(end, (int, float)) and end < sum(areas) and _matches(change, end * abs(depth))):
            return NOT_MATCHING, False
        trimmed = True
    if (change > 0) != (depth > 0):
        return WRONG_WAY, False
    return None, trimmed


def trimmed_face(data):
    """The outline record of the lone face an emboss is trimmed to (written as `within`), or None."""
    faces, depth = data.get("faces"), data.get("depth")
    if (not isinstance(faces, list) or len(faces) != 1 or not isinstance(faces[0], dict)
            or not isinstance(depth, (int, float)) or abs(depth) <= ZERO_TOL or not data.get("profiles")):
        return None
    problem, trimmed = volume_check(data, depth)
    outline = faces[0].get("outline")
    return outline if problem is None and trimmed and isinstance(outline, dict) else None
