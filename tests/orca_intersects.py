"""Captures of extrude intersects with several outlines, for the Orca tests and the live check:

    python3 -m tests.orca_intersects <name> <capture.json>
    python3 scripts/orca_live_check.py write <capture.json> <out.3mf>

A 40 by 40 block, 10 high from z 0, is intersected with an extrude through all of its outlines, drawn on the block's
bottom plane. Volumes are exact: a circle of radius r keeps pi r^2 x 10, a ring pi (R^2 - r^2) x 10.
"""
import json
import math
import sys

from tests import context  # noqa: F401
from tests.derived_fixtures import dimension
from tests.orca_extents import UP, capture, extrude, profile, rect, sketch_item, side
from tests.probe_helpers import model, user
from tests.sketch_solve_helpers import C, Sketch

BLOCK = {"min": [-20.0, -20.0, 0.0], "max": [20.0, 20.0, 10.0]}
THROUGH = {"kind": "throughAll", "positive": True, "taper_deg": 0.0}


def _circles_graph(centres, radius, param):
    """The graph of a sketch of circles at fixed `centres`, all with the diameter `param`."""
    s = Sketch()
    for cx, cy in centres:
        centre = s.point(cx, cy, fixed=True)
        ring = s.circle(centre, radius)
        dimension(s, "diameter", [C(ring)], 2.0 * radius, "d_" + param, param)
    record = s.record()
    record.update(sketch="Tool sketch", token="s2")
    for number, entity in enumerate(record["curves"]):
        entity["token"] = "s2c%d" % number
    return record


def _intersect(profiles, target_box=BLOCK, **extra):
    return extrude(3, "Trim", profiles, operation="intersect", side_one=THROUGH, end_offset=None,
                   target_box_before=dict(target_box), **extra)


def _block():
    return [sketch_item(0, "Block sketch"),
            extrude(1, "Block", [profile("Block sketch", UP, rect(-20, -20, 20, 20))], side_one=side(10.0),
                    end_offset=10.0, target_box_before=None),
            sketch_item(2, "Tool sketch")]


def two_circles(radius=8.0):
    """The block intersected with two separate circles of diameter `hole_d` (16) at x -10 and x 10, both on y 0: two
    pieces in one body, 1280 pi = 4021.24 mm3 (`--set hole_d=12` gives 720 pi = 2261.95)."""
    centres = [(-10.0, 0.0), (10.0, 0.0)]
    tool = [dict(profile("Tool sketch", UP, [{"kind": "circle", "center": list(c), "radius": radius}]),
                 sketch_token="s2", space="sketch") for c in centres]
    volume = 2.0 * math.pi * radius ** 2 * 10.0
    items = _block() + [_intersect(tool)]
    out = capture(items, ((-10.0 - radius, -radius, 0.0), (10.0 + radius, radius, 10.0)), volume,
                  [user("hole_d", "%g mm" % (2 * radius), 2 * radius)],
                  [model("d_hole_d", "hole_d", 2 * radius, sketch="Tool sketch")])
    out["sketch_graphs"] = [_circles_graph(centres, radius, "hole_d")]
    out["_comment"] = two_circles.__doc__
    return out


def ring(outer=15.0, inner=5.0):
    """The block intersected with one ring outline, outer radius 15 and inner radius 5, about the origin: one
    piece of 200 pi x 10 = 6283.19 mm3."""
    tool = [profile("Tool sketch", UP, [{"kind": "circle", "center": [0.0, 0.0], "radius": outer}],
                    holes=[[{"kind": "circle", "center": [0.0, 0.0], "radius": inner}]])]
    volume = math.pi * (outer ** 2 - inner ** 2) * 10.0
    out = capture(_block() + [_intersect(tool)], ((-outer, -outer, 0.0), (outer, outer, 10.0)), volume)
    out["_comment"] = ring.__doc__
    return out


def ring_and_disc():
    """The block intersected with two outlines of one sketch: a ring (outer radius 15, inner 8) and a disc of radius
    4 inside its hole, both about the origin: pi (225 - 64 + 16) x 10 = 1770 pi = 5560.62 mm3 in one body (the
    two pieces lie apart)."""
    tool = [profile("Tool sketch", UP, [{"kind": "circle", "center": [0.0, 0.0], "radius": 15.0}],
                    holes=[[{"kind": "circle", "center": [0.0, 0.0], "radius": 8.0}]]),
            profile("Tool sketch", UP, [{"kind": "circle", "center": [0.0, 0.0], "radius": 4.0}])]
    out = capture(_block() + [_intersect(tool)], ((-15.0, -15.0, 0.0), (15.0, 15.0, 10.0)),
                  math.pi * (225.0 - 64.0 + 16.0) * 10.0)
    out["_comment"] = ring_and_disc.__doc__
    return out


def tapered_both_sides(deg=-10.0):
    """The block intersected with a disc of radius 15 on the plane z 5, extruded 10 long to both sides (5 each) and
    narrowing by 10 degrees: two cones of height 5 that join at the plane, so the part is
    2 pi (15^2 5 - 15 k 5^2 + k^2 5^3 / 3) = 6661.26 mm3 with k = tan 10 degrees (the walls lean in, `deg` is
    negative)."""
    k = math.tan(math.radians(-deg))
    lean = math.sin(math.radians(-deg))
    tool = [profile("Tool sketch", dict(UP, origin=[0.0, 0.0, 5.0]), [{"kind": "circle", "center": [0.0, 0.0],
                                                                      "radius": 15.0}])]
    step = extrude(3, "Trim", tool, operation="intersect", extent="symmetric", side_one=None,
                   symmetric={"distance": 10.0, "full_length": True, "taper_deg": deg}, end_offset=5.0,
                   target_box_before=dict(BLOCK), side_leans=[lean, -lean])
    volume = 2.0 * math.pi * (15.0 ** 2 * 5.0 - 15.0 * k * 25.0 + k * k * 125.0 / 3.0)
    out = capture(_block() + [step], ((-15.0, -15.0, 0.0), (15.0, 15.0, 10.0)), volume)
    out["_comment"] = tapered_both_sides.__doc__
    return out


BUILDERS = {"two_circles": two_circles, "ring": ring, "ring_and_disc": ring_and_disc,
            "tapered_both_sides": tapered_both_sides}


if __name__ == "__main__":
    with open(sys.argv[2], "w", encoding="utf-8") as out:
        json.dump(BUILDERS[sys.argv[1]](), out, indent=1)
