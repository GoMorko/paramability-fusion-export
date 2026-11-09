import math
import unittest

from tests import context  # noqa: F401
from tests.translator_helpers import assert_schema_ok, close, load_capture, steps_of, translate_fixture

from lib.translator import translate, vec


def verdict_of(result, index):
    return [v for v in result.items if v["index"] == index][0]


def variant(name, edit):
    """Translate a fixture after `edit(item)` changed its last item."""
    capture = load_capture(name)
    edit(capture["items"][-1])
    return translate(capture)


def sweep_midpoint(step):
    """Where the middle of the sketch outline ends up halfway through the turn, in model coordinates."""
    on = step["sketch"]["on"]
    x = on["xDir"]
    y = vec.cross(on["normal"], x)

    def world(p):
        return vec.add(on["origin"], vec.add(vec.scale(x, p[0]), vec.scale(y, p[1])))

    axis = step["axis"]
    point = world(axis["point"])
    direction = vec.add(vec.scale(x, axis["dir"][0]), vec.scale(y, axis["dir"][1]))
    return vec.rotate(world(step["sketch"]["outer"]["center"]), direction, step.get("angleDeg", 360) / 2.0, point)


def revolves(name):
    result = translate_fixture(name)
    assert result.recipe, result.refusal
    return steps_of(result.recipe, "revolve")


class RevolveTest(unittest.TestCase):
    def test_profile_with_an_uncertain_curve_space_is_refused(self):
        for space in ("ambiguous", None):
            result = variant("revolve_full", lambda item, space=space: item["data"]["profiles"][0].update(space=space))
            self.assertIsNone(result.recipe)
            self.assertIn("could not be placed", result.refusal["reason"])
        ok = variant("revolve_full", lambda item: item["data"]["profiles"][0].update(space="model"))
        self.assertIsNotNone(ok.recipe)

    def test_other_or_face_profile_entries_are_refused(self):
        for entry in ({"kind": "other", "type": "Unknown"}, {"face": True, "type": "BRepFace"}):
            result = variant("revolve_full", lambda item, entry=entry: item["data"].update(profiles=[entry]))
            self.assertIsNone(result.recipe)
            self.assertIn("flat face", result.refusal["reason"])

    def test_full_turn_has_no_angle(self):
        result = translate_fixture("revolve_full")
        (step,) = result.recipe["features"]
        self.assertNotIn("angleDeg", step)
        self.assertEqual((step["axis"], step["combine"]), ({"point": [0, 0], "dir": [0, 1]}, "new"))
        self.assertEqual(step["sketch"]["outer"], {"kind": "rect", "center": [7.5, 10], "width": 5, "height": 20})
        self.assertEqual(step["sketch"]["on"], {"origin": [0, 0, 0], "normal": [0, 0, 1], "xDir": [1, 0, 0]})
        self.assertEqual(verdict_of(result, 1)["verdict"], "translated")
        assert_schema_ok(self, result.recipe)

    def test_quarter_keeps_the_axis_when_the_start_face_agrees(self):
        (step,) = revolves("revolve_quarter")
        self.assertEqual((step["angleDeg"], step["axis"]["dir"]), (90, [0, 1]))
        # The new solid sweeps down from the sketch plane, where its start face points up.
        self.assertLess(sweep_midpoint(step)[2], -1)

    def test_quarter_negates_the_axis_when_the_start_face_is_flipped(self):
        (step,) = revolves("revolve_quarter_reversed")
        self.assertEqual((step["angleDeg"], step["axis"]["dir"]), (90, [0, -1]))
        self.assertGreater(sweep_midpoint(step)[2], 1)

    def test_part_turn_without_a_measured_start_face_refuses(self):
        result = variant("revolve_quarter", lambda i: i["data"].update(start_face_normal=None))
        self.assertIsNone(result.recipe)
        self.assertIn("turning direction", result.refusal["reason"])

    def test_symmetric_turns_the_placement_about_the_axis(self):
        (step,) = revolves("revolve_symmetric")
        half = math.radians(60)
        on = step["sketch"]["on"]
        self.assertTrue(close(on["xDir"], [math.cos(half), 0, math.sin(half)], 1e-8))
        self.assertTrue(close(on["normal"], [-math.sin(half), 0, math.cos(half)], 1e-8))
        self.assertEqual((step["angleDeg"], step["axis"]["dir"]), (120, [0, 1]))
        self.assertEqual(step["sketch"]["outer"], {"kind": "rect", "center": [7.5, 10], "width": 5, "height": 20})

    def test_symmetric_checks_the_start_face_against_half_the_angle(self):
        wrong = variant("revolve_symmetric", lambda i: i["data"].update(start_face_normal=[0, 0, 1]))
        self.assertIsNone(wrong.recipe)
        self.assertIn("symmetric", wrong.refusal["reason"])
        missing = variant("revolve_symmetric", lambda i: i["data"].update(start_face_normal=None))
        self.assertIsNone(missing.recipe)

    def test_two_sides_refuse(self):
        result = translate_fixture("revolve_two_sides")
        self.assertIsNone(result.recipe)
        self.assertEqual((result.refusal["index"], result.refusal["type"]), (1, "RevolveFeature"))

    def test_cut_start_face_points_along_the_travel(self):
        result = translate_fixture("revolve_cut_quarter")
        step = result.recipe["features"][1]
        self.assertEqual((step["combine"], step["angleDeg"], step["axis"]["dir"]), ("cut", 90, [0, -1]))
        # The cut must sweep up into the plate (z above its sketch plane at 5), not down out of it.
        self.assertGreater(sweep_midpoint(step)[2], 5 + 1)
        assert_schema_ok(self, result.recipe)

    def test_cut_with_the_start_face_pointing_down_sweeps_down(self):
        result = variant("revolve_cut_quarter", lambda i: i["data"].update(start_face_normal=[0, 0, -1]))
        step = result.recipe["features"][1]
        self.assertEqual(step["axis"]["dir"], [0, 1])
        self.assertLess(sweep_midpoint(step)[2], 5 - 1)

    def test_axis_off_the_sketch_plane_refuses_unless_projected(self):
        refused = translate_fixture("revolve_axis_off_plane")
        self.assertIsNone(refused.recipe)
        self.assertEqual(refused.refusal["index"], 1)
        projected = variant("revolve_axis_off_plane", lambda i: i["data"].update(project_axis=True))
        self.assertEqual(projected.recipe["features"][0]["axis"], {"point": [0, 0], "dir": [0, 1]})
        assert_schema_ok(self, projected.recipe)

    def test_tilted_axis_is_projected_onto_the_plane(self):
        result = variant("revolve_full", lambda i: i["data"].update(
            project_axis=True, axis={"point": [0, 0, 0], "dir": [0, 3, 4]}))
        self.assertEqual(result.recipe["features"][0]["axis"]["dir"], [0, 1])

    def test_cut_on_an_existing_body(self):
        result = translate_fixture("revolve_cut")
        self.assertEqual([s["combine"] for s in result.recipe["features"]], ["new", "cut"])
        self.assertEqual(result.recipe["features"][1]["kind"], "revolve")
        assert_schema_ok(self, result.recipe)

    def test_refusals(self):
        cases = {
            "read error": lambda i: i["data"].clear() or i["data"].update(read_error="boom"),
            "other axis": lambda i: i["data"].update(axis={"kind": "other"}),
            "other extent": lambda i: i["data"].update(extent={"kind": "other", "type": "X"}),
            "new component": lambda i: i["data"].update(operation="newComponent"),
            "face profile": lambda i: i["data"].update(profiles=[{"face": True, "type": "BRepFace"}]),
            "curve of kind other": lambda i: i["data"]["profiles"][0]["loops"][0].update(
                curves=[{"kind": "other", "type": "NurbsCurve3D", "start": [0, 0], "end": [1, 0], "samples": []}]),
        }
        for label, edit in cases.items():
            with self.subTest(label):
                result = variant("revolve_full", edit)
                self.assertIsNone(result.recipe)
                self.assertEqual(result.refusal["type"], "RevolveFeature")


class HoleTest(unittest.TestCase):
    def test_through_hole(self):
        result = translate_fixture("hole_through")
        step = steps_of(result.recipe, "hole")[0]
        self.assertEqual((step["origin"], step["direction"], step["diameter"], step["depth"]),
                         ([10, 10, 10], [0, 0, -1], 5, None))
        self.assertEqual(verdict_of(result, 3)["verdict"], "translated")
        assert_schema_ok(self, result.recipe)

    def test_blind_tip_is_a_revolve_cut_of_the_drill_profile(self):
        result = translate_fixture("hole_blind_tip")
        step = steps_of(result.recipe, "revolve")[0]
        self.assertEqual(step["combine"], "cut")
        self.assertEqual(step["axis"], {"point": [0, 0], "dir": [0, 1]})
        self.assertNotIn("angleDeg", step)
        points = step["sketch"]["outer"]["points"]
        self.assertEqual(len(points), 4)
        self.assertEqual(points[:3], [[0, -0.01], [2.5, -0.01], [2.5, 8]])
        self.assertAlmostEqual(points[3][1], 8 + 2.5 / math.tan(math.radians(59)), places=8)
        on = step["sketch"]["on"]
        self.assertEqual(on["origin"], [10, 10, 10])
        # Sketch y (normal x xDir) runs along the hole direction.
        self.assertTrue(close(vec.cross(on["normal"], on["xDir"]), [0, 0, -1], 1e-9))
        assert_schema_ok(self, result.recipe)

    def test_blind_flat_is_a_plain_hole(self):
        step = steps_of(translate_fixture("hole_blind_flat").recipe, "hole")[0]
        self.assertEqual(step["depth"], 8)

    def test_counterbore_blind_has_six_points_with_the_step_at_its_depth(self):
        step = steps_of(translate_fixture("hole_counterbore_blind").recipe, "revolve")[0]
        points = step["sketch"]["outer"]["points"]
        self.assertEqual(points[:5], [[0, -0.01], [4.5, -0.01], [4.5, 3], [2.5, 3], [2.5, 8]])
        self.assertEqual(len(points), 6)

    def test_counterbore_through(self):
        result = translate_fixture("hole_counterbore_through")
        step = steps_of(result.recipe, "hole")[0]
        self.assertEqual(step["counterbore"], {"diameter": 9, "depth": 3})
        self.assertEqual(verdict_of(result, 3)["verdict"], "translated")
        assert_schema_ok(self, result.recipe)

    def test_countersink_through(self):
        result = translate_fixture("hole_countersink_through")
        self.assertEqual(steps_of(result.recipe, "hole")[0]["countersink"], {"diameter": 10, "angleDeg": 90})
        assert_schema_ok(self, result.recipe)

    def test_countersink_blind_tip_profile(self):
        result = variant("hole_blind_tip", lambda i: i["data"].update(
            hole_type="countersink", countersink={"diameter": 10.0, "angle_deg": 90.0}))
        points = steps_of(result.recipe, "revolve")[0]["sketch"]["outer"]["points"]
        self.assertEqual(points[1], [5.01, -0.01])
        self.assertEqual(points[2], [2.5, 2.5])
        self.assertEqual(len(points), 5)
        assert_schema_ok(self, result.recipe)

    def test_three_points_make_three_steps(self):
        result = translate_fixture("hole_three_points")
        self.assertEqual([s["id"] for s in steps_of(result.recipe, "hole")], ["hole_3", "hole_3_2", "hole_3_3"])
        self.assertEqual([s["origin"] for s in steps_of(result.recipe, "hole")], [[8, 6, 10], [20, 10, 10], [32, 14, 10]])
        self.assertEqual(verdict_of(result, 3)["verdict"], "translated")

    def test_direction_is_negated_when_the_measured_end_lies_behind(self):
        result = translate_fixture("hole_direction_disagrees")
        self.assertEqual(steps_of(result.recipe, "hole")[0]["direction"], [0, 0, -1])
        self.assertEqual(verdict_of(result, 3)["verdict"], "translatedWithNote")

    def test_measured_size_mismatch_notes(self):
        def edit(i):
            i["data"]["side_cylinders"][0]["radius"] = 3.0
        result = variant("hole_through", edit)
        self.assertEqual(steps_of(result.recipe, "hole")[0]["diameter"], 5)
        self.assertEqual(verdict_of(result, 3)["verdict"], "translatedWithNote")

    def test_tapped_modeled_refuses(self):
        result = translate_fixture("hole_tapped_modeled")
        self.assertIsNone(result.recipe)
        self.assertEqual((result.refusal["index"], result.refusal["type"]), (3, "HoleFeature"))

    def test_tapped_cosmetic_uses_the_measured_drill_size(self):
        result = translate_fixture("hole_tapped_cosmetic")
        self.assertAlmostEqual(steps_of(result.recipe, "hole")[0]["diameter"], 5.1)
        self.assertEqual(verdict_of(result, 3)["verdict"], "translatedWithNote")
        assert_schema_ok(self, result.recipe)

    def test_tapped_counterbore_uses_the_bore_not_the_counterbore_wall(self):
        step = steps_of(translate_fixture("hole_tapped_counterbore").recipe, "hole")[0]
        self.assertAlmostEqual(step["diameter"], 5.1)
        self.assertEqual(step["counterbore"], {"diameter": 9, "depth": 3})

    def test_tapped_hole_without_a_measured_cylinder_refuses(self):
        result = translate_fixture("hole_tapped_no_cylinder")
        self.assertIsNone(result.recipe)
        self.assertIn("drill size", result.refusal["reason"])

    def test_taper_tapped_and_unreadable_thread_refuse(self):
        for label, edit in {
            "taper tapped": lambda i: i["data"].update(tap_type="taperTapped"),
            "thread unknown": lambda i: i["data"].update(thread_modeled=None),
        }.items():
            with self.subTest(label):
                self.assertIsNone(variant("hole_tapped_cosmetic", edit).recipe)

    def test_measured_flat_end_wins_over_the_stored_tip_angle(self):
        result = translate_fixture("hole_flat_point_stored_tip")
        (step,) = result.recipe["features"][1:]
        self.assertEqual((step["kind"], step["depth"]), ("hole", 8))
        self.assertEqual(verdict_of(result, 3)["verdict"], "translatedWithNote")

    def test_measured_cone_without_a_tip_angle_refuses(self):
        result = variant("hole_blind_tip", lambda i: i["data"].update(tip_angle_deg=None))
        self.assertIsNone(result.recipe)

    def test_unclear_end_faces_refuse(self):
        result = variant("hole_blind_tip", lambda i: i["data"].update(end_face_types=["cone", "plane"]))
        self.assertIsNone(result.recipe)

    def test_hole_refusals(self):
        cases = {
            "read error": lambda i: i["data"].clear() or i["data"].update(read_error="boom"),
            "to entity": lambda i: i["data"].update(extent={"kind": "toEntity"}),
            "other extent": lambda i: i["data"].update(extent={"kind": "other"}),
            "no positions": lambda i: i["data"].update(positions=[]),
            "counterbore deeper than hole": lambda i: i["data"].update(
                hole_type="counterbore", counterbore={"diameter": 9.0, "depth": 9.0}, extent={"kind": "distance", "depth": 8.0}),
            "countersink too wide an angle": lambda i: i["data"].update(
                hole_type="countersink", countersink={"diameter": 10.0, "angle_deg": 140.0}),
        }
        for label, edit in cases.items():
            with self.subTest(label):
                result = variant("hole_through", edit)
                self.assertIsNone(result.recipe)
                self.assertEqual(result.refusal["type"], "HoleFeature")


class ThreadTest(unittest.TestCase):
    def test_cosmetic_thread_adds_no_step_and_notes(self):
        result = translate_fixture("thread_cosmetic")
        self.assertEqual(len(result.recipe["features"]), 2)
        verdict = verdict_of(result, 4)
        self.assertEqual((verdict["verdict"], verdict["steps"]), ("skipped", []))
        self.assertTrue(verdict["note"])

    def test_modeled_thread_refuses(self):
        result = translate_fixture("thread_modeled")
        self.assertIsNone(result.recipe)
        self.assertEqual((result.refusal["index"], result.refusal["type"]), (4, "ThreadFeature"))


if __name__ == "__main__":
    unittest.main()
