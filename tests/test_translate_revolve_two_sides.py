"""Revolves to two sides with two angles, and intersect revolves of several outlines.

The fixture `revolve_two_sides` turns an outline at x 5 to 10 on the XY plane about the Y axis, by 30 degrees (angle
one) and 60 degrees (angle two). A face at the angle `a` about +Y (right hand rule) has the outward normal
(sin a, 0, cos a) when the material lies at larger angles, and the opposite when it lies at smaller ones.
"""
import copy
import math
import unittest

from tests import context  # noqa: F401
from tests.test_translate_revolve_hole import sweep_midpoint, variant
from tests.test_translate_sized import TICKED, on_fixture, param, resolved, run
from tests.translator_helpers import assert_schema_ok, steps_of

from lib.capture_model import gap_hints


def lower_end(a):
    """Outward normal of the start face at `a` degrees when the material lies at larger angles."""
    r = math.radians(a)
    return [math.sin(r), 0.0, math.cos(r)]


def upper_end(a):
    return [-c for c in lower_end(a)]


# The material from -60 to 30 degrees (side one turns the right hand way), and from -30 to 60 (the other way).
SIDE_ONE_RIGHT_HAND = (lower_end(-60), upper_end(30))
SIDE_ONE_OTHER_WAY = (lower_end(-30), upper_end(60))


def two_sides(normal, one=30.0, two=60.0, **more):
    def edit(item):
        item["data"].update(start_face_normal=normal, **more)
        item["data"]["extent"].update(angle_one_deg=one, angle_two_deg=two)
    return variant("revolve_two_sides", edit)


def sized(normal, params, one=30.0, two=60.0, **more):
    def edit(data):
        data.update(start_face_normal=normal, params=params, **more)
        data["extent"].update(angle_one_deg=one, angle_two_deg=two)
    capture, ticked = on_fixture("revolve_two_sides", edit, TICKED + ["turn_deg"])
    result, table = run(capture, ticked)
    assert result.recipe, result.refusal
    assert_schema_ok(unittest.TestCase(), result.recipe)
    return result, table


def fixed_names(result):
    """The sizes that a copied step reads and cannot follow."""
    return {entry["name"] for entry in result.fixed + result.dropped if entry.get("used", True)}


class TwoSidesTest(unittest.TestCase):
    def test_the_start_face_tells_which_side_each_angle_turns_to(self):
        for normals, below in ((SIDE_ONE_RIGHT_HAND, False), (SIDE_ONE_OTHER_WAY, True)):
            for normal in normals:
                result = two_sides(normal)
                self.assertIsNotNone(result.recipe, result.refusal)
                (step,) = steps_of(result.recipe, "revolve")
                self.assertEqual((step["angleDeg"], step["axis"]["dir"], step["combine"]), (90, [0, 1], "new"))
                # The middle of the turn is at -15 degrees (z above 0) or at +15 degrees (z below 0).
                middle = sweep_midpoint(step)
                self.assertAlmostEqual(abs(middle[2]), 7.5 * math.sin(math.radians(15)), places=6)
                self.assertEqual(middle[2] < 0, below)
                assert_schema_ok(self, result.recipe)

    def test_a_start_face_that_fits_neither_turn_is_left_out(self):
        result = two_sides([0.0, 0.0, 1.0])
        self.assertIsNone(result.recipe)
        self.assertEqual((result.refusal["index"], result.refusal["type"]), (1, "RevolveFeature"))

    def test_a_quarter_turn_that_does_not_tell_the_side_is_left_out(self):
        # From -30 to 90 and from -90 to 30 both have a face with the normal -X.
        result = two_sides([-1.0, 0.0, 0.0], one=90.0, two=30.0)
        self.assertIsNone(result.recipe)
        self.assertEqual(result.refusal_cause, gap_hints.REVOLVE_SIDES)

    def test_two_sides_that_make_a_full_turn_are_a_full_revolve(self):
        result = two_sides(None, one=300.0, two=60.0)
        (step,) = steps_of(result.recipe, "revolve")
        self.assertNotIn("angleDeg", step)

    def test_both_angles_follow_sizes_with_a_move_that_turns_the_revolve_back(self):
        result, table = sized(SIDE_ONE_RIGHT_HAND[0], {
            "extent.angle_one_deg": param("d4", "turn_deg - 60 deg", 30.0),
            "extent.angle_two_deg": param("d5", "turn_deg - 30 deg", 60.0)})
        self.assertEqual(fixed_names(result), set())
        (tool,) = result.recipe["features"]
        self.assertEqual((tool["kind"], tool["combine"]), ("toolBody", "new"))
        revolve, move = resolved(result.recipe, table)["features"][0]["features"]
        self.assertEqual((revolve["angleDeg"], revolve["sketch"]["on"]["normal"]), (90, [0, 0, 1]))
        self.assertEqual(move["turn"], {"axisPoint": [0, 0, 0], "axis": [0, -1, 0], "angleDeg": 60})
        self.assertEqual(tool["features"][1]["turn"]["angleDeg"], {"expr": "turn_deg - 30"})

    def test_equal_angles_keep_their_numbers(self):
        result, _ = sized(lower_end(-45), {"extent.angle_one_deg": param("d4", "turn_deg / 2", 45.0),
                                           "extent.angle_two_deg": param("d5", "turn_deg / 2", 45.0)},
                          one=45.0, two=45.0)
        self.assertEqual(fixed_names(result), {"turn_deg"})
        (step,) = steps_of(result.recipe, "revolve")
        self.assertEqual(step["angleDeg"], 90)

    def test_angles_that_may_pass_a_full_turn_keep_their_numbers(self):
        result, _ = sized(lower_end(-225), {"extent.angle_one_deg": param("d4", "turn_deg - 60 deg", 30.0),
                                            "extent.angle_two_deg": param("d5", "turn_deg * 2.5", 225.0)},
                          two=225.0)
        self.assertEqual(fixed_names(result), {"turn_deg"})
        (step,) = steps_of(result.recipe, "revolve")
        self.assertEqual(step["angleDeg"], 255)

    def test_the_angle_back_about_a_projected_axis_keeps_its_number(self):
        result, table = sized(SIDE_ONE_RIGHT_HAND[0], {
            "extent.angle_one_deg": param("d4", "turn_deg - 60 deg", 30.0),
            "extent.angle_two_deg": param("d5", "holes_count * 20 deg", 60.0)}, project_axis=True)
        self.assertEqual(fixed_names(result), {"holes_count"})
        (step,) = resolved(result.recipe, table)["features"]
        self.assertEqual((step["kind"], step["angleDeg"]), ("revolve", 90))
        self.assertIn("turn_deg", result.recipe["sizes"])


class IntersectTest(unittest.TestCase):
    def test_several_outlines_intersect_as_one_tool(self):
        def edit(item):
            item["data"]["operation"] = "intersect"
            item["data"]["start_face_normal"] = [-c for c in item["data"]["start_face_normal"]]
            item["data"]["profiles"].append(copy.deepcopy(item["data"]["profiles"][0]))
        result = variant("revolve_cut_quarter", edit)
        self.assertIsNotNone(result.recipe, result.refusal)
        tool = result.recipe["features"][-1]
        self.assertEqual((tool["kind"], tool["combine"]), ("toolBody", "intersect"))
        self.assertEqual([(s["kind"], s["combine"]) for s in tool["features"]],
                         [("revolve", "new"), ("revolve", "add")])
        assert_schema_ok(self, result.recipe)


if __name__ == "__main__":
    unittest.main()
