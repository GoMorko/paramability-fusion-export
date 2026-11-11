"""Matching a sketch state read in Fusion to the captured profile, curve by curve."""
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


if __name__ == "__main__":
    unittest.main()
