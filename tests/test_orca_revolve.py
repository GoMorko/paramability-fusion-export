"""Revolves in the Orca copy (`orca_translate/revolve.py`): the outline with a construction line on the axis, the
turning sense from the measured start face, the angle bound to its parameter, and what Orca cannot turn."""
import copy
import math
import unittest

from tests import context  # noqa: F401
from tests.orca_revolves import (caps, groove_both_sides, ring_on_rod, ring_with_hole, rect, symmetric_ring,
                                 two_rings_on_rod)
from tests.orca_sized import fixture, revolve_sized, table_of
from tests.test_orca_finishes import finish_item
from tests.probe_helpers import user

from lib.capture_model import gap_hints
from lib.orca_recipe.enums import BooleanMode, EntityType, FeatureType
from lib.orca_translate import FIXED, causes, translate
from lib.orca_translate.solid import Solid, Turned, seamed
from lib.orca_translate.place import plane_point


def revolve_of(result):
    (made,) = [f for f in result.recipe.features if f.type == FeatureType.REVOLVE]
    return made, result.recipe.features[made.sketch_ref]


def axis_of(made, sketch):
    """The turning axis in Orca coordinates: its point and its unit direction."""
    line = sketch.entities[made.revolve_axis_entity]
    a, b = plane_point(sketch.plane, line.p0), plane_point(sketch.plane, line.p1)
    d = [q - p for p, q in zip(a, b)]
    n = math.sqrt(sum(v * v for v in d))
    return a, [v / n for v in d]


def on_offset_plane(capture, profile):
    """Put the sketch of `profile` on Plane1, an offset of the origin XY plane by the user parameter `lift`."""
    params = capture.setdefault("parameters", {})
    params.setdefault("user", []).append(user("lift", "5 mm", 5.0))
    params.setdefault("model", []).append(
        {"name": "d_lift", "expression": "lift", "value": 0.5, "unit": "mm", "kind": "derived", "role": "",
         "dependency_parameters": ["lift"], "created_by": {"kind": "constructionPlane", "token": "cp1", "name": ""}})
    profile["reference"] = {"kind": "constructionPlane", "token": "cp1",
                            "definition": "ConstructionPlaneOffsetDefinition", "built_on": [{"origin": True}]}
    return capture


class RevolveTest(unittest.TestCase):
    def test_a_full_turn_names_a_construction_line_on_the_axis(self):
        result = translate(fixture("revolve_full"))
        made, sketch = revolve_of(result)
        line = sketch.entities[made.revolve_axis_entity]
        self.assertEqual((line.type, line.construction), (EntityType.LINE, True))
        self.assertEqual(made.revolve_axis_entity, len(sketch.entities) - 1)
        self.assertEqual((made.revolve_angle, made.mode), (360.0, BooleanMode.NEW))
        point, direction = axis_of(made, sketch)
        self.assertEqual([round(v, 9) for v in direction], [0.0, 1.0, 0.0])
        self.assertEqual([round(v, 9) for v in point], [round(v, 9) for v in result.place.point([0, 0, 0])])

    def test_the_turning_sense_follows_the_start_face(self):
        forward = axis_of(*revolve_of(translate(fixture("revolve_quarter"))))[1]
        backward = axis_of(*revolve_of(translate(fixture("revolve_quarter_reversed"))))[1]
        # A quarter turn about +Y takes +X to -Z, where revolve_quarter lies; the reversed one lies at +Z.
        self.assertEqual([round(v, 9) for v in forward], [0.0, 1.0, 0.0])
        self.assertEqual([round(v, 9) for v in backward], [0.0, -1.0, 0.0])

    def test_the_angle_follows_its_parameter(self):
        capture = revolve_sized()
        result = translate(capture, table_of(capture))
        made, _ = revolve_of(result)
        self.assertEqual((made.revolve_angle, made.expr), (90.0, {"revolve_angle": "turn_deg"}))
        self.assertEqual(result.parameters[0]["outcome"], "variable")

    def test_a_turn_to_both_sides_starts_half_its_angle_back_with_a_fixed_angle(self):
        capture = fixture("revolve_symmetric")
        result = translate(capture)
        made, sketch = revolve_of(result)
        self.assertEqual(made.revolve_angle, 120.0)
        # The sketch plane is turned 60 degrees back about the axis, so its normal leaves +Z.
        self.assertAlmostEqual(abs(sketch.plane.normal[2]), 0.5)

    def test_a_turn_of_half_a_circle_to_each_side_closes_the_ring(self):
        # Fusion's angle of a symmetric revolve is the turn to each side; 2 x 200 degrees leaves no start face.
        capture = fixture("revolve_symmetric")
        capture["items"][-1]["data"].update(extent={"kind": "angle", "angle_deg": 200, "symmetric": True},
                                            start_face_normal=None)
        result = translate(capture)
        made, sketch = revolve_of(result)
        self.assertEqual((made.revolve_angle, result.left_out), (360.0, []))
        self.assertAlmostEqual(abs(sketch.plane.normal[2]), 1.0)

    def test_the_made_faces_tell_the_turn_when_the_start_face_is_gone(self):
        # A join can merge the start face into a face of the part. A quarter turn about +Y ends with its end face
        # looking toward -X either way round, so the box of the faces the revolve made decides.
        for z, expected in ((-10, [0.0, 1.0, 0.0]), (10, [0.0, -1.0, 0.0])):
            capture = fixture("revolve_quarter")
            capture["items"][-1]["data"].update(start_face_normal=None, end_face_normal=[-1, 0, 0], made_box={
                "min": [0, 0, min(z, 0)], "max": [10, 20, max(z, 0)]})
            direction = axis_of(*revolve_of(translate(capture)))[1]
            self.assertEqual([round(v, 9) for v in direction], expected)
        capture = fixture("revolve_quarter")
        capture["items"][-1]["data"].update(start_face_normal=None, end_face_normal=[-1, 0, 0])
        self.assertEqual(len(translate(capture).left_out), 1)

    def test_caps_that_do_not_fit_the_turn_leave_the_revolve_out(self):
        capture = fixture("revolve_quarter")
        capture["items"][-1]["data"].update(end_face_normal=[1, 0, 0])
        self.assertEqual([g["index"] for g in translate(capture).left_out], [capture["items"][-1]["index"]])
    def test_a_turn_to_two_sides_starts_the_angle_of_one_side_back(self):
        # Turned 30 degrees one way and 60 the other about +Y: the start face at -60 degrees (side one turns the right
        # hand way) or at -30 degrees (the other way) puts the sketch plane there.
        for back in (60, 30):
            capture = fixture("revolve_two_sides")
            r = math.radians(-back)
            capture["items"][-1]["data"]["start_face_normal"] = [math.sin(r), 0.0, math.cos(r)]
            made, sketch = revolve_of(translate(capture))
            self.assertEqual(made.revolve_angle, 90.0)
            self.assertAlmostEqual(sketch.plane.normal[0], -math.sin(math.radians(back)))
            self.assertEqual([round(v, 9) for v in axis_of(made, sketch)[1]], [0.0, 1.0, 0.0])

    def test_a_turn_to_two_sides_that_does_not_tell_the_side_is_left_out(self):
        capture = fixture("revolve_two_sides")
        capture["items"][-1]["data"].update(start_face_normal=[-1.0, 0.0, 0.0])
        capture["items"][-1]["data"]["extent"].update(angle_one_deg=90.0, angle_two_deg=30.0)
        self.assertEqual([g["cause"] for g in translate(capture).left_out], [gap_hints.REVOLVE_SIDES])

    def test_sizes_that_move_the_sketch_plane_are_marked(self):
        capture = fixture("revolve_quarter")
        on_offset_plane(capture, capture["items"][-1]["data"]["profiles"][0])
        result = translate(capture, table_of(capture))
        self.assertEqual(len(revolve_of(result)), 2)
        self.assertEqual([p["outcome"] for p in result.parameters if p["name"] == "lift"], [FIXED])

    def test_a_cut_turned_into_the_part_is_written_and_one_that_misses_is_left_out(self):
        result = translate(fixture("revolve_cut_quarter"))
        made, _ = revolve_of(result)
        self.assertEqual(made.mode, BooleanMode.CUT)
        capture = fixture("revolve_cut_quarter")
        data = capture["items"][-1]["data"]
        data["axis"]["point"] = [0, 0, 105]
        for profile in data["profiles"]:
            profile["frame"]["origin"] = [0, 0, 105]
        self.assertEqual([(g["index"], g["cause"]) for g in translate(capture).left_out],
                         [(capture["items"][-1]["index"], causes.MISSES_PART)])

    def test_what_orca_cannot_turn_is_left_out_with_its_cause(self):
        across = fixture("revolve_full")
        across["items"][1]["data"]["axis"]["point"] = [7, 0, 0]
        cases = {"axis off the plane": (fixture("revolve_axis_off_plane"), causes.REVOLVE_AXIS),
                 "across the axis": (across, causes.REVOLVE_ACROSS_AXIS)}
        for name, (capture, cause) in cases.items():
            with self.subTest(name):
                self.assertEqual([(g["index"], g["cause"]) for g in translate(capture).left_out], [(1, cause)])


def revolves(result):
    return [f for f in result.recipe.features if f.type == FeatureType.REVOLVE]


def modes(result):
    """(type, mode) of each feature that builds or joins bodies, in order."""
    return [(f.type, f.mode) for f in result.recipe.features if f.type in (FeatureType.REVOLVE, FeatureType.BOOLEAN)]


def sized_result(capture):
    return translate(capture, table_of(capture))


class HolesAndOutlinesTest(unittest.TestCase):
    def test_a_first_body_with_a_hole_turns_the_hole_and_cuts_it_away(self):
        result = translate(ring_with_hole())
        self.assertEqual(result.left_out, [])
        self.assertEqual(modes(result), [(FeatureType.REVOLVE, BooleanMode.NEW), (FeatureType.REVOLVE, BooleanMode.CUT)])
        # Orca turns one closed loop per sketch: the hole has a sketch of its own.
        hole = result.recipe.features[revolves(result)[1].sketch_ref]
        self.assertEqual([e.type for e in hole.entities if not e.construction], [EntityType.CIRCLE])

    def test_a_holed_outline_on_the_part_is_a_tool_body_joined_by_a_boolean(self):
        result = translate(ring_on_rod())
        self.assertEqual(result.left_out, [])
        self.assertEqual(modes(result), [(FeatureType.REVOLVE, BooleanMode.NEW), (FeatureType.REVOLVE, BooleanMode.CUT),
                                         (FeatureType.BOOLEAN, BooleanMode.ADD)])
        made = result.recipe.features[-1]
        self.assertEqual((made.target_body, made.bool_tool_body), (0, 1))

    def test_a_pattern_of_a_holed_revolve_is_left_out_with_its_own_cause(self):
        capture = ring_on_rod()
        pattern = copy.deepcopy(fixture("rpattern_row")["items"][-1])
        pattern["index"], pattern["data"]["sources"] = 4, [3]
        capture["items"].append(pattern)
        result = translate(capture)
        (gap,) = [g for g in result.left_out if g["type"] == "RectangularPatternFeature"]
        self.assertEqual(gap["cause"], causes.NOT_REPEATABLE)
        self.assertNotIn("separate body", gap["reason"])
        self.assertEqual([f for f in result.recipe.features if f.type == FeatureType.PATTERN], [])

    def test_a_holed_cut_is_a_tool_body_cut_from_the_part(self):
        capture = ring_on_rod()
        capture["items"][-1]["data"]["operation"] = "cut"
        self.assertEqual(modes(translate(capture))[-1], (FeatureType.BOOLEAN, BooleanMode.CUT))

    def test_several_outlines_are_turned_one_by_one(self):
        result = translate(two_rings_on_rod())
        self.assertEqual(result.left_out, [])
        self.assertEqual(modes(result), [(FeatureType.REVOLVE, BooleanMode.ADD)] * 2)

    def test_an_intersect_of_several_outlines_joins_them_first(self):
        capture = two_rings_on_rod()
        capture["items"][-1]["data"]["operation"] = "intersect"
        self.assertEqual(modes(translate(capture)), [(FeatureType.REVOLVE, BooleanMode.NEW),
                                                     (FeatureType.REVOLVE, BooleanMode.ADD),
                                                     (FeatureType.BOOLEAN, BooleanMode.INTERSECT)])

    def test_a_cut_outline_that_misses_the_part_is_left_out_of_the_step(self):
        capture = two_rings_on_rod()
        data = capture["items"][-1]["data"]
        data["operation"] = "cut"
        data["profiles"][1]["loops"] = [{"outer": True, "curves": rect(10, 40, 16, 45)}]
        result = translate(capture)
        self.assertEqual((result.left_out, modes(result)), ([], [(FeatureType.REVOLVE, BooleanMode.CUT)]))

    def test_a_new_body_of_separate_outlines_is_left_out(self):
        capture = two_rings_on_rod()
        capture["items"] = capture["items"][:1] + capture["items"][2:]
        item = capture["items"][-1]
        item["data"]["operation"] = "newBody"
        item["bodies_after"].append({"token": "t2", "name": "Body2"})
        self.assertEqual([g["index"] for g in translate(capture).left_out], [item["index"]])

    def test_outlines_that_turn_different_ways_are_left_out_unless_the_turn_is_full(self):
        capture = ring_with_hole()
        item = capture["items"][-1]
        item["data"]["profiles"].append(dict(item["data"]["profiles"][0], loops=[
            {"outer": True, "curves": rect(-30, 0, -25, 10)}]))
        self.assertEqual(translate(capture).left_out, [])
        item["data"].update(extent={"kind": "angle", "angle_deg": 90, "symmetric": False},
                            start_face_normal=[0, -1, 0])
        self.assertEqual([g["cause"] for g in translate(capture).left_out], [causes.REVOLVE_OUTLINE_SIDES])


class SymmetricSizedTest(unittest.TestCase):
    def test_a_symmetric_angle_that_follows_sizes_is_two_halves_from_the_sketch(self):
        result = sized_result(symmetric_ring())
        halves = revolves(result)
        self.assertEqual([(f.flip, f.revolve_angle, f.expr) for f in halves],
                         [(flip, 45.0, {"revolve_angle": "min(half_deg, 180)"}) for flip in (False, True)])
        # The sketch stays on the XZ plane.
        self.assertAlmostEqual(abs(result.recipe.features[halves[0].sketch_ref].plane.normal[1]), 1.0)
        self.assertEqual(result.parameters[0]["outcome"], "variable")

    def test_an_intersect_keeps_the_angle_as_a_number(self):
        capture = ring_on_rod()
        capture["items"][-1] = symmetric_ring()["items"][1]
        capture["items"][-1].update(index=3)
        capture["items"][-1]["data"]["operation"] = "intersect"
        capture["parameters"] = symmetric_ring()["parameters"]
        result = sized_result(capture)
        self.assertEqual([(f.revolve_angle, f.expr) for f in revolves(result)], [(90.0, {})])
        self.assertEqual(result.parameters[0]["outcome"], FIXED)

    def test_a_cut_whose_half_misses_the_part_keeps_the_angle_as_a_number(self):
        capture = ring_on_rod()
        cut = symmetric_ring()["items"][1]
        cut.update(index=3)
        start, end = caps(45.0, cut=True)
        cut["data"].update(operation="cut", start_face_normal=start, end_face_normal=end)
        cut["data"]["profiles"][0]["loops"] = [{"outer": True, "curves": rect(10, 5, 14, 9)}]
        capture["items"][-1] = cut
        capture["parameters"] = symmetric_ring()["parameters"]
        both = sized_result(capture)
        self.assertEqual([f.flip for f in revolves(both)], [False, True])
        # A block on one side of the sketch plane only: the other half would cut nothing.
        capture["items"][1]["data"]["profiles"][0]["loops"] = [{"outer": True, "curves": rect(0, 0, 30, 30)}]
        capture["items"][1]["data"]["side_one"]["distance"] = 30.0
        capture["items"][1]["data"]["profiles"][0]["frame"]["origin"] = [-15, 0, 0]
        one = sized_result(capture)
        self.assertEqual([(f.revolve_angle, f.expr) for f in revolves(one)], [(90.0, {})])
        self.assertEqual(one.parameters[0]["outcome"], FIXED)

    def test_a_round_on_halves_joined_together_is_left_out_for_the_seam(self):
        top = [[15 * math.cos(math.radians(a)), 15 * math.sin(math.radians(a)), 10] for a in (-30, 0, 30)]
        for capture, cause in ((symmetric_ring(), causes.REVOLVE_SEAM),
                               (fixture("revolve_symmetric"), causes.EDGES_UNKNOWN)):
            capture["items"].append(finish_item(2, "FilletFeature", top, 1.0))
            result = sized_result(capture) if capture.get("parameters") else translate(capture)
            self.assertEqual([g["cause"] for g in result.left_out], [cause])

    def test_seamed_finds_a_seam_inside_bodies(self):
        frame = {"origin": [0, 0, 0], "x": [1, 0, 0], "y": [0, 1, 0], "z": [0, 0, 1]}
        shape = Turned(frame, [rect(5, 0, 10, 5)], [0, 0, 0], [0, 1, 0], 90)
        body = Solid([("add", Solid([("add", shape)]))])
        self.assertFalse(seamed(body))
        shape.seam = True
        self.assertTrue(seamed(body))


class OverlapAndLimitTest(unittest.TestCase):
    def test_a_cut_outline_whose_turn_lies_inside_an_earlier_one_is_dropped(self):
        result = translate(groove_both_sides())
        self.assertEqual((result.left_out, modes(result)), ([], [(FeatureType.REVOLVE, BooleanMode.CUT)]))
        self.assertEqual(len(result.notes), 1)

    def test_a_cut_outline_that_would_remove_nothing_after_an_earlier_one_leaves_the_step_out(self):
        # The mirror reaches past the rod: not inside the first turn, and it would cut nothing after it.
        self.assertEqual([g["cause"] for g in translate(groove_both_sides(reach=14.0)).left_out],
                         [causes.REVOLVE_OVERLAP])

    def test_a_join_of_outlines_whose_turns_overlap_is_left_out(self):
        capture = two_rings_on_rod()
        data = capture["items"][-1]["data"]
        data["profiles"][1]["loops"] = [{"outer": True, "curves": rect(-20, 0, -10, 5)}]
        self.assertEqual([g["cause"] for g in translate(capture).left_out], [causes.REVOLVE_OVERLAP])

    def test_halves_that_would_cut_the_same_ring_keep_the_angle_as_a_number(self):
        capture = groove_both_sides()
        capture["items"][-1]["data"]["extent"] = {"kind": "angle", "angle_deg": 180.0, "symmetric": True}
        capture["parameters"] = symmetric_ring()["parameters"]
        capture["items"][-1]["data"]["params"] = symmetric_ring()["items"][1]["data"]["params"]
        result = sized_result(capture)
        self.assertEqual([(f.revolve_angle, f.flip, f.expr) for f in revolves(result)], [(360.0, False, {})])
        self.assertEqual((result.left_out, result.parameters[0]["outcome"]), ([], FIXED))

    def test_a_turned_angle_has_its_limits_on_the_parameter_line(self):
        result = sized_result(revolve_sized())
        (limit,) = [w for w in result.parameters[0]["follows"] if getattr(w, "high", None) is not None]
        self.assertEqual((limit.low, limit.high), (0.01, 360.0))

    def test_cut_halves_tell_how_far_the_angle_may_shrink_before_a_half_misses(self):
        # A block on each side of the sketch plane, 5 mm from it: the halves of the outline (out to radius 14) meet it
        # only past asin(5 / 14) = 20.9 degrees.
        capture = ring_on_rod()
        block = capture["items"][1]["data"]["profiles"][0]
        block["loops"] = [{"outer": True, "curves": rect(0, 5, 30, 30)}]
        capture["items"][1]["data"]["profiles"].append(dict(block, loops=[
            {"outer": True, "curves": rect(0, -30, 30, -5)}]))
        cut = symmetric_ring()["items"][1]
        cut.update(index=3)
        start, end = caps(45.0, cut=True)
        cut["data"].update(operation="cut", start_face_normal=start, end_face_normal=end)
        cut["data"]["profiles"][0]["loops"] = [{"outer": True, "curves": rect(10, 5, 14, 9)}]
        capture["items"][-1] = cut
        capture["parameters"] = symmetric_ring()["parameters"]
        result = sized_result(capture)
        self.assertEqual([f.flip for f in revolves(result)], [False, True])
        lows = [w.low for w in result.parameters[0]["follows"] if getattr(w, "low", None) is not None]
        self.assertEqual(len(lows), 1)
        self.assertTrue(20.9 <= lows[0] < 23.0, lows)


if __name__ == "__main__":
    unittest.main()
