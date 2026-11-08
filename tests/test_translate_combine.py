import copy
import unittest

from tests import context  # noqa: F401
from tests.translator_helpers import assert_schema_ok, load_capture, steps_of, translate_fixture

from lib.translator import translate


def verdict_of(result, index):
    return [v for v in result.items if v["index"] == index][0]


def edited(name, edit):
    capture = copy.deepcopy(load_capture(name))
    edit(capture)
    return translate(capture)


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

    def test_tools_with_other_history_refuse(self):
        for name in ("combine_tool_filleted", "combine_tool_two_steps"):
            with self.subTest(name):
                result = translate_fixture(name)
                self.assertIsNone(result.recipe)
                self.assertEqual(result.refusal["type"], "CombineFeature")

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


if __name__ == "__main__":
    unittest.main()
