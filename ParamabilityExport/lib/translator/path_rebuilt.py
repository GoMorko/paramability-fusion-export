"""A path read back from written numbers: its curves, and the check of the app's rules for it that is run over the
range of every size the path follows (`path_motion`). Pure."""
from . import vec
from .path_checks import bend_refusal, off_square, overlap_refusal, rise_refusal, self_touch
from .path_curves import near, polyline, tangents, tightest_radius, turn_deg
from .path_limits import (CLOSED_AT_CORNER, CROSSES, NOT_SQUARE, SHARP_CORNER, SMOOTH_JOIN_DEG, STRAIGHT_DEG,
                          TURNED_ROUND, UNREADABLE)
from .result import Refusal


def flat_curves(recipe):
    """The curves of a flat path recipe with plain numbers, 3D in the frame of its `on` placement: lines and arcs
    (`mid` is the written `through` point). Raises ValueError for a segment that is not a line or an arc."""
    on = recipe["on"]
    z, x = vec.unit(on["normal"]), vec.unit(on["xDir"])
    y = vec.cross(z, x)

    def lift(p):
        return [on["origin"][i] + x[i] * p[0] + y[i] * p[1] for i in range(3)]

    out, at = [], lift(recipe["start"])
    for segment in recipe["segments"]:
        end = lift(segment["to"])
        if segment["kind"] == "line":
            out.append({"kind": "line", "start": at, "end": end})
        elif segment["kind"] == "arc":
            out.append({"kind": "arc", "start": at, "mid": lift(segment["through"]), "end": end})
        else:
            raise ValueError("a free curve")
        at = end
    return out


def rebuilt_refusal(curves, closed, normal, reach, fixed=False, extra=0.0, leaves=None):
    """A Refusal when a chain of lines and arcs read back from written numbers (the first curve starts on the
    outline's plane) breaks a rule the app checks: it does not leave the plane square, it has a sharp corner, the
    outline reaches past its tightest bend, it touches itself, or (for an outline kept in one direction) it stops
    rising. `reach` is how far the outline reaches across the path's plane, `extra` how far a taper can grow it, and
    `normal` the unit normal of the outline's plane, `leaves` the direction the path leaves it (when given, the path
    must leave it that way)."""
    try:
        if any(c["kind"] == "line" and near(c["start"], c["end"]) for c in curves):
            return Refusal(UNREADABLE)
        first = tangents(curves[0])[0]
        if off_square(first, normal):
            return Refusal(NOT_SQUARE)
        if leaves is not None and vec.dot(first, leaves) <= 0:
            return Refusal(TURNED_ROUND)
        ring = list(zip(curves, curves[1:] + curves[:1] if closed else curves[1:]))
        for number, (a, b) in enumerate(ring):
            limit = STRAIGHT_DEG if a["kind"] == b["kind"] == "line" else SMOOTH_JOIN_DEG
            if turn_deg(tangents(a)[1], tangents(b)[0]) > limit:
                return Refusal(CLOSED_AT_CORNER if closed and number == len(ring) - 1 else SHARP_CORNER)
        refusal = bend_refusal(reach + extra, tightest_radius(curves))
        if refusal:
            return refusal
        points = [p for c in curves for p in polyline(c)]
        if self_touch(points, closed):
            return Refusal(CROSSES)
        if fixed:
            return rise_refusal(curves, normal)
        return overlap_refusal(points, reach + extra, closed)
    except ValueError:
        return Refusal(UNREADABLE)
