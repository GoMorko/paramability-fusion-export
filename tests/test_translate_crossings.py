"""Corners where sketch curves cross follow sizes exactly (sketch_crossings.py, curved.py, outlines.py)."""
import math
import unittest

from tests import context  # noqa: F401
from tests.test_translate_copies import _edges_set, _item
from tests.translator_helpers import assert_schema_ok, load_capture, steps_of

from lib.params import size_table
from lib.sketch_values.motion import Affine, Motion, Stuck
from lib.translator import translate
from lib.translator.outlines import _joined, merge_touching
from lib.translator.sketch_crossings import Sources
from lib.translator.sketch_motion import Anchors, _from_anchors

R = 10.0


def user(name, mm):
    return {"name": name, "expression": "%g mm" % mm, "value": mm / 10.0, "unit": "mm", "kind": "length",
            "value_type": "numeric", "is_favorite": True, "dependency_parameters": []}


def line(a, b, entity):
    return {"kind": "line", "start": list(a), "end": list(b), "entity": entity}


def arc(a, mid, b, center, entity, radius=R):
    return {"kind": "arc", "start": list(a), "end": list(b), "mid": list(mid), "center": list(center),
            "radius": radius, "entity": entity}


def capture_with(curves, name, value):
    capture = load_capture("extrude_plate")
    capture["capture"] = 3
    capture["parameters"] = {"user": [user(name, value)], "model": []}
    profile = capture["items"][1]["data"]["profiles"][0]
    profile.update(sketch="Sketch1", sketch_token="s1", loops=[{"outer": True, "curves": curves}])
    return capture


def run(capture, name, motion, ranges=None):
    table = size_table.build(capture["parameters"]["user"], [name], capture["parameters"]["model"],
                             ranges=ranges)
    return translate(capture, size_table=table, motion=motion)


def expr(value):
    return value["expr"] if isinstance(value, dict) else value


def d_shape(w=10.0):
    """The part of a circle (radius 10, at the origin) right of the line x = -w / 2."""
    x, h = -w / 2, math.sqrt(R * R - w * w / 4)
    return [line((x, -h), (x, h), "cut"), arc((x, h), (R, 0), (x, -h), (0, 0), "round")]


def d_motion():
    """What the probe fits for the D: the crossings move along the circle (stuck); the line moves with w_mm."""
    stuck = Stuck(["w_mm"], "curve", "Sketch1")
    half = Affine(0.0, {"w_mm": -0.5}, "Sketch1")
    return Motion({"1/p0/l0/start.0": half, "1/p0/l0/start.1": stuck, "1/p0/l0/segments.0.to.0": half,
                   "1/p0/l0/segments.0.to.1": stuck, "1/p0/l0/segments.1.to.0": half,
                   "1/p0/l0/segments.1.to.1": stuck, "1/p0/c0.0/offset": Affine(0.0, {"w_mm": 0.5}, "Sketch1")},
                  curves=["1/p0"])


class CrossingTest(unittest.TestCase):
    def test_a_line_crossing_a_circle_writes_the_square_root(self):
        result = run(capture_with(d_shape(), "w_mm", 10.0), "w_mm", d_motion(), {"w_mm": (4.0, 16.0)})
        self.assertEqual((result.fixed, result.loose), ([], []))
        assert_schema_ok(self, result.recipe)
        outer = steps_of(result.recipe, "extrude")[0]["sketch"]["outer"]
        self.assertEqual([expr(c) for c in outer["start"]],
                         ["-0.5 * w_mm", "-(sqrt(-0.25 * (w_mm * w_mm) + 100))"])

    def test_a_crossing_that_disappears_inside_the_range_marks_its_size(self):
        result = run(capture_with(d_shape(), "w_mm", 10.0), "w_mm", d_motion())  # w_mm reaches 20: the line only touches
        self.assertEqual([f["name"] for f in result.loose], ["w_mm"])
        self.assertIn("along a curve", result.loose[0]["reason"])

    def test_two_circles_cross_where_their_offset_puts_them(self):
        off, half = 4.0, math.sqrt(R * R - 4.0)
        lens = [arc((2, -half), (off - R, 0), (2, half), (off, 0), "moved"),
                arc((2, half), (R, 0), (2, -half), (0, 0), "still")]
        stuck = Stuck(["off_mm"], "curve", "Sketch1")
        motion = Motion({"1/p0/l0/start.0": Affine(0.0, {"off_mm": 0.5}), "1/p0/l0/start.1": stuck,
                         "1/p0/l0/segments.0.through.0": Affine(-R, {"off_mm": 1.0}),
                         "1/p0/l0/segments.0.to.0": Affine(0.0, {"off_mm": 0.5}), "1/p0/l0/segments.0.to.1": stuck,
                         "1/p0/l0/segments.1.to.0": Affine(0.0, {"off_mm": 0.5}), "1/p0/l0/segments.1.to.1": stuck,
                         "1/p0/c0.0/center.0": Affine(0.0, {"off_mm": 1.0})}, curves=["1/p0"])
        result = run(capture_with(lens, "off_mm", off), "off_mm", motion)
        self.assertEqual((result.fixed, result.loose), ([], []))
        start = steps_of(result.recipe, "extrude")[0]["sketch"]["outer"]["start"]
        self.assertEqual(expr(start[1]), "-(sqrt(-0.25 * (off_mm * off_mm) + 100))")

    def test_without_measured_curves_a_stuck_crossing_still_marks_its_size(self):
        motion = d_motion()
        motion.curves = set()
        result = run(capture_with(d_shape(), "w_mm", 10.0), "w_mm", motion, {"w_mm": (4.0, 16.0)})
        self.assertEqual([f["name"] for f in result.loose], ["w_mm"])

    def test_a_line_that_turns_cannot_carry_its_crossings(self):
        motion = d_motion()
        motion.values["1/p0/c0.0/turn"] = Affine(0.0, {"w_mm": 1.0}, "Sketch1")
        result = run(capture_with(d_shape(), "w_mm", 10.0), "w_mm", motion, {"w_mm": (4.0, 16.0)})
        self.assertEqual([f["name"] for f in result.loose], ["w_mm"])

    def fillet_at(self, point):
        capture = capture_with(d_shape(), "w_mm", 10.0)
        capture["items"].append(_item(2, "Fillet1", "FilletFeature", {
            "sets": [_edges_set("constant", [point], radius=1.0, continuity="tangent")]}))
        return run(capture, "w_mm", d_motion(), {"w_mm": (4.0, 16.0)})

    def test_a_pick_on_an_arc_that_changes_shape_marks_its_sizes(self):
        a = R / math.sqrt(2)
        result = self.fillet_at([a, a, 10.0])
        self.assertEqual([f["name"] for f in result.loose], ["w_mm"])
        self.assertIn("Fillet1", result.loose[0]["reason"])

    def test_a_pick_at_the_middle_of_that_arc_stays(self):
        result = self.fillet_at([R, 0.0, 10.0])
        self.assertEqual((result.fixed, result.loose), ([], []))


class CornerWithThreeCurvesTest(unittest.TestCase):
    """Three sketch lines end at the origin; the first one cannot follow its size."""
    STUCK = Stuck(["w_mm"], "curve", "S")

    def sources(self, curves):
        return Sources(lambda key, number: self.STUCK if key == "p/c0.0/offset" else Affine(number, {}, "S"),
                       [("p", {"loops": [{"curves": curves}]})], "S")

    def test_a_pair_of_curves_that_can_follow_gives_the_corner(self):
        curves = [line((5, 0), (0, 0), "a"), line((0, 0), (0, 5), "b"), line((3, 3), (0, 0), "c")]
        self.assertIsInstance(self.sources(curves).point((0, 0)), tuple)

    def test_the_cause_of_a_stuck_corner_stays_on_the_anchor_value(self):
        sources = self.sources([line((5, 0), (0, 0), "a"), line((0, 0), (0, 5), "b")])
        loop = {"kind": "polygon", "points": [[0, 0], [5, 0], [0, 5]]}
        raw = _from_anchors(loop, Anchors("S"), "S", sources)
        self.assertEqual(raw["points"][0], [self.STUCK, self.STUCK])


class MergedOutlineTest(unittest.TestCase):
    FRAME = {"origin": [0, 0, 0], "x": [1, 0, 0], "y": [0, 1, 0], "z": [0, 0, 1]}

    def profile(self, curves):
        return {"sketch": "S", "frame": self.FRAME, "space": "sketch", "loops": [{"outer": True, "curves": curves}]}

    def test_pieces_of_one_sketch_line_are_joined_back(self):
        left = [line((0, 0), (5, 0), "bottom"), line((5, 0), (5, 4), "mid"), line((5, 4), (0, 4), "top"),
                line((0, 4), (0, 0), "west")]
        right = [line((5, 0), (10, 0), "bottom"), line((10, 0), (10, 4), "east"), line((10, 4), (5, 4), "top"),
                 line((5, 4), (5, 0), "mid")]
        (merged,) = merge_touching([self.profile(left), self.profile(right)])
        self.assertEqual(len(merged["loops"][0]["curves"]), 4)

    def test_pieces_of_a_line_are_joined_in_a_loop_of_three_curves(self):
        loop = [line((0, -3), (0, 0), "cut"), line((0, 0), (0, 3), "cut"), arc((0, 3), (3, 0), (0, -3), (0, 0), "round", 3)]
        joined = _joined(loop)
        self.assertEqual([c["kind"] for c in joined], ["line", "arc"])
        self.assertEqual((joined[0]["start"], joined[0]["end"]), ([0, -3], [0, 3]))

    def test_arcs_of_one_circle_become_that_circle(self):
        h = math.sqrt(R * R - 25)
        cap = [line((5, -h), (5, h), "cut"), arc((5, h), (R, 0), (5, -h), (0, 0), "round")]
        rest = [line((5, -h), (5, h), "cut"), arc((5, h), (-R, 0), (5, -h), (0, 0), "round")]
        (merged,) = merge_touching([self.profile(cap), self.profile(rest)])
        self.assertEqual([c["kind"] for c in merged["loops"][0]["curves"]], ["circle"])


if __name__ == "__main__":
    unittest.main()
