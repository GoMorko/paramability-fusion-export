"""Sketch point formulas with arcs and circles: a placed circle, a slot, a round corner, a ring and a point on a
circle whose crossing can swap at other sizes (lib/sketch_solve)."""
import math
import unittest

from tests import context  # noqa: F401
from tests.sketch_solve_helpers import A, C, L, P, SolvedCase, Sketch, rectangle

from lib.sketch_solve.outcome import DERIVED
from lib.sketch_solve.solve import solve_sketch


class CircleTest(SolvedCase, unittest.TestCase):
    def test_a_circle_with_a_diameter_placed_from_the_origin(self):
        s = Sketch()
        center = s.point(15.0, 8.0)
        circle = s.circle(center, 4.0)
        s.dim("linear", [P(0), P(center)], 15.0, "d1", "horizontal")
        s.dim("linear", [P(0), P(center)], 8.0, "d2", "vertical")
        s.dim("diameter", [C(circle)], 8.0, "d3")
        out = solve_sketch(s.record())
        self.assertEqual(out.outcome, DERIVED)
        self.assert_point(out, center, lambda e: (e["d1"], e["d2"]), [{"d1": 3.0, "d2": 4.0}, {"d1": 22.0, "d2": 1.5}])
        self.assertEqual(out.radii[circle].affine().terms, {"d3": 0.5})

    def test_a_ring_of_two_concentric_circles(self):
        s = Sketch()
        inner_center, outer_center = s.point(0.0, 0.0), s.point(0.0, 0.0)
        inner, outer = s.circle(inner_center, 5.0), s.circle(outer_center, 7.5)
        s.con("coincident", P(inner_center), P(0))
        s.con("concentric", C(inner), C(outer))
        s.dim("diameter", [C(inner)], 10.0, "d1")
        s.dim("concentric_circles", [C(inner), C(outer)], 2.5, "d2")
        out = solve_sketch(s.record())
        self.assertEqual(out.outcome, DERIVED)
        for env in ({"d1": 6.0, "d2": 1.0}, {"d1": 20.0, "d2": 4.0}):
            self.assertAlmostEqual(out.radii[outer].expr.value(env), env["d1"] / 2 + env["d2"])


class SlotTest(SolvedCase, unittest.TestCase):
    def test_a_slot_of_two_lines_and_two_tangent_arcs(self):
        """Centres on a horizontal construction line, the length between them, the width as a diameter, the two
        lines parallel to the centre line and tangent to both arcs."""
        length, r = 30.0, 4.0
        s = Sketch()
        far = s.point(length, 0.0)
        centre_line = s.line(0, far, construction=True)
        s.con("horizontal", L(centre_line))
        p1, p2, p3, p4 = s.point(0.0, -r), s.point(length, -r), s.point(length, r), s.point(0.0, r)
        bottom, top = s.line(p1, p2), s.line(p3, p4)
        right, left = s.arc(far, p2, p3), s.arc(0, p4, p1)
        for line in (bottom, top):
            s.con("parallel", L(centre_line), L(line))
            for arc in (left, right):
                s.con("tangent", L(line), A(arc))
        s.con("equal", A(left), A(right))
        s.dim("linear", [P(0), P(far)], length, "d1", "horizontal")
        s.dim("diameter", [A(left)], 2 * r, "d2")
        out = solve_sketch(s.record())
        self.assertEqual(out.outcome, DERIVED, out.reason)
        settings = [{"d1": 45.0, "d2": 6.0}, {"d1": 12.0, "d2": 10.0}]
        self.assert_point(out, p2, lambda e: (e["d1"], -e["d2"] / 2), settings)
        self.assert_point(out, p4, lambda e: (0.0, e["d2"] / 2), settings)

    def test_a_round_corner_tangent_to_two_sides(self):
        w, h, r = 20.0, 12.0, 3.0
        s = Sketch()
        a, b = s.point(w - r, 0.0), s.point(w, r)
        top_right, top_left = s.point(w, h), s.point(0.0, h)
        center = s.point(w - r, r)
        bottom, side = s.line(0, a), s.line(b, top_right)
        s.line(top_right, top_left)
        s.line(top_left, 0)
        for i, line in enumerate((bottom, side, 2, 3)):
            s.con("horizontal" if i in (0, 2) else "vertical", L(line))
        corner = s.arc(center, a, b)
        s.con("tangent", L(bottom), A(corner))
        s.con("tangent", L(side), A(corner))
        s.dim("linear", [P(0), P(top_right)], w, "d1", "horizontal")
        s.dim("linear", [P(0), P(top_right)], h, "d2", "vertical")
        s.dim("radial", [A(corner)], r, "d3")
        out = solve_sketch(s.record())
        self.assertEqual(out.outcome, DERIVED, out.reason)
        settings = [{"d1": 30.0, "d2": 10.0, "d3": 5.0}, {"d1": 14.0, "d2": 18.0, "d3": 1.0}]
        self.assert_point(out, center, lambda e: (e["d1"] - e["d3"], e["d3"]), settings)
        self.assert_point(out, a, lambda e: (e["d1"] - e["d3"], 0.0), settings)
        self.assert_point(out, b, lambda e: (e["d1"], e["d3"]), settings)


class BranchTest(SolvedCase, unittest.TestCase):
    def _point_on_circle(self, side=-1.0):
        """A point on a circle around the origin, at a height size: two crossings, the drawing has the one on `side`
        of the centre."""
        s = Sketch()
        circle = s.circle(0, 10.0)
        tip = s.point(side * 8.0, 6.0)
        s.con("coincident", P(tip), C(circle))
        s.dim("radial", [C(circle)], 10.0, "d1")
        s.dim("linear", [P(0), P(tip)], 6.0, "d2", "vertical")
        return s, tip

    def test_the_crossing_the_drawing_shows_is_kept(self):
        for side in (-1.0, 1.0):
            with self.subTest(side=side):
                s, tip = self._point_on_circle(side)
                out = solve_sketch(s.record(), settings=[{"d1": 12.0, "d2": 5.0}])
                x_value = out.points[tip][0]
                for env in ({"d1": 12.0, "d2": 5.0}, {"d1": 9.0, "d2": 2.0}):
                    self.assertAlmostEqual(x_value.expr.value(env), side * math.sqrt(env["d1"] ** 2 - env["d2"] ** 2))
                self.assertFalse(out.flips)

    def test_the_tip_of_a_triangle_from_its_three_sides(self):
        """Two aligned lengths from the ends of a base: the tip is where two circles cross."""
        w, a, b = 10.0, 8.0, 6.0
        tx = (w * w + a * a - b * b) / (2 * w)
        s = Sketch()
        q = s.point(w, 0.0)
        tip = s.point(tx, math.sqrt(a * a - tx * tx))
        base = s.line(0, q)
        s.con("horizontal", L(base))
        s.dim("linear", [L(base)], w, "d1", "horizontal")
        s.line(0, tip)
        s.line(q, tip)
        s.dim("linear", [L(1)], a, "d2", "aligned")
        s.dim("linear", [P(tip), P(q)], b, "d3", "aligned")
        out = solve_sketch(s.record())
        self.assertEqual(out.outcome, DERIVED, out.reason)

        def apex(e):
            px = (e["d1"] ** 2 + e["d2"] ** 2 - e["d3"] ** 2) / (2 * e["d1"])
            return px, math.sqrt(e["d2"] ** 2 - px * px)
        self.assert_point(out, tip, apex, [{"d1": 12.0, "d2": 9.0, "d3": 7.0}, {"d1": 9.0, "d2": 5.0, "d3": 6.5}])

    def test_a_setting_where_the_crossing_is_gone_is_named(self):
        s, tip = self._point_on_circle()
        out = solve_sketch(s.record(), settings=[{"d1": 12.0, "d2": 5.0}, {"d1": 10.0, "d2": 11.0}])
        flipped = [a for a in out.assumptions if a.flips]
        self.assertEqual([a.flips for a in flipped], [[1]])
        self.assertEqual(flipped[0].where, "point %d" % tip)
        self.assertEqual(out.outcome, DERIVED)


if __name__ == "__main__":
    unittest.main()
