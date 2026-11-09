"""Sketch text: its outlines are copied by extrudes and embosses like any other outline."""
import unittest

from tests import context  # noqa: F401
from tests.translator_helpers import assert_schema_ok, load_capture, steps_of

from lib.params import size_table
from lib.probe import build
from lib.translator import loops, translate

EMBOSS = "emboss_text"
EXTRUDE = "extrude_text"


def step_of(capture, kind="EmbossFeature"):
    return next(i for i in capture["items"] if i["type"] == kind)


def reason_of(capture, kind="EmbossFeature"):
    result = translate(capture)
    assert result.recipe is None, "the text was copied"
    assert result.refusal["index"] == step_of(capture, kind)["index"]
    return result.refusal["reason"]


def square(x, y, size):
    corners = [(x, y), (x + size, y), (x + size, y + size), (x, y + size)]
    return [{"kind": "line", "start": list(a), "end": list(b)} for a, b in zip(corners, corners[1:] + corners[:1])]


class TextCopyTest(unittest.TestCase):
    def test_an_emboss_of_text_adds_one_step_per_outer_outline_and_keeps_the_hole(self):
        result = translate(load_capture(EMBOSS))
        self.assertIsNone(result.refusal)
        assert_schema_ok(self, result.recipe)
        lid, letter_o, letter_i = steps_of(result.recipe, "extrude")
        self.assertEqual((letter_o["combine"], letter_i["combine"], letter_o["distance"]), ("add", "add", 1.0))
        self.assertEqual(len(letter_o["sketch"]["inner"]), 1)
        self.assertEqual(letter_o["sketch"]["on"]["origin"], [0.0, 0.0, 4.0])
        self.assertNotIn("inner", letter_i["sketch"])

    def test_an_extrude_of_text_makes_a_body_and_joins_the_rest_to_it(self):
        result = translate(load_capture(EXTRUDE))
        self.assertIsNone(result.refusal)
        assert_schema_ok(self, result.recipe)
        self.assertEqual([s["combine"] for s in steps_of(result.recipe, "extrude")], ["new", "add"])

    def test_a_text_that_sinks_into_the_part_cuts(self):
        capture = load_capture(EMBOSS)
        data = step_of(capture)["data"]
        data.update(depth=-1.0, volume_after=data["volume_before"] - sum(data["areas"]), end_offset=-1.0)
        data["params"]["depth"].update(value=-1.0, expression="-raise_mm")
        result = translate(capture)
        self.assertEqual([s["combine"] for s in steps_of(result.recipe, "extrude")[1:]], ["cut", "cut"])


class TextRefusalTest(unittest.TestCase):
    def test_each_problem_a_text_can_have_gets_its_own_reason(self):
        reasons = set()
        for problem in ("too_many", "open", "space", "unread", "foreign"):
            capture = load_capture(EXTRUDE)
            step_of(capture, "ExtrudeFeature")["data"]["profiles"] = [
                {"text": True, "sketch": "Sketch2", "problem": problem}]
            reasons.add(reason_of(capture, "ExtrudeFeature"))
        self.assertEqual(len(reasons), 4)

    def test_an_emboss_whose_measured_volume_is_not_the_outline_area_times_the_depth(self):
        capture = load_capture(EMBOSS)
        data = step_of(capture)["data"]
        data["volume_after"] = data["volume_before"] + 0.5 * sum(data["areas"])
        self.assertIn("does not match", reason_of(capture))

    def test_a_text_outline_past_the_point_cap_is_refused_as_text(self):
        capture = load_capture(EMBOSS)
        outer = step_of(capture)["data"]["profiles"][1]["loops"][0]
        steps = 1001
        outer["curves"] = [{"kind": "line", "start": [20.0 + 6.0 * i / steps, 0.0], "end": [20.0 + 6.0 * (i + 1) / steps, 0.0]}
                           for i in range(steps)] + [
            {"kind": "line", "start": [26.0, 0.0], "end": [26.0, 20.0]},
            {"kind": "line", "start": [26.0, 20.0], "end": [20.0, 20.0]},
            {"kind": "line", "start": [20.0, 20.0], "end": [20.0, 0.0]}]
        self.assertEqual(reason_of(capture), loops.TEXT_TOO_BIG)

    def test_a_text_with_more_holes_than_the_cap_is_refused_as_text(self):
        capture = load_capture(EMBOSS)
        profile = step_of(capture)["data"]["profiles"][1]
        profile["loops"] += [{"outer": False, "curves": square(0.1 * n, 1.0, 0.05)} for n in range(loops.MAX_INNER_LOOPS + 1)]
        self.assertEqual(reason_of(capture), loops.TEXT_TOO_BIG)

    def test_a_text_that_is_moved_on_its_face_is_still_refused(self):
        capture = load_capture(EMBOSS)
        step_of(capture)["data"]["offset_x"] = 2.0
        self.assertIn("moved or turned", reason_of(capture))


class TextSizesTest(unittest.TestCase):
    def test_a_size_that_moves_the_sketch_of_a_text_is_left_out_with_that_reason(self):
        capture = load_capture(EMBOSS)
        params = capture["parameters"]
        table = size_table.build(params["user"], [p["name"] for p in params["user"]], params["model"], "mm")
        result = translate(capture, size_table=table, motion=build.build(capture, table, []))
        self.assertEqual([d["name"] for d in result.dropped], ["margin_mm"])
        self.assertIn("Sketch2", result.dropped[0]["reason"])
        self.assertEqual(sorted(result.recipe["sizes"]), ["lid_mm", "raise_mm"])
