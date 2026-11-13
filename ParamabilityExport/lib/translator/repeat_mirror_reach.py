"""The check that a mirror of the whole body may be written as a mirror of every earlier step.

A whole body mirror in Fusion is "the body joined with its mirror image". The recipe instead mirrors every earlier step
onto the finished part, which agrees only when the body lies on one side of the plane and no cutting tool reaches
across it. These helpers prove that at the current sizes (`body_mirror_problem`) and at the ends of the size ranges
(`keep_one_side`), and the mirror is refused when they cannot.
"""
import math

from ..params.expressions.errors import ExpressionError
from ..params.expressions.evaluation import evaluate
from . import range_check, vec
from .step_kinds import recipe_kind
from .values import Sized, number, numbers_of, reads_in
from .written_loops import spline_points

SIDE_TOL_MM = 1e-4


def side_of_plane(box, origin, normal):
    """+1 or -1 when the whole box lies on that side of the plane (within tolerance), else 0."""
    return vec.box_side(box, origin, normal, SIDE_TOL_MM)


def _arc_circle_points(p0, pm, p1):
    """Corners of the square around the circle through three 2D points (a bound for any arc of that circle)."""
    ax, ay = p0
    bx, by = pm
    cx, cy = p1
    d = 2 * (ax * (by - cy) + bx * (cy - ay) + cx * (ay - by))
    if abs(d) < 1e-12:
        return [p0, pm, p1]
    ux = ((ax * ax + ay * ay) * (by - cy) + (bx * bx + by * by) * (cy - ay) + (cx * cx + cy * cy) * (ay - by)) / d
    uy = ((ax * ax + ay * ay) * (cx - bx) + (bx * bx + by * by) * (ax - cx) + (cx * cx + cy * cy) * (bx - ax)) / d
    r = math.hypot(ax - ux, ay - uy)
    return [[ux + sx * r, uy + sy * r] for sx in (-1, 1) for sy in (-1, 1)]


def _loop_points(loop):
    """2D points whose hull contains the loop, or None for a loop kind this does not know."""
    kind = loop.get("kind")
    if kind in ("circle", "ellipse", "rect"):
        cx, cy = loop["center"]
        if kind == "circle":
            reach = loop["radius"]
        elif kind == "ellipse":
            reach = max(loop["radiusX"], loop["radiusY"])
        else:
            reach = math.hypot(loop["width"], loop["height"]) / 2
        return [[cx + sx * reach, cy + sy * reach] for sx in (-1, 1) for sy in (-1, 1)]
    if kind == "polygon":
        return [[number(c) for c in p] for p in loop["points"]]
    if kind == "profile":
        points, here = [list(loop["start"])], list(loop["start"])
        for seg in loop["segments"]:
            if seg.get("kind") == "arc":
                points += _arc_circle_points(here, seg["through"], seg["to"])
            elif seg.get("kind") == "spline":
                points += spline_points([here] + [list(p) for p in seg.get("through") or []] + [list(seg["to"])])
            points.append(list(seg["to"]))
            here = list(seg["to"])
        return points
    return None


def _placed(on, point2):
    """A sketch point in model coordinates (the sketch y axis is normal x xDir)."""
    y_dir = vec.cross(on["normal"], on["xDir"])
    return vec.add(vec.add(on["origin"], vec.scale(on["xDir"], point2[0])), vec.scale(y_dir, point2[1]))


def _cut_reach(step, as_numbers=numbers_of):
    """(points, margin) with every point of the tool within `margin` mm of one of `points`; None when the tool is
    not bounded by a known rule (through cuts, other loop kinds). `as_numbers` turns the step's formulas into numbers
    (the measured ones by default)."""
    step = as_numbers(step)
    kind = step["kind"]
    if kind == "hole":
        axis = vec.unit(step["direction"])
        if step.get("depth") is None:
            return None
        radius = max([number(step["diameter"])]
                     + [number(step.get(k, {}).get("diameter", 0)) for k in ("counterbore", "countersink")]) / 2
        end = vec.add(step["origin"], vec.scale(axis, number(step["depth"])))
        return [step["origin"], end], radius
    sketch = step.get("sketch") or {}
    if "on" not in sketch:
        return None
    on = {k: (vec.unit(v) if k != "origin" else [number(c) for c in v]) for k, v in sketch["on"].items()}
    outline = _loop_points(sketch["outer"])
    if outline is None:
        return None
    if kind == "revolve":
        axis_point = _placed(on, step["axis"]["point"])
        axis_dir = vec.unit(vec.add(vec.scale(on["xDir"], step["axis"]["dir"][0]),
                                    vec.scale(vec.cross(on["normal"], on["xDir"]), step["axis"]["dir"][1])))
        points, margin = [], 0.0
        for q in outline:
            p = _placed(on, q)
            along = vec.dot(vec.sub(p, axis_point), axis_dir)
            points.append(vec.add(axis_point, vec.scale(axis_dir, along)))
            margin = max(margin, vec.length(vec.sub(p, points[-1])))
        return points, margin
    if kind == "extrude":
        extent = step.get("extent")
        distance = number(step.get("distance"))
        if extent not in ("oneSide", "symmetric") or distance is None:
            return None
        low, high = (0.0, distance) if extent == "oneSide" else (-distance / 2, distance / 2)
        margin = distance * math.tan(math.radians(abs(number(step.get("taperDeg", 0.0)))))
        points = [vec.add(_placed(on, q), vec.scale(on["normal"], h)) for q in outline for h in (low, high)]
        return points, margin
    return None


def _cuts(step, by_id):
    """True when the step (or a step it repeats) removes material."""
    kind = recipe_kind(step["kind"])
    if kind.repeats:
        return any(_cuts(by_id[i], by_id) for i in step["of"])
    return kind.always_cuts or step.get("combine") in ("cut", "intersect")


def body_mirror_problem(data, plane, steps):
    """A plain reason when mirroring every earlier step would not equal the body joined with its image, else None."""
    box = data.get("target_box_before")
    if not box:
        return "The part could not be measured before this mirror."
    origin, normal = plane["origin"], plane["normal"]
    side = side_of_plane(box, origin, normal)
    if not side:
        return "A mirror of the whole body is only copied when the body lies on one side of the plane."
    by_id = {step["id"]: step for step in steps}
    for step in steps:
        if step.get("combine") == "intersect" or recipe_kind(step["kind"]).repeats and _cuts(step, by_id):
            return "A mirror of the whole body is not copied when a cut is repeated or the part is trimmed."
        if not _cuts(step, by_id):
            continue
        reach = _reach_or_none(step, numbers_of)
        if reach is None:
            return "A mirror of the whole body is not copied when a cut has no measurable end."
        points, margin = reach
        if min(side * vec.dot(vec.sub(p, origin), normal) for p in points) - margin < -SIDE_TOL_MM:
            return "A mirror of the whole body is not copied when a cut reaches across the mirror plane."
    return None


def _evaluated(env):
    """A function that turns every formula of a written value into its number at the sizes `env`."""
    def convert(node):
        if isinstance(node, Sized):
            return evaluate(node["expr"], env)
        if isinstance(node, dict):
            return {k: convert(v) for k, v in node.items()}
        if isinstance(node, list):
            return [convert(v) for v in node]
        return node
    return convert


def _step_reads(step, by_id):
    """The Fusion names a step reads, with those of the steps it repeats."""
    found = list(reads_in(step))
    for source in step.get("of") or ():
        if source in by_id:
            found += _step_reads(by_id[source], by_id)
    return tuple(dict.fromkeys(found))


def _reach_or_none(step, as_numbers):
    """`_cut_reach`, or None when the step repeats others or its tool cannot be bounded from what it holds."""
    if recipe_kind(step["kind"]).repeats:
        return None
    try:
        return _cut_reach(step, as_numbers)
    except (KeyError, TypeError, IndexError, ValueError, ZeroDivisionError, OverflowError):
        return None


def _slack(steps, origin, normal, side, as_numbers):
    """How far the tools of the steps stay on `side` of the plane, in mm (negative when one reaches across); None
    when no step has a known reach."""
    worst = None
    for step in steps:
        reach = _reach_or_none(step, as_numbers)
        if reach is None:
            continue
        points, margin = reach
        here = min(side * vec.dot(vec.sub(p, origin), normal) for p in points) - margin
        worst = here if worst is None else min(worst, here)
    return worst


def keep_one_side(ctx, item, plane, steps, side):
    """The body lies on one side of the plane at the current sizes. Mirroring every step equals the body joined with
    its image only while that holds, so each corner of the size ranges is tried too: a step that reaches across the
    plane there, or whose reach is unknown, marks the sizes it reads. The reach of a tool is a bound, so a corner
    only counts when it is worse than the current sizes."""
    table = ctx.table
    reads = tuple(dict.fromkeys(reads_in(steps) + reads_in(plane)))
    if table is None or not reads:
        return
    by_id = {step["id"]: step for step in steps}
    name = item.get("name", "a mirror")
    unknown = [step for step in steps if _reach_or_none(step, numbers_of) is None]
    for step in unknown:
        ctx.doubt(_step_reads(step, by_id), "%s mirrors the whole part, and %s cannot be checked to stay on one side "
                  "of the plane" % (name, step.get("label") or "a step"))
    known = [step for step in steps if all(step is not other for other in unknown)]
    names = {table.size_name(read): read for read in reads}
    why = "%s mirrors the whole part, and at some sizes the part would reach across the plane" % name
    current = None
    for setting in range_check.corners(table, reads):
        try:
            as_numbers = _evaluated(range_check.size_env(table, setting))
            slack = _slack(known, as_numbers(plane["origin"]), plane["normal"], side, as_numbers)
        except (ExpressionError, ValueError, ZeroDivisionError, OverflowError):
            ctx.doubt(reads, "%s mirrors the whole part, and its sizes cannot be tried at the ends of their ranges"
                      % name)
            return
        if not setting:
            current = slack
        elif slack is not None and slack < min(-SIDE_TOL_MM, (current if current is not None else 0.0) - SIDE_TOL_MM):
            ctx.doubt([names[n] for n in setting if n in names], why)
