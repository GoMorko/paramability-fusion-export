"""Captures of the owner's hybrid assembly (add-in 0.3.1, 0.3.2 for report (3), 0.3.3 to 0.4.3, 0.7.2 and 0.7.4 inside
the FilterBox packages) and of a bracket (0.7.2, 0.7.4). They stay outside the repo; the tests skip without them."""
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
        # The lid rails slide with the box wall; pieces of one sketch line keep their own place in the loop. The lid
        # sketch reads another outline in one row only after the row before it, so it blames no size there.
        rails = [v for k, v in motion.values.items() if k.split("/")[0] in ("65", "66", "67", "68") and "/l" in k]
        self.assertTrue(rails)
        self.assertEqual({(tuple(r.terms), abs(r.terms["FilterBox_depth_mm"])) for r in rails},
                         {(("FilterBox_depth_mm",), 0.5)})
        result = translate(capture, size_table=table, motion=motion)
        # The pipe offset of the lid moves only an outline that cannot follow it, so no formula reads it.
        self.assertEqual(result.fixed, [])
        free = sorted(n for n, size in result.recipe["sizes"].items() if "value" in size)
        self.assertEqual(free, sorted(n.replace("$", "_") for n in PROBE_TICKED[:5] + PROBE_TICKED[6:]))
        # Fusion did not rebuild with the depth halved, so its range starts at its value, and the pipe slope stops
        # before its taper reaches 45 degrees. The lid slot of Extrude5 may fail inside the other ranges: the sizes
        # it reads are marked, with the value past which it fails.
        depth = result.recipe["sizes"][PROBE_TICKED[2].replace("$", "_")]
        self.assertEqual((depth["min"], depth["max"]), (1.8, 3.6))
        self.assertEqual(result.recipe["sizes"][PROBE_TICKED[6]]["max"], 44.98)
        marked = {f["name"]: f["reason"] for f in result.loose}
        self.assertEqual(sorted(marked), sorted([PROBE_TICKED[0], PROBE_TICKED[3]]))
        self.assertIn("past 20.52", marked[PROBE_TICKED[3]])
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
        # A dialog range equal to the default is cut as the default is; the sizes the lid slot reads are marked.
        self.assertEqual(sorted(f["name"] for f in result.loose), sorted([PROBE_TICKED[0], PROBE_TICKED[3]]))
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
        # The ranges stop where Fusion did not rebuild; the lid slot of Extrude5 may stop meeting the part past these.
        marked = {f["name"]: f["reason"] for f in result.loose}
        self.assertEqual(sorted(marked), sorted([PROBE_TICKED[0], PROBE_TICKED[3], "_Filter__Wall_thickness_mm"]))
        for name, where in ((PROBE_TICKED[0], "past 1.8"), (PROBE_TICKED[3], "past 18"),
                            ("_Filter__Wall_thickness_mm", "below 0.98")):
            self.assertIn("may give unexpected results %s:" % where, marked[name])
        self.assertIn("Extrude5", marked[PROBE_TICKED[3]])
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

    def test_without_a_motion_the_sketch_sizes_are_marked_loose(self):
        capture = package_report(self, PACKAGE_WITH_OFFSET_FACES)["capture"]
        params = capture["parameters"]
        ticked = PROBE_TICKED + ["_Filter__Wall_thickness_mm"]
        table = size_table.build(params["user"], ticked, params["model"], capture.get("design_units", "mm"))
        result = translate(capture, size_table=table)
        self.assertEqual(result.fixed, [])
        free = {n: (s["min"], s["max"]) for n, s in result.recipe["sizes"].items() if "value" in s}
        self.assertEqual(len(free), 6)
        self.assertEqual(free["_Pipe__Slope_deg"], (0.0, 44.98))
        # The sketch sizes are loose, and the pipe offset that no step reads is not a size.
        self.assertEqual(sorted(f["name"] for f in result.loose), sorted(
            [PROBE_TICKED[0], PROBE_TICKED[2], PROBE_TICKED[3], "_Filter__Wall_thickness_mm"]))
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
        # The slot cut goes through the wall, so the rounds on its edges follow. Fusion did not rebuild with the
        # inner leg halved, so that range starts at its value instead of marking the size.
        self.assertEqual(result.loose, [])
        leg = result.recipe["sizes"]["InnerLegLength"]
        self.assertEqual((leg["min"], leg["max"]), (12.0, 24.0))
        # Some points follow the angle times a length through a cosine or a cotangent, checked by the states.
        self.assertTrue(any(isinstance(v, Terms) for v in motion.values.values()))

    def test_the_bracket_with_its_pattern_is_copied(self):
        report = package_report(self, PACKAGE_BRACKET_PATTERN)
        self.assertIsNotNone(translate(report["capture"]).recipe)


# Add-in 0.7.4 exports: the box again (its lid sketches stay on their other solution after a row that did not build),
# and a bracket with a slot whose ends are fully rounded and a symmetric pattern of a groove with its round and chamfer.
PACKAGE_074_BOX = "Pat - Pipe, Filter (Box, Cylinder) (8).paramability"
PACKAGE_074_BRACKET = "Untitled.paramability"


class OwnerCapture074Test(unittest.TestCase):
    def test_a_lid_sketch_left_on_its_other_solution_blames_no_size_and_the_ribs_follow_the_box(self):
        result, motion = replay(self, PACKAGE_074_BOX)
        self.assertEqual(len(motion.flipped), 2)
        self.assertFalse([f for f in result.loose if "different outline" in f["reason"]])
        free = [n for n, size in result.recipe["sizes"].items() if "value" in size]
        self.assertEqual(len(free), 9)
        rib = next(f for f in result.recipe["features"] if f["id"] == "extrude_53")
        self.assertIn("FilterBox___width__contains_CeramicMedium", rib["sketch"]["outer"]["center"][0]["expr"])
        self.assertEqual(check_recipe(result.recipe), [])

    def test_the_bracket_slot_ends_are_its_outline_and_the_groove_finishes_follow_the_count(self):
        result, motion = replay(self, PACKAGE_074_BRACKET)
        steps = {f["id"]: f for f in result.recipe["features"]}
        self.assertEqual(steps["extrude_4"]["sketch"]["outer"]["kind"], "slot")
        self.assertNotIn("round_5", steps)
        # One round and one chamfer per copy for every count the size allows, each kept while the count makes it.
        (count,) = {s["linear"]["count"]["expr"] for s in steps.values() if s["kind"] == "pattern"}
        copies = [s for s in steps.values() if s.get("when")]
        self.assertEqual(len(copies), 28)
        self.assertTrue(all(count in s["when"] for s in copies))
        self.assertFalse([f for f in result.loose if "different outline" in f["reason"]])
        self.assertEqual(len(result.dropped), 1)
        # The two half way rows of the angle had one read between them; the one that does not match its row is left
        # out, and a point follows the angle through the cotangent of its half.
        self.assertTrue(any(isinstance(v, Terms) and any(f[0] == "cot" for _, fs in v.parts for f in fs)
                            for v in motion.values.values()))
        self.assertEqual(check_recipe(result.recipe), [])


if __name__ == "__main__":
    unittest.main()
