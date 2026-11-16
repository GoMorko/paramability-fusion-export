"""Move handler (MoveFeature).

A Move carries bodies to another place. It becomes a `move` step in the list of the body it moves: the app applies the
move to the steps before it, and every later value stays as Fusion measured it at that point of the timeline.

What the body really did is measured: the first vertices of the body before and after the item. A Move along the axes,
a rotation and a free move also say what they were made from, and that must agree with the measured points, or the Move
is refused. Their distances and angles follow sizes. The other kinds are written as the measured numbers. What
they follow (a point, an edge) may move with any size, whether a written step reads it or not, so every size is marked.

After the step, the walk's placers stand where the Move put them (`moved_placer.MoveMaker`), so later picks follow sizes.
"""
import math

from ...design_model.steps.move import FIT_TOL_MM, ROTATION_TOL, spread
from ...design_model.steps.move import fit as fit_move
from ...design_model.values import Quantity
from ...geometry import rigid, vec
from ...package.numbers import round9
from .. import repeat, values
from ..faces.moved_placer import MoveMaker
from ..faces.slabs import IDENTITY_ROWS, Motion
from ..result import Refusal, StepResult

NO_MOVE_MM = 1e-9


def carries(motion, before, after):
    """True when `motion` puts each of the points `before` on the point of `after` at its place in the list."""
    return len(before) == len(after) and all(vec.close(motion.numbers(p), q, FIT_TOL_MM) for p, q in zip(before, after))


def fit(before, after):
    """The rigid `Motion` that carries the points `before` onto `after`, or None (`design_model/steps/move.py`)."""
    found = fit_move(before, after)
    return None if found is None else Motion(found.rows, found.offset)


def _turn_of(rows):
    """`(axis, degrees)` of a rotation, or None when it turns nothing."""
    if vec.close([list(row) for row in rows], [list(row) for row in IDENTITY_ROWS], ROTATION_TOL):
        return None
    axis = [rows[2][1] - rows[1][2], rows[0][2] - rows[2][0], rows[1][0] - rows[0][1]]
    cosine = (rows[0][0] + rows[1][1] + rows[2][2] - 1.0) / 2.0
    degrees = math.degrees(math.atan2(vec.length(axis) / 2.0, cosine))
    if vec.length(axis) > ROTATION_TOL:
        return vec.unit(axis), degrees
    # A half turn: each column of the rotation plus one is a multiple of the axis.
    columns = [[rows[i][j] + (1.0 if i == j else 0.0) for i in range(3)] for j in range(3)]
    return vec.unit(max(columns, key=vec.length)), degrees


def written(motion):
    """The `move` step of a Motion, in plain numbers. The turn is about the origin, and comes before the shift."""
    step = {"kind": "move"}
    turn = _turn_of(motion.rows)
    if turn is not None:
        step["turn"] = {"axisPoint": [0.0, 0.0, 0.0], "axis": [round9(c) for c in turn[0]], "angleDeg": round9(turn[1])}
    shift = [q.n for q in motion.shift]
    if turn is None or vec.length(shift) > NO_MOVE_MM:
        step["translate"] = [round9(c) for c in shift]
    return step


def _name(item):
    return item.get("name") or "This move"


def _numbers(motion):
    """`(step, motion)` for a move written as numbers; the step is None when it moves nothing."""
    moves = _turn_of(motion.rows) is not None or vec.length([q.n for q in motion.shift]) > NO_MOVE_MM
    return (written(motion) if moves else None), motion


def _is_vector(value):
    return isinstance(value, list) and len(value) == 3 and all(
        isinstance(c, (int, float)) and not isinstance(c, bool) for c in value)


def _space_rows(ctx, data):
    """The rows that turn the Move's distances into the frame the steps are written in, or None when that cannot be
    told. Distances in design space are turned by the place of the component."""
    space = data.get("is_design_space")
    frame = ctx.component_frame() if space is not False else None
    if frame is None:
        return IDENTITY_ROWS
    rows = rigid.move_from_frame(frame).inverse().rows
    return rows if space or rows == IDENTITY_ROWS else None


def _translate_xyz(item, ctx, data, before, after):
    raw = data.get("translate")
    rows = _space_rows(ctx, data)
    if not _is_vector(raw) or rows is None:
        return Refusal("The distances of %s could not be read." % _name(item))
    axes = Motion(rows)
    if not carries(Motion(shift=axes.turn_vector(raw)), before, after):
        return Refusal("%s does not move the body as its distances say." % _name(item))
    shift = axes.quantities([values.quantity(ctx, item, "translate.%d" % n, raw[n]) for n in range(3)])
    motion = Motion(shift=shift, by=_name(item))
    if not motion.moves and vec.length([q.n for q in shift]) <= NO_MOVE_MM:
        return None, motion
    return {"kind": "move", "translate": [q.json() for q in shift]}, motion


def _sense(point, direction, angle, before, after):
    """Which way the Move turns about `direction`: +1 or -1, 0 when the points cannot tell, None when neither fits."""
    fits = [sign for sign in (1, -1) if carries(Motion.turn(point, vec.scale(direction, sign), angle), before, after)]
    if not fits:
        return None
    return fits[0] if len(fits) == 1 else 0


def _rotate(item, ctx, data, before, after):
    axis, angle = data.get("axis") or {}, data.get("angle_deg")
    if "point" not in axis or vec.length(axis.get("dir") or [0.0]) < NO_MOVE_MM or not isinstance(angle, (int, float)):
        return Refusal("The axis or the angle of %s could not be read." % _name(item))
    direction, point = vec.unit(axis["dir"]), axis["point"]
    sense = _sense(point, direction, angle, before, after)
    if sense is None:
        return Refusal("%s does not turn the body as its axis and angle say." % _name(item))
    if sense:
        angle_q = values.quantity(ctx, item, "angle_deg", angle, dim="angle")
    else:
        values.pin(ctx, item, "angle_deg", "the corners of the body do not tell which way %s turns" % _name(item))
        angle_q = Quantity(angle)
    direction = vec.scale(direction, sense or 1)
    moved = repeat.axis_shift(ctx, item, axis, direction)
    motion = repeat.turn_motion(point, moved, direction, angle, angle_q.reads, _name(item))
    if not angle_q.sized and _turn_of(motion.rows) is None:
        return None, motion
    axis_point = [q.plus(c).json() if q.sized else round9(c) for q, c in zip(moved, point)]
    return {"kind": "move", "turn": {"axisPoint": axis_point, "axis": [round9(c) for c in direction],
                                     "angleDeg": angle_q.json()}}, motion


def _free(item, ctx, data, before, after):
    frame = data.get("transform")
    if frame is None:
        return _fitted(item, before, after)
    if rigid.frame_problem(frame):
        return Refusal("%s mirrors or scales the body, which a move cannot copy." % _name(item))
    found = rigid.move_from_frame(frame)
    motion = Motion(found.rows, found.offset)
    if not carries(motion, before, after):
        return Refusal("%s does not move the body as its transform says." % _name(item))
    return _numbers(motion)


def _fitted(item, before, after):
    """`(step, motion)` from the measured points alone, or a Refusal."""
    if spread(before) is None:
        return Refusal("The body of %s has too few corners to tell how it moved." % _name(item))
    motion = fit(before, after)
    if motion is None:
        return Refusal("%s does not move the body rigidly." % _name(item))
    return _numbers(motion)


def _follows_a_point(item, ctx, data, before, after):
    found = _fitted(item, before, after)
    if not isinstance(found, Refusal):
        as_numbers = "%s is written as the numbers Fusion measured, so it cannot follow this" % _name(item)
        for path in data.get("params") or {}:
            values.pin(ctx, item, path, as_numbers)
        ctx.doubt(ctx.table.ticked if ctx.table is not None else (),
                  "%s follows a point or an edge that may move with it, and the copy cannot follow that" % _name(item))
    return found


_WAYS = {"translateXYZ": _translate_xyz, "rotate": _rotate, "free": _free, "pointToPoint": _follows_a_point,
         "pointToPosition": _follows_a_point, "alongEntity": _follows_a_point}


def _points_of(ctx, data):
    """`(points before, points after)` of the walk's body, or None when they were not read."""
    bodies = data.get("bodies") or []
    n = next((n for n, body in enumerate(bodies) if ctx.is_target(body)), None)
    before, after = data.get("points_before") or [], data.get("points_after") or []
    if n is None or n >= len(before) or n >= len(after) or not before[n] or len(before[n]) != len(after[n]):
        return None
    return before[n], after[n]


def handle(ctx, step):
    item, data = step.brought, step.brought_data
    kind = data.get("input_kind")
    if kind == "faces":
        return Refusal("%s moves faces of the body, which is not copied yet." % _name(item))
    points = _points_of(ctx, data) if kind == "bodies" else None
    if points is None:
        return Refusal("The body that %s moves could not be measured." % _name(item))
    way = _WAYS.get(data.get("move_type"))
    if way is None:
        return Refusal("%s moves the body in a way that is not copied yet." % _name(item))
    found = way(item, ctx, data, *points)
    if isinstance(found, Refusal):
        return found
    recipe_step, motion = found
    out = StepResult()
    if recipe_step is not None:
        out.add(recipe_step, [MoveMaker(motion)])
    return out
