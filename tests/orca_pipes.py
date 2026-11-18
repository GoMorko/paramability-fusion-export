"""Captures of round pipes for the Orca tests and the live check:

    python3 -m tests.orca_pipes <name> <capture.json>
    python3 scripts/orca_live_check.py write <capture.json> <out.3mf>

Each pipe's section size is the user parameter `pipe_d` and a hollow pipe's wall is `wall`. Volumes are exact: a
circle of radius r whose centre runs along a path of length L sweeps pi r^2 L, a ring pi (R^2 - r^2) L.
"""
import json
import math
import sys

from tests import context  # noqa: F401
from tests.orca_extents import B1, UP, capture, extrude, model, profile, rect, sketch_item, side
from tests.probe_helpers import user


def line(a, b, frame):
    """A path line from `a` to `b` (3D) in the plane of `frame` (its x and y axes along X and Y)."""
    flat = [[p[0] - frame["origin"][0], p[1] - frame["origin"][1]] for p in (a, b)]
    return {"kind": "line", "start": list(a), "end": list(b), "opposed": False,
            "flat": {"kind": "line", "start": flat[0], "end": flat[1]}}


def arc(centre, radius, start_deg, end_deg, z):
    """A path arc in the plane of height `z`, counter clockwise about +Z from `start_deg` to `end_deg`."""
    def at(deg):
        return [centre[0] + radius * math.cos(math.radians(deg)), centre[1] + radius * math.sin(math.radians(deg)), z]

    a, b, m = at(start_deg), at(end_deg), at((start_deg + end_deg) / 2.0)
    return {"kind": "arc", "start": a, "end": b, "mid": m, "center": [centre[0], centre[1], z], "radius": radius,
            "normal": [0.0, 0.0, 1.0], "opposed": False,
            "flat": {"kind": "arc", "start": a[:2], "end": b[:2], "mid": m[:2], "center": list(centre),
                     "radius": radius}}


def path_of(curves, frame, closed=False):
    for n, curve in enumerate(curves):
        curve["entity"] = "p%d" % n
    return {"closed": closed, "kind": "sketch", "sketch": "Path", "sketch_token": "sp", "frame": dict(frame),
            "curves": curves, "edges": [], "reference": {"kind": "origin"}, "projected": False}


def pipe_item(index, path, size, wall=None, operation="newBody", end=None, volume=None, section="circular"):
    """A pipe of diameter `size` (the user parameter `pipe_d`), hollow with `wall` (`wall`) when given, along
    `path`. `end` is `(point, outward normal)` of its end face; `volume` the body it made, for a new body."""
    params = {"section_size": {"name": "d_pipe_d", "expression": "pipe_d", "value": size},
              "distance_one": {"name": "d_along", "expression": "1", "value": 1.0}}
    if wall is not None:
        params["section_thickness"] = {"name": "d_wall", "expression": "wall", "value": wall}
    data = {"operation": operation, "participants": [dict(B1)] if operation != "newBody" else [],
            "target_box_before": None, "section": section, "section_size": float(size), "hollow": wall is not None,
            "section_thickness": None if wall is None else float(wall), "distance_one": 1.0, "distance_two": None,
            "path": path, "params": params, "faces_after": {"start": [], "end": []}}
    if end is not None:
        data["faces_after"]["end"] = [{"point": list(end[0]), "normal": list(end[1])}]
    return {"index": index, "name": "Pipe1", "type": "PipeFeature", "suppressed": False, "health": "ok",
            "in_target_component": True, "bodies_after": [dict(B1)],
            "target_after": None if volume is None else {"volume_mm3": volume}, "data": data}


def pipe_parameters(size, wall=None):
    users = [user("pipe_d", "%g mm" % size, size)]
    models = [model("d_pipe_d", "pipe_d", size), model("d_along", "1", 1.0, unit="")]
    if wall is not None:
        users.append(user("wall", "%g mm" % wall, wall))
        models.append(model("d_wall", "wall", wall))
    return users, models


def _plate(index, low, high):
    """A block from `low` to `high` (3D corners), sketched on its bottom face."""
    return extrude(index, "Block", [profile("Block sketch", dict(UP, origin=[0.0, 0.0, low[2]]),
                                            rect(low[0], low[1], high[0], high[1]))],
                   side_one=side(high[2] - low[2]), end_offset=high[2] - low[2], target_box_before=None)


def solid_pipe_on_plate(size=6.0):
    """A plate from (-5, -10, 0) to (45, 10, 6), then a solid pipe of diameter `pipe_d` (6) joined to it along a
    40 mm line on its top face, from (0, 0, 6) along +X. Half of the pipe stands above the plate: 6000 + 0.5 pi
    (d/2)^2 40, so 6000 + 180 pi = 6565.49 mm3 at 6 and 6000 + 320 pi = 7005.31 mm3 at 8."""
    r = size / 2.0
    frame = dict(UP, origin=[0.0, 0.0, 6.0])
    path = path_of([line((0.0, 0.0, 6.0), (40.0, 0.0, 6.0), frame)], frame)
    users, models = pipe_parameters(size)
    items = [sketch_item(0, "Block sketch"), _plate(1, (-5.0, -10.0, 0.0), (45.0, 10.0, 6.0)), sketch_item(2, "Path"),
             pipe_item(3, path, size, operation="join", end=((40.0, 0.0, 6.0), (1.0, 0.0, 0.0)))]
    out = capture(items, ((-5.0, -10.0, 0.0), (45.0, 10.0, 6.0 + r)), 6000.0 + 0.5 * math.pi * r * r * 40.0, users,
                  models)
    out["_comment"] = solid_pipe_on_plate.__doc__
    return out


BEND_LENGTH = 20.0 + 10.0 * math.pi + 30.0


def hollow_pipe_bend(size=8.0, wall=1.0):
    """A hollow pipe of diameter `pipe_d` (8) and wall `wall` (1) as a new body on the XY plane: a 20 mm line along
    +X from the origin, a tangent arc of radius 20 through 90 degrees and a 30 mm line along +Y. The ring's centre runs
    on the path: pi (R^2 - r^2) (50 + 10 pi), so 350 pi + 70 pi^2 = 1790.43 mm3 at 8 and 1; 600 pi + 120 pi^2 =
    3069.31 at `wall` 2; 450 pi + 90 pi^2 = 2301.98 at `pipe_d` 10."""
    outer, inner = size / 2.0, size / 2.0 - wall
    path = path_of([line((0.0, 0.0, 0.0), (20.0, 0.0, 0.0), UP), arc((20.0, 20.0), 20.0, -90.0, 0.0, 0.0),
                    line((40.0, 20.0, 0.0), (40.0, 50.0, 0.0), UP)], UP)
    volume = math.pi * (outer * outer - inner * inner) * BEND_LENGTH
    users, models = pipe_parameters(size, wall)
    items = [sketch_item(0, "Path"),
             pipe_item(1, path, size, wall, end=((40.0, 50.0, outer - wall / 2.0), (0.0, 1.0, 0.0)), volume=volume)]
    out = capture(items, ((0.0, -outer, -outer), (40.0 + outer, 50.0, outer)), volume, users, models)
    out["_comment"] = hollow_pipe_bend.__doc__
    return out


CUT_INSIDE = 30.0 + 7.5 * math.pi + 15.0


def pipe_cut_into_block(size=6.0, low=(-10.0, -10.0, 0.0), high=(50.0, 30.0, 20.0)):
    """A block from (-10, -10, 0) to (50, 30, 20), then a solid pipe of diameter `pipe_d` (6) cut into it at height
    10: a line along +X from (-15, 0) to (20, 0), a tangent arc of radius 15 through 90 degrees to (35, 15) and a line
    along +Y to (35, 40). It enters through the face at x -10 and leaves through the face at y 30, so it cuts
    pi (d/2)^2 (45 + 7.5 pi): 48000 - 405 pi - 67.5 pi^2 = 46061.46 mm3 at 6, 48000 - 720 pi - 120 pi^2 = 44553.70 at
    8."""
    r = size / 2.0
    frame = dict(UP, origin=[0.0, 0.0, 10.0])
    path = path_of([line((-15.0, 0.0, 10.0), (20.0, 0.0, 10.0), frame), arc((20.0, 15.0), 15.0, -90.0, 0.0, 10.0),
                    line((35.0, 15.0, 10.0), (35.0, 40.0, 10.0), frame)], frame)
    users, models = pipe_parameters(size)
    pipe = pipe_item(3, path, size, operation="cut", end=((35.0, 40.0, 10.0), (0.0, 1.0, 0.0)))
    pipe["data"]["target_box_before"] = {"min": list(low), "max": list(high)}
    block = 1.0
    for a, b in zip(low, high):
        block *= b - a
    items = [sketch_item(0, "Block sketch"), _plate(1, low, high), sketch_item(2, "Path"), pipe]
    out = capture(items, (low, high), block - math.pi * r * r * CUT_INSIDE, users, models)
    out["_comment"] = pipe_cut_into_block.__doc__
    return out


BUILDERS = {"solid_pipe_on_plate": solid_pipe_on_plate, "hollow_pipe_bend": hollow_pipe_bend,
            "pipe_cut_into_block": pipe_cut_into_block}


if __name__ == "__main__":
    with open(sys.argv[2], "w", encoding="utf-8") as out:
        json.dump(BUILDERS[sys.argv[1]](), out, indent=1)
