"""Path patterns on one straight line, arc or circle, written as the rectangular or circular pattern they equal."""
import copy
import math
import unittest

from tests import context  # noqa: F401
from tests.test_translate_sized import table_of
from tests.translator_helpers import assert_schema_ok, left_out, load_capture, steps_of, translate_fixture

from lib.capture_model import gap_hints
from lib.design_model import words as shared
from lib.params.expressions import evaluate
from lib.probe.plan.covered import scan
from lib.sketch_values.motion import Motion
from lib.translator import translate
from lib.translator.ranges.range_check import recipe_size_values

LINE, ARC = "ppattern_line", "ppattern_arc"
SIZES = ["count", "pitch"]


def capture_of(name, edit=None):
    capture = copy.deepcopy(load_capture(name))
    if edit:
        edit(capture["items"][-1]["data"])
    return capture


def sized(name, edit=None, ticked=SIZES):
    capture = capture_of(name, edit)
    table = table_of(capture, ticked)
    return translate(capture, size_table=table), table


def gap_of(result):
    return next(g for g in result.gaps if g["name"] == "PathPattern1")


class PathPatternTest(unittest.TestCase):
    def test_a_line_path_is_a_row_along_the_line(self):
        result = translate_fixture(LINE)
        (pattern,) = steps_of(result.recipe, "pattern")
        self.assertEqual(pattern["linear"], {"dir": [1, 0, 0], "count": 3, "step": 15})
        self.assertEqual(pattern["of"], ["extrude_3"])
        assert_schema_ok(self, result.recipe)

    def test_an_arc_path_is_a_turn_about_the_arc_centre(self):
        result = translate_fixture(ARC)
        (pattern,) = steps_of(result.recipe, "pattern")
        polar = pattern["polar"]
        self.assertEqual((polar["axisPoint"], polar["axis"], polar["count"]), ([20, 10, 10], [0, 0, 1], 3))
        self.assertAlmostEqual(polar["angleDeg"], 60.0, places=6)
        assert_schema_ok(self, result.recipe)

    def test_a_full_circle_path_turns_evenly_and_keeps_its_distance(self):
        def full(data):
            data["path"]["curves"][0].update(kind="circle")
            data["distance_type"] = "extent"
            data["distance"] = 2 * math.pi * 8.0
            data["params"]["distance"] = {"name": "d4", "expression": "pitch * 12", "value": 2 * math.pi * 8.0}
            data["path"]["closed"] = True
            turn = data["elements"]
            for element, angle in zip(turn, (0, 120, 240)):
                a = math.radians(angle)
                ca, sa = math.cos(a), math.sin(a)
                element["frame"] = {"origin": [20 - (ca * 20 - sa * 10), 10 - (sa * 20 + ca * 10), 0.0],
                                    "x": [ca, sa, 0.0], "y": [-sa, ca, 0.0], "z": [0.0, 0.0, 1.0]}
        result, _ = sized(ARC, full)
        (pattern,) = steps_of(result.recipe, "pattern")
        self.assertNotIn("angleDeg", pattern["polar"])
        self.assertEqual(pattern["polar"]["count"], {"expr": "count"})
        self.assertNotIn("pitch", result.recipe.get("sizes") or {})
        self.assertIn("pitch", [entry["name"] for entry in result.loose + result.dropped])

    def test_count_and_spacing_follow_and_the_ranges_keep_the_copies_on_the_path(self):
        for name in (LINE, ARC):
            with self.subTest(name):
                result, table = sized(name)
                (pattern,) = steps_of(result.recipe, "pattern")
                self.assertEqual(sorted(c["name"] for c in result.cuts), SIZES)
                self.assertEqual(result.loose, [])
                if name == ARC:
                    angle = pattern["polar"]["angleDeg"]["expr"]
                    env = recipe_size_values(table, {})
                    self.assertAlmostEqual(evaluate(angle, env), 60.0, places=4)
                    env = dict(env, count=4)
                    self.assertAlmostEqual(evaluate(angle, env), 90.0, places=4)

    def test_a_size_that_moves_the_path_sketch_is_marked(self):
        capture = capture_of(ARC)
        capture["parameters"]["model"].append(dict(capture["parameters"]["model"][3], name="d5",
                                                   expression="pitch * 2",
                                                   created_by={"kind": "sketchDimension", "sketch": "Sketch4"}))
        capture["parameters"]["user"][1]["dependent_parameters"].append("d5")
        result = translate(capture, size_table=table_of(capture, SIZES), motion=Motion({}))
        self.assertEqual(len(steps_of(result.recipe, "pattern")), 1)
        self.assertEqual([entry["name"] for entry in result.loose], ["pitch"])

    def test_the_path_sketch_stays_followed_by_the_size_probe(self):
        self.assertIn("s4", scan(load_capture(LINE)).covered)


class PathPatternLeftOutTest(unittest.TestCase):
    def assert_left_out(self, name, edit, reason):
        result = translate(capture_of(name, edit))
        self.assertEqual(left_out(result)["index"], 5)
        self.assertEqual(left_out(result)["reason"], reason)
        self.assertEqual(gap_of(result)["hint"], gap_hints.HINTS[gap_hints.PATH_PATTERN])
        self.assertEqual(len(steps_of(result.recipe, "extrude")), 2)

    def test_a_path_of_two_curves(self):
        def two(data):
            data["path"]["curves"].append(copy.deepcopy(data["path"]["curves"][0]))
        self.assert_left_out(LINE, two, shared.PATH_PATTERN_CURVE)

    def test_copies_to_both_sides_of_the_start_point(self):
        self.assert_left_out(LINE, lambda data: data.update(symmetric=True), shared.PATH_PATTERN_BOTH_SIDES)

    def test_copies_that_keep_their_direction_on_a_round_path(self):
        self.assert_left_out(ARC, lambda data: data.update(along_path=False), shared.PATH_PATTERN_SLIDES)

    def test_a_setting_that_could_not_be_read(self):
        self.assert_left_out(LINE, lambda data: data.update(start_point=None), shared.PATH_PATTERN_UNREAD)

    def test_copies_past_the_end_of_the_path(self):
        self.assert_left_out(LINE, lambda data: data.update(start_point=0.5), shared.PATH_PATTERN_RUNS_OFF)

    def test_copies_that_run_against_the_way_the_path_was_read(self):
        self.assert_left_out(LINE, lambda data: data.update(flip=True), shared.PATH_PATTERN_WRONG_WAY)

    def test_copies_that_do_not_turn_by_the_distance_along_the_arc(self):
        self.assert_left_out(ARC, lambda data: data.update(distance=data["distance"] * 1.01),
                             shared.PATTERN_UNEVEN_ROUND)


if __name__ == "__main__":
    unittest.main()
