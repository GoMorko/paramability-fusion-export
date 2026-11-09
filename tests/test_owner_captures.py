"""Captures of the owner's hybrid assembly (add-in 0.3.1, 0.3.2 for report (3), 0.3.3 to 0.4.3 inside the FilterBox
packages). They stay outside the repo; the tests skip without them."""
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
MISSING = "skipped: the owner's capture files are not in %s (the folder is missing or lacks them)" % REPORTS
FILES = ("report.json", "report (1).json", "report (3).json")
PACKAGE = "Pat - Pipe, Filter (Box, Cylinder).paramability"
# The same part exported by add-in 0.4.0, whose reader measures the faces of the offset.
PACKAGE_WITH_OFFSET = "Pat - Pipe, Filter (Box, Cylinder) (2).paramability"
# Add-in 0.4.1 with the offset removed in Fusion, and the probe's states read at other size values.
PACKAGE_WITH_PROBE = "P123at - Pipe, Filter (Box, Cylinder).paramability"
# Add-in 0.4.3 with the offset back in Fusion: Fusion lists another end face of the lid slot cut, and its lid sketch
# lands on another solution in some probe states.
PACKAGE_WITH_OFFSET_FACES = "Pat - Pipe, Filter (Box, Cylinder) (4).paramability"
PROBE_TICKED = ["FilterBox_$_width__contains_CeramicMedium", "FilterBox_$_height__contains_CeramicMedium",
                "FilterBox_$_depth__contains_CeramicMedium", "_CeramicMedium__Cube_width_unitless",
                "FilterBox__PipeTop_offsetFromCenter_mm", "FilterBox__PipeBottom_offsetFromCenter_mm",
                "_Pipe__Slope_deg"]


class OwnerCaptureTest(unittest.TestCase):
    def test_assembly_steps_are_skipped_and_the_walk_reaches_the_part(self):
        found = [os.path.join(REPORTS, f) for f in FILES if os.path.exists(os.path.join(REPORTS, f))]
        if not found:
            self.skipTest(MISSING)
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
            self.skipTest(MISSING)
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
            self.skipTest(MISSING)
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
            self.skipTest(MISSING)
        with zipfile.ZipFile(path) as package:
            report = json.loads(package.read("report.json"))
        capture = report["capture"]
        self.assertIn("PipeInsertBottom", other_sketch_names(capture))  # only the lid's steps use it
        params = capture["parameters"]
        table = size_table.build(params["user"], PROBE_TICKED, params["model"], capture.get("design_units", "mm"))
        motion = probe_motion.build(probe_view(capture), table, report["probe"]["states"])
        # The lid rails slide with the box wall; pieces of one sketch line keep their own place in the loop.
        rails = [v.rest for k, v in motion.values.items()
                 if k.split("/")[0] in ("65", "66", "67", "68") and "/l" in k and getattr(v, "rest", None)]
        self.assertTrue(rails)
        self.assertEqual({(tuple(r.terms), abs(r.terms["FilterBox_depth_mm"])) for r in rails},
                         {(("FilterBox_depth_mm",), 0.5)})
        result = translate(capture, size_table=table, motion=motion)
        self.assertEqual([f["name"] for f in result.fixed], ["FilterBox__PipeBottom_offsetFromCenter_mm"])
        free = sorted(n for n, size in result.recipe["sizes"].items() if "value" in size)
        self.assertEqual(free, sorted(n.replace("$", "_") for n in PROBE_TICKED[:5] + PROBE_TICKED[6:]))
        self.assertEqual(sorted((r["name"], r["min"]) for r in result.raised),
                         sorted([(PROBE_TICKED[0], 1.01), (PROBE_TICKED[2], 1.01)]))
        # Past these, the lid slot of Extrude5 no longer ends inside the closed end wall, and the pipe taper reaches 45.
        self.assertEqual(sorted((n["name"], n["max"]) for n in result.narrowed),
                         sorted([(PROBE_TICKED[0], 2.05), (PROBE_TICKED[3], 20.52), (PROBE_TICKED[6], 44.98)]))
        self.assertEqual(check_recipe(result.recipe), [])

    def test_with_the_dialog_ranges_the_filter_box_sizes_stay_free_and_its_counts_are_raised(self):
        path = os.path.join(REPORTS, PACKAGE_WITH_PROBE)
        if not os.path.exists(path):
            self.skipTest(MISSING)
        with zipfile.ZipFile(path) as package:
            report = json.loads(package.read("report.json"))
        capture = report["capture"]
        params = capture["parameters"]
        table = size_table.build(params["user"], PROBE_TICKED, params["model"], capture.get("design_units", "mm"))
        # The dialog sends the range of every ticked row, also when it is the default one.
        ranges = {n: (table.sizes[table.size_name(n)]["min"], table.sizes[table.size_name(n)]["max"])
                  for n in PROBE_TICKED}
        table = size_table.build(params["user"], PROBE_TICKED, params["model"], capture.get("design_units", "mm"),
                                 ranges=ranges)
        motion = probe_motion.build(probe_view(capture), table, report["probe"]["states"])
        result = translate(capture, size_table=table, motion=motion, loose=True)
        # The pipe offset of the lid moves only an outline that cannot follow it, so no formula reads it.
        self.assertEqual([f["name"] for f in result.fixed], ["FilterBox__PipeBottom_offsetFromCenter_mm"])
        # The box width and the cube keep the range Fusion builds; past these the lid slot may stop meeting the part.
        self.assertEqual([(f["name"], f["reason"].split(":")[0].split("results ")[1]) for f in result.loose],
                         [(PROBE_TICKED[0], "past 2.05"), (PROBE_TICKED[3], "past 20.52")])
        self.assertEqual(result.narrowed[0]["name"], PROBE_TICKED[6])
        self.assertEqual(sorted((r["name"], r["min"]) for r in result.raised),
                         sorted([(PROBE_TICKED[0], 1.01), (PROBE_TICKED[2], 1.01)]))
        self.assertEqual(len([n for n, size in result.recipe["sizes"].items() if "value" in size]), 6)

    def test_with_the_offset_back_the_filter_box_sizes_stay_free(self):
        path = os.path.join(REPORTS, PACKAGE_WITH_OFFSET_FACES)
        if not os.path.exists(path):
            self.skipTest(MISSING)
        with zipfile.ZipFile(path) as package:
            report = json.loads(package.read("report.json"))
        capture = report["capture"]
        params = capture["parameters"]
        ticked = PROBE_TICKED + ["_Filter__Wall_thickness_mm"]
        table = size_table.build(params["user"], ticked, params["model"], capture.get("design_units", "mm"))
        # The range ends as the tries in Fusion left them: the slope builds only below its value, the wall only
        # thinner, and the smallest counts and cube did not build.
        table = table.with_narrowed({
            "_Pipe__Slope_deg": (0.0, 0.5), "_Filter__Wall_thickness_mm": (0.625, 1.25),
            PROBE_TICKED[0]: (1.35, 3.6), PROBE_TICKED[2]: (1.35, 3.6), PROBE_TICKED[3]: (13.5, 36.0)})
        motion = probe_motion.build(probe_view(capture), table, report["probe"]["states"])
        # The lid sketch reads the same other outline after four rows of four different sizes.
        self.assertEqual(motion.apart, [6, 10, 12, 19])
        result = translate(capture, size_table=table, motion=motion, loose=True)
        self.assertEqual(result.fixed, [])
        # The ranges stay as Fusion builds them; the lid slot of Extrude5 may stop meeting the part past these.
        self.assertEqual([(f["name"], f["reason"].split(":")[0].split("results ")[1]) for f in result.loose],
                         [(PROBE_TICKED[0], "past 2.05"), (PROBE_TICKED[3], "past 20.52"),
                          ("_Filter__Wall_thickness_mm", "below 0.98")])
        self.assertTrue(all("Extrude5" in f["reason"] for f in result.loose))
        verdicts = {v["index"]: v for v in result.items}
        self.assertNotIn("two ways", verdicts[65]["note"])
        self.assertEqual(verdicts[92]["verdict"], "translated")
        free = {n: (s["min"], s["max"]) for n, s in result.recipe["sizes"].items() if "value" in s}
        self.assertEqual(free, {
            "FilterBox___width__contains_CeramicMedium": (1.35, 3.6),
            "FilterBox___height__contains_CeramicMedium": (0.6, 2.4),
            "FilterBox___depth__contains_CeramicMedium": (1.35, 3.6),
            "_CeramicMedium__Cube_width_unitless": (13.5, 36.0),
            "FilterBox__PipeTop_offsetFromCenter_mm": (0.025, 0.1),
            "_Pipe__Slope_deg": (0.0, 0.5),
            "_Filter__Wall_thickness_mm": (0.625, 1.25)})
        self.assertEqual(check_recipe(result.recipe), [])
        # "Keep doubtful sizes fixed" shortens them as before.
        strict = translate(capture, size_table=table, motion=motion)
        self.assertEqual({n["name"]: (n["min"], n["max"]) for n in strict.narrowed},
                         {PROBE_TICKED[0]: (1.35, 2.05), PROBE_TICKED[3]: (13.5, 20.52),
                          "_Filter__Wall_thickness_mm": (0.98, 1.25)})

    def test_the_rim_chamfer_picked_by_the_top_face_follows_the_box(self):
        path = os.path.join(REPORTS, PACKAGE_WITH_OFFSET_FACES)
        if not os.path.exists(path):
            self.skipTest(MISSING)
        with zipfile.ZipFile(path) as package:
            report = json.loads(package.read("report.json"))
        capture = report["capture"]
        # Chamfer2's first set was picked by the box's top face; this capture is older than the face record.
        rim = next(i for i in capture["items"] if i["index"] == 70)["data"]["sets"][0]
        self.assertEqual((rim["input_kinds"], len(rim["edges"])), (["face"], 36))
        rim["faces"] = [{"token": "top", "point": [0.0, 0.0, 21.6]}]
        params = capture["parameters"]
        ticked = PROBE_TICKED + ["_Filter__Wall_thickness_mm"]
        table = size_table.build(params["user"], ticked, params["model"], capture.get("design_units", "mm"))
        motion = probe_motion.build(probe_view(capture), table, report["probe"]["states"])
        result = translate(capture, size_table=table, motion=motion, loose=True, plain=True)
        bevels = [f for f in result.recipe["features"] if f["label"] == "Chamfer2"]
        # One step picks the whole rim, however many bumps the width makes; the other set keeps its points.
        self.assertEqual(bevels[0]["edges"], {"faceEdges": {"featureFace": "extrude_49", "which": "end"}})
        self.assertEqual([list(b["edges"]) for b in bevels[1:]], [["near"], ["near"]])
        self.assertEqual(result.recipe["version"], 14)
        self.assertEqual(check_recipe(result.recipe), [])

    def test_the_plain_export_keeps_every_range_and_marks_the_sketch_sizes_loose(self):
        path = os.path.join(REPORTS, PACKAGE_WITH_OFFSET_FACES)
        if not os.path.exists(path):
            self.skipTest(MISSING)
        with zipfile.ZipFile(path) as package:
            capture = json.loads(package.read("report.json"))["capture"]
        params = capture["parameters"]
        ticked = PROBE_TICKED + ["_Filter__Wall_thickness_mm"]
        table = size_table.build(params["user"], ticked, params["model"], capture.get("design_units", "mm"))
        result = translate(capture, size_table=table, loose=True, plain=True)
        self.assertEqual((result.fixed, result.raised, result.narrowed), ([], [], []))
        free = {n: (s["min"], s["max"]) for n, s in result.recipe["sizes"].items() if "value" in s}
        self.assertEqual(len(free), 6)
        self.assertEqual(free["_Pipe__Slope_deg"], (0.0, 45.5))
        # The sketch sizes are loose, and the pipe offset that no step reads is not a size.
        self.assertEqual(sorted(f["name"] for f in result.loose), sorted(
            [PROBE_TICKED[0], PROBE_TICKED[2], PROBE_TICKED[3], PROBE_TICKED[6], "_Filter__Wall_thickness_mm"]))
        self.assertNotIn("FilterBox__PipeTop_offsetFromCenter_mm", [f["name"] for f in result.loose])
        self.assertEqual(check_recipe(result.recipe), [])

    def test_the_plain_export_with_the_motion_of_the_stored_states(self):
        path = os.path.join(REPORTS, PACKAGE_WITH_OFFSET_FACES)
        if not os.path.exists(path):
            self.skipTest(MISSING)
        with zipfile.ZipFile(path) as package:
            report = json.loads(package.read("report.json"))
        capture = report["capture"]
        params = capture["parameters"]
        ticked = PROBE_TICKED + ["_Filter__Wall_thickness_mm"]
        table = size_table.build(params["user"], ticked, params["model"], capture.get("design_units", "mm"))
        motion = probe_motion.build(probe_view(capture), table, report["probe"]["states"])
        result = translate(capture, size_table=table, motion=motion, loose=True, plain=True)
        self.assertEqual((result.fixed, result.raised, result.narrowed), ([], [], []))
        free = sorted(n for n, size in result.recipe["sizes"].items() if "value" in size)
        self.assertEqual(len(free), 7)
        # With the motion only the sizes whose values still cannot follow are loose; the height and the pipe offset
        # follow.
        self.assertEqual(sorted(f["name"] for f in result.loose), sorted(
            [PROBE_TICKED[0], PROBE_TICKED[2], PROBE_TICKED[3], PROBE_TICKED[6], "_Filter__Wall_thickness_mm"]))
        self.assertEqual(check_recipe(result.recipe), [])


if __name__ == "__main__":
    unittest.main()
