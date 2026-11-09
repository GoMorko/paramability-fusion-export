"""Revolve feature handler (RevolveFeature): sketch profiles turned about an axis in their sketch plane.

The recipe kernel turns by the right hand rule about the axis direction. Fusion does not say which way it turned, so
the measured outward normal of the start face decides whether the axis direction is kept or negated. The start face
bounds the new material for a new body, join or intersect, so its outward normal points against the travel. After a
cut it bounds the material that stays, so the normal points along the travel. Two sided revolves are refused: their
start face is the end of one side, which does not name the side. With the probe's motion file the outline, its plane
and an axis from a sketch line follow sizes (sketch_motion.py).
"""
import math

from . import loops, notes, placement, sketch_motion, values, vec
from .extrude import COMBINE
from .result import Refusal

TYPES = ("RevolveFeature",)

AXIS_PLANE_TOL = 1e-4
AXIS_SQUARE_TOL = 1e-9
FULL_TURN_DEG = 360.0


def _n(value):
    return round(value, 9) + 0.0


def _pt(p):
    return [_n(p[0]), _n(p[1])]


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


def _turn_direction(frame, outer, point2, dir2, dir3):
    """Unit direction the profile moves in at the start of a right hand turn about dir3, or a Refusal."""
    centre = _centroid(outer)
    p = [centre[0] - point2[0], centre[1] - point2[1]]
    along = p[0] * dir2[0] + p[1] * dir2[1]
    perp = [p[0] - along * dir2[0], p[1] - along * dir2[1]]
    if math.hypot(perp[0], perp[1]) < 1e-9:
        return Refusal("The sketch of this revolve lies on its axis.")
    radial = vec.add(vec.scale(frame["x"], perp[0]), vec.scale(frame["y"], perp[1]))
    return vec.unit(vec.cross(dir3, radial))


def _travel_from_normal(data, combine):
    """Measured travel direction at the start of the turn, or a Refusal."""
    normal = data.get("start_face_normal")
    if not normal:
        return Refusal("The turning direction of this revolve could not be read.")
    return vec.scale(vec.unit(normal), 1.0 if combine == "cut" else -1.0)


def _sense(data, combine, frame, outer, point2, dir2, dir3):
    """+1 when the captured axis direction turns the way Fusion did, -1 when it must be negated, or a Refusal."""
    travel = _travel_from_normal(data, combine)
    if isinstance(travel, Refusal):
        return travel
    turn = _turn_direction(frame, outer, point2, dir2, dir3)
    if isinstance(turn, Refusal):
        return turn
    side = vec.dot(travel, turn)
    if abs(side) < 1e-6:
        return Refusal("The turning direction of this revolve could not be read.")
    return 1 if side > 0 else -1


def _symmetric_ok(data, combine, frame, outer, point2, dir2, dir3, angle):
    """True when the measured start face sits half the angle before the profile (either way round), else a Refusal.

    Catches an angle that Fusion stores as the half turn instead of the whole one.
    """
    travel = _travel_from_normal(data, combine)
    if isinstance(travel, Refusal):
        return travel
    turn = _turn_direction(frame, outer, point2, dir2, dir3)
    if isinstance(turn, Refusal):
        return turn
    half = angle / 2.0
    for sense in (1.0, -1.0):
        expected = vec.rotate(vec.scale(turn, sense), dir3, -sense * half)
        if vec.length(vec.sub(expected, travel)) < 1e-3:
            return True
    return Refusal("The turn of this symmetric revolve does not match its measured start face.")


def _angles(extent):
    """(kind, angle) with kind full, part or symmetric; or a Refusal."""
    kind = (extent or {}).get("kind")
    if kind == "angle":
        angle = float(extent["angle_deg"])
        if not angle > 0 or angle > FULL_TURN_DEG + 1e-9:
            return Refusal("This revolve turns by an angle that is not copied.")
        if angle >= FULL_TURN_DEG - 1e-9:
            return "full", FULL_TURN_DEG
        return ("symmetric" if extent.get("symmetric") else "part"), angle
    if kind == "twoSidesAngle":
        return Refusal("Revolves turned to both sides are not copied yet.")
    return Refusal("This way of setting the revolve angle is not copied yet.")


def _turned(on, dir3, point3, degrees):
    """The placement turned about the 3D axis (right hand rule)."""
    return {
        "origin": [_n(v) for v in vec.rotate(on["origin"], dir3, degrees, point3)],
        "normal": [_n(v) for v in vec.rotate(on["normal"], dir3, degrees)],
        "xDir": [_n(v) for v in vec.rotate(on["xDir"], dir3, degrees)],
    }


def _turned_sized(ctx, item, drawn, dir3, point3, degrees):
    """The sketch origin turned about the axis when the plane or the axis moves with sizes: R o + (I - R) a, as
    written values; None when neither moves."""
    axis = sketch_motion.axis_raw(ctx, item)
    moving_axis = axis is not None and any(not (isinstance(a, sketch_motion.Affine) and a.is_constant) for a in axis)
    still = isinstance(drawn.plane, sketch_motion.Affine) and drawn.plane.is_constant if drawn is not None else True
    if drawn is None or (not moving_axis and still):
        return None
    if moving_axis and (item.get("data") or {}).get("project_axis"):
        ctx.fix([n for a in axis for n in sketch_motion.movers(ctx.table, a)],
                notes.stuck_reason("turns", drawn.sketch))
        return None
    frame, z = drawn.frame, drawn.frame["z"]
    origin = [sketch_motion.combine([(1.0, o - d * drawn.plane0), (d, drawn.plane)]) for o, d in zip(frame["origin"], z)]
    points = axis if moving_axis else [float(v) for v in point3]
    rows = [vec.rotate(e, dir3, degrees) for e in ([1, 0, 0], [0, 1, 0], [0, 0, 1])]
    turn = [[rows[j][i] for j in range(3)] for i in range(3)]
    turned = vec.rotate(frame["origin"], dir3, degrees, point3)
    out = []
    for i in range(3):
        parts = [(turn[i][j], origin[j]) for j in range(3)]
        parts += [((1.0 if i == j else 0.0) - turn[i][j], points[j]) for j in range(3)]
        q = sketch_motion.quantity(ctx, sketch_motion.combine(parts, drawn.sketch), turned[i])
        out.append(q.json() if q.sized else _n(q.n))
    return out


def _angle_value(ctx, item, mode, angle):
    """The turn as a Quantity. Only a turn that starts at the sketch can follow a size; the others stay numbers."""
    if mode == "part":
        return values.quantity(ctx, item, "extent.angle_deg", angle, dim="angle", absolute=True)
    values.pin(ctx, item, "extent.angle_deg", "a %s turn in %s cannot follow it" % (mode, item.get("name", "a step")))
    return values.Quantity(angle)


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
    mode, angle = angles

    built = []
    for at, profile in enumerate(profiles):
        outline = loops.profile_loops(profile)
        if isinstance(outline, Refusal):
            return outline
        if not isinstance(profile.get("frame"), dict):
            return Refusal("A sketch outline has no readable position.")
        located = _axis_in(profile["frame"], axis, bool(data.get("project_axis")))
        if isinstance(located, Refusal):
            return located
        drawn = sketch_motion.outline(ctx, item, profile, outline[0], outline[1], [(at, profile)])
        built.append((profile, outline, located, drawn))
    sketch_motion.planes_apart(ctx, [drawn for _, _, _, drawn in built], item)

    profile, (outer, _), (point2, dir2, point3, dir3), _ = built[0]
    sign = 1
    if mode == "part":
        sign = _sense(data, combine, profile["frame"], outer, point2, dir2, dir3)
        if isinstance(sign, Refusal):
            return sign
    elif mode == "symmetric":
        checked = _symmetric_ok(data, combine, profile["frame"], outer, point2, dir2, dir3, angle)
        if isinstance(checked, Refusal):
            return checked

    angle_value = _angle_value(ctx, item, mode, angle)
    steps = []
    for profile, (outer, inners), (point2, dir2, point3, dir3), drawn in built:
        on = placement.from_frame(profile["frame"])
        if mode == "symmetric":
            moved = _turned_sized(ctx, item, drawn, dir3, point3, -angle / 2.0)
            on = _turned(on, dir3, point3, -angle / 2.0)
            if moved is not None:
                on["origin"] = moved
        elif drawn is not None:
            on["origin"] = drawn.origin(ctx, values.Quantity(0.0))
        if drawn is not None:
            outer, inners = drawn.written(ctx)
        sketch = {"on": on, "outer": outer}
        if inners:
            sketch["inner"] = inners
        step = {
            "kind": "revolve",
            "sketch": sketch,
            "axis": {"point": sketch_motion.axis_point(ctx, item, profile["frame"], point2),
                     "dir": _pt([sign * dir2[0], sign * dir2[1]])},
            "combine": combine if not steps else ("add" if combine == "new" else combine),
        }
        if mode != "full":
            step["angleDeg"] = angle_value.json()
        steps.append(step)
    return steps
