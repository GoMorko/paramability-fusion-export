"""What the sketch solver refuses: points nothing fixes, constraints it does not read, dimensions that do not match
the drawing, driven dimensions, and redundant rules that disagree when the sizes change (lib/sketch_solve)."""
import unittest

from tests import context  # noqa: F401
from tests.sketch_solve_helpers import L, P, SolvedCase, Sketch, rectangle

from lib.sketch_solve import outcome
from lib.sketch_solve.solve import solve_sketch


def corner_rectangle(width=12.0, height=7.0, width_value=None):
    s = Sketch()
    p1, p2, p3 = s.point(width, 0.0), s.point(width, height), s.point(0.0, height)
    lines = rectangle(s, [0, p1, p2, p3])
    s.dim("linear", [L(lines[0])], width if width_value is None else width_value, "d1", "horizontal")
    s.dim("linear", [L(lines[1])], height, "d2", "vertical")
    return s, (p1, p2, p3), lines


SETTINGS = [{"d1": 20.0, "d2": 3.0}, {"d1": 5.0, "d2": 9.0}]


class OpenPointTest(SolvedCase, unittest.TestCase):
    def test_a_point_nothing_fixes_stays_open_and_the_others_are_derived(self):
        s, (p1, p2, p3), _ = corner_rectangle()
        loose = s.point(30.0, 4.0, free=True)
        s.line(p2, loose, free=True)
        out = solve_sketch(s.record())
        self.assertEqual(out.outcome, outcome.PARTLY)
        self.assertEqual([v.code for v in out.points[loose]], [outcome.FREE, outcome.FREE])
        self.assert_point(out, p2, lambda e: (e["d1"], e["d2"]), SETTINGS)

    def test_a_constraint_the_solver_does_not_read_keeps_its_points_open(self):
        s, (p1, p2, p3), lines = corner_rectangle()
        s.con("other", L(lines[1]), name="adsk::fusion::FutureConstraint", unknown=True)
        out = solve_sketch(s.record())
        self.assertEqual(out.points[p2][0].code, outcome.BLOCKED)
        self.assertIn("FutureConstraint", out.points[p2][0].reason)
        self.assert_point(out, p3, lambda e: (0.0, e["d2"]), SETTINGS)


class DimensionCheckTest(SolvedCase, unittest.TestCase):
    def test_a_dimension_that_does_not_match_the_drawing_is_not_used(self):
        s, (p1, p2, p3), _ = corner_rectangle(width_value=10.0)
        out = solve_sketch(s.record())
        self.assertEqual(out.dimensions[0].status, "refused")
        self.assertAlmostEqual(out.dimensions[0].measured, 12.0)
        self.assertEqual(out.points[p1][0].code, outcome.REFUSED)
        self.assertIn("dimension 0", out.points[p1][0].reason)
        self.assert_point(out, p3, lambda e: (0.0, e["d2"]), SETTINGS)

    def test_a_driven_dimension_only_measures(self):
        s, (p1, p2, p3), lines = corner_rectangle()
        s.dim("linear", [P(0), P(p2)], 13.892443989449804, "d5", "aligned", driving=False)
        out = solve_sketch(s.record())
        self.assertEqual(out.outcome, outcome.DERIVED)
        self.assertEqual(out.dimensions[2].status, "driven")
        self.assertNotIn("d5", out.leaves)


class RedundantTest(unittest.TestCase):
    def _two_widths(self):
        s, corners, lines = corner_rectangle()
        s.dim("linear", [L(lines[2])], 12.0, "d5", "horizontal")
        return s, corners

    def test_redundant_dimensions_that_move_apart_leave_the_sketch_not_derived(self):
        s, (p1, p2, p3) = self._two_widths()
        out = solve_sketch(s.record())
        self.assertEqual(out.outcome, outcome.NOT_DERIVED)
        self.assertIn("sizes change", out.reason)
        self.assertEqual(out.points[p2][0].code, outcome.CONFLICT)

    def test_redundant_dimensions_that_move_together_agree(self):
        s, (p1, p2, p3) = self._two_widths()
        settings = [{"d1": w, "d5": w, "d2": 5.0} for w in (8.0, 15.0, 30.0)]
        out = solve_sketch(s.record(), settings=settings)
        self.assertEqual(out.outcome, outcome.DERIVED, out.reason)


class RecordTest(unittest.TestCase):
    def test_a_sketch_the_reader_cut_is_not_derived(self):
        out = solve_sketch({"sketch": "Sketch1", "token": "s1", "cut": "entities", "points": [], "curves": []})
        self.assertEqual(out.outcome, outcome.NOT_DERIVED)
        self.assertIn("too large", out.reason)

    def test_a_dimension_with_an_unread_entity_keeps_its_points_open(self):
        s, (p1, p2, p3), lines = corner_rectangle()
        s.dimensions[0]["on"] = [None]
        out = solve_sketch(s.record())
        self.assertEqual(out.dimensions[0].status, "unread")
        self.assertEqual(out.outcome, outcome.PARTLY)


if __name__ == "__main__":
    unittest.main()
