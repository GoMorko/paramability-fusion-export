"""Captures of rounds and chamfers on the side edges of straight extrudes, for the Orca tests and the live check
(`scripts/orca_live_check.py write <file>` with a capture these write). Each target box and volume is worked out from
the shapes, so the live check can compare what Orca builds."""
import math

from tests.orca_extents import B1, UP, capture, extrude, model, param, profile, rect, side, sketch_item
from tests.probe_helpers import user


def lines(points):
    return [{"kind": "line", "start": list(a), "end": list(b)} for a, b in zip(points, points[1:] + points[:1])]


def edge(point):
    return {"token": "e%g_%g_%g" % tuple(point), "closed": False, "points": [list(point)]}


def finish(index, name, sets, chamfer=False, params=None):
    """A fillet (or chamfer) step: `sets` is a list of (edge points, size)."""
    entries = []
    for points, size in sets:
        entry = {"kind": "equal", "distance": size} if chamfer else \
            {"kind": "constant", "radius": size, "continuity": "tangent"}
        entry.update(input_kinds=["edge"], edges=[edge(p) for p in points])
        entries.append(entry)
    data = {"corner_type": "chamfer", "sets": entries} if chamfer else {"rolling_ball": True, "sets": entries}
    data["params"] = params or {}
    return {"index": index, "name": name, "type": "ChamferFeature" if chamfer else "FilletFeature",
            "suppressed": False, "health": "ok", "in_target_component": True, "bodies_after": [dict(B1)],
            "data": data}


def corner_area(size, chamfer=False, angle_deg=90.0):
    """The area a round of radius `size` (or an even chamfer) takes from a corner of `angle_deg`."""
    half = math.radians(angle_deg) / 2.0
    if chamfer:
        return 0.5 * size * size * math.sin(2 * half)
    reach = size / math.tan(half)
    return reach * size - size * size * (math.pi - 2 * half) / 2.0


# The plate: 40 by 20 from (-20, -10), 10 tall. Its side edges, measured at mid height.
PLATE_SIDES = [(-20, -10, 5), (20, -10, 5), (20, 10, 5), (-20, 10, 5)]


def plate(sets, chamfer=False, sized=False):
    """The plate with its side edges rounded (or chamfered): `sets` of (edge points, size). With `sized` the first
    set's size is the user parameter `r`."""
    users, models, params = [], [], {}
    if sized:
        size = sets[0][1]
        users = [user("r", "%g mm" % size, size)]
        models = [model("d5", "r", size)]
        params = {("sets.0.distance" if chamfer else "sets.0.radius"): param("d5", "r", size)}
    taken = sum(corner_area(size, chamfer) for points, size in sets for _ in points)
    items = [sketch_item(0, "Sketch1"),
             extrude(1, "Extrude1", [profile("Sketch1", UP, rect(-20, -10, 20, 10))], side_one=side(10.0),
                     end_offset=10.0, target_box_before=None),
             finish(2, "Chamfer1" if chamfer else "Fillet1", sets, chamfer, params)]
    return capture(items, ((-20, -10, 0), (20, 10, 10)), 10.0 * (800.0 - taken), users, models)


def plate_sized_outline(size=2.0):
    """An 80 by 60 by 32 box whose rectangle follows the sizes of its sketch graph, with its four side edges
    rounded."""
    import copy
    from tests.derived_fixtures import box_capture
    found = copy.deepcopy(box_capture())
    found["items"] = found["items"][:2] + [
        finish(2, "Fillet1", [([(x, y, 16) for x, y in ((-40, -30), (40, -30), (40, 30), (-40, 30))], size)])]
    found["target"]["volume_mm3"] = round(32.0 * (80.0 * 60.0 - 4 * corner_area(size)), 4)
    return found


def sized_outline_then_top(size=4.0, top_size=1.0, sized=None):
    """`plate_sized_outline` with its corners rounded by `size` (the user parameter `sized` when given), then all
    its top edges rounded by `top_size` (Orca's group of top edges)."""
    found = plate_sized_outline(size)
    if sized:
        found["parameters"]["user"].append(user(sized, "%g mm" % size, size))
        found["parameters"]["model"].append(model("r_" + sized, sized, size))
        found["items"][2]["data"]["params"] = {"sets.0.radius": param("r_" + sized, sized, size)}
    lean = size * math.cos(math.radians(45))
    top = [(0, -30, 32), (40, 0, 32), (0, 30, 32), (-40, 0, 32)]
    top += [(x * (40 - size + lean), y * (30 - size + lean), 32) for x, y in ((1, 1), (-1, 1), (-1, -1), (1, -1))]
    found["items"].append(dict(finish(3, "Fillet2", [(top, top_size)]), index=3))
    return found


def ell(sets, chamfer=False):
    """An L, 10 tall: a 40 by 10 bar along x and a 10 by 20 leg up y from its left end. Its inward corner is at
    (10, 10), its outer corners at (0, 0), (40, 0), (40, 10), (10, 30), (0, 30)."""
    outline = lines([(0, 0), (40, 0), (40, 10), (10, 10), (10, 30), (0, 30)])
    change = 0.0
    for points, size in sets:
        for p in points:
            inward = (p[0], p[1]) == (10, 10)
            change += corner_area(size, chamfer) * (1 if inward else -1)
    items = [sketch_item(0, "Sketch1"),
             extrude(1, "Extrude1", [profile("Sketch1", UP, outline)], side_one=side(10.0), end_offset=10.0,
                     target_box_before=None),
             finish(2, "Chamfer1" if chamfer else "Fillet1", sets, chamfer)]
    return capture(items, ((0, 0, 0), (40, 30, 10)), 10.0 * (600.0 + change), [], [])


# A wall 60 wide (x), 6 deep (y from -3 to 3) and 40 tall, and a window 40 by 12 cut through it along y.
WINDOW = [(-20, 0, 14), (20, 0, 14), (20, 0, 26), (-20, 0, 26)]


def window(size, chamfer=False):
    """The wall with the window's four edges along y rounded (or chamfered) by `size`. At a size of 6 the window's
    short sides are taken whole: it becomes a slot."""
    front = {"origin": [0.0, -3.0, 0.0], "x": [1.0, 0.0, 0.0], "y": [0.0, 0.0, 1.0], "z": [0.0, 1.0, 0.0]}
    cut = extrude(3, "Window", [profile("Sketch2", front, rect(-20, 14, 20, 26))], operation="cut",
                  side_one={"kind": "throughAll", "positive": True, "taper_deg": 0.0}, end_offset=None,
                  target_box_before={"min": [-30, -3, 0], "max": [30, 3, 40]})
    items = [sketch_item(0, "Sketch1"),
             extrude(1, "Wall", [profile("Sketch1", UP, rect(-30, -3, 30, 3))], side_one=side(40.0),
                     end_offset=40.0, target_box_before=None),
             sketch_item(2, "Sketch2"), cut,
             finish(4, "Chamfer1" if chamfer else "Fillet1", [(WINDOW, size)], chamfer)]
    hole = 40.0 * 12.0 - 4 * corner_area(size, chamfer)
    return capture(items, ((-30, -3, 0), (30, 3, 40)), 60.0 * 6.0 * 40.0 - 6.0 * hole, [], [])


# A block 40 by 30 by 20 and a pocket 20 by 10, 8 deep, cut down from its top.
POCKET = [(-10, -5, 16), (10, -5, 16), (10, 5, 16), (-10, 5, 16)]


def pocket(size):
    """The block with the pocket's four upright edges rounded by `size` (they run from the pocket's floor up)."""
    top = {"origin": [0.0, 0.0, 20.0], "x": [1.0, 0.0, 0.0], "y": [0.0, 1.0, 0.0], "z": [0.0, 0.0, 1.0]}
    cut = extrude(3, "Pocket", [profile("Sketch2", top, rect(-10, -5, 10, 5))], operation="cut",
                  side_one=side(-8.0), end_offset=-8.0, target_box_before={"min": [-20, -15, 0], "max": [20, 15, 20]})
    items = [sketch_item(0, "Sketch1"),
             extrude(1, "Block", [profile("Sketch1", UP, rect(-20, -15, 20, 15))], side_one=side(20.0),
                     end_offset=20.0, target_box_before=None),
             sketch_item(2, "Sketch2"), cut, finish(4, "Fillet1", [(POCKET, size)])]
    return capture(items, ((-20, -15, 0), (20, 15, 20)), 40.0 * 30.0 * 20.0 - 8.0 * (200.0 - 4 * corner_area(size)),
                   [], [])


def hexagon(size, chamfer=False):
    """A regular hexagon of 20 across its corners, 10 tall, with its six side edges rounded: corners of 120
    degrees."""
    points = [(10 * math.cos(math.radians(60 * k)), 10 * math.sin(math.radians(60 * k))) for k in range(6)]
    items = [sketch_item(0, "Sketch1"),
             extrude(1, "Extrude1", [profile("Sketch1", UP, lines(points))], side_one=side(10.0), end_offset=10.0,
                     target_box_before=None),
             finish(2, "Chamfer1" if chamfer else "Fillet1", [([(x, y, 5) for x, y in points], size)], chamfer)]
    area = 1.5 * math.sqrt(3) * 100.0 - 6 * corner_area(size, chamfer, 120.0)
    # The corners at x = -10 and 10 are taken in: by the arc's far point, or to the chamfer's line.
    reach_x = 10.0 - 0.5 * size if chamfer else 10.0 - size / math.sin(math.radians(60)) + size
    half_y = 10 * math.sin(math.radians(60))
    return capture(items, ((-reach_x, -half_y, 0), (reach_x, half_y, 10)), 10.0 * area, [], [])


def plate_then_top(side_size=3.0, top_size=1.0):
    """The plate with its side edges rounded, then all its top edges rounded (Orca's group of top edges). The top
    round takes a cross section of (1 - pi / 4) * size^2 along the straight sides, and along each corner arc the same
    section turned about the arc's centre (Pappus: its centroid lies 0.2234 of the size in from the wall)."""
    found = plate([(PLATE_SIDES, side_size)])
    top = [(0, -10, 10), (20, 0, 10), (0, 10, 10), (-20, 0, 10)]
    top += [(s * (20 - side_size + side_size * math.cos(math.radians(45))),
             t * (10 - side_size + side_size * math.sin(math.radians(45))), 10) for s, t in ((1, 1), (-1, 1), (-1, -1),
                                                                                           (1, -1))]
    found["items"].append(dict(finish(3, "Fillet2", [(top, top_size)]), index=3))
    section = (1 - math.pi / 4) * top_size ** 2
    inward = top_size * (10 - 3 * math.pi) / (12 - 3 * math.pi)
    straight = 2 * (40 - 2 * side_size) + 2 * (20 - 2 * side_size)
    found["target"]["volume_mm3"] = round(found["target"]["volume_mm3"]
                                          - section * (straight + 2 * math.pi * (side_size - inward)), 4)
    return found
