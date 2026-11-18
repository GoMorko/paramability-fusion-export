"""Captures of a Press Pull of a whole round face (a pin or a bore), for the Orca tests and the live check:

    python3 -m tests.orca_press_round <name> <capture.json>
    python3 scripts/orca_live_check.py write <capture.json> <out.3mf>

Volumes and boxes are exact (a cylinder of radius r and height h is pi r^2 h).
"""
import json
import math
import sys

from tests import context  # noqa: F401
from tests import orca_extents as ex
from tests.probe_helpers import user

BLOCK = ex.rect(-20, -20, 20, 20)
DOWN = {"origin": [0.0, 0.0, 0.0], "x": [1.0, 0.0, 0.0], "y": [0.0, -1.0, 0.0], "z": [0.0, 0.0, -1.0]}


def face(frame, outer, holes=()):
    """A flat end face of the round face: its outline in its own frame, z its outward normal."""
    return {"frame": frame, "space": "sketch", "loops": [{"outer": True, "curves": outer}]
            + [{"outer": False, "curves": h} for h in holes]}


def end(z, radius, normal, end_face):
    return {"kind": "circle", "center": [0.0, 0.0, float(z)], "normal": [0.0, 0.0, float(normal)],
            "radius": float(radius), "face": end_face}


def round_face(radius, outward, low, high, ends):
    """The round face of radius `radius` on the z axis between `low` and `high`: a pin or a boss (`outward`) or a
    bore."""
    return {"kind": "round", "token": "c1", "origin": [0.0, 0.0, float(low)], "axis": [0.0, 0.0, 1.0],
            "radius": float(radius), "point": [float(radius), 0.0, (low + high) / 2.0], "outward": outward,
            "meets_offset": False, "ends": ends}


def press_pull(index, faces, distance, expression=None):
    """A Press Pull of `faces` by `distance` (mm, along the outward normal); Fusion left the cylinders of the moved
    round faces. `expression` is the formula of the distance, when it follows a size."""
    after = [{"origin": [0.0, 0.0, 0.0], "axis": [0.0, 0.0, 1.0],
              "radius": f["radius"] + (distance if f["outward"] else -distance)} for f in faces if "radius" in f]
    data = {"distance": float(distance), "faces": faces, "faces_after": [], "rounds_after": after,
            "params": {"distance": ex.param("d9", expression, distance)} if expression else {}}
    return {"index": index, "name": "PressPull1", "type": "OffsetFacesFeature", "suppressed": False, "health": "ok",
            "message": "", "in_target_component": True, "bodies_after": [dict(ex.B1)], "data": data}


def pin_face(radius=5.0):
    """The round face of the pin of `pin_items`: radius 5 from the plate's top (z 5) to the pin's top (z 15)."""
    return round_face(radius, True, 5.0, 15.0, [
        end(15.0, radius, 1.0, face(ex.at(15.0), ex.circle(radius))),
        end(5.0, radius, 1.0, face(ex.at(5.0), BLOCK, [ex.circle(radius)]))])


def pin_items():
    """A 40 by 40 by 5 plate (8000 mm3) and a pin of radius 5 joined on its top, 10 high (z 5 to 15)."""
    return [ex.sketch_item(0, "Sketch1"),
            ex.extrude(1, "Plate", [ex.profile("Sketch1", ex.UP, BLOCK)], side_one=ex.side(5.0), end_offset=5.0,
                       target_box_before=None),
            ex.sketch_item(2, "Sketch2"),
            ex.extrude(3, "Pin", [ex.profile("Sketch2", ex.at(5.0), ex.circle(5.0))], operation="join",
                       side_one=ex.side(10.0), end_offset=10.0,
                       target_box_before={"min": [-20, -20, 0], "max": [20, 20, 5]})]


def _pin(distance, name, expression):
    users = [user(name, "%g mm" % abs(distance), abs(distance), "mm")]
    models = [ex.model("d9", expression, distance)]
    radius = 5.0 + distance
    items = pin_items() + [press_pull(4, [pin_face()], distance, expression)]
    return ex.capture(items, ((-20, -20, 0), (20, 20, 15)), 8000.0 + math.pi * radius * radius * 10.0, users, models)


def pin_grown(grow=1.0):
    """The pin grown by `grow_mm` (1): radius 6, 8000 + 360 pi = 9130.97 mm3, box (-20, -20, 0) to (20, 20, 15).
    `--set grow_mm=2` gives radius 7, 8000 + 490 pi = 9539.38 mm3; `--set grow_mm=0.5` radius 5.5,
    8000 + 302.5 pi = 8950.33 mm3."""
    return _pin(grow, "grow_mm", "grow_mm")


def pin_shrunk(shrink=1.0):
    """The pin shrunk by `shrink_mm` (1): radius 4, 8000 + 160 pi = 8502.65 mm3, box (-20, -20, 0) to (20, 20, 15).
    `--set shrink_mm=2` gives radius 3, 8000 + 90 pi = 8282.74 mm3; `--set shrink_mm=0.5` radius 4.5,
    8000 + 202.5 pi = 8636.17 mm3."""
    return _pin(-shrink, "shrink_mm", "-shrink_mm")


def bore_face(radius=4.0):
    """The round face of the bore of `bore_items`: radius 4 through the block, z 0 to 10."""
    return round_face(radius, False, 0.0, 10.0, [
        end(10.0, radius, 1.0, face(ex.at(10.0), BLOCK, [ex.circle(radius)])),
        end(0.0, radius, -1.0, face(DOWN, BLOCK, [ex.circle(radius)]))])


def bore_items():
    """A 40 by 40 by 10 block with a bore of radius 4 through it: 16000 - 160 pi mm3."""
    return [ex.sketch_item(0, "Sketch1"),
            ex.extrude(1, "Block", [ex.profile("Sketch1", ex.UP, BLOCK, [ex.circle(4.0)])], side_one=ex.side(10.0),
                       end_offset=10.0, target_box_before=None)]


def bore_grown(grow=0.5):
    """The bore grown by `grow_mm` (0.5): radius 4.5, 16000 - 202.5 pi = 15363.83 mm3, box (-20, -20, 0) to
    (20, 20, 10). `--set grow_mm=1` gives radius 5, 16000 - 250 pi = 15214.60 mm3; `--set grow_mm=2` radius 6,
    16000 - 360 pi = 14869.03 mm3."""
    users = [user("grow_mm", "%g mm" % grow, grow, "mm")]
    models = [ex.model("d9", "-grow_mm", -grow)]
    radius = 4.0 + grow
    items = bore_items() + [press_pull(2, [bore_face()], -grow, "-grow_mm")]
    return ex.capture(items, ((-20, -20, 0), (20, 20, 10)), 16000.0 - math.pi * radius * radius * 10.0, users,
                      models)


BUILDERS = {"pin_grown": pin_grown, "bore_grown": bore_grown, "pin_shrunk": pin_shrunk}


if __name__ == "__main__":
    with open(sys.argv[2], "w", encoding="utf-8") as out:
        json.dump(BUILDERS[sys.argv[1]](), out, indent=1)
