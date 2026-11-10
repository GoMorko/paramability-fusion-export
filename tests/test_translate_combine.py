import copy
import unittest

from tests import context  # noqa: F401
from tests.translator_helpers import assert_schema_ok, edited, steps_of, translate_fixture, verdict_of


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

    def test_a_tool_with_a_fillet_refuses_and_names_the_fillet(self):
        result = translate_fixture("combine_tool_filleted")
        self.assertIsNone(result.recipe)
        self.assertEqual(result.refusal["type"], "CombineFeature")
        self.assertIn("Fillet1 (fillet)", result.refusal["reason"])

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
                self.assertIsNone(result.recipe)
                self.assertEqual(result.refusal["index"], 4)


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

    def test_a_tool_step_that_cuts_the_tool_refuses_and_names_the_cut(self):
        result = edited("combine_tool_two_steps", tool_steps_of("cut", "cut"))
        self.assertIsNone(result.recipe)
        self.assertEqual(result.refusal["index"], 6)
        self.assertIn("Extrude3 (cut)", result.refusal["reason"])

    def test_an_intersect_takes_a_tool_of_one_step_only(self):
        result = edited("combine_tool_two_steps", tool_steps_of("intersect"))
        self.assertIsNone(result.recipe)
        self.assertEqual(result.refusal["index"], 6)

    def test_a_second_tool_step_that_reaches_to_a_face_refuses(self):
        def edit(capture):
            tool_steps_of("cut")(capture)
            capture["items"][5]["data"]["side_one"] = {"kind": "toEntity", "plane": None, "offset": 0.0,
                                                       "entity_type": "BRepFace", "face_point": [20, 10, 14]}
        result = edited("combine_tool_two_steps", edit)
        self.assertIsNone(result.recipe)
        self.assertEqual(result.refusal["index"], 6)

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
        self.assertIsNone(result.recipe)
        self.assertEqual(result.refusal["index"], 7)

    def test_a_change_the_steps_cannot_fill_refuses(self):
        def edit(capture):
            tool_steps_of("cut")(capture)
            data = capture["items"][-1]["data"]
            data["volume_before"], data["volume_after"] = 7000.0, 7000.0 - 1500.0
        result = edited("combine_tool_two_steps", edit)
        self.assertIsNone(result.recipe)
        self.assertEqual(result.refusal["index"], 6)

    def test_a_change_the_steps_can_fill_is_copied(self):
        def edit(capture):
            tool_steps_of("cut")(capture)
            data = capture["items"][-1]["data"]
            data["volume_before"], data["volume_after"] = 7000.0, 7000.0 - 1000.0
        self.assertIsNotNone(edited("combine_tool_two_steps", edit).recipe)


if __name__ == "__main__":
    unittest.main()
