"""Bodies inside components: placement, steps of other components, and parts that stay fixed shapes."""
import copy
import unittest

from tests import context  # noqa: F401
from tests.test_translate_sized import run
from tests.translator_helpers import assert_schema_ok, load_capture, steps_of, translate_fixture

from lib.translator import CaptureError, translate
from lib.translator.notes import step_only_note


def verdicts(result):
    return {v["index"]: (v["verdict"], v["note"]) for v in result.items}


class PlacementTest(unittest.TestCase):
    def test_the_recipe_lands_where_the_occurrence_sits(self):
        result = translate_fixture("component_moved")
        self.assertIsNone(result.refusal)
        assert_schema_ok(self, result.recipe)
        on = steps_of(result.recipe, "extrude")[0]["sketch"]["on"]
        self.assertEqual(on["origin"], [100.0, 50.0, 0.0])
        self.assertEqual(steps_of(result.recipe, "hole")[0]["origin"], [120.0, 80.0, 0.0])

    def test_steps_of_the_root_component_do_not_enter_the_recipe(self):
        result = translate_fixture("component_moved")
        self.assertEqual(verdicts(result)[8], ("skipped", "In another component."))
        self.assertEqual([s["label"] for s in result.recipe["features"]].count("Extrude1"), 1)

    def test_a_turned_nested_part_maps_every_position_and_direction(self):
        result = translate_fixture("component_nested_rotated")
        assert_schema_ok(self, result.recipe)
        by_kind = {s["kind"]: s for s in result.recipe["features"]}
        self.assertEqual(steps_of(result.recipe, "extrude")[0]["sketch"]["on"], {
            "origin": [100.0, 60.0, 0.0], "normal": [1.0, 0.0, 0.0], "xDir": [0.0, 1.0, 0.0]})
        self.assertEqual(by_kind["hole"]["origin"], [100.0, 80.0, 30.0])
        self.assertEqual(by_kind["hole"]["direction"], [1.0, 0.0, 0.0])
        pad = steps_of(result.recipe, "extrude")[1]["sketch"]["on"]
        self.assertEqual(pad["origin"], [95.0, 60.0, 0.0])

    def test_a_pick_that_follows_a_size_turns_into_a_formula_in_the_assembly(self):
        result, _ = run(load_capture("component_nested_rotated"))
        self.assertEqual(result.fixed, [])
        near = steps_of(result.recipe, "round")[0]["edges"]["near"][0]
        self.assertEqual(near, [{"expr": "0.5 * FilterBox_height_mm + 100"}, 60.0, 0.0])

    def test_a_y_up_design_gets_the_move_and_the_turn_in_one_pass(self):
        capture = load_capture("component_nested_rotated")
        capture["up_axis"] = "y"
        on = steps_of(translate(capture).recipe, "extrude")[0]["sketch"]["on"]
        self.assertEqual(on, {"origin": [100.0, 0.0, 60.0], "normal": [1.0, 0.0, 0.0], "xDir": [0.0, 0.0, 1.0]})

    def test_a_root_body_has_no_placement(self):
        capture = load_capture("extrude_plate")
        self.assertEqual(translate(capture).recipe, translate({**capture, "capture": 3}).recipe)


class RefusalTest(unittest.TestCase):
    def refusal(self, name):
        result = translate_fixture(name)
        self.assertIsNone(result.recipe)
        return result.refusal

    def test_a_step_of_another_component_that_changes_the_part(self):
        refusal = self.refusal("component_cross_cut")
        self.assertEqual((refusal["index"], refusal["name"]), (3, "Extrude5"))
        self.assertEqual(step_only_note(refusal), "Added as a fixed shape: Extrude5 (extrude) changes this part from "
                         "another component. Steps across components are not copied yet.")

    def test_a_body_made_in_another_component(self):
        refusal = self.refusal("component_made_elsewhere")
        self.assertEqual(refusal["index"], 1)
        self.assertEqual(step_only_note(refusal),
                         "Added as a fixed shape: this body was made in another component and moved here later.")

    def test_a_step_that_reaches_into_another_component(self):
        refusal = self.refusal("component_foreign_extent")
        self.assertEqual((refusal["index"], refusal["name"]), (3, "Extrude2"))
        self.assertEqual(step_only_note(refusal), "Added as a fixed shape: Extrude2 (extrude) reaches into another "
                         "component, which is not copied yet.")

    def test_a_foreign_profile_refuses_too(self):
        capture = load_capture("component_foreign_extent")
        capture["items"][3]["data"]["side_one"] = {"kind": "distance", "distance": 8.0, "taper_deg": 0.0}
        capture["items"][3]["data"]["end_offset"] = 8.0
        self.assertIsNone(translate(copy.deepcopy(capture)).refusal)
        capture["items"][3]["data"]["profiles"][0]["foreign"] = True
        self.assertIn("another component", translate(capture).refusal["reason"])

    def test_a_participant_from_another_component_is_ignored(self):
        capture = load_capture("component_foreign_extent")
        capture["items"][3]["data"]["side_one"] = {"kind": "distance", "distance": 8.0, "taper_deg": 0.0}
        capture["items"][3]["data"]["end_offset"] = 8.0
        capture["items"][3]["data"]["participants"].append({"token": "tX", "name": "Lid", "foreign": True})
        self.assertIsNone(translate(capture).refusal)

    def test_a_linked_part_is_named(self):
        capture = load_capture("component_moved")
        capture["target"]["placement"]["linked"] = True
        refusal = translate(capture).refusal
        self.assertEqual(step_only_note(refusal),
                         "This part comes from a linked design. Open that design in Fusion and export the part there.")

    def test_a_place_that_could_not_be_read_or_is_not_a_rotation(self):
        capture = load_capture("component_moved")
        capture["target"]["placement"] = {"path": "Tray:1", "error": "no candidate matched"}
        self.assertEqual(step_only_note(translate(capture).refusal),
                         "Added as a fixed shape: the place of this part in the assembly could not be read.")
        capture = load_capture("component_moved")
        capture["target"]["placement"]["frame"]["x"] = [2, 0, 0]
        self.assertIn("scaled", translate(capture).refusal["reason"])

    def test_a_foreign_tool_body_of_a_combine(self):
        capture = load_capture("component_moved")
        capture["items"].insert(7, {
            "index": 7, "name": "Combine1", "type": "CombineFeature", "suppressed": False, "health": "ok",
            "message": "", "component": "cTray", "in_target_component": True, "target_changed": True,
            "bodies_after": [{"token": "t1", "name": "Body1"}],
            "data": {"operation": "cut", "target": {"token": "t1", "name": "Body1"},
                     "tools": [{"token": "tL", "name": "Lid", "foreign": True}], "keep_tools": False}})
        refusal = translate(capture).refusal
        self.assertEqual(refusal["name"], "Combine1")
        self.assertIn("Lid is in another component", refusal["reason"])


class CaptureShapeTest(unittest.TestCase):
    def test_capture_3_needs_a_frame_of_numbers_or_a_reason(self):
        capture = load_capture("component_moved")
        capture["target"]["placement"]["frame"] = {"origin": [0, 0, 0]}
        with self.assertRaises(CaptureError):
            translate(capture)

    def test_targets_must_be_a_list_of_bodies(self):
        capture = load_capture("component_moved")
        capture["targets"] = []
        with self.assertRaises(CaptureError):
            translate(capture)


if __name__ == "__main__":
    unittest.main()
