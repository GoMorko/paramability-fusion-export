"""The tolerances, the combine table and the small sign helpers that the extrude modules share."""
from .. import vec


PARALLEL_TOL = 1e-9
SIGN_TOL = 1e-9
LENGTH_TOL = 1e-3
SAMPLE_INSET = 0.02
COMBINE = {"join": "add", "cut": "cut", "intersect": "intersect", "newBody": "new"}
UNREADABLE = "A setting of this extrude could not be read from Fusion."


def sign_of(value):
    return -1 if value < 0 else 1


def parallel(a, b):
    return vec.length(vec.cross(vec.unit(a), vec.unit(b))) <= PARALLEL_TOL
