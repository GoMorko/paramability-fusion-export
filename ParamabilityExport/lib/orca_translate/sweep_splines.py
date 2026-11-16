"""Free curves (splines) in the path of an Orca sweep, written exactly.

Orca builds the wire of a path sketch from the same entities as an outline (`SketchEngine::entities_to_wires`), so a
path spline is written as the Bezier pieces of `splines.py`: the same curve, no fit. A sketch path's curve carries its
exact definition in its `flat` record (`nurbs`, in the path sketch's 2D frame); a body edge has none and stays out.

- `with_exact_splines` gives each spline of a sketch path its definition in the capture's coordinates (`nurbs3d`)
  and its exact end directions (from the first and last poles of a clamped curve), so the planner and the corner
  check see whether the spline meets its neighbours smoothly. The measured points only give those directions to
  within a fraction of a degree.
- `flat_spline` turns such a curve into a curve of the path's 2D frame, run the way the planned path runs. A curve the
  planner cut (a closed path opened inside the spline) no longer starts and ends at the definition's ends and is None.
- `tightest` is the radius of the tightest bend of the Bezier pieces, read along them, which the planner's fitted
  curve only comes close to.
- `Chain` is the shape of the outline carried along a spline for later cuts: a prism along each short chord of the
  measured points, each lengthened at its joints by what the turn there opens on the outer side.
"""
import math

from ..geometry import vec
from . import splines
from .solid import Prism, box_of, union

# How close (mm) a curve's ends must lie to the ends of its definition, and its poles to the path's plane.
_END_TOL = 1e-3
_PLANE_TOL = 1e-4
# Readings per Bezier piece when its tightest bend is looked for.
_BEND_READINGS = 256
# The measured points of a spline lie this close (mm) to the chords the shape for later cuts is built from.
_CHORD_TOL = 2e-3
_EPS = 1e-12


def _exact(curve, frame):
    """`nurbs3d`, `tangent_start` and `tangent_end` for a path curve whose `flat` record holds a definition Orca
    draws exactly and whose ends match it (either way round), else None."""
    flat = curve.get("flat")
    nurbs = flat.get("nurbs") if isinstance(flat, dict) else None
    if not isinstance(nurbs, dict) or not splines.bezier_pieces(nurbs):
        return None
    try:
        poles = [vec.frame_apply(frame, [float(p[0]), float(p[1]), 0.0]) for p in nurbs["poles"]]
        start, end = list(curve["start"]), list(curve["end"])
    except (KeyError, TypeError, ValueError, IndexError):
        return None
    if math.dist(poles[0], start) <= _END_TOL and math.dist(poles[-1], end) <= _END_TOL:
        pass
    elif math.dist(poles[-1], start) <= _END_TOL and math.dist(poles[0], end) <= _END_TOL:
        nurbs, poles = _reversed(nurbs), list(reversed(poles))
    else:
        return None
    first = next((p for p in poles[1:] if math.dist(p, poles[0]) > _EPS), None)
    last = next((p for p in reversed(poles[:-1]) if math.dist(p, poles[-1]) > _EPS), None)
    if first is None or last is None:
        return None
    return {"nurbs3d": dict(nurbs, poles=poles), "tangent_start": vec.unit(vec.sub(first, poles[0])),
            "tangent_end": vec.unit(vec.sub(poles[-1], last))}


def with_exact_splines(path):
    """The path record with each spline of a sketch path given its exact definition in the capture's coordinates and
    its exact end directions (`_exact`); the record itself when there is nothing to add."""
    frame, curves = path.get("frame"), path.get("curves")
    if not isinstance(frame, dict) or not isinstance(curves, list):
        return path
    out, changed = [], False
    for curve in curves:
        found = _exact(curve, frame) if isinstance(curve, dict) and curve.get("kind") == "other" else None
        if found is not None:
            curve, changed = dict(curve, **found), True
        out.append(curve)
    return dict(path, curves=out) if changed else path


def _reversed(nurbs):
    knots = nurbs["knots"]
    low, high = knots[0], knots[-1]
    weights = nurbs.get("weights")
    return dict(nurbs, knots=[low + high - k for k in reversed(knots)], poles=list(reversed(nurbs["poles"])),
                weights=list(reversed(weights)) if weights else weights)


def flat_spline(curve, frame):
    """A planned spline curve in the 2D frame `frame` of the path's plane, as a capture curve with its `nurbs` run the
    way the curve runs, or None when it has no exact definition, was cut, or leaves the plane."""
    nurbs = curve.get("nurbs3d")
    if not isinstance(nurbs, dict):
        return None
    poles = nurbs["poles"]
    if math.dist(poles[0], curve["start"]) <= _END_TOL and math.dist(poles[-1], curve["end"]) <= _END_TOL:
        pass
    elif math.dist(poles[-1], curve["start"]) <= _END_TOL and math.dist(poles[0], curve["end"]) <= _END_TOL:
        nurbs = _reversed(nurbs)
    else:
        return None
    flat = [vec.frame_to_local(frame, p) for p in nurbs["poles"]]
    if any(abs(p[2]) > _PLANE_TOL for p in flat):
        return None

    def local(p):
        return vec.frame_to_local(frame, p)[:2]

    return {"kind": "other", "start": local(curve["start"]), "end": local(curve["end"]),
            "samples": [local(p) for p in curve["samples"]], "nurbs": dict(nurbs, poles=[p[:2] for p in flat])}


def _radius(piece, t):
    """The bend radius of a 2D Bezier piece at `t` (infinity where it runs straight)."""
    def derivative(points):
        n = len(points) - 1
        return [(n * (b[0] - a[0]), n * (b[1] - a[1])) for a, b in zip(points, points[1:])]

    def at(points):
        points = list(points)
        while len(points) > 1:
            points = [((1 - t) * a[0] + t * b[0], (1 - t) * a[1] + t * b[1]) for a, b in zip(points, points[1:])]
        return points[0]

    first = derivative(piece)
    d1 = at(first)
    d2 = at(derivative(first)) if len(first) > 1 else (0.0, 0.0)
    bend = abs(d1[0] * d2[1] - d1[1] * d2[0])
    speed = math.hypot(*d1)
    return math.inf if bend < _EPS else speed ** 3 / bend


def tightest(flat_curves):
    """The radius of the tightest bend of the flat path curves `flat_curves` (2D): arcs by their radius, splines by
    their Bezier pieces read along them."""
    found = math.inf
    for curve in flat_curves:
        if curve["kind"] == "arc":
            found = min(found, float(curve["radius"]))
        elif curve["kind"] == "other":
            for piece in splines.bezier_pieces(curve["nurbs"]) or ():
                found = min(found, min(_radius(piece, k / _BEND_READINGS) for k in range(_BEND_READINGS + 1)))
    return found


# ---- the shape for later cuts ---------------------------------------------------------------------------------

def _chord_points(samples):
    """The measured points kept as chord ends: each chord as long as every point it skips lies within `_CHORD_TOL`."""
    kept, at = [samples[0]], 0
    while at < len(samples) - 1:
        reach = at + 1
        while reach + 1 < len(samples) and all(_off_chord(samples[k], samples[at], samples[reach + 1]) <= _CHORD_TOL
                                               for k in range(at + 1, reach + 1)):
            reach += 1
        kept.append(samples[reach])
        at = reach
    return kept


def _off_chord(p, a, b):
    ab = vec.sub(b, a)
    size = vec.length(ab)
    if size < _EPS:
        return vec.length(vec.sub(p, a))
    return vec.length(vec.cross(vec.sub(p, a), ab)) / size


def _turn(a, b):
    return math.atan2(vec.length(vec.cross(a, b)), vec.dot(a, b))


def chain(curve, place, reach, open_start, open_end):
    """The outline carried along a spline curve of the path, as a `Chain` of prisms. `place(direction, at)` gives the
    outline's frame and loops carried to the point `at`, facing along `direction`, as `(frame, loops)`; `reach` is how
    far the outline reaches from the path across its plane. A chord end that is also an end of the whole path
    (`open_start`, `open_end`) is not lengthened, so the end faces stay where the path ends."""
    points = _chord_points([list(p) for p in curve["samples"]])
    chords = [(a, b) for a, b in zip(points, points[1:]) if vec.length(vec.sub(b, a)) > _EPS]
    if not chords:
        return Chain([])
    ends = curve.get("tangent_start"), curve.get("tangent_end")
    directions = [vec.unit(vec.sub(b, a)) for a, b in chords]
    turns = [_turn(a, b) for a, b in zip(directions, directions[1:])]
    first = 0.0 if open_start or ends[0] is None else _turn(ends[0], directions[0]) * 2.0
    last = 0.0 if open_end or ends[1] is None else _turn(directions[-1], ends[1]) * 2.0
    before = [first] + turns
    after = turns + [last]
    prisms = []
    for (a, b), direction, low, high in zip(chords, directions, before, after):
        frame, loops = place(direction, a)
        grow_low, grow_high = reach * math.tan(low / 2.0), reach * math.tan(high / 2.0)
        size = vec.length(vec.sub(b, a))
        if vec.dot(frame["z"], direction) > 0:
            prisms.append(Prism(frame, loops, -grow_low, size + grow_high))
        else:
            prisms.append(Prism(frame, loops, -(size + grow_high), grow_low))
    return Chain(prisms)


class Chain:
    """Shapes joined into one, each asked only for the lines that cross its box."""

    def __init__(self, shapes):
        self.shapes = [(shape, shape.bounds()) for shape in shapes]

    def span(self, start, direction):
        held = []
        for shape, box in self.shapes:
            if box is None or _crosses(box, start, direction):
                held = union(held, shape.span(start, direction))
        return held

    def bounds(self):
        boxes = [box for _, box in self.shapes]
        if not boxes or any(box is None for box in boxes):
            return None
        return box_of([box["min"] for box in boxes] + [box["max"] for box in boxes])


def _crosses(box, start, direction):
    """True when the line `start + t * direction` passes through the box."""
    low, high = -math.inf, math.inf
    for i in range(3):
        if abs(direction[i]) < _EPS:
            if not box["min"][i] - _EPS <= start[i] <= box["max"][i] + _EPS:
                return False
            continue
        a, b = (box["min"][i] - start[i]) / direction[i], (box["max"][i] - start[i]) / direction[i]
        low, high = max(low, min(a, b)), min(high, max(a, b))
    return low <= high + _EPS
