"""Matching a sketch state read in Fusion to the captured profile, curve by curve."""
import math
import unittest

from tests.probe_helpers import capture, extrude, line, loop, profile, read, sketch_state

from lib.probe import match, plan


def slot(dx=0.0):
    """A 4 by 2 outline whose bottom line is split in two pieces of one sketch line (entity "b"), listed from the
    second piece, moved `dx` along x."""
    corners = [(2, 0), (4, 0), (4, 2), (0, 2), (0, 0)]
    p = [(x + dx, y) for x, y in corners]
    return [line(p[0], p[1], "b"), line(p[1], p[2], "r"), line(p[2], p[3], "t"), line(p[3], p[4], "l"),
            line(p[4], p[0], "b")]


class PiecesOfOneLineTest(unittest.TestCase):
    def test_a_loop_that_moved_further_than_its_pieces_are_apart_pairs_each_piece_with_its_own(self):
        # Moved 2 mm, the first piece lands where the second one was captured: nearness alone would swap them.
        found = plan.scan(capture(extrude(1, profile("Slot", "sk1", [loop(slot())]))))
        target = found.targets[0]
        values, cause = match.state_values(target, read(sketch_state("sk1", [{"loops": [loop(slot(2.0))]}])))
        self.assertIsNone(cause)
        want = match.captured_values(target)
        moved = {k: round(values[k] - v, 9) for k, v in want.items() if "/l0/" in k}
        self.assertEqual({v for k, v in moved.items() if k.endswith(".0")}, {2.0})
        self.assertEqual({v for k, v in moved.items() if k.endswith(".1")}, {0.0})


class PathOnlySketchTest(unittest.TestCase):
    """A sketch that holds only a sweep path has no outline curves: its path curves still count as a change."""

    @staticmethod
    def sketch(end):
        return {"frame": {"origin": [0, 0, 0]}, "profiles": [],
                "curves": {"t1": {"kind": "line", "start": [0, 0], "end": [end, 0]}}}

    def test_a_moved_path_curve_is_another_read(self):
        self.assertFalse(match.same_read(self.sketch(10.0), self.sketch(12.0)))

    def test_the_same_path_under_a_new_curve_token_is_the_same_read(self):
        again = self.sketch(10.0)
        again["curves"] = {"t9": again["curves"]["t1"]}
        self.assertTrue(match.same_read(self.sketch(10.0), again))


class CurveMadeAgainTest(unittest.TestCase):
    """Fusion may give a projected or intersection curve a new token when it recomputes the sketch."""

    @staticmethod
    def split(top_token, y=3.0, extra=()):
        """Two boxes on top of each other, split by one line (`top_token`) at height `y`."""
        lower = [line((0, 0), (2, 0), "b"), line((2, 0), (2, y), "r1"), line((2, y), (0, y), top_token),
                 line((0, y), (0, 0), "l1")]
        upper = [line((0, y), (2, y), top_token), line((2, y), (2, 6), "r2"), line((2, 6), (0, 6), "t"),
                 line((0, 6), (0, y), "l2")]
        return [{"loops": [loop(lower)]}, {"loops": [loop(upper)]}] + list(extra)

    def setUp(self):
        self.target = plan.scan(capture(extrude(1, profile("S", "sk", [loop(self.split("m")[0]["loops"][0]["curves"])])))).targets[0]
        self.e0 = read(sketch_state("sk", self.split("m")))

    def test_a_curve_with_a_new_token_in_the_place_of_the_old_one_reads_as_the_captured_outline(self):
        values, cause = match.state_values(self.target, read(sketch_state("sk", self.split("m2", y=3.5))), self.e0)
        self.assertIsNone(cause)
        self.assertAlmostEqual(values["1/p0/l0/height"], 3.5)
        self.assertTrue(match.same_read(self.e0["sketches"]["sk"], sketch_state("sk", self.split("m2"))["sk"]))

    def test_a_new_curve_with_no_curve_of_its_loop_kept_is_another_outline(self):
        others = [{"loops": [loop([line((0, 0), (2, 0), "x1"), line((2, 0), (2, 3), "x2"), line((2, 3), (0, 3), "x3"),
                                   line((0, 3), (0, 0), "x4")])]}]
        _, cause = match.state_values(self.target, read(sketch_state("sk", others)), self.e0)
        self.assertEqual(cause, "shape")


def leg(turn):
    """A triangle whose first side, a 10 mm leg from the origin, is turned `turn` degrees about the origin; the other
    two sides close it through (0, 3)."""
    tip = (round(10 * math.cos(math.radians(turn)), 6), round(10 * math.sin(math.radians(turn)), 6))
    return [line((0, 0), tip, "a"), line(tip, (0, 3), "b"), line((0, 3), (0, 0), "c")]


class TurnedLegTest(unittest.TestCase):
    def test_a_side_that_turned_far_keeps_its_direction_along_the_loop(self):
        # Turned 150 degrees, the leg lies nearer its captured place with its ends swapped; the loop says otherwise.
        target = plan.scan(capture(extrude(1, profile("Leg", "sk1", [loop(leg(0))])))).targets[0]
        values, cause = match.state_values(target, read(sketch_state("sk1", [{"loops": [loop(leg(150))]}])))
        self.assertIsNone(cause)
        self.assertAlmostEqual(values["1/p0/c0.0/turn"], 150.0, places=6)


def arc(start, end, mid, center, radius, entity):
    return {"kind": "arc", "start": list(start), "end": list(end), "mid": list(mid), "center": list(center),
            "radius": radius, "entity": entity}


def lens_regions(dy=0.0):
    """Two regions of one sketch moved `dy` along y: a circle (entity "c", radius 1.5) cut in half by an arc ("a",
    radius 1.625) through its ends. The lower region is the arc with the lower half of the circle, the upper one the
    arc with the upper half: both list the same two entities."""
    def p(x, y):
        return (x, y + dy)
    over = arc(p(1.5, 0), p(-1.5, 0), p(0, 1), p(0, -0.625), 1.625, "a")
    lower = [over, arc(p(-1.5, 0), p(1.5, 0), p(0, -1.5), p(0, 0), 1.5, "c")]
    upper = [arc(p(1.5, 0), p(-1.5, 0), p(0, 1.5), p(0, 0), 1.5, "c"), over]
    return lower, upper


class SharedCurvesTest(unittest.TestCase):
    def test_a_region_that_moved_further_than_its_neighbour_is_away_is_still_matched_by_its_shape(self):
        # Moved 3 mm down, the upper region lies where the lower one was captured.
        lower, upper = lens_regions()
        target = plan.scan(capture(extrude(1, profile("Lens", "sk1", [loop(lower)])))).targets[0]
        moved_lower, moved_upper = lens_regions(-3.0)
        state = read(sketch_state("sk1", [{"loops": [loop(moved_upper)]}, {"loops": [loop(moved_lower)]}]))
        values, cause = match.state_values(target, state)
        self.assertIsNone(cause)
        want = match.captured_values(target)
        self.assertEqual({round(values[k] - v, 9) for k, v in want.items() if k.endswith(".1")}, {-3.0})


def disc_regions(d, r=2.0):
    """A circle ("c", radius `r`) cut by a chord ("k") at height `d`: the region below the chord and the one above."""
    x = math.sqrt(r * r - d * d)
    below = [line((x, d), (-x, d), "k"), arc((-x, d), (x, d), (0, -r), (0, 0), r, "c")]
    above = [arc((x, d), (-x, d), (0, r), (0, 0), r, "c"), line((-x, d), (x, d), "k")]
    return below, above


class ChordRegionTest(unittest.TestCase):
    def test_a_region_whose_shape_changes_keeps_its_own_piece_of_the_circle(self):
        # Captured as the small cap below a chord at -1; with the chord at 1.5 the cap above looks more like it.
        target = plan.scan(capture(extrude(1, profile("Disc", "sk1", [loop(disc_regions(-1.0)[0])])))).targets[0]
        below, above = disc_regions(1.5)
        values, cause = match.state_values(target, read(sketch_state("sk1", [{"loops": [loop(above)]},
                                                                             {"loops": [loop(below)]}])))
        self.assertIsNone(cause)
        self.assertEqual(round(values["1/p0/l0/segments.1.through.1"], 9), -2.0)


if __name__ == "__main__":
    unittest.main()
