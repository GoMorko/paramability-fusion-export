"""Revolve feature handler (RevolveFeature): sketch profiles turned about an axis in their sketch plane.

The recipe kernel turns by the right hand rule about the axis direction. Fusion does not say which way it turned, so
the measured outward normals of the caps decide whether the axis direction is kept or negated
(`design_model.steps.revolve.sense`). Fusion's angle of a symmetric revolve is the turn to each side: the copy turns
twice the angle from the angle back, a turn of 180 degrees or more to each side closes the ring, and the measured caps
must sit where that puts them. The start face of a revolve to two sides is the end of one side:
`design_model.steps.revolve.back_sides` tells from it which side each angle turns to. The copy turns the sketch back by
that angle and revolves by the sum of the two. When the angle back follows a size, the revolve stays at the sketch and
a `move` inside a `toolBody` turns it back instead. An intersect of several outlines is one `toolBody` that holds them
all, since the part keeps what any of them holds. With the probe's motion file the outline, its plane and an axis from
a sketch line follow sizes (sketch/sketch_motion.py); for a line of another sketch than the outline's, the sizes that
may move it and were not tried are marked (`ref_motion.check_own_axis`). An axis of another component follows the
sizes the probe measured it move with (ref_motion.py). Any other axis of the part is written as measured, and the
sizes that may move it are marked (`ref_motion.check_own_axis`). A caller that has worked out the axis point's raw
values (`axis.raw`) or the angle (`extent.quantity`) gives them as they are.
"""
import math

from ...capture_model import gap_hints
from ...design_model.values import Quantity
from ...geometry import vec
from ...package.numbers import round9

from ...design_model import refs
from ...design_model.steps import revolve as revolve_facts
from ...design_model import words as shared
from .. import notes, placement, ref_motion, values
from ..extrude import COMBINE
from ..faces.tool_placer import JoinedWalk
from ..ranges import range_check
from ..result import Refusal, StepResult
from ..sketch import loops, sketch_motion


AXIS_PLANE_TOL = 1e-4
AXIS_SQUARE_TOL = 1e-9
FULL_TURN_DEG = 360.0
# The params paths of the two angles of a revolve to two sides.
TWO_ANGLES = ("extent.angle_one_deg", "extent.angle_two_deg")


def _pt(p):
    return [round9(p[0]), round9(p[1])]


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
        return Refusal(shared.REVOLVE_ON_AXIS)
    radial = vec.add(vec.scale(frame["x"], perp[0]), vec.scale(frame["y"], perp[1]))
    return vec.unit(vec.cross(dir3, radial))


def _travel_from_normal(data, combine):
    """Measured travel direction at the start of the turn, or a Refusal."""
    normal = data.get("start_face_normal")
    if not normal:
        return Refusal(shared.REVOLVE_TURN_UNREAD)
    return vec.scale(vec.unit(normal), 1.0 if combine == "cut" else -1.0)


def _sense(data, combine, frame, outer, point2, dir2, dir3, point3, angle, bodies):
    """+1 when the captured axis direction turns the way Fusion did, -1 when it must be negated, or a Refusal.
    `bodies` holds the boxes of the body before and after the step (`revolve_facts.body_boxes`)."""
    turn = _turn_direction(frame, outer, point2, dir2, dir3)
    if isinstance(turn, Refusal):
        return turn
    found = revolve_facts.sense(data, turn, dir3, angle, combine == "cut", revolve_facts.outline_points(data), point3,
                                bodies)
    return Refusal(shared.REVOLVE_TURN_UNREAD) if found is None else int(found)


def _symmetric_ok(data, combine, frame, outer, point2, dir2, dir3, angle):
    """True when the measured caps sit half the whole turn `angle` before and after the profile, else a Refusal."""
    turn = _turn_direction(frame, outer, point2, dir2, dir3)
    if isinstance(turn, Refusal):
        return turn
    fits = revolve_facts.symmetric_ok(data, turn, dir3, angle / 2.0, combine == "cut")
    if fits is None:
        return Refusal(shared.REVOLVE_TURN_UNREAD)
    return True if fits else Refusal(shared.REVOLVE_SYMMETRIC_CAPS)


def _two_sides_back(data, combine, frame, outer, point2, dir2, dir3, angles):
    """The side (1 or 2) whose angle the turn starts back from the sketch, by the right hand rule about dir3; 0 when
    the two angles are equal and either fits; or a Refusal."""
    travel = _travel_from_normal(data, combine)
    if isinstance(travel, Refusal):
        return travel
    turn = _turn_direction(frame, outer, point2, dir2, dir3)
    if isinstance(turn, Refusal):
        return turn
    sides = revolve_facts.back_sides(travel, turn, dir3, angles[0], angles[1])
    if not sides:
        return Refusal("The turn of this two sided revolve does not match its measured start face.")
    if len(sides) == 1:
        return sides[0]
    if abs(angles[0] - angles[1]) <= 1e-9:
        return 0
    return Refusal("The start face of this two sided revolve does not tell which side each angle turns to.",
                   cause=gap_hints.REVOLVE_SIDES)


def _angles(extent):
    """(kind, angle) with kind full, part, symmetric (angle is the whole turn) or twoSides (angle is then the pair of
    angles); or a Refusal."""
    kind = (extent or {}).get("kind")
    if kind == "angle":
        angle = float(extent["angle_deg"])
        if not angle > 0 or angle > FULL_TURN_DEG + 1e-9:
            return Refusal(shared.REVOLVE_ANGLE)
        symmetric = bool(extent.get("symmetric"))
        total, full = revolve_facts.total_turn(angle, symmetric)
        if full:
            return "full", FULL_TURN_DEG
        return ("symmetric" if symmetric else "part"), total
    if kind == "twoSidesAngle":
        pair = (float(extent["angle_one_deg"]), float(extent["angle_two_deg"]))
        if not (pair[0] > 0 and pair[1] > 0) or sum(pair) > FULL_TURN_DEG + 1e-9:
            return Refusal(shared.REVOLVE_ANGLE)
        if sum(pair) >= FULL_TURN_DEG - 1e-9:
            return "full", FULL_TURN_DEG
        return "twoSides", pair
    return Refusal(shared.REVOLVE_ANGLE_KIND)


def _turned(on, dir3, point3, degrees):
    """The placement turned about the 3D axis (right hand rule)."""
    return {
        "origin": [round9(v) for v in vec.rotate(on["origin"], dir3, degrees, point3)],
        "normal": [round9(v) for v in vec.rotate(on["normal"], dir3, degrees)],
        "xDir": [round9(v) for v in vec.rotate(on["xDir"], dir3, degrees)],
    }


def _foreign_axis(ctx, item, axis):
    """The raw 3D point of an axis of another component as it moves with sizes (`ref_motion`), or None when sketch
    values do not follow sizes in this walk. The sizes that move it are marked here when the move cannot be followed."""
    moved = ref_motion.raw_moves(ctx, item, axis.get("ref") or {}, refs.AXIS, "turns about")
    if not sketch_motion.active(ctx):
        return None
    return [sketch_motion.Affine(float(p)).plus(m) for p, m in zip(axis["point"], moved)]


def _keep_in_plane(ctx, item, coords, outlines):
    """An axis of another component that moves out of the plane of a sketch that does not move with it would leave
    that plane at other sizes: the sizes behind the difference are marked."""
    for drawn in outlines:
        if drawn is None or not isinstance(drawn.plane, sketch_motion.Affine):
            continue
        z = drawn.frame["z"]
        along = sketch_motion.combine([(z[c], coords[c]) for c in range(3)], drawn.sketch)
        if not sketch_motion.same(along, drawn.plane):
            names = sketch_motion.movers(ctx.table, along) + sketch_motion.movers(ctx.table, drawn.plane)
            ctx.doubt(tuple(dict.fromkeys(names)), "%s turns about an axis of another component that moves out of "
                      "the plane of its sketch, and the copy cannot follow that" % item.get("name", "a step"))


def _moves(axis):
    """True when the raw axis point `axis` (None when sketch values do not follow sizes) moves with sizes."""
    return axis is not None and any(not (isinstance(a, sketch_motion.Affine) and a.is_constant) for a in axis)


def _turned_sized(ctx, item, data, drawn, dir3, point3, degrees, axis=None):
    """The sketch origin turned about the axis when the plane or the axis moves with sizes: R o + (I - R) a, as
    written values; None when neither moves. `data` is the data of the revolve `item`. `axis` is the raw axis point
    when it comes from another component."""
    if axis is None:
        axis = sketch_motion.axis_raw(ctx, item, data.get("axis"))
    moving_axis = _moves(axis)
    still = isinstance(drawn.plane, sketch_motion.Affine) and drawn.plane.is_constant if drawn is not None else True
    if drawn is None or (not moving_axis and still):
        return None
    if moving_axis and data.get("project_axis"):
        ctx.doubt([n for a in axis for n in sketch_motion.movers(ctx.table, a)],
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
        out.append(q.json() if q.sized else round9(q.n))
    return out


def _angle_value(ctx, item, mode, angle, extent):
    """The turn as a Quantity. Only a turn that starts at the sketch can follow a size; the others stay numbers.
    `extent.quantity` is a Quantity the caller worked out (a sweep along an arc)."""
    given = extent.get("quantity")
    if given is not None and mode == "part":
        return given
    if mode == "part":
        return values.quantity(ctx, item, "extent.angle_deg", angle, dim="angle", absolute=True)
    for path in (TWO_ANGLES if extent.get("kind") == "twoSidesAngle" else ("extent.angle_deg",)):
        values.pin(ctx, item, path, "a %s turn in %s cannot follow it" % (mode, item.get("name", "a step")))
    return Quantity(angle)


def _two_sides_values(ctx, item, data, angles, side, axis_raw):
    """`(total, back, turn_back)` of a two sided revolve whose turn starts back by the angle of `side` (0 when the two
    angles are equal): the whole turn as a Quantity, the degrees back as a number, and the turn back as a Quantity
    when it follows sizes (a `move` writes it then), else None. Both angles follow sizes while their sum stays a full
    turn or less. With equal angles the copy cannot tell which side each one turns to at other sizes, so both stay
    numbers. The turn back stays a number about a projected axis or an axis that moves with sizes."""
    name = item.get("name", "a step")
    if side == 0:
        for path in TWO_ANGLES:
            values.pin(ctx, item, path, "the two angles of %s are equal, so the copy cannot tell which side each one "
                       "turns to" % name)
        return Quantity(sum(angles)), angles[1], None
    at = side - 1
    ahead = values.quantity(ctx, item, TWO_ANGLES[1 - at], angles[1 - at], dim="angle", absolute=True)
    back = values.quantity(ctx, item, TWO_ANGLES[at], angles[at], dim="angle", absolute=True)
    total = ahead.plus(back)
    if total.sized and not range_check.sweep(ctx.table, total.text, total.reads).at_most(FULL_TURN_DEG + 1e-9):
        ctx.doubt(total.reads, "the two angles of %s would turn more than a full circle at other sizes" % name)
        return Quantity(sum(angles)), angles[at], None
    if back.sized and (data.get("project_axis") or _moves(axis_raw)):
        ctx.doubt(back.reads, "the axis of %s is projected onto its sketch or moves with sizes, so its angle on the "
                  "far side of the sketch cannot follow them" % name)
        return ahead.plus(angles[at]), angles[at], None
    return total, angles[at], (back if back.sized else None)


def _held(ctx, item, steps, combine, extra=None):
    """One `toolBody` step with `combine` that holds the revolves `steps` (the first makes the tool, the rest join it)
    and the `extra` step after them."""
    for n, step in enumerate(steps):
        step["combine"] = "add" if n else "new"
    inner = StepResult.of(steps + ([extra] if extra else []))
    held = ctx.child({"name": item.get("name")}, "%st%s_rv_" % (ctx.id_prefix, item["index"]), depth=ctx.depth + 1)
    held.add_steps(item, inner)
    out = StepResult()
    out.add({"kind": "toolBody", "combine": combine, "features": held.steps}, [JoinedWalk(held)])
    return out


# What a revolve axis the copy cannot use is, by the Fusion type the reader recorded.
_AXIS_WORDS = {"BRepEdge": "an edge", "BRepFace": "a face", "SketchLine": "a sketch line",
               "ConstructionAxis": "a construction axis"}


def _axis_refusal(axis):
    """Why a revolve axis cannot be copied, saying what the axis is when the reader recorded it."""
    kind = axis.get("type")
    if kind == "none":
        return "Fusion gives no axis for this revolve."
    words = _AXIS_WORDS.get(kind, "a %s" % kind if kind else "")
    if kind == "BRepEdge" and axis.get("geometry"):
        return "The axis of this revolve is an edge that is not straight, which cannot be copied."
    if kind == "BRepFace" and axis.get("geometry"):
        return "The axis of this revolve is a face that is not round, which cannot be copied."
    if axis.get("error") and words:
        return "The axis of this revolve (%s) could not be read." % words
    if words:
        return "The axis of this revolve is %s, which cannot be copied yet." % words
    return "The axis of this revolve is not a straight line that can be copied."


def handle(ctx, step):
    item, data = step.brought, step.brought_data
    operation = data.get("operation")
    if operation == "newComponent":
        return Refusal("Revolves that make a new component are not copied.", cause=gap_hints.NEW_COMPONENT)
    if operation not in COMBINE:
        return Refusal("This revolve combines with the part in a way that is not copied yet.")
    combine = COMBINE[operation]
    profiles = data.get("profiles") or []
    if not profiles:
        return Refusal("This revolve has no sketch outline.")
    axis = data.get("axis")
    if not axis or axis.get("kind") == "other" or "point" not in axis or "dir" not in axis:
        return Refusal(_axis_refusal(axis or {}))
    coords = _foreign_axis(ctx, item, axis) if axis.get("assembly") else axis.get("raw")
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
        drawn = sketch_motion.outline(ctx, item, profile, outline[0], outline[1], [(sketch_motion.profile_number(profile, at), profile)])
        built.append((profile, outline, located, drawn))
    sketch_motion.planes_apart(ctx, [drawn for _, _, _, drawn in built], item)
    if coords is not None and not data.get("project_axis"):
        _keep_in_plane(ctx, item, coords, [drawn for _, _, _, drawn in built])

    profile, (outer, _), (point2, dir2, point3, dir3), _ = built[0]
    extent = data.get("extent") or {}
    sign, back, turn_back = 1, 0.0, None
    if mode == "part":
        sign = _sense(data, combine, profile["frame"], outer, point2, dir2, dir3, point3, angle,
                      revolve_facts.body_boxes(item))
        if isinstance(sign, Refusal):
            return sign
    elif mode == "symmetric":
        checked = _symmetric_ok(data, combine, profile["frame"], outer, point2, dir2, dir3, angle)
        if isinstance(checked, Refusal):
            return checked
        back = angle / 2.0
    if mode == "twoSides":
        side = _two_sides_back(data, combine, profile["frame"], outer, point2, dir2, dir3, angle)
        if isinstance(side, Refusal):
            return side
        axis_raw = coords if coords is not None else sketch_motion.axis_raw(ctx, item, axis)
        angle_value, back, turn_back = _two_sides_values(ctx, item, data, angle, side, axis_raw)
    else:
        angle_value = _angle_value(ctx, item, mode, angle, extent)
    steps = []
    for profile, (outer, inners), (point2, dir2, point3, dir3), drawn in built:
        on = placement.from_frame(profile["frame"])
        if back and turn_back is None:
            moved = _turned_sized(ctx, item, data, drawn, dir3, point3, -back, coords)
            on = _turned(on, dir3, point3, -back)
            if moved is not None:
                on["origin"] = moved
        elif drawn is not None:
            on["origin"] = drawn.origin(ctx, Quantity(0.0))
        if drawn is not None:
            outer, inners = drawn.written(ctx)
        sketch = {"on": on, "outer": outer}
        if inners:
            sketch["inner"] = inners
        recipe_step = {
            "kind": "revolve",
            "sketch": sketch,
            "axis": {"point": sketch_motion.axis_point(ctx, item, axis, profile["frame"], point2, coords),
                     "dir": _pt([sign * dir2[0], sign * dir2[1]])},
            "combine": combine if not steps else ("add" if combine == "new" else combine),
        }
        if mode != "full":
            recipe_step["angleDeg"] = angle_value.json()
        steps.append(recipe_step)
    ref_motion.check_own_axis(ctx, item, axis, "turns about", {p.get("sketch") for p, _, _, _ in built})
    if turn_back is not None:
        # The revolves start at the sketch; the move turns them back about the axis (the right hand rule about the
        # reversed axis). It holds no projected or moving axis (`_two_sides_values`), so built[0] gives the axis.
        _, _, (_, _, point3, dir3), _ = built[0]
        move = {"kind": "move", "turn": {"axisPoint": [round9(c) for c in point3],
                                         "axis": [round9(-c) for c in dir3], "angleDeg": turn_back.json()}}
        return _held(ctx, item, steps, combine, move)
    if combine == "intersect" and len(steps) > 1:
        return _held(ctx, item, steps, combine)
    return StepResult.of(steps)
