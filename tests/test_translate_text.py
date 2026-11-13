"""Sketch text: its outlines are copied by extrudes and embosses like any other outline."""
import time
import unittest
from copy import deepcopy

from tests import context  # noqa: F401
from tests.translator_helpers import assert_schema_ok, left_out, load_capture, steps_of, stopped

from lib.geometry import text_outlines
from lib.params import size_table
from lib.probe import build
from lib.translator.sketch import loops, spline_fit
from lib.translator import translate

EMBOSS = "emboss_text"
EXTRUDE = "extrude_text"


def step_of(capture, kind="EmbossFeature"):
    return next(i for i in capture["items"] if i["type"] == kind)


def reason_of(capture, kind="EmbossFeature", missing=left_out):
    """Why the text step is not copied. `missing` is `left_out` when the copy goes on without it, `stopped` when the
    copy stops there."""
    found = missing(translate(capture))
    assert found is not None, "the text was copied"
    assert found["index"] == step_of(capture, kind)["index"]
    return found["reason"]


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

    def test_an_emboss_of_text_whose_strokes_overlap_is_refused_by_the_volume_check(self):
        capture = load_capture(EMBOSS)
        data = step_of(capture)["data"]
        data["volume_after"] = data["volume_before"] + (sum(data["areas"]) - 5.0) * data["depth"]
        self.assertIn("does not match", reason_of(capture))

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
        for problem in ("too_many", "open", "overlap", "space", "unread", "foreign"):
            capture = load_capture(EXTRUDE)
            step_of(capture, "ExtrudeFeature")["data"]["profiles"] = [
                {"text": True, "sketch": "Sketch2", "problem": problem}]
            reasons.add(reason_of(capture, "ExtrudeFeature", stopped))
        self.assertEqual(len(reasons), 5)

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

    def with_height(self, expression, user_name, maker, link):
        """The emboss capture plus a height parameter `d9` reading `expression`. `maker` is its created_by; `link`
        edits the text record (how the reader tied the text to the parameter)."""
        capture = load_capture(EMBOSS)
        params = capture["parameters"]
        params["user"].append(dict(params["user"][0], name=user_name, expression="5 mm", value=0.5, display_value=5.0))
        params["model"].append({"name": "d9", "expression": expression, "value": 0.5, "unit": "mm", "kind": "derived",
                                "role": "", "dependency_parameters": [user_name.split()[0]], "created_by": maker})
        for profile in step_of(capture)["data"]["profiles"]:
            link(profile)
        table = size_table.build(params["user"], [p["name"] for p in params["user"]], params["model"], "mm")
        return translate(capture, size_table=table, motion=build.build(capture, table, []))

    def assert_text_size_marked(self, result, name):
        marked = {d["name"]: d["reason"] for d in result.dropped}
        marked.update({d["name"]: d["reason"] for d in result.loose})
        self.assertIn("Sketch2", marked.get(name, ""))

    def test_a_size_behind_the_text_height_is_left_out_with_the_sketch_named(self):
        other = {"kind": "other", "token": "t", "name": "", "sketch": "", "component": ""}
        for link in (lambda p: p.update(text_params=["d9"]), lambda p: p.update(text_params_unknown=True)):
            result = self.with_height("text_h", "text_h", other, link)
            self.assert_text_size_marked(result, "text_h")
            self.assertNotIn("text_h", result.recipe["sizes"])

    def test_a_size_behind_both_the_text_height_and_the_depth_stays_free_with_a_mark(self):
        other = {"kind": "other", "token": "t", "name": "", "sketch": "", "component": ""}
        result = self.with_height("raise_mm * 5", "text_h", other, lambda p: p.update(text_params=["d9"]))
        self.assertIn("raise_mm", result.recipe["sizes"])
        self.assert_text_size_marked(result, "raise_mm")

    def test_a_height_parameter_made_by_the_text_needs_no_record_on_the_outlines(self):
        made = {"kind": "sketchText", "token": "t", "name": "", "sketch": "Sketch2", "component": ""}
        result = self.with_height("raise_mm * 5", "text_h", made, lambda p: None)
        self.assert_text_size_marked(result, "raise_mm")


def segments(points):
    return [{"kind": "line", "start": list(a), "end": list(b)} for a, b in zip(points, points[1:] + points[:1])]


class TextSortTest(unittest.TestCase):
    def test_an_outer_outline_keeps_the_hole_inside_it(self):
        found = text_outlines.outlines_of(square(0, 0, 10) + square(3, 3, 4))
        self.assertEqual(len(found), 1)
        self.assertEqual([loop["outer"] for loop in found[0]["loops"]], [True, False])
        self.assertEqual(found[0]["area"], 84.0)

    def test_a_dot_over_a_stem_is_two_outlines(self):
        found = text_outlines.outlines_of(square(0, 0, 4) + square(0, 6, 4))
        self.assertEqual([len(o["loops"]) for o in found], [1, 1])

    def test_loops_that_touch_at_a_corner_are_not_overlapping(self):
        found = text_outlines.outlines_of(square(0, 0, 4) + square(4, 4, 4))
        self.assertIsInstance(found, list)
        self.assertEqual(len(found), 2)

    def test_two_overlapping_strokes_are_not_sorted(self):
        bar = segments([(0, 0), (20, 0), (20, 5), (0, 5)])
        stem = segments([(8, 1), (12, 1), (12, 12), (8, 12)])
        self.assertEqual(text_outlines.outlines_of(bar + stem), text_outlines.OVERLAP)

    def test_a_text_with_overlapping_strokes_is_refused_for_that_reason(self):
        capture = load_capture(EXTRUDE)
        step_of(capture, "ExtrudeFeature")["data"]["profiles"] = [
            {"text": True, "sketch": "Sketch2", "problem": text_outlines.OVERLAP}]
        self.assertEqual(reason_of(capture, "ExtrudeFeature", stopped), loops.TEXT_PROBLEMS["overlap"])

    def test_two_hundred_outlines_are_sorted_fast(self):
        curves = []
        for n in range(200):
            curves += square(12.0 * n, 0, 10) + square(12.0 * n + 3, 3, 4)
        started = time.time()
        found = text_outlines.outlines_of(curves)
        self.assertLess(time.time() - started, 2.0)
        self.assertEqual(len(found), 200)
        self.assertTrue(all(len(o["loops"]) == 2 for o in found))

    def test_two_hundred_nested_outlines_in_one_row_are_sorted_fast(self):
        curves = []
        for n in range(100):
            curves += square(0.1 * n, 0.1 * n, 100 - 0.2 * n)
        started = time.time()
        found = text_outlines.outlines_of(curves)
        self.assertLess(time.time() - started, 2.0)
        self.assertEqual(len(found), 50)


def moved(node, dx):
    """`node` (a profile record) with every coordinate moved along x."""
    if isinstance(node, dict):
        return {key: [[p[0] + dx, p[1]] for p in value] if key == "samples"
                else [value[0] + dx, value[1]] if key in ("start", "end", "mid", "center") else moved(value, dx)
                for key, value in node.items()}
    if isinstance(node, list):
        return [moved(value, dx) for value in node]
    return node


class TextSplineSpeedTest(unittest.TestCase):
    def test_two_hundred_letter_outlines_with_curves_translate_fast(self):
        capture = load_capture(EMBOSS)
        data = step_of(capture)["data"]
        profiles, areas = data["profiles"], data["areas"]
        data["profiles"] = [moved(profile, 30.0 * n) for n in range(100) for profile in profiles]
        data["areas"] = [area for _ in range(100) for area in areas]
        data["volume_after"] = data["volume_before"] + sum(data["areas"]) * abs(data["depth"])
        self.assertEqual(len(data["profiles"]), 200)
        spline_fit._fit.cache_clear()
        started = time.time()
        result = translate(deepcopy(capture))
        self.assertLess(time.time() - started, 5.0)
        self.assertIsNone(result.refusal)
        self.assertEqual(len(steps_of(result.recipe, "extrude")), 201)
