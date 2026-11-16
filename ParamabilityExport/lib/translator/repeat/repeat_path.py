"""Path patterns (PathPatternFeature) on one straight line, arc or circle.

The pattern is handed to the rectangular or the circular pattern handler as the plain pattern it equals
(`design_model/steps/path_pattern.py`): a line as a rectangular pattern of one direction along the line, a round path
as a circular pattern about the axis of the arc, with the turn worked out from the distance along the arc. Those
handlers check the measured copies against the pattern they write, so a copy Fusion put elsewhere leaves the step out.

The copies must stay on the path: at the captured sizes the step is left out when they run past an end of it, and the
ranges of a count or distance that can make them run past an end are cut to where they stay on it (the sizes are
marked when no cut does that). The path itself is written as numbers: the sizes that may move or turn it (its sketch,
the plane the sketch sits on, or the steps before an edge of the part) are marked.
"""
import math

from ...capture_model import gap_hints
from ...design_model import design, reach, words as shared
from ...design_model.problem import is_problem
from ...design_model.steps import path_pattern
from ...design_model.steps.repeat import data_in_component, is_identity, kept_elements
from .. import values
from ..ranges import kept_ranges
from ..result import Refusal
from .repeat_circular import FULL_TURN_DEG, circular
from .repeat_lattice import gaps_between
from .repeat_rectangular import rectangular

# Distance (mm) the copies may reach past an end of the path, for numbers rounded in the capture.
END_TOL_MM = 1e-3
# Share of the turn between copies by which the measured turn may differ from the one the distance and the rounded
# radius give.
TURN_SHARE = 1e-4
# The keys of the data that the plain pattern takes over as they are.
_KEPT = ("entity_type", "sources", "source_bodies", "result_bodies", "elements", "suppressed_ids")


def _mark_path(ctx, item, data):
    """The path is written as numbers: mark the sizes that may move or turn it. A sketch path: the sketch's sizes and
    what moves its plane or its projected geometry (`reach.sketch_line_sizes`). An edge of the part: what may move that
    edge (`reach.reference_sizes`). The first translation of an export marks nothing."""
    if ctx.table is None or getattr(ctx.motion, "optimistic", False):
        return
    path, timeline = data["path"], ctx.capture.get("items") or []
    if path.get("kind") == "sketch" and path.get("sketch"):
        names = reach.sketch_line_sizes(ctx.table, timeline, item, path["sketch"], path.get("reference"),
                                        path.get("projected"))
        names = [name for name in ctx.table.ticked if name in names]
    else:
        names = reach.reference_sizes(ctx.table, timeline, item, data.get("path_place") or {"entity_type": "BRepEdge"})
    if names:
        ctx.doubt(names, "%s copies its path as measured" % item.get("name", "a path pattern"))


def _kept(data, ctx):
    """The kept copies other than the original, with their frames in the component the walk builds in."""
    return [e for e in kept_elements(data_in_component(data, ctx.component_frame())) or []
            if not is_identity(e["frame"])]


def _line_runs_against(found, data, ctx, way):
    """True when a measured copy of a line path pattern runs against `way` (1 toward the path's end, -1 toward its
    start)."""
    return any(path_pattern.run_of(found, e["frame"]) == -way for e in _kept(data, ctx))


def _travel(ctx, item, data):
    """`(distance, travel)` as Quantities: the distance, and how far the last copy runs along the path from the start
    point."""
    count_q = values.quantity(ctx, item, "quantity", int(data["quantity"]), dim="scalar", whole=True)
    distance_q = values.quantity(ctx, item, "distance", float(data["distance"]), absolute=True)
    travel = distance_q if data["distance_type"] == "extent" else gaps_between(count_q).times(distance_q)
    return distance_q, travel


def _keep_on_path(ctx, item, travel, room):
    """A count or distance that can make the copies run past the end of the path inside the size ranges: the ranges of
    the sizes they read are cut to where the copies stay on the path, or, when no cut does that, the sizes are
    marked."""
    if not travel.sized or ctx.table is None:
        return
    left = travel.scaled(-1).plus(room + END_TOL_MM)
    if values.stays_positive(ctx.table, left):
        return
    why = "%s would run its copies past the end of its path" % item.get("name", "a path pattern")
    found = kept_ranges.holding_ranges(ctx.table, [(left, 1)], 0.0)
    if found:
        ctx.cut(found, why)
    else:
        ctx.doubt(travel.reads, why)


def _plain_data(data, extra):
    """The data of the plain pattern: the sources and the copies of the path pattern, with `extra`."""
    out = {key: data[key] for key in _KEPT if key in data}
    out.update(extra)
    return out


def _as_line(ctx, step, data, found):
    """A line path as a rectangular pattern of one direction. The path goes in as the direction's sketch or edge, so
    the rectangular handler marks the sizes that may turn it."""
    params = data.get("params") or {}
    built = _plain_data(data, {
        "direction_one": found.direction, "quantity_one": int(data["quantity"]),
        "distance_one": float(data["distance"]), "direction_two": None, "quantity_two": 1, "distance_two": 0.0,
        "distance_type": data["distance_type"], "symmetric_one": False, "symmetric_two": False,
        "params": {plain: params[own] for plain, own in (("quantity_one", "quantity"), ("distance_one", "distance"))
                   if own in params}})
    path = data["path"]
    if isinstance(data.get("path_place"), dict):
        built["direction_one_place"] = data["path_place"]
    elif path.get("kind") == "sketch" and path.get("sketch"):
        built["direction_one_sketch"] = {"sketch": path["sketch"], "reference": path.get("reference"),
                                         "projected": path.get("projected")}
    return rectangular(ctx, _rewritten(step, built))


def _rewritten(step, built):
    """The resolved step of the item of `step` with the data `built`; it keeps the item's index and name."""
    return design.as_read(dict(step.brought, data=built))


def _measured_turn(found, data, ctx, way, delta):
    """The turn between neighbour copies that the measured copies show when they turn `way` along a round path, or
    None when they do not sit on whole steps of `delta`, the turn the distance and the radius give (within TURN_SHARE
    of it). The radius is read rounded, so the measured turn is the one written."""
    best, steps = delta, 0
    for element in _kept(data, ctx):
        turn = (way * path_pattern.turn_deg(found, element["frame"])) % FULL_TURN_DEG
        k = round(turn / delta)
        if k < 1 or abs(turn / k - delta) > TURN_SHARE * delta:
            return None
        if k > steps:
            best, steps = turn / k, k
    return best


def _as_round(ctx, step, data, found, way, distance_q):
    """An arc or circle path as a circular pattern about the axis of the arc. Its angle follows the distance (and the
    count for a spacing); a pattern round the whole circle is a full turn."""
    item = step.brought
    count = int(data["quantity"])
    total = float(data["distance"]) * 180.0 / (math.pi * found.radius)
    if data["distance_type"] == "spacing":
        total *= count - 1
    full = abs(total - FULL_TURN_DEG) <= TURN_SHARE * FULL_TURN_DEG
    expected = FULL_TURN_DEG / count if full else total / (count - 1)
    delta = _measured_turn(found, data, ctx, way, expected)
    if delta is None:
        against = _measured_turn(found, data, ctx, -way, expected) is not None
        return Refusal(shared.PATH_PATTERN_WRONG_WAY if against else shared.PATTERN_UNEVEN_ROUND)
    if full:
        total = FULL_TURN_DEG
        values.pin(ctx, item, "distance", "%s goes round its whole path only while its distance stays as it is"
                   % item.get("name", "a path pattern"))
    else:
        total = delta * (count - 1)
    params = data.get("params") or {}
    built = _plain_data(data, {
        "axis": dict(found.axis, fixed=True), "quantity": count, "total_angle_deg": total,
        "symmetric": False, "params": {"quantity": params["quantity"]} if "quantity" in params else {}})
    # Degrees of turn per mm along the path, as the measured copies give it.
    spacing = data["distance_type"] == "spacing"
    per_mm = (delta if spacing else delta * (count - 1)) / float(data["distance"])

    def total_angle(counted):
        turn = distance_q.scaled(per_mm)
        return gaps_between(counted).times(turn) if spacing else turn

    return circular(ctx, _rewritten(step, built), total_angle=None if full else total_angle)


def path(ctx, step):
    """The path pattern of the resolved step `step`, written as the rectangular or circular pattern it equals. A
    refusal that has no cause of its own and comes from no earlier gap gets the path pattern's hint."""
    found = _path(ctx, step)
    if isinstance(found, Refusal) and found.cause is None and not found.depends_on:
        found.cause = gap_hints.PATH_PATTERN
    return found


def _path(ctx, step):
    item, data = step.brought, step.brought_data
    found = path_pattern.layout(data)
    if is_problem(found):
        return Refusal(found.words, cause=found.cause)
    count, distance, kind = data.get("quantity"), data.get("distance"), data.get("distance_type")
    if not isinstance(count, int) or not isinstance(distance, (int, float)) or distance <= 0 \
            or kind not in ("extent", "spacing") or not isinstance(data.get("flip"), bool):
        return Refusal(shared.PATH_PATTERN_UNREAD)
    if count < 2:
        return Refusal(shared.PATTERN_NO_COPIES)
    way = -1 if data["flip"] else 1
    if found.kind == "line" and _line_runs_against(found, data, ctx, way):
        return Refusal(shared.PATH_PATTERN_WRONG_WAY)
    room = found.room[0 if way > 0 else 1]
    distance_q, travel = _travel(ctx, item, data)
    if travel.n > room + END_TOL_MM:
        return Refusal(shared.PATH_PATTERN_RUNS_OFF)
    _keep_on_path(ctx, item, travel, room)
    _mark_path(ctx, item, data)
    if found.kind == "line":
        return _as_line(ctx, step, data, found)
    return _as_round(ctx, step, data, found, way, distance_q)
