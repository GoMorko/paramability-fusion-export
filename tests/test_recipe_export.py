import json
import os
import tempfile
import unittest
from types import SimpleNamespace

from tests import context  # noqa: F401
from tests.schema_check import check_recipe
from tests.translator_helpers import load_capture

from lib.export_plan import recipe_export
from lib.export_plan.messages import fixed_note, loose_note
from lib.export_plan.recipe_export import plan_single_export
from lib.params import size_table
from lib.package.manifest import validate_manifest


def coil_then_plate():
    """A coil that starts the body: nothing is copied before it, so the copy stops there."""
    capture = load_capture("extrude_plate")
    body = capture["items"][1]["bodies_after"]
    capture["items"][1]["index"] = 3
    capture["items"].insert(1, {"index": 2, "name": "Coil1", "type": "ThickenFeature", "suppressed": False,
                                "health": "ok", "message": "", "in_target_component": True, "bodies_after": body,
                                "data": {}})
    return capture


COVER = {"token": "cmp_cover", "name": "Cover"}


class FollowedComponentsTest(unittest.TestCase):
    def followed(self):
        from tests.test_translate_ref_motion import SIZES, motion_with, run
        return run(load_capture("component_ref_reach"), motion_with("component_ref_reach"), SIZES)

    def test_a_part_that_follows_a_component_outside_the_file_says_so(self):
        result = self.followed()
        manifest, _, _ = plan_single_export(load_capture("component_ref_reach"), "x.step", "Boss", "w", "z",
                                            translated=result)
        self.assertIn("This part follows the sizes of Cover. Export both together so they change together.",
                      manifest["notes"])

    def test_a_component_whose_body_is_in_the_file_is_not_named(self):
        result = self.followed()
        self.assertEqual(recipe_export.followed_outside([result]), ["Cover"])
        self.assertEqual(recipe_export.followed_outside([result], [{"component": COVER}]), [])
        self.assertEqual(recipe_export.followed_outside([result], [{"component": {"token": "", "name": "Cover"}}]), [])

    def test_a_part_that_follows_nothing_gets_no_such_note(self):
        manifest, _, _ = plan_single_export(load_capture("extrude_plate"), "x.step", "Plate", "w", "z")
        self.assertFalse(any("follows the sizes" in note for note in manifest["notes"]))


class PlanTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.step = os.path.join(self.tmp.name, "01.step")
        with open(self.step, "wb") as f:
            f.write(b"ISO-10303-21;")

    def plan(self, capture, up_axis="z"):
        return plan_single_export(capture, self.step, "Plate", "writer 1", up_axis)

    def test_a_count_a_pick_needs_keeps_its_range_and_is_marked_loose(self):
        from tests.test_translate_copies import counted
        capture, table = counted()
        manifest, files, report = plan_single_export(capture, self.step, "Plate", "w", "z", size_table=table)
        self.assertEqual(manifest["checks"], [])
        self.assertFalse([name for name in files if name.startswith("checks/")])
        self.assertEqual(json.loads(files["recipe.json"])["sizes"]["holes_count"]["min"], 1.0)
        self.assertEqual([f["name"] for f in manifest["loose"]], ["holes_count"])
        self.assertEqual(set(report["sizes"]), {"free", "fixed", "loose", "dropped"})
        self.assertNotIn("check_sizes", report)
        self.assertNotIn("keep_doubtful", report)

    def test_loose_sizes_reach_the_manifest_the_report_and_a_note(self):
        from tests.test_translate_copies import counted
        capture, table = counted()
        loose = [{"name": "wall_mm", "reason": "wall_mm may give unexpected results: it moves a joint."},
                 {"name": "gone", "reason": "gone may give unexpected results: x."}]
        manifest, _, report = plan_single_export(capture, self.step, "Plate", "w", "z", size_table=table,
                                                 loose=loose)
        # The export's own entry comes first, then the translator's (the count a pick needs); a name that is no size
        # of the recipe is left out.
        self.assertEqual([f["name"] for f in manifest["loose"]], ["wall_mm", "holes_count"])
        self.assertEqual(manifest["loose"][0], loose[0])
        self.assertEqual(report["sizes"]["loose"], manifest["loose"])
        self.assertTrue(any("wall_mm" in n and "holes_count" in n for n in manifest["notes"]))
        self.assertEqual(validate_manifest(manifest), [])

    def test_a_step_that_may_stop_meeting_the_part_marks_its_sizes_loose_and_keeps_the_ranges(self):
        from tests.test_translate_component import tray_with_lid_slot
        from tests.test_translate_sized import TICKED, table_of
        capture = tray_with_lid_slot()
        table = table_of(capture, TICKED)
        manifest, _, report = plan_single_export(capture, self.step, "Tray", "w", "z", size_table=table)
        loose = {f["name"]: f["reason"] for f in manifest["loose"]}
        self.assertIn("below 1.01", loose["wall_mm"])
        self.assertEqual(report["sizes"]["loose"], manifest["loose"])

    def test_with_steps_left_out_the_loose_and_fixed_size_notes_stay_within_the_note_cap(self):
        capture = load_capture("filter_tray_sized")
        capture["items"][2]["type"] = "ThickenFeature"
        params = capture["parameters"]
        table = size_table.build(params["user"], ["wall_mm", "pipe_d_mm", "holes_count"], params["model"], "mm",
                                 fixed={"pipe_d_mm": "it cannot follow"})
        loose = [{"name": "wall_mm", "reason": "wall_mm may give unexpected results: x."}]
        manifest, _, _ = plan_single_export(capture, self.step, "Tray", "w", "z", size_table=table, loose=loose)
        self.assertEqual(manifest["gaps"], "gaps.json")
        self.assertLessEqual(len(manifest["notes"]), recipe_export.MAX_NOTES)
        self.assertIn(loose_note(["wall_mm"]), manifest["notes"])
        self.assertIn(fixed_note(["pipe_d_mm"]), manifest["notes"])

        parts = [SimpleNamespace(is_recipe=True, gaps=[{}], given=SimpleNamespace(name="Lid")),
                 SimpleNamespace(is_recipe=False, gaps=[], given=SimpleNamespace(name="Base"))]
        notes = recipe_export._parts_notes(parts, ["a"], [{"name": "a"}], [{"name": "b"}], None)
        self.assertLessEqual(len(notes), recipe_export.MAX_NOTES)
        self.assertIn(loose_note(["a"]), notes)
        self.assertIn(fixed_note(["b"]), notes)

    def test_body_in_a_component_is_a_recipe_at_its_place(self):
        manifest, files, report = self.plan(load_capture("component_moved"))
        self.assertEqual(manifest["kind"], "recipe")
        self.assertEqual(manifest["notes"], ["5 steps copied from Fusion."])
        on = json.loads(files["recipe.json"])["features"][0]["sketch"]["on"]
        self.assertEqual(on["origin"], [100.0, 50.0, 0.0])
        self.assertEqual(report["capture"]["target"]["placement"]["path"], "Tray:1")

    def test_sketch_graphs_pass_the_capture_check_and_reach_report_json(self):
        capture = load_capture("component_moved")
        capture["sketch_graphs"] = [{"sketch": "Sketch1", "token": "t", "points": [], "curves": []}]
        manifest, files, report = self.plan(capture)
        self.assertEqual(manifest["kind"], "recipe")
        self.assertEqual(json.loads(files["report.json"])["capture"]["sketch_graphs"], capture["sketch_graphs"])

    def test_report_json_is_written_without_indentation(self):
        _, files, _ = self.plan(load_capture("component_moved"))
        self.assertNotIn(b"\n", files["report.json"])
        self.assertEqual(json.loads(files["report.json"])["capture"]["target"]["placement"]["path"], "Tray:1")

    def test_a_part_used_several_times_says_which_copy_the_file_holds(self):
        capture = load_capture("component_moved")
        capture["target"]["placement"]["uses"] = 3
        manifest, _, _ = self.plan(capture)
        self.assertIn("3 times", manifest["notes"][0])
        self.assertEqual(validate_manifest(manifest), [])

    def test_a_linked_part_or_unreadable_place_is_a_fixed_shape_with_its_own_note(self):
        capture = load_capture("component_moved")
        capture["target"]["placement"]["linked"] = True
        manifest, files, report = self.plan(capture)
        self.assertEqual(manifest["kind"], "stepOnly")
        self.assertTrue(manifest["notes"][0].startswith("This part comes from a linked design."))
        self.assertNotIn("recipe.json", files)
        capture = load_capture("component_moved")
        capture["target"]["placement"] = {"path": "Tray:1", "error": "no match", "uses": 1, "linked": False}
        manifest, _, report = self.plan(capture)
        self.assertEqual(manifest["notes"], ["Added as a fixed shape: the place of this part in the assembly could not be read."])
        self.assertEqual(report["outcome"], "stepOnly")

    def test_a_step_of_another_component_is_a_fixed_shape_naming_the_step(self):
        manifest, _, report = self.plan(load_capture("component_cross_cut"))
        self.assertEqual(manifest["kind"], "stepOnly")
        self.assertIn("Extrude5 (extrude) changes this part from another component", manifest["notes"][0])
        self.assertEqual(report["refusal"]["index"], 3)
        self.assertEqual(validate_manifest(manifest), [])

    def test_translated_part_is_a_recipe_package(self):
        manifest, files, report = self.plan(load_capture("extrude_plate"))
        self.assertEqual(manifest["kind"], "recipe")
        self.assertEqual(manifest["checks"], [])
        self.assertEqual(manifest["notes"], ["1 step copied from Fusion."])
        self.assertEqual(validate_manifest(manifest), [])
        self.assertEqual(sorted(files), ["part.step", "recipe.json", "report.json"])
        self.assertEqual(check_recipe(json.loads(files["recipe.json"])), [])
        self.assertEqual(report["outcome"], "recipe")
        self.assertEqual(json.loads(files["report.json"])["capture"]["design"], "Test")

    def test_unsupported_feature_gives_step_only_naming_it(self):
        manifest, files, report = self.plan(coil_then_plate())
        self.assertEqual(manifest["kind"], "stepOnly")
        self.assertNotIn("recipe", manifest)
        self.assertEqual(sorted(files), ["part.step", "report.json"])
        self.assertIn("coil", manifest["notes"][0].lower())
        self.assertEqual(validate_manifest(manifest), [])
        self.assertEqual(report["refusal"]["type"], "ThickenFeature")
        self.assertEqual(report["outcome"], "stepOnly")

    def test_a_stop_still_reports_the_later_steps_that_cannot_be_copied(self):
        capture = load_capture("filter_tray_sized")
        capture["items"][2]["health"] = "error"
        capture["items"][5]["type"] = "ThickenFeature"
        manifest, files, report = self.plan(capture)
        self.assertEqual((manifest["kind"], report["refusal"]["index"]), ("stepOnly", 2))
        self.assertIn(5, [step["index"] for step in report["after_stop"]["steps"]])
        self.assertIn("Hole1", manifest["notes"][1])
        self.assertEqual(validate_manifest(manifest), [])

    def test_a_capture_that_cannot_be_read_gives_a_fixed_shape(self):
        for name, capture in (("bad version", load_capture("core_bad_version")), ("reader error", RuntimeError("boom"))):
            with self.subTest(name):
                manifest, files, report = self.plan(capture)
                self.assertEqual(manifest["kind"], "stepOnly")
                self.assertEqual(manifest["notes"], ["Added as a fixed shape: the steps could not be read."])
                self.assertEqual(sorted(files), ["part.step", "report.json"])
                self.assertTrue(report["error"])

    def test_translator_crash_never_stops_the_export(self):
        original = recipe_export.translate
        recipe_export.translate = lambda capture, size_table=None, motion=None: 1 / 0
        try:
            manifest, _, report = self.plan(load_capture("extrude_plate"))
        finally:
            recipe_export.translate = original
        self.assertEqual(manifest["kind"], "stepOnly")
        self.assertEqual(manifest["notes"], ["Added as a fixed shape: the steps could not be copied."])
        self.assertIn("ZeroDivisionError", report["error"])

    def test_recipe_above_the_reader_cap_is_a_fixed_shape(self):
        original = recipe_export.MAX_RECIPE_BYTES
        recipe_export.MAX_RECIPE_BYTES = 10
        try:
            manifest, files, _ = self.plan(load_capture("extrude_plate"))
        finally:
            recipe_export.MAX_RECIPE_BYTES = original
        self.assertEqual(manifest["kind"], "stepOnly")
        self.assertIn("too large", manifest["notes"][0])
        self.assertNotIn("recipe.json", files)

    def test_dialog_up_axis_decides_the_turn(self):
        capture = load_capture("zup_plate_yup")
        capture["up_axis"] = "z"
        manifest, files, _ = self.plan(capture, up_axis="y")
        self.assertEqual(manifest["upAxis"], "y")
        on = json.loads(files["recipe.json"])["features"][0]["sketch"]["on"]
        self.assertEqual(on["origin"], [5.0, -3.0, 2.0])


class MotionHandoverTest(unittest.TestCase):
    """The translator gets the sketch motion, and the report keeps the probe record."""

    def setUp(self):
        self.seen = []
        real = recipe_export.translate

        def translate(capture, size_table=None, motion=None):
            self.seen.append(motion)
            return real(capture, size_table=size_table, motion=motion)

        self._real = real
        recipe_export.translate = translate
        self.addCleanup(setattr, recipe_export, "translate", real)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.step = os.path.join(self.tmp.name, "01.step")
        with open(self.step, "wb") as f:
            f.write(b"ISO-10303-21;")

    def test_motion_and_probe_record_reach_the_translator_and_the_report(self):
        marker = object()
        _, _, report = plan_single_export(load_capture("extrude_plate"), self.step, "Plate", "w", "z",
                                          motion=marker, probe={"restore_gap_mm": 0.0})
        self.assertEqual(self.seen, [marker])
        self.assertEqual(report["probe"], {"restore_gap_mm": 0.0})

    def test_a_translation_that_refused_is_used_as_given_and_nothing_translates_again(self):
        capture = coil_then_plate()
        refused = recipe_export.translate(capture)
        self.assertIsNone(refused.recipe)
        self.seen.clear()
        manifest, _, report = plan_single_export(capture, self.step, "Plate", "w", "z", translated=refused)
        self.assertEqual(self.seen, [])
        self.assertEqual(manifest["kind"], "stepOnly")
        self.assertEqual(report["refusal"], refused.refusal)


if __name__ == "__main__":
    unittest.main()
