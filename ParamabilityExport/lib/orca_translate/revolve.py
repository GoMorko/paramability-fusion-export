"""Revolve steps as Orca Revolve features.

Each loop of an outline becomes a sketch of its lines and arcs, plus a construction line along the turning axis that
the Revolve names (`revolve_axis_entity`), so the axis may sit anywhere in the sketch plane. Orca turns by the right
hand rule about that line; Fusion does not say which way it turned, so the measured caps decide
(`steps.revolve.sense`). `revolve_angle` follows the angle's parameter. How the sketches, revolves and tool bodies
are written is in `revolve_parts`: a hole of the outline is turned the same way and cut away, and several outlines are
turned one by one. Outlines that a turn of less than a full circle moves different ways at the sketch (on different
sides of the axis) are left out: the one measured start face cannot tell how each turned.

Fusion's angle of a symmetric revolve is the turn to each side. When that angle follows sizes (and the step is not an
intersect), the copy writes two revolves from the sketch plane, one each way (Orca's `flip`), each by
`min(angle, 180)`, so the angle follows and 180 degrees or more to each side closes the ring. A cut is written so only
when each half meets the part. Otherwise the copy turns twice the angle from the angle back, the sketch plane is
turned there, so its angle keeps its number; a symmetric turn of 180 degrees or more to each side closes the ring.
Either way the measured caps must sit where the turn puts them. A turn to two sides by two angles starts the angle of
one side back (the start face tells which, `design_model.steps.revolve.back_sides`) and turns by the sum of the two;
both angles keep their numbers.

Orca needs the axis in the sketch plane and each outline on one side of it; anything else is left out with the
reason. A cut that removes nothing stops Orca's rebuild, so a cut that misses the copied part is left out
(`solid.Turned` is the shape the check uses); of several cut outlines, those that miss are left out with a note.
"""
from ..capture_model import gap_hints
from ..design_model import reach, roles
from ..design_model.steps import revolve as revolve_facts
from ..geometry import vec
from ..geometry.footprint import polyline
from . import causes, kept_refs, revolve_checks, revolve_parts
from ..design_model.values import Quantity
from ..design_model import words as shared
from .sketches import entities_of, outlines_of
from .sketch_sizes import profile_sizes, projection_doubts
from .steps import Skip
from .tools import label

FULL_TURN_DEG = 360.0
HALF_TURN_DEG = 180.0
# How far (mm) the axis may sit off the sketch plane, and how far it may lean out of it, and still count as in it.
AXIS_PLANE_TOL = 1e-4
AXIS_TILT_TOL = 1e-6
# How far (mm) an outline may reach across the axis.
SIDE_TOL = 1e-6


def _profile_problem(profile):
    if profile.get("face"):
        return "This revolve turns a face of the body, which the Orca copy does not copy yet."
    if profile.get("text"):
        return "Sketch text is not copied to Orca yet."
    if profile.get("foreign"):
        return "This revolve uses a sketch of another component, which is not copied."
    if profile.get("space") not in (None, "sketch", "model") or not isinstance(profile.get("frame"), dict):
        return "The outline of this revolve could not be read."
    return None


def _two_angles(ctx, item, extent):
    """`(Quantity of the whole turn, the two angles)` of a turn to two sides, or a Skip. A whole turn has no angles."""
    pair = [extent.get(key) for key in ("angle_one_deg", "angle_two_deg")]
    if not all(isinstance(a, (int, float)) and a > 0 for a in pair) or sum(pair) > FULL_TURN_DEG + 1e-9:
        return Skip(shared.REVOLVE_ANGLE)
    for path, angle in zip(("extent.angle_one_deg", "extent.angle_two_deg"), pair):
        value = ctx.quantity(item, path, angle, "angle")
        if value.text is not None:
            ctx.doubt(value.reads, "%s turns to two sides of its sketch, so its angles keep their numbers in Orca"
                      % label(item))
    if sum(pair) >= FULL_TURN_DEG - 1e-9:
        return Quantity(FULL_TURN_DEG), None
    return Quantity(float(sum(pair))), (float(pair[0]), float(pair[1]))


class _Angle:
    """The angle of a revolve: `total` (a `Quantity` of the whole turn), `sides` (None for a turn from the sketch,
    "symmetric" for a turn to both sides by one angle, or the two angles of a turn to two sides) and `per_side`: for a
    symmetric turn whose angle follows sizes, the `Quantity` of the angle to each side, else None."""

    def __init__(self, total, sides=None, per_side=None):
        self.total, self.sides, self.per_side = total, sides, per_side


def _angle(ctx, item, extent):
    """The `_Angle` of a revolve, or a Skip."""
    kind = (extent or {}).get("kind")
    if kind == "twoSidesAngle":
        found = _two_angles(ctx, item, extent)
        return found if isinstance(found, Skip) else _Angle(*found)
    if kind != "angle" or not isinstance(extent.get("angle_deg"), (int, float)):
        return Skip(shared.REVOLVE_ANGLE_KIND)
    angle = abs(float(extent["angle_deg"]))
    if not 0 < angle <= FULL_TURN_DEG + 1e-9:
        return Skip(shared.REVOLVE_ANGLE)
    symmetric = bool(extent.get("symmetric"))
    total, full = revolve_facts.total_turn(angle, symmetric)
    value = ctx.quantity(item, "extent.angle_deg", angle, "angle").magnitude()
    per_side = value if symmetric and value.text is not None else None
    if full:
        if value.text is not None and not symmetric:
            ctx.doubt(value.reads, "%s turns a full circle only while its angle is 360" % label(item))
        return _Angle(Quantity(FULL_TURN_DEG), None, per_side)
    if symmetric:
        return _Angle(Quantity(total), "symmetric", per_side)
    return _Angle(value)


def _fixed_symmetric(ctx, item, angle):
    """A symmetric turn whose angle follows sizes is written with its angle as a number: the sizes get the reason."""
    if angle.per_side is None:
        return
    if angle.total.n >= FULL_TURN_DEG:
        ctx.doubt(angle.per_side.reads, "%s turns a full circle only while its angle is 180 or more" % label(item))
    else:
        ctx.doubt(angle.per_side.reads, "%s turns to both sides of its sketch, so its angle keeps its number in Orca"
                  % label(item))


def _half(per_side):
    """The angle of each half of a symmetric turn that follows sizes: at most half a circle, so the two halves close
    the ring at 180 degrees or more to each side, as Fusion does."""
    return Quantity(min(per_side.n, HALF_TURN_DEG), "min(%s, %s)" % (per_side.text, int(HALF_TURN_DEG)),
                    per_side.reads)


def _points(curves):
    return [p for c in curves for p in polyline(c)]


def _turn(frame, outer, point, direction):
    """The unit way the outline moves at its sketch plane on a right hand turn about `direction`, or a Skip."""
    flat = _points(outer)
    centre = [sum(p[0] for p in flat) / len(flat), sum(p[1] for p in flat) / len(flat)]
    v = vec.sub(vec.frame_apply(frame, [centre[0], centre[1], 0.0]), point)
    radial = vec.sub(v, vec.scale(direction, vec.dot(v, direction)))
    if vec.length(radial) < 1e-9:
        return Skip(shared.REVOLVE_ON_AXIS)
    return vec.unit(vec.cross(direction, vec.unit(radial)))


def _travel_turn(data, operation, frame, outer, point, direction):
    """`(travel, turn)`: the measured direction the material leaves the start face in, and the direction the outline
    moves in at the start of a right hand turn about `direction`; or a Skip."""
    normal = data.get("start_face_normal")
    if not isinstance(normal, (list, tuple)) or vec.length(normal) < 1e-9:
        return Skip(shared.REVOLVE_TURN_UNREAD)
    travel = vec.scale(vec.unit(normal), 1.0 if operation == "cut" else -1.0)
    turn = _turn(frame, outer, point, direction)
    return turn if isinstance(turn, Skip) else (travel, turn)


def _sense(data, operation, frame, outer, point, direction, angle, symmetric, bodies):
    """+1 when Fusion turned by the right hand rule about `direction`, -1 when the other way (a symmetric turn keeps
    +1 once its caps fit), or a Skip. `bodies` holds the boxes of the body before and after the step
    (`revolve_facts.body_boxes`)."""
    turn = _turn(frame, outer, point, direction)
    if isinstance(turn, Skip):
        return turn
    cut = operation == "cut"
    if symmetric:
        fits = revolve_facts.symmetric_ok(data, turn, direction, angle / 2.0, cut)
        if fits is None:
            return Skip(shared.REVOLVE_TURN_UNREAD)
        return 1.0 if fits else Skip(shared.REVOLVE_SYMMETRIC_CAPS)
    found = revolve_facts.sense(data, turn, direction, angle, cut, revolve_facts.outline_points(data), point, bodies)
    return Skip(shared.REVOLVE_TURN_UNREAD) if found is None else found


def _back(data, operation, frame, outer, point, direction, angles):
    """Degrees a turn to two sides starts back from the sketch by the right hand rule about `direction`, or a Skip."""
    found = _travel_turn(data, operation, frame, outer, point, direction)
    if isinstance(found, Skip):
        return found
    sides = revolve_facts.back_sides(found[0], found[1], direction, angles[0], angles[1])
    if not sides:
        return Skip("The turn of this two sided revolve does not match its measured start face.")
    if len(sides) > 1 and abs(angles[0] - angles[1]) > 1e-9:
        return Skip("The start face of this two sided revolve does not tell which side each angle turns to.",
                    gap_hints.REVOLVE_SIDES)
    return angles[sides[0] - 1]


def _outline_part(profile, outline, point, direction):
    """`(revolve_parts.Part, its way of turning at the sketch plane)` of one outline, or a Skip. The shape is set
    once the plan is known."""
    frame = profile["frame"]
    normal = vec.unit(frame["z"])
    if abs(vec.dot(vec.sub(point, frame["origin"]), normal)) > AXIS_PLANE_TOL \
            or abs(vec.dot(direction, normal)) > AXIS_TILT_TOL:
        return Skip("The revolve axis does not lie in the plane of the sketch, which Orca needs.", causes.REVOLVE_AXIS)
    across = [vec.dot(vec.cross(direction, vec.sub(vec.frame_apply(frame, [p[0], p[1], 0.0]), point)), normal)
              for p in _points(outline.outer)]
    if min(across) < -SIDE_TOL and max(across) > SIDE_TOL:
        return Skip("The outline of this revolve reaches across its axis, which Orca does not turn.",
                    causes.REVOLVE_ACROSS_AXIS)
    loops = [entities_of([loop]) for loop in [outline.outer] + outline.holes]
    if any(found is None for found in loops):
        return Skip("The outline of this revolve has a curve the Orca copy cannot draw yet (it draws lines, arcs, "
                    "circles and splines Fusion gives exactly).")
    turn = _turn(frame, outline.outer, point, direction)
    if isinstance(turn, Skip):
        return turn
    return revolve_parts.Part(frame, [outline.outer] + outline.holes, loops[0], loops[1:], None), turn


def _misses(ctx, operation):
    gap = bool(ctx.left_out)
    what = "cut" if operation == "cut" else "intersect"
    return Skip("This %s does not meet the part as the Orca copy builds it%s, and Orca stops the whole rebuild on a "
                "%s that removes nothing, so it is left out." % (what, " (a step before it is left out)" if gap else "",
                                                                 what),
                gap_hints.AFTER_GAP if gap else causes.MISSES_PART)


def _cut(ctx, item, parts, plan):
    """`(the parts of a cut to write with plan, notes for those left out)` (`revolve_checks.cut_order`), or a Skip."""
    meeting = [part for part in parts if ctx.solid.meets(part.shape)]
    if not meeting:
        return _misses(ctx, "cut")
    found = revolve_checks.cut_order(ctx.solid, meeting, plan, plan.angle.n, plan.angle.text is None)
    if found is None:
        return Skip("An outline of this cut would remove nothing after the outlines cut before it (they turn into "
                    "the same space), and Orca stops the whole rebuild on a cut that removes nothing, so it is left "
                    "out.", causes.REVOLVE_OVERLAP)
    kept, inside = found
    notes = []
    if len(meeting) < len(parts):
        notes.append("%s: %d of its outlines do not meet the part as the Orca copy builds it and are left out."
                     % (label(item), len(parts) - len(meeting)))
    if inside:
        notes.append("%s: %d of its outlines turn wholly inside what its other outlines cut and are left out."
                     % (label(item), inside))
    return kept, notes


def revolve(ctx, step):
    item, data = step.brought, step.brought_data
    operation = data.get("operation")
    if operation == "newComponent":
        return Skip("This revolve makes a new component, which is not copied.", gap_hints.NEW_COMPONENT)
    if operation not in revolve_parts.SOLID_MODES:
        return Skip("This kind of revolve is not copied.")
    if not ctx.has_body and operation in ("cut", "intersect"):
        return Skip("The part this %s works on is not in the copy." % ("cut" if operation == "cut" else "intersect"),
                    gap_hints.AFTER_GAP)
    profiles = data.get("profiles") or []
    if not profiles:
        return Skip("This revolve has no outline that could be read.")
    for profile in profiles:
        problem = _profile_problem(profile)
        if problem:
            return Skip(problem)
    others = roles.new_bodies(item, [ctx.target])
    if operation == "newBody" and len(profiles) > 1 and others:
        return Skip("This revolve makes several bodies, and the Orca copy cannot tell which outline is the part.")
    if operation == "cut" and others:
        return Skip("This cut splits the part into pieces, which is not copied to Orca yet.")
    axis = data.get("axis") or {}
    if axis.get("foreign"):
        return Skip("The revolve axis belongs to another component and could not be brought into the part's place, "
                    "which is not copied to Orca.", gap_hints.OTHER_COMPONENT)
    if not isinstance(axis.get("point"), (list, tuple)) or not isinstance(axis.get("dir"), (list, tuple)):
        return Skip("The revolve axis could not be read as a line.")
    angle = _angle(ctx, item, data.get("extent"))
    if isinstance(angle, Skip):
        return angle
    point, direction = [float(c) for c in axis["point"]], vec.unit(axis["dir"])
    outlines, parts, turns = [], [], []
    for profile in profiles:
        outline = outlines_of(profile)
        if outline is None:
            return Skip("The outline of this revolve could not be read.")
        found = _outline_part(profile, outline, point, direction)
        if isinstance(found, Skip):
            return found
        outlines.append(outline)
        parts.append(found[0])
        turns.append(found[1])
    first, frame = outlines[0], profiles[0]["frame"]
    total, sides = angle.total, angle.sides
    if total.n < FULL_TURN_DEG and any(vec.length(vec.sub(t, turns[0])) > 1e-6 for t in turns[1:]):
        return Skip("The outlines of this revolve do not all turn the same way at its sketch (they lie on different "
                    "sides of the axis), and the Orca copy cannot tell how each one turned.",
                    causes.REVOLVE_OUTLINE_SIDES)
    sense, start = 1.0, 0.0
    if isinstance(sides, tuple):
        back = _back(data, operation, frame, first.outer, point, direction, sides)
        if isinstance(back, Skip):
            return back
        start = -back
    elif total.n < FULL_TURN_DEG:
        sense = _sense(data, operation, frame, first.outer, point, direction, total.n, sides == "symmetric",
                       revolve_facts.body_boxes(item))
        if isinstance(sense, Skip):
            return sense
        if sides == "symmetric":
            start = -total.n / 2.0
    turn_axis = vec.scale(direction, sense)
    plans = [revolve_parts.Plan(point, turn_axis, total, start)]
    if angle.per_side is not None and operation != "intersect":
        # A symmetric angle that follows sizes: two revolves from the sketch plane, one each way, unless they cannot
        # be cut one after the other.
        plans.insert(0, revolve_parts.Plan(point, turn_axis, _half(angle.per_side), 0.0, (False, True)))
    for plan in plans:
        for part in parts:
            part.shape = revolve_checks.whole(part, plan, plan.angle.n)
        found = _cut(ctx, item, parts, plan) if operation == "cut" else (parts, [])
        if isinstance(found, Skip):
            if plan is plans[-1]:
                return found
            continue
        found, notes = found
        floor = revolve_checks.angle_floor(ctx.solid, found, plan, operation)
        if floor is None and plan is not plans[-1]:
            continue
        if floor is None:
            # How far the angle may shrink before a revolve misses the part cannot be told: it keeps its number.
            ctx.doubt(plan.angle.reads, "%s: the copy cannot tell how far its angle may change before it no longer "
                      "meets the part, so the angle keeps its number in Orca" % label(item))
            plan.angle, floor = Quantity(plan.angle.n), 0.0
        parts = found
        break
    for note in notes:
        ctx.note(note)
    if operation == "intersect" and not any(ctx.solid.meets(part.shape) for part in parts):
        return _misses(ctx, operation)
    if operation != "cut" and revolve_checks.overlap(parts):
        return Skip("Two outlines of this revolve turn into the same space, and the Orca copy cannot tell that Orca "
                    "joins such turns as Fusion does, so it is left out.", causes.REVOLVE_OVERLAP)
    if len(plan.flips) == 1:
        _fixed_symmetric(ctx, item, angle)

    name = label(item)
    kept_refs.mark(ctx, item, axis, "turns about")
    written = revolve_parts.write(ctx, name, parts, plan, operation)
    revolve_checks.tell_angle(ctx, written, floor)
    for profile in profiles:
        projection_doubts(ctx, item, profile, outlines_of(profile))
        loose = profile_sizes(ctx, profile)
        if loose:
            ctx.doubt(loose, "%s: the outline from %s keeps its drawn numbers: Orca can tie only the size of a plain "
                      "rectangle or circle to a variable" % (name, profile.get("sketch") or "the sketch"))
        moving = reach.sketch_plane_sizes(ctx.table, ctx.capture.get("items") or [], item, profile)
        ctx.doubt(moving, "%s: its sketch sits on a plane or face that moves with it, and Orca cannot move a sketch "
                  "plane with a variable" % name)
    return written


HANDLERS = {"RevolveFeature": revolve}
