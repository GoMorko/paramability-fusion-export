"""Sketch text and embosses in the Orca copy: letters as imported regions whose depth follows its variable, and the
steps left out where Orca would build them otherwise than Fusion."""
import copy
import math
import unittest

from tests import context  # noqa: F401
from tests import orca_text as tx
from tests.orca_cuts import Section
from tests.orca_extents import UP, at, profile, rect, side
from tests.test_orca_extents import outcome, run
from tests.translator_helpers import load_capture

from lib.capture_model import gap_hints
from lib.orca_recipe.enums import ExtrudeEnd, FeatureType
from lib.orca_translate import FIXED, VARIABLE, causes
from lib.orca_translate import text_regions

# Points of the plate: in the L, in the O's ring, in the O's hole, and on the bare plate.
IN_L, IN_RING, IN_HOLE, BARE = (-19.0, 0.0), (4.0, 0.0), (0.0, 0.0), (20.0, 0.0)


def solid_at(result, xy, z, **values):
    (body,) = Section(result.recipe, values).bodies
    return body(list(result.place.point([xy[0], xy[1], z])))


def left_out(result):
    (found,) = result.left_out
    return found


def text_sketch(result):
    return next(f for f in result.recipe.features if f.type == FeatureType.SKETCH and f.imported_regions)


class TextExtrudeTest(unittest.TestCase):
    def test_raised_letters_follow_their_depth(self):
        result = run(tx.text_extrude(1.0))
        self.assertEqual(result.left_out, [])
        self.assertEqual([len(region) for region in text_sketch(result).imported_regions], [1, 2])
        for depth in (1.0, 2.5):
            above = 2.0 + depth - 0.1
            self.assertTrue(solid_at(result, IN_L, above, text_depth=depth))
            self.assertTrue(solid_at(result, IN_RING, above, text_depth=depth))
            self.assertFalse(solid_at(result, IN_HOLE, above, text_depth=depth))
            self.assertFalse(solid_at(result, IN_L, 2.0 + depth + 0.1, text_depth=depth))
        self.assertEqual(outcome(result, "text_depth")["outcome"], VARIABLE)

    def test_sunk_letters_follow_their_depth(self):
        result = run(tx.text_extrude(-0.6, operation="cut"))
        self.assertEqual(result.left_out, [])
        for depth in (0.6, 1.5):
            self.assertFalse(solid_at(result, IN_L, 2.0 - depth + 0.05, text_depth=depth))
            self.assertTrue(solid_at(result, IN_L, 2.0 - depth - 0.05, text_depth=depth))
            self.assertTrue(solid_at(result, IN_HOLE, 1.9, text_depth=depth))
            self.assertTrue(solid_at(result, BARE, 1.9, text_depth=depth))

    def test_symmetric_letters_are_copied_symmetric(self):
        capture = tx.text_extrude(1.0, extent_type="symmetric", side_one=None, end_offset=None,
                                  symmetric={"distance": 1.0, "full_length": True, "taper_deg": 0.0})
        result = run(capture)
        (extrude,) = [f for f in result.recipe.features if f.type == FeatureType.EXTRUDE and f.sketch_ref ==
                      result.recipe.features.index(text_sketch(result))]
        self.assertEqual((extrude.extrude_end, extrude.symmetric), (ExtrudeEnd.SYMMETRIC, True))

    def test_two_sides_and_a_taper_are_left_out(self):
        two = tx.text_extrude(1.0, extent_type="two", side_two=side(0.5))
        tapered = tx.text_extrude(1.0, profiles=[tx.text_profile(tx.O_OUTER)], side_one=side(1.0, taper=-5.0),
                                  profile_area=100.0, end_area=90.0)
        for capture in (two, tapered):
            self.assertEqual(left_out(run(capture))["cause"], causes.TEXT_EXTENT)

    def test_text_with_another_outline_is_left_out(self):
        mixed = tx.letters() + [profile("Sketch2", at(2.0), rect(10, -5, 20, 5))]
        self.assertEqual(left_out(run(tx.text_extrude(1.0, profiles=mixed)))["cause"], causes.TEXT_OUTLINE)

    def test_letters_orca_would_build_otherwise_are_left_out(self):
        crossing = [(-20, -5), (-10, 5), (-10, -5), (-20, 7)]
        hole_outside = [(-3, -3), (3, -3), (3, 3), (-3, 3)]
        touching = [(-14, -5), (-10, -5), (-10, 5), (-14, 5)]
        cases = {
            "a loop crossing itself": [tx.text_profile(crossing)],
            "a hole outside its letter": [tx.text_profile(tx.L_OUTLINE, [hole_outside])],
            "letters that touch": [tx.text_profile(tx.L_OUTLINE), tx.text_profile(touching)],
            "a letter inside another": [tx.text_profile(tx.O_OUTER), tx.text_profile(tx.O_HOLE)],
        }
        for name, profiles in cases.items():
            with self.subTest(name):
                result = run(tx.text_extrude(1.0, profiles=profiles))
                self.assertEqual(left_out(result)["cause"], causes.TEXT_OUTLINE)

    def test_a_free_curve_whose_samples_do_not_stand_for_it_is_left_out(self):
        letter = tx.text_profile(tx.O_OUTER)
        circle = [[3 * math.cos(t / 20.0 * 2 * math.pi), 3 * math.sin(t / 20.0 * 2 * math.pi)] for t in range(21)]
        letter["loops"][0]["curves"] = [{"kind": "other", "start": circle[0], "end": circle[-1], "samples": circle,
                                         "truncated": True}]
        self.assertEqual(left_out(run(tx.text_extrude(1.0, profiles=[letter])))["cause"], causes.TEXT_OUTLINE)

    def test_several_letters_that_start_the_part_are_left_out(self):
        result = run(load_capture("extrude_text"))
        self.assertEqual(left_out(result)["cause"], causes.TEXT_OUTLINE)

    def test_letters_of_a_cut_that_miss_the_part_are_left_out(self):
        result = run(tx.text_extrude(-0.6, operation="cut", profiles=tx.letters(at(10.0))))
        self.assertEqual(left_out(result)["cause"], causes.MISSES_PART)

    def test_a_size_that_places_the_text_keeps_its_number_with_a_reason(self):
        capture = tx.text_extrude(1.0)
        capture["parameters"]["user"].append(tx.user("margin", "4 mm", 4.0))
        capture["parameters"]["model"].append(tx.model("d3", "margin", 4.0, kind="sketchDimension"))
        capture["parameters"]["model"][-1]["created_by"]["sketch"] = "Sketch2"
        found = outcome(run(capture), "margin")
        self.assertEqual(found["outcome"], FIXED)
        self.assertTrue(found["reasons"])


class EmbossTest(unittest.TestCase):
    def test_raised_and_sunk_embosses_are_the_extrudes_they_stand_for(self):
        for depth in (1.0, -0.6):
            result = run(tx.text_emboss(depth))
            self.assertEqual(result.left_out, [])
            inside = 2.0 + depth / 2.0
            self.assertEqual(solid_at(result, IN_L, inside, text_depth=abs(depth)), depth > 0)
            self.assertEqual(solid_at(result, IN_HOLE, inside, text_depth=abs(depth)), depth < 0)
            deeper = 2.0 + depth * 1.5
            self.assertEqual(solid_at(result, IN_L, deeper, text_depth=abs(depth) * 2), depth > 0)

    def test_the_fusion_text_capture_is_copied(self):
        result = run(load_capture("emboss_text"))
        self.assertEqual(result.left_out, [])
        self.assertEqual(len(text_sketch(result).imported_regions), 2)

    def test_an_emboss_orca_cannot_follow_is_left_out_with_its_cause(self):
        def trimmed(data):
            data.update(volume_after=tx.PLATE + 50.0, end_area=50.0)

        def curved(data):
            data["faces"][0].update(surface="Cylinder")

        def tangent(data):
            data.update(tangent_chain=True, tangent_faces=[{"surface": "Cylinder", "plane": None}])

        def moved(data):
            data.update(offset_x=2.0)

        cases = {"trimmed": (trimmed, causes.EMBOSS_TRIMMED), "curved": (curved, causes.EMBOSS_FACE),
                 "tangent": (tangent, causes.EMBOSS_FACE), "moved": (moved, gap_hints.REFUSED)}
        for name, (change, cause) in cases.items():
            with self.subTest(name):
                capture = tx.text_emboss(1.0)
                change(capture["items"][3]["data"])
                self.assertEqual(left_out(run(capture))["cause"], cause)

    def test_an_emboss_of_a_drawn_outline_is_copied_too(self):
        capture = tx.text_emboss(1.0, profiles=[profile("Sketch2", at(2.0), rect(10, -5, 20, 5))], areas=[100.0],
                                 volume_after=tx.PLATE + 100.0, end_area=100.0)
        result = run(capture)
        self.assertEqual(result.left_out, [])
        self.assertTrue(solid_at(result, (15.0, 0.0), 2.5, text_depth=1.0))


class PolygonTest(unittest.TestCase):
    def test_arcs_and_free_curves_stay_within_the_chord_tolerance(self):
        r = 2.0
        circle = text_regions.loop_polygon([{"kind": "circle", "center": [0.0, 0.0], "radius": r}])
        samples = [[r * math.cos(k * 2 * math.pi / 4000), r * math.sin(k * 2 * math.pi / 4000)] for k in range(4001)]
        spline = text_regions.loop_polygon([{"kind": "other", "start": samples[0], "end": samples[-1],
                                             "samples": samples}])
        for ring in (circle, spline):
            self.assertLess(len(ring), 400)
            for a, b in zip(ring, ring[1:] + ring[:1]):
                mid = math.hypot((a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0)
                self.assertLessEqual(r - mid, text_regions.CHORD_TOL + 1e-9)
                self.assertGreater(math.hypot(b[0] - a[0], b[1] - a[1]), text_regions.JOIN_TOL)


if __name__ == "__main__":
    unittest.main()
