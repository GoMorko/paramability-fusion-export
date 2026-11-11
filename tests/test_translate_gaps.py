"""Steps left out of the copy as gaps (lib/translator/gaps.py, walk.py)."""
import copy
import json
import unittest

from tests import context  # noqa: F401
from tests.schema_check import check_recipe
from tests.test_translate_sized import H, run
from tests.translator_helpers import load_capture, steps_of

from lib.translator import CaptureError, Refusal, translate
from lib.translator.gaps import MAX_DATA_BYTES, MAX_GAPS, pick_records

TRAY = "filter_tray_sized"  # Extrude1, Shell1, Fillet1 (picks edges), Hole1, a pattern of Hole1
SHELL, FILLET, HOLE, PATTERN = 2, 3, 5, 6


def tray(edit=None):
    capture = load_capture(TRAY)
    if edit:
        edit(capture)
    return capture


def unsupported(index, type_name="SweepFeature"):
    def edit(capture):
        capture["items"][index]["type"] = type_name
    return edit


def gap_names(result):
    return [gap["name"] for gap in result.gaps]


def place_of(gap):
    return gap["after"], gap["before"], gap["list"]


class LeftOutTest(unittest.TestCase):
    def test_a_step_type_without_a_handler_mid_timeline_is_left_out_and_the_rest_is_copied(self):
        result = translate(tray(unsupported(SHELL)))
        self.assertIsNone(result.refusal)
        self.assertEqual([s["id"] for s in result.recipe["features"]], ["extrude_1", "hole_5", "pattern_6"])
        shell = result.gaps[0]
        self.assertEqual((shell["id"], shell["name"]), ("gap_2", "Shell1"))
        self.assertEqual(place_of(shell), ("extrude_1", "hole_5", None))
        self.assertEqual(next(v for v in result.items if v["index"] == SHELL)["gap"], "gap_2")
        self.assertEqual(check_recipe(result.recipe), [])

    def test_a_handler_refusal_mid_timeline_is_left_out(self):
        result = translate(tray(lambda c: c["items"][SHELL]["data"].update(shell_type="rounded")))
        self.assertIsNone(result.refusal)
        self.assertEqual(gap_names(result)[0], "Shell1")

    def test_a_gap_before_the_first_written_step_stops_the_copy(self):
        result = translate(tray(unsupported(1, "LoftFeature")))
        self.assertIsNone(result.recipe)
        self.assertEqual((result.refusal["index"], result.gaps), (1, []))

    def test_more_gaps_than_the_cap_stop_the_copy(self):
        def edit(capture):
            shell = capture["items"][SHELL]
            capture["items"][SHELL:] = [dict(copy.deepcopy(shell), index=10 + n, name="Sweep%d" % n, type="SweepFeature")
                                        for n in range(MAX_GAPS + 1)]
        result = translate(tray(edit))
        self.assertIsNone(result.recipe)
        self.assertEqual(result.refusal["index"], 10 + MAX_GAPS)


class PicksTest(unittest.TestCase):
    def test_without_reach_a_later_picking_step_is_left_out_and_a_later_step_that_picks_nothing_is_copied(self):
        result = translate(tray(unsupported(SHELL)))
        self.assertEqual(gap_names(result), ["Shell1", "Fillet1"])
        self.assertEqual(result.gaps[1]["dependsOn"], ["gap_2"])
        self.assertEqual(len(steps_of(result.recipe, "hole")), 1)

    def test_with_reach_only_a_step_that_picks_faces_of_a_gap_is_left_out(self):
        for makers, expected in (([SHELL], ["Shell1", "Fillet1"]), ([], ["Shell1"])):
            with self.subTest(makers=makers):
                capture = tray(unsupported(SHELL))
                capture["reach"] = {"read": True, "makers": {str(FILLET): makers}}
                result = translate(capture)
                self.assertEqual(gap_names(result), expected)
                self.assertEqual(len(steps_of(result.recipe, "round")), 0 if makers else 1)

    def test_a_reach_read_that_failed_counts_as_no_reach(self):
        capture = tray(unsupported(SHELL))
        capture["reach"] = {"read": False, "error": "boom"}
        self.assertEqual(gap_names(translate(capture)), ["Shell1", "Fillet1"])

    def test_a_malformed_reach_is_refused(self):
        capture = tray()
        capture["reach"] = {"read": True, "makers": {"3": ["2"]}}
        with self.assertRaises(CaptureError):
            translate(capture)

    def test_a_pattern_of_a_gap_is_left_out_and_depends_on_it(self):
        result = translate(tray(unsupported(HOLE)))
        self.assertEqual(gap_names(result), ["Hole1", "RectangularPattern1"])
        self.assertEqual(result.gaps[1]["dependsOn"], ["gap_5"])

    def test_a_mirror_of_the_whole_body_after_a_gap_is_left_out(self):
        capture = load_capture("mirror_body")
        capture["items"][3]["type"] = "SweepFeature"
        result = translate(capture)
        self.assertEqual(gap_names(result), ["Extrude2", "Mirror1"])
        self.assertEqual(steps_of(result.recipe, "mirror"), [])

    def test_the_pick_records_of_an_item_name_each_picked_edge_face_and_point(self):
        item = {"data": {
            "sets": [{"edges": [{"token": "e1", "points": [[0, 0, 0]]}], "faces": [{"token": "f1", "point": [1, 0, 0]}]}],
            "profiles": [{"sketch": "Sketch1", "loops": []}, {"face": True, "token": "f2", "loops": []}],
            "side_one": {"kind": "toEntity", "face_point": [0, 0, 5]},
            "participants": [{"token": "t1"}], "faces_after": [{"point": [0, 0, 0]}],
        }}
        found = [(r["kind"], r["path"]) for r in pick_records(item)]
        self.assertEqual(found, [("edge", ["sets", 0, "edges", 0]), ("face", ["sets", 0, "faces", 0]),
                                 ("face", ["profiles", 1]), ("point", ["side_one"])])
        self.assertIs(pick_records(item)[0]["record"], item["data"]["sets"][0]["edges"][0])


class PlaceTest(unittest.TestCase):
    def test_a_gap_inside_a_tool_body_belongs_to_the_tool_step_written_for_it(self):
        capture = load_capture("combine_tool_two_steps")  # a tool of two adding steps, written onto the part
        capture["items"][5]["type"] = "SweepFeature"
        result = translate(capture)
        tool = steps_of(result.recipe, "toolBody")[0]
        self.assertEqual(place_of(result.gaps[0]), (tool["features"][0]["id"], None, tool["id"]))

    def test_a_tool_whose_first_step_is_a_gap_makes_the_combine_one_gap(self):
        capture = load_capture("combine_tool_filleted")
        capture["items"][3]["type"] = "SweepFeature"
        result = translate(capture)
        self.assertEqual(gap_names(result), ["Combine1"])
        self.assertEqual(steps_of(result.recipe, "toolBody"), [])

    def test_a_pattern_of_the_whole_body_after_a_gap_takes_the_gap_into_its_tool(self):
        capture = load_capture("pattern_target_finish")
        capture["items"][2]["type"] = "SweepFeature"
        result = translate(capture)
        tool = steps_of(result.recipe, "toolBody")[0]
        self.assertEqual(place_of(result.gaps[0]), ("extrude_1", None, tool["id"]))


class SizesTest(unittest.TestCase):
    def setUp(self):
        def edit(capture):
            unsupported(SHELL)(capture)
            capture["items"][SHELL]["data"]["params"]["inside"]["expression"] = "wall_mm + FilterBox_height_mm * 0"
        self.result, self.table = run(tray(edit))
        self.loose = {d["name"] for d in self.result.loose}

    def test_a_size_only_a_gap_reads_stays_a_size_marked_loose(self):
        self.assertIn("wall_mm", self.result.recipe["sizes"])
        self.assertIn("wall_mm", self.loose)
        self.assertNotIn("wall_mm", {d["name"] for d in self.result.dropped})
        self.assertEqual(self.result.gaps[0]["looseSizes"], ["wall_mm"])

    def test_a_size_a_written_step_reads_too_stays_free_and_is_named_by_the_gap(self):
        height = self.table.size_name(H)
        self.assertNotIn(H, self.loose)
        self.assertIn(height, self.result.gaps[0]["sizes"])
        self.assertNotIn(height, self.result.gaps[0]["looseSizes"])

    def test_the_doubt_of_a_refused_handler_fixes_no_size(self):
        def refuse(item, ctx):
            ctx.doubt(("wall_mm",), "it cannot be followed", fixed=True)
            return Refusal("Not today.")
        result = translate(tray(), handlers={"ShellFeature": refuse}, size_table=self.table)
        self.assertEqual(result.fixed, [])
        self.assertIn("wall_mm", result.recipe["sizes"])


class RecordTest(unittest.TestCase):
    def test_a_placed_y_up_part_gives_the_body_measures_and_the_map_in_recipe_coordinates(self):
        def edit(capture):
            unsupported(SHELL)(capture)
            capture["up_axis"] = "y"
            capture["target"]["placement"] = {"frame": {"origin": [100, 0, 0], "x": [1, 0, 0], "y": [0, 1, 0],
                                                        "z": [0, 0, 1]}}
            capture["items"][SHELL]["target_before"] = {"box": {"min": [0, 0, 0], "max": [80, 60, 32]},
                                                        "volume_mm3": 153600.0}
        gap = translate(tray(edit)).gaps[0]
        self.assertEqual(gap["bodyBefore"], {"box": {"min": [100, -32, 0], "max": [180, 0, 60]}, "volume": 153600.0})
        self.assertNotIn("bodyAfter", gap)

    def test_a_large_face_outline_is_trimmed_under_the_cap(self):
        def edit(capture):
            unsupported(SHELL)(capture)
            samples = [[n * 0.001, 0.0] for n in range(5000)]
            loop = {"outer": False, "curves": [{"kind": "spline", "samples": samples}]}
            capture["items"][SHELL]["data"]["profiles"] = [{"face": True, "token": "f9", "loops": [loop] * 20}]
        gap = translate(tray(edit)).gaps[0]
        self.assertTrue(gap["trimmed"])
        self.assertLessEqual(len(json.dumps(gap["data"]).encode("utf-8")), MAX_DATA_BYTES)
        self.assertEqual(gap["data"]["inside"], 2.0)


if __name__ == "__main__":
    unittest.main()
