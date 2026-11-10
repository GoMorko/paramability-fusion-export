"""Sketch point formulas from line sketches: rectangles, legs at an angle, crossing lines, symmetry and projected
edges (lib/sketch_solve). Each formula is evaluated at other size settings against a hand computation."""
import unittest

from tests import context  # noqa: F401
from tests.sketch_solve_helpers import L, P, SolvedCase, Sketch, cos, rectangle, sin

from lib.sketch_solve.outcome import DERIVED
from lib.sketch_solve.solve import solve_sketch


class RectangleTest(SolvedCase, unittest.TestCase):
    def test_rectangle_from_the_origin_follows_width_and_height(self):
        s = Sketch()
        p1, p2, p3 = s.point(12.0, 0.0), s.point(12.0, 7.0), s.point(0.0, 7.0)
        lines = rectangle(s, [0, p1, p2, p3])
        s.dim("linear", [L(lines[0])], 12.0, "d1", "horizontal")
        s.dim("linear", [P(p1), P(p2)], 7.0, "d2", "vertical")
        out = solve_sketch(s.record())
        self.assertEqual(out.outcome, DERIVED)
        settings = [{"d1": 20.0, "d2": 3.0}, {"d1": 5.5, "d2": 9.25}]
        self.assert_point(out, p2, lambda e: (e["d1"], e["d2"]), settings)
        self.assert_point(out, p3, lambda e: (0.0, e["d2"]), settings)
        self.assertEqual(out.points[p1][0].affine().terms, {"d1": 1.0})

    def test_rectangle_centred_on_the_origin_by_its_diagonal(self):
        s = Sketch()
        corners = [s.point(-6.0, -3.5), s.point(6.0, -3.5), s.point(6.0, 3.5), s.point(-6.0, 3.5)]
        lines = rectangle(s, corners)
        diagonal = s.line(corners[0], corners[2], construction=True)
        s.con("midpoint", P(0), L(diagonal))
        s.dim("linear", [L(lines[0])], 12.0, "d1", "horizontal")
        s.dim("linear", [L(lines[1])], 7.0, "d2", "vertical")
        out = solve_sketch(s.record())
        self.assertEqual(out.outcome, DERIVED)
        settings = [{"d1": 20.0, "d2": 3.0}, {"d1": 5.0, "d2": 11.0}]
        self.assert_point(out, corners[0], lambda e: (-e["d1"] / 2, -e["d2"] / 2), settings)
        self.assert_point(out, corners[2], lambda e: (e["d1"] / 2, e["d2"] / 2), settings)


class AngleTest(SolvedCase, unittest.TestCase):
    def test_a_leg_at_an_angle_is_its_length_times_cos_and_sin_of_the_angle(self):
        s = Sketch()
        p1 = s.point(30.0, 0.0)
        p2 = s.point(18.0 * cos(35.0), 18.0 * sin(35.0))
        base = s.line(0, p1)
        leg = s.line(0, p2)
        s.con("horizontal", L(base))
        s.dim("linear", [L(base)], 30.0, "d1", "horizontal")
        s.dim("linear", [L(leg)], 18.0, "d2", "aligned")
        s.dim("angular", [L(base), L(leg)], 35.0, "d3")
        out = solve_sketch(s.record())
        self.assertEqual(out.outcome, DERIVED)
        self.assert_point(out, p2, lambda e: (e["d2"] * cos(e["d3"]), e["d2"] * sin(e["d3"])),
                          [{"d1": 30.0, "d2": 25.0, "d3": 50.0}, {"d1": 30.0, "d2": 12.0, "d3": 20.0}])
        self.assertEqual([v.expr.text() for v in out.points[p2]], ["d2 * cos(d3)", "d2 * sin(d3)"])

    def test_two_perpendicular_families_at_an_angle(self):
        """A bent bracket profile: a rectangle turned by an angle size, its width along one family, its height the
        offset between the two lines of the family."""
        a, w, h = 30.0, 20.0, 6.0
        s = Sketch()
        q = s.point(5.0, 0.0)
        p1 = s.point(w * cos(a), w * sin(a))
        p2 = s.point(w * cos(a) - h * sin(a), w * sin(a) + h * cos(a))
        p3 = s.point(-h * sin(a), h * cos(a))
        axis = s.line(0, q, construction=True)
        s.con("horizontal", L(axis))
        s.dim("linear", [L(axis)], 5.0, "d9", "horizontal")
        l0, l1, l2, l3 = s.line(0, p1), s.line(p1, p2), s.line(p2, p3), s.line(p3, 0)
        s.con("perpendicular", L(l0), L(l1))
        s.con("parallel", L(l0), L(l2))
        s.con("parallel", L(l1), L(l3))
        s.dim("angular", [L(axis), L(l0)], a, "d1")
        s.dim("linear", [L(l0)], w, "d2", "aligned")
        s.dim("offset", [L(l0), L(l2)], h, "d3")
        out = solve_sketch(s.record())
        self.assertEqual(out.outcome, DERIVED)

        def corner(e):
            return (e["d2"] * cos(e["d1"]) - e["d3"] * sin(e["d1"]), e["d2"] * sin(e["d1"]) + e["d3"] * cos(e["d1"]))
        settings = [{"d1": 42.0, "d2": 26.0, "d3": 4.0, "d9": 5.0}, {"d1": 12.0, "d2": 15.0, "d3": 9.0, "d9": 5.0}]
        self.assert_point(out, p2, corner, settings)
        self.assert_point(out, p3, lambda e: (-e["d3"] * sin(e["d1"]), e["d3"] * cos(e["d1"])), settings)

    def test_a_point_where_two_lines_cross(self):
        """Two lines from the ends of a base, each at its own angle size: the tip is where they cross."""
        a, b, w = 50.0, 70.0, 40.0
        t = w * sin(b) / sin(a + b)
        s = Sketch()
        q = s.point(w, 0.0)
        tip = s.point(t * cos(a), t * sin(a))
        base = s.line(0, q)
        s.con("horizontal", L(base))
        s.dim("linear", [P(0), P(q)], w, "d1", "horizontal")
        left, right = s.line(0, tip), s.line(q, tip)
        s.dim("angular", [L(base), L(left)], a, "d2")
        s.dim("angular", [L(base), L(right)], b, "d3")
        out = solve_sketch(s.record())
        self.assertEqual(out.outcome, DERIVED)

        def crossing(e):
            reach = e["d1"] * sin(e["d3"]) / sin(e["d2"] + e["d3"])
            return reach * cos(e["d2"]), reach * sin(e["d2"])
        self.assert_point(out, tip, crossing, [{"d1": 55.0, "d2": 40.0, "d3": 65.0},
                                               {"d1": 30.0, "d2": 62.0, "d3": 48.0}])


class OffsetTest(SolvedCase, unittest.TestCase):
    def test_an_offset_outline_around_a_rectangle(self):
        w, h, d = 12.0, 7.0, 2.0
        s = Sketch()
        p1, p2, p3 = s.point(w, 0.0), s.point(w, h), s.point(0.0, h)
        parents = rectangle(s, [0, p1, p2, p3])
        s.dim("linear", [L(parents[0])], w, "d1", "horizontal")
        s.dim("linear", [L(parents[1])], h, "d2", "vertical")
        outer = [s.point(-d, -d), s.point(w + d, -d), s.point(w + d, h + d), s.point(-d, h + d)]
        children = [s.line(outer[i], outer[(i + 1) % 4]) for i in range(4)]
        dim = s.dim("offset_curves", [], d, "d3")
        s.dimensions[dim]["offset_constraint"] = 0
        s.con("offset", *[L(c) for c in parents + children], parents=[["line", c] for c in parents],
              children=[["line", c] for c in children], distance=d, topology_matched=True, dimension=dim)
        s.constraints.insert(0, s.constraints.pop())
        for i, con in enumerate(s.constraints):
            con["id"] = i
        out = solve_sketch(s.record())
        self.assertEqual(out.outcome, DERIVED, out.reason)
        settings = [{"d1": 20.0, "d2": 3.0, "d3": 1.0}, {"d1": 6.0, "d2": 9.0, "d3": 4.0}]
        self.assert_point(out, outer[0], lambda e: (-e["d3"], -e["d3"]), settings)
        self.assert_point(out, outer[2], lambda e: (e["d1"] + e["d3"], e["d2"] + e["d3"]), settings)

    def test_a_point_at_a_distance_from_a_line(self):
        s = Sketch()
        far = s.point(40.0, 0.0)
        base = s.line(0, far)
        s.con("horizontal", L(base))
        s.dim("linear", [L(base)], 40.0, "d1", "horizontal")
        hole = s.point(15.0, 9.0)
        s.dim("linear", [L(base), P(hole)], 9.0, "d2", "aligned")
        s.dim("linear", [P(0), P(hole)], 15.0, "d3", "horizontal")
        out = solve_sketch(s.record())
        self.assert_point(out, hole, lambda e: (e["d3"], e["d2"]), [{"d1": 40.0, "d2": 4.0, "d3": 22.0},
                                                                    {"d1": 40.0, "d2": 13.0, "d3": 7.0}])


class SymmetryTest(SolvedCase, unittest.TestCase):
    def test_a_pair_mirrored_about_a_construction_line(self):
        s = Sketch()
        top = s.point(0.0, 10.0)
        axis = s.line(0, top, construction=True)
        s.con("vertical", L(axis))
        s.dim("linear", [L(axis)], 10.0, "d9", "vertical")
        left, right = s.point(-4.0, 6.0), s.point(4.0, 6.0)
        s.con("symmetry", P(left), P(right), L(axis))
        s.dim("linear", [P(left), P(right)], 8.0, "d1", "horizontal")
        s.dim("linear", [P(0), P(left)], 6.0, "d2", "vertical")
        out = solve_sketch(s.record())
        self.assertEqual(out.outcome, DERIVED)
        settings = [{"d1": 14.0, "d2": 2.0, "d9": 10.0}, {"d1": 3.0, "d2": 9.0, "d9": 12.0}]
        self.assert_point(out, left, lambda e: (-e["d1"] / 2, e["d2"]), settings)
        self.assert_point(out, right, lambda e: (e["d1"] / 2, e["d2"]), settings)


class ProjectedEdgeTest(SolvedCase, unittest.TestCase):
    def _sketch(self):
        """A horizontal line from the origin to a projected edge of another component."""
        s = Sketch()
        source = {"source": "other", "component": "c", "token": "edge"}
        e1, e2 = s.point(10.0, -5.0, reference=source), s.point(14.0, 7.0, reference=source)
        edge = s.line(e1, e2, reference=source)
        end = s.point(10.0 + 4.0 * 5.0 / 12.0, 0.0)
        own = s.line(0, end)
        s.con("horizontal", L(own))
        s.con("coincident", P(end), L(edge))
        return s, e1, e2, end

    def test_a_projected_edge_is_a_measured_input(self):
        s, e1, e2, end = self._sketch()
        out = solve_sketch(s.record())
        self.assertEqual(out.outcome, DERIVED)
        names = {leaf.entity: n for n, leaf in out.leaves.items() if leaf.kind == "input" and leaf.field == "x"}
        x1, y1 = names[P(e1)], names[P(e1)].replace(".x", ".y")
        x2, y2 = names[P(e2)], names[P(e2)].replace(".x", ".y")

        def crossing(e):
            return e[x1] + (0.0 - e[y1]) * (e[x2] - e[x1]) / (e[y2] - e[y1]), 0.0
        self.assert_point(out, end, crossing, [{x1: 9.0, y1: -6.0, x2: 16.0, y2: 8.0},
                                               {x1: 12.0, y1: -2.0, x2: 11.0, y2: 5.0}])

    def test_a_projected_edge_the_caller_knows_is_fixed_is_a_constant(self):
        s, e1, e2, end = self._sketch()
        out = solve_sketch(s.record(), constants=[P(e1), P(e2)])
        self.assertEqual(out.leaves, {})
        self.assertAlmostEqual(out.points[end][0].expr.const, 10.0 + 4.0 * 5.0 / 12.0)
        self.assertTrue(out.points[end][0].expr.is_constant)


if __name__ == "__main__":
    unittest.main()
