import copy
import glob
import json
import os
import unittest

from tests import context  # noqa: F401
from tests.schema_check import check_recipe
from tests.translator_helpers import FIXTURES, assert_schema_ok, close, load_capture, steps_of, translate_fixture

from lib.translator import extrude, translate


def under_test(result, index):
    """The recipe steps written for the timeline item at `index`."""
    return [s for s in result.recipe["features"] if s["id"] == "extrude_%d" % index or s["id"].startswith("extrude_%d_" % index)]


def verdict_of(result, index):
    return [v for v in result.items if v["index"] == index][0]


def variant(name, edit):
    """Translate a fixture after `edit(data)` changed the data of its last item."""
    capture = load_capture(name)
    edit(capture["items"][-1]["data"])
    return translate(capture)


class ShapeTest(unittest.TestCase):
    def test_plate(self):
        result = translate_fixture("extrude_plate")
        (step,) = result.recipe["features"]
        self.assertEqual(step["sketch"]["on"], {"origin": [0, 0, 0], "normal": [0, 0, 1], "xDir": [1, 0, 0]})
        self.assertEqual(step["sketch"]["outer"], {"kind": "rect", "center": [20, 10], "width": 40, "height": 20})
        self.assertEqual((step["extent"], step["distance"], step["combine"]), ("oneSide", 10, "new"))
        self.assertEqual(verdict_of(result, 1)["verdict"], "translated")
        assert_schema_ok(self, result.recipe)

    def test_turned_rect(self):
        outer = translate_fixture("extrude_turned_rect").recipe["features"][0]["sketch"]["outer"]
        self.assertEqual((outer["kind"], outer["angleDeg"]), ("rect", 30))
        self.assertTrue(close([outer["width"], outer["height"]], [30, 10]))

    def test_ring_has_circle_outer_and_inner(self):
        sketch = translate_fixture("extrude_ring").recipe["features"][0]["sketch"]
        self.assertEqual(sketch["outer"], {"kind": "circle", "center": [0, 0], "radius": 10})
        self.assertEqual(sketch["inner"], [{"kind": "circle", "center": [0, 0], "radius": 6}])

    def test_l_shape_polygon_keeps_area(self):
        points = translate_fixture("extrude_l_shape").recipe["features"][0]["sketch"]["outer"]["points"]
        pairs = zip(points, points[1:] + points[:1])
        self.assertAlmostEqual(abs(sum(a[0] * b[1] - b[0] * a[1] for a, b in pairs)) / 2, 500)

    def test_slot_is_a_profile(self):
        outer = translate_fixture("extrude_slot_arcs").recipe["features"][0]["sketch"]["outer"]
        kinds = [s["kind"] for s in outer["segments"]]
        self.assertEqual((kinds.count("line"), kinds.count("arc")), (2, 2))
        self.assertEqual({tuple(s["through"]) for s in outer["segments"] if s["kind"] == "arc"}, {(25, 0), (-5, 0)})


class PlacementTest(unittest.TestCase):
    def test_offset_and_turned_sketch_keeps_its_frame(self):
        on = translate_fixture("extrude_offset_sketch").recipe["features"][0]["sketch"]["on"]
        self.assertEqual((on["origin"], on["xDir"], on["normal"]), ([0, 0, 5], [0, 1, 0], [0, 0, 1]))

    def test_flipped_extrude_reverses_the_placement_and_mirrors_the_sketch(self):
        result = translate_fixture("extrude_flipped")
        step = result.recipe["features"][0]
        self.assertEqual(step["sketch"]["on"]["normal"], [0, 0, -1])
        self.assertEqual(step["sketch"]["on"]["xDir"], [1, 0, 0])
        self.assertEqual(step["sketch"]["outer"]["center"], [20, -10])
        self.assertEqual(step["distance"], 8)
        self.assertEqual(verdict_of(result, 1)["verdict"], "translated")

    def test_measured_end_wins_when_the_sign_disagrees(self):
        result = translate_fixture("extrude_sign_disagrees")
        step = result.recipe["features"][0]
        self.assertEqual((step["sketch"]["on"]["normal"], step["distance"]), ([0, 0, -1], 8))
        self.assertEqual(verdict_of(result, 1)["verdict"], "translatedWithNote")

    def test_negative_distance_alone_flips(self):
        result = variant("extrude_plate", lambda d: d.update(side_one={"kind": "distance", "distance": -6.0, "taper_deg": 0.0}, end_offset=None))
        self.assertEqual(result.recipe["features"][0]["sketch"]["on"]["normal"], [0, 0, -1])

    def test_start_offset_moves_the_origin_along_the_normal(self):
        result = translate_fixture("extrude_start_offset")
        (step,) = under_test(result, 3)
        self.assertEqual(step["sketch"]["on"]["origin"], [0, 0, 13])
        self.assertEqual((step["combine"], step["distance"]), ("add", 4))

    def test_start_from_a_parallel_plane_acts_as_an_offset(self):
        plane = {"point": [0, 0, 14], "normal": [0, 0, -1]}
        result = variant("extrude_start_offset", lambda d: d.update(start={"kind": "fromEntity", "plane": plane}))
        self.assertEqual(under_test(result, 3)[0]["sketch"]["on"]["origin"], [0, 0, 14])

    def test_start_from_a_tilted_plane_refuses(self):
        plane = {"point": [0, 0, 14], "normal": [0.3, 0, 0.954]}
        result = variant("extrude_start_offset", lambda d: d.update(start={"kind": "fromEntity", "plane": plane}))
        self.assertIsNone(result.recipe)
        self.assertEqual(result.refusal["index"], 3)


class ExtentTest(unittest.TestCase):
    def test_symmetric_half_length_doubles(self):
        step = translate_fixture("extrude_symmetric_half").recipe["features"][0]
        self.assertEqual((step["extent"], step["distance"]), ("symmetric", 10))

    def test_symmetric_full_length_is_kept(self):
        result = variant("extrude_symmetric_half", lambda d: d["symmetric"].update(full_length=True))
        self.assertEqual(result.recipe["features"][0]["distance"], 5)

    def test_two_sides_make_two_steps_second_reversed(self):
        result = translate_fixture("extrude_two_sides")
        first, second = result.recipe["features"]
        self.assertEqual((first["combine"], second["combine"]), ("new", "add"))
        self.assertEqual((first["distance"], second["distance"]), (6, 4))
        self.assertEqual((first["sketch"]["on"]["normal"], second["sketch"]["on"]["normal"]), ([0, 0, 1], [0, 0, -1]))
        self.assertEqual(second["sketch"]["outer"]["center"], [20, -10])
        self.assertEqual([s["id"] for s in result.recipe["features"]], ["extrude_1", "extrude_1_2"])

    def test_cut_through_both_ways_is_extent_through(self):
        result = translate_fixture("extrude_cut_through_two")
        (step,) = under_test(result, 3)
        self.assertEqual((step["extent"], step["combine"]), ("through", "cut"))
        self.assertNotIn("distance", step)
        assert_schema_ok(self, result.recipe)

    def test_cut_through_one_way_reaches_past_the_part(self):
        result = translate_fixture("extrude_cut_through_one")
        (step,) = under_test(result, 3)
        self.assertEqual((step["extent"], step["combine"]), ("oneSide", "cut"))
        self.assertGreaterEqual(step["distance"], 41)
        self.assertEqual(step["sketch"]["on"]["normal"], [1, 0, 0])

    def test_cut_through_the_other_way_goes_against_the_normal(self):
        result = variant("extrude_cut_through_one", lambda d: d.update(side_one={"kind": "throughAll", "positive": False, "taper_deg": 0.0}, end_offset=None))
        (step,) = under_test(result, 3)
        self.assertEqual(step["sketch"]["on"]["normal"], [-1, 0, 0])
        self.assertGreaterEqual(step["distance"], 1)

    def test_through_all_join_refuses(self):
        result = variant("extrude_cut_through_one", lambda d: d.update(operation="join"))
        self.assertIn("only copied for cuts", result.refusal["reason"])

    def test_through_all_without_a_measured_part_refuses(self):
        result = variant("extrude_cut_through_one", lambda d: d.update(target_box_before=None))
        self.assertIsNone(result.recipe)

    def test_all_kind_cuts_like_through_all(self):
        result = variant("extrude_cut_through_one", lambda d: d.update(side_one={"kind": "all"}, end_offset=None))
        self.assertEqual(under_test(result, 3)[0]["extent"], "oneSide")

    def test_to_plane_measures_the_distance(self):
        (step,) = under_test(translate_fixture("extrude_to_plane"), 3)
        self.assertEqual((step["extent"], step["distance"], step["combine"]), ("oneSide", 10, "add"))

    def test_to_plane_adds_its_offset(self):
        result = variant("extrude_to_plane", lambda d: d["side_one"].update(offset=1.5))
        self.assertEqual(under_test(result, 3)[0]["distance"], 11.5)

    def test_to_a_plane_behind_the_sketch_goes_backwards(self):
        def edit(d):
            d["side_one"]["plane"] = {"point": [0, 0, -4], "normal": [0, 0, 1]}
            d["end_offset"] = None
        (step,) = under_test(variant("extrude_to_plane", edit), 3)
        self.assertEqual((step["sketch"]["on"]["normal"], step["distance"]), ([0, 0, -1], 6))

    def test_to_tilted_plane_refuses_naming_the_item(self):
        result = translate_fixture("extrude_to_tilted")
        self.assertIsNone(result.recipe)
        self.assertEqual((result.refusal["index"], result.refusal["name"]), (3, "Extrude2"))

    def test_to_unreadable_entity_refuses(self):
        result = variant("extrude_to_plane", lambda d: d["side_one"].update(plane=None))
        self.assertIsNone(result.recipe)

    def test_two_profiles_make_two_add_steps(self):
        result = translate_fixture("extrude_two_profiles")
        steps = under_test(result, 3)
        self.assertEqual([s["id"] for s in steps], ["extrude_3", "extrude_3_2"])
        self.assertEqual([s["combine"] for s in steps], ["add", "add"])
        self.assertEqual(verdict_of(result, 3)["steps"], ["extrude_3", "extrude_3_2"])

    def test_new_body_with_two_profiles_adds_the_second(self):
        capture = load_capture("extrude_plate")
        data = capture["items"][-1]["data"]
        data["profiles"].append(copy.deepcopy(data["profiles"][0]))
        steps = translate(capture).recipe["features"]
        self.assertEqual([s["combine"] for s in steps], ["new", "add"])


class TaperTest(unittest.TestCase):
    def test_taper_uses_the_sign_constant(self):
        step = translate_fixture("extrude_taper").recipe["features"][0]
        self.assertEqual(step["taperDeg"], extrude.FUSION_TAPER_SIGN * 5)

    def test_taper_at_the_cap_refuses(self):
        result = variant("extrude_taper", lambda d: d["side_one"].update(taper_deg=45.0))
        self.assertIsNone(result.recipe)

    def test_symmetric_taper_is_kept(self):
        result = variant("extrude_symmetric_half", lambda d: d["symmetric"].update(taper_deg=3.0))
        self.assertEqual(result.recipe["features"][0]["taperDeg"], extrude.FUSION_TAPER_SIGN * 3)

    def test_no_taper_writes_no_field(self):
        self.assertNotIn("taperDeg", translate_fixture("extrude_plate").recipe["features"][0])


class OperationTest(unittest.TestCase):
    def test_intersect(self):
        (step,) = under_test(translate_fixture("extrude_intersect"), 3)
        self.assertEqual(step["combine"], "intersect")

    def test_intersect_with_two_profiles_refuses(self):
        capture = load_capture("extrude_intersect")
        data = capture["items"][-1]["data"]
        data["profiles"].append(copy.deepcopy(data["profiles"][0]))
        self.assertIsNone(translate(capture).recipe)

    def test_two_sided_cut_cuts_twice(self):
        def edit(d):
            d.update(operation="cut", extent_type="two", side_one={"kind": "distance", "distance": 3.0, "taper_deg": 0.0},
                     side_two={"kind": "distance", "distance": 2.0, "taper_deg": 0.0}, end_offset=3.0)
        steps = under_test(variant("extrude_to_plane", edit), 3)
        self.assertEqual([s["combine"] for s in steps], ["cut", "cut"])

    def test_two_sided_intersect_refuses(self):
        def edit(d):
            d.update(extent_type="two", side_two={"kind": "distance", "distance": 2.0, "taper_deg": 0.0})
        self.assertIsNone(variant("extrude_intersect", edit).recipe)

    def test_two_sides_with_one_through_reaches_past_the_part_on_that_side(self):
        def edit(d):
            d.update(extent_type="two", side_one={"kind": "distance", "distance": 3.0, "taper_deg": 0.0},
                     side_two={"kind": "throughAll", "positive": True, "taper_deg": 0.0}, end_offset=3.0)
        steps = under_test(variant("extrude_cut_through_one", edit), 3)
        self.assertEqual([s["distance"] > 40 for s in steps], [False, True])
        self.assertEqual(steps[1]["sketch"]["on"]["normal"], [-1, 0, 0])


class RefusalTest(unittest.TestCase):
    def test_each_unsupported_input_has_its_own_reason(self):
        reasons = {}
        for name in ("extrude_thin", "extrude_face_profile", "extrude_new_component", "extrude_spline"):
            result = translate_fixture(name)
            self.assertIsNone(result.recipe, name)
            self.assertEqual((result.refusal["index"], result.refusal["type"]), (1, "ExtrudeFeature"), name)
            reasons[name] = result.refusal["reason"]
        self.assertEqual(len(set(reasons.values())), 4)

    def test_helper_body_extrude_is_kept_as_a_pending_new_body_step(self):
        capture = load_capture("extrude_plate")
        helper = copy.deepcopy(capture["items"][-1])
        helper.update(index=2, name="Extrude2", bodies_after=[{"token": "t2", "name": "Body2"}])
        capture["items"].append(helper)
        result = translate(capture)
        self.assertEqual(len(result.recipe["features"]), 1)
        self.assertEqual(verdict_of(result, 2)["verdict"], "skipped")


class FixtureSchemaTest(unittest.TestCase):
    def test_every_translated_extrude_fixture_passes_the_schema(self):
        translated = 0
        for path in sorted(glob.glob(os.path.join(FIXTURES, "extrude_*.json"))):
            with open(path, encoding="utf-8") as f:
                result = translate(json.load(f))
            if result.recipe is not None:
                translated += 1
                self.assertEqual(check_recipe(result.recipe), [], os.path.basename(path))
        self.assertEqual(translated, 17)


if __name__ == "__main__":
    unittest.main()
