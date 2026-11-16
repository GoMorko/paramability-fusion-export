"""Combine steps in the Orca copy (`orca_translate/combine.py`, `tools.py`): each tool body written from the steps
that made it, then an Orca Boolean into the part, with the body indexes Orca resolves at that point."""
import copy
import unittest

from tests import context  # noqa: F401
from tests.orca_sized import fixture, table_of
from tests.translator_helpers import verdict_of

from lib.capture_model import gap_hints
from lib.orca_recipe.enums import BooleanMode, FeatureType
from lib.orca_translate import causes, translate


def of_type(result, kind):
    return [f for f in result.recipe.features if f.type == kind]


def run(name, edit=None):
    capture = fixture(name)
    if edit is not None:
        edit(capture)
    return translate(capture)


PART = {"token": "t9", "name": "Plate"}


def intersect_tool(state=None):
    """`intersect_every` as a tool: its Combine (index 6) makes Body1 from what it shares with Body2 and Body3, then a
    plate (Plate, exported) is extruded and Body1 cut from it. The reader read the intersect rule with the plate's
    volume ("any"); `state` is what it measured on Body1 itself around the Combine."""
    capture = fixture("intersect_every")
    capture["items"][6]["data"]["intersect_model"] = "any"
    if state is not None:
        capture["items"][6]["body_states"] = {"t1": state}
    plate = copy.deepcopy(capture["items"][1])
    plate.update(index=7, name="Plate", bodies_after=[PART])
    plate["data"].update(participants=[], profiles=[dict(plate["data"]["profiles"][0], sketch="Sketch1")])
    plate["data"]["profiles"][0]["loops"][0]["curves"] = [
        {"kind": "line", "start": a, "end": b} for a, b in
        (([-10, -10], [50, -10]), ([50, -10], [50, 30]), ([50, 30], [-10, 30]), ([-10, 30], [-10, -10]))]
    cut = copy.deepcopy(capture["items"][6])
    cut.pop("body_states", None)
    cut.update(index=8, name="Combine2", bodies_after=[PART])
    cut["data"] = {"target": PART, "tools": [{"token": "t1", "name": "Body1", "volume": 2000.0}],
                   "operation": "cut", "keep_tools": False, "volume_before": 24000.0, "volume_after": 22000.0}
    capture["items"] += [plate, cut]
    capture["target"] = dict(PART, box={"min": [-10, -10, 0], "max": [50, 30, 10]}, volume_mm3=22000.0)
    return capture


class CombineTest(unittest.TestCase):
    def test_join_cut_and_intersect_become_booleans_on_the_part_with_the_tool_after_it(self):
        for name, mode in (("combine_join", BooleanMode.ADD), ("combine_cut", BooleanMode.CUT),
                           ("combine_intersect", BooleanMode.INTERSECT)):
            result = run(name)
            (boolean,) = of_type(result, FeatureType.BOOLEAN)
            self.assertEqual((boolean.mode, boolean.target_body, boolean.bool_tool_body, boolean.bool_keep_tool),
                             (mode, 0, 1, False), name)
            self.assertEqual(of_type(result, FeatureType.EXTRUDE)[-1].mode, BooleanMode.NEW, name)
            self.assertEqual(verdict_of(result, 3)["verdict"], "copied")

    def test_a_tool_kept_by_fusion_is_still_used_up_in_orca(self):
        result = run("combine_keep_tools")
        self.assertFalse(of_type(result, FeatureType.BOOLEAN)[0].bool_keep_tool)

    def test_an_intersect_with_any_tool_joins_the_tools_first(self):
        result = run("intersect_any")
        first, second = of_type(result, FeatureType.BOOLEAN)
        self.assertEqual((first.mode, first.target_body, first.bool_tool_body), (BooleanMode.ADD, 1, 2))
        self.assertEqual((second.mode, second.target_body, second.bool_tool_body), (BooleanMode.INTERSECT, 0, 1))

    def test_an_intersect_with_every_tool_keeps_what_each_shares(self):
        result = run("intersect_every")
        booleans = of_type(result, FeatureType.BOOLEAN)
        self.assertEqual([(b.mode, b.target_body, b.bool_tool_body) for b in booleans],
                         [(BooleanMode.INTERSECT, 0, 1), (BooleanMode.INTERSECT, 0, 1)])

    def test_an_intersect_whose_rule_is_unknown_is_left_out(self):
        result = run("intersect_every", lambda c: c["items"][-1]["data"].update(intersect_model="unknown"))
        self.assertEqual([g["cause"] for g in result.left_out], [causes.INTERSECT_RULE])

    def test_a_combine_inside_a_tool_builds_that_tool_deeper(self):
        result = run("combine_in_tool")
        booleans = of_type(result, FeatureType.BOOLEAN)
        # The inner Combine works on the tool (body 1) with its own tool after it (body 2); the outer one on the part.
        self.assertEqual([(b.target_body, b.bool_tool_body) for b in booleans], [(1, 2), (0, 1)])

    def test_a_combine_inside_a_tool_reads_the_rule_measured_on_the_tool(self):
        result = translate(intersect_tool({"box_before": None, "volume_before": 8000.0, "volume_after": 2000.0}))
        # Body1 kept what it shares with every tool: two intersects on it, then the cut of the plate.
        booleans = of_type(result, FeatureType.BOOLEAN)
        self.assertEqual([b.mode for b in booleans], [BooleanMode.INTERSECT] * 2 + [BooleanMode.CUT])
        self.assertEqual(verdict_of(result, 8)["verdict"], "copied")

    def test_a_combine_inside_a_tool_with_no_measure_of_the_tool_is_left_out(self):
        result = translate(intersect_tool())
        self.assertEqual([(g["index"], g["cause"]) for g in result.left_out], [(8, causes.INTERSECT_RULE)])

    def test_a_tool_moved_by_a_move_turns_with_the_angle_parameter(self):
        capture = fixture("move_rotate_sized")
        result = translate(capture, table_of(capture))
        (move,) = of_type(result, FeatureType.TRANSFORM)
        self.assertEqual((move.target_body, move.expr), (1, {"xf_angle_deg": "tilt_deg"}))
        self.assertEqual({p["name"]: p["outcome"] for p in result.parameters},
                         {"peg_len_mm": "variable", "tilt_deg": "variable"})

    def test_a_tool_that_cannot_be_copied_leaves_the_combine_out_and_writes_nothing(self):
        def edit(capture):
            capture["items"][3]["data"]["thin"] = True
        result = run("combine_join", edit)
        self.assertEqual([(g["index"], g["cause"]) for g in result.left_out], [(4, gap_hints.THIN_OUTLINE)])
        self.assertEqual(len(result.recipe.features), 2)
        self.assertEqual(verdict_of(result, 3)["verdict"], "skipped")

    def test_a_step_of_a_tool_that_cannot_be_copied_is_named_with_the_tool(self):
        def edit(capture):
            cut = copy.deepcopy(capture["items"][3])
            cut.update(index=4, name="Cut3")
            cut["data"].update(operation="cut", participants=[{"token": "t2", "name": "Body2"}],
                               target_box_before={"min": [15, 5, -2], "max": [25, 15, 12]})
            cut["data"]["profiles"][0]["loops"][0]["curves"][0]["center"] = [100, 100]
            capture["items"][4]["index"] = 5
            capture["items"].insert(4, cut)
        (gap,) = run("combine_join", edit).left_out
        self.assertEqual((gap["name"], gap["cause"]), ("Combine1", causes.MISSES_PART))
        # The reason of the cut names the tool body it misses, not the exported part.
        self.assertIn("meet the tool body Body2", gap["reason"])

    def test_a_second_tool_that_cannot_be_copied_undoes_the_first(self):
        def edit(capture):
            capture["items"][-1]["data"]["intersect_model"] = "every"
            capture["items"][5]["data"]["thin"] = True
        result = run("intersect_every", edit)
        self.assertEqual(verdict_of(result, 6)["verdict"], "leftOut")
        self.assertEqual(verdict_of(result, 3)["verdict"], "skipped")
        self.assertEqual(of_type(result, FeatureType.BOOLEAN), [])

    def test_a_combine_of_another_body_that_keeps_the_part_does_not_change_it(self):
        def edit(capture):
            data = capture["items"][4]["data"]
            data["target"], data["tools"], data["keep_tools"] = {"token": "t2", "name": "Body2"}, \
                [{"token": "t1", "name": "Body1"}], True
            capture["items"][4]["bodies_after"] = [{"token": "t1", "name": "Body1"}, {"token": "t2", "name": "Body2"}]
        result = run("combine_join", edit)
        self.assertEqual(verdict_of(result, 4)["verdict"], "skipped")
        self.assertEqual(of_type(result, FeatureType.BOOLEAN), [])


if __name__ == "__main__":
    unittest.main()
