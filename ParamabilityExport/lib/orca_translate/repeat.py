"""Rectangular and circular patterns and mirrors as Orca Pattern and Mirror features.

Orca repeats whole bodies: its Pattern copies a body and joins the copies into it, its Mirror joins a body with its
mirror image. A Fusion pattern or mirror of features repeats some steps only, so the copy writes those steps again as
a tool body (`tools.of_steps`; a Combine among the sources writes its tools again), repeats that body, and adds it
to the part or cuts it away with a Boolean, as the steps did. Steps that add and steps that remove get one tool body
each, in timeline order. A source that rounds or chamfers edges leaves the pattern out, since the copies would lack
the rounds. A hole whose place follows a variable keeps its place: the copies are drilled where it is now.

- Rectangular: one Orca Pattern per direction (Orca's linear pattern has one), `pattern_count` and `pattern_spacing`
  bound to the quantity and the distance. A distance measured over the whole extent becomes a spacing of
  `distance / (count - 1)`. A direction that spreads copies to both sides of the original is two tool bodies, one
  repeated each way from the original, with counts that follow the quantity as Fusion splits it: `(n + 1) / 2` on the
  side with the extra copy and `n / 2` on the other (Orca rounds a half up, so these give n // 2 + 1 and
  (n - 1) // 2 + 1). Orca's pattern cannot leave copies out, so a pattern with suppressed copies is left out.
- Circular: `pattern_circular` about the axis, `pattern_angle` and `pattern_count` bound to the angle and quantity.
  Orca spreads the copies over the angle with both ends kept, and over a full turn evenly, as Fusion does. A turn to
  both sides of the original is two tool bodies with their numbers fixed.
- Mirror of features: the tool body joined with its mirror image. Mirror of the body joined to it: an Orca Mirror of
  the part (Add). A mirror or pattern of bodies that leaves separate copies does not change the part.
- Pattern along a path: Fusion's path pattern has no Orca handler, so it is left out by its step type.

The copies the shape check works with (`solid.Moved`) are the ones Orca builds from the numbers written.
"""
import math
from itertools import product

from ..capture_model import gap_hints, tool_items
from ..capture_model.capture import same_body
from ..geometry import vec
from ..orca_recipe.enums import BooleanMode, FeatureType
from ..params.expressions.text import format_number
from . import causes, kept_refs
from ..design_model import design, edges, reach
from ..design_model.problem import is_problem
from ..design_model.steps import pattern_places
from ..design_model.steps.repeat import (FIT_TOL_MM, data_in_component, is_identity, is_identity_rotation,
                                        mirror_plane, reach as symmetric_reach, solve_lattice)
from ..design_model.values import Quantity
from ..design_model import words as shared
from ..results.verdicts import LEFT_OUT, SKIPPED
from .solid import ADD, Moved, Solid
from .steps import Skip
from .tools import OPERATIONS, Pass, boolean, build, feature, hold_place, label, of_steps, step_mode

IDENTITY = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
ANGLE_TOL_DEG = 1e-6
FULL_TURN_DEG = 360.0
LEAVES_COPIES_OUT = "Some copies of this %s are suppressed, and Orca's pattern cannot leave copies out."


def _text(value):
    return value.text if value.text is not None else format_number(value.n)


def _divided(value, by, text):
    """`value / by`, where `by` is a number and `text` its formula (or None)."""
    number = value.n / by
    if value.text is None and text is None:
        return Quantity(number)
    return Quantity(number, "(%s) / (%s)" % (_text(value), text or format_number(by)), value.reads)


def _square(n):
    helper = [0.0, 0.0, 1.0] if abs(n[2]) < 0.9 else [1.0, 0.0, 0.0]
    return vec.unit(vec.cross(helper, n))


def _plane_along(ctx, origin, x_axis):
    """An Orca plane whose x axis is `x_axis` (a linear pattern runs along it)."""
    normal = _square(x_axis)
    return ctx.place.plane(origin, x_axis, vec.cross(normal, x_axis), normal)


def _plane_about(ctx, origin, normal):
    """An Orca plane whose normal is `normal` (a circular pattern turns about it, a mirror reflects across it)."""
    x_axis = _square(normal)
    return ctx.place.plane(origin, x_axis, vec.cross(normal, x_axis), normal)


def _turn_rows(axis, degrees):
    columns = [vec.rotate(e, axis, degrees) for e in ([1, 0, 0], [0, 1, 0], [0, 0, 1])]
    return [[columns[j][i] for j in range(3)] for i in range(3)]


def _turn(point, axis, degrees):
    """`(rows, offset)` of a turn about the line through `point` along `axis`."""
    rows = _turn_rows(axis, degrees)
    return rows, vec.sub(point, [sum(rows[i][k] * point[k] for k in range(3)) for i in range(3)])


def _reflection(point, normal):
    n = vec.unit(normal)
    rows = [[(1.0 if i == j else 0.0) - 2.0 * n[i] * n[j] for j in range(3)] for i in range(3)]
    return rows, vec.scale(n, 2.0 * vec.dot(point, n))


def _bind_count(ctx, made, value, where):
    ctx.bind(made, "pattern_count", value, where)
    made.pattern_count = int(round(value.n))


def _params_doubt(ctx, item, used, why):
    """Sizes behind the step's parameters that no written field follows get `why`."""
    for path, found in design.params_of(item).items():
        if path not in used and isinstance(found, dict) and found.get("name"):
            ctx.doubt(ctx.depends([found["name"]]), why)


# ---- what is repeated ------------------------------------------------------------------------------------------

def _covered(ctx, indexes, what):
    """Timeline indexes of the steps that built the tools of each Combine among the sources (repeated through the
    Combine), or a Skip when some of them are not sources."""
    chosen, covered = set(indexes), set()
    for index in indexes:
        source = _item(ctx, index)
        tools = _tools_of(source)
        if tools is None:
            continue
        for tool in tools:
            if not isinstance(tool, dict):
                continue
            found = tool_items.built_by(ctx.capture["items"], tool, source)
            if not found or not found <= chosen:
                return Skip("This %s repeats %s but not every step that builds its tool body %s." % (
                    what, label(source), tool.get("name") or ""))
            covered |= found
    return covered


def _tools_of(item):
    """The tool body records of a source that takes tool bodies (a Combine: its data lists them), else None."""
    tools = design.as_read(item).brought_data.get("tools") if item is not None else None
    return tools if isinstance(tools, list) else None


def _item(ctx, index):
    return next((i for i in ctx.capture["items"] if i.get("index") == index), None)


def _verdict(ctx, index):
    return next((v for v in ctx.items if v.get("index") == index), None)


def sources(ctx, data, what):
    """The sources of a repeat of features (`data`, the data of its step) as groups `(mode, kind, payload)` in
    timeline order: kind "steps" with the timeline indexes of copied steps that work the same way (adding or
    removing), or "combine" with a Combine item. A Skip when a source cannot be repeated."""
    indexes = sorted(i for i in data.get("sources") or [] if isinstance(i, int))
    if not indexes:
        return Skip("This %s has no features to repeat." % what)
    covered = _covered(ctx, indexes, what)
    if isinstance(covered, Skip):
        return covered
    groups = []
    for index in indexes:
        if index in covered:
            continue
        source = _item(ctx, index)
        verdict = _verdict(ctx, index)
        if verdict is not None and verdict.get("verdict") == LEFT_OUT:
            return Skip("A step this %s repeats (%s) is left out of the Orca copy." % (what, verdict.get("name")),
                        gap_hints.AFTER_GAP)
        if _tools_of(source) is not None:
            mode = OPERATIONS.get(design.as_read(source).brought_data.get("operation"))
            if mode not in (BooleanMode.ADD, BooleanMode.CUT):
                return Skip(shared.REPEAT_TOOL_KEEPS % (label(source), what))
            groups.append((mode, "combine", source))
            continue
        if not ctx.written.get(index):
            if verdict is not None and verdict.get("verdict") == SKIPPED and source is not None \
                    and source.get("suppressed"):
                continue
            return Skip("A step this %s repeats is not part of the exported body." % what)
        mode = step_mode(ctx, index)
        if isinstance(mode, tuple):
            return Skip("This %s cannot be copied: %s." % (what, mode[0]), mode[1])
        if groups and groups[-1][0] == mode and groups[-1][1] == "steps":
            groups[-1][2].append(index)
        else:
            groups.append((mode, "steps", [index]))
    if not groups:
        return Skip("This %s repeats no step the Orca copy holds." % what)
    return groups


def _tool(ctx, kind, payload, name):
    """A tool body of one group of sources, or a Skip. Returns (body, holes whose place follows variables)."""
    if kind == "steps":
        return of_steps(ctx, payload, name)
    built = []
    for tool in _tools_of(payload) or []:
        if isinstance(tool, dict):
            body = build(ctx, tool, payload)
            if isinstance(body, Skip):
                return body
            built.append(body)
    if not built:
        return Skip("The tool bodies of %s could not be read." % label(payload))
    ctx.push(built[0])
    for other in built[1:]:
        boolean(ctx, other, BooleanMode.ADD, "%s: tools" % name)
    ctx.pop()
    return built[0], []


def write(ctx, item, groups, layouts, copies, what):
    """For each group of sources and each layout: a tool body of the sources, its copies written on it by
    `copies(ctx, tool, layout, name)` (which returns the `(rows, offset)` of every copy, the original included), and
    a Boolean into the part. Returns the features written, or a Skip with nothing written."""
    start = len(ctx.features)
    mark = ctx.checkpoint()
    name = label(item)
    total = len(groups) * len(layouts)
    placed = []
    number = 0
    for mode, kind, payload in groups:
        for layout in layouts:
            number += 1
            tag = name if total == 1 else "%s (%d)" % (name, number)
            made = _tool(ctx, kind, payload, tag)
            if isinstance(made, Skip):
                ctx.rollback(mark)
                return Skip("This %s cannot be copied. %s" % (what, made.reason), made.cause)
            tool, holes = made
            placed += [h for h in holes if all(h is not p for p in placed)]
            seed = tool.solid.copy()
            moves = copies(ctx, tool, layout, tag)
            tool.solid = Solid([(ADD, Moved(seed, rows, offset)) for rows, offset in moves])
            boolean(ctx, tool, mode, tag)
    if placed and len(ctx.scopes) > 1:
        # Inside a tool body a later step can still undo this one (`Context.rollback`), and that does not bind a
        # hole place again, so the place is not unbound there.
        ctx.rollback(mark)
        return Skip("This %s inside a tool body repeats a hole whose place follows a variable, which its copies "
                    "cannot follow." % what, causes.HOLE_PLACE_IN_TOOL)
    # The copies are drilled where the holes are now, so the holes keep that place too: else a variable change
    # moves the hole and leaves a copy at the old place.
    for hole in placed:
        hold_place(ctx, hole, "%s: the copies of %s cannot follow its place, so the hole keeps its place in Orca" % (
            name, hole.name))
    return ctx.features[start:]


def _separate_copies(ctx, data, what):
    """A pattern or mirror of bodies (`data`, the data of its step) that leaves its copies as separate bodies."""
    sources_ = [b for b in data.get("source_bodies") or [] if isinstance(b, dict)]
    if sources_ and not any(same_body(b, ctx.target) for b in sources_):
        return Skip("This body is a copy made by a %s of another body, which is not copied." % what)
    if len(ctx.scopes) > 1:
        return Skip("A %s of bodies inside a tool body is not copied." % what)
    return Pass("Its copies are separate bodies; this part does not change.")


# ---- rectangular -----------------------------------------------------------------------------------------------

class _Part:
    """One run of copies from the original along `direction`: `count` copies (the original included) `step` apart,
    with their Values."""

    def __init__(self, direction, count, count_value, step, step_value):
        self.direction, self.count, self.count_value = direction, count, count_value
        self.step, self.step_value = step, step_value


def _directions(item, data):
    """`(which, forward unit direction, quantity, |distance|, symmetric)` of each direction that makes copies, or
    a Skip."""
    out = []
    for which in ("one", "two"):
        n = int(data.get("quantity_" + which) or 1)
        raw = float(data.get("distance_" + which) or 0.0)
        if n <= 1 or abs(raw) < 1e-9:
            continue
        place = data.get("direction_%s_place" % which)
        if isinstance(place, dict) and place.get("foreign"):
            return Skip("The direction of this pattern comes from another component and could not be brought into "
                        "the part's place, which is not copied to Orca.", gap_hints.OTHER_COMPONENT)
        direction = data.get("direction_" + which)
        if not isinstance(direction, (list, tuple)) or vec.length(direction) < 1e-9:
            return Skip(shared.PATTERN_DIRECTION_UNREAD)
        out.append((which, vec.scale(vec.unit(direction), 1.0 if raw > 0 else -1.0), n, abs(raw),
                    bool(data.get("symmetric_" + which))))
    if not out:
        return Skip(shared.PATTERN_NO_COPIES)
    if len(out) == 2 and 1.0 - vec.dot(out[0][1], out[1][1]) ** 2 < 1e-9:
        return Skip(shared.PATTERN_ONE_LINE)
    return out


def _mark_directions(ctx, item, directions):
    """Mark the sizes that may turn each direction taken from the part (an edge, an axis, a sketch line,
    `edges.direction_sizes`): Orca keeps the direction it has now."""
    if ctx.table is None:
        return
    for which, *_ in directions:
        names = edges.direction_sizes(ctx.table, ctx.capture, item, which)
        if names:
            noun = reach.direction_kind(item, which)
            ctx.doubt(names, shared.kept_in_place(shared.ref_phrase(item, {"type": noun, "own": True},
                                                                    "spreads copies along")))


def _gaps(n, symmetric):
    return max(n // 2, 1) if symmetric else n - 1


def _grid(data, elements, directions):
    """`(distance kind, steps, places)`: how the distance is measured, the step of each direction and the steps of
    each copy from the original; or a Skip when the copies do not sit on such a grid."""
    kind = data.get("distance_type")
    for guess in ([kind] if kind in ("spacing", "extent") else ["spacing", "extent"]):
        steps = [d if guess == "spacing" else d / _gaps(n, sym) for _, _, n, d, sym in directions]
        places, fits = [], True
        for element in elements:
            frame = element["frame"]
            if not is_identity_rotation(frame):
                return Skip(shared.PATTERN_TURNED, causes.COPIES_TURNED)
            indexes, residual = solve_lattice(frame["origin"], [(d[1], s) for d, s in zip(directions, steps)])
            if residual > FIT_TOL_MM:
                fits = False
                break
            places.append(tuple(indexes))
        if fits:
            return guess, steps, places
    return Skip(shared.PATTERN_UNEVEN_GRID, causes.COPIES_UNEVEN)


def _parts(ctx, item, direction, kind, step, places):
    """The runs of one direction (`_Part`), or a Skip."""
    which, forward, n, distance, symmetric = direction
    name = label(item)
    count_value = ctx.quantity(item, "quantity_" + which, n, "scalar")
    distance_value = ctx.quantity(item, "distance_" + which, distance).magnitude()
    if kind == "spacing":
        step_value = distance_value
    elif not symmetric:
        text = "max((%s) - 1, 1)" % _text(count_value) if count_value.text is not None else None
        step_value = _divided(distance_value, n - 1, text)
        if text is not None:
            step_value.reads = tuple(dict.fromkeys(step_value.reads + count_value.reads))
    else:
        step_value = _divided(distance_value, n // 2, None)
        if count_value.text is not None:
            ctx.doubt(count_value.reads, "%s spreads its copies over a set reach to both sides, which Orca follows "
                      "only at this count" % name)
            count_value = Quantity(n)
    if not symmetric:
        if places and max(places) <= 0:
            # Fusion can run the copies against the direction it stores.
            forward, places = vec.scale(forward, -1.0), [-p for p in places]
        if any(p < 0 or p >= n for p in places):
            return Skip(shared.PATTERN_COUNT, causes.COPIES_UNEVEN)
        return [_Part(forward, n, count_value, step, step_value)]
    found = symmetric_reach(list(places), n)
    if found is None:
        return Skip(shared.PATTERN_RULE, causes.COPIES_UNEVEN)
    back, ahead = found
    longer = "((%s) + 1) / 2" % _text(count_value)
    shorter = "(%s) / 2" % _text(count_value)
    extra_ahead = ahead >= back
    out = []
    for sign, steps, formula in ((1.0, ahead, longer if extra_ahead else shorter),
                                 (-1.0, back, shorter if extra_ahead else longer)):
        value = Quantity(steps + 1, formula, count_value.reads) if count_value.text is not None else Quantity(steps + 1)
        if steps or value.text is not None:
            out.append(_Part(vec.scale(forward, sign), steps + 1, value, step, step_value))
    return out


def _linear_copies(ctx, tool, layout, name):
    moves = [(IDENTITY, [0.0, 0.0, 0.0])]
    for n, part in enumerate(layout, start=1):
        made = feature(FeatureType.PATTERN, "%s: pattern%s" % (name, " %d" % n if len(layout) > 1 else ""),
                       plane=_plane_along(ctx, [0.0, 0.0, 0.0], part.direction), target_body=tool.index)
        _bind_count(ctx, made, part.count_value, "%s count" % made.name)
        ctx.bind(made, "pattern_spacing", part.step_value, "%s spacing" % made.name)
        ctx.add(made)
        moves = [(IDENTITY, vec.add(offset, vec.scale(part.direction, k * part.step)))
                 for _, offset in moves for k in range(part.count)]
    return moves


def rectangular(ctx, step):
    item, data = step.brought, step.brought_data
    if data.get("entity_type") == "bodies":
        return _separate_copies(ctx, data, "pattern")
    if data.get("entity_type") != "features":
        return Skip("Patterns of faces are not copied to Orca yet.", gap_hints.REPEAT_FACES)
    groups = sources(ctx, data, "pattern")
    if isinstance(groups, Skip):
        return groups
    raw = data
    data = data_in_component(data, ctx.component_frame(), merge=True)
    elements = data.get("elements") or []
    if not elements:
        return Skip(shared.PATTERN_COPIES_UNREAD)
    if data.get("suppressed_ids") or any(e.get("suppressed") for e in elements):
        return Skip(LEAVES_COPIES_OUT % "pattern", causes.COPIES_SUPPRESSED)
    if not any(is_identity(e["frame"]) for e in elements):
        return Skip(shared.PATTERN_ORIGINAL_LOST)
    directions = _directions(item, data)
    if isinstance(directions, Skip):
        return directions
    _mark_directions(ctx, item, directions)
    grid = _grid(data, elements, directions)
    if isinstance(grid, Skip):
        return grid
    kind, steps, steps_of_copies = grid
    full = 1
    for _, _, n, _, _ in directions:
        full *= n
    listed = data if any(int(raw.get("quantity_" + w) or 1) > 1 and abs(float(raw.get("distance_" + w) or 0.0)) < 1e-9
                         for w in ("one", "two")) else data_in_component(raw, ctx.component_frame())
    found = pattern_places.grid_places(listed["elements"], [(d[1], s) for d, s in zip(directions, steps)], full, data)
    if found is not None:
        return Skip(found.words, causes.COPIES_UNEVEN)
    source = pattern_places.source_faces(data)
    if any(pattern_places.agrees(source, e, e["frame"]) is False for e in elements):
        return Skip(shared.PATTERN_FACES_DISAGREE, causes.COPIES_UNEVEN)
    runs = []
    for k, direction in enumerate(directions):
        found = _parts(ctx, item, direction, kind, steps[k], [p[k] for p in steps_of_copies])
        if isinstance(found, Skip):
            return found
        runs.append(found)
    used = {"%s_%s" % (key, d[0]) for d in directions for key in ("quantity", "distance")}
    made = write(ctx, item, groups, list(product(*runs)), _linear_copies, "pattern")
    if not isinstance(made, Skip):
        _params_doubt(ctx, item, used, "%s: a direction without copies" % label(item))
    return made


# ---- circular --------------------------------------------------------------------------------------------------

def _turn_of(frame, axis, point):
    """The signed turn of an element frame about `axis` through `point` in degrees, or None when the copy is not
    such a turn."""
    rows = [[frame[name][i] for name in "xyz"] for i in range(3)]

    def image(v):
        return [sum(rows[i][k] * v[k] for k in range(3)) for i in range(3)]

    if not vec.close(image(axis), axis, 1e-6):
        return None
    moved = vec.add(image(point), vec.sub(frame["origin"], [0.0, 0.0, 0.0]))
    if not vec.close(moved, point, FIT_TOL_MM):
        return None
    v = _square(axis)
    w = image(v)
    return math.degrees(math.atan2(vec.dot(axis, vec.cross(v, w)), vec.dot(v, w)))


def _copy_numbers(turns, delta, count, sign, symmetric):
    """The copy number of each turn (signed when `symmetric`), or None when a turn is not a whole number of steps."""
    out = []
    for turn in turns:
        found = None
        for wrap in (0.0, -FULL_TURN_DEG, FULL_TURN_DEG):
            k = round((sign * turn + wrap) / delta)
            if abs(sign * turn + wrap - k * delta) <= ANGLE_TOL_DEG * 10 and (
                    abs(k) < count if symmetric else 0 <= k < count + 1):
                found = k % count if not symmetric and k == count else k
                break
        if found is None:
            return None
        out.append(found)
    return out


def circular(ctx, step):
    item, data = step.brought, step.brought_data
    if data.get("entity_type") == "bodies":
        return _separate_copies(ctx, data, "pattern")
    if data.get("entity_type") != "features":
        return Skip("Patterns of faces are not copied to Orca yet.", gap_hints.REPEAT_FACES)
    groups = sources(ctx, data, "pattern")
    if isinstance(groups, Skip):
        return groups
    axis = data.get("axis") or {}
    if axis.get("foreign"):
        return Skip("The axis of this pattern belongs to another component and could not be brought into the "
                    "part's place, which is not copied to Orca.", gap_hints.OTHER_COMPONENT)
    if not isinstance(axis.get("point"), (list, tuple)) or not isinstance(axis.get("dir"), (list, tuple)):
        return Skip("The turning axis of this pattern could not be read as a line.")
    n = int(data.get("quantity") or 1)
    if n < 2:
        return Skip(shared.PATTERN_NO_COPIES)
    kept_refs.mark(ctx, item, axis, "turns copies about")
    raw = float(data.get("total_angle_deg") or 0.0)
    full = abs(abs(raw) - FULL_TURN_DEG) <= ANGLE_TOL_DEG
    if not full and not 0 < abs(raw) < FULL_TURN_DEG:
        return Skip(shared.PATTERN_ANGLE_UNREAD)
    delta = FULL_TURN_DEG / n if full else abs(raw) / (n - 1)
    data = data_in_component(data, ctx.component_frame())
    elements = data.get("elements") or []
    if not elements:
        return Skip(shared.PATTERN_COPIES_UNREAD)
    if data.get("suppressed_ids") or any(e.get("suppressed") for e in elements):
        return Skip(LEAVES_COPIES_OUT % "pattern", causes.COPIES_SUPPRESSED)
    direction, point = vec.unit(axis["dir"]), [float(c) for c in axis["point"]]
    turns = [_turn_of(e["frame"], direction, point) for e in elements]
    if any(t is None for t in turns):
        return Skip(shared.PATTERN_OFF_AXIS, causes.COPIES_UNEVEN)
    symmetric = bool(data.get("symmetric")) and not full
    name = label(item)
    if not symmetric:
        # Copy `id` sits `id` steps from the original; the element transforms are not always right.
        ids = pattern_places.id_places(data, n)
        if is_problem(ids):
            return Skip(ids.words, causes.COPIES_UNEVEN)
        sign = pattern_places.circular_sign(data, elements, point, direction, delta)
        if is_problem(sign):
            return Skip(sign.words, causes.COPIES_UNEVEN)
    else:
        for sign in (1.0, -1.0):
            numbers = _copy_numbers(turns, delta, n, sign, symmetric)
            if numbers is not None:
                break
        else:
            return Skip(shared.PATTERN_UNEVEN_ROUND, causes.COPIES_UNEVEN)
    axis_dir = vec.scale(direction, sign)
    count_value = ctx.quantity(item, "quantity", n, "scalar")
    angle_value = ctx.quantity(item, "total_angle_deg", abs(raw), "angle").magnitude()
    if not symmetric:
        layouts = [(axis_dir, n, count_value, abs(raw) if not full else FULL_TURN_DEG, angle_value)]
    else:
        found = symmetric_reach(numbers, n)
        if found is None or len(set(numbers)) != n:
            return Skip(shared.PATTERN_RULE, causes.COPIES_UNEVEN)
        source = pattern_places.source_faces(data)
        if any(pattern_places.agrees(source, e, pattern_places.turn_frame(point, axis_dir, k * delta)) is False
               for e, k in zip(elements, numbers)):
            return Skip(shared.PATTERN_FACES_DISAGREE, causes.COPIES_UNEVEN)
        back, ahead = found
        ctx.doubt(count_value.reads + angle_value.reads, "%s turns copies to both sides of the first one, which "
                  "Orca writes with fixed numbers" % name)
        layouts = [(vec.scale(axis_dir, s), steps + 1, Quantity(steps + 1), steps * delta, Quantity(steps * delta))
                   for s, steps in ((1.0, ahead), (-1.0, back)) if steps]

    def copies(ctx_, tool, layout, tag):
        turn_axis, count, count_v, angle, angle_v = layout
        made = feature(FeatureType.PATTERN, "%s: pattern" % tag, plane=_plane_about(ctx_, point, turn_axis),
                       pattern_circular=True, target_body=tool.index)
        _bind_count(ctx_, made, count_v, "%s count" % made.name)
        ctx_.bind(made, "pattern_angle", angle_v, "%s angle" % made.name)
        ctx_.add(made)
        return [_turn(point, turn_axis, k * delta) for k in range(count)]

    return write(ctx, item, groups, layouts, copies, "pattern")


# ---- mirror ----------------------------------------------------------------------------------------------------

def _mirror_feature(ctx, name, plane, body):
    return feature(FeatureType.MIRROR, name, plane=_plane_about(ctx, plane["origin"], plane["normal"]),
                   mode=BooleanMode.ADD, mirror_keep_original=True, target_body=body.index)


def mirror(ctx, step):
    item, data = step.brought, step.brought_data
    found = data.get("plane") or {}
    if found.get("foreign"):
        return Skip("The mirror plane belongs to another component and could not be brought into the part's place, "
                    "which is not copied to Orca.", gap_hints.OTHER_COMPONENT)
    plane = mirror_plane(data)
    if plane is None:
        return Skip(shared.MIRROR_PLANE)
    kept_refs.mark(ctx, item, found, "mirrors across")
    reflect = _reflection(plane["origin"], plane["normal"])
    entity = data.get("entity_type")
    if entity == "bodies":
        if not data.get("combine"):
            return _separate_copies(ctx, data, "mirror")
        if not ctx.has_body:
            return Skip("The part this mirror copies is not in the copy.", gap_hints.AFTER_GAP)
        made = _mirror_feature(ctx, label(item), plane, ctx.scope)
        ctx.add(made)
        ctx.solid.add(ADD, Moved(ctx.solid.copy(), *reflect))
        return [made]
    if entity != "features":
        return Skip(shared.MIRROR_FACES, gap_hints.REPEAT_FACES)
    groups = sources(ctx, data, "mirror")
    if isinstance(groups, Skip):
        return groups

    def copies(ctx_, tool, layout, tag):
        ctx_.add(_mirror_feature(ctx_, "%s: mirror" % tag, plane, tool))
        return [(IDENTITY, [0.0, 0.0, 0.0]), reflect]

    return write(ctx, item, groups, [None], copies, "mirror")


HANDLERS = {"RectangularPatternFeature": rectangular, "CircularPatternFeature": circular, "MirrorFeature": mirror}
