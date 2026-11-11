"""Translator walk rules outside the plain case: steps of other bodies, steps that leave the body alone, steps Fusion
warns about, and the copy limits."""
import copy
import unittest

from tests import context  # noqa: F401
from tests.translator_helpers import load_capture

from lib.params import size_table
from lib.translator import translate

TRAY = "filter_tray_sized"
BODY = {"token": "t1", "name": "Body1"}
LID = {"token": "t2", "name": "Lid"}


def _item(index, name, kind, bodies, data=None, **more):
    item = {"index": index, "name": name, "type": kind, "suppressed": False, "health": "ok", "message": "",
            "in_target_component": True, "bodies_after": bodies, "data": data or {}}
    item.update(more)
    return item


def tray_with_lid(combine=False):
    """The filter tray plus a lid body made from the same sketch. Its length is `wall_mm * 5` in Fusion, which gives
    10 mm while the lid measures 12 mm, so the copy cannot follow `wall_mm` there."""
    capture = load_capture(TRAY)
    params = capture["parameters"]
    params["model"].append({"name": "d10", "expression": "wall_mm * 5", "value": 1.2, "unit": "mm", "kind": "length",
                            "value_type": "numeric", "dependency_parameters": ["wall_mm"], "role": "Distance",
                            "created_by": {"kind": "feature", "token": "tok_d10", "name": ""}})
    lid = copy.deepcopy(capture["items"][1]["data"])
    lid["side_one"]["distance"] = lid["end_offset"] = 12.0
    lid["params"] = {"side_one.distance": {"name": "d10", "expression": "wall_mm * 5", "value": 12.0}}
    capture["items"].append(_item(7, "LidExtrude", "ExtrudeFeature", [LID], lid))
    if combine:
        capture["items"].append(_item(8, "Combine1", "CombineFeature", [BODY, LID], {
            "operation": "join", "target": BODY, "tools": [LID], "keep_tools": False}))
    return capture


def translated(capture):
    params = capture["parameters"]
    table = size_table.build(params["user"], [p["name"] for p in params["user"]], params["model"],
                             capture.get("design_units", "mm"))
    return translate(capture, size_table=table)


class OtherBodyTest(unittest.TestCase):
    def test_a_lid_that_is_never_combined_does_not_mark_the_sizes_of_the_box(self):
        result = translated(tray_with_lid())
        self.assertEqual((result.fixed, result.loose), ([], []))
        self.assertIn("wall_mm", result.recipe["sizes"])

    def test_a_lid_that_is_combined_into_the_box_marks_the_size_it_cannot_follow(self):
        result = translated(tray_with_lid(combine=True))
        self.assertEqual([f["name"] for f in result.loose], ["wall_mm"])
        self.assertIn("LidExtrude", result.loose[0]["reason"])


def two_step_tool(combine=True, tool_step_reads="peg_len_mm"):
    """The plate cut by a tool of two joined cylinders. `peg_len_mm` is read by the second tool step alone."""
    capture = load_capture("combine_cut_tool_two_steps_sized")
    if not combine:
        capture["items"].pop()
    if tool_step_reads != "peg_len_mm":
        capture["items"][5]["data"]["params"]["side_one.distance"]["expression"] = tool_step_reads
        next(p for p in capture["parameters"]["model"] if p["name"] == "d3")["expression"] = tool_step_reads
    return capture


class ToolOfSeveralStepsTest(unittest.TestCase):
    def test_a_size_only_a_tool_step_reads_stays_free_and_a_recipe_formula_reads_it(self):
        result = translated(two_step_tool())
        self.assertEqual((result.fixed, result.loose, result.dropped), ([], [], []))
        reads = [s.get("distance") for s in result.recipe["features"]]
        self.assertIn({"expr": "peg_len_mm"}, reads)

    def test_a_tool_that_is_never_combined_marks_nothing_and_its_size_is_unused(self):
        result = translated(two_step_tool(combine=False))
        self.assertEqual((result.fixed, result.loose), ([], []))
        self.assertEqual([(d["name"], d["used"]) for d in result.dropped], [("peg_len_mm", False)])

    def test_a_tool_step_value_the_copy_cannot_follow_marks_its_size_once_the_tool_is_combined(self):
        # The formula gives 8 mm at the measured sizes while Fusion measured 4 mm.
        combined = translated(two_step_tool(tool_step_reads="peg_len_mm * 2"))
        self.assertEqual([(d["name"], d["used"]) for d in combined.dropped], [("peg_len_mm", True)])
        self.assertIn("Extrude4", combined.dropped[0]["reason"])
        alone = translated(two_step_tool(combine=False, tool_step_reads="peg_len_mm * 2"))
        self.assertEqual([(d["name"], d["used"]) for d in alone.dropped], [("peg_len_mm", False)])


def tray_with(*items):
    capture = load_capture(TRAY)
    capture["items"].extend(items)
    return capture


def verdicts(result):
    return {v["name"]: v for v in result.items}


class StepsThatLeaveTheBodyAloneTest(unittest.TestCase):
    def test_a_remove_of_another_body_is_skipped_and_the_copy_goes_on(self):
        result = translated(tray_with(_item(7, "Remove1", "RemoveFeature", [], target_changed=False)))
        self.assertIsNone(result.refusal)
        self.assertEqual(verdicts(result)["Remove1"]["verdict"], "skipped")
        self.assertEqual([n for n in result.notes if "Remove1" in n], [])

    def test_a_remove_is_kept_as_a_stop_when_the_capture_cannot_say_the_body_stayed(self):
        for changed in (True, None):
            with self.subTest(target_changed=changed):
                result = translated(tray_with(_item(7, "Remove1", "RemoveFeature", [], target_changed=changed)))
                self.assertEqual((result.recipe, result.refusal["name"]), (None, "Remove1"))

    def test_a_split_face_on_another_body_is_skipped(self):
        result = translated(tray_with(_item(7, "SplitFace1", "SplitFaceFeature", [LID], target_changed=False)))
        self.assertIsNone(result.refusal)
        self.assertEqual(verdicts(result)["SplitFace1"]["verdict"], "skipped")

    def test_a_split_face_on_the_exported_body_is_skipped_with_a_note_about_picks(self):
        result = translated(tray_with(_item(7, "SplitFace1", "SplitFaceFeature", [BODY], target_changed=False)))
        self.assertIsNone(result.refusal)
        self.assertEqual(verdicts(result)["SplitFace1"]["verdict"], "skipped")
        notes = [n for n in result.notes if "SplitFace1" in n]
        self.assertEqual(len(notes), 1)
        self.assertIn("Picks", notes[0])

    def test_a_split_face_that_the_capture_cannot_prove_harmless_stops_the_copy(self):
        result = translated(tray_with(_item(7, "SplitFace1", "SplitFaceFeature", [BODY], target_changed=None)))
        self.assertEqual(result.refusal["name"], "SplitFace1")

    def test_an_unknown_step_on_the_exported_body_stops_the_copy_and_is_named_even_if_its_size_stays(self):
        # Only a split of faces is known to leave the solid as it is, whatever the box and volume say.
        for changed in (True, False):
            with self.subTest(target_changed=changed):
                result = translated(tray_with(_item(7, "Draft1", "DraftFeature", [BODY], target_changed=changed)))
                self.assertEqual((result.recipe, result.refusal["name"]), (None, "Draft1"))


class FusionWarningTest(unittest.TestCase):
    def test_a_copied_step_that_fusion_warns_about_gets_a_note_on_its_verdict(self):
        capture = load_capture(TRAY)
        capture["items"][3].update(health="warning", message="Some edges could not be rounded.")
        result = translated(capture)
        verdict = verdicts(result)["Fillet1"]
        self.assertEqual(verdict["verdict"], "translatedWithNote")
        self.assertIn("Some edges could not be rounded", verdict["note"])
        self.assertIn(verdict["note"], result.notes)


def pattern_of(expression, count):
    """The tray with its hole pattern making `count` copies, the count written as `expression` in Fusion."""
    capture = load_capture(TRAY)
    data = capture["items"][6]["data"]
    data["quantity_one"] = count
    data["elements"] = [
        {"id": n + 1, "suppressed": False,
         "frame": {"origin": [24 * n, 0, 0], "x": [1, 0, 0], "y": [0, 1, 0], "z": [0, 0, 1]}} for n in range(count)]
    data["params"]["quantity_one"] = {"name": "d8", "expression": expression, "value": float(count)}
    model = next(m for m in capture["parameters"]["model"] if m["name"] == "d8")
    model.update(expression=expression, value=count)
    return capture


class CopyLimitTest(unittest.TestCase):
    def test_a_count_that_stays_under_the_limit_at_every_size_is_left_alone(self):
        result = translated(pattern_of("holes_count * 4", 12))
        self.assertEqual((result.refusal, result.fixed, result.loose), (None, [], []))

    def test_a_count_that_passes_the_limit_inside_its_size_range_marks_its_size(self):
        # holes_count runs from 1 to 6: 150 copies now, 300 at the top.
        result = translated(pattern_of("holes_count * 50", 150))
        self.assertIsNone(result.refusal)
        self.assertEqual([f["name"] for f in result.loose], ["holes_count"])
        self.assertIn("more than 256 copies", result.loose[0]["reason"])
        self.assertIn("holes_count", result.recipe["sizes"])

    def test_a_count_over_the_limit_at_its_current_value_stops_the_copy(self):
        result = translated(pattern_of("holes_count * 100", 300))
        self.assertIsNone(result.recipe)
        self.assertIn("more than 256 copies", result.refusal["reason"])


if __name__ == "__main__":
    unittest.main()
