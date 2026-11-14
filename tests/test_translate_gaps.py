"""Steps left out of the copy as gaps (lib/translator/gaps/stops.py, walk.py)."""
import copy
import json
import math
import unittest
from unittest import mock

from tests import context  # noqa: F401
from tests.schema_check import check_recipe
from tests.test_translate_sized import H, run
from tests.translator_helpers import load_capture, steps_of, stopped, verdict_of

from lib.capture_model.gap_picks import pick_records
from lib.translator import CaptureError, Refusal, translate
from lib.translator.gaps import stops as gaps_module
from lib.translator.gaps.finishing import is_finishing
from lib.translator.gaps.gap_file import MAX_DATA_BYTES, MAX_DATA_DEPTH
from lib.translator.gaps.stops import MAX_GAPS

TRAY = "filter_tray_sized"  # Extrude1, Shell1, Fillet1 (picks edges), Hole1, a pattern of Hole1
SHELL, FILLET, HOLE, PATTERN = 2, 3, 5, 6


def tray(edit=None):
    capture = load_capture(TRAY)
    if edit:
        edit(capture)
    return capture


def unsupported(index, type_name="CoilFeature"):
    def edit(capture):
        capture["items"][index]["type"] = type_name
    return edit


def gap_names(result):
    return [gap["name"] for gap in result.gaps]


def place_of(gap):
    return gap["after"], gap["before"], gap["list"]


class FinishingFlagTest(unittest.TestCase):
    def test_a_gap_is_flagged_by_its_step_type_a_fillet_that_picks_a_gap_is_finishing_the_coil_is_not(self):
        result = translate(tray(unsupported(SHELL)))
        self.assertEqual({gap["name"]: gap["finishing"] for gap in result.gaps}, {"Shell1": False, "Fillet1": True})

    def test_a_round_and_a_thread_that_is_not_modeled_are_finishing_other_steps_are_not(self):
        cases = [
            ("FilletFeature", {}, True), ("ThreadFeature", {"modeled": False}, True),
            ("ThreadFeature", {"modeled": True}, False), ("ThreadFeature", None, False),
            ("ExtrudeFeature", {}, False), ("NotAStepType", {"modeled": False}, False),
        ]
        for step_type, data, expected in cases:
            with self.subTest(type=step_type, data=data):
                self.assertIs(is_finishing(step_type, data), expected)


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


def _at_shell(**changes):
    def edit(capture):
        capture["items"][SHELL].update(changes)
    return edit


def _shell_with_new_body(type_name=None, **data):
    def edit(capture):
        shell = capture["items"][SHELL]
        shell["bodies_after"] = shell["bodies_after"] + [{"token": "t9", "name": "Body9"}]
        shell["type"] = type_name or shell["type"]
        shell["data"].update(data)
    return edit


def _more_gaps_than_the_cap(capture):
    shell = capture["items"][SHELL]
    capture["items"][SHELL:] = [dict(copy.deepcopy(shell), index=10 + n, name="Coil%d" % n, type="CoilFeature")
                                for n in range(MAX_GAPS + 1)]


class StopTest(unittest.TestCase):
    def test_each_case_that_leaves_the_body_unknown_stops_the_copy_instead_of_leaving_a_gap(self):
        cases = {
            "Fusion marks the step as an error": (_at_shell(health="error"), SHELL),
            "its bodies could not be read": (_at_shell(bodies_after=None), SHELL),
            "its data could not be read": (_at_shell(data={"read_error": "boom"}), SHELL),
            "a type without a handler whose data could not be read":
                (_at_shell(type="CoilFeature", data={"read_error": "boom"}), SHELL),
            "the body cannot be followed": (_at_shell(bodies_after=[{"token": "t9", "name": "Body1"}]), SHELL),
            "a type without a handler makes another body": (_shell_with_new_body("CoilFeature"), SHELL),
            "a step that reaches into another component makes another body":
                (_shell_with_new_body(inside={"foreign": True}), SHELL),
            "a step its handler refuses makes another body": (_shell_with_new_body(shell_type="rounded"), SHELL),
            "the first step is a gap": (unsupported(1, "CoilFeature"), 1),
            "more gaps than the cap": (_more_gaps_than_the_cap, 10 + MAX_GAPS),
        }
        for label, (edit, index) in cases.items():
            with self.subTest(label):
                result = translate(tray(edit))
                self.assertIsNotNone(stopped(result))
                self.assertEqual((stopped(result)["index"], result.gaps), (index, []))

    def test_a_part_with_more_gaps_than_an_old_gaps_file_held_keeps_its_recipe_and_every_gap(self):
        def edit(capture):
            shell = capture["items"][SHELL]
            capture["items"][SHELL:] = [dict(copy.deepcopy(shell), index=10 + n, name="Coil%d" % n, type="CoilFeature")
                                        for n in range(20)]
        result = translate(tray(edit))
        self.assertIsNone(stopped(result))
        self.assertIsNotNone(result.recipe)
        self.assertEqual(len(result.gaps), 20)

    def test_a_step_that_makes_another_body_and_leaves_the_part_as_it_was_is_passed_by(self):
        def edit(capture):
            _shell_with_new_body("OffsetFeature")(capture)
            capture["items"][SHELL]["target_changed"] = False
        result = translate(tray(edit))
        self.assertIsNone(stopped(result))
        self.assertEqual(verdict_of(result, SHELL)["verdict"], "skipped")

    def test_a_tool_body_that_passes_the_gap_cap_stops_the_whole_copy(self):
        # Two left out steps after the tool's first one: the second meets the cap inside the tool walk.
        capture = load_capture("combine_tool_two_steps")
        items = capture["items"]
        items[5]["type"] = "CoilFeature"
        items[6:] = [dict(copy.deepcopy(items[5]), index=6, name="Extrude4"), dict(items[6], index=7)]
        with mock.patch.object(gaps_module, "MAX_GAPS", 1):
            result = translate(capture)
        self.assertIsNotNone(stopped(result))
        self.assertEqual(result.gaps, [])


class AfterStopTest(unittest.TestCase):
    def test_a_copy_that_stops_still_names_every_step_after_it_that_cannot_be_copied(self):
        def edit(capture):
            capture["items"][SHELL].update(health="error")
            unsupported(HOLE)(capture)
        result = translate(tray(edit))
        self.assertEqual((stopped(result)["index"], result.recipe), (SHELL, None))
        after = result.after_stop
        self.assertEqual([s["index"] for s in after["steps"]], [SHELL, FILLET, HOLE, PATTERN])
        self.assertEqual([v["index"] for v in after["items"]], [FILLET, FILLET + 1, HOLE, PATTERN])


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
                capture["reach"] = {"read": True, "gaps": [SHELL], "makers": {str(FILLET): makers}}
                result = translate(capture)
                self.assertEqual(gap_names(result), expected)
                self.assertEqual(len(steps_of(result.recipe, "round")), 0 if makers else 1)

    def test_a_gap_the_reach_was_not_read_for_or_a_reach_that_failed_may_be_picked(self):
        for reach in ({"read": True, "gaps": [], "makers": {str(FILLET): []}},
                      {"read": True, "makers": {str(FILLET): []}},
                      {"read": False, "error": "boom"}):
            with self.subTest(reach=reach):
                capture = tray(unsupported(SHELL))
                capture["reach"] = reach
                result = translate(capture)
                self.assertEqual(gap_names(result), ["Shell1", "Fillet1"])
                self.assertEqual(result.gaps[1]["dependsOn"], ["gap_2"])

    def test_a_malformed_reach_is_refused(self):
        capture = tray()
        capture["reach"] = {"read": True, "makers": {"3": ["2"]}}
        with self.assertRaises(CaptureError):
            translate(capture)

    def test_a_pattern_of_a_gap_is_left_out_and_depends_on_it(self):
        result = translate(tray(unsupported(HOLE)))
        self.assertEqual(gap_names(result), ["Hole1", "RectangularPattern1"])
        self.assertEqual(result.gaps[1]["dependsOn"], ["gap_5"])

    def test_a_mirror_of_the_whole_body_after_a_gap_mirrors_the_gathered_body_with_the_gap_inside(self):
        capture = load_capture("mirror_body")
        capture["items"][3]["type"] = "CoilFeature"
        result = translate(capture)
        gathered = result.recipe["features"][0]
        self.assertEqual(gap_names(result), ["Extrude2"])
        self.assertEqual(result.gaps[0]["list"], gathered["id"])
        self.assertEqual(steps_of(result.recipe, "mirror")[0]["of"], [gathered["id"]])

    def test_the_pick_records_of_an_item_are_the_edges_and_faces_it_picks_by_measured_points(self):
        item = {"data": {
            "sets": [{"edges": [{"token": "e1", "points": [[0, 0, 0]]}], "faces": [{"token": "f1", "point": [1, 0, 0]}]}],
            "profiles": [{"sketch": "Sketch1", "loops": []}, {"face": True, "face_point": [0, 0, 5], "loops": []}],
            "side_one": {"kind": "toEntity", "face_point": [0, 0, 5]},
            "faces": [{"surface": "Plane", "face_point": [0, 0, 5]}],
            "participants": [{"token": "t1"}], "faces_after": [{"point": [0, 0, 0]}],
        }}
        found = [(r["kind"], r["path"]) for r in pick_records(item)]
        self.assertEqual(found, [("edge", ["sets", 0, "edges", 0]), ("face", ["sets", 0, "faces", 0])])
        self.assertIs(pick_records(item)[0]["record"], item["data"]["sets"][0]["edges"][0])


class PlaceTest(unittest.TestCase):
    def test_a_gap_inside_a_tool_body_belongs_to_the_tool_step_written_for_it(self):
        capture = load_capture("combine_tool_two_steps")  # a tool of two adding steps, written onto the part
        capture["items"][5]["type"] = "CoilFeature"
        result = translate(capture)
        tool = steps_of(result.recipe, "toolBody")[0]
        self.assertEqual(place_of(result.gaps[0]), (tool["features"][0]["id"], None, tool["id"]))

    def test_a_tool_whose_first_step_is_a_gap_makes_the_combine_one_gap(self):
        capture = load_capture("combine_tool_filleted")
        capture["items"][3]["type"] = "CoilFeature"
        result = translate(capture)
        self.assertEqual(gap_names(result), ["Combine1"])
        self.assertEqual(steps_of(result.recipe, "toolBody"), [])

    def test_a_pattern_of_the_whole_body_after_a_gap_takes_the_gap_into_its_tool(self):
        capture = load_capture("pattern_target_finish")
        capture["items"][2]["type"] = "CoilFeature"
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

    def test_data_the_app_would_refuse_is_made_plain_json_and_marked_trimmed(self):
        def deepest(node, level=1):
            children = node.values() if isinstance(node, dict) else node if isinstance(node, list) else ()
            return max([level] + [deepest(child, level + 1) for child in children])

        def edit(capture):
            unsupported(SHELL)(capture)
            nested = 1.0
            for _ in range(MAX_DATA_DEPTH + 8):
                nested = {"in": nested}
            capture["items"][SHELL]["data"].update(outside=math.nan, nested=nested)
        gap = translate(tray(edit)).gaps[0]
        json.dumps(gap["data"], allow_nan=False)
        self.assertLessEqual(deepest(gap["data"]), MAX_DATA_DEPTH)
        self.assertEqual((gap["data"]["outside"], gap["data"]["inside"], gap["trimmed"]), (None, 2.0, True))


if __name__ == "__main__":
    unittest.main()
