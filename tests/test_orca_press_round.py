"""A Press Pull of a whole round face in the Orca copy (`orca_translate/press_round.py`): a ring tool body joined to
the part or cut from it, against the captures of tests/orca_press_round.py."""
import unittest

from tests import context  # noqa: F401
from tests import orca_extents as ex
from tests import orca_press_round as pr
from tests.orca_cuts import Section
from tests.test_orca_extents import limit_of, outcome, run

from lib.capture_model import gap_hints
from lib.export_plan.recipe_export import translate_capture
from lib.orca_recipe.enums import BooleanMode, FeatureType
from lib.orca_translate import PARTLY, VARIABLE, causes, limits


def boolean(result):
    return next(f for f in result.recipe.features if f.type == FeatureType.BOOLEAN)


def solid_at(result, changed, radius, z):
    """True when the part Orca builds with the variables `changed` holds the point at `radius` from the axis, at
    height `z` (capture coordinates)."""
    section = Section(result.recipe, changed)
    return section.bodies[0](result.place.point([radius, 0.0, z]))


class CopiedTest(unittest.TestCase):
    def test_the_ring_is_joined_or_cut_and_its_new_radius_follows_the_distance(self):
        # (capture, variable, Orca mode, {value: (a radius with material, a radius without)}) at mid height.
        cases = (
            (pr.pin_grown(), "grow_mm", BooleanMode.ADD, {1.0: (5.5, 6.5), 2.0: (6.5, 7.5)}),
            (pr.bore_grown(), "grow_mm", BooleanMode.CUT, {0.5: (4.75, 4.25), 1.0: (5.25, 4.75)}),
            (pr.pin_shrunk(), "shrink_mm", BooleanMode.CUT, {1.0: (3.5, 4.5), 2.0: (2.5, 3.5)}),
        )
        for capture, name, mode, points in cases:
            with self.subTest(name=name, mode=mode):
                result = run(capture)
                self.assertEqual(result.left_out, [])
                self.assertEqual(boolean(result).mode, mode)
                self.assertEqual(outcome(result, name)["outcome"], VARIABLE)
                z = 10.0 if capture["target"]["box"]["max"][2] == 15 else 5.0
                for value, (full, empty) in points.items():
                    self.assertTrue(solid_at(result, {name: value}, full, z))
                    self.assertFalse(solid_at(result, {name: value}, empty, z))

    def test_the_line_of_the_distance_tells_how_far_it_may_go(self):
        # The pin and the bore reach the plate's sides (20 from the axis); the shrunk pin closes at 0.
        cases = ((pr.pin_grown(), "grow_mm", 14.9, limits.RING_MEETS),
                 (pr.bore_grown(), "grow_mm", 15.9, limits.RING_MEETS),
                 (pr.pin_shrunk(), "shrink_mm", 4.99, limits.SHAPE_ZERO))
        for capture, name, high, why in cases:
            with self.subTest(high=high):
                limit = limit_of(outcome(run(capture), name))
                self.assertEqual((limit.high, limit.why[1]), (high, why))
                self.assertEqual(limit.why[0], limits.RING_TURNS)

    def test_sizes_that_may_move_the_face_or_its_ends_are_marked(self):
        capture = pr.pin_grown()
        capture["parameters"]["user"].append(ex.user("h", "5 mm", 5.0, "mm"))
        capture["parameters"]["model"].append(ex.model("d1", "h", 5.0))
        capture["items"][1]["data"]["params"] = {"side_one.distance": ex.param("d1", "h", 5.0)}
        result = run(capture)
        self.assertEqual(result.left_out, [])
        self.assertEqual(outcome(result, "h")["outcome"], PARTLY)
        self.assertEqual(outcome(result, "grow_mm")["outcome"], VARIABLE)


class LeftOutTest(unittest.TestCase):
    def test_a_press_pull_that_is_not_one_whole_round_face_is_left_out_with_its_cause(self):
        flat = dict(pr.face(ex.at(15.0), ex.circle(5.0)), token="f1", sides="square", meets_offset=False)
        part = dict(pr.pin_face(), ends=[{"kind": "other", "type": "edges"}])
        cases = {
            "a flat face": ([flat], 1.0, causes.PRESS_PULL_FLAT),
            "two faces": ([pr.pin_face(), flat], 1.0, causes.PRESS_PULL_FACES),
            "another curved face": ([{"kind": "other", "type": "Cone"}], 1.0, gap_hints.OFFSET_CURVED),
            "part of a round face": ([part], 1.0, gap_hints.OFFSET_CURVED),
            "a ring that reaches the plate's sides": ([pr.pin_face()], 15.5, gap_hints.OFFSET_CURVED),
        }
        for name, (faces, distance, cause) in cases.items():
            with self.subTest(name):
                capture = pr.pin_grown()
                capture["items"][4] = pr.press_pull(4, faces, distance)
                record = run(capture).left_out
                self.assertEqual([r["cause"] for r in record], [cause])
                if cause == gap_hints.OFFSET_CURVED:
                    self.assertEqual(record[0]["reason"], translate_capture(capture, "z").gaps[0]["reason"])

    def test_a_ring_where_the_copy_has_no_round_face_is_left_out(self):
        for capture in (pr.pin_grown(), pr.pin_shrunk()):
            with self.subTest(distance=capture["items"][4]["data"]["distance"]):
                del capture["items"][2:4]
                record = run(capture).left_out
                self.assertEqual([r["cause"] for r in record], [causes.MISSES_PART])


if __name__ == "__main__":
    unittest.main()
