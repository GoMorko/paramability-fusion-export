"""Captures of the owner's hybrid assembly (add-in 0.3.1, 0.3.2 for report (3), and 0.3.3 inside the FilterBox
package). They stay outside the repo; the tests skip without them."""
import json
import os
import unittest
import zipfile

from tests import context  # noqa: F401
from tests.schema_check import check_recipe

from lib.export_plan.body_scope import other_sketch_names
from lib.export_plan.probe_flow import probe_view
from lib.params import size_table
from lib.probe import motion as probe_motion
from lib.translator import translate

REPORTS = os.path.expanduser("~/Documents/free-projects/3mf-compose/tmp/reports")
FILES = ("report.json", "report (1).json", "report (3).json")
PACKAGE = "Pat - Pipe, Filter (Box, Cylinder).paramability"
# The same part exported by add-in 0.4.0, whose reader measures the faces of the offset.
PACKAGE_WITH_OFFSET = "Pat - Pipe, Filter (Box, Cylinder) (2).paramability"
# Add-in 0.4.1 with the offset removed in Fusion, and the probe's states read at other size values.
PACKAGE_WITH_PROBE = "P123at - Pipe, Filter (Box, Cylinder).paramability"
PROBE_TICKED = ["FilterBox_$_width__contains_CeramicMedium", "FilterBox_$_height__contains_CeramicMedium",
                "FilterBox_$_depth__contains_CeramicMedium", "_CeramicMedium__Cube_width_unitless",
                "FilterBox__PipeTop_offsetFromCenter_mm", "FilterBox__PipeBottom_offsetFromCenter_mm",
                "_Pipe__Slope_deg"]


class OwnerCaptureTest(unittest.TestCase):
    def test_assembly_steps_are_skipped_and_the_walk_reaches_the_part(self):
        found = [os.path.join(REPORTS, f) for f in FILES if os.path.exists(os.path.join(REPORTS, f))]
        if not found:
            self.skipTest("the owner's captures are not on this machine")
        for path in found:
            with self.subTest(os.path.basename(path)), open(path, encoding="utf-8") as f:
                capture = json.load(f)["capture"]
                own = capture["target"]["component"]["token"]
                result = translate(capture)
                walked = {v["index"]: v["verdict"] for v in result.items}
                assembly = [i["index"] for i in capture["items"] if i["type"] in ("Occurrence", "ConstructionPlane")
                            and i["index"] in walked]
                self.assertTrue(assembly and all(walked[i] == "skipped" for i in assembly))
                refused = capture["items"][result.refusal["index"]]
                self.assertEqual(refused["component"], own)


    def test_the_filter_box_steps_up_to_the_offset_are_copied(self):
        path = os.path.join(REPORTS, PACKAGE)
        if not os.path.exists(path):
            self.skipTest("the owner's package is not on this machine")
        with zipfile.ZipFile(path) as package:
            capture = json.loads(package.read("report.json"))["capture"]
        result = translate(capture)
        walked = {v["name"]: v["verdict"] for v in result.items if v["verdict"] != "skipped"}
        self.assertEqual(walked["Chamfer1"], "translated")
        self.assertEqual(walked["Extrude9"], "translated")
        self.assertEqual(result.refusal["name"], "OffsetFaces3")

    def test_the_filter_box_offset_becomes_an_offset_faces_step(self):
        path = os.path.join(REPORTS, PACKAGE_WITH_OFFSET)
        if not os.path.exists(path):
            self.skipTest("the owner's package is not on this machine")
        with zipfile.ZipFile(path) as package:
            capture = json.loads(package.read("report.json"))["capture"]
        result = translate(capture)
        self.assertIsNone(result.refusal)
        verdicts = {v["index"]: v["verdict"] for v in result.items}
        self.assertEqual(verdicts[92], "translated")
        self.assertEqual(result.recipe["version"], 13)
        step = result.recipe["features"][-1]
        self.assertEqual((step["kind"], step["label"], step["distance"]), ("offsetFaces", "OffsetFaces3", -0.04))
        self.assertEqual(len(step["faces"]["near"]), 2)
        self.assertEqual(check_recipe(result.recipe), [])

    def test_the_probe_states_of_the_filter_box_leave_its_sizes_free(self):
        path = os.path.join(REPORTS, PACKAGE_WITH_PROBE)
        if not os.path.exists(path):
            self.skipTest("the owner's package is not on this machine")
        with zipfile.ZipFile(path) as package:
            report = json.loads(package.read("report.json"))
        capture = report["capture"]
        self.assertIn("PipeInsertBottom", other_sketch_names(capture))  # only the lid's steps use it
        params = capture["parameters"]
        table = size_table.build(params["user"], PROBE_TICKED, params["model"], capture.get("design_units", "mm"))
        motion = probe_motion.build(probe_view(capture), table, report["probe"]["states"])
        result = translate(capture, size_table=table, motion=motion)
        self.assertEqual([f["name"] for f in result.fixed], ["FilterBox__PipeBottom_offsetFromCenter_mm"])
        free = sorted(n for n, size in result.recipe["sizes"].items() if "value" in size)
        self.assertEqual(free, sorted(n.replace("$", "_") for n in PROBE_TICKED[:5] + PROBE_TICKED[6:]))
        self.assertEqual(sorted((r["name"], r["min"]) for r in result.raised),
                         sorted([(PROBE_TICKED[0], 1.01), (PROBE_TICKED[2], 1.01)]))
        self.assertEqual(check_recipe(result.recipe), [])


if __name__ == "__main__":
    unittest.main()
