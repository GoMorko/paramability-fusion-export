"""Path patterns (PathPatternFeature) on one straight line, arc or circle as Orca patterns.

The shared reader (`design_model/steps/path_pattern.py`) gives the plain pattern a path pattern equals:

- A straight line: an Orca linear pattern along the line, written by the rectangular handler (`repeat.rectangular`)
  as a pattern of one direction. The count and the spacing (or the distance over the whole extent) follow variables.
- An arc or a circle whose copies turn with the path: an Orca circular pattern about the axis of the arc, written by
  the circular handler (`repeat.circular`). The angle is the distance along the arc over the radius, as a formula of
  the distance (times the gaps for a spacing), with the turn per mm that the measured copies show. A pattern round
  the whole circle is a full turn whose distance keeps its number.
- An arc whose copies keep their direction: Orca's pattern along a curve on a sketch arc from the start of the path
  to the last copy. Orca moves copy i (without a turn) by the arc's point at i / (count - 1) of its sweep less its
  start point; Fusion moves the copies by the path's point at their distance along the path less its start point.
  The two agree when the arc starts where the path starts and ends at the last copy, which the measured copies must
  show. Orca cannot draw a sketch arc that follows a variable, so the distance keeps its number (the count follows
  only for a distance over the whole extent).

The handlers check the measured copies against the pattern they write, so a copy Fusion put elsewhere leaves the step
out. As in the Paramability export, copies on a round path must start at the start of the path and run along it
(Fusion has been seen to put them off the arc otherwise), and copies that run past an end of the path at the current
sizes leave the step out. The parameter's line tells how far the count or the distance may go before the copies run
past the end (`limits.guard`: Orca would build those copies off the path without an error). The path is written as
numbers, so the sizes that may move or turn it are marked.
"""
import math

from ..capture_model import gap_hints
from ..design_model import design, edges, reach, words as shared
from ..design_model.problem import is_problem
from ..design_model.steps import path_pattern, pattern_places
from ..design_model.steps.repeat import (FIT_TOL_MM, data_in_component, is_identity, is_identity_rotation,
                                        kept_elements)
from ..geometry import vec
from ..orca_recipe.enums import EntityType, FeatureType
from ..orca_recipe.sketch import SketchEntity
from . import causes, limits
from .repeat import IDENTITY, LEAVES_COPIES_OUT, circular, rectangular, separate_copies, sources, write
from .skip import Skip
from .tools import feature, label

FULL_TURN_DEG = 360.0
# Distance (mm) the copies may reach past an end of the path, for numbers rounded in the capture.
END_TOL_MM = 1e-3
# A start point (a share of the path's length) up to this counts as the start of the path.
START_TOL = 1e-9
# An angle (degrees) a pattern along a whole circle stays under: at exactly a full turn Orca spreads the copies evenly.
CLOSED_TOP_DEG = FULL_TURN_DEG - 1e-6
# The frame of a copy that is not moved, for the checks of its faces.
IDENTITY_FRAME = {"origin": [0.0, 0.0, 0.0], "x": [1.0, 0.0, 0.0], "y": [0.0, 1.0, 0.0], "z": [0.0, 0.0, 1.0]}
# The keys of the data that the plain pattern takes over as they are.
_KEPT = ("entity_type", "sources", "source_bodies", "result_bodies", "elements", "suppressed_ids", "source_faces")

SLIDES_ROUND_CIRCLE = ("The copies of this path pattern keep their direction along a whole circle, which is not "
                       "copied to Orca yet.")
SLIDES_OFF_ARC = "The copies of this path pattern do not sit where sliding along the arc puts them."


def path(ctx, step):
    """The path pattern of the resolved step `step` as an Orca pattern, or a Skip. A Skip that has no cause of its own
    gets the path pattern's cause."""
    found = _path(ctx, step)
    if isinstance(found, Skip) and found.cause == gap_hints.REFUSED:
        found.cause = gap_hints.PATH_PATTERN
    return found


def _path(ctx, step):
    item, data = step.brought, step.brought_data
    found = path_pattern.layout(data, slides=True)
    if is_problem(found):
        return Skip.of(found)
    count, distance, kind = data.get("quantity"), data.get("distance"), data.get("distance_type")
    if not isinstance(count, int) or isinstance(count, bool) or not isinstance(distance, (int, float)) \
            or distance <= 0 or kind not in ("extent", "spacing") or not isinstance(data.get("flip"), bool):
        return Skip(shared.PATH_PATTERN_UNREAD)
    if count < 2:
        return Skip(shared.PATTERN_NO_COPIES)
    way = -1 if data["flip"] else 1
    if found.kind == "line" and any(path_pattern.run_of(found, f) == -way for f in _kept_frames(ctx, data)):
        return Skip(shared.PATH_PATTERN_WRONG_WAY)
    if found.kind == "round" and (data["flip"] or float(data.get("start_point") or 0.0) > START_TOL):
        # Seen in Fusion 2706: from a start point part way along an arc and against it, the copies land off the arc.
        return Skip(shared.PATH_PATTERN_OFF_ROUND)
    room = found.room[0 if way > 0 else 1]
    travel = float(distance) * (1 if kind == "extent" else count - 1)
    if travel > room + END_TOL_MM:
        return Skip(shared.PATH_PATTERN_RUNS_OFF)
    _mark_path(ctx, item, data, found)
    if found.kind == "line":
        return _as_line(ctx, step, data, found, room)
    if found.turns:
        return _as_round(ctx, step, data, found, room)
    return _as_slide(ctx, step, data, found, travel)


def _kept_frames(ctx, data):
    """The frames of the kept copies other than the original, in the component the walk builds in."""
    return [e["frame"] for e in kept_elements(data_in_component(data, ctx.component_frame())) or []
            if not is_identity(e["frame"])]


def _mark_path(ctx, item, data, found):
    """The path is written as numbers: mark the sizes that may move or turn it. A sketch path: the sizes of its
    sketch, of the plane it sits on and of its projected geometry; a line gives only its direction and length, so
    only the sizes that may turn or stretch it (`edges.line_sizes`). An edge of the part: what may move that edge."""
    if ctx.table is None:
        return
    path_record, timeline = data["path"], ctx.capture.get("items") or []
    if path_record.get("kind") == "sketch" and path_record.get("sketch"):
        names = reach.sketch_line_sizes(ctx.table, timeline, item, path_record["sketch"],
                                        path_record.get("reference"), path_record.get("projected"))
        if found.kind == "line":
            source = {key: path_record.get(key) for key in ("sketch", "sketch_token", "reference", "projected")}
            names &= set(edges.line_sizes(ctx.table, ctx.capture, item, source,
                                          path_record["curves"][0].get("flat")))
        names = [name for name in ctx.table.ticked if name in names]
    else:
        names = reach.reference_sizes(ctx.table, timeline, item,
                                      data.get("path_place") or {"entity_type": "BRepEdge"})
    if names:
        ctx.doubt(names, "%s copies its path as measured" % label(item))


def _plain_data(data, extra):
    """The data of the plain pattern: the sources and the copies of the path pattern, with `extra`."""
    out = {key: data[key] for key in _KEPT if key in data}
    out.update(extra)
    return out


def _rewritten(step, built):
    """The resolved step of the item of `step` with the data `built`; it keeps the item's index and name."""
    return design.as_read(dict(step.brought, data=built))


def _patterns(made):
    return [f for f in made if f.type == FeatureType.PATTERN] if isinstance(made, list) else []


def _guard(ctx, item, made, fields_of, ok):
    """Tell on the parameters' lines how far the count or the distance may go before the copies run past the end of
    the path; a variable whose limit cannot be told keeps its number (`limits.guard`)."""
    for pattern in _patterns(made):
        limits.guard(ctx, fields_of(pattern), ok, "%s: the Orca copy cannot tell how far this may change before the "
                     "copies run past the end of the path" % label(item))


def _as_line(ctx, step, data, found, room):
    """A line path as a rectangular pattern of one direction. An edge path goes in as the direction's edge, so the
    rectangular handler marks the sizes that may turn it; a sketch line is marked by `_mark_path` (`fixed`)."""
    params = data.get("params") or {}
    built = _plain_data(data, {
        "direction_one": found.direction, "quantity_one": int(data["quantity"]),
        "distance_one": float(data["distance"]), "direction_two": None, "quantity_two": 1, "distance_two": 0.0,
        "distance_type": data["distance_type"], "symmetric_one": False, "symmetric_two": False,
        "params": {plain: params[own] for plain, own in (("quantity_one", "quantity"), ("distance_one", "distance"))
                   if own in params}})
    path_record = data["path"]
    if isinstance(data.get("path_place"), dict):
        built["direction_one_place"] = data["path_place"]
    elif path_record.get("kind") == "sketch" and path_record.get("sketch"):
        built["direction_one_place"] = {"entity_type": "SketchLine", "own": True, "fixed": True,
                                        "sketch": path_record["sketch"]}
    made = rectangular(ctx, _rewritten(step, built))

    def fields(pattern):
        return [(pattern, "pattern_count", "%s count" % pattern.name),
                (pattern, "pattern_spacing", "%s spacing" % pattern.name)]

    _guard(ctx, step.brought, made, fields,
           lambda n: limits.stop((n[0] - 1.0) * n[1] <= room + END_TOL_MM, limits.PATH_ENDS))
    return made


def _turn_steps(found, frames, way, delta):
    """The number of steps of `delta` degrees each frame turns along the path, or None when one is no whole step."""
    out = []
    for frame in frames:
        turn = (way * path_pattern.turn_deg(found, frame)) % FULL_TURN_DEG
        k = round(turn / delta)
        if k < 1 or abs(turn / k - delta) > path_pattern.TURN_SHARE * delta:
            return None
        out.append(k)
    return out


def _as_round(ctx, step, data, found, room):
    """An arc or circle path whose copies turn with it as a circular pattern about the axis of the arc. The angle
    follows the distance (and the count for a spacing); a pattern round the whole circle is a full turn."""
    item = step.brought
    count, distance = int(data["quantity"]), float(data["distance"])
    spacing = data["distance_type"] == "spacing"
    total = distance * 180.0 / (math.pi * found.radius) * (count - 1 if spacing else 1)
    full = abs(total - FULL_TURN_DEG) <= path_pattern.TURN_SHARE * FULL_TURN_DEG
    expected = FULL_TURN_DEG / count if full else total / (count - 1)
    frames = _kept_frames(ctx, data)
    delta = path_pattern.measured_turn(found, frames, 1, expected)
    steps = _turn_steps(found, frames, 1, delta) if delta is not None else None
    if steps is None or any(k > count - 1 for k in steps):
        against = path_pattern.measured_turn(found, frames, -1, expected) is not None
        return Skip(shared.PATH_PATTERN_WRONG_WAY if against else shared.PATTERN_UNEVEN_ROUND,
                    gap_hints.REFUSED if against else causes.COPIES_UNEVEN)
    distance_q = ctx.quantity(item, "distance", distance).magnitude()
    if full:
        total = FULL_TURN_DEG
        ctx.doubt(distance_q.reads, "%s goes round its whole path only while its distance stays as it is"
                  % label(item))
    else:
        total = delta * (count - 1)
    params = data.get("params") or {}
    built = _plain_data(data, {
        "axis": dict(found.axis, fixed=True), "quantity": count, "total_angle_deg": total, "symmetric": False,
        "params": {"quantity": params["quantity"]} if "quantity" in params else {}})
    # Degrees of turn per mm along the path, as the measured copies give it.
    per_mm = (delta if spacing else delta * (count - 1)) / distance

    def angle_of(count_value):
        turn = distance_q.scaled(per_mm)
        return count_value.plus(-1).times(turn) if spacing else turn

    made = circular(ctx, _rewritten(step, built), angle_of=angle_of)
    if not full:
        closed = data["path"]["curves"][0]["kind"] == "circle"
        top = CLOSED_TOP_DEG if closed else (room + END_TOL_MM) * per_mm

        def fields(pattern):
            return [(pattern, "pattern_angle", "%s angle" % pattern.name)]

        _guard(ctx, item, made, fields, lambda n: limits.stop(n[0] <= top, limits.PATH_ENDS))
    return made


def _slide_places(found, start, count, travel):
    """The moves (mm) of the copies of a pattern that slides along the arc of `found` from the path's start point
    `start`: copy k sits on the arc `k * travel / (count - 1)` along it."""
    centre, axis = found.axis["point"], found.axis["dir"]
    arm = vec.sub(start, centre)
    sweep = math.degrees(travel / found.radius)
    return [vec.sub(vec.rotate(arm, axis, sweep * k / (count - 1)), arm) for k in range(count)]


def _slide_check(ctx, data, places):
    """None when the measured copies of `data` sit on `places` without a turn, fill them and agree with their faces;
    else a Skip."""
    data = data_in_component(data, ctx.component_frame())
    elements = data.get("elements") or []
    if not elements:
        return Skip(shared.PATTERN_COPIES_UNREAD)
    if pattern_places.left_out(data):
        return Skip(LEAVES_COPIES_OUT % "pattern", causes.COPIES_SUPPRESSED)
    if not any(is_identity(e["frame"]) for e in elements):
        return Skip(shared.PATTERN_ORIGINAL_LOST)
    numbers = []
    for element in elements:
        frame = element["frame"]
        if not is_identity_rotation(frame):
            return Skip(shared.PATTERN_TURNED, causes.COPIES_TURNED)
        k = next((k for k, place in enumerate(places) if vec.close(frame["origin"], place, FIT_TOL_MM)), None)
        if k is None:
            return Skip(SLIDES_OFF_ARC, causes.COPIES_UNEVEN)
        numbers.append(k)
    problem = pattern_places.listed_places(numbers, len(places), data)
    if problem is not None:
        return Skip(problem.words, causes.COPIES_UNEVEN)
    source = pattern_places.source_faces(data)
    if any(pattern_places.agrees(source, e, dict(IDENTITY_FRAME, origin=places[k])) is False
           for e, k in zip(elements, numbers)):
        return Skip(shared.PATTERN_FACES_DISAGREE, causes.COPIES_UNEVEN)
    return None


def _as_slide(ctx, step, data, found, travel):
    """An arc path whose copies keep their direction as Orca's pattern along a sketch arc from the start of the path
    to the last copy. The arc is drawn as numbers, so the distance keeps its number, and so does the count of a
    pattern by spacing (its last copy moves with the count)."""
    item = step.brought
    if data.get("entity_type") == "bodies":
        return separate_copies(ctx, data, "pattern")
    if data.get("entity_type") != "features":
        return Skip("Patterns of faces are not copied to Orca yet.", gap_hints.REPEAT_FACES)
    curve = data["path"]["curves"][0]
    if curve["kind"] != "arc":
        return Skip(SLIDES_ROUND_CIRCLE)
    groups = sources(ctx, data, "pattern")
    if isinstance(groups, Skip):
        return groups
    count = int(data["quantity"])
    start = [float(c) for c in (curve["end"] if curve["opposed"] else curve["start"])]
    places = _slide_places(found, start, count, travel)
    refused = _slide_check(ctx, data, places)
    if refused is not None:
        return refused
    count_value = ctx.quantity(item, "quantity", count, "scalar")
    distance_value = ctx.quantity(item, "distance", float(data["distance"]))
    why = "%s slides its copies along an arc that Orca draws as numbers" % label(item)
    ctx.doubt(distance_value.reads, why)
    if data["distance_type"] == "spacing":
        ctx.doubt(count_value.reads, why)
        count_value = None
    centre, axis = found.axis["point"], vec.unit(found.axis["dir"])
    x_axis = vec.unit(vec.sub(start, centre))
    plane = ctx.place.plane(centre, x_axis, vec.cross(axis, x_axis), axis)
    sweep = travel / found.radius
    radius = found.radius
    arc = SketchEntity(type=EntityType.ARC, p0=(radius, 0.0), p1=(radius * math.cos(sweep), radius * math.sin(sweep)),
                       center=(0.0, 0.0), radius=radius, start_angle=0.0, end_angle=sweep)

    def copies(ctx_, tool, layout, tag):
        guide = ctx_.add(feature(FeatureType.SKETCH, "%s: path" % tag, entities=[arc], plane=plane))
        made = feature(FeatureType.PATTERN, "%s: pattern" % tag, pattern_curve_sketch=guide, pattern_curve_entity=0,
                       pattern_count=count, target_body=tool.index)
        if count_value is not None:
            ctx_.bind(made, "pattern_count", count_value, "%s count" % made.name)
            made.pattern_count = int(round(count_value.n))
        ctx_.add(made)
        return [(IDENTITY, place) for place in places]

    return write(ctx, item, groups, [None], copies, "pattern")
