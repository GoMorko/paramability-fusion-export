import copy
import glob
import json
import math
import os
import unittest

from tests import context  # noqa: F401
from tests.schema_check import check_recipe
from tests.translator_helpers import left_out
from tests.translator_helpers import FIXTURES, assert_schema_ok, load_capture, translate_fixture, variant, verdict_of

from tests.test_translate_start_from_face import as_extrude

from lib.capture_model import gap_hints
from lib.design_model import design
from lib.translator import extrude, translate
from lib.translator.result import StepResult


def under_test(result, index):
    """The recipe steps written for the timeline item at `index`."""
    return [s for s in result.recipe["features"] if s["id"] == "extrude_%d" % index or s["id"].startswith("extrude_%d_" % index)]


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
        self.assertIsNotNone(left_out(result))
        self.assertEqual(left_out(result)["index"], 3)

    def test_start_at_a_distance_from_a_plane_refuses(self):
        # Which way Fusion measures the offset from the plane is not read, so the start cannot be placed.
        plane = {"point": [0, 0, 14], "normal": [0, 0, -1]}
        held = {"start.offset": {"name": "d9", "expression": "2 mm", "value": 2.0}}
        result = variant("extrude_start_offset", lambda d: d.update(
            start={"kind": "fromEntity", "plane": plane}, end_offset=8.0, params=held))
        self.assertEqual(left_out(result)["index"], 3)
        self.assertEqual([g["hint"] for g in result.gaps], [gap_hints.HINTS[gap_hints.EXTRUDE_END_FACE]])

    def test_two_sides_to_planes_on_one_side_refuse(self):
        def to(height):
            return {"kind": "toEntity", "offset": 0.0, "plane": {"point": [0, 0, height], "normal": [0, 0, 1]}}
        result = variant("extrude_to_plane", lambda d: d.update(extent_type="two", side_one=to(12.0),
                                                               side_two=to(16.0)))
        self.assertEqual(left_out(result)["index"], 3)


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
        def inside(d):
            d.update(side_one={"kind": "throughAll", "positive": False, "taper_deg": 0.0}, end_offset=None)
            d["profiles"][0]["frame"]["origin"] = [20, 0, 0]  # material on both sides of the sketch

        (step,) = under_test(variant("extrude_cut_through_one", inside), 3)
        self.assertEqual(step["sketch"]["on"]["normal"], [-1, 0, 0])
        self.assertGreaterEqual(step["distance"], 1)

    def test_a_cut_through_stored_toward_empty_space_goes_through_the_part_with_a_note(self):
        result = variant("extrude_cut_through_one", lambda d: d.update(
            side_one={"kind": "throughAll", "positive": False, "taper_deg": 0.0}, end_offset=None))
        (step,) = under_test(result, 3)
        self.assertEqual(step["sketch"]["on"]["normal"], [1, 0, 0])
        self.assertTrue(verdict_of(result, 3)["note"])

    def test_a_cut_through_all_that_narrows_ends_just_past_the_part(self):
        # Fusion's -1 degrees leans the walls in; the side walls of the cut show that lean.
        lean = -math.sin(math.radians(1.0))
        result = variant("extrude_cut_through_one", lambda d: d.update(
            side_one={"kind": "throughAll", "positive": True, "taper_deg": -1.0}, end_offset=None,
            side_leans=[lean] * 4))
        (step,) = under_test(result, 3)
        self.assertEqual((step["extent"], step["taperDeg"], step["distance"]), ("oneSide", 1, 41))
        assert_schema_ok(self, result.recipe)

    def test_a_cut_through_all_that_widens_reaches_well_past_the_part(self):
        lean = math.sin(math.radians(1.0))
        result = variant("extrude_cut_through_one", lambda d: d.update(
            side_one={"kind": "throughAll", "positive": True, "taper_deg": 1.0}, end_offset=None,
            side_leans=[lean] * 4))
        (step,) = under_test(result, 3)
        self.assertEqual(step["taperDeg"], -1)
        self.assertGreater(step["distance"], 41)

    def test_a_cut_through_all_whose_outline_closes_inside_the_part_is_left_out(self):
        lean = -math.sin(math.radians(10.0))
        result = variant("extrude_cut_through_one", lambda d: d.update(
            side_one={"kind": "throughAll", "positive": True, "taper_deg": -10.0}, end_offset=None,
            side_leans=[lean] * 4))
        self.assertIn("closes before it passes the part", left_out(result)["reason"])

    def test_a_tapered_cut_through_all_stored_toward_empty_space_checks_the_walls_of_the_side_it_cuts(self):
        lean = -math.sin(math.radians(1.0))
        result = variant("extrude_cut_through_one", lambda d: d.update(
            side_one={"kind": "throughAll", "positive": False, "taper_deg": -1.0}, end_offset=None,
            side_leans=[lean] * 4))
        (step,) = under_test(result, 3)
        self.assertEqual((step["sketch"]["on"]["normal"], step["taperDeg"]), ([1, 0, 0], 1))

    def test_a_cut_through_all_toward_a_thin_wall_at_its_start_keeps_its_direction(self):
        def thin(d):
            d.update(end_offset=None)
            d["profiles"][0]["frame"]["origin"] = [39.5, 0, 0]  # 0.5 mm of the plate ahead, the rest behind

        (step,) = under_test(variant("extrude_cut_through_one", thin), 3)
        self.assertEqual(step["sketch"]["on"]["normal"], [1, 0, 0])

    def test_a_tapered_cut_through_all_whose_walls_show_its_stored_direction_keeps_it(self):
        lean = math.sin(math.radians(1.0))  # the walls of a cut toward -x that narrows
        result = variant("extrude_cut_through_one", lambda d: d.update(
            side_one={"kind": "throughAll", "positive": False, "taper_deg": -1.0}, end_offset=None,
            side_leans=[lean] * 4))
        (step,) = under_test(result, 3)
        self.assertEqual(step["sketch"]["on"]["normal"], [-1, 0, 0])

    def test_a_cut_through_all_both_ways_with_a_taper_is_left_out(self):
        result = variant("extrude_cut_through_one", lambda d: d.update(
            extent_type="symmetric", symmetric=None, end_offset=None,
            side_one={"kind": "throughAll", "positive": True, "taper_deg": 2.0}))
        self.assertIn("both ways", left_out(result)["reason"])

    def test_through_all_join_refuses(self):
        result = variant("extrude_cut_through_one", lambda d: d.update(operation="join"))
        self.assertIn("only copied for cuts", left_out(result)["reason"])

    def test_through_all_without_a_measured_part_refuses(self):
        result = variant("extrude_cut_through_one", lambda d: d.update(target_box_before=None))
        self.assertIsNotNone(left_out(result))

    def test_to_plane_measures_the_distance_and_adds_its_offset(self):
        (step,) = under_test(translate_fixture("extrude_to_plane"), 3)
        self.assertEqual((step["extent"], step["distance"], step["combine"]), ("oneSide", 10, "add"))
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
        self.assertIsNotNone(left_out(result))
        self.assertEqual((left_out(result)["index"], left_out(result)["name"]), (3, "Extrude2"))

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
        self.assertIn("several bodies", extrude.handle(None, design.as_read(item)).reason)

    def test_profiles_must_share_one_plane_and_facing(self):
        result = translate_fixture("extrude_profiles_two_planes")
        self.assertIsNotNone(left_out(result))
        self.assertIn("different planes", left_out(result)["reason"])

        capture = load_capture("extrude_profiles_two_planes")
        capture["items"][-1]["data"]["profiles"][1]["frame"]["origin"] = [0, 0, 10]
        self.assertEqual([s["id"] for s in under_test(translate(capture), 3)], ["extrude_3", "extrude_3_2"])

        frame = capture["items"][-1]["data"]["profiles"][1]["frame"]
        frame.update(z=[0, 0, -1], y=[0, -1, 0])
        self.assertIsNotNone(left_out(translate(capture)))


class MeasuredLengthTest(unittest.TestCase):
    def test_one_side_length_must_match_the_measured_end(self):
        result = variant("extrude_plate", lambda d: d.update(end_offset=12.0))
        self.assertIn("does not match its length", result.refusal["reason"])

    def test_symmetric_distance_is_checked_as_half_length(self):
        ok = variant("extrude_symmetric_half", lambda d: d.update(end_offset=5.0))
        self.assertEqual(ok.recipe["features"][0]["distance"], 10)
        wrong = variant("extrude_symmetric_half", lambda d: d.update(end_offset=10.0))
        self.assertIsNone(wrong.recipe)

    def test_two_sided_end_face_must_lie_at_the_end_of_a_side(self):
        swapped = variant("extrude_two_sides", lambda d: d.update(end_offset=4.0))
        self.assertIsNone(swapped.recipe)
        ok = variant("extrude_two_sides", lambda d: d.update(end_offset=-6.0))
        self.assertEqual(ok.recipe["features"][0]["sketch"]["on"]["normal"], [0, 0, -1])

    def test_two_sided_end_face_at_the_end_of_side_two_keeps_the_stored_direction(self):
        ok = variant("extrude_two_sides", lambda d: d.update(end_offset=-4.0))
        self.assertEqual(ok.recipe["features"][0]["sketch"]["on"]["normal"], [0, 0, 1])

    def test_a_nearer_face_is_accepted_only_when_its_own_side_passes_the_part(self):
        def cut(low, high):
            return lambda d: d.update(extent_type="two", end_offset=-4.0, target_box_before={
                "min": [low, 0.0, 0.0], "max": [high, 20.0, 10.0]},
                side_one={"kind": "distance", "distance": 60.0, "taper_deg": 0.0},
                side_two={"kind": "distance", "distance": 10.0, "taper_deg": 0.0})
        # The face 4 behind the sketch lies on side two (10 long). Side one (60 long) passing says nothing about it.
        for low, high, copied in ((-8.0, 40.0, True), (-40.0, 40.0, False), (-40.0, 80.0, False)):
            with self.subTest(low=low, high=high):
                result = variant("extrude_cut_through_one", cut(low, high))
                if copied:
                    self.assertEqual(len(under_test(result, 3)), 2)
                else:
                    self.assertIsNotNone(left_out(result, 3))

    def test_a_measured_face_that_is_not_an_end_cap_is_no_measure(self):
        def cut(**face):
            return lambda d: d.update(extent_type="two", end_offset=-4.0, target_box_before={
                "min": [-40.0, 0.0, 0.0], "max": [40.0, 20.0, 10.0]},
                side_one={"kind": "distance", "distance": 60.0, "taper_deg": 0.0},
                side_two={"kind": "distance", "distance": 10.0, "taper_deg": 0.0}, **face)
        # A small wall the cut made where it went through a rib: the stored lengths stand.
        self.assertEqual(len(under_test(variant("extrude_cut_through_one", cut(end_area=0.5)), 3)), 2)
        self.assertEqual(len(under_test(variant("extrude_cut_through_one", cut(end_normal=[0, 0, 1])), 3)), 2)
        # A face parallel to the sketch is a cap, and it is nearer than the end of a side inside the part.
        self.assertIsNotNone(left_out(variant("extrude_cut_through_one", cut(end_normal=[-1, 0, 0])), 3))

    def test_a_nearer_face_of_a_symmetric_cut_is_accepted_when_its_half_passes_the_part(self):
        def cut(low):
            return lambda d: d.update(extent_type="symmetric", end_offset=-4.0, side_one=None, target_box_before={
                "min": [low, 0.0, 0.0], "max": [40.0, 20.0, 10.0]},
                symmetric={"distance": 10.0, "full_length": False, "taper_deg": 0.0})
        self.assertEqual(len(under_test(variant("extrude_cut_through_one", cut(-8.0)), 3)), 1)
        self.assertIsNotNone(left_out(variant("extrude_cut_through_one", cut(-40.0)), 3))

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
        self.assertIsNotNone(left_out(result))

    def test_a_cut_past_the_part_is_not_checked_against_a_nearer_wall(self):
        def cut(distance):
            return lambda d: d.update(side_one={"kind": "distance", "distance": distance, "taper_deg": 0.0}, end_offset=30.0)
        self.assertEqual(under_test(variant("extrude_cut_through_one", cut(60.0)), 3)[0]["distance"], 60)
        self.assertIsNotNone(left_out(variant("extrude_cut_through_one", cut(35.0))))


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
        self.assertIsNotNone(left_out(translate(capture)))

    def test_two_sided_cut_cuts_twice(self):
        def edit(d):
            d.update(operation="cut", extent_type="two", side_one={"kind": "distance", "distance": 3.0, "taper_deg": 0.0},
                     side_two={"kind": "distance", "distance": 2.0, "taper_deg": 0.0}, end_offset=3.0)
        steps = under_test(variant("extrude_to_plane", edit), 3)
        self.assertEqual([s["combine"] for s in steps], ["cut", "cut"])

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
        for name in ("extrude_thin", "extrude_face_profile", "extrude_new_component", "extrude_open_spline"):
            result = translate_fixture(name)
            self.assertIsNone(result.recipe, name)
            self.assertEqual((result.refusal["index"], result.refusal["type"]), (1, "ExtrudeFeature"), name)
            reasons[name] = result.refusal["reason"]
        self.assertEqual(len(set(reasons.values())), 4)


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

    def test_read_error_refuses(self):
        result = translate_fixture("extrude_read_error")
        self.assertEqual(result.refusal["index"], 1)

    def test_unknown_type_without_bodies_refuses_but_joints_are_skipped(self):
        capture = load_capture("extrude_plate")
        later = dict(capture["items"][0], index=2, name="X", type="MoveFeature", bodies_after=[], data={})
        capture["items"].append(later)
        self.assertIn("move", translate(capture).refusal["reason"])
        later["type"] = "Joint"
        self.assertIsNotNone(translate(capture).recipe)

    def test_handler_with_no_steps_is_skipped_with_its_note(self):
        def silent(ctx, step):
            ctx.note("Nothing to copy.")
            return StepResult()
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
        self.assertIsNotNone(left_out(variant("extrude_cut_through_one", lambda d: d["side_one"].update(positive=None))))
        self.assertIsNotNone(left_out(variant("extrude_to_plane", lambda d: d["side_one"].update(offset=None))))
        self.assertIsNotNone(left_out(variant("extrude_to_plane", lambda d: d["side_one"].update(plane=None))))

    def test_model_space_profile_translates_like_sketch_space(self):
        a = translate_fixture("extrude_space_model").recipe
        b = translate_fixture("extrude_plate").recipe
        self.assertEqual(a["features"][0]["sketch"], b["features"][0]["sketch"])

class RepeatabilityTest(unittest.TestCase):
    def ids_not_repeatable(self, name):
        """Ids of the steps the extrude handler marks as not repeatable by a pattern or mirror."""
        results = []

        def recording(ctx, step):
            results.append(extrude.handle(ctx, step))
            return results[-1]

        self.assertIsNotNone(translate(load_capture(name), {"ExtrudeFeature": recording}).recipe)
        return {e.step["id"] for r in results for e in r.entries if not e.repeatable}

    def test_steps_that_reach_a_face_or_the_far_side_are_not_repeatable(self):
        self.assertEqual(self.ids_not_repeatable("extrude_to_plane"), {"extrude_3"})
        self.assertEqual(self.ids_not_repeatable("extrude_cut_through_one"), {"extrude_3"})

    def test_fixed_length_steps_stay_repeatable(self):
        self.assertEqual(self.ids_not_repeatable("extrude_plate"), set())
        self.assertEqual(self.ids_not_repeatable("extrude_cut_through_two"), set())


class FreeOutlineVolumeTest(unittest.TestCase):
    """An extrude of text or spline outlines is checked against the volume Fusion made (plain outlines are not)."""

    TEXT = ("extrude_text", [175.848813, 80.0], 3.0)
    SPLINE = ("extrude_spline", [30.0], 10.0)
    PART = 9600.0

    def run_with(self, case, change, operation=None):
        """Translate the fixture with the measured volume change `change(expected)` for its outlines. A join or cut
        runs on the lid of the emboss fixture, rewritten as a one millimetre extrude of its text."""
        name, areas, length = case
        capture = as_extrude(load_capture("emboss_text"), index=3) if operation else load_capture(name)
        data = capture["items"][3 if operation else 1]["data"]
        before = self.PART if operation else 0.0
        expected = sum(areas) * (1.0 if operation else length)
        data.update(areas=areas, volume_before=before, volume_after=before + change(expected))
        if operation:
            data["operation"] = operation
        return translate(capture)

    def test_a_new_body_that_has_the_outline_volume_is_copied(self):
        for case in (self.TEXT, self.SPLINE):
            self.assertIsNotNone(self.run_with(case, lambda expected: expected).recipe)

    def test_a_new_body_with_more_or_less_volume_than_its_outlines_is_refused(self):
        for case in (self.TEXT, self.SPLINE):
            for factor in (1.5, 0.7):
                result = self.run_with(case, lambda expected: expected * factor)
                self.assertIsNone(result.recipe)
                self.assertEqual(result.refusal["index"], 1)

    def test_a_volume_that_was_not_measured_refuses(self):
        capture = load_capture("extrude_text")
        capture["items"][1]["data"].update(areas=[175.848813, 80.0], volume_before=0.0, volume_after=None)
        self.assertIsNone(translate(capture).recipe)

    def test_a_capture_without_the_measured_values_is_copied_as_before(self):
        self.assertIsNotNone(translate(load_capture("extrude_text")).recipe)

    def test_a_join_may_lose_volume_to_the_part_but_never_gain_more_than_its_outlines(self):
        self.assertIsNotNone(self.run_with(self.TEXT, lambda expected: expected, "join").recipe)
        self.assertIsNotNone(self.run_with(self.TEXT, lambda expected: 0.5 * expected, "join").recipe)
        self.assertIsNotNone(left_out(self.run_with(self.TEXT, lambda expected: 1.4 * expected, "join")))
        self.assertIsNotNone(left_out(self.run_with(self.TEXT, lambda expected: -1.0, "join")))

    def test_a_cut_that_removes_more_than_its_outlines_is_refused(self):
        self.assertIsNotNone(self.run_with(self.TEXT, lambda expected: -0.5 * expected, "cut").recipe)
        self.assertIsNotNone(left_out(self.run_with(self.TEXT, lambda expected: -1.4 * expected, "cut")))

    def test_plain_outlines_are_not_checked(self):
        capture = load_capture("extrude_plate")
        capture["items"][1]["data"].update(areas=[800.0], volume_before=0.0, volume_after=1.0)
        self.assertIsNotNone(translate(capture).recipe)


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
