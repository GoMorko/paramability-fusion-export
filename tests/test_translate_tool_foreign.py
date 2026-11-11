"""A Combine whose tool body is made in another component (lib/translator/combine.py, tool_move).

The fixture `component_tool_foreign`: a box in the root cut by a tool of two joined cylinders made in the component
Rod. Rod sits at (30, 10, 0) turned a quarter about z. box_h is read by the box, tool_len by both tool steps, and
rod_x acts on Rod without a step reading it.
"""
import copy
import unittest

from tests import context  # noqa: F401
from tests.schema_check import check_recipe
from tests.translator_helpers import load_capture, steps_of

from lib.params import size_table
from lib.params.expressions import evaluate
from lib.sketch_values.motion import Motion
from lib.translator import translate
from lib.translator.moved_placer import MovedPlacer
from lib.translator.slabs import Motion as CopyMotion

NAME = "component_tool_foreign"
SIZES = ["box_h", "tool_len", "rod_x"]
MEASURED = {"7.tool0.xy": "", "7.tool0.xz": "", "7.tool0.yz": ""}
MOVES = {"const": -30, "terms": {"rod_x": 1}}


def run(capture, motion=None, ticked=SIZES):
    params = capture["parameters"]
    table = size_table.build(params["user"], ticked, params["model"], capture.get("design_units", "mm"))
    return translate(capture, size_table=table, motion=motion)


def motion_of(values=None, refs=None):
    return Motion.from_json({"values": values or {}, "refs": MEASURED if refs is None else refs})


def marked(result):
    found = {d["name"]: d["reason"] for d in result.dropped if d.get("used")}
    found.update({d["name"]: d["reason"] for d in result.loose})
    found.update({d["name"]: d["reason"] for d in result.fixed})
    return found


def with_tool(edit):
    capture = load_capture(NAME)
    edit(capture["items"][-1]["data"]["tools"][0], capture)
    return capture


def value_at(written, **sizes):
    return evaluate(written["expr"], sizes) if isinstance(written, dict) else written


class PlacedToolTest(unittest.TestCase):
    def setUp(self):
        self.result = translate(load_capture(NAME))
        self.cuts = [s for s in self.result.recipe["features"] if s.get("combine") == "cut"]

    def test_each_tool_step_is_written_at_the_combines_place_in_the_tools_place(self):
        self.assertEqual(len(self.cuts), 2)
        for cut in self.cuts:
            self.assertEqual(cut["sketch"]["on"]["origin"], [30.0, 10.0, 0.0])
            self.assertEqual(cut["sketch"]["on"]["xDir"], [0.0, 1.0, 0.0])
        self.assertEqual(check_recipe(self.result.recipe), [])

    def test_the_steps_of_the_tool_are_part_of_the_copy(self):
        self.assertIsNone(self.result.refusal)
        self.assertEqual([v["verdict"] for v in self.result.items if v["index"] == 7], ["translated"])

    def test_a_box_not_in_the_root_is_moved_by_the_inverse_of_its_own_place(self):
        def edit(tool, capture):
            tool["place"]["target_frame"] = {"origin": [5, 0, 0], "x": [1, 0, 0], "y": [0, 1, 0], "z": [0, 0, 1]}
        cut = [s for s in translate(with_tool(edit)).recipe["features"] if s.get("combine") == "cut"][0]
        self.assertEqual(cut["sketch"]["on"]["origin"], [25.0, 10.0, 0.0])

    def test_a_tool_in_the_root_is_not_moved(self):
        def edit(tool, capture):
            tool["place"] = {"path": "", "frame": copy.deepcopy(capture["items"][1]["data"]["profiles"][0]["frame"]),
                             "source": "root", "target_frame": None}
        cut = [s for s in translate(with_tool(edit)).recipe["features"] if s.get("combine") == "cut"][0]
        self.assertEqual(cut["sketch"]["on"]["origin"], [0.0, 0.0, 0.0])


class SizesOfTheToolTest(unittest.TestCase):
    def test_a_size_a_tool_step_reads_is_a_free_size_the_tool_follows(self):
        result = run(load_capture(NAME), motion_of())
        self.assertEqual((result.loose, result.fixed), ([], []))
        self.assertIn("tool_len", result.recipe["sizes"])
        distances = [s["distance"] for s in result.recipe["features"] if s.get("combine") == "cut"]
        self.assertEqual(distances, [{"expr": "tool_len"}] * 2)

    def test_a_size_that_acts_on_the_tools_component_without_moving_it_is_not_marked(self):
        result = run(load_capture(NAME), motion_of())
        self.assertEqual(marked(result), {})
        (rod,) = [d for d in result.dropped if d["name"] == "rod_x"]
        self.assertTrue(rod["tried"])

    def test_the_sizes_of_a_tool_step_count_only_when_the_combine_takes_the_tool(self):
        capture = load_capture(NAME)
        capture["items"].pop()
        result = run(capture, motion_of())
        self.assertNotIn("tool_len", result.recipe["sizes"])
        self.assertEqual(marked(result), {})

    def test_a_size_that_moves_the_tools_component_moves_the_steps_with_it(self):
        result = run(load_capture(NAME), motion_of({"7/r/tool0.yz/offset": MOVES}))
        self.assertEqual((result.loose, result.fixed), ([], []))
        self.assertIn("rod_x", result.recipe["sizes"])
        origin = [s for s in result.recipe["features"] if s.get("combine") == "cut"][0]["sketch"]["on"]["origin"]
        self.assertEqual([value_at(c, rod_x=x) for c in origin for x in (30,)], [30.0, 10.0, 0.0])
        self.assertEqual(value_at(origin[1], rod_x=40), 20.0)
        self.assertEqual(value_at(origin[0], rod_x=40), 30.0)

    def test_a_place_that_turns_marks_the_sizes_that_turn_it_and_keeps_the_place(self):
        values = {"7/r/tool0.yz/offset": {"stuck": ["rod_x"], "cause": "turns"}}
        result = run(load_capture(NAME), motion_of(values))
        self.assertEqual(list(marked(result)), ["rod_x"])
        self.assertIn("Rod", marked(result)["rod_x"])
        self.assertEqual([s for s in result.recipe["features"] if s.get("combine") == "cut"][0]["sketch"]["on"]["origin"],
                         [30.0, 10.0, 0.0])

    def test_a_place_the_probe_did_not_measure_marks_every_size_that_acts_on_the_component(self):
        for refs in ({}, {"7.tool0.xy": "its first read did not match the capture"}):
            with self.subTest(refs=refs):
                result = run(load_capture(NAME), motion_of(refs=refs))
                self.assertEqual(sorted(marked(result)), ["rod_x", "tool_len"])

    def test_without_a_motion_file_the_sizes_that_act_on_the_component_are_marked(self):
        self.assertEqual(sorted(marked(run(load_capture(NAME)))), ["rod_x", "tool_len"])

    def test_a_tool_without_references_to_its_planes_marks_the_sizes_that_act_on_the_component(self):
        def edit(tool, capture):
            for slot in ("xy", "xz", "yz"):
                del tool["place"][slot]
        result = run(with_tool(edit), motion_of())
        self.assertEqual(sorted(marked(result)), ["rod_x", "tool_len"])

    def test_the_first_translation_marks_nothing(self):
        from lib.sketch_values.motion import OPTIMISTIC
        self.assertEqual(marked(run(load_capture(NAME), OPTIMISTIC)), {})

    def test_a_size_behind_a_sketch_of_the_tool_is_followed_through_the_probe(self):
        capture = load_capture(NAME)
        capture["parameters"]["model"].append({
            "name": "d20", "expression": "tool_r", "value": 0.4, "unit": "mm", "kind": "derived", "is_favorite": False,
            "value_type": "numeric", "dependency_parameters": ["tool_r"], "role": "Radius",
            "created_by": {"kind": "sketchDimension", "token": "", "name": "", "sketch": "Sketch1", "component": "cRod"}})
        capture["parameters"]["user"].append({
            "name": "tool_r", "expression": "4 mm", "value": 0.4, "unit": "mm", "comment": "", "is_favorite": True,
            "value_type": "numeric", "dependency_parameters": [], "kind": "length", "display_value": 4.0,
            "dependents": [{"name": "d20", "kind": "sketchDimension", "sketch": "Sketch1", "sketch_token": "sk_rod1",
                            "component": "cRod"}]})
        values = {"4/p0/l0/radius": {"const": 0, "terms": {"tool_r": 1}, "sketch": "Sketch1"}}
        result = run(capture, motion_of(values), SIZES + ["tool_r"])
        self.assertIn("tool_r", result.recipe["sizes"])
        radius = [s for s in result.recipe["features"] if s.get("combine") == "cut"][0]["sketch"]["outer"]["radius"]
        self.assertEqual(value_at(radius, tool_r=6), 6.0)


class RefusedToolTest(unittest.TestCase):
    def step_before_combine(self, kind, name, data=None):
        capture = load_capture(NAME)
        step = copy.deepcopy(capture["items"][6])
        step.update(index=7, name=name, type=kind, data=data if data is not None else {})
        capture["items"][7]["index"] = 8
        capture["items"].insert(7, step)
        return capture

    def refusal(self, capture):
        result = translate(capture)
        self.assertIsNone(result.recipe)
        return result.refusal

    def test_a_round_on_the_tool_stops_the_copy_and_names_the_step_and_the_component(self):
        refusal = self.refusal(self.step_before_combine("FilletFeature", "Fillet1"))
        self.assertEqual(refusal["name"], "Combine1")
        self.assertIn("Fillet1", refusal["reason"])
        self.assertIn("Rod", refusal["reason"])

    def test_a_pasted_tool_and_a_moved_tool_that_were_not_read_stop_the_copy_and_name_the_step(self):
        for kind in ("CopyPasteBody", "MoveFeature"):
            with self.subTest(kind):
                self.assertIn("Step1", self.refusal(self.step_before_combine(kind, "Step1"))["reason"])

    def test_a_step_that_was_not_read_stops_the_copy_and_says_why(self):
        capture = self.step_before_combine("ExtrudeFeature", "Extrude9", {})
        del capture["items"][7]["helper_of"]
        capture["items"][7]["helper_unread"] = "the export reads at most 40 steps of tool bodies"
        reason = self.refusal(capture)["reason"]
        self.assertIn("Extrude9", reason)
        self.assertIn("at most 40", reason)

    def test_a_step_that_could_not_be_read_stops_the_copy(self):
        capture = load_capture(NAME)
        capture["items"][6]["data"] = {"read_error": "boom"}
        self.assertIn("Extrude2", self.refusal(capture)["reason"])

    def test_a_step_that_reaches_into_a_third_component_stops_the_copy(self):
        capture = load_capture(NAME)
        capture["items"][6]["data"]["side_one"] = {"kind": "toEntity", "foreign": True}
        self.assertIn("another component", self.refusal(capture)["reason"])

    def test_a_tool_whose_place_cannot_be_used_stops_the_copy_and_names_the_component(self):
        cases = {
            "error": lambda t, c: t.update(place={"path": "Rod:1", "error": "No planes of the component could be compared."}),
            "scaled": lambda t, c: t["place"]["frame"].update(x=[2, 0, 0]),
            "target": lambda t, c: t["place"].update(target_error="The place of the part could not be read."),
            "target scaled": lambda t, c: t["place"].update(target_frame={"origin": [0, 0, 0], "x": [2, 0, 0],
                                                                         "y": [0, 1, 0], "z": [0, 0, 1]}),
        }
        for name, edit in cases.items():
            with self.subTest(name):
                reason = self.refusal(with_tool(edit))["reason"]
                self.assertIn("place of", reason)

    def test_a_tool_that_names_no_place_is_not_copied(self):
        def edit(tool, capture):
            del tool["place"]
        self.assertIn("another component", self.refusal(with_tool(edit))["reason"])

    def test_a_combine_that_removes_more_than_the_tool_fills_is_refused(self):
        capture = load_capture(NAME)
        capture["items"][-1]["data"]["volume_after"] = 100.0
        self.assertIn("more than", self.refusal(capture)["reason"])


class KeptToolTest(unittest.TestCase):
    def test_a_kept_tool_serves_a_second_combine_at_its_place(self):
        capture = load_capture(NAME)
        capture["items"][-1]["data"]["keep_tools"] = True
        second = copy.deepcopy(capture["items"][-1])
        second.update(index=8, name="Combine2")
        capture["items"].append(second)
        result = translate(capture)
        self.assertIsNone(result.refusal)
        self.assertEqual(len([s for s in result.recipe["features"] if s.get("combine") == "cut"]), 4)


class MovedPlacerTest(unittest.TestCase):
    class Inner:
        opaque = False

        def material_at(self, p):
            return "add" if all(0 <= c <= 1 for c in p) else None

    def test_material_is_asked_about_the_point_carried_back(self):
        placer = MovedPlacer(self.Inner(), CopyMotion(shift=(10, 0, 0)))
        self.assertEqual((placer.material_at([10.5, 0.5, 0.5]), placer.material_at([0.5, 0.5, 0.5])), ("add", None))
        self.assertIsNone(placer.place([10.5, 0.5, 0.5], False))


class ProbeSeesTheToolTest(unittest.TestCase):
    def test_the_sketches_of_the_tool_steps_and_the_places_of_its_planes_are_followed(self):
        from lib.probe import plan
        capture = load_capture(NAME)
        found = plan.scan(capture)
        self.assertEqual(sorted(found.native), ["sk_rod1", "sk_rod2"])
        self.assertEqual(sorted(found.covered), ["sk_Sketch1", "sk_rod1", "sk_rod2"])
        params = capture["parameters"]
        table = size_table.build(params["user"], SIZES, params["model"], "mm")
        request = plan.request(capture, table)
        self.assertEqual(request["native"], ["sk_rod1", "sk_rod2"])
        self.assertEqual(sorted(request["refs"]), ["7.tool0.xy", "7.tool0.xz", "7.tool0.yz"])
        refs = plan.refs(capture)
        self.assertEqual(sorted(r["key"] for r in refs), ["7.tool0.xy", "7.tool0.xz", "7.tool0.yz"])
        self.assertTrue(all(r["shape"] == plan.SHAPE_PLANE for r in refs))


if __name__ == "__main__":
    unittest.main()
