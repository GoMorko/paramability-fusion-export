"""The measured elements of a pattern: which copies Fusion kept and where their frames sit.

An element frame is the transform of one copy from the original (`origin` and the three axes). Fusion gives it in
assembly space; `in_component` carries the frames into the frame of the component the recipe is written in, and drops
copies that sit exactly on an earlier one. `read_in_component` does the same for the copies a probe state read.
"""
from ..capture_model import tool_items
from ..geometry import vec

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


def _carried(place, frame):
    """The transform `frame` (assembly space) seen in the component frame `place` (component to assembly)."""
    def apply(m, v):
        return [sum(m[name][i] * v[k] for k, name in enumerate("xyz")) for i in range(3)]

    def back(w):
        return [vec.dot(place[name], w) for name in "xyz"]

    axes = {name: back(apply(frame, place[name])) for name in "xyz"}
    shifted = vec.add(apply(frame, place["origin"]), vec.sub(frame["origin"], place["origin"]))
    return dict(axes, origin=back(shifted))


def _same_frame(a, b):
    return (vec.close(a["origin"], b["origin"], FIT_TOL_MM)
            and all(vec.close(a[name], b[name], ROTATION_TOL * 1e3) for name in "xyz"))


def read_in_component(read, ctx):
    """A probe read of a pattern (`{ count, elements }`) with its element frames in the frame of the component the
    walk builds in, like the captured ones."""
    place = tool_items.component_frame(ctx)
    if place is None or not read.get("elements"):
        return read
    return dict(read, elements=[dict(e, frame=_carried(place, e["frame"])) for e in read["elements"]])


def in_component(item, ctx, merge=False):
    """`item` with its element frames in the frame of the component the walk builds in. With `merge`, copies that sit
    exactly on an earlier one are dropped (a direction with a distance of zero makes such copies). The item itself
    when it has no elements."""
    data = item.get("data") or {}
    elements = data.get("elements")
    if not elements:
        return item
    place = tool_items.component_frame(ctx)
    carried, kept = [], []
    for element in elements:
        frame = element["frame"] if place is None else _carried(place, element["frame"])
        if merge and any(_same_frame(frame, other["frame"]) and element.get("suppressed") == other.get("suppressed")
               for other in kept):
            continue
        kept.append(dict(element, frame=frame))
    return dict(item, data=dict(data, elements=kept))
