import copy
import unittest

from tests import context  # noqa: F401
from tests.translator_helpers import left_out
from tests.translator_helpers import assert_schema_ok, edited, load_capture, steps_of, translate_fixture, verdict_of

from lib.params import size_table
from lib.translator import translate
from lib.translator.combine import tool_walk
from lib.translator.context import Context
from lib.translator.finishes.finish import fillet
from lib.translator.result import Refusal


class CombineTest(unittest.TestCase):
    def test_tool_step_moves_to_the_combine_with_its_operation(self):
        for name, combine in (("combine_cut", "cut"), ("combine_join", "add"), ("combine_intersect", "intersect")):
            with self.subTest(name):
                result = translate_fixture(name)
                extrudes = steps_of(result.recipe, "extrude")
                self.assertEqual([(s["id"], s["combine"]) for s in extrudes], [("extrude_1", "new"), ("extrude_4", combine)])
                self.assertEqual(verdict_of(result, 3)["verdict"], "skipped")
                self.assertEqual(verdict_of(result, 4)["steps"], ["extrude_4"])
                assert_schema_ok(self, result.recipe)

    def test_keeping_the_tool_only_adds_a_note(self):
        result = translate_fixture("combine_keep_tools")
        self.assertEqual(verdict_of(result, 4)["verdict"], "translatedWithNote")
        self.assertEqual(steps_of(result.recipe, "extrude")[1]["combine"], "cut")

    def test_several_tools_make_a_step_each(self):
        def edit(capture):
            items = capture["items"]
            second = copy.deepcopy(items[2:4])
            second[0]["index"], second[1]["index"] = 4, 5
            second[1]["bodies_after"] = [{"token": "t3", "name": "Body3"}]
            combine = items[4]
            combine["index"] = 6
            combine["data"]["tools"].append({"token": "t3", "name": "Body3"})
            items[4:4] = second
        result = edited("combine_cut", edit)
        self.assertEqual(verdict_of(result, 6)["steps"], ["extrude_6", "extrude_6_2"])
        self.assertEqual([s["combine"] for s in steps_of(result.recipe, "extrude")], ["new", "cut", "cut"])

    def test_a_tool_step_that_cannot_be_copied_is_left_out_of_the_tool(self):
        def edit(capture):
            capture["items"][4]["type"] = "ThickenFeature"
        result = edited("combine_tool_filleted", edit)
        self.assertEqual(left_out(result)["name"], "Fillet1")
        self.assertEqual(result.gaps[0]["list"], steps_of(result.recipe, "toolBody")[0]["id"])

    def test_a_tool_listed_twice_is_taken_once(self):
        def twice(capture):
            tools = capture["items"][-1]["data"]["tools"]
            tools.append(dict(tools[0]))
        once, doubled = translate_fixture("combine_cut"), edited("combine_cut", twice)
        self.assertEqual(doubled.recipe, once.recipe)

    def test_other_refusals(self):
        def other_target(capture):
            capture["items"][-1]["data"]["target"] = {"token": "t2", "name": "Body2"}

        def unknown_tool(capture):
            capture["items"][-1]["data"]["tools"] = [{"token": "t9", "name": "Body9"}]

        def unknown_operation(capture):
            capture["items"][-1]["data"]["operation"] = "newBody"

        for label, edit in (("other target", other_target), ("unknown tool", unknown_tool),
                            ("operation", unknown_operation)):
            with self.subTest(label):
                result = edited("combine_cut", edit)
                self.assertIsNotNone(left_out(result))
                self.assertEqual(left_out(result)["index"], 4)


def tool_steps_of(operation, tool_operation="join"):
    """A capture of combine_tool_two_steps with the Combine and the second tool step set to the given operations."""
    def edit(capture):
        capture["items"][-1]["data"]["operation"] = operation
        capture["items"][5]["data"]["operation"] = tool_operation
    return edit


class MoreThanOneToolStepTest(unittest.TestCase):
    def test_every_step_of_an_adding_tool_takes_the_operation_of_the_combine(self):
        for operation, written in (("cut", "cut"), ("join", "add")):
            with self.subTest(operation):
                result = edited("combine_tool_two_steps", tool_steps_of(operation))
                self.assertEqual([s["combine"] for s in steps_of(result.recipe, "extrude")], ["new", written, written])
                self.assertEqual(verdict_of(result, 6)["steps"], ["extrude_6", "extrude_6_2"])
                self.assertEqual([verdict_of(result, n)["verdict"] for n in (3, 5)], ["skipped", "skipped"])
                assert_schema_ok(self, result.recipe)

    def test_a_tool_step_that_reaches_to_a_curved_face_is_left_out(self):
        def edit(capture):
            tool_steps_of("cut")(capture)
            capture["items"][5]["data"]["side_one"] = {"kind": "toEntity", "chained": False,
                                                       "plane": None, "offset": 0.0,
                                                       "entity_type": "BRepFace", "face_point": [20, 10, 14]}
        result = edited("combine_tool_two_steps", edit)
        self.assertEqual(left_out(result)["index"], 5)

    def test_a_tool_the_combine_keeps_can_be_used_by_a_second_combine(self):
        def edit(capture):
            tool_steps_of("cut")(capture)
            items = capture["items"]
            items[-1]["data"]["keep_tools"] = True
            again = copy.deepcopy(items[-1])
            again["index"], again["name"] = 7, "Combine2"
            again["data"]["operation"] = "join"
            items.append(again)
        result = edited("combine_tool_two_steps", edit)
        self.assertEqual([s["combine"] for s in steps_of(result.recipe, "extrude")],
                         ["new", "cut", "cut", "add", "add"])
        self.assertEqual(len({s["id"] for s in result.recipe["features"]}), 5)

    def test_a_tool_a_combine_has_used_up_cannot_be_used_again(self):
        def edit(capture):
            items = capture["items"]
            again = copy.deepcopy(items[-1])
            again["index"], again["name"] = 7, "Combine2"
            items.append(again)
        result = edited("combine_tool_two_steps", edit)
        self.assertIsNotNone(left_out(result))
        self.assertEqual(left_out(result)["index"], 7)

    def test_a_change_the_steps_cannot_fill_refuses(self):
        def edit(capture):
            tool_steps_of("cut")(capture)
            data = capture["items"][-1]["data"]
            data["volume_before"], data["volume_after"] = 7000.0, 7000.0 - 1500.0
        result = edited("combine_tool_two_steps", edit)
        self.assertIsNotNone(left_out(result))
        self.assertEqual(left_out(result)["index"], 6)

    def test_a_change_the_steps_can_fill_is_copied(self):
        def edit(capture):
            tool_steps_of("cut")(capture)
            data = capture["items"][-1]["data"]
            data["volume_before"], data["volume_after"] = 7000.0, 7000.0 - 1000.0
        self.assertIsNotNone(edited("combine_tool_two_steps", edit).recipe)


def sized(capture):
    params = capture["parameters"]
    table = size_table.build(params["user"], [p["name"] for p in params["user"]], params["model"], "mm")
    return translate(capture, size_table=table)


def one_step_tool():
    """The plate with a tool of one step, on a sketch 3 mm up; the plate's height follows `plate_h_mm`."""
    capture = load_capture("combine_cut_tool_two_steps_sized")
    del capture["items"][4:6]
    return capture


class ToolWalkTest(unittest.TestCase):
    def seen_by_fillet(self, edit=None):
        """What the handler of the tool's fillet sees: its context and its item."""
        seen = []

        def spy(ctx, step):
            seen.append((step.brought, ctx.target, list(ctx.steps)))
            return fillet(ctx, step)
        capture = load_capture("combine_tool_filleted")
        if edit:
            edit(capture)
        translate(capture, {"FilletFeature": spy})
        return seen[0]

    def test_a_handler_in_a_tool_walk_sees_the_tool_as_its_target(self):
        _, target, steps = self.seen_by_fillet()
        self.assertEqual(target["token"], "t2")
        self.assertEqual([s["kind"] for s in steps], ["extrude"])

    def test_a_handler_reads_what_was_measured_on_the_tool(self):
        box = {"min": [0, 0, 0], "max": [1, 1, 1]}

        def edit(capture):
            fillet_item = next(i for i in capture["items"] if i["type"] == "FilletFeature")
            fillet_item["body_states"] = {"t2": {"box_before": box, "volume_before": 5.0, "volume_after": 4.0}}
        item, _, _ = self.seen_by_fillet(edit)
        self.assertEqual((item["data"]["target_box_before"], item["data"]["volume_after"]), (box, 4.0))

    def test_tools_nested_too_deep_are_refused(self):
        capture = load_capture("combine_cut")
        built = tool_walk.build(Context(capture), {"token": "t2", "name": "Body2"}, 4, tool_walk.MAX_DEPTH + 1)
        self.assertIsInstance(built, Refusal)


class FlatToolOnThePartTest(unittest.TestCase):
    def test_a_tool_that_reaches_a_face_of_the_part_follows_that_face(self):
        capture = one_step_tool()
        capture["items"][3]["data"].update(end_offset=7.0, side_one={
            "kind": "toEntity", "chained": False, "plane": {"point": [12, 10, 10], "normal": [0, 0, 1]}, "offset": 0.0,
            "entity_type": "BRepFace", "face_point": [12, 10, 10]})
        cut = steps_of(sized(capture).recipe, "extrude")[1]
        self.assertEqual(cut["distance"], {"expr": "plate_h_mm - 3"})

    def test_a_joined_tool_starts_with_the_outline_that_meets_the_part(self):
        def square(x):
            corners = [[x, 5], [x + 8, 5], [x + 8, 15], [x, 15]]
            return {"sketch": "Sketch3", "frame": {"origin": [0, 0, 0], "x": [1, 0, 0], "y": [0, 1, 0], "z": [0, 0, 1]},
                    "loops": [{"outer": True, "curves": [{"kind": "line", "start": corners[n], "end": corners[(n + 1) % 4]}
                                                         for n in range(4)]}]}
        capture = one_step_tool()
        capture["items"][3]["data"]["profiles"] = [square(50), square(30)]
        capture["items"][-1]["data"]["operation"] = "join"
        first = steps_of(translate(capture).recipe, "extrude")[1]
        self.assertEqual(first["sketch"]["outer"]["center"][0], 34)

    def test_a_step_sees_only_what_was_written_before_it(self):
        ctx = Context({"target": {"token": "t1"}, "items": []})
        first, second = {"index": 1}, {"index": 2}
        ctx.enter(first)
        ctx.written_reads = ("a",)
        ctx.enter(second)
        ctx.written_reads = ("a", "b")
        with ctx.as_of(first):
            self.assertEqual(ctx.written_reads, ())
        with ctx.as_of(second):
            self.assertEqual(ctx.written_reads, ("a",))
        self.assertEqual(ctx.written_reads, ("a", "b"))


if __name__ == "__main__":
    unittest.main()
