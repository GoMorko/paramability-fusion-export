"""Captures of rounds and chamfers on the side edges of outlines that follow user parameters, for the tests of corner
tools and the live check (`scripts/orca_live_check.py write <file>` with a capture these write), and the area such
corners leave (`rounded_area`), worked out from the corners of the outline at any values. Target volumes are worked
out from the same corners, so the live check can compare what Orca builds."""
import math

from tests.derived_fixtures import dimension
from tests.orca_cuts import PLATE_HEIGHT, WINDOW, Shape, onto_plate_capture, outline_capture, window_capture
from tests.orca_extents import model, param
from tests.orca_outline import corner_area, finish
from tests.probe_helpers import user
from tests.sketch_solve_helpers import L, P

from lib.orca_translate import halfplanes


def _turn(points, k):
    """The turn of the counter clockwise loop at corner `k` (degrees, above zero at a convex corner)."""
    n = len(points)
    a, p, b = points[k - 1], points[k], points[(k + 1) % n]
    d1 = math.atan2(p[1] - a[1], p[0] - a[0])
    d2 = math.atan2(b[1] - p[1], b[0] - p[0])
    return (math.degrees(d2 - d1) + 180.0) % 360.0 - 180.0


def rounded_area(points, rounds):
    """The area of the loop `points` with corner `k` rounded (or chamfered) for each `k: (size, chamfer)` of
    `rounds`: a convex corner loses the corner's area, an inward one gains it."""
    if halfplanes.area(points) < 0:
        n = len(points)
        points = points[::-1]
        rounds = {n - 1 - k: v for k, v in rounds.items()}
    total = halfplanes.area(points)
    for k, (size, chamfer) in rounds.items():
        turn = _turn(points, k)
        total -= math.copysign(corner_area(size, chamfer, 180.0 - abs(turn)), turn)
    return total


def rounded_inside(points, rounds, x):
    """True when the point `x` lies inside the loop with its corners rounded as `rounded_area` takes them."""
    inside = halfplanes.in_polygon(points, x)
    if halfplanes.area(points) < 0:
        n = len(points)
        points = points[::-1]
        rounds = {n - 1 - k: v for k, v in rounds.items()}
    n = len(points)
    for k, (size, chamfer) in rounds.items():
        p, a, b = points[k], points[k - 1], points[(k + 1) % n]
        ua, ub = _unit(a, p), _unit(b, p)
        angle = math.acos(max(-1.0, min(1.0, ua[0] * ub[0] + ua[1] * ub[1])))
        reach = size if chamfer else size / math.tan(angle / 2.0)
        ta, tb = (p[0] + ua[0] * reach, p[1] + ua[1] * reach), (p[0] + ub[0] * reach, p[1] + ub[1] * reach)
        mid = _unit((ua[0] + ub[0], ua[1] + ub[1]), (0.0, 0.0))
        centre = (p[0] + mid[0] * size / math.sin(angle / 2.0), p[1] + mid[1] * size / math.sin(angle / 2.0))
        sides = [_side(p, ta, x), _side(ta, tb, x), _side(tb, p, x)]
        if (all(v > 0 for v in sides) or all(v < 0 for v in sides)) and \
                (chamfer or math.hypot(x[0] - centre[0], x[1] - centre[1]) > size):
            inside = not inside
    return inside


def _unit(to, frm):
    dx, dy = to[0] - frm[0], to[1] - frm[1]
    length = math.hypot(dx, dy)
    return dx / length, dy / length


def _side(a, b, c):
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def _centred(s, v):
    """A rectangle `wide` by `deep` whose centre is the fixed point (30, 20): it keeps its place."""
    w, d = v["wide"], v["deep"]
    centre = s.point(30.0, 20.0, fixed=True)
    ids = [s.point(30.0 + x * w / 2.0, 20.0 + y * d / 2.0) for x, y in ((-1, -1), (1, -1), (1, 1), (-1, 1))]
    lines = []
    for k in range(4):
        line = s.line(ids[k], ids[(k + 1) % 4])
        s.con("horizontal" if k % 2 == 0 else "vertical", L(line))
        lines.append(line)
    diagonal = s.line(ids[0], ids[2], construction=True)
    s.con("midpoint", P(centre), L(diagonal))
    dimension(s, "linear", [L(lines[0])], w, "d1", "wide", "horizontal")
    dimension(s, "linear", [L(lines[1])], d, "d2", "deep", "vertical")
    return ids


# A block 24 by 16 centred on (30, 20) of the plate `orca_cuts.PLATE`, its width and depth user parameters.
CENTRED = Shape({"wide": 24.0, "deep": 16.0, "t": 10.0}, _centred)


def add_steps(capture, shape, steps, z, first=None):
    """Append round or chamfer steps on the side edges of the shape's outline, measured at height `z`: each step is
    `(name, chamfer, corners, size, size parameter or None)`, the corners by their index in the shape's loop. A size
    parameter becomes a user parameter of that name. Returns the capture."""
    corners = shape.corners()
    index = first if first is not None else max(item["index"] for item in capture["items"]) + 1
    for name, chamfer, which, size, sized in steps:
        params = {}
        if sized:
            capture["parameters"]["user"].append(user(sized, "%g mm" % size, size))
            capture["parameters"]["model"].append(model("r_" + sized, sized, size))
            params = {("sets.0.distance" if chamfer else "sets.0.radius"): param("r_" + sized, sized, size)}
        points = [(corners[k][0], corners[k][1], z) for k in which]
        capture["items"].append(finish(index, name, [(points, size)], chamfer, params))
        index += 1
    return capture


def rounds_of(steps, values=None):
    """`{corner index: (size, chamfer)}` of `steps` at `values` (a size parameter takes its value there)."""
    values = values or {}
    return {k: (values.get(sized, size) if sized else size, chamfer)
            for _, chamfer, which, size, sized in steps for k in which}


def outline_volume(shape, steps, values=None, height=None):
    """The volume of the shape's outline with the steps' corners, `t` (or `height`) tall."""
    values = dict(shape.values, **(values or {}))
    return rounded_area(shape.corners(values), rounds_of(steps, values)) * (height or values["t"])


def rounded_outline(shape, steps, extent="one"):
    """`outline_capture` of the shape with round and chamfer steps on its side edges (at mid height)."""
    found = outline_capture(shape, extent=extent)
    t = shape.values["t"]
    add_steps(found, shape, steps, {"one": t / 2.0, "symmetric": 0.0}[extent], first=2)
    found["target"]["volume_mm3"] = round(outline_volume(shape, steps), 4)
    return found


def rounded_window(steps, shape=WINDOW):
    """`orca_cuts.window_capture` with round or chamfer steps on the window's edges: the corners the window's own
    outline rounds fill the plate."""
    found = window_capture(shape)
    add_steps(found, shape, steps, 5.0, first=4)
    found["target"]["volume_mm3"] = round(window_volume(shape, steps), 4)
    return found


def window_volume(shape, steps, values=None):
    values = dict(shape.values, **(values or {}))
    return (2400.0 - rounded_area(shape.corners(values), rounds_of(steps, values))) * 10.0


def rounded_block(steps, operation="join", shape=CENTRED):
    """`orca_cuts.onto_plate_capture` of a rectangle that keeps its place, with round or chamfer steps on its side
    edges: above the plate for a join, inside it for a cut."""
    found = onto_plate_capture(shape, operation)
    t = shape.values["t"]
    add_steps(found, shape, steps, min(t, PLATE_HEIGHT) / 2.0 if operation == "cut" else (PLATE_HEIGHT + t) / 2.0,
              first=4)
    found["target"]["volume_mm3"] = round(block_volume(shape, steps, operation=operation), 4)
    return found


def block_volume(shape, steps, values=None, operation="join"):
    """The plate (6 tall) and the shape's outline with its corners, `t` tall, from the plate's plane: joined to it, cut
    from it, or what both share."""
    values = dict(shape.values, **(values or {}))
    area = rounded_area(shape.corners(values), rounds_of(steps, values))
    if operation == "join":
        return 2400.0 * 6.0 + area * max(0.0, values["t"] - 6.0)
    if operation == "cut":
        return 2400.0 * 6.0 - area * min(values["t"], 6.0)
    return area * min(values["t"], 6.0)


def rounded_pattern(steps, copies=2, spacing=30.0):
    """The window (at x 5) cut through the plate with its corners rounded, both repeated `copies` times `spacing`
    apart along x by one pattern of features."""
    from tests.orca_cuts import window_pattern_capture
    found = window_pattern_capture(copies, spacing)
    pattern = found["items"].pop()
    shape = Shape(dict(WINDOW.values, wx=5.0), WINDOW.draw)
    add_steps(found, shape, steps, 5.0, first=4)
    pattern["index"] = 4 + len(steps)
    pattern["data"]["sources"] = [3] + list(range(4, 4 + len(steps)))
    found["items"].append(pattern)
    area = rounded_area(shape.corners(), rounds_of(steps))
    found["target"]["volume_mm3"] = round((2400.0 - copies * area) * 10.0, 4)
    return found


# The L of `orca_cuts`: its inward corner (3) and an outer one (1) rounded by 2, another outer one (5) chamfered by 3.
ELL_STEPS = [("Fillet1", False, [3, 1], 2.0, None), ("Chamfer1", True, [5], 3.0, None)]
# The trapezoid: a corner where a side turns with `ang` (1) rounded by the user parameter `fr`, a top one (3)
# chamfered by 2.
TRAPEZOID_STEPS = [("Fillet1", False, [1], 3.0, "fr"), ("Chamfer1", True, [3], 2.0, None)]
# Every corner of a rectangle rounded by 2.
FOUR = [("Fillet1", False, [0, 1, 2, 3], 2.0, None)]


def pattern_item(index, sources, copies, spacing):
    """A rectangular pattern of the features at the timeline indexes `sources`, `copies` of them `spacing` apart
    along x, on Body1."""
    elements = [{"id": k, "suppressed": False,
                 "frame": {"origin": [k * spacing, 0, 0], "x": [1, 0, 0], "y": [0, 1, 0], "z": [0, 0, 1]}}
                for k in range(copies)]
    data = {"entity_type": "features", "sources": list(sources), "direction_one": [1, 0, 0], "quantity_one": copies,
            "distance_one": spacing, "direction_two": None, "quantity_two": 1, "distance_two": 0.0,
            "distance_type": "spacing", "symmetric_one": False, "symmetric_two": False, "elements": elements,
            "suppressed_ids": []}
    return {"index": index, "name": "Pattern1", "type": "RectangularPatternFeature", "suppressed": False,
            "health": "ok", "in_target_component": True, "bodies_after": [{"token": "t1", "name": "Body1"}],
            "data": data}


def _placed_trapezoid(s, v):
    """The trapezoid of `orca_cuts.TRAPEZOID` with its base starting at the fixed point (10, 10), so that it sits
    inside the plate."""
    a, h, ang = v["base"], v["high"], v["ang"]
    run = h / math.tan(math.radians(ang))
    ids = [s.point(10.0 + x, 10.0 + y, fixed=(x, y) == (0, 0)) for x, y in ((0, 0), (a, 0), (a - run, h), (run, h))]
    lines = [s.line(ids[k], ids[(k + 1) % 4]) for k in range(4)]
    s.con("horizontal", L(lines[0]))
    s.con("horizontal", L(lines[2]))
    dimension(s, "linear", [P(ids[0]), P(ids[1])], a, "d1", "base", "horizontal")
    dimension(s, "linear", [P(ids[0]), P(ids[3])], h, "d2", "high", "vertical")
    dimension(s, "angular", [L(lines[0]), L(lines[3])], ang, "d3", "ang")
    dimension(s, "angular", [L(lines[0]), L(lines[1])], ang, "d4", "ang")
    return ids


# A trapezoid 20 wide and 10 high, its sides at 70 degrees to its base, inside the plate: a copy 25 along x fits too.
PLACED_TRAPEZOID = Shape({"base": 20.0, "high": 10.0, "ang": 70.0}, _placed_trapezoid, angles=("ang",))


def rounded_window_pattern(shape, steps, copies=2, spacing=25.0):
    """The shape's outline cut through the plate (`orca_cuts.window_capture`) with round or chamfer steps on its
    edges, all repeated `copies` times `spacing` apart along x by one pattern of features."""
    found = window_capture(shape)
    add_steps(found, shape, steps, 5.0, first=4)
    found["items"].append(pattern_item(4 + len(steps), range(3, 4 + len(steps)), copies, spacing))
    area = rounded_area(shape.corners(), rounds_of(steps))
    found["target"]["volume_mm3"] = round((2400.0 - copies * area) * 10.0, 4)
    return found


# A smaller block of `CENTRED`, 10 by 8 on (30, 20): a copy 15 along x still sits on the plate.
SMALL = Shape({"wide": 10.0, "deep": 8.0, "t": 10.0}, _centred)
B2 = {"token": "t2", "name": "Body2"}


def rounded_tool(steps, operation="join", copies=1, spacing=15.0, shape=SMALL):
    """The plate, then the shape's outline extruded `t` up from the plate's plane as a body of its own (Body2), its
    side edges rounded by `steps`, then a Combine that joins it to the plate or cuts it away (`operation`). With
    `copies` over 1, a pattern of features repeats the extrude, the rounds and the Combine `spacing` apart along x."""
    found = onto_plate_capture(shape, "join")
    block = found["items"][3]
    block["bodies_after"] = [dict(B2)]
    block["data"].update(operation="newBody", participants=[dict(B2)], target_box_before=None)
    add_steps(found, shape, steps, shape.values["t"] / 2.0, first=4)
    for item in found["items"][4:]:
        item["bodies_after"] = [dict(B2)]
    index = 4 + len(steps)
    plate = {"token": "t1", "name": "Body1"}
    found["items"].append({"index": index, "name": "Combine1", "type": "CombineFeature", "suppressed": False,
                           "health": "ok", "in_target_component": True, "bodies_after": [dict(plate)],
                           "data": {"target": dict(plate), "tools": [dict(B2)], "operation": operation,
                                    "keep_tools": False}})
    if copies > 1:
        found["items"].append(pattern_item(index + 1, list(range(3, index + 1)), copies, spacing))
    t = shape.values["t"]
    area = rounded_area(shape.corners(), rounds_of(steps))
    if operation == "join":
        volume = 2400.0 * PLATE_HEIGHT + copies * area * max(0.0, t - PLATE_HEIGHT)
        top = max(t, PLATE_HEIGHT)
    else:
        volume = 2400.0 * PLATE_HEIGHT - copies * area * min(t, PLATE_HEIGHT)
        top = PLATE_HEIGHT
    found["target"]["box"] = {"min": [0.0, 0.0, 0.0], "max": [60.0, 40.0, top]}
    found["target"]["volume_mm3"] = round(volume, 4)
    return found
