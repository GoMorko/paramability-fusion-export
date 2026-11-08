import json
import os
import tempfile
import unittest
import zipfile

from tests import context  # noqa: F401
from tests.schema_check import check_recipe
from tests.translator_helpers import load_capture

from lib.export_plan import recipe_export
from lib.export_plan.recipe_export import plan_single_export, recipe_saved_message
from lib.package.manifest import validate_manifest
from lib.package.writer import write_package
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

    def test_zip_holds_manifest_and_files(self):
        manifest, files, _ = self.plan(load_capture("extrude_plate"))
        out = os.path.join(self.tmp.name, "plate.paramability")
        write_package(out, manifest, files)
        with zipfile.ZipFile(out) as zf:
            self.assertEqual(zf.namelist(), ["manifest.json", "part.step", "recipe.json", "report.json"])
            self.assertEqual(json.loads(zf.read("manifest.json"))["recipe"], "recipe.json")
            self.assertEqual(zf.read("part.step"), b"ISO-10303-21;")

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
        recipe_export.translate = lambda capture: 1 / 0
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
