"""The destination-neutral reading of patterns and mirrors: the copies Fusion kept and where they sit.

An element frame is the transform of one copy from the original (`origin` and the three axes). Fusion gives it in
assembly space; `data_in_component` carries the frames (and the centres of the faces of each copy and of the original,
`pattern_places`) in the data of a pattern into the frame of the component the steps are written in, and drops copies
that sit exactly on an earlier one. `read_in_component` does
the same for the copies a probe state read. `solve_lattice` gives the grid index of a copy, `reach` the steps a
symmetric direction runs each way, and `mirror_plane` the plane of a mirror. `repeated_items` gives the timeline
items a pattern or a mirror repeats. What a copy does about a size, and how a copy is written, stay with
the destination.
"""
from ...capture_model import step_kinds
from ...geometry import vec
from ...package.numbers import round9

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


def carried_frame(place, frame):
    """The transform `frame` (assembly space) seen in the component frame `place` (component to assembly)."""
    def apply(m, v):
        return [sum(m[name][i] * v[k] for k, name in enumerate("xyz")) for i in range(3)]

    def back(w):
        return [vec.dot(place[name], w) for name in "xyz"]

    axes = {name: back(apply(frame, place[name])) for name in "xyz"}
    shifted = vec.add(apply(frame, place["origin"]), vec.sub(frame["origin"], place["origin"]))
    return dict(axes, origin=back(shifted))


def carried_point(place, point):
    """The point `point` (assembly space) seen in the component frame `place` (component to assembly)."""
    return [vec.dot(place[name], vec.sub(point, place["origin"])) for name in "xyz"]


def carried_faces(place, faces):
    """Face records (`{ center, area }`, `pattern_places`) with their centres in the component frame `place`; other
    values as they are."""
    if place is None or not isinstance(faces, list):
        return faces
    return [dict(f, center=carried_point(place, f["center"]))
            if isinstance(f, dict) and isinstance(f.get("center"), list) else f for f in faces]


def _carried_element(place, element):
    """An element with its frame and the centres of its faces in the component frame `place`."""
    out = dict(element, frame=carried_frame(place, element["frame"]))
    if "faces" in element:
        out["faces"] = carried_faces(place, element["faces"])
    return out


def same_frame(a, b):
    return (vec.close(a["origin"], b["origin"], FIT_TOL_MM)
            and all(vec.close(a[name], b[name], ROTATION_TOL * 1e3) for name in "xyz"))


def read_in_component(read, place):
    """A probe read of a pattern (`{ count, elements }`) with its element frames in the frame of the component the
    walk builds in (`place`, component to assembly, or None), like the captured ones."""
    if place is None or not read.get("elements"):
        return read
    return dict(read, elements=[_carried_element(place, e) for e in read["elements"]])


def repeated_items(item):
    """The timeline indexes of the items that `item` repeats as copies (`data.sources`) when its kind repeats items
    (`StepType.repeats_sources`: a pattern or a mirror), else an empty list."""
    spec = step_kinds.step_type(item.get("type"))
    if spec is None or not spec.repeats_sources:
        return []
    data = item.get("data")
    return (data.get("sources") if isinstance(data, dict) else None) or []


def data_in_component(data, place, merge=False):
    """The data of a pattern with its element frames in the frame of the component the walk builds in (`place`,
    component to assembly, or None). With `merge`, copies that sit exactly on an earlier one are dropped (a direction
    with a distance of zero makes such copies). The data itself when it has no elements."""
    elements = data.get("elements")
    if not elements:
        return data
    kept = []
    for element in elements:
        element = element if place is None else _carried_element(place, element)
        if merge and any(same_frame(element["frame"], other["frame"])
                         and element.get("suppressed") == other.get("suppressed") for other in kept):
            continue
        kept.append(element)
    out = dict(data, elements=kept)
    if place is not None and "source_faces" in data:
        out["source_faces"] = carried_faces(place, data["source_faces"])
    return out


def solve_lattice(offset, axes):
    """Lattice indexes of an offset and the leftover distance in mm. `axes` are (unit dir, step)."""
    if len(axes) == 1:
        coords = [vec.dot(offset, axes[0][0])]
    else:
        d1, d2 = axes[0][0], axes[1][0]
        g12 = vec.dot(d1, d2)
        det = 1.0 - g12 * g12
        b1, b2 = vec.dot(offset, d1), vec.dot(offset, d2)
        coords = [(b1 - g12 * b2) / det, (b2 - g12 * b1) / det]
    indexes = [int(round(c / step)) for c, (_, step) in zip(coords, axes)]
    fitted = [0.0, 0.0, 0.0]
    for index, (direction, step) in zip(indexes, axes):
        fitted = vec.add(fitted, vec.scale(direction, index * step))
    return indexes, vec.length(vec.sub(offset, fitted))


# Where Fusion puts the extra copy of a rectangular pattern with an even count, as seen in its exports: ahead of the
# original, along the direction of the pattern (the way its distance points, so against the direction when the
# distance is negative).
FUSION_EXTRA_SIDE = 1


def reach(places, count):
    """`(back, forward)`: the steps the measured copies run behind and ahead of the original, or None when they do not
    follow the rule for `count` copies. `places` are the signed steps of every copy, the original (0) included."""
    if not places:
        return None
    back, forward = -min(places), max(places)
    if back < 0 or forward < 0 or back + forward + 1 != count:
        return None
    half = count // 2
    allowed = {(half, half)} if count % 2 else {(half, half - 1), (half - 1, half)}
    return (back, forward) if (back, forward) in allowed else None


def mirror_plane(data):
    """The plane of a mirror as `{ origin, normal }` (rounded, unit normal), or None when it is not a flat plane."""
    plane = data.get("plane")
    if not plane or "point" not in plane or "normal" not in plane or vec.length(plane["normal"]) < 1e-9:
        return None
    return {"origin": [round9(v) for v in plane["point"]], "normal": [round9(v) for v in vec.unit(plane["normal"])]}
