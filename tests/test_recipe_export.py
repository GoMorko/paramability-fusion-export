import json
import os
import tempfile
import unittest

from tests import context  # noqa: F401
from tests.schema_check import check_recipe
from tests.translator_helpers import load_capture

from lib.export_plan import recipe_export
from lib.export_plan.messages import recipe_saved_message
from lib.export_plan.recipe_export import plan_single_export
from lib.package.manifest import validate_manifest
from lib.translator import CaptureError


def plate_then_emboss():
    capture = load_capture("extrude_plate")
    body = capture["items"][1]["bodies_after"]
    capture["items"].append({"index": 2, "name": "Emboss1", "type": "EmbossFeature", "suppressed": False,
                             "health": "ok", "message": "", "component_root": True, "bodies_after": body, "data": {}})
    return capture


class PlanTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.step = os.path.join(self.tmp.name, "01.step")
        with open(self.step, "wb") as f:
            f.write(b"ISO-10303-21;")

    def plan(self, capture, up_axis="z"):
        return plan_single_export(capture, self.step, "Plate", "writer 1", up_axis)

    def test_a_raised_smallest_value_is_in_the_recipe_and_the_report(self):
        from tests.test_translate_copies import counted
        capture, table = counted()
        _, files, report = plan_single_export(capture, self.step, "Plate", "w", "z", size_table=table)
        self.assertEqual([(r["name"], r["min"]) for r in report["sizes"]["raised"]], [("holes_count", 2)])
        self.assertEqual(json.loads(files["recipe.json"])["sizes"]["holes_count"]["min"], 2)

    def test_loose_sizes_reach_the_manifest_the_report_and_a_note(self):
        from tests.test_translate_copies import counted
        capture, table = counted()
        loose = [{"name": "wall_mm", "reason": "wall_mm may give unexpected results: it moves a joint."},
                 {"name": "gone", "reason": "gone may give unexpected results: x."}]
        manifest, _, report = plan_single_export(capture, self.step, "Plate", "w", "z", size_table=table,
                                                 loose=loose)
        self.assertEqual(manifest["loose"], loose[:1])
        self.assertEqual(report["sizes"]["loose"], loose[:1])
        self.assertIn("1 size may give unexpected results: wall_mm.", manifest["notes"])
        self.assertEqual(validate_manifest(manifest), [])
        self.assertFalse(report["keep_doubtful"])
        strict = plan_single_export(capture, self.step, "Plate", "w", "z", size_table=table, loose_sizes=False)[2]
        self.assertTrue(strict["keep_doubtful"])

    def test_a_plain_export_has_no_checks_keeps_the_ranges_and_records_both_choices(self):
        from tests.test_translate_copies import counted
        capture, table = counted()
        manifest, files, report = plan_single_export(capture, self.step, "Plate", "w", "z", size_table=table,
                                                     plain=True)
        self.assertEqual(manifest["checks"], [])
        self.assertEqual(json.loads(files["recipe.json"])["sizes"]["holes_count"]["min"], 1.0)
        self.assertEqual([f["name"] for f in manifest["loose"]], ["holes_count"])
        self.assertNotIn("raised", report["sizes"])
        self.assertFalse(any("not checked" in n for n in manifest["notes"]))
        self.assertEqual((report["check_sizes"], report["keep_doubtful"]), (False, False))
        self.assertTrue(plan_single_export(capture, self.step, "Plate", "w", "z", size_table=table)[2]["check_sizes"])

    def test_checks_are_planned_inside_the_limits_the_translation_found(self):
        from tests.test_translate_copies import counted
        from lib.export_plan.recipe_export import translate_capture, with_translated_limits
        capture, table = counted()
        planned = with_translated_limits(table, translate_capture(capture, "z", table))
        self.assertEqual(planned.sizes["holes_count"]["min"], 2)
        self.assertEqual(planned.typed_ends("holes_count"), (False, False))

    def test_a_check_below_a_raised_minimum_is_left_out(self):
        from tests.test_translate_copies import counted
        capture, table = counted()
        checks = [{"size": "holes_count", "value": 1.0, "step_file": self.step}]
        manifest, _, report = plan_single_export(capture, self.step, "Plate", "w", "z", size_table=table,
                                                 checks=checks)
        self.assertEqual((manifest["checks"], report["sizes"]["unchecked"]), ([], ["holes_count"]))

    def test_a_range_a_step_shortened_is_noted_and_shown_shortened(self):
        from tests.test_translate_component import tray_with_lid_slot
        from tests.test_translate_sized import TICKED, table_of
        from lib.export_plan.result_rows import result_view
        capture = tray_with_lid_slot()
        table = table_of(capture, TICKED)
        manifest, _, report = plan_single_export(capture, self.step, "Tray", "w", "z", size_table=table,
                                                 loose_sizes=False)
        wall = [n for n in report["sizes"]["narrowed"] if n["size"] == "wall_mm"]
        self.assertEqual([(n["side"], n["to"]) for n in wall], [("min", 1.01)])
        self.assertIn(wall[0]["note"], manifest["notes"])
        view = result_view("Tray.paramability", manifest, report, table, TICKED)
        rows = {r["name"]: r["range"] for r in view["rows"]}
        self.assertIn("1.01", rows["wall_mm"])

    def test_body_in_a_component_is_a_recipe_at_its_place(self):
        manifest, files, report = self.plan(load_capture("component_moved"))
        self.assertEqual(manifest["kind"], "recipe")
        self.assertEqual(manifest["notes"], ["5 steps copied from Fusion."])
        on = json.loads(files["recipe.json"])["features"][0]["sketch"]["on"]
        self.assertEqual(on["origin"], [100.0, 50.0, 0.0])
        self.assertEqual(report["capture"]["target"]["placement"]["path"], "Tray:1")

    def test_a_part_used_several_times_says_which_copy_the_file_holds(self):
        capture = load_capture("component_moved")
        capture["target"]["placement"]["uses"] = 3
        manifest, _, _ = self.plan(capture)
        self.assertEqual(manifest["notes"][0],
                         "5 steps copied from Fusion. Fusion uses this part 3 times; the file holds the one you picked.")
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
        manifest, files, report = self.plan(plate_then_emboss())
        self.assertEqual(manifest["kind"], "stepOnly")
        self.assertNotIn("recipe", manifest)
        self.assertEqual(sorted(files), ["part.step", "report.json"])
        self.assertIn("emboss", manifest["notes"][0].lower())
        self.assertEqual(validate_manifest(manifest), [])
        self.assertEqual(report["refusal"]["type"], "EmbossFeature")
        self.assertEqual(report["outcome"], "stepOnly")

    def test_capture_error_gives_reader_failure_note(self):
        bad = load_capture("core_bad_version")
        manifest, files, report = self.plan(bad)
        self.assertEqual(manifest["kind"], "stepOnly")
        self.assertEqual(manifest["notes"], ["Added as a fixed shape: the steps could not be read."])
        self.assertIn("CaptureError", report["error"])

    def test_reader_exception_gives_reader_failure_note(self):
        manifest, files, report = self.plan(RuntimeError("boom"))
        self.assertEqual(manifest["kind"], "stepOnly")
        self.assertEqual(manifest["notes"], ["Added as a fixed shape: the steps could not be read."])
        self.assertNotIn("capture", report)
        self.assertEqual(sorted(files), ["part.step", "report.json"])

    def test_translator_crash_never_stops_the_export(self):
        original = recipe_export.translate
        recipe_export.translate = lambda capture, size_table=None: 1 / 0
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

    def test_saved_message(self):
        recipe, _, _ = self.plan(load_capture("extrude_plate"))
        fixed, _, _ = self.plan(plate_then_emboss())
        self.assertEqual(recipe_saved_message(recipe, "a.paramability"), "Saved a.paramability. 1 step copied from Fusion.")
        self.assertTrue(recipe_saved_message(fixed, "a.paramability").startswith("Saved a.paramability.\n\nAdded as a fixed shape"))


if __name__ == "__main__":
    unittest.main()


class MotionHandoverTest(unittest.TestCase):
    """The translator gets the sketch motion only when it takes one, and the report keeps the probe record."""

    def setUp(self):
        self.seen = []
        real = recipe_export.translate

        def translate(capture, size_table=None, motion=None):
            self.seen.append(motion)
            return real(capture, size_table=size_table)

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

    def test_no_motion_and_no_probe_leave_the_report_as_before(self):
        _, _, report = plan_single_export(load_capture("extrude_plate"), self.step, "Plate", "w", "z")
        self.assertEqual(self.seen, [None])
        self.assertNotIn("probe", report)
