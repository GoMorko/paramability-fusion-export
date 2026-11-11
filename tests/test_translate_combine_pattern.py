"""A pattern whose sources are a Combine and the steps that built its tool (lib/translator/repeat.py)."""
import unittest

from tests import context  # noqa: F401
from tests.schema_check import check_recipe
from tests.translator_helpers import load_capture, steps_of

from lib.params import size_table
from lib.params.expressions import evaluate
from lib.translator import translate

PATTERN = 7


def sized(capture):
    params = capture["parameters"]
    table = size_table.build(params["user"], [p["name"] for p in params["user"]], params["model"],
                             capture.get("design_units", "mm"))
    return translate(capture, size_table=table)


def flat(capture):
    """The tool's hole becomes a join, so the Combine writes the tool's steps one by one onto the part."""
    capture["items"][5]["data"]["operation"] = "join"
    for key in ("volume_before", "volume_after"):
        capture["items"][6]["data"].pop(key)
    return capture


def with_sources(capture, sources):
    capture["items"][PATTERN]["data"]["sources"] = sources
    return capture


class CombinePatternTest(unittest.TestCase):
    def test_the_copies_repeat_the_tool_step_and_follow_the_count_and_reach(self):
        result = sized(load_capture("combine_tool_pattern"))
        self.assertIsNone(result.refusal)
        tool = steps_of(result.recipe, "toolBody")[0]
        patterns = steps_of(result.recipe, "pattern")
        # One part of the row runs each way from the peg.
        self.assertEqual(len(patterns), 2)
        self.assertTrue(all(p["of"] == [tool["id"]] for p in patterns))
        env = {"pegs": 5, "plate_w_mm": 60}
        for pattern in patterns:
            self.assertEqual(evaluate(pattern["linear"]["count"]["expr"], env), 3)
            self.assertAlmostEqual(evaluate(pattern["linear"]["step"]["expr"], env), 7.5)
        self.assertIn("value", result.recipe["sizes"]["pegs"])
        self.assertEqual(check_recipe(result.recipe), [])

    def test_a_combine_written_flat_is_repeated_by_its_own_steps(self):
        result = translate(flat(load_capture("combine_tool_pattern")))
        self.assertIsNone(result.refusal)
        self.assertEqual(steps_of(result.recipe, "toolBody"), [])
        written = [s["id"] for s in result.recipe["features"] if s.get("combine") == "cut"]
        self.assertEqual(len(written), 2)
        self.assertTrue(all(p["of"] == written for p in steps_of(result.recipe, "pattern")))
        self.assertEqual(check_recipe(result.recipe), [])

    def test_a_combine_without_every_step_of_its_tool_refuses(self):
        for sources in ([3, 6], [6]):
            with self.subTest(sources):
                result = translate(with_sources(load_capture("combine_tool_pattern"), sources))
                self.assertEqual(result.refusal["index"], PATTERN)

    def test_the_steps_of_a_tool_without_their_combine_refuse(self):
        result = translate(with_sources(load_capture("combine_tool_pattern"), [3, 5]))
        self.assertEqual(result.refusal["index"], PATTERN)

    def test_an_intersecting_combine_refuses(self):
        capture = load_capture("combine_tool_pattern")
        data = capture["items"][6]["data"]
        data["operation"] = "intersect"
        for key in ("volume_before", "volume_after"):
            data.pop(key)
        result = translate(capture)
        self.assertEqual(result.refusal["index"], PATTERN)


if __name__ == "__main__":
    unittest.main()
