"""Outlines with free curves: a spline edge is written as recipe spline segments through points that keep the app's
curve within a small distance of the Fusion curve."""
import math
import unittest
from unittest import mock

from tests import context  # noqa: F401
from tests.translator_helpers import assert_schema_ok, load_capture, steps_of

from lib.geometry.plane2d import to_segment
from lib.params import size_table
from lib.probe import build
from lib.translator import translate
from lib.translator.result import Refusal
from lib.geometry import spline_fit
from lib.translator.sketch import loops

EDGE = "extrude_spline_edge"
EXTRUDE = 1


def profile_of(capture):
    return capture["items"][EXTRUDE]["data"]["profiles"][0]


def curves_of(capture):
    return profile_of(capture)["loops"][0]["curves"]


def spline_of(capture):
    return next(c for c in curves_of(capture) if c["kind"] == "other")


def reason_of(capture):
    result = translate(capture)
    assert result.recipe is None, "the extrude was copied"
    assert result.refusal["index"] == EXTRUDE
    return result.refusal["reason"]


def segments_of(result):
    return steps_of(result.recipe, "extrude")[0]["sketch"]["outer"]["segments"]


class SplineCopyTest(unittest.TestCase):
    def test_a_spline_edge_is_written_as_spline_segments_the_schema_accepts(self):
        result = translate(load_capture(EDGE))
        self.assertIsNone(result.refusal)
        assert_schema_ok(self, result.recipe)
        kinds = [s["kind"] for s in segments_of(result)]
        self.assertEqual((kinds.count("spline"), kinds.count("line")), (1, 3))

    def test_the_apps_curve_through_the_written_points_stays_within_the_stated_tolerance(self):
        capture = load_capture(EDGE)
        segments = segments_of(translate(capture))
        at = next(i for i, s in enumerate(segments) if s["kind"] == "spline")
        start = segments[at - 1]["to"]
        written = [start] + segments[at]["through"] + [segments[at]["to"]]
        curve = spline_fit.interpolate(written)
        samples = spline_of(capture)["samples"]
        worst = max(min(min(_gap(p, curve.at(k / 400.0), curve.at((k + 1) / 400.0)) for k in range(400)), 1.0)
                    for p in samples)
        self.assertLessEqual(worst, spline_fit.TOLERANCE_MM)

    def test_a_curve_drawn_the_other_way_round_gives_the_same_curve(self):
        capture = load_capture(EDGE)
        curve = spline_of(capture)
        curve["start"], curve["end"] = curve["end"], curve["start"]
        curve["samples"] = list(reversed(curve["samples"]))
        result = translate(capture)
        self.assertIsNone(result.refusal)
        self.assertEqual([s["kind"] for s in segments_of(result)].count("spline"), 1)

    def test_a_loop_that_is_one_closed_spline_is_a_profile_of_one_segment(self):
        result = translate(load_capture("extrude_spline"))
        outer = steps_of(result.recipe, "extrude")[0]["sketch"]["outer"]
        self.assertEqual((outer["kind"], len(outer["segments"]), outer["segments"][0]["to"]), ("profile", 1, outer["start"]))

    def test_a_curve_that_needs_more_than_one_segment_is_split_at_the_cap(self):
        capture = load_capture(EDGE)
        curve = spline_of(capture)
        curve["samples"] = [[x, 20 + (y - 20) * 1.25] for x, y in curve["samples"]]
        with mock.patch.object(spline_fit, "MAX_THROUGH", 3):
            segments = [s for s in segments_of(translate(capture)) if s["kind"] == "spline"]
        self.assertGreater(len(segments), 1)
        self.assertTrue(all(len(s["through"]) <= 3 for s in segments))


def _gap(p, a, b):
    return to_segment(p, a, b)


class SplineRefusalTest(unittest.TestCase):
    def test_an_open_spline_outline_is_not_closed(self):
        self.assertIn("not closed", translate_reason("extrude_open_spline"))

    def test_a_curve_without_samples_or_cut_short_is_not_copied(self):
        for edit in (lambda c: c.update(samples=[]), lambda c: c.update(truncated=True)):
            capture = load_capture(EDGE)
            edit(spline_of(capture))
            self.assertIn("could not be read closely enough", reason_of(capture))

    def test_an_outline_past_the_point_cap_is_refused(self):
        capture = load_capture(EDGE)
        steps = 995
        run = [{"kind": "line", "start": [30.0 * i / steps, 0.0], "end": [30.0 * (i + 1) / steps, 0.0]}
               for i in range(steps)]
        curves_of(capture)[0:1] = run
        self.assertIn("too many", reason_of(capture))

    def test_a_spline_counts_its_points_toward_the_cap(self):
        segments = [{"kind": "line", "to": [1, 0]}, {"kind": "spline", "through": [[2, 1], [3, 1]], "to": [4, 0]}]
        self.assertEqual(loops.segments_cost(segments), 4)


def translate_reason(name):
    result = translate(load_capture(name))
    assert result.recipe is None
    return result.refusal["reason"]


class FlipTest(unittest.TestCase):
    def test_a_reversed_placement_mirrors_every_point_of_a_spline(self):
        loop = {"kind": "profile", "start": [0, 0], "segments": [
            {"kind": "spline", "through": [[2, 1], [3, 2]], "to": [5, 0]}, {"kind": "line", "to": [0, 0]}]}
        flipped = loops.flip_y(loop)
        self.assertEqual(flipped["segments"][0]["through"], [[2, -1], [3, -2]])
        self.assertEqual(loops.flip_y(flipped), loop)


class MergedProfilesTest(unittest.TestCase):
    def test_two_profiles_that_share_a_spline_edge_make_one_outline(self):
        shared = [[10 + 3 * math.sin(math.pi * y / 20), float(y)] for y in range(0, 21)]
        a = {"kind": "other", "type": "NurbsCurve3D", "entity": "s", "start": shared[0], "end": shared[-1],
             "mid": shared[10], "samples": shared}
        b = dict(a, start=shared[-1], end=shared[0], samples=list(reversed(shared)))

        def line(p, q, entity):
            return {"kind": "line", "start": p, "end": q, "entity": entity}

        frame = {"origin": [0, 0, 0], "x": [1, 0, 0], "y": [0, 1, 0], "z": [0, 0, 1]}
        left = {"sketch": "Sketch1", "frame": frame, "loops": [{"outer": True, "curves": [
            line([0, 0], shared[0], "l1"), a, line(shared[-1], [0, 20], "l2"), line([0, 20], [0, 0], "l3")]}]}
        right = {"sketch": "Sketch1", "frame": frame, "loops": [{"outer": True, "curves": [
            line(shared[0], [20, 0], "r1"), line([20, 0], [20, 20], "r2"), line([20, 20], shared[-1], "r3"), b]}]}
        capture = load_capture(EDGE)
        capture["items"][EXTRUDE]["data"]["profiles"] = [left, right]
        result = translate(capture)
        self.assertIsNone(result.refusal)
        extrudes = steps_of(result.recipe, "extrude")
        self.assertEqual(len(extrudes), 1)
        self.assertNotIn("spline", [s["kind"] for s in extrudes[0]["sketch"]["outer"].get("segments", [])])


class SplineSizesTest(unittest.TestCase):
    def run_sized(self, edit=None):
        capture = load_capture(EDGE)
        if edit:
            edit(capture)
        params = capture["parameters"]
        table = size_table.build(params["user"], [p["name"] for p in params["user"]], params["model"], "mm")
        motion = build.build(capture, table, [])
        return translate(capture, size_table=table, motion=motion)

    def test_a_size_that_moves_a_sketch_with_a_spline_is_left_out_with_that_reason(self):
        result = self.run_sized()
        self.assertEqual([d["name"] for d in result.dropped], ["width_mm"])
        self.assertIn("Sketch1", result.dropped[0]["reason"])
        self.assertEqual(list(result.recipe["sizes"]), ["height_mm"])

    def test_a_size_that_also_drives_a_formula_stays_free_with_a_warning(self):
        def drive_height(capture):
            ref = capture["items"][EXTRUDE]["data"]["params"]["side_one.distance"]
            ref.update(expression="width_mm / 4", value=7.5)
            capture["items"][EXTRUDE]["data"].update(end_offset=7.5)
            capture["items"][EXTRUDE]["data"]["side_one"]["distance"] = 7.5
            for p in capture["parameters"]["model"]:
                if p["name"] == "d2":
                    p.update(expression="width_mm / 4", dependency_parameters=["width_mm"])
        result = self.run_sized(drive_height)
        self.assertEqual([m["name"] for m in result.loose], ["width_mm"])
        self.assertIn("Sketch1", result.loose[0]["reason"])
        self.assertIn("width_mm", result.recipe["sizes"])


class LoopOfTest(unittest.TestCase):
    def test_a_free_curve_without_samples_is_a_refusal(self):
        refusal = loops.loop_of([{"kind": "other", "type": "NurbsCurve3D", "start": [0, 0], "end": [0, 0], "samples": []}])
        self.assertIsInstance(refusal, Refusal)
