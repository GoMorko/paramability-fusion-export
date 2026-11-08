"""Revolve feature handler (RevolveFeature): sketch profiles turned about an axis in their sketch plane.

The recipe kernel turns by the right hand rule about the axis direction. Fusion does not say which way it turned, so
the measured outward normal of the start face decides whether the axis direction is kept or negated.
"""
import math

from . import loops, placement, vec
from .extrude import COMBINE
from .result import Refusal

TYPES = ("RevolveFeature",)

AXIS_PLANE_TOL = 1e-4
AXIS_SQUARE_TOL = 1e-9
FULL_TURN_DEG = 360.0
MAX_INNER_LOOPS = 256


def _n(value):
    return round(value, 9) + 0.0


def _pt(p):
    return [_n(p[0]), _n(p[1])]


def build_outline(profile):
    """(outer, inners) recipe loops of one captured profile, or a Refusal."""
    if profile.get("face") or "loops" not in profile:
        return Refusal("A flat face used as a sketch outline is not copied yet.")
    sketch = profile.get("sketch", "")
    outers, inners = [], []
    for raw in profile["loops"]:
        loop = loops.loop_of(raw.get("curves") or [], sketch)
        if isinstance(loop, Refusal):
            return loop
        (outers if raw.get("outer") else inners).append(loop)
    if len(outers) != 1:
        where = " in %s" % sketch if sketch else ""
        return Refusal("An outline%s does not have exactly one outer loop." % where)
    if len(inners) > MAX_INNER_LOOPS:
        return Refusal("An outline has too many holes.")
    return outers[0], inners


def _loop_points(loop):
    kind = loop["kind"]
    if kind == "polygon":
        return loop["points"]
    if kind == "profile":
        points = [loop["start"]]
        for seg in loop["segments"]:
            if "through" in seg:
                points.append(seg["through"])
            points.append(seg["to"])
        return points
    return [loop["center"]]


def _centroid(loop):
    """Area centroid of a loop's corner points, or their average when the area vanishes."""
    points = _loop_points(loop)
    area = cx = cy = 0.0
    for a, b in zip(points, points[1:] + points[:1]):
        cross = a[0] * b[1] - b[0] * a[1]
        area += cross
        cx += (a[0] + b[0]) * cross
        cy += (a[1] + b[1]) * cross
    if abs(area) > 1e-12:
        return [cx / (3.0 * area), cy / (3.0 * area)]
    return [sum(p[0] for p in points) / len(points), sum(p[1] for p in points) / len(points)]


def _axis_in(frame, axis, project):
    """(point2, dir2, point3, dir3) of the axis in a profile's sketch plane, or a Refusal.

    An axis off the plane is refused unless `project`, which drops it onto the plane first.
    """
    z = vec.unit(frame["z"])
    point, direction = list(axis["point"]), vec.unit(axis["dir"])
    off = vec.dot(vec.sub(point, frame["origin"]), z)
    tilt = vec.dot(direction, z)
    if abs(off) > AXIS_PLANE_TOL or abs(tilt) > AXIS_SQUARE_TOL:
        if not project:
            return Refusal("The revolve axis does not lie in the plane of the sketch.")
        point = vec.sub(point, vec.scale(z, off))
        flat = vec.sub(direction, vec.scale(z, tilt))
        if vec.length(flat) < 1e-9:
            return Refusal("The revolve axis points straight out of the plane of the sketch.")
        direction = vec.unit(flat)
    local = vec.frame_to_local(frame, point)
    dir2 = [vec.dot(direction, frame["x"]), vec.dot(direction, frame["y"])]
    return [local[0], local[1]], dir2, point, direction


def _sense(data, frame, outer, point2, dir2, dir3):
    """+1 when the captured axis direction turns the way Fusion did, -1 when it must be negated, or a Refusal."""
    normal = data.get("start_face_normal")
    if not normal:
        return Refusal("The turning direction of this revolve could not be read.")
    travel = vec.scale(vec.unit(normal), -1.0)
    centre = _centroid(outer)
    p = [centre[0] - point2[0], centre[1] - point2[1]]
    along = p[0] * dir2[0] + p[1] * dir2[1]
    perp = [p[0] - along * dir2[0], p[1] - along * dir2[1]]
    if math.hypot(perp[0], perp[1]) < 1e-9:
        return Refusal("The sketch of this revolve lies on its axis.")
    radial = vec.add(vec.scale(frame["x"], perp[0]), vec.scale(frame["y"], perp[1]))
    turn = vec.cross(dir3, radial)
    side = vec.dot(travel, turn) / (vec.length(turn) * vec.length(travel))
    if abs(side) < 1e-6:
        return Refusal("The turning direction of this revolve could not be read.")
    return 1 if side > 0 else -1


def _angles(extent):
    """(kind, angle one, angle two) with kind full, part, symmetric or two; or a Refusal."""
    kind = (extent or {}).get("kind")
    if kind == "angle":
        angle = float(extent["angle_deg"])
        if not angle > 0 or angle > FULL_TURN_DEG + 1e-9:
            return Refusal("This revolve turns by an angle that is not copied.")
        if angle >= FULL_TURN_DEG - 1e-9:
            return "full", FULL_TURN_DEG, None
        return ("symmetric" if extent.get("symmetric") else "part"), angle, None
    if kind == "twoSidesAngle":
        one, two = float(extent["angle_one_deg"]), float(extent["angle_two_deg"])
        if not (one > 0 and two > 0 and one + two <= FULL_TURN_DEG + 1e-9):
            return Refusal("This revolve turns by angles that are not copied.")
        return "two", one, two
    return Refusal("This way of setting the revolve angle is not copied yet.")


def _turned(on, dir3, point3, degrees):
    """The placement turned about the 3D axis (right hand rule)."""
    return {
        "origin": [_n(v) for v in vec.rotate(on["origin"], dir3, degrees, point3)],
        "normal": [_n(v) for v in vec.rotate(on["normal"], dir3, degrees)],
        "xDir": [_n(v) for v in vec.rotate(on["xDir"], dir3, degrees)],
    }


def handle(item, ctx):
    data = item.get("data") or {}
    if "read_error" in data:
        return Refusal("This revolve could not be read from Fusion.")
    operation = data.get("operation")
    if operation == "newComponent":
        return Refusal("Revolves that make a new component are not copied.")
    if operation not in COMBINE:
        return Refusal("This revolve combines with the part in a way that is not copied yet.")
    combine = COMBINE[operation]
    profiles = data.get("profiles") or []
    if not profiles:
        return Refusal("This revolve has no sketch outline.")
    axis = data.get("axis")
    if not axis or axis.get("kind") == "other" or "point" not in axis or "dir" not in axis:
        return Refusal("The axis of this revolve is not a straight line that can be copied.")
    angles = _angles(data.get("extent"))
    if isinstance(angles, Refusal):
        return angles
    mode, angle_one, angle_two = angles

    built = []
    for profile in profiles:
        outline = build_outline(profile)
        if isinstance(outline, Refusal):
            return outline
        located = _axis_in(profile["frame"], axis, bool(data.get("project_axis")))
        if isinstance(located, Refusal):
            return located
        built.append((profile, outline, located))

    sign = 1
    if mode in ("part", "two"):
        profile, (outer, _), (point2, dir2, _, dir3) = built[0]
        sign = _sense(data, profile["frame"], outer, point2, dir2, dir3)
        if isinstance(sign, Refusal):
            return sign

    sides = [(1, angle_one)]
    if mode == "two":
        sides.append((-1, angle_two))
    steps = []
    for profile, (outer, inners), (point2, dir2, point3, dir3) in built:
        base = placement.from_frame(profile["frame"])
        if mode == "symmetric":
            base = _turned(base, dir3, point3, -angle_one / 2.0)
        for side_sign, degrees in sides:
            run = sign * side_sign
            sketch = {"on": base, "outer": outer}
            if inners:
                sketch["inner"] = inners
            step = {
                "kind": "revolve",
                "sketch": sketch,
                "axis": {"point": _pt(point2), "dir": _pt([run * dir2[0], run * dir2[1]])},
                "combine": combine if not steps else ("add" if combine == "new" else combine),
            }
            if mode != "full":
                step["angleDeg"] = _n(degrees)
            steps.append(step)
    return steps
