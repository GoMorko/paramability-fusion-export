"""Sketch frames to recipe placements.

A recipe placement is `{ origin, normal, xDir }`; the sketch y axis is `normal x xDir`. Flipping the normal while
keeping `xDir` mirrors the sketch y axis, so the loops of a flipped placement go through `loops.flip_y`.
"""
from ..geometry import vec


def _clean(values):
    return [round(v, 9) + 0.0 for v in values]


def from_frame(frame):
    """Capture frame ({origin, x, y, z}) to a recipe placement {origin, normal, xDir}."""
    return {
        "origin": _clean(frame["origin"]),
        "normal": _clean(frame["z"]),
        "xDir": _clean(frame["x"]),
    }


def reversed_of(placement):
    """The same plane seen from the other side: normal negated, xDir and origin kept."""
    return {
        "origin": list(placement["origin"]),
        "normal": _clean(vec.scale(placement["normal"], -1)),
        "xDir": list(placement["xDir"]),
    }


def moved_along(placement, distance, direction=None):
    """The placement with its origin moved by `distance` along `direction` (default: its own normal)."""
    step = vec.scale(direction if direction is not None else placement["normal"], distance)
    return {
        "origin": _clean(vec.add(placement["origin"], step)),
        "normal": list(placement["normal"]),
        "xDir": list(placement["xDir"]),
    }
