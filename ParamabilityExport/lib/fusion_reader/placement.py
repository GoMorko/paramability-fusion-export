"""Where a body sits in the assembly: the frame that maps its component coordinates to the root's.

A picked body inside a component is an occurrence proxy; its native body lives in component coordinates. Two
candidate frames are tried (the occurrence's own transform, and the product of the native occurrence transforms along
the path). A candidate counts only when a few native vertices, mapped by it, land on the same vertices of the proxy.
No adsk import: it works on the objects it is given. Frames are `{ origin, x, y, z }` in mm, like the capture's.
"""
import math

from ..package.units import cm_to_mm
from . import read_geometry as geo

POINT_TOLERANCE_MM = 1e-3
AXIS_TOLERANCE = 1e-9
POINTS_TO_CHECK = 3
_MAX_DEPTH = 64

# Candidate sources. The occurrence's own transform comes first; the path product second. When `transform2` cannot be
# read, the retired `transform` is used and the source name says so.
SOURCE_TRANSFORM2 = "transform2"
SOURCE_TRANSFORM = "transform"
SOURCE_PATH_TRANSFORM2 = "path_transform2"
SOURCE_PATH_TRANSFORM = "path_transform"
_PATH_SOURCES = (SOURCE_PATH_TRANSFORM2, SOURCE_PATH_TRANSFORM)


def occurrence_path(body):
    """Occurrences from the body's own one out to the top, as seen from the root (empty for a root body)."""
    path, occurrence = [], geo.safe(lambda: body.assemblyContext, None)
    while occurrence is not None and len(path) < _MAX_DEPTH:
        path.append(occurrence)
        occurrence = geo.safe(lambda: occurrence.assemblyContext, None)
    return path


def _native(occurrence):
    return geo.safe(lambda: occurrence.nativeObject, None) or occurrence


def _raw_frame(matrix):
    """Matrix3D to a frame with raw axes (not normalized) and the origin in mm."""
    origin, x, y, z = matrix.getAsCoordinateSystem()
    return {
        "origin": [cm_to_mm(origin.x), cm_to_mm(origin.y), cm_to_mm(origin.z)],
        "x": [x.x, x.y, x.z],
        "y": [y.x, y.y, y.z],
        "z": [z.x, z.y, z.z],
    }


def _matrix(occurrence):
    """(raw frame, member used): `transform2`, else the retired `transform`; (None, "") when neither reads."""
    for member in ("transform2", "transform"):
        matrix = geo.safe(lambda: getattr(occurrence, member), None)
        frame = geo.safe(lambda: _raw_frame(matrix), None) if matrix is not None else None
        if frame is not None:
            return frame, member
    return None, ""


def _map(frame, p):
    return [frame["origin"][i] + p[0] * frame["x"][i] + p[1] * frame["y"][i] + p[2] * frame["z"][i] for i in range(3)]


def _turn(frame, d):
    return [d[0] * frame["x"][i] + d[1] * frame["y"][i] + d[2] * frame["z"][i] for i in range(3)]


def _compose(outer, inner):
    """The frame that applies `inner` first, then `outer`."""
    return {
        "origin": _map(outer, inner["origin"]),
        "x": _turn(outer, inner["x"]),
        "y": _turn(outer, inner["y"]),
        "z": _turn(outer, inner["z"]),
    }


def _dot(a, b):
    return sum(u * v for u, v in zip(a, b))


def _rigid(frame):
    """True for a rotation plus a move: unit, perpendicular axes, right handed (no scale, no mirror)."""
    axes = [frame["x"], frame["y"], frame["z"]]
    if any(abs(_dot(a, a) - 1.0) > AXIS_TOLERANCE for a in axes):
        return False
    if any(abs(_dot(axes[i], axes[j])) > AXIS_TOLERANCE for i, j in ((0, 1), (0, 2), (1, 2))):
        return False
    cross = [frame["x"][1] * frame["y"][2] - frame["x"][2] * frame["y"][1],
             frame["x"][2] * frame["y"][0] - frame["x"][0] * frame["y"][2],
             frame["x"][0] * frame["y"][1] - frame["x"][1] * frame["y"][0]]
    return _dot(cross, frame["z"]) > 0


def _rounded(frame):
    """The capture form: origin to 6 digits, unit axes to 9."""
    def unit(v):
        n = math.sqrt(_dot(v, v)) or 1.0
        return [round(c / n, 9) + 0.0 for c in v]
    return {"origin": [round(c, 6) + 0.0 for c in frame["origin"]],
            "x": unit(frame["x"]), "y": unit(frame["y"]), "z": unit(frame["z"])}


def _direct(path):
    """Candidate A: the transform of the body's own occurrence."""
    return _matrix(path[0])


def _along_path(path):
    """Candidate B: the native occurrence transforms from the top occurrence down, multiplied."""
    total, members = None, set()
    for occurrence in path:  # inner to outer
        frame, member = _matrix(_native(occurrence))
        if frame is None:
            return None, ""
        members.add(member)
        total = frame if total is None else _compose(frame, total)
    return total, "path_" + ("transform2" if members == {"transform2"} else "transform")


def _sample_points(body):
    """Up to POINTS_TO_CHECK points in mm: vertices first, then points on faces when there are too few vertices."""
    points = []
    for vertex in geo.collection_items(geo.safe(lambda: body.vertices, None)):
        p = geo.safe(lambda: geo.point(vertex.geometry), None)
        if p is not None:
            points.append(p)
        if len(points) == POINTS_TO_CHECK:
            return points
    for face in geo.collection_items(geo.safe(lambda: body.faces, None)):
        p = geo.safe(lambda: geo.point(face.pointOnFace), None)
        if p is not None:
            points.append(p)
        if len(points) == POINTS_TO_CHECK:
            break
    return points


def _lands_on(frame, native_points, proxy_points):
    return all(max(abs(a - b) for a, b in zip(_map(frame, n), q)) <= POINT_TOLERANCE_MM
               for n, q in zip(native_points, proxy_points))


def _names(path):
    return "+".join(geo.safe(lambda: o.name, "") or "?" for o in reversed(path))


def _failed(path, reason, uses, linked):
    return {"path": path, "error": reason, "uses": uses, "linked": linked}


def read_placement(body, root, component=None):
    """The placement record of a picked body (docs/capture-format.md), or None for a body of the root itself.

    `component` is the body's native component. A failure is not raised: the record then holds `error` and no
    `frame`, and the export lands a fixed shape.
    """
    path = occurrence_path(body)
    if component is None:
        component = geo.safe(lambda: body.parentComponent, None)
    if not path:
        token = geo.safe(lambda: component.entityToken, None)
        if token is None or token == geo.safe(lambda: root.entityToken, None):
            return None
        return _failed("", "The body was not picked through its place in the assembly.", 1, False)
    name = geo.safe(lambda: path[0].fullPathName, "") or _names(path)
    uses = geo.safe(lambda: int(root.allOccurrencesByComponent(component).count), 1) if component is not None else 1
    linked = any(geo.safe(lambda: bool(o.isReferencedComponent), False) or
                 geo.safe(lambda: bool(_native(o).isReferencedComponent), False) for o in path)
    native = geo.safe(lambda: body.nativeObject, None)
    if native is None:
        return _failed(name, "The body in its component could not be read.", uses, linked)
    native_points, proxy_points = _sample_points(native), _sample_points(body)
    if not native_points or len(native_points) != len(proxy_points):
        return _failed(name, "No points of the body could be compared.", uses, linked)
    reason = "The place of the part could not be read."
    for candidate in (_direct, _along_path):
        raw, used = candidate(path)
        if raw is None:
            continue
        if not _rigid(raw):
            reason = "The place of the part is scaled or mirrored."
            continue
        frame = _rounded(raw)
        if not _lands_on(frame, native_points, proxy_points):
            reason = "The place of the part does not match the body in the assembly."
            continue
        return {"path": name, "frame": frame, "source": used, "checked_points": len(native_points),
                "uses": uses, "linked": linked}
    return _failed(name, reason, uses, linked)


def read_frame(body, source):
    """The frame of a body's place read again with the candidate that read_placement chose; None when unreadable.

    No point check: the size checks only compare it with the frame the export used.
    """
    path = occurrence_path(body)
    if not path:
        return None
    raw, _ = (_along_path if source in _PATH_SOURCES else _direct)(path)
    return _rounded(raw) if raw is not None else None
