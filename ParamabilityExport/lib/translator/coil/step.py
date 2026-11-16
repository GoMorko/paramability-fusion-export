"""Coil feature handler (CoilFeature): a wire swept along a helix, written as the recipe's `coil` step.

Fusion's API gives no type, axis, hand, section or operation of a coil (`fusion_reader/read_coil.py`), so they are
worked out from what the reader measured and checked against it:
- the sizes (diameter, section size, revolutions, height or pitch) come from the model parameters the coil made;
- the axis, the hand and the first section come from the coil's two flat end faces and its helical edges
  (`coil_fit`), and `verify` tests that the helix passes through every measured point;
- the operation (new body, join, cut) comes from the volumes of the bodies before and after (`coil_operation`).
The sizes follow formulas only where the formula gives the measured number (`coil_values`). A spiral, a tapered coil,
a wire that is not a plain section, a coil whose end faces are lost in the part and a coil past the recipe's caps are
left out as gaps. A coil is never part of a tool body with other steps: the recipe keeps coils out of tools.
"""
import math

from ...design_model.values import Quantity
from ...geometry import vec
from ...package.numbers import round9
from .. import placement, turn_budget, values
from ..extrude import COMBINE
from ..result import Refusal, StepResult
from ..step_walk import all_steps
from . import coil_fit, coil_limits as limits, coil_operation, coil_section, coil_values

KINDS = {("height", "revolutions"): "revolutions_height", ("pitch", "revolutions"): "revolutions_pitch",
         ("height", "pitch"): "height_pitch"}
SQUARE_TOL = 1e-3


def _kind(params):
    """revolutions_height, revolutions_pitch or height_pitch from the parameters present, or None."""
    return KINDS.get(tuple(sorted(key for key in ("revolutions", "height", "pitch") if key in params)))


def _written_coils(ctx):
    """The coil steps written so far in this walk and in the walks around it."""
    found, level = [], ctx
    while level is not None:
        found += [s for s in all_steps(level.steps) if s.get("kind") == "coil"]
        level = level.outer
    return found


def _shape(loop, along):
    """`circle`, `square` (sides along and across the axis) or `other` for a section loop; `along` is the axis
    direction on the sketch plane."""
    if loop["kind"] == "circle":
        return "circle"
    if loop["kind"] == "rect" and abs(loop["width"] - loop["height"]) <= limits.LEN_TOL:
        angle = math.radians(loop.get("angleDeg", 0.0))
        turn = abs(math.cos(angle) * along[0] + math.sin(angle) * along[1])
        if min(turn, 1.0 - turn) <= SQUARE_TOL:
            return "square"
    return "other"


def _written_loop(section, shape, loop, centre):
    """The recipe loop of the wire, centred on `centre` (two numbers or formulas)."""
    if shape == "circle":
        radius = section.half.json() if section.half is not None else round9(loop["radius"])
        return {"kind": "circle", "center": centre, "radius": radius}
    if shape == "square":
        size = section.size.json() if section.size is not None else round9(loop["width"])
        out = {"kind": "rect", "center": centre, "width": size, "height": size}
        if loop.get("angleDeg"):
            out["angleDeg"] = loop["angleDeg"]
        return out
    return loop


def _centre(frame, axis, rho, measured):
    """The wire's centre on the sketch plane: the axis point moved `rho` along the radial direction when `rho` follows
    sizes, else the measured centre."""
    if not rho.sized:
        return [round9(v) for v in vec.frame_to_local(frame, measured)[:2]]
    point = vec.frame_to_local(frame, axis["point"])
    radial = [vec.dot(axis["radial"], frame["x"]), vec.dot(axis["radial"], frame["y"])]
    return [(Quantity(round9(point[i])).plus(rho.scaled(radial[i])).json() if abs(radial[i]) > 1e-9
             else round9(point[i])) for i in range(2)]


def _half_turns(turns):
    """True for a number of turns that ends half way round (2.5): the two end faces then lie in one plane on the two
    sides of the axis, which does not give the axis."""
    return abs(2 * turns - round(2 * turns)) < 1e-6 < abs(turns - round(turns))


def _maybe_spiral(kind, refusal):
    """A coil of revolutions and pitch that does not fit a helix may be a spiral, which has the same two parameters."""
    if kind == "revolutions_pitch" and refusal.cause != limits.CAUSE_SPIRAL:
        return Refusal(limits.SPIRAL_OR_OTHER, cause=limits.CAUSE_SPIRAL)
    return refusal


def handle(item, ctx):
    data = item.get("data") or {}
    if "faces" not in data:
        return Refusal(limits.OLD_EXPORT, cause=limits.CAUSE_OTHER)
    params = data.get("params") or {}
    taper = params.get("taper_deg")
    if taper is not None and abs(taper["value"]) > limits.LEN_TOL:
        return Refusal(limits.TAPERED, cause=limits.CAUSE_TAPER)
    kind = _kind(params)
    if kind is None:
        return Refusal(limits.NO_PARAMETERS, cause=limits.CAUSE_OTHER)
    if kind != "height_pitch" and _half_turns(params["revolutions"]["value"]):
        return Refusal(limits.HALF_TURNS, cause=limits.CAUSE_HALF)
    faces = data.get("faces")
    flat = faces.get("flat") if isinstance(faces, dict) else None
    if not isinstance(flat, list) or len(flat) != 2:
        return Refusal(limits.PLACE, cause=limits.CAUSE_PLACE)
    caps = [coil_section.cap_of(record) for record in flat]
    for cap in caps:
        if isinstance(cap, Refusal):
            return cap
    start, end = caps
    edges = faces.get("edges") or []
    axis = coil_fit.find_axis(start, end, edges)
    if isinstance(axis, Refusal):
        return _maybe_spiral(kind, axis)
    rise = axis["rise"]
    if kind == "height_pitch":
        pitch_mm = abs(params["pitch"]["value"])
        turns_mm = rise / pitch_mm if pitch_mm > 0 else 0.0
    else:
        turns_mm = params["revolutions"]["value"]
        pitch_mm = rise / turns_mm if turns_mm > 0 else 0.0
        stated = abs(params["pitch"]["value"]) if kind == "revolutions_pitch" else pitch_mm
        if abs(stated - pitch_mm) > 10 * (limits.LEN_TOL + limits.REL_TOL * pitch_mm):
            return _maybe_spiral(kind, Refusal(limits.NOT_FITTING, cause=limits.CAUSE_OTHER))
    if not (turns_mm > limits.ZERO_TURN and pitch_mm > 0):
        return Refusal(limits.NO_PARAMETERS, cause=limits.CAUSE_OTHER)
    if not coil_fit.verify(axis, start, end, edges, pitch_mm, turns_mm):
        if _half_turns(turns_mm):
            return Refusal(limits.HALF_TURNS, cause=limits.CAUSE_HALF)
        return _maybe_spiral(kind, Refusal(limits.NOT_FITTING, cause=limits.CAUSE_OTHER))
    operation = coil_operation.operation_of(data, 2.0 * math.pi * turns_mm * start["area"] * axis["rho"])
    if isinstance(operation, Refusal):
        return operation
    return _write(item, ctx, params, kind, (start, axis, operation), (rise, pitch_mm, turns_mm))


def _write(item, ctx, params, kind, found, measured):
    start, axis, operation = found
    rise, pitch_mm, turns_mm = measured
    written = _written_coils(ctx)
    if len(written) >= limits.MAX_COILS:
        return Refusal(limits.TOO_MANY % limits.MAX_COILS, cause=limits.CAUSE_LIMIT)
    turns_left = turn_budget.left(ctx)
    if turns_mm > min(limits.MAX_TURNS, turns_left):
        return Refusal(limits.TOO_MANY_TURNS % limits.MAX_TURNS_TOTAL, cause=limits.CAUSE_LIMIT)
    frame, loop = start["frame"], start["loop"]
    section_points = coil_fit.section_in_axis(axis, start)
    axial_mm = max(p[1] for p in section_points) - min(p[1] for p in section_points)
    if min(p[0] for p in section_points) <= limits.LEN_TOL:
        return Refusal(limits.NOT_FITTING, cause=limits.CAUSE_OTHER)
    if turns_mm > 1 and not pitch_mm > axial_mm + limits.LEN_TOL:
        return Refusal(limits.TOUCHING)
    along = [vec.dot(axis["dir"], frame["x"]), vec.dot(axis["dir"], frame["y"])]
    shape = _shape(loop, along)
    section = coil_values.section_values(ctx, item, params, shape, loop, axial_mm)
    rho = coil_values.rho_value(ctx, item, params, section, axis["rho"])
    pitch, turns = coil_values.rise_values(ctx, item, params, kind, section, rise, pitch_mm, turns_mm)
    if "taper_deg" in params:
        values.pin(ctx, item, "taper_deg", "the taper of %s is not copied" % item.get("name", "a coil"))
    section, rho, pitch, turns = coil_values.keep_inside_ranges(ctx, item, section, rho, pitch, turns, axial_mm,
                                                                turns_left)
    centre = _centre(frame, axis, rho, start["centre"])
    step = {
        "kind": "coil",
        "sketch": {"on": placement.from_frame(frame), "outer": _written_loop(section, shape, loop, centre)},
        "axis": {"point": [round9(v) for v in vec.frame_to_local(frame, axis["point"])[:2]],
                 "dir": [round9(v) for v in along]},
        "pitch": pitch.json(),
        "turns": turns.json(),
        "combine": COMBINE[operation],
    }
    if axis["hand"] == "left":
        step["hand"] = "left"
    out = StepResult()
    out.add(step, repeatable=False)
    return out
