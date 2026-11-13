"""Loft through two outlines with free ends: copied as a ruled loft; each case it cannot copy is left out as a gap."""
import math
import unittest

from tests import context  # noqa: F401
from tests.test_translate_sketch_motion import motion_of, run
from tests.translator_helpers import assert_schema_ok, left_out, load_capture, steps_of, stopped, translate, verdict_of

from lib.translator import loft

SQUARES = "loft_two_squares"
ROUND_TO_SQUARE = "loft_circle_to_square"
TUBE = "loft_tube"
PLATE = "loft_on_plate"
SIZES = ["base_mm", "top_mm", "height_mm"]


def loft_data(capture):
    return next(i for i in capture["items"] if i["type"] == "LoftFeature")["data"]


def edited(name, edit):
    capture = load_capture(name)
    edit(loft_data(capture), capture)
    return translate(capture)


def reason_of(result):
    assert left_out(result) is not None, "the loft was copied"
    return left_out(result)["reason"]


def circle_hole(center, radius, tag):
    return {"outer": False, "curves": [{"kind": "circle", "center": center, "radius": radius, "entity": tag}]}


class LoftCopyTest(unittest.TestCase):
    def test_two_squares_are_a_ruled_loft_through_both_planes(self):
        result = translate(load_capture(SQUARES))
        self.assertIsNone(result.refusal)
        (loft,) = steps_of(result.recipe, "loft")
        self.assertEqual((loft["ruled"], loft["combine"], len(loft["sections"])), (True, "new", 2))
        low, high = loft["sections"]
        self.assertEqual((low["on"]["origin"], high["on"]["origin"]), ([0.0, 0.0, 0.0], [0.0, 0.0, 30.0]))
        self.assertEqual((high["outer"]["width"], high["outer"]["height"]), (10.0, 10.0))
        self.assertEqual(verdict_of(result, 2)["verdict"], "translated")
        assert_schema_ok(self, result.recipe)

    def test_a_join_loft_adds_to_the_part_and_the_plate_before_it_is_kept(self):
        result = translate(load_capture(PLATE))
        self.assertEqual([step["combine"] for step in steps_of(result.recipe, "loft")], ["add"])
        self.assertEqual(len(steps_of(result.recipe, "extrude")), 1)
        assert_schema_ok(self, result.recipe)

    def test_outlines_of_different_shapes_are_copied_with_a_note(self):
        result = translate(load_capture(ROUND_TO_SQUARE))
        self.assertEqual(steps_of(result.recipe, "loft")[0]["sections"][0]["outer"]["kind"], "circle")
        self.assertEqual(verdict_of(result, 2)["verdict"], "translatedWithNote")
        assert_schema_ok(self, result.recipe)

    def test_merge_tangent_edges_off_is_a_note_only(self):
        result = edited(SQUARES, lambda data, _: data.update(merge_tangent=False))
        self.assertEqual(verdict_of(result, 2)["verdict"], "translatedWithNote")
        self.assertEqual(len(steps_of(result.recipe, "loft")), 1)


class LoftPairingTest(unittest.TestCase):
    """A 20 by 20 square and a 10 by 10 square 30 mm above it. Turned 45 degrees the top square pairs with the bottom
    one by the nearest corners (6414.2 mm3) or, joined the other way, by corners far apart (3585.8 mm3)."""
    S = math.sqrt(0.5)

    def made(self, volume, turned=False):
        capture = load_capture(SQUARES)
        data = loft_data(capture)
        if turned:
            data["profiles"][1]["frame"].update(x=[self.S, self.S, 0], y=[-self.S, self.S, 0])
        capture["items"][2]["target_after"] = {"volume_mm3": volume}
        return translate(capture)

    def test_a_new_body_with_the_volume_of_the_copy_is_copied_without_a_note(self):
        for turned, volume in ((False, 7000.0), (True, 6414.2)):
            with self.subTest(turned=turned):
                result = self.made(volume, turned)
                self.assertIsNone(result.refusal)
                self.assertEqual(verdict_of(result, 2)["verdict"], "translated")

    def test_a_new_body_with_another_volume_is_refused_since_the_corners_are_paired_another_way(self):
        for turned, volume in ((False, 8000.0), (True, 3585.8)):
            with self.subTest(turned=turned):
                self.assertEqual(stopped(self.made(volume, turned))["reason"], loft.CORNERS_PAIRED)

    def test_turned_outlines_without_a_volume_to_compare_are_copied_with_a_note(self):
        result = self.made(None, True)
        self.assertEqual(verdict_of(result, 2)["verdict"], "translatedWithNote")
        self.assertEqual(verdict_of(self.made(None), 2)["verdict"], "translated")


class LoftOpeningsTest(unittest.TestCase):
    def test_openings_are_paired_by_the_nearest_centre_whatever_their_order(self):
        def two_openings(data, _):
            low, high = data["profiles"]
            low["loops"][1:] = [circle_hole([-5, 0], 2, "a"), circle_hole([5, 0], 2, "b")]
            high["loops"][1:] = [circle_hole([4, 0], 1.5, "c"), circle_hole([-4, 0], 1.5, "d")]
        low, high = steps_of(edited(TUBE, two_openings).recipe, "loft")[0]["sections"]
        key_at = lambda section, x: next(h["key"] for h in section["holes"] if h["loop"]["center"][0] == x)  # noqa: E731
        self.assertEqual(key_at(low, 5.0), key_at(high, 4.0))
        self.assertEqual(key_at(low, -5.0), key_at(high, -4.0))
        self.assertNotEqual(key_at(low, 5.0), key_at(low, -5.0))

    def test_outlines_with_different_numbers_of_openings_are_refused(self):
        result = edited(TUBE, lambda data, _: data["profiles"][1]["loops"].pop())
        self.assertIsNotNone(result.refusal)


class LoftSizesTest(unittest.TestCase):
    def test_section_sizes_and_the_spacing_follow_the_sizes(self):
        result = run(load_capture(SQUARES), SIZES, motion_of(SQUARES))
        low, high = steps_of(result.recipe, "loft")[0]["sections"]
        self.assertEqual((low["outer"]["width"], high["outer"]["height"], high["on"]["origin"][2]),
                         ({"expr": "base_mm"}, {"expr": "top_mm"}, {"expr": "height_mm"}))
        self.assertEqual((result.fixed, result.loose, result.dropped), ([], [], []))
        assert_schema_ok(self, result.recipe)

    def test_an_outline_from_another_component_marks_the_sizes_of_its_sketch(self):
        capture = load_capture(SQUARES)
        loft_data(capture)["profiles"][0]["borrowed"] = "Lid"
        result = run(capture, SIZES, motion_of(SQUARES))
        self.assertEqual([f["name"] for f in result.loose], ["base_mm"])

    def test_without_the_sketch_values_no_size_behind_a_sketch_stays_free(self):
        result = run(load_capture(SQUARES), SIZES, None)
        self.assertEqual(steps_of(result.recipe, "loft")[0]["sections"][1]["on"]["origin"][2], 30.0)
        self.assertEqual((result.fixed, result.loose), ([], []))


class LoftOrderTest(unittest.TestCase):
    def test_outlines_whose_planes_cross_are_refused(self):
        result = translate(load_capture("loft_crossing_sections"))
        self.assertIsNotNone(reason_of(result))


class LoftRefusalTest(unittest.TestCase):
    """The plate is copied and the loft is left out with a reason of its own."""

    def test_each_loft_the_copy_cannot_follow_is_left_out_with_its_own_reason(self):
        def update(**more):
            return lambda data, _: data.update(**more)

        def drop_loops(data, _):
            del data["profiles"][0]["loops"]
            data["profiles"][0]["face"] = True

        cases = {
            "centre line": update(centerline={"closed": False, "kind": "sketch", "curves": []}),
            "closed loft": update(closed=True),
            "surface loft": update(solid=False),
            "new component": update(operation="newComponent"),
            "section is a face": lambda data, _: data["sections"][0].update(kind="face"),
            "section is not an outline": lambda data, _: data["sections"][1].update(kind="other"),
            "end condition unread": lambda data, _: data["sections"][0].update(end=None),
            "outline record is a face": drop_loops,
        }
        cases.update({"%s unread" % field: update(**{field: None}) for field in ("closed", "rails", "sections")})
        reasons = {}
        for label, change in cases.items():
            with self.subTest(label):
                reasons[label] = reason_of(edited(PLATE, change))
        for name in ("loft_three_sections", "loft_tangent_end", "loft_point_end", "loft_rails"):
            with self.subTest(name):
                result = translate(load_capture(name))
                reasons[name] = reason_of(result)
                self.assertEqual(len(steps_of(result.recipe, "extrude")), 1)
        self.assertGreaterEqual(len(set(reasons.values())), 11)

    def test_a_loft_left_out_as_the_first_step_stops_the_copy(self):
        capture = load_capture(SQUARES)
        loft_data(capture)["closed"] = True
        result = translate(capture)
        self.assertIsNone(result.recipe)
        self.assertIsNotNone(result.refusal)


if __name__ == "__main__":
    unittest.main()
