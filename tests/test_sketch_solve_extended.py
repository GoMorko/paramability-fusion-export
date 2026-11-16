"""The extended reading of the sketch solver (`solve_sketch(extended=True)`), which only the Orca copy uses: a
distance dimension between two lines keeps them parallel, angles and parallel lines are tested within what the
rounding of the drawing allows, and each line's direction is given. The default reading, which the recipe export
uses, must stay as it was."""
import json
import unittest
from unittest import mock

from tests import context  # noqa: F401
from tests.derived_fixtures import box_capture
from tests.fakes import FakePort
from tests.sketch_solve_helpers import L, P, SolvedCase, Sketch, cos, sin
from tests.test_pipeline import export

from lib.probe import derived
from lib.sketch_solve import checks
from lib.sketch_solve.outcome import DERIVED
from lib.sketch_solve.solve import solve_sketch


def _beside(tilt=30.0, gap=5.0):
    """A base line along x, a 40 mm leg at `tilt` from it, a construction line square to the leg from its end, and a
    30 mm line `gap` beside the leg, tied to it by the distance dimension only. Returns the record and the point ids
    of the leg's end and of the second line."""
    s = Sketch()
    u, n = (cos(tilt), sin(tilt)), (-sin(tilt), cos(tilt))
    p1 = s.point(30.0, 0.0)
    tip = s.point(40.0 * u[0], 40.0 * u[1])
    start = s.point(40.0 * u[0] + gap * n[0], 40.0 * u[1] + gap * n[1])
    end = s.point(40.0 * u[0] + gap * n[0] + 30.0 * u[0], 40.0 * u[1] + gap * n[1] + 30.0 * u[1])
    base, leg = s.line(0, p1), s.line(0, tip)
    square = s.line(tip, start, construction=True)
    other = s.line(start, end)
    s.con("horizontal", L(base))
    s.con("perpendicular", L(square), L(leg))
    s.dim("linear", [L(base)], 30.0, "d1", "horizontal")
    s.dim("linear", [L(leg)], 40.0, "d2", "aligned")
    s.dim("angular", [L(base), L(leg)], tilt, "d3")
    s.dim("offset", [L(leg), L(other)], gap, "d4")
    s.dim("linear", [L(other)], 30.0, "d5", "aligned")
    return s.record(), tip, start, end, leg, other


class DistanceBetweenLinesTest(SolvedCase, unittest.TestCase):
    def test_the_default_reading_leaves_the_second_line_open(self):
        record, _, start, end, _, _ = _beside()
        out = solve_sketch(record)
        self.assertFalse(out.points[start][0].derived or out.points[end][0].derived)
        self.assertEqual(out.directions, {})

    def test_the_extended_reading_keeps_the_two_lines_parallel(self):
        record, _, start, end, _, _ = _beside()
        out = solve_sketch(record, extended=True)
        self.assertEqual(out.outcome, DERIVED)

        def at(env, along):
            t, g = env["d3"], env["d4"]
            return (along * cos(t) - g * sin(t), along * sin(t) + g * cos(t))
        settings = [{"d1": 30.0, "d2": 40.0, "d3": 50.0, "d4": 9.0, "d5": 30.0},
                    {"d1": 30.0, "d2": 25.0, "d3": 10.0, "d4": 3.0, "d5": 12.0}]
        self.assert_point(out, start, lambda e: at(e, e["d2"]), settings)
        self.assert_point(out, end, lambda e: at(e, e["d2"] + e["d5"]), settings)

    def test_without_the_parallel_rule_the_second_line_stays_open_and_the_pair_is_named(self):
        record, _, start, _, leg, other = _beside()
        joined = solve_sketch(record, extended=True)
        self.assertEqual([set(p) for p in joined.parallel_by_distance], [{leg, other}])
        plain = solve_sketch(record, extended=True, distance_parallel=False)
        self.assertFalse(plain.points[start][0].derived)
        self.assertFalse(plain.directions[other].derived)
        self.assertTrue(plain.directions[leg].derived)

    def test_each_line_gets_its_direction_as_an_angle(self):
        record, _, _, _, leg, other = _beside()
        out = solve_sketch(record, extended=True)
        env = {"d3": 47.0}
        self.assertAlmostEqual(out.directions[leg].expr.value(env) % 360.0, 47.0, places=9)
        self.assertAlmostEqual(out.directions[other].expr.value(env) % 360.0, 47.0, places=9)


class RoundedDrawingTest(unittest.TestCase):
    def _leg(self, angle, drawn=None, size=3.0):
        """A 3 mm base along x and a leg `size` long drawn at `drawn` (else `angle`) with an angle dimension of
        `angle`, each coordinate rounded to 6 decimals as a capture is."""
        drawn = angle if drawn is None else drawn
        s = Sketch()
        p1 = s.point(3.0, 0.0)
        p2 = s.point(round(size * cos(drawn), 6), round(size * sin(drawn), 6))
        base, leg = s.line(0, p1), s.line(0, p2)
        s.con("horizontal", L(base))
        s.dim("linear", [L(base)], 3.0, "d1", "horizontal")
        s.dim("linear", [P(0), P(p2)], size, "d2", "aligned")
        s.dim("angular", [L(base), L(leg)], angle, "d3")
        return s.record()

    def test_a_line_too_short_to_show_its_direction_does_not_widen_the_angle_test_past_the_cap(self):
        # A 0.001 mm leg drawn 0.2 degrees off its dimension: its rounding alone would allow about 0.23 degrees.
        record = self._leg(120.0, drawn=120.2, size=0.001)
        self.assertEqual(solve_sketch(record, extended=True).dimensions[2].status, "refused")

    def test_an_angle_off_by_the_rounding_of_short_lines_is_used_by_the_extended_reading_only(self):
        record = self._leg(120.0)
        self.assertEqual(solve_sketch(record).dimensions[2].status, "refused")
        self.assertEqual(solve_sketch(record, extended=True).dimensions[2].status, "used")


class NormalExportTest(unittest.TestCase):
    def test_the_recipe_export_never_turns_on_the_extended_reading(self):
        calls, slacks = [], []
        real_solve, real_slack = derived.solve_sketch, checks.turn_slack

        def spy_solve(*args, **kwargs):
            calls.append(kwargs.get("extended", False))
            return real_solve(*args, **kwargs)

        def spy_slack(*args, **kwargs):
            slacks.append(args)
            return real_slack(*args, **kwargs)

        with mock.patch.object(derived, "solve_sketch", side_effect=spy_solve), \
                mock.patch.object(checks, "turn_slack", side_effect=spy_slack):
            result = export(FakePort(capture=box_capture()))
        self.assertEqual(calls, [False])
        self.assertEqual(slacks, [])
        written = json.loads(result.files["report.json"])
        self.assertEqual(written["derived"]["sketches"][0]["outcome"], "derived")


if __name__ == "__main__":
    unittest.main()
