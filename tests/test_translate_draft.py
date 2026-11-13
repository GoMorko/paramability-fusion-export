"""Draft: the faces lean about the neutral plane; the way they lean is read from the part's volume."""
import unittest

from tests import context  # noqa: F401
from tests.test_translate_sized import table_of
from tests.translator_helpers import assert_schema_ok, left_out, load_capture, steps_of

from lib.translator import translate

TRAY = "filter_tray_sized"

WALL = {"token": "f1", "point": [40, 10, 5], "box": {"min": [40, 0, 0], "max": [40, 20, 10]}}
FLOOR = {"point": [0, 0, 0], "normal": [0, 0, 1]}


def drafted(volume_after=7900.0, **data):
    """The 40 x 20 x 10 plate of combine_cut with its right wall drafted from the floor."""
    capture = load_capture("combine_cut")
    capture["items"] = capture["items"][:2]
    found = {"faces": [WALL], "tangent_chain": False, "plane": FLOOR, "flipped": False, "two_angles": False,
             "symmetric": False, "angle_deg": 3.0, "angle_two_deg": None, "volume_before": 8000.0,
             "volume_after": volume_after}
    found.update(data)
    capture["items"].append({"index": 2, "name": "Draft1", "type": "DraftFeature", "suppressed": False,
                             "health": "ok", "message": "", "in_target_component": True,
                             "bodies_after": [{"token": "t1", "name": "Body1"}], "target_changed": True,
                             "data": found})
    return capture


class DraftTest(unittest.TestCase):
    def test_a_draft_that_takes_material_off_leans_the_faces_in(self):
        result = translate(drafted())
        step = steps_of(result.recipe, "draft")[0]
        self.assertEqual((step["faces"], step["angleDeg"]), ({"near": [[40.0, 10.0, 5.0]]}, 3.0))
        self.assertEqual(step["neutral"], {"origin": [0.0, 0.0, 0.0], "normal": [0.0, 0.0, 1.0]})
        assert_schema_ok(self, result.recipe)

    def test_a_draft_that_adds_material_leans_the_other_way(self):
        self.assertEqual(steps_of(translate(drafted(8100.0)).recipe, "draft")[0]["angleDeg"], -3.0)

    def test_the_angle_follows_its_size(self):
        capture = drafted(params={"angle_deg": {"name": "d9", "expression": "turn_deg / 30", "value": 3.0}})
        capture["parameters"] = load_capture(TRAY)["parameters"]
        table = table_of(capture, ["turn_deg"])
        step = steps_of(translate(capture, size_table=table).recipe, "draft")[0]
        self.assertIn(table.size_name("turn_deg"), step["angleDeg"]["expr"])

    def test_a_sized_angle_keeps_under_the_recipe_cap(self):
        capture = drafted(angle_deg=22.5, params={"angle_deg": {"name": "d9", "expression": "turn_deg / 4",
                                                                "value": 22.5}})
        capture["parameters"] = load_capture(TRAY)["parameters"]
        result = translate(capture, size_table=table_of(capture, ["turn_deg"]))
        self.assertLess(result.recipe["sizes"]["turn_deg"]["max"], 120.0)

    def test_a_sized_angle_whose_range_reaches_zero_has_its_range_cut_there(self):
        capture = drafted(params={"angle_deg": {"name": "d9", "expression": "turn_deg - 87", "value": 3.0}})
        capture["parameters"] = load_capture(TRAY)["parameters"]
        result = translate(capture, size_table=table_of(capture, ["turn_deg"]))
        self.assertIn("turn_deg", steps_of(result.recipe, "draft")[0]["angleDeg"]["expr"])
        self.assertEqual(result.recipe["sizes"]["turn_deg"]["min"], 87.01)

    def test_two_angles_from_different_formulas_stay_a_number(self):
        capture = drafted(two_angles=True, angle_two_deg=3.0, params={
            "angle_deg": {"name": "d9", "expression": "turn_deg / 30", "value": 3.0},
            "angle_two_deg": {"name": "d10", "expression": "3 deg", "value": 3.0}})
        capture["parameters"] = load_capture(TRAY)["parameters"]
        result = translate(capture, size_table=table_of(capture, ["turn_deg"]))
        self.assertEqual(steps_of(result.recipe, "draft")[0]["angleDeg"], 3.0)

    def test_each_draft_the_copy_cannot_check_is_left_out(self):
        cases = {
            "faces on both sides": drafted(plane={"point": [0, 0, 5], "normal": [0, 0, 1]}),
            "volume not measured": drafted(None),
            "volume unchanged": drafted(8000.0),
            "two different angles": drafted(two_angles=True, angle_two_deg=5.0),
            "past the recipe's cap": drafted(angle_deg=30.0),
        }
        for label, capture in cases.items():
            with self.subTest(label):
                self.assertEqual(left_out(translate(capture))["name"], "Draft1")


if __name__ == "__main__":
    unittest.main()
