import copy
import glob
import json
import math
import os
import unittest

from tests import context  # noqa: F401
from tests.schema_check import check_recipe
from tests.translator_helpers import FIXTURES, assert_schema_ok, load_capture, translate_fixture

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

    def test_ring_has_circle_outer_and_inner(self):
        sketch = translate_fixture("extrude_ring").recipe["features"][0]["sketch"]
        self.assertEqual(sketch["outer"], {"kind": "circle", "center": [0, 0], "radius": 10})
        self.assertEqual(sketch["inner"], [{"kind": "circle", "center": [0, 0], "radius": 6}])

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
        result = variant("extrude_start_offset", lambda d: d.update(start={"kind": "fromEntity", "plane": plane}, end_offset=8.0))
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

    def test_to_plane_measures_the_distance(self):
        (step,) = under_test(translate_fixture("extrude_to_plane"), 3)
        self.assertEqual((step["extent"], step["distance"], step["combine"]), ("oneSide", 10, "add"))

    def test_to_plane_adds_its_offset(self):
        result = variant("extrude_to_plane", lambda d: (d["side_one"].update(offset=1.5), d.update(end_offset=11.5)))
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

    def test_two_profiles_make_two_add_steps(self):
        result = translate_fixture("extrude_two_profiles")
        steps = under_test(result, 3)
        self.assertEqual([s["id"] for s in steps], ["extrude_3", "extrude_3_2"])
        self.assertEqual([s["combine"] for s in steps], ["add", "add"])
        self.assertEqual(verdict_of(result, 3)["steps"], ["extrude_3", "extrude_3_2"])

    def test_new_body_from_two_outlines_that_fusion_made_one_body(self):
        result = translate_fixture("extrude_new_body_two_bodies")
        self.assertEqual([s["combine"] for s in result.recipe["features"]], ["new", "add"])
        item = load_capture("extrude_new_body_two_bodies")["items"][-1]
        item["bodies_after"] = []
        self.assertIn("several bodies", extrude.handle(item, None).reason)

    def test_profiles_on_two_planes_refuse(self):
        result = translate_fixture("extrude_profiles_two_planes")
        self.assertIsNone(result.recipe)
        self.assertIn("different planes", result.refusal["reason"])

    def test_profiles_on_one_plane_from_two_sketches_pass(self):
        capture = load_capture("extrude_profiles_two_planes")
        capture["items"][-1]["data"]["profiles"][1]["frame"]["origin"] = [0, 0, 10]
        self.assertEqual([s["id"] for s in under_test(translate(capture), 3)], ["extrude_3", "extrude_3_2"])

    def test_profiles_facing_opposite_ways_refuse(self):
        capture = load_capture("extrude_profiles_two_planes")
        frame = capture["items"][-1]["data"]["profiles"][1]["frame"]
        frame.update(origin=[0, 0, 10], z=[0, 0, -1], y=[0, -1, 0])
        self.assertIsNone(translate(capture).recipe)


class MeasuredLengthTest(unittest.TestCase):
    def test_one_side_length_must_match_the_measured_end(self):
        result = variant("extrude_plate", lambda d: d.update(end_offset=12.0))
        self.assertIn("does not match its length", result.refusal["reason"])

    def test_symmetric_distance_is_checked_as_half_length(self):
        ok = variant("extrude_symmetric_half", lambda d: d.update(end_offset=5.0))
        self.assertEqual(ok.recipe["features"][0]["distance"], 10)
        wrong = variant("extrude_symmetric_half", lambda d: d.update(end_offset=10.0))
        self.assertIsNone(wrong.recipe)

    def test_two_sided_end_face_must_belong_to_side_one(self):
        swapped = variant("extrude_two_sides", lambda d: d.update(end_offset=4.0))
        self.assertIsNone(swapped.recipe)
        ok = variant("extrude_two_sides", lambda d: d.update(end_offset=-6.0))
        self.assertEqual(ok.recipe["features"][0]["sketch"]["on"]["normal"], [0, 0, -1])

    def test_a_two_sided_cut_turns_only_for_a_face_that_the_stored_direction_cannot_reach(self):
        def cut(end):
            return lambda d: d.update(extent_type="two", end_offset=end,
                                      side_one={"kind": "distance", "distance": 60.0, "taper_deg": 0.0},
                                      side_two={"kind": "distance", "distance": 10.0, "taper_deg": 0.0})
        # A wall cut through 4 mm behind the sketch lies in reach of the second side.
        kept = under_test(variant("extrude_cut_through_one", cut(-4.0)), 3)
        self.assertEqual(kept[0]["sketch"]["on"]["normal"], [1, 0, 0])
        turned = under_test(variant("extrude_cut_through_one", cut(-50.0)), 3)
        self.assertEqual(turned[0]["sketch"]["on"]["normal"], [-1, 0, 0])

    def test_to_entity_offset_is_checked_against_the_measured_end(self):
        result = variant("extrude_to_plane", lambda d: d["side_one"].update(offset=1.5))
        self.assertIsNone(result.recipe)

    def test_a_cut_past_the_part_is_not_checked_against_a_nearer_wall(self):
        def cut(distance):
            return lambda d: d.update(side_one={"kind": "distance", "distance": distance, "taper_deg": 0.0}, end_offset=30.0)
        self.assertEqual(under_test(variant("extrude_cut_through_one", cut(60.0)), 3)[0]["distance"], 60)
        self.assertIsNone(variant("extrude_cut_through_one", cut(35.0)).recipe)

    def test_missing_measure_is_not_a_refusal(self):
        self.assertIsNotNone(variant("extrude_symmetric_half", lambda d: d.update(end_offset=None)).recipe)


class TaperTest(unittest.TestCase):
    def test_taper_uses_the_sign_constant_when_measured_agrees(self):
        step = translate_fixture("extrude_taper").recipe["features"][0]
        self.assertEqual(step["taperDeg"], extrude.FUSION_TAPER_SIGN * 5)

    def test_taper_that_grows_the_end_face_refuses(self):
        result = translate_fixture("extrude_taper_wrong_sign")
        self.assertIsNone(result.recipe)
        self.assertIn("does not match what was measured", result.refusal["reason"])

    def test_taper_without_a_measure_refuses(self):
        result = translate_fixture("extrude_taper_unmeasured")
        self.assertIn("could not be measured", result.refusal["reason"])

    def test_taper_with_no_size_change_refuses(self):
        result = variant("extrude_taper", lambda d: d.update(end_area=d["profile_area"]))
        self.assertIsNone(result.recipe)

    def test_taper_at_the_cap_refuses(self):
        result = variant("extrude_taper", lambda d: d["side_one"].update(taper_deg=45.0))
        self.assertIsNone(result.recipe)

    def test_symmetric_taper_is_kept(self):
        def edit(d):
            d["symmetric"].update(taper_deg=-3.0)
            d.update(end_offset=5.0, profile_area=800.0, end_area=700.0)
        result = variant("extrude_symmetric_half", edit)
        self.assertEqual(result.recipe["features"][0]["taperDeg"], extrude.FUSION_TAPER_SIGN * -3)

def two_tapered_squares(lean, operation="newBody"):
    """The taper fixture (Fusion 5 degrees, walls out) with a second outline beside the first, one end face over both,
    and side walls that lean by `lean` (sine) along the sketch normal."""
    def edit(d):
        second = copy.deepcopy(d["profiles"][0])
        for curve in second["loops"][0]["curves"]:
            curve["start"], curve["end"] = [curve["start"][0] + 50, curve["start"][1]], [curve["end"][0] + 50, curve["end"][1]]
        d["profiles"].append(second)
        d.update(operation=operation, end_area=1500.0, side_leans=[lean] * 8)
        if operation == "cut":
            d["side_one"]["taper_deg"] = 5.0
    return edit


class SideWallTaperTest(unittest.TestCase):
    LEAN = math.sin(math.radians(5.0))

    def test_several_outlines_are_checked_by_their_side_walls(self):
        result = variant("extrude_taper", two_tapered_squares(-self.LEAN))
        self.assertEqual([s["taperDeg"] for s in result.recipe["features"]], [-5, -5])

    def test_walls_that_lean_the_other_way_refuse(self):
        result = variant("extrude_taper", two_tapered_squares(self.LEAN))
        self.assertIn("does not match what was measured", result.refusal["reason"])

    def test_a_cut_shows_the_walls_of_the_hole(self):
        capture = load_capture("extrude_taper")
        base = copy.deepcopy(capture["items"][-1])
        base["data"].update(side_one={"kind": "distance", "distance": 20.0, "taper_deg": 0.0}, end_offset=20.0,
                            profile_area=None, end_area=None)
        base["data"]["profiles"][0]["loops"][0]["curves"] = [
            {"kind": "line", "start": a, "end": b} for a, b in
            (([-10, -10], [100, -10]), ([100, -10], [100, 30]), ([100, 30], [-10, 30]), ([-10, 30], [-10, -10]))]
        capture["items"].insert(-1, dict(base, name="Block"))
        cut = capture["items"][-1]
        cut["index"] = 2
        cut["data"]["participants"] = [{"token": "t1", "name": "Body1"}]
        two_tapered_squares(self.LEAN, "cut")(cut["data"])
        result = translate(capture)
        self.assertEqual([s["taperDeg"] for s in under_test(result, cut["index"])], [-5, -5])

    def test_several_outlines_without_measured_walls_refuse(self):
        def edit(d):
            two_tapered_squares(self.LEAN)(d)
            del d["side_leans"]
        self.assertIn("could not be measured", variant("extrude_taper", edit).refusal["reason"])


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


class DriverGuardTest(unittest.TestCase):
    def test_cut_that_splits_the_target_refuses(self):
        for name in ("extrude_cut_splits_target", "extrude_cut_splits_target_unknown_before"):
            result = translate_fixture(name)
            self.assertIsNone(result.recipe, name)
            self.assertEqual(result.refusal["index"], 3, name)
            self.assertIn("splits the part", result.refusal["reason"], name)

    def test_cut_across_two_existing_bodies_is_kept(self):
        result = translate_fixture("extrude_cut_two_bodies_existing")
        self.assertEqual(under_test(result, 3)[0]["combine"], "cut")

    def test_two_bodies_listed_after_a_new_body_refuse(self):
        result = translate_fixture("extrude_new_body_two_bodies_listed")
        self.assertIsNone(result.recipe)

    def test_target_with_a_new_token_is_not_skipped(self):
        result = translate_fixture("extrude_target_token_changes")
        self.assertIsNone(result.recipe)
        self.assertIn("could not be followed", result.refusal["reason"])

    def test_unreadable_bodies_refuse(self):
        result = translate_fixture("extrude_bodies_unreadable")
        self.assertIsNone(result.recipe)
        self.assertEqual(result.refusal["index"], 3)

    def test_read_error_refuses_in_driver_and_handler(self):
        result = translate_fixture("extrude_read_error")
        self.assertEqual(result.refusal["reason"], "This step could not be read from Fusion.")
        item = load_capture("extrude_read_error")["items"][-1]
        self.assertEqual(extrude.handle(item, None).reason, "This step could not be read from Fusion.")

    def test_unknown_type_without_bodies_refuses_but_joints_are_skipped(self):
        capture = load_capture("extrude_plate")
        later = dict(capture["items"][0], index=2, name="X", type="MoveFeature", bodies_after=[], data={})
        capture["items"].append(later)
        self.assertIn("move", translate(capture).refusal["reason"])
        later["type"] = "Joint"
        self.assertIsNotNone(translate(capture).recipe)

    def test_handler_with_no_steps_is_skipped_with_its_note(self):
        def silent(item, ctx):
            ctx.note("Nothing to copy.")
            return []
        capture = load_capture("extrude_plate")
        capture["items"].append(dict(capture["items"][1], index=2, name="Thread1", type="ThreadFeature", data={}))
        result = translate(capture, {"ThreadFeature": silent})
        verdict = verdict_of(result, 2)
        self.assertEqual((verdict["verdict"], verdict["steps"], verdict["note"]), ("skipped", [], "Nothing to copy."))
        self.assertEqual(len(result.recipe["features"]), 1)


class UnreadableTest(unittest.TestCase):
    def test_each_unreadable_setting_refuses_at_the_extrude(self):
        for name in ("extrude_taper_unreadable", "extrude_thin_unreadable", "extrude_start_unreadable",
                     "extrude_extent_type_unreadable", "extrude_full_length_unreadable", "extrude_space_ambiguous"):
            result = translate_fixture(name)
            self.assertIsNone(result.recipe, name)
            self.assertEqual((result.refusal["index"], result.refusal["type"]), (1, "ExtrudeFeature"), name)

    def test_unreadable_through_all_direction_to_offset_and_to_plane_refuse(self):
        self.assertIsNone(variant("extrude_cut_through_one", lambda d: d["side_one"].update(positive=None)).recipe)
        self.assertIsNone(variant("extrude_to_plane", lambda d: d["side_one"].update(offset=None)).recipe)
        self.assertIsNone(variant("extrude_to_plane", lambda d: d["side_one"].update(plane=None)).recipe)

    def test_model_space_profile_translates_like_sketch_space(self):
        a = translate_fixture("extrude_space_model").recipe
        b = translate_fixture("extrude_plate").recipe
        self.assertEqual(a["features"][0]["sketch"], b["features"][0]["sketch"])

class RepeatabilityTest(unittest.TestCase):
    def ids_not_repeatable(self, name, edit=None):
        from lib.translator.context import Context
        capture = load_capture(name)
        if edit:
            edit(capture["items"][-1]["data"])
        holder = {}
        real = Context.__init__

        def init(self, cap, *rest):
            real(self, cap, *rest)
            holder["ctx"] = self

        Context.__init__ = init
        try:
            result = translate(capture)
        finally:
            Context.__init__ = real
        self.assertIsNotNone(result.recipe)
        for step in result.recipe["features"]:
            self.assertNotIn("_adjusts", step)
        return holder["ctx"].not_repeatable

    def test_steps_that_reach_a_face_or_the_far_side_are_not_repeatable(self):
        self.assertEqual(self.ids_not_repeatable("extrude_to_plane"), {"extrude_3"})
        self.assertEqual(self.ids_not_repeatable("extrude_cut_through_one"), {"extrude_3"})

    def test_fixed_length_steps_stay_repeatable(self):
        self.assertEqual(self.ids_not_repeatable("extrude_plate"), set())
        self.assertEqual(self.ids_not_repeatable("extrude_cut_through_two"), set())


class FixtureSchemaTest(unittest.TestCase):
    def test_every_translated_extrude_fixture_passes_the_schema(self):
        translated = 0
        for path in sorted(glob.glob(os.path.join(FIXTURES, "extrude_*.json"))):
            with open(path, encoding="utf-8") as f:
                result = translate(json.load(f))
            if result.recipe is not None:
                translated += 1
                self.assertEqual(check_recipe(result.recipe), [], os.path.basename(path))
        self.assertGreater(translated, 10)


if __name__ == "__main__":
    unittest.main()
