"""The measured elements of a pattern: which copies Fusion kept and where their frames sit.

An element frame is the transform of one copy from the original (`origin` and the three axes).
"""
from . import vec

FIT_TOL_MM = 1e-4
ROTATION_TOL = 1e-9


def is_identity_rotation(frame):
    return (vec.close(frame["x"], [1, 0, 0], ROTATION_TOL) and vec.close(frame["y"], [0, 1, 0], ROTATION_TOL)
            and vec.close(frame["z"], [0, 0, 1], ROTATION_TOL))


def is_identity(frame):
    return is_identity_rotation(frame) and vec.length(frame["origin"]) <= FIT_TOL_MM


def kept_elements(data):
    """Elements that are present and not suppressed, or None when the list was not read."""
    elements = data.get("elements") or []
    if not elements:
        return None
    left_out = set(data.get("suppressed_ids") or [])
    return [e for e in elements if not e.get("suppressed") and e.get("id") not in left_out]
