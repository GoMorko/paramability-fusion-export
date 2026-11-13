"""An extrude that starts on a face is measured from its sketch plane: the plane's own move and the face's move are
counted once (lib/translator/extrude/, lib/translator/sketch/sketch_motion.py)."""
import copy
import unittest

from tests import context  # noqa: F401
from tests.translator_helpers import load_capture, steps_of

from lib.params import size_table
from lib.params.expressions import evaluate
from lib.sketch_values.motion import Affine, Motion
from lib.translator import translate

LID = "emboss_lid_outline"
ITEM = 3
LID_TOP = 4.0


def as_extrude(capture, index=ITEM):
    """The emboss item rewritten as a plain extrude that starts on the lid top (the same joined letters)."""
    item = capture["items"][index]
    data = item["data"]
    face = data["faces"][0]
    item["type"] = "ExtrudeFeature"
    item["data"] = {
        "operation": "join",
        "profiles": data["profiles"],
        "start": {"kind": "fromEntity", "plane": face["plane"], "entity_type": "BRepFace",
                  "face_point": face["face_point"]},
        "extent_type": "one",
        "side_one": {"kind": "distance", "distance": data["depth"], "taper_deg": 0.0},
        "side_two": None, "symmetric": None, "thin": False,
        "participants": data["participants"],
        "target_box_before": data["target_box_before"],
        "end_offset": data["end_offset"],
        "profile_area": data["areas"][0],
        "end_area": data["end_area"],
    }
    return capture


def origin_height(capture, ticked, plane_terms):
    """The written height of the raised outline's sketch origin as a function of the sizes (a number or a formula),
    when the sketch plane at item `ITEM` follows `plane_terms` (size name to factor)."""
    params = capture["parameters"]
    table = size_table.build(params["user"], list(ticked), params["model"], "mm")
    motion = Motion({"%d/p0/plane" % ITEM: Affine(0.0, plane_terms, "Sketch2")}, unmeasured={})
    result = translate(capture, size_table=table, motion=motion)
    assert result.recipe is not None, result.refusal
    assert result.fixed == []
    return steps_of(result.recipe, "extrude")[-1]["sketch"]["on"]["origin"][2]


def height_at(written, sizes):
    return evaluate(written["expr"], sizes) if isinstance(written, dict) else written


class StartOnFaceTest(unittest.TestCase):
    CASES = {"emboss": lambda: load_capture(LID), "extrude": lambda: as_extrude(load_capture(LID))}

    def test_a_face_and_a_plane_that_move_together_start_on_the_face(self):
        for name, make in self.CASES.items():
            with self.subTest(name):
                written = origin_height(make(), ("lid_mm", "raise_mm"), {"lid_mm": 1.0})
                for lid in (4.0, 10.0):
                    self.assertAlmostEqual(height_at(written, {"lid_mm": lid, "raise_mm": 1.0}), lid)

    def test_a_face_that_stays_keeps_the_start_while_the_plane_moves(self):
        for name, make in self.CASES.items():
            with self.subTest(name):
                written = origin_height(make(), ("raise_mm",), {"raise_mm": LID_TOP})
                for raise_mm in (1.0, 3.0):
                    self.assertAlmostEqual(height_at(written, {"raise_mm": raise_mm}), LID_TOP)

    def test_without_a_moving_plane_the_start_is_the_face(self):
        for name, make in self.CASES.items():
            with self.subTest(name):
                result = translate(make())
                self.assertEqual(steps_of(result.recipe, "extrude")[-1]["sketch"]["on"]["origin"][2], LID_TOP)
