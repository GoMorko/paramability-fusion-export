"""Loft through two outlines with free ends: copied as a ruled loft; each case it cannot copy is left out as a gap."""
import unittest

from tests import context  # noqa: F401
from tests.test_translate_sketch_motion import motion_of, run
from tests.translator_helpers import assert_schema_ok, left_out, load_capture, steps_of, translate, verdict_of

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


class LoftOpeningsTest(unittest.TestCase):
    def test_an_opening_in_both_outlines_shares_one_key(self):
        result = translate(load_capture(TUBE))
        low, high = steps_of(result.recipe, "loft")[0]["sections"]
        self.assertEqual([h["key"] for h in low["holes"]], [h["key"] for h in high["holes"]])
        assert_schema_ok(self, result.recipe)

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
        self.assertIn("numbers of openings", result.refusal["reason"])


class LoftSizesTest(unittest.TestCase):
    def test_section_sizes_and_the_spacing_follow_the_sizes(self):
        result = run(load_capture(SQUARES), SIZES, motion_of(SQUARES))
        low, high = steps_of(result.recipe, "loft")[0]["sections"]
        self.assertEqual((low["outer"]["width"], high["outer"]["height"], high["on"]["origin"][2]),
                         ({"expr": "base_mm"}, {"expr": "top_mm"}, {"expr": "height_mm"}))
        self.assertEqual((result.fixed, result.loose, result.dropped), ([], [], []))
        assert_schema_ok(self, result.recipe)

    def test_without_the_sketch_values_no_size_behind_a_sketch_stays_free(self):
        result = run(load_capture(SQUARES), SIZES, None)
        self.assertEqual(steps_of(result.recipe, "loft")[0]["sections"][1]["on"]["origin"][2], 30.0)
        self.assertEqual((result.fixed, result.loose), ([], []))


class LoftOrderTest(unittest.TestCase):
    def test_outlines_whose_planes_cross_are_refused(self):
        result = translate(load_capture("loft_crossing_sections"))
        self.assertIn("cross each other", reason_of(result))


class LoftRefusalTest(unittest.TestCase):
    """The plate is copied and the loft is left out with its own reason."""

    def check(self, name, word):
        result = translate(load_capture(name))
        self.assertIn(word, reason_of(result))
        self.assertEqual(len(steps_of(result.recipe, "extrude")), 1)

    def edit(self, change, word):
        self.assertIn(word, reason_of(edited(PLATE, change)))

    def test_three_sections(self):
        self.check("loft_three_sections", "more than two outlines")

    def test_a_tangent_end(self):
        self.check("loft_tangent_end", "shapes its ends")

    def test_a_point_section(self):
        self.check("loft_point_end", "end in a point")

    def test_rails(self):
        self.check("loft_rails", "rails")

    def test_a_centre_line(self):
        self.edit(lambda data, _: data.update(centerline={"closed": False, "kind": "sketch", "curves": []}),
                  "centre line")

    def test_a_closed_loft(self):
        self.edit(lambda data, _: data.update(closed=True), "Closed lofts")

    def test_a_section_that_is_a_face(self):
        self.edit(lambda data, _: data["sections"][0].update(kind="face"), "face of the part")

    def test_a_section_that_is_not_a_sketch_outline(self):
        self.edit(lambda data, _: data["sections"][1].update(kind="other"), "not a closed sketch outline")

    def test_a_surface_loft(self):
        self.edit(lambda data, _: data.update(solid=False), "Surface lofts")

    def test_a_loft_that_makes_a_new_component(self):
        self.edit(lambda data, _: data.update(operation="newComponent"), "new component")

    def test_a_setting_that_could_not_be_read(self):
        for field in ("closed", "rails", "sections"):
            with self.subTest(field=field):
                self.edit(lambda data, _, field=field: data.update({field: None}), "could not be read")

    def test_an_end_condition_that_could_not_be_read(self):
        self.edit(lambda data, _: data["sections"][0].update(end=None), "could not be read")

    def test_a_flat_face_used_as_an_outline_record(self):
        def face(data, _):
            del data["profiles"][0]["loops"]
            data["profiles"][0]["face"] = True
        self.edit(face, "face")

    def test_a_loft_left_out_as_the_first_step_stops_the_copy(self):
        capture = load_capture(SQUARES)
        loft_data(capture)["closed"] = True
        result = translate(capture)
        self.assertIsNone(result.recipe)
        self.assertIn("Closed lofts", result.refusal["reason"])


if __name__ == "__main__":
    unittest.main()
