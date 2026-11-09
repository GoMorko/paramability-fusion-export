"""Fillet, chamfer and shell handlers (FilletFeature, ChamferFeature, ShellFeature).

Edges and faces are picked by `near` points taken from the captured edge and face positions (see picks.py).
What the recipe has no words for is refused: changing radii, two sized chamfers, outside or rounded shells.
"""
from . import picks, values
from .result import Refusal

TYPES = ("FilletFeature", "ChamferFeature", "ShellFeature")

SIZE_TOL = 1e-9
ANGLE_TOL = 1e-6
EQUAL_ANGLE_DEG = 45.0

_FILLET_SET_REFUSALS = {
    "variable": "Rounds with a changing radius are not copied yet.",
    "chordLength": "Rounds set by chord length are not copied yet.",
    "asymmetric": "Rounds with two different radii are not copied yet.",
}


def _n(value):
    return round(value, 9) + 0.0


def _close(a, b, tol=SIZE_TOL):
    return abs(a - b) <= tol


def _split_note(ctx, steps):
    if len(steps) > 1:
        ctx.note("The edges are picked in %d steps, since one pick holds at most %d points."
                 % (len(steps), picks.MAX_NEAR_POINTS))


def _flat_edges(sets):
    """Every edge of `sets` with its set index, in order."""
    return [(edge, n) for n, entry in enumerate(sets) for edge in entry.get("edges") or []]


def _unlocated(edges):
    return any(not edge.get("points") for edge in edges)


def _fillet_steps(pairs):
    """One `round` step per group of edges that fits a pick. `pairs` are (edge, size Quantity)."""
    steps = []
    by_edge = {id(edge): size for edge, size in pairs}
    for group in picks.edge_groups([edge for edge, _ in pairs]):
        sizes = []
        for edge in group:
            sizes += [by_edge[id(edge)]] * len(edge["points"])
        step = {"kind": "round", "edges": {"near": picks.near_points(group)}, "size": sizes[0].json()}
        if any(not s.same_as(sizes[0]) for s in sizes):
            step["edgeSizes"] = [s.json() for s in sizes]
        steps.append(step)
    return steps


def _fillet(item, ctx):
    data = item.get("data") or {}
    sets = data.get("sets") or []
    if not sets:
        return Refusal("This round has no edges to copy.")
    for entry in sets:
        kind = entry.get("kind")
        if kind != "constant":
            return Refusal(_FILLET_SET_REFUSALS.get(kind, "This kind of round is not copied yet."))
        if "feature" in (entry.get("input_kinds") or []):
            return Refusal("A round that follows another step's edges is not copied yet.")
        if entry.get("continuity") == "curvature":
            return Refusal("Rounds with curvature continuity are not copied yet.")
        radius = entry.get("radius")
        if not isinstance(radius, (int, float)) or not radius > 0:
            return Refusal("This round has no readable radius.")
    sizes = {n: values.quantity(ctx, item, "sets.%d.radius" % n, entry["radius"]) for n, entry in enumerate(sets)}
    pairs = [(edge, sizes[n]) for edge, n in _flat_edges(sets)]
    if not pairs or _unlocated([edge for edge, _ in pairs]):
        return Refusal("The edges of this round could not be located.")
    if any(entry.get("continuity") == "other" for entry in sets):
        ctx.note("The smoothness of this round could not be read; a tangent round was used.")
    if data.get("rolling_ball") is False:
        ctx.note("Fusion used setback corners for this round. The copy uses rolling ball corners, so corners where "
                 "three or more rounded edges meet can look different.")
    steps = _fillet_steps(pairs)
    _split_note(ctx, steps)
    return steps


def _chamfer_size(entry):
    """The one size of a chamfer set, or a Refusal when the two sides differ."""
    kind = entry.get("kind")
    uneven = Refusal("Chamfers with two sizes are not copied yet.")
    distance = entry.get("distance")
    if kind == "equal":
        size = distance
    elif kind == "twoDistances":
        other = entry.get("distance_two")
        if not isinstance(distance, (int, float)) or not isinstance(other, (int, float)) or not _close(distance, other):
            return uneven
        size = distance
    elif kind == "distanceAngle":
        angle = entry.get("angle_deg")
        if not isinstance(angle, (int, float)) or not _close(angle, EQUAL_ANGLE_DEG, ANGLE_TOL):
            return uneven
        size = distance
    else:
        return Refusal("This kind of chamfer is not copied yet.")
    if not isinstance(size, (int, float)) or not size > 0:
        return Refusal("This chamfer has no readable size.")
    return size


def _chamfer(item, ctx):
    data = item.get("data") or {}
    sets = data.get("sets") or []
    if not sets:
        return Refusal("This chamfer has no edges to copy.")
    groups = []
    for n, entry in enumerate(sets):
        size = _chamfer_size(entry)
        if isinstance(size, Refusal):
            return size
        if entry.get("kind") != "equal":
            for path in ("distance_two", "angle_deg"):
                values.pin(ctx, item, "sets.%d.%s" % (n, path), "the chamfer in %s needs it to stay as it is"
                           % item.get("name", "a step"))
        size = values.quantity(ctx, item, "sets.%d.distance" % n, size)
        if "feature" in (entry.get("input_kinds") or []):
            return Refusal("A chamfer that follows another step's edges is not copied yet.")
        if _unlocated(entry.get("edges") or []):
            return Refusal("The edges of this chamfer could not be located.")
        for group in groups:
            if group["size"].same_as(size):
                group["edges"] += entry.get("edges") or []
                break
        else:
            groups.append({"size": size, "edges": list(entry.get("edges") or [])})
    groups = [g for g in groups if g["edges"]]
    if not groups:
        return Refusal("This chamfer has no edges to copy.")
    if data.get("corner_type", "chamfer") != "chamfer":
        ctx.note("Fusion used another corner type for this chamfer; the copy uses the default one.")
    if len(groups) > 1:
        ctx.note("Chamfers of different sizes are applied one after the other.")
    steps = []
    for group in groups:
        for part in picks.edge_groups(group["edges"]):
            steps.append({"kind": "bevel", "edges": {"near": picks.near_points(part)},
                          "size": group["size"].json()})
    _split_note(ctx, steps)
    return steps


def _shell(item, ctx):
    data = item.get("data") or {}
    if (data.get("outside") or 0) > 0:
        return Refusal("Shells that grow outward are not copied yet.")
    if data.get("bodies_input"):
        return Refusal("Closed hollow shells are not copied yet.")
    if data.get("shell_type", "sharp") != "sharp":
        return Refusal("Shells with rounded corners are not copied yet.")
    thickness = data.get("inside")
    if not isinstance(thickness, (int, float)) or not thickness > 0:
        return Refusal("This shell has no readable wall thickness.")
    faces = data.get("faces") or []
    points = picks.face_points(faces)
    if not points:
        return Refusal("This shell has no open faces to copy.")
    if len(points) > picks.MAX_NEAR_POINTS:
        return Refusal("This shell opens more than %d faces." % picks.MAX_NEAR_POINTS)
    wall = values.quantity(ctx, item, "inside", thickness)
    return [{"kind": "shell", "thickness": wall.json(), "openFaces": {"near": points}}]


_HANDLERS = {"FilletFeature": _fillet, "ChamferFeature": _chamfer, "ShellFeature": _shell}


def handle(item, ctx):
    return _HANDLERS[item["type"]](item, ctx)
