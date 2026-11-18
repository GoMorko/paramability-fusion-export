"""Captures of a hole that goes up to a plane and of extrudes that start at a distance from a face, for the Orca tests
and the live check:

    python3 -m tests.orca_to_faces <name> <capture.json>
    python3 scripts/orca_live_check.py write <capture.json> <out.3mf>

Volumes and boxes are exact (no curves but the hole's cylinder, of area pi r^2).
"""
import json
import math
import sys

from tests import context  # noqa: F401
from tests import orca_extents as ex
from tests.probe_helpers import user

BLOCK = ex.rect(-20, -20, 20, 20)


def hole_item(index, name, plane, depth, **more):
    """A simple hole of diameter 5 at the middle of the top of the block (z 20), drilled down to `plane` (a
    construction plane or face record), `depth` mm long with a flat end."""
    target = dict(plane, kind="toEntity")
    data = {"hole_type": "simple", "tap_type": "simple", "thread_modeled": None, "diameter": 5.0, "tip_angle_deg": 180,
            "counterbore": None, "countersink": None, "direction": [0, 0, -1], "positions": [[0, 0, 20]],
            "extent": target, "side_cylinders": [{"origin": [0, 0, 20], "axis": [0, 0, -1], "radius": 2.5}],
            "end_points": [[0, 0, 20 - depth]], "end_face_types": ["plane"], "participants": [dict(ex.B1)]}
    data.update(more)
    return {"index": index, "name": name, "type": "HoleFeature", "suppressed": False, "health": "ok", "message": "",
            "in_target_component": True, "bodies_after": [dict(ex.B1)], "data": data}


def block_items():
    return [ex.sketch_item(0, "Sketch1"),
            ex.extrude(1, "Block", [ex.profile("Sketch1", ex.UP, BLOCK)], side_one=ex.side(20.0), end_offset=20.0,
                       target_box_before=None)]


def hole_to_plane(lift=8.0):
    """A 40 by 40 by 20 block (32000 mm3, box (-20, -20, 0) to (20, 20, 20)) with a hole of diameter 5 from the middle
    of its top down to Plane1, `lift_mm` (8) above the origin XY plane, so 12 deep: 32000 - 75 pi = 31764.38 mm3. The
    hole's depth is 20 - lift_mm: with lift_mm 5 the hole is 15 deep (32000 - 93.75 pi = 31705.48) and with 12 it is 8
    deep (32000 - 50 pi = 31842.92)."""
    users = [user("lift_mm", "%g mm" % lift, lift, "mm")]
    models = [ex.model("d20", "lift_mm", lift, kind="constructionPlane", token="cp1")]
    items = block_items() + [ex.plane_item(2, "Plane1"), ex.sketch_item(3, "Sketch2"),
                             hole_item(4, "Hole1", ex.plane_target(lift, "cp1", made_by=2), 20.0 - lift)]
    return ex.capture(items, ((-20, -20, 0), (20, 20, 20)), 32000.0 - math.pi * 6.25 * (20.0 - lift), users, models)


def _plate(height=10.0):
    return [ex.sketch_item(0, "Sketch1"),
            ex.extrude(1, "Plate", [ex.profile("Sketch1", ex.UP, BLOCK)], side_one=ex.side(height),
                       end_offset=height, target_box_before=None)]


def boss_into_plate(inset=-2.0):
    """A 40 by 40 by 10 plate (16000 mm3) and a 10 by 10 boss sketched on its base plane that starts From the plate's
    top face at the offset `-inset_mm` (inset_mm 2: 2 mm below the face, inside the plate) and goes 5 mm up. The boss starts at z
    8 and ends at z 13: 16000 + 100 * 3 = 16300 mm3, box (-20, -20, 0) to (20, 20, 13). Orca keeps the sketch plane
    where it is (z 8), so `--set inset_mm=...` leaves the body as it is."""
    users = [user("inset_mm", "%g mm" % -inset, -inset, "mm")]
    models = [ex.model("d9", "-inset_mm", inset)]
    start = dict(ex.face_target(10.0, (15.0, 5.0)), kind="fromEntity")
    items = _plate() + [
        ex.sketch_item(2, "Sketch2"),
        ex.extrude(3, "Boss", [ex.profile("Sketch2", ex.UP, ex.rect(-5, -5, 5, 5))], operation="join",
                   side_one=ex.side(5.0), start=start, start_offset=None, end_offset=13.0, end_area=100.0,
                   end_normal=[0.0, 0.0, 1.0], params={"start.offset": ex.param("d9", "-inset_mm", inset)},
                   target_box_before={"min": [-20, -20, 0], "max": [20, 20, 10]})]
    return ex.capture(items, ((-20, -20, 0), (20, 20, 10 + 5 + inset)), 16000.0 + 100.0 * (5 + inset), users, models)


def lowered_post(rise=2.0):
    """The same plate and a 10 by 10 post that starts From its top face at the offset `rise_mm` (2: 2 mm above the
    face) and goes 4 mm down into the plate. Fusion measures the start face at z 12 (`start_offset`). The post covers
    z 8 to 12: 16000 + 100 * 2 = 16200 mm3, box (-20, -20, 0) to (20, 20, 12)."""
    users = [user("rise_mm", "%g mm" % rise, rise, "mm")]
    models = [ex.model("d9", "rise_mm", rise)]
    start = dict(ex.face_target(10.0, (15.0, 5.0)), kind="fromEntity")
    items = _plate() + [
        ex.sketch_item(2, "Sketch2"),
        ex.extrude(3, "Post", [ex.profile("Sketch2", ex.UP, ex.rect(-5, -5, 5, 5))], operation="join",
                   side_one=ex.side(-4.0), start=start, start_offset=10.0 + rise, end_offset=None,
                   params={"start.offset": ex.param("d9", "rise_mm", rise)},
                   target_box_before={"min": [-20, -20, 0], "max": [20, 20, 10]})]
    return ex.capture(items, ((-20, -20, 0), (20, 20, 10 + rise)), 16000.0 + 100.0 * rise, users, models)


BUILDERS = {"hole_to_plane": hole_to_plane, "boss_into_plate": boss_into_plate, "lowered_post": lowered_post}


if __name__ == "__main__":
    with open(sys.argv[2], "w", encoding="utf-8") as out:
        json.dump(BUILDERS[sys.argv[1]](), out, indent=1)
