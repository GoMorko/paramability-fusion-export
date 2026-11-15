"""Bodies inside components: placement, steps of other components, and parts that stay fixed shapes."""
import copy
import unittest

from tests import context  # noqa: F401
from tests.test_translate_sized import TICKED, run, table_of
from tests.test_translate_sketch_motion import run as run_with_motion
from tests.translator_helpers import left_out, stopped
from tests.translator_helpers import assert_schema_ok, load_capture, steps_of, translate_fixture

from lib.capture_model import gap_hints
from lib.sketch_values.motion import OPTIMISTIC, Affine, Motion, Stuck
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
    def refusal(self, name, missing):
        """Why the fixture's step is not copied: `stopped` when the copy stops, `left_out` when it goes on."""
        found = missing(translate_fixture(name))
        self.assertIsNotNone(found)
        return found

    def test_a_step_of_another_component_that_changes_the_part(self):
        refusal = self.refusal("component_cross_cut", stopped)
        self.assertEqual((refusal["index"], refusal["name"]), (3, "Extrude5"))
        self.assertIn("Extrude5 (extrude) changes this part from another component", step_only_note(refusal))

    def test_a_stop_caused_by_another_component_carries_a_tip(self):
        for name, cause in (("component_cross_cut", gap_hints.CHANGED_FROM_OTHER_COMPONENT),
                            ("component_made_elsewhere", gap_hints.MADE_IN_OTHER_COMPONENT)):
            with self.subTest(name):
                refusal = self.refusal(name, stopped)
                self.assertEqual(refusal["hint"], gap_hints.HINTS[cause])
                self.assertTrue(step_only_note(refusal).endswith("Tip: " + refusal["hint"]))

    def test_a_body_made_in_another_component(self):
        refusal = self.refusal("component_made_elsewhere", stopped)
        self.assertEqual(refusal["index"], 1)
        self.assertIn("made in another component and moved here later", step_only_note(refusal))

    def test_a_step_that_reaches_into_another_component(self):
        refusal = self.refusal("component_foreign_extent", left_out)
        self.assertEqual((refusal["index"], refusal["name"]), (3, "Extrude2"))
        self.assertIn("another component", refusal["reason"])

    def test_a_foreign_profile_refuses_too(self):
        capture = load_capture("component_foreign_extent")
        capture["items"][3]["data"]["side_one"] = {"kind": "distance", "distance": 8.0, "taper_deg": 0.0}
        capture["items"][3]["data"]["end_offset"] = 8.0
        copied = translate(copy.deepcopy(capture))
        self.assertIsNotNone(copied.recipe)
        self.assertIsNone(left_out(copied))
        capture["items"][3]["data"]["profiles"][0]["foreign"] = True
        self.assertIn("another component", left_out(translate(capture))["reason"])

    def test_a_participant_from_another_component_is_ignored(self):
        capture = load_capture("component_foreign_extent")
        capture["items"][3]["data"]["side_one"] = {"kind": "distance", "distance": 8.0, "taper_deg": 0.0}
        capture["items"][3]["data"]["end_offset"] = 8.0
        capture["items"][3]["data"]["participants"].append({"token": "tX", "name": "Lid", "foreign": True})
        self.assertIsNone(translate(capture).refusal)

    def test_a_linked_part_is_named(self):
        capture = load_capture("component_moved")
        capture["target"]["placement"]["linked"] = True
        self.assertIn("linked design", step_only_note(translate(capture).refusal))

    def test_a_place_that_could_not_be_read_or_is_not_a_rotation(self):
        capture = load_capture("component_moved")
        capture["target"]["placement"] = {"path": "Tray:1", "error": "no candidate matched"}
        self.assertIn("place of this part in the assembly could not be read", step_only_note(translate(capture).refusal))
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
        refusal = left_out(translate(capture))
        self.assertEqual(refusal["name"], "Combine1")
        self.assertIn("Lid is in another component", refusal["reason"])


def lid_rim(placement=None, sketch_params=()):
    """A join extrude on the tray from the sketch Rim of the component Lid: a 10 mm square, 4 mm up. The Lid sits at
    (110, 50, 32) turned a quarter about z, so in the tray's coordinates the square starts at (10, 0, 32)."""
    square = [[0, 0], [10, 0], [10, 10], [0, 10]]
    flat = {"origin": [0, 0, 0], "x": [1, 0, 0], "y": [0, 1, 0], "z": [0, 0, 1]}
    lid = {"origin": [110, 50, 32], "x": [0, 1, 0], "y": [-1, 0, 0], "z": [0, 0, 1]}
    in_tray = {"origin": [10, 0, 32], "x": [0, 1, 0], "y": [-1, 0, 0], "z": [0, 0, 1]}
    profile = {"sketch": "Rim", "frame": in_tray, "native_frame": flat, "space": "sketch", "foreign": True,
               "loops": [{"outer": True, "curves": [{"kind": "line", "start": square[n], "end": square[(n + 1) % 4]}
                                                     for n in range(4)]}],
               "component": {"token": "cLid", "name": "Lid"},
               "placement": placement or {"path": "Lid:1", "frame": lid, "source": "transform2", "checked_points": 3},
               "sketch_params": list(sketch_params)}
    return {"index": 9, "name": "Extrude9", "type": "ExtrudeFeature", "suppressed": False, "health": "ok",
            "message": "", "component": "cTray", "in_target_component": True, "target_changed": True,
            "bodies_after": [{"token": "t1", "name": "Body1"}],
            "data": {"operation": "join", "profiles": [profile], "start": {"kind": "profilePlane"},
                     "extent_type": "one", "side_one": {"kind": "distance", "distance": 4.0, "taper_deg": 0.0},
                     "side_two": None, "symmetric": None, "thin": False, "participants": [], "end_offset": 4.0}}


def tray_with_lid_slot():
    """The tray with a slot cut from the Lid's sketch Rim, 9 mm toward its side wall at x = 80: the slot ends 1 mm
    into that 2 mm wall."""
    capture = load_capture("component_moved")
    slot = lid_rim()
    slot["data"]["profiles"][0]["frame"] = {"origin": [70, 20, 10], "x": [0, 1, 0], "y": [0, 0, 1], "z": [1, 0, 0]}
    slot["data"].update(operation="cut", side_one={"kind": "distance", "distance": 9.0, "taper_deg": 0.0},
                        end_offset=9.0)
    capture["items"].append(slot)
    return capture


class BorrowedSketchTest(unittest.TestCase):
    def test_a_sketch_of_another_component_is_brought_in_through_the_assembly(self):
        capture = load_capture("component_moved")
        capture["items"].append(lid_rim())
        result = translate(capture)
        assert_schema_ok(self, result.recipe)
        rim = [s for s in result.recipe["features"] if s["label"] == "Extrude9"][0]
        self.assertEqual(rim["sketch"]["on"], {"origin": [110.0, 50.0, 32.0], "normal": [0.0, 0.0, 1.0],
                                               "xDir": [0.0, 1.0, 0.0]})
        self.assertEqual(verdicts(result)[9], ("translatedWithNote", "Extrude9 uses the sketch Rim of Lid; its "
                                               "outline is copied in place as fixed numbers."))

    def test_sizes_that_move_the_borrowed_sketch_are_marked(self):
        capture = load_capture("component_moved")
        capture["items"].append(lid_rim(sketch_params=[{"name": "d90", "expression": "wall_mm * 5", "reads": []}]))
        result, _ = run(capture)
        self.assertEqual(result.fixed, [])
        loose = {f["name"]: f["reason"] for f in result.loose}
        self.assertIn("sketch Rim of Lid", loose["wall_mm"])
        # The rim is copied as numbers and sits on the top of the tray, which moves with its height.
        self.assertIn("Extrude9 (drawn on Rim of Lid) would no longer meet the part",
                      loose["FilterBox_$_height__contains_CeramicMedium"])

    def test_a_borrowed_cut_that_ends_inside_a_wall_keeps_the_range_and_lists_the_values_it_doubts(self):
        capture = tray_with_lid_slot()
        table = table_of(capture, TICKED)
        result = translate(capture, size_table=table)
        self.assertEqual(result.fixed, [])
        self.assertEqual(result.recipe["sizes"]["wall_mm"]["min"], table.sizes["wall_mm"]["min"])
        reasons = {f["name"]: f["reason"] for f in result.loose}
        self.assertEqual(reasons["wall_mm"], "wall_mm may give unexpected results below 1.01: Extrude9 (drawn on Rim "
                         "of Lid) may no longer meet the part.")

    def borrowed_run(self, motion):
        capture = load_capture("component_moved")
        capture["items"].append(lid_rim(sketch_params=[{"name": "d90", "expression": "wall_mm * 5", "reads": []}]))
        result = run_with_motion(capture, ["wall_mm"], motion)
        assert_schema_ok(self, result.recipe)
        return result, [s for s in result.recipe["features"] if s["label"] == "Extrude9"][0]

    def test_a_borrowed_sketch_follows_the_sizes_the_probe_found(self):
        result, rim = self.borrowed_run(Motion({"9/p0/l0/width": Affine(8, {"wall_mm": 1.0}, "Rim")}))
        self.assertEqual(result.fixed, [])
        self.assertEqual(rim["sketch"]["outer"]["width"]["expr"], "wall_mm + 8")
        self.assertNotIn("fixed numbers", verdicts(result)[9][1])

    def test_a_borrowed_value_the_probe_could_not_follow_or_never_gave_marks_its_sizes(self):
        stuck = Motion({"9/p0/l0/width": Stuck(["wall_mm"], "unread", "Rim of Lid")})
        for label, motion in (("stuck", stuck), ("no value", Motion({}))):
            with self.subTest(label):
                result, _ = self.borrowed_run(motion)
                self.assertEqual((result.fixed, [f["name"] for f in result.loose]), ([], ["wall_mm"]))
        self.assertIn("Rim of Lid", self.borrowed_run(stuck)[0].loose[0]["reason"])

    def test_the_first_translation_fixes_nothing_for_a_borrowed_sketch(self):
        result, _ = self.borrowed_run(OPTIMISTIC)
        self.assertEqual(result.fixed, [])

    def test_a_borrowed_sketch_without_a_readable_place_refuses(self):
        capture = load_capture("component_moved")
        capture["items"].append(lid_rim(placement={"path": "Lid:1", "error": "No points of the sketch could be compared."}))
        self.assertIn("another component", left_out(translate(capture))["reason"])


class AssemblyStepsTest(unittest.TestCase):
    """Occurrences, joints and the like are not modeling steps."""

    def with_occurrence(self, **fields):
        capture = load_capture("component_moved")
        # As capture 3 of add-in 0.3.1 wrote it: no readable component, no readable bodies.
        occurrence = {"index": 99, "name": "Lid:1", "type": "Occurrence", "suppressed": False, "health": "ok",
                      "message": "", "component": "", "in_target_component": True, "bodies_after": None,
                      "read_error": "bodies: no attribute", "target_changed": None, "data": {}}
        occurrence.update(fields)
        capture["items"].insert(0, occurrence)
        return capture

    def test_an_occurrence_is_skipped(self):
        result = translate(self.with_occurrence())
        self.assertIsNotNone(result.recipe)
        self.assertEqual(verdicts(result)[99], ("skipped", ""))

    def test_an_occurrence_that_brings_the_body_in_refuses(self):
        refusal = translate(self.with_occurrence(target_changed=True)).refusal
        self.assertEqual(refusal["index"], 99)
        self.assertIn("made in another component and moved here later", step_only_note(refusal))


class CaptureShapeTest(unittest.TestCase):
    def test_a_placement_without_a_frame_or_a_list_of_bodies_without_bodies_is_not_a_capture(self):
        def half_frame(capture):
            capture["target"]["placement"]["frame"] = {"origin": [0, 0, 0]}

        def no_bodies(capture):
            capture["targets"] = []

        for label, edit in (("half a frame", half_frame), ("no bodies", no_bodies)):
            with self.subTest(label):
                capture = load_capture("component_moved")
                edit(capture)
                with self.assertRaises(CaptureError):
                    translate(capture)


if __name__ == "__main__":
    unittest.main()
