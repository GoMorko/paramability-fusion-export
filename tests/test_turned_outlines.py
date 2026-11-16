"""Outlines whose corners turn with an angle size: the range is cut where the outline would cross itself
(sketch_crossings.order_ranges), and a point picked inside an end face moves with one corner, not the centre of all
of them (sketch/inner_pick.py)."""
import copy
import math
import unittest

from tests import context  # noqa: F401
from unittest import mock

from tests.test_translate_crossings import arc, capture_with, line, user
from tests.translator_helpers import assert_schema_ok, load_capture, steps_of

from lib.params import size_table
from lib.params.expressions import evaluate
from lib.sketch_values.motion import Affine, Motion, Terms
from lib.translator import notes, translate
from lib.translator.ranges import kept_ranges
from lib.translator.sketch import sketch_crossings
from lib.translator.sketch.loops import profile_loops
from lib.design_model.values import Quantity


def angle(name, deg):
    return {"name": name, "expression": "%g deg" % deg, "value": math.radians(deg), "display_value": deg,
            "unit": "deg", "comment": "", "is_favorite": False, "kind": "angle", "value_type": "numeric",
            "dependency_parameters": []}


def turned(*legs):
    """`Terms` of a sum of `(coefficient, length size or "", function)` products with the angle `a_deg`."""
    return Terms(0.0, [(k, ([("", leg, 1.0)] if leg else []) + [(f, "a_deg", 1.0)]) for k, leg, f in legs],
                 "Sketch1")


def run(capture, motion):
    params = capture["parameters"]
    table = size_table.build(params["user"], [p["name"] for p in params["user"]], params["model"])
    return translate(capture, size_table=table, motion=motion)


class CrossingCutTest(unittest.TestCase):
    def test_an_outline_that_crosses_itself_in_a_corner_of_the_ranges_cuts_them(self):
        # The right side sits at (p - q) * sin(a): with p at its minimum and q at its maximum it passes the left side.
        corners = [(0, 0), (9.0, 0), (9.0, 5), (-2, 5)]
        capture = capture_with([line(corners[i], corners[(i + 1) % 4], "e%d" % i) for i in range(4)], "p_mm", 14.0)
        capture["parameters"]["user"] += [user("q_mm", 5.0), angle("a_deg", 90.0)]
        side = turned((1.0, "p_mm", "sin"), (-1.0, "q_mm", "sin"))
        result = run(capture, Motion({"1/p0/l0/points.1.0": side, "1/p0/l0/points.2.0": side}))
        sizes = result.recipe.get("sizes", {})
        self.assertEqual((sorted(sizes), result.loose, result.fixed), (["a_deg", "p_mm", "q_mm"], [], []))
        self.assertGreater(sizes["p_mm"]["min"], sizes["q_mm"]["max"])
        self.assertEqual(sorted(c["name"] for c in result.cuts), ["p_mm", "q_mm"])

    def test_a_cut_range_keeps_the_order_inside_it_not_only_at_its_ends_and_middle(self):
        # A check that dips below zero only round p = 12.5, inside the default range 5 to 20 of p (now 10).
        rule = "abs(p_mm - 12.5) - 0.5"
        table = size_table.build([user("p_mm", 10.0)], ["p_mm"], [])
        with mock.patch.object(sketch_crossings, "_checks", lambda *_: [object()]), \
                mock.patch.object(sketch_crossings, "render", lambda *_: Quantity(1.5, rule, ("p_mm",))):
            kept = sketch_crossings.order_ranges(table, [{}], [{}], "Sketch1")
        low, high = kept["p_mm"]
        self.assertTrue(all(evaluate(rule, {"p_mm": low + (high - low) * n / 200}) > 0 for n in range(201)))


# (p, 5) follows p in a quad with fixed corners (0, 0), (10, 0) and (10, 10).
STRAIGHT = {"1/p0/l0/points.3.0": Affine(0.0, {"p_mm": 1.0}, "Sketch1")}


class StraightCrossingTest(unittest.TestCase):
    def test_a_corner_that_follows_a_size_past_a_side_that_stays_cuts_the_range_before_it(self):
        # p is 6 now, range 3 to 12: past 10 the edge back to the origin crosses the side at x = 10.
        result = self.straight()
        self.assertEqual((result.recipe["sizes"]["p_mm"]["min"], result.recipe["sizes"]["p_mm"]["max"]), (3.0, 9.99))
        self.assertEqual([c["name"] for c in result.cuts], ["p_mm"])

    def test_with_a_typed_range_the_size_is_marked_instead_of_cut(self):
        result = self.straight(ranges={"p_mm": (4.0, 12.0)})
        self.assertEqual((result.recipe["sizes"]["p_mm"]["min"], result.recipe["sizes"]["p_mm"]["max"]), (4.0, 12.0))
        self.assertEqual(([c["name"] for c in result.cuts], [f["name"] for f in result.loose]), ([], ["p_mm"]))

    def test_once_the_checks_ran_out_of_time_the_size_is_marked_instead_of_cut(self):
        with mock.patch.object(sketch_crossings, "OUTLINE_CHECK_SECONDS", 0.0):
            result = self.straight()
        self.assertEqual((result.recipe["sizes"]["p_mm"]["min"], result.recipe["sizes"]["p_mm"]["max"]), (3.0, 12.0))
        self.assertEqual(([c["name"] for c in result.cuts], [f["name"] for f in result.loose]), ([], ["p_mm"]))

    def test_the_walks_of_one_translation_check_an_outline_once(self):
        found = kept_ranges.holding_ranges_where
        with mock.patch.object(kept_ranges, "holding_ranges_where", wraps=found) as holding:
            self.straight()
        self.assertEqual(holding.call_count, 1)

    def straight(self, ranges=None):
        corners = [(0, 0), (10, 0), (10, 10), (6, 5)]
        capture = capture_with([line(corners[i], corners[(i + 1) % 4], "e%d" % i) for i in range(4)], "p_mm", 6.0)
        params = capture["parameters"]
        table = size_table.build(params["user"], ["p_mm"], params["model"], ranges=ranges)
        return translate(capture, size_table=table, motion=Motion(dict(STRAIGHT)))

    def test_a_corner_that_follows_a_size_into_an_arc_that_stays_cuts_the_range_where_it_meets_the_arc(self):
        # A notch at (-p, 0) inside a half circle of radius 10 (p 6 now, range 3 to 12): past 10 it crosses the arc.
        a, b = (0, 10), (0, -10)
        curves = [arc(a, (-10, 0), b, (0, 0), "a0", radius=10), line(b, (-6, 0), "e1"), line((-6, 0), a, "e2")]
        capture = capture_with(curves, "p_mm", 6.0)
        result = run(capture, Motion({"1/p0/l0/segments.1.to.0": Affine(0.0, {"p_mm": -1.0}, "Sketch1")}))
        self.assertEqual((result.recipe["sizes"]["p_mm"]["min"], result.recipe["sizes"]["p_mm"]["max"]), (3.0, 9.99))


    def test_a_hole_that_a_following_plate_would_leave_cuts_the_range_before_that(self):
        # A 60 x 40 plate whose right edge follows p (60 now, range 30 to 120) and a round hole 16 wide at x = 30:
        # the plate must stay wider than 38 mm to hold the hole.
        corners = [(0, 0), (60, 0), (60, 40), (0, 40)]
        capture = capture_with([line(corners[i], corners[(i + 1) % 4], "e%d" % i) for i in range(4)], "p_mm", 60.0)
        capture["items"][1]["data"]["profiles"][0]["loops"].append(
            {"outer": False, "curves": [{"kind": "circle", "center": [30, 20], "radius": 8, "entity": "c"}]})
        plate = {"1/p0/l0/width": Affine(0.0, {"p_mm": 1.0}, "Sketch1"),
                 "1/p0/l0/center.0": Affine(0.0, {"p_mm": 0.5}, "Sketch1")}
        result = run(capture, Motion(plate))
        size = result.recipe["sizes"]["p_mm"]
        self.assertEqual((size["min"], size["max"]), (38.01, 120.0))
        self.assertEqual(result.cuts[0]["why"], notes.crosses_reason("Sketch1"))
        capture["items"][1]["data"]["profiles"][0]["loops"][1]["curves"][0].update(center=[10, 20], radius=1.0)
        self.assertEqual(run(capture, Motion(plate)).cuts, [])


def _v_shape(p, q, a, w=3.0):
    """Corners of a V: a leg of length p along x and a leg of length q turned by a, both w wide."""
    c, s = math.cos(math.radians(a)), math.sin(math.radians(a))
    return [(0.0, -w), (p, -w), (p, 0.0), (q * c, q * s), (q * c - w * s, q * s + w * c), (-w * s, w * c)]


def _v_values():
    """The corner formulas of `_v_shape`, by corner and coordinate (a fixed one has none)."""
    return {
        (1, 0): Terms(0.0, [(1.0, [("", "p_mm", 1.0)])], "Sketch1"),
        (2, 0): Terms(0.0, [(1.0, [("", "p_mm", 1.0)])], "Sketch1"),
        (3, 0): turned((1.0, "q_mm", "cos")),
        (3, 1): turned((1.0, "q_mm", "sin")),
        (4, 0): turned((1.0, "q_mm", "cos"), (-3.0, "", "sin")),
        (4, 1): turned((1.0, "q_mm", "sin"), (3.0, "", "cos")),
        (5, 0): turned((-3.0, "", "sin")),
        (5, 1): turned((3.0, "", "cos")),
    }


def _v_capture():
    """A chamfer of the edges around both end faces of an extruded V, picked by points near the end of the leg that
    does not turn, and the motion of the V's corners."""
    capture = copy.deepcopy(load_capture("chamfer_equal"))
    corners = _v_shape(16.0, 9.0, 90.0)
    profile = capture["items"][1]["data"]["profiles"][0]
    profile.update(sketch="Sketch1", sketch_token="s1", loops=[{"outer": True, "curves": [
        line(corners[i], corners[(i + 1) % len(corners)], "e%d" % i) for i in range(len(corners))]}])
    capture["capture"] = 3
    capture["parameters"] = {"user": [user("p_mm", 16.0), user("q_mm", 9.0), angle("a_deg", 90.0)], "model": []}
    capture["target"]["box"] = {"min": [-3.0, -3.0, 0.0], "max": [16.0, 9.0, 10.0]}
    capture["items"][2]["data"]["sets"][0].update(input_kinds=["face"], faces=[
        {"token": "top", "point": [15.0, -1.5, 10.0]}, {"token": "bottom", "point": [15.0, -1.5, 0.0]}])
    outer = profile_loops(profile)[0]
    values, by_corner = {}, _v_values()
    for at, point in enumerate(outer["points"]):
        corner = min(range(len(corners)), key=lambda c: math.dist(corners[c], point))
        for axis in (0, 1):
            if (corner, axis) in by_corner:
                values["1/p0/l0/points.%d.%d" % (at, axis)] = by_corner[(corner, axis)]
    return capture, Motion(values)


class InnerPickTest(unittest.TestCase):
    def test_a_face_picked_near_the_leg_that_does_not_turn_stays_when_the_angle_turns(self):
        capture, motion = _v_capture()
        result = run(capture, motion)
        assert_schema_ok(self, result.recipe)
        self.assertEqual((result.loose, result.fixed), ([], []))
        (step,) = steps_of(result.recipe, "bevel")
        env = {n: s["value"] for n, s in result.recipe["sizes"].items() if "value" in s}
        for point in step["edges"]["faceEdges"]["near"]:
            at = [evaluate(c["expr"], dict(env, a_deg=135.0)) if isinstance(c, dict) else c for c in point]
            self.assertAlmostEqual(math.dist(at[:2], (15.0, -1.5)), 0.0, places=6)

    def test_an_edge_picked_inside_an_end_face_moves_with_the_centre_of_the_corners(self):
        # A six-sided outline that widens evenly both ways with w: its centre stays, its corners move with w / 2.
        # The picked edge comes from another step, so moving with the nearest corner would carry the point off it.
        capture = copy.deepcopy(load_capture("chamfer_equal"))
        corners = [(-10.0, -5.0), (10.0, -5.0), (12.0, 0.0), (10.0, 5.0), (-10.0, 5.0), (-12.0, 0.0)]
        profile = capture["items"][1]["data"]["profiles"][0]
        profile.update(sketch="Sketch1", sketch_token="s1", loops=[{"outer": True, "curves": [
            line(corners[i], corners[(i + 1) % len(corners)], "e%d" % i) for i in range(len(corners))]}])
        capture["capture"] = 3
        capture["parameters"] = {"user": [user("w_mm", 20.0)], "model": []}
        capture["target"]["box"] = {"min": [-12.0, -5.0, 0.0], "max": [12.0, 5.0, 10.0]}
        capture["items"][2]["data"]["sets"][0]["edges"] = [{"token": "t0", "closed": False, "points": [[7.0, 0.0, 10.0]]}]
        values = {}
        for at, point in enumerate(profile_loops(profile)[0]["points"]):
            x = min(corners, key=lambda c: math.dist(c, point))[0]
            side = 1.0 if x > 0 else -1.0
            values["1/p0/l0/points.%d.0" % at] = Terms(x - side * 10.0, [(side * 0.5, [("", "w_mm", 1.0)])], "Sketch1")
        result = run(capture, Motion(values))
        assert_schema_ok(self, result.recipe)
        (step,) = steps_of(result.recipe, "bevel")
        (point,) = step["edges"]["near"]
        at = [evaluate(c["expr"], {"w_mm": 30.0}) if isinstance(c, dict) else c for c in point]
        self.assertAlmostEqual(math.dist(at, (7.0, 0.0, 10.0)), 0.0, places=6)
