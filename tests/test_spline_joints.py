"""Corners inside a spline, read from its definition (`geometry.spline_joints`)."""
import unittest

from tests import context  # noqa: F401

from lib.geometry.spline_joints import joint_turns

# A cubic of two pieces whose middle knot is there three times: it passes through (10, 0) and leaves it at 90 degrees.
KINKED = {"degree": 3, "knots": [0, 0, 0, 0, 1, 1, 1, 2, 2, 2, 2],
          "poles": [[0, 0], [4, 0], [7, 0], [10, 0], [10, 3], [10, 6], [10, 10]]}


class JointTurnsTest(unittest.TestCase):
    def test_a_knot_as_often_as_the_degree_gives_the_turn_there(self):
        self.assertAlmostEqual(joint_turns(KINKED)[0], 90.0)

    def test_weights_do_not_change_the_turn(self):
        weighted = dict(KINKED, rational=True, weights=[1, 3, 0.5, 2, 1, 4, 1])
        self.assertAlmostEqual(joint_turns(weighted)[0], 90.0)

    def test_a_knot_less_often_than_the_degree_is_smooth(self):
        smooth = dict(KINKED, knots=[0, 0, 0, 0, 1, 1.5, 2, 3, 3, 3, 3])
        self.assertEqual(joint_turns(smooth), [])

    def test_a_pole_repeated_at_the_joint_reads_the_next_pole_that_differs(self):
        polyline = {"degree": 1, "knots": [0, 0, 1, 2, 3, 3], "poles": [[0, 0], [5, 0], [5, 0], [5, 5]]}
        self.assertEqual([round(t, 6) for t in joint_turns(polyline)], [90.0, 90.0])

    def test_a_break_or_a_definition_that_does_not_fit_is_unreadable(self):
        broken = {"degree": 1, "knots": [0, 0, 1, 1, 2, 2], "poles": [[0, 0], [5, 0], [6, 0], [6, 5]]}
        for name, nurbs in (("a break", broken), ("too few knots", dict(KINKED, knots=[0, 0, 1, 1]))):
            with self.subTest(name):
                self.assertIsNone(joint_turns(nurbs))


if __name__ == "__main__":
    unittest.main()
