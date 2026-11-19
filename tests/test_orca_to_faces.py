"""A hole that goes up to a face or plane, and an extrude that starts at a distance from a face, in the Orca copy
(`orca_translate/hole_reach.py`, `orca_translate/extents.py`), against the captures of tests/orca_to_faces.py."""
import copy
import math
import unittest

from tests import context  # noqa: F401
from tests import orca_extents as ex
from tests import orca_to_faces as faces
from tests.probe_helpers import user
from tests.test_orca_extents import at, limit_of, named, outcome, run

from lib.capture_model import gap_hints
from lib.orca_recipe.enums import FeatureType
from lib.orca_translate import FIXED, PARTLY, VARIABLE


def hole_data(capture):
    return capture["items"][4]["data"]


def causes_of(result):
    return [gap["cause"] for gap in result.left_out]


class HoleToFaceTest(unittest.TestCase):
    def test_a_hole_up_to_a_plane_follows_the_distance_of_the_plane(self):
        result = run(faces.hole_to_plane(lift=8.0))
        self.assertEqual(result.left_out, [])
        hole = named(result, "Hole1")
        self.assertEqual((hole.type, hole.hole_through, hole.hole_depth), (FeatureType.HOLE, False, 12.0))
        for lift, depth in ((5.0, 15.0), (12.0, 8.0)):
            self.assertAlmostEqual(at(hole, "hole_depth", lift_mm=lift), depth)
        self.assertEqual(outcome(result, "lift_mm")["outcome"], VARIABLE)

    def test_the_depth_must_stay_above_zero_and_the_limit_is_told(self):
        param = outcome(run(faces.hole_to_plane()), "lift_mm")
        self.assertEqual((limit_of(param).low, limit_of(param).high), (None, 20.0))

    def test_a_hole_up_to_the_end_face_of_an_extrude_follows_that_length(self):
        capture = tower_and_hole()
        result = run(capture)
        self.assertEqual(result.left_out, [])
        hole = named(result, "Hole1")
        self.assertEqual(hole.hole_depth, 10.0)
        self.assertAlmostEqual(at(hole, "hole_depth", h=14.0), 6.0)

    def test_a_face_the_copy_cannot_place_keeps_the_measured_depth_and_marks_its_sizes(self):
        capture = tower_and_hole()
        hole_data(capture)["extent"]["face_point"] = [20.0, 0.0, 5.0]  # on a side wall of the plate
        result = run(capture)
        self.assertNotIn("hole_depth", named(result, "Hole1").expr)
        self.assertEqual(outcome(result, "h")["outcome"], PARTLY)

    def test_a_hole_that_cannot_be_told_to_end_on_a_flat_face_square_to_it_is_left_out(self):
        def tilted(data):
            data["extent"]["plane"]["normal"] = [0.0, math.sin(0.3), math.cos(0.3)]

        def curved(data):
            data["extent"].update(plane=None, surface="Cylinder")

        def other_component(data):
            data["extent"]["foreign"] = True

        def drill_point(data):
            data["end_face_types"] = ["cone"]

        def ends_elsewhere(data):
            data["end_points"] = [[0, 0, 7.0]]

        def end_unread(data):
            data["end_points"] = []

        def offset(data):
            data["extent"]["offset"] = 2.0

        cases = {"tilted": (tilted, gap_hints.EXTRUDE_END_FACE), "curved": (curved, gap_hints.EXTRUDE_END_FACE),
                 "another component": (other_component, gap_hints.OTHER_COMPONENT),
                 "drill point": (drill_point, gap_hints.REFUSED), "end elsewhere": (ends_elsewhere, gap_hints.REFUSED),
                 "end not measured": (end_unread, gap_hints.REFUSED), "offset": (offset, gap_hints.REFUSED)}
        for name, (change, cause) in cases.items():
            with self.subTest(name):
                capture = faces.hole_to_plane()
                change(hole_data(capture))
                self.assertEqual(causes_of(run(capture)), [cause])

    def test_sizes_that_move_a_face_fusion_may_join_with_the_faces_next_to_it_are_marked(self):
        # `chained` null (as the reader gives for `matchShape`) or true: at other sizes the faces next to the plate's
        # top may end the hole first, so `h` gets one more reason than when the hole follows the face alone.
        def reasons(chained):
            capture = tower_and_hole()
            hole_data(capture)["extent"]["chained"] = chained
            result = run(capture)
            self.assertEqual(result.left_out, [])
            return outcome(result, "h")["reasons"]

        alone = reasons(False)
        for chained in (None, True):
            with self.subTest(chained):
                found = reasons(chained)
                self.assertEqual((len(found), set(alone) <= set(found)), (len(alone) + 1, True))

    def test_the_depth_must_stay_below_a_counterbore_or_countersink_and_the_limit_is_told(self):
        # The hole is 20 - lift_mm deep: a counterbore 5 deep needs lift_mm under 15; a countersink of 11 mm on the
        # 5 mm hole at 90 degrees reaches 3 deep, so lift_mm under 17.
        recesses = {"counterbore": ({"diameter": 9.0, "depth": 5.0}, 15.0),
                    "countersink": ({"diameter": 11.0, "angle_deg": 90.0}, 17.0)}
        for kind, (recess, high) in recesses.items():
            with self.subTest(kind):
                capture = faces.hole_to_plane()
                hole_data(capture).update(hole_type=kind, **{kind: recess})
                result = run(capture)
                self.assertEqual(result.left_out, [])
                told = limit_of(outcome(result, "lift_mm")).high
                self.assertTrue(high - 0.2 < told <= high, told)

    def test_a_hole_of_a_given_depth_keeps_above_its_counterbore(self):
        capture = faces.hole_to_plane()
        capture["parameters"]["user"].append(user("deep_mm", "12 mm", 12.0))
        capture["parameters"]["model"].append(ex.model("d30", "deep_mm", 12.0))
        hole_data(capture).update(hole_type="counterbore", counterbore={"diameter": 9.0, "depth": 5.0},
                                  extent={"kind": "distance", "depth": 12.0},
                                  params={"extent.depth": ex.param("d30", "deep_mm", 12.0)})
        result = run(capture)
        self.assertEqual(result.left_out, [])
        told = limit_of(outcome(result, "deep_mm")).low
        self.assertTrue(5.0 <= told < 5.2, told)

    def test_a_tapped_hole_up_to_a_plane_is_drilled_to_that_depth(self):
        capture = faces.hole_to_plane()
        data = hole_data(capture)
        data.update(tap_type="tapped", thread_modeled=False,
                    thread={"thread_type": "ISO Metric profile", "designation": "M5x0.8", "internal": True,
                            "right_hand": True, "pitch": 0.8, "major_diameter": 5.0, "minor_diameter": 4.134,
                            "full_length": True, "depth": None, "made_span": None},
                    side_cylinders=[{"origin": [0, 0, 20], "axis": [0, 0, -1], "radius": 4.134 / 2}])
        result = run(capture)
        self.assertEqual(result.left_out, [])
        self.assertEqual(named(result, "Hole1").hole_depth, 12.0)


def tower_and_hole():
    """A 40 by 20 plate `h` (10) tall with a 10 by 10 tower on it (to z 20), and a hole from the middle of the tower's
    top down to the plate's top face, 10 deep."""
    users, models = ex.plate_users()
    face = dict(ex.face_target(10.0, (15.0, 5.0)), kind="toEntity")
    items = ex.plate_items() + [
        ex.sketch_item(2, "Sketch2"),
        ex.extrude(3, "Tower", [ex.profile("Sketch2", ex.at(10.0), ex.rect(-5, -5, 5, 5))], operation="join",
                   side_one=ex.side(10.0), end_offset=10.0, target_box_before={"min": [-20, -10, 0], "max": [20, 10, 10]}),
        faces.hole_item(4, "Hole1", {k: v for k, v in face.items() if k != "kind"}, 10.0)]
    return ex.capture(items, ((-20, -10, 0), (20, 10, 20)), 8000.0 + 1000.0 - math.pi * 6.25 * 10.0, users, models)


class StartAtADistanceTest(unittest.TestCase):
    def test_a_start_inside_the_part_moves_the_sketch_and_keeps_the_offset_as_a_number(self):
        result = run(faces.boss_into_plate(inset=-2.0))
        self.assertEqual(result.left_out, [])
        boss = named(result, "Boss")
        sketch = result.recipe.features[boss.sketch_ref]
        self.assertAlmostEqual(sketch.plane.origin[2], result.place.point([0.0, 0.0, 8.0])[2])
        self.assertEqual((boss.distance, boss.flip), (5.0, False))
        self.assertNotIn("distance", boss.expr)
        self.assertEqual(outcome(result, "inset_mm")["outcome"], FIXED)

    def test_a_start_above_the_face_goes_the_way_the_measured_start_face_shows(self):
        result = run(faces.lowered_post(rise=2.0))
        self.assertEqual(result.left_out, [])
        post = named(result, "Post")
        sketch = result.recipe.features[post.sketch_ref]
        self.assertAlmostEqual(sketch.plane.origin[2], result.place.point([0.0, 0.0, 12.0])[2])
        self.assertEqual((post.distance, post.flip), (4.0, True))
        self.assertEqual(outcome(result, "rise_mm")["outcome"], FIXED)

    def test_an_offset_whose_way_is_not_sure_leaves_the_step_out(self):
        unsure = {"no measured face": {"start_offset": None},
                  "measured face at neither way": {"start_offset": 11.0}}
        for name, change in unsure.items():
            with self.subTest(name):
                capture = faces.lowered_post()
                capture["items"][3]["data"].update(change)
                self.assertEqual(causes_of(run(capture)), [gap_hints.EXTRUDE_START_OFFSET])

    def test_the_way_may_be_told_by_the_measured_end_cap_when_no_start_face_is_measured(self):
        # The boss that starts inside the plate has no start face; its end cap shows the way, and a cap that
        # fits no start shows none.
        capture = faces.boss_into_plate()
        self.assertEqual(run(capture).left_out, [])
        capture["items"][3]["data"]["end_offset"] = 9.0
        self.assertEqual(causes_of(run(capture)), [gap_hints.EXTRUDE_START_OFFSET])

    def test_sizes_that_move_the_start_face_and_the_offset_are_both_marked(self):
        capture = faces.lowered_post()
        users, models = ex.plate_users()
        capture["parameters"]["user"] += users
        capture["parameters"]["model"] += models
        capture["items"][1]["data"]["params"] = {"side_one.distance": ex.param("d1", "h", 10.0)}
        result = run(capture)
        self.assertEqual(result.left_out, [])
        self.assertEqual({p["name"]: p["outcome"] for p in result.parameters}, {"rise_mm": FIXED, "h": PARTLY})

    def test_a_later_face_on_the_end_of_that_extrude_is_marked_with_the_sizes_behind_its_start(self):
        # The boss's sketch plane keeps its number in Orca, so a rod up to the boss's top face may not follow the
        # offset that sets where the boss starts.
        capture = faces.boss_into_plate()
        top = dict(ex.face_target(13.0, (3.0, 3.0)), kind="toEntity", chained=False, offset=0.0)
        capture["items"] += [ex.sketch_item(4, "Sketch3"),
                             ex.extrude(5, "Rod", [ex.profile("Sketch3", ex.UP, ex.rect(2, 2, 4, 4))],
                                        operation="join", side_one=top, end_offset=13.0,
                                        target_box_before={"min": [-20, -20, 0], "max": [20, 20, 13]})]
        result = run(capture)
        self.assertEqual(result.left_out, [])
        reasons = outcome(result, "inset_mm")["reasons"]
        self.assertTrue(any("sketch plane" in reason and "Rod" in reason for reason in reasons), reasons)


if __name__ == "__main__":
    unittest.main()
