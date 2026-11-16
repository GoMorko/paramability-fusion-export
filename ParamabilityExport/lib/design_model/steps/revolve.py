"""Revolves as facts: how far Fusion turns and which way, told by the measured caps of the turned material.

Fusion's angle of a symmetric revolve is the turn to each side, so the whole turn is twice the angle, and a whole turn
of 360 degrees or more closes the ring (`total_turn`). Fusion does not say which way a one sided revolve turned. The
outward normals of its caps tell it: the start cap (`start_face_normal`) lies in the sketch plane and the end cap
(`end_face_normal`) where the turn stops. For new material the start cap faces against the travel and the end cap
along it; after a cut both face the other way. A cap that a join merged into a face of the part, or that a cut
removed, is not given; the other cap can still tell (`sense`). A quarter turn ends with the same cap normal either
way, so when the caps do not tell, the box of the faces the revolve made (`made_box`) must fit inside the box the
outline sweeps one way and not the other. A join merges its faces with faces of the part, so those faces can reach
past the swept box: for a join, the made faces and the whole body after the step must fit inside the box of the body
before the step together with the swept box (`body_boxes`). For a symmetric revolve the caps must sit the angle
before and after the sketch (`symmetric_ok`): that also proves how Fusion counts the angle.

A revolve to two sides turns by `angle one` to one side of the sketch and by `angle two` to the other, and Fusion does
not say which side is which. The result covers one turn of `angle one + angle two` that starts a number of degrees back
from the sketch: `angle two` back when side one is the right hand turn about the axis, `angle one` back when it is the
other. The start face is one of the two end faces of that turn, so the way the material leaves it (`travel`) tells the
two apart (`back_sides`). How the travel is measured, and how the result is written, stay with the destination.
"""
import math

from ...geometry import footprint, vec

FULL_TURN_DEG = 360.0
# How far apart two unit normals may be and still count as the same direction.
NORMAL_TOL = 1e-3
# How far apart (unit vectors) the measured and the expected travel of a two sided revolve may be.
TRAVEL_TOL = 1e-3
# Steps per full turn when the box an outline sweeps is sampled, and how far (mm) a made face may stand out of it.
BOX_STEPS = 720
BOX_TOL = 1e-2


def total_turn(angle_deg, symmetric):
    """(the whole turn in degrees, True when it closes the ring) of an angle extent."""
    total = abs(float(angle_deg)) * (2.0 if symmetric else 1.0)
    return min(total, FULL_TURN_DEG), total >= FULL_TURN_DEG - 1e-9


def _caps(turn, axis, start_deg, total_deg, cut):
    """Outward normals (start cap, end cap) of material turned by the right hand rule about `axis` from `start_deg`
    for `total_deg`, where `turn` is the way the outline moves at the sketch plane."""
    first = vec.rotate(turn, axis, start_deg)
    last = vec.rotate(turn, axis, start_deg + total_deg)
    if cut:
        return vec.scale(first, 1.0), vec.scale(last, -1.0)
    return vec.scale(first, -1.0), vec.scale(last, 1.0)


def _same(a, b):
    return vec.length(vec.sub(vec.unit(a), b)) < NORMAL_TOL


def _normal(data, key):
    found = data.get(key)
    if isinstance(found, (list, tuple)) and len(found) == 3 and vec.length(found) > 1e-9:
        return [float(c) for c in found]
    return None


def _curve_points(curve):
    """2D points whose polygon holds the capture curve `curve`. An arc or circle is a polyline whose points are moved
    out from the centre so that every chord lies outside the curve; the box it sweeps is then never smaller than the
    box the curve sweeps."""
    points = footprint.polyline(curve)
    if curve.get("kind") not in ("arc", "circle"):
        return points
    if footprint.is_full(curve):
        sweep = 2.0 * math.pi
    else:
        sweep = abs(footprint.arc_span(curve)[1])
    out = 1.0 / math.cos(sweep / (2.0 * footprint.ARC_SEGMENTS))
    c = curve["center"]
    return [[c[0] + (p[0] - c[0]) * out, c[1] + (p[1] - c[1]) * out] for p in points]


def outline_points(data):
    """3D points of the outer loops of every outline of the revolve in `data`, for `turned_box`; None when an outline
    does not read. A line is its two ends, an arc or circle a polyline outside it (`_curve_points`), a free curve its
    samples."""
    found = []
    try:
        for profile in data.get("profiles") or []:
            frame = profile["frame"]
            for loop in profile["loops"]:
                if loop.get("outer"):
                    for curve in loop["curves"]:
                        found += [vec.frame_apply(frame, [p[0], p[1], 0.0]) for p in _curve_points(curve)]
    except (KeyError, TypeError, IndexError, ValueError, ZeroDivisionError):
        return None
    return found or None


def turned_box(points, axis_point, axis, total_deg):
    """(min, max) corners of the box that `points` sweep turning by the right hand rule about the line through
    `axis_point` along `axis`, from 0 to `total_deg` degrees."""
    steps = max(2, int(math.ceil(BOX_STEPS * abs(total_deg) / 360.0)))
    low, high = [math.inf] * 3, [-math.inf] * 3
    for k in range(steps + 1):
        for p in points:
            q = vec.rotate(p, axis, total_deg * k / steps, axis_point)
            low = [min(a, b) for a, b in zip(low, q)]
            high = [max(a, b) for a, b in zip(high, q)]
    return low, high


def _box_holds(outer, inner):
    return all(outer[0][i] - BOX_TOL <= inner[0][i] and inner[1][i] <= outer[1][i] + BOX_TOL for i in range(3))


def _box(box):
    """(min, max) of a { min, max } box record, or None when it does not read."""
    if not isinstance(box, dict):
        return None
    low, high = box.get("min"), box.get("max")
    if not (isinstance(low, (list, tuple)) and isinstance(high, (list, tuple)) and len(low) == len(high) == 3):
        return None
    return [float(c) for c in low], [float(c) for c in high]


def body_boxes(item):
    """(box before, box after) of the body a walk builds around the timeline item `item`, each a { min, max } record
    or None: the item's `target_before` and `target_after`, else the `target_box_before` of its data (`roles.seen_on`
    gives the measures of another body there)."""
    data = item.get("data") if isinstance(item.get("data"), dict) else {}
    before = (item.get("target_before") or {}).get("box") or data.get("target_box_before")
    return before, (item.get("target_after") or {}).get("box")


def _union(a, b):
    return [min(x, y) for x, y in zip(a[0], b[0])], [max(x, y) for x, y in zip(a[1], b[1])]


def sense(data, turn, axis, total_deg, cut, points=None, axis_point=None, bodies=(None, None)):
    """+1 when Fusion turned a one sided revolve by the right hand rule about `axis`, -1 when the other way, or None
    when the measurements of `data` do not tell. `turn` is the unit way the outline moves at the sketch plane on a
    right hand turn; `points` (3D points of the outline, `outline_points`) and `axis_point` let the made faces tell.

    `bodies` holds the boxes of the body before and after the step (`body_boxes`). A join adds material only where the
    outline sweeps, so the made faces and the body after it lie inside the box before together with the swept box of
    the turn Fusion made. A box before that is looser than the body only lets more turns fit; when both turns fit, the
    answer is None."""
    measured = [_normal(data, "start_face_normal"), _normal(data, "end_face_normal")]
    fits = []
    for sign in (1.0, -1.0):
        caps = _caps(vec.scale(turn, sign), vec.scale(axis, sign), 0.0, total_deg, cut)
        if all(n is None or _same(n, cap) for n, cap in zip(measured, caps)):
            fits.append(sign)
    made = _box(data.get("made_box"))
    before, after = (_box(box) for box in bodies)
    join = data.get("operation") == "join" and before is not None
    inner = [box for box in (made, after if join else None) if box is not None]
    if len(fits) > 1 and inner and points and axis_point is not None:
        def holds(sign):
            outer = turned_box(points, axis_point, vec.scale(axis, sign), total_deg)
            outer = _union(outer, before) if join else outer
            return all(_box_holds(outer, box) for box in inner)

        fits = [sign for sign in fits if holds(sign)]
    if len(fits) == 1 and (any(measured) or inner):
        return fits[0]
    return None


def symmetric_ok(data, turn, axis, per_side_deg, cut):
    """True when each measured cap of a symmetric revolve sits `per_side_deg` before or after the sketch plane, False
    when one does not, None when no cap was measured."""
    measured = [n for n in (_normal(data, "start_face_normal"), _normal(data, "end_face_normal")) if n]
    if not measured:
        return None
    caps = _caps(turn, axis, -per_side_deg, 2.0 * per_side_deg, cut)
    return all(any(_same(n, cap) for cap in caps) for n in measured)


def back_sides(travel, turn, axis, angle_one, angle_two):
    """The sides (1 for `angle one`, 2 for `angle two`) whose angle the turn may start back from the sketch.

    `travel` is the unit direction the material leaves the start face in, `turn` the unit direction the outline moves
    in at the start of a right hand turn about the unit `axis`, both in one frame. The answer is empty when no end face
    of either turn matches the start face, and holds both sides when the start face fits both turns (equal angles, or
    an angle of a quarter turn). The turn then covers from `back` degrees back to `angle one + angle two - back`
    degrees ahead, by the right hand rule about `axis`.
    """
    angles = {1: float(angle_one), 2: float(angle_two)}
    found = set()
    for sense in (1.0, -1.0):
        for side, back in angles.items():
            expected = vec.rotate(vec.scale(turn, sense), axis, -sense * back)
            if vec.length(vec.sub(expected, travel)) < TRAVEL_TOL:
                # Turning the other way from `back` ahead covers the same turn as the right hand way from the other
                # angle back.
                found.add(side if sense > 0 else 3 - side)
    return sorted(found)
