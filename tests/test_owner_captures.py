"""Captures of the owner's hybrid assembly (add-in 0.3.1, 0.3.2 for report (3), 0.3.3 to 0.4.3 and 0.7.2 inside the
FilterBox packages) and of a bracket (0.7.2). They stay outside the repo; the tests skip without them."""
import json
import os
import unittest
import zipfile

from tests import context  # noqa: F401
from tests.schema_check import check_recipe

from lib.export_plan.probe_flow import probe_view
from lib.params import size_table
from lib.probe import build as probe_build
from lib.sketch_values.motion import Terms
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


def package_report(test, name):
    """The report.json inside an owner's package, or a skipped test when the file is not here."""
    path = os.path.join(REPORTS, name)
    if not os.path.exists(path):
        test.skipTest(MISSING)
    with zipfile.ZipFile(path) as package:
        return json.loads(package.read("report.json"))


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
        capture = package_report(self, PACKAGE)["capture"]
        result = translate(capture)
        walked = {v["name"]: v["verdict"] for v in result.items if v["verdict"] != "skipped"}
        self.assertEqual(walked["Chamfer1"], "translated")
        self.assertEqual(walked["Extrude9"], "translated")
        self.assertEqual(result.refusal["name"], "OffsetFaces3")

    def test_the_filter_box_offset_becomes_an_offset_faces_step(self):
        capture = package_report(self, PACKAGE_WITH_OFFSET)["capture"]
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
        report = package_report(self, PACKAGE_WITH_PROBE)
        capture = report["capture"]
        params = capture["parameters"]
        table = size_table.build(params["user"], PROBE_TICKED, params["model"], capture.get("design_units", "mm"))
        motion = probe_build.build(probe_view(capture), table, report["probe"]["states"])
        # The lid rails slide with the box wall; pieces of one sketch line keep their own place in the loop.
        rails = [v.rest for k, v in motion.values.items()
                 if k.split("/")[0] in ("65", "66", "67", "68") and "/l" in k and getattr(v, "rest", None)]
        self.assertTrue(rails)
        self.assertEqual({(tuple(r.terms), abs(r.terms["FilterBox_depth_mm"])) for r in rails},
                         {(("FilterBox_depth_mm",), 0.5)})
        result = translate(capture, size_table=table, motion=motion)
        # The pipe offset of the lid moves only an outline that cannot follow it, so no formula reads it.
        self.assertEqual(result.fixed, [])
        free = sorted(n for n, size in result.recipe["sizes"].items() if "value" in size)
        self.assertEqual(free, sorted(n.replace("$", "_") for n in PROBE_TICKED[:5] + PROBE_TICKED[6:]))
        # The ranges stay as the table gives them. The counts that a pick on a pattern copy needs, the lid slot of
        # Extrude5 and the pipe taper may fail inside them: the sizes they read are marked, with the value past
        # which they fail where that is known.
        marked = {f["name"]: f["reason"] for f in result.loose}
        self.assertEqual(sorted(marked), sorted([PROBE_TICKED[0], PROBE_TICKED[2], PROBE_TICKED[3], PROBE_TICKED[6]]))
        self.assertIn("past 44.98", marked[PROBE_TICKED[6]])
        self.assertIn("past 23.4", marked[PROBE_TICKED[3]])
        self.assertEqual(check_recipe(result.recipe), [])

    def test_with_the_dialog_ranges_the_filter_box_sizes_stay_free_and_are_marked(self):
        report = package_report(self, PACKAGE_WITH_PROBE)
        capture = report["capture"]
        params = capture["parameters"]
        table = size_table.build(params["user"], PROBE_TICKED, params["model"], capture.get("design_units", "mm"))
        # The dialog sends the range of every ticked row, also when it is the default one.
        ranges = {n: (table.sizes[table.size_name(n)]["min"], table.sizes[table.size_name(n)]["max"])
                  for n in PROBE_TICKED}
        table = size_table.build(params["user"], PROBE_TICKED, params["model"], capture.get("design_units", "mm"),
                                 ranges=ranges)
        motion = probe_build.build(probe_view(capture), table, report["probe"]["states"])
        result = translate(capture, size_table=table, motion=motion)
        # The pipe offset of the lid moves only an outline that cannot follow it, so no formula reads it.
        self.assertEqual(result.fixed, [])
        # The ranges stay as the dialog sent them; the sizes that the pattern picks, the lid slot and the pipe taper
        # read are marked, with the value past which they fail where that is known.
        self.assertEqual(sorted(f["name"] for f in result.loose),
                         sorted([PROBE_TICKED[0], PROBE_TICKED[2], PROBE_TICKED[3], PROBE_TICKED[6]]))
        self.assertEqual(len([n for n, size in result.recipe["sizes"].items() if "value" in size]), 6)

    def test_with_the_offset_back_the_filter_box_sizes_stay_free_with_their_ranges(self):
        report = package_report(self, PACKAGE_WITH_OFFSET_FACES)
        capture = report["capture"]
        params = capture["parameters"]
        ticked = PROBE_TICKED + ["_Filter__Wall_thickness_mm"]
        table = size_table.build(params["user"], ticked, params["model"], capture.get("design_units", "mm"))
        motion = probe_build.build(probe_view(capture), table, report["probe"]["states"])
        # The lid sketch reads the same other outline after four rows of four different sizes.
        self.assertEqual(motion.apart, [6, 10, 12, 19])
        result = translate(capture, size_table=table, motion=motion)
        self.assertEqual(result.fixed, [])
        # The ranges stay as Fusion builds them; the lid slot of Extrude5 may stop meeting the part past these.
        marked = {f["name"]: f["reason"] for f in result.loose}
        self.assertEqual(sorted(marked), sorted([PROBE_TICKED[0], PROBE_TICKED[2], PROBE_TICKED[3], PROBE_TICKED[6],
                                                 "_Filter__Wall_thickness_mm"]))
        for name, where in ((PROBE_TICKED[0], "past 1.8"), (PROBE_TICKED[3], "past 18"),
                            ("_Filter__Wall_thickness_mm", "outside 0.98 to 1.25"), (PROBE_TICKED[6], "past 44.98")):
            self.assertIn("may give unexpected results %s:" % where, marked[name])
        self.assertIn("Extrude5", marked[PROBE_TICKED[3]])
        verdicts = {v["index"]: v for v in result.items}
        self.assertNotIn("two ways", verdicts[65]["note"])
        self.assertEqual(verdicts[92]["verdict"], "translated")
        free = {n: (s["min"], s["max"]) for n, s in result.recipe["sizes"].items() if "value" in s}
        self.assertEqual(free, {
            "FilterBox___width__contains_CeramicMedium": (0.9, 3.6),
            "FilterBox___height__contains_CeramicMedium": (0.6, 2.4),
            "FilterBox___depth__contains_CeramicMedium": (0.9, 3.6),
            "_CeramicMedium__Cube_width_unitless": (9.0, 36.0),
            "FilterBox__PipeTop_offsetFromCenter_mm": (0.025, 0.1),
            "_Pipe__Slope_deg": (0.0, 45.5),
            "_Filter__Wall_thickness_mm": (0.625, 2.5)})
        self.assertEqual(check_recipe(result.recipe), [])

    def test_the_rim_chamfer_picked_by_the_top_face_follows_the_box(self):
        report = package_report(self, PACKAGE_WITH_OFFSET_FACES)
        capture = report["capture"]
        # Chamfer2's first set was picked by the box's top face; this capture is older than the face record.
        rim = next(i for i in capture["items"] if i["index"] == 70)["data"]["sets"][0]
        self.assertEqual((rim["input_kinds"], len(rim["edges"])), (["face"], 36))
        rim["faces"] = [{"token": "top", "point": [0.0, 0.0, 21.6]}]
        params = capture["parameters"]
        ticked = PROBE_TICKED + ["_Filter__Wall_thickness_mm"]
        table = size_table.build(params["user"], ticked, params["model"], capture.get("design_units", "mm"))
        motion = probe_build.build(probe_view(capture), table, report["probe"]["states"])
        result = translate(capture, size_table=table, motion=motion)
        bevels = [f for f in result.recipe["features"] if f["label"] == "Chamfer2"]
        # One step picks the whole rim, however many bumps the width makes; the other set keeps its points.
        self.assertEqual(bevels[0]["edges"], {"faceEdges": {"featureFace": "extrude_49", "which": "end"}})
        self.assertEqual([list(b["edges"]) for b in bevels[1:]], [["near"], ["near"]])
        self.assertEqual(result.recipe["version"], 14)
        self.assertEqual(check_recipe(result.recipe), [])

    def test_without_a_motion_every_range_stays_and_the_sketch_sizes_are_marked_loose(self):
        capture = package_report(self, PACKAGE_WITH_OFFSET_FACES)["capture"]
        params = capture["parameters"]
        ticked = PROBE_TICKED + ["_Filter__Wall_thickness_mm"]
        table = size_table.build(params["user"], ticked, params["model"], capture.get("design_units", "mm"))
        result = translate(capture, size_table=table)
        self.assertEqual(result.fixed, [])
        free = {n: (s["min"], s["max"]) for n, s in result.recipe["sizes"].items() if "value" in s}
        self.assertEqual(len(free), 6)
        self.assertEqual(free["_Pipe__Slope_deg"], (0.0, 45.5))
        # The sketch sizes are loose, and the pipe offset that no step reads is not a size.
        self.assertEqual(sorted(f["name"] for f in result.loose), sorted(
            [PROBE_TICKED[0], PROBE_TICKED[2], PROBE_TICKED[3], PROBE_TICKED[6], "_Filter__Wall_thickness_mm"]))
        self.assertNotIn("FilterBox__PipeTop_offsetFromCenter_mm", [f["name"] for f in result.loose])
        self.assertEqual(check_recipe(result.recipe), [])



# Add-in 0.7.2 exports: the box with the pipe hole (many rows do not build at the range ends, and a sketch lands on
# another solution), and a plain bracket whose angle size moves its points along a curve.
PACKAGE_072 = "Pat - Pipe, Filter (Box, Cylinder) (7).paramability"
PACKAGE_BRACKET = "simplfiideUntitled.paramability"
PACKAGE_BRACKET_PATTERN = "withpatternUntitled.paramability"


def replay(test, name):
    """The translation of a package from its own probe states, with the sizes its rows varied as the ticked ones."""
    from lib.export_plan.body_scope import body_links, scope_inputs
    report = package_report(test, name)
    capture, states = report["capture"], report["probe"]["states"]
    varied = {n for s in states for n in s.get("values") or {}}
    ticked = [p["name"] for p in capture["parameters"]["user"] if p["name"] in varied]
    model, quantities = scope_inputs(capture, capture["parameters"]["model"])
    table = size_table.build(capture["parameters"]["user"], ticked, model, capture.get("design_units", "mm"),
                             quantity_params=quantities, links=body_links(capture))
    motion = probe_build.build(probe_view(capture), table, states)
    return translate(capture, size_table=table, motion=motion), motion


class OwnerCapture072Test(unittest.TestCase):
    def test_the_box_sizes_follow_and_a_size_no_row_built_is_not_called_unchanging(self):
        result, motion = replay(self, PACKAGE_072)
        free = [n for n, size in result.recipe["sizes"].items() if "value" in size]
        self.assertEqual(len(free), 7)
        never = {n for n, span in motion.spans.items() if span["low"] == span["high"]}
        self.assertTrue(never)
        for entry in result.dropped:
            if entry["name"] in never:
                self.assertTrue(entry["used"])
                self.assertNotIn("tried", entry)

    def test_the_bracket_keeps_every_size_but_the_angle_that_curves_its_points(self):
        result, motion = replay(self, PACKAGE_BRACKET)
        free = [n for n, size in result.recipe["sizes"].items() if "value" in size]
        self.assertEqual((len(free), len(result.dropped)), (7, 1))
        curved = {n for v in motion.values.values() if getattr(v, "cause", "") == "curve" for n in v.movers}
        self.assertEqual(curved, {result.dropped[0]["name"]})
        # The slot cut goes through the wall, so the rounds on its edges follow; the one loose size was measured over
        # part of its range only.
        self.assertEqual(len(result.loose), 1)
        self.assertNotIn("picks", result.loose[0]["reason"])
        # Some points follow the angle times a length through a cosine or a cotangent, checked by the states.
        self.assertTrue(any(isinstance(v, Terms) for v in motion.values.values()))

    def test_the_bracket_with_its_pattern_is_copied(self):
        report = package_report(self, PACKAGE_BRACKET_PATTERN)
        self.assertIsNotNone(translate(report["capture"]).recipe)


if __name__ == "__main__":
    unittest.main()
