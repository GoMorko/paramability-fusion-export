"""Captures of thin extrudes for the Orca tests and the live check. `python3 -m tests.orca_thin <folder>` writes
`CAPTURES` there as JSON files, for `scripts/orca_live_check.py write <folder>/<name>.json <out.3mf>`. Each target box
and volume is worked out from the shapes, so the live check can compare what Orca builds.

- `divider`: a 40 by 40 by 2 plate and a divider wall centred on one straight line 30 long (`len`), 1.6 thick
  (`wall`), from the plate's base plane 22 up, joined: 3200 + 30 * 1.6 * 20 = 4160 mm3.
- `ell`: an L shaped line (0, 0) to (30, 0) to (30, 20), its wall 2 thick (`wall_mm`) inside the corner, 20 up: the
  wall's outline is 30 * 2 + 18 * 2 = 96 mm2, so 1920 mm3.
- `frame_wall`: a wall 2 thick (`wall`) outside a centred 80 by 50 rectangle (`width`, `depth`), 30 up:
  (84 * 54 - 80 * 50) * 30 = 16080 mm3; with `wall` 3, (86 * 56 - 4000) * 30 = 24480.
- `ring_wall`: a wall 2 thick (`wall`) inside a centred circle 40 across (`dia`), 10 up:
  pi * (20^2 - 18^2) * 10 = 760 pi = 2387.61 mm3; with `wall` 3, 1110 pi = 3487.17.
"""
import json
import math
import os
import sys

from tests.derived_fixtures import dimension
from tests.orca_extents import B1, UP, capture, extrude, profile, rect, side, sketch_item
from tests.probe_helpers import model, user
from tests.sketch_solve_helpers import C, L, P, Sketch, rectangle

from lib.design_model.steps import thin as facts


def graph_of(s):
    record = s.record()
    for number, entity in enumerate(record["curves"]):
        entity["token"] = "e%d" % number
    return record


def _feature_model(name, expression, mm):
    return model(name, expression, mm, kind="feature", token="tok_" + name)


def _thin(data, location, thickness, path_name="d_wall", expression="wall"):
    data["thin"] = True
    data["thin_wall"] = {"location": location, "thickness": thickness, "location_two": location,
                         "thickness_two": None, "profile_type": "Path" if data.get("path") else "Profile"}
    data["params"]["thin.thickness"] = {"name": path_name, "expression": expression, "value": thickness}
    return data


def wall_faces(corners, low, high, bottom=True):
    """The flat faces Fusion lists for a wall whose outline is `corners` between the heights `low` and `high` on the
    XY plane: one per side at the middle of its edge, facing out, the top, and the bottom when `bottom`."""
    ring = corners + corners[:1]
    turn = 1.0 if sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(ring, ring[1:])) > 0 else -1.0
    out = []
    for a, b in zip(ring, ring[1:]):
        d = [b[0] - a[0], b[1] - a[1]]
        size = math.hypot(*d)
        out.append({"surface": "Plane", "point": [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2, (low + high) / 2],
                    "normal": [turn * d[1] / size, -turn * d[0] / size, 0.0]})
    edge = [(ring[0][0] + ring[1][0]) / 2, (ring[0][1] + ring[1][1]) / 2]
    out.append({"surface": "Plane", "point": edge + [high], "normal": [0.0, 0.0, 1.0]})
    if bottom:
        out.append({"surface": "Plane", "point": edge + [low], "normal": [0.0, 0.0, -1.0]})
    return out


def path_record(points, sketch="Sketch2", token="s2"):
    curves = [{"kind": "line", "start": list(a) + [0.0], "end": list(b) + [0.0], "opposed": False,
               "entity": "ln%d" % n, "flat": {"kind": "line", "start": list(a), "end": list(b)}}
              for n, (a, b) in enumerate(zip(points, points[1:]))]
    return {"closed": False, "kind": "sketch", "sketch": sketch, "sketch_token": token, "frame": UP,
            "reference": {"kind": "constructionPlane", "token": "tok_xy", "origin": True}, "projected": False,
            "curves": curves, "edges": []}


# ---- a divider centred on one line -----------------------------------------------------------------------------

def divider_graph(length=30.0):
    """Sketch2: one horizontal line `len` long whose middle is the sketch origin."""
    s = Sketch()
    a, b = s.point(-length / 2, 0.0), s.point(length / 2, 0.0)
    line = s.line(a, b)
    s.con("horizontal", L(line))
    s.con("midpoint", P(0), L(line))
    dimension(s, "linear", [L(line)], length, "d_len", "len", "horizontal")
    record = graph_of(s)
    record.update(sketch="Sketch2", token="s2")
    return record


def divider(length=30.0, thickness=1.6, height=22.0):
    points = [(-length / 2, 0.0), (length / 2, 0.0)]
    plate = extrude(1, "Plate", [profile("Sketch1", UP, rect(-20, -20, 20, 20))], side_one=side(2.0), end_offset=2.0,
                    target_box_before=None)
    corners = facts.band([list(p) for p in points], thickness / 2, thickness / 2)
    wall = extrude(3, "Divider", [{"kind": "other", "type": "Path"}], operation="join", side_one=side(height),
                   end_offset=None, target_box_before={"min": [-20.0, -20.0, 0.0], "max": [20.0, 20.0, 2.0]},
                   path=path_record(points), wall_faces=wall_faces(corners, 0.0, height, bottom=False))
    _thin(wall["data"], "center", thickness)
    items = [sketch_item(0, "Sketch1"), plate, sketch_item(2, "Sketch2"), wall]
    volume = 40.0 * 40.0 * 2.0 + length * thickness * (height - 2.0)
    found = capture(items, ((-20.0, -20.0, 0.0), (20.0, 20.0, height)), volume,
                    [user("len", "%g mm" % length, length), user("wall", "%g mm" % thickness, thickness)],
                    [model("d_len", "len", length, sketch="Sketch2"), _feature_model("d_wall", "wall", thickness)])
    found["design"] = "Thin divider"
    found["sketch_graphs"] = [divider_graph(length)]
    return found


# ---- an L shaped line, its wall on one side --------------------------------------------------------------------

ELL_POINTS = [(0.0, 0.0), (30.0, 0.0), (30.0, 20.0)]


def ell(thickness=2.0, height=20.0, location="side1"):
    """The wall stands left of the line (inside the corner) for side one."""
    left, right = facts.reaches(facts.RULE[location], thickness)
    corners = facts.band([list(p) for p in ELL_POINTS], left, right)
    wall = extrude(1, "Extrude1", [{"kind": "other", "type": "Path"}], side_one=side(height), end_offset=None,
                   target_box_before=None, path=path_record(ELL_POINTS, "Sketch1", "s1"),
                   wall_faces=wall_faces(corners, 0.0, height))
    _thin(wall["data"], location, thickness, "d_wall", "wall_mm")
    area = abs(sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(corners, corners[1:] + corners[:1]))) / 2.0
    xs, ys = [c[0] for c in corners], [c[1] for c in corners]
    found = capture([sketch_item(0, "Sketch1"), wall], ((min(xs), min(ys), 0.0), (max(xs), max(ys), height)),
                    area * height, [user("wall_mm", "%g mm" % thickness, thickness)],
                    [_feature_model("d_wall", "wall_mm", thickness)])
    found["design"] = "Thin L"
    return found


# ---- closed outlines -------------------------------------------------------------------------------------------

def frame_graph(width=80.0, depth=50.0):
    """Sketch1: a `width` by `depth` rectangle centred on the origin by the middle of a diagonal."""
    s = Sketch()
    corners = [s.point(-width / 2, -depth / 2), s.point(width / 2, -depth / 2), s.point(width / 2, depth / 2),
               s.point(-width / 2, depth / 2)]
    lines = rectangle(s, corners)
    diagonal = s.line(corners[0], corners[2], construction=True)
    s.con("midpoint", P(0), L(diagonal))
    dimension(s, "linear", [L(lines[0])], width, "d_width", "width", "horizontal")
    dimension(s, "linear", [L(lines[1])], depth, "d_depth", "depth", "vertical")
    return graph_of(s)


def frame_wall(width=80.0, depth=50.0, thickness=2.0, height=30.0, location="side2", end_area=None):
    """A wall `thickness` thick outside the rectangle; `end_area` stands for what Fusion measured (the sharp
    cornered outside wall unless given)."""
    sharp = (width + 2 * thickness) * (depth + 2 * thickness) - width * depth
    data_area = sharp if end_area is None else end_area
    item = extrude(1, "Extrude1", [profile("Sketch1", UP, rect(-width / 2, -depth / 2, width / 2, depth / 2))],
                   side_one=side(height), end_offset=height, target_box_before=None, end_area=data_area)
    _thin(item["data"], location, thickness)
    half = (width / 2 + thickness, depth / 2 + thickness)
    found = capture([sketch_item(0, "Sketch1"), item], ((-half[0], -half[1], 0.0), (half[0], half[1], height)),
                    sharp * height,
                    [user("width", "%g mm" % width, width), user("depth", "%g mm" % depth, depth),
                     user("wall", "%g mm" % thickness, thickness)],
                    [model("d_width", "width", width, sketch="Sketch1"), model("d_depth", "depth", depth,
                                                                               sketch="Sketch1"),
                     _feature_model("d_wall", "wall", thickness)])
    found["design"] = "Thin frame"
    found["sketch_graphs"] = [frame_graph(width, depth)]
    return found


def ring_graph(diameter=40.0):
    """Sketch1: a circle `dia` across, centred on the origin."""
    s = Sketch()
    ring = s.circle(0, diameter / 2)
    dimension(s, "diameter", [C(ring)], diameter, "d_dia", "dia")
    return graph_of(s)


def ring_wall(diameter=40.0, thickness=2.0, height=10.0, location="side1"):
    """A wall `thickness` thick inside the circle."""
    r = diameter / 2
    area = math.pi * (r * r - (r - thickness) ** 2)
    circle = [{"kind": "circle", "center": [0.0, 0.0], "radius": r}]
    item = extrude(1, "Extrude1", [profile("Sketch1", UP, circle)], side_one=side(height), end_offset=height,
                   target_box_before=None, end_area=area)
    _thin(item["data"], location, thickness)
    found = capture([sketch_item(0, "Sketch1"), item], ((-r, -r, 0.0), (r, r, height)), area * height,
                    [user("dia", "%g mm" % diameter, diameter), user("wall", "%g mm" % thickness, thickness)],
                    [model("d_dia", "dia", diameter, sketch="Sketch1"), _feature_model("d_wall", "wall", thickness)])
    found["design"] = "Thin ring"
    found["sketch_graphs"] = [ring_graph(diameter)]
    return found


def onto_plate(build, operation):
    """`build()` as a step on a 120 by 100 plate 6 thick (drawn with numbers, under the sketch plane): the thin
    extrude joins, cuts or intersects it. The target box and volume are not worked out."""
    found = build()
    item = found["items"][-1]
    for entry in found["items"]:
        entry["index"] += 2
    plate = extrude(1, "Plate", [profile("Sketch0", dict(UP, origin=[0.0, 0.0, -3.0]), rect(-60, -50, 60, 50))],
                    side_one=side(6.0), end_offset=6.0, target_box_before=None)
    item["data"]["operation"] = operation
    item["data"]["participants"] = [dict(B1)]
    item["data"]["target_box_before"] = {"min": [-60.0, -50.0, -3.0], "max": [60.0, 50.0, 3.0]}
    found["items"] = [sketch_item(0, "Sketch0"), plate] + found["items"]
    return found


# The live check captures, by file name.
CAPTURES = {"orca_thin_divider": divider, "orca_thin_ell": ell, "orca_thin_frame": frame_wall,
            "orca_thin_ring": ring_wall}


def write(folder):
    os.makedirs(folder, exist_ok=True)
    for name, build in CAPTURES.items():
        with open(os.path.join(folder, name + ".json"), "w", encoding="utf-8") as f:
            json.dump(build(), f, indent=1)


if __name__ == "__main__":
    write(sys.argv[1])
