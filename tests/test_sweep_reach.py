"""How far a written outline reaches from the path, with arcs and splines sampled as the app does."""
import math
import unittest

from tests import context  # noqa: F401

from lib.translator import sweep_reach


def arc_loop(start_deg, through_deg, end_deg, radius=10.0):
    def at(deg):
        return [radius * math.cos(math.radians(deg)), radius * math.sin(math.radians(deg))]

    return {"kind": "profile", "start": at(start_deg),
            "segments": [{"kind": "arc", "through": at(through_deg), "to": at(end_deg)},
                         {"kind": "line", "to": at(start_deg)}]}


class ReachTest(unittest.TestCase):
    def test_an_arc_counts_by_its_farthest_point_not_by_its_ends_and_middle(self):
        # The arc from -60 to 20 degrees with its middle at -20 is farthest from the start across x at 0 degrees.
        reach = sweep_reach.reach_of(arc_loop(-60, -20, 20), {}, [0.0, 0.0], across=[0.0, 1.0])
        self.assertAlmostEqual(reach, 10.0, delta=0.01)

    def test_an_arc_point_that_is_a_formula_is_worked_out(self):
        loop = arc_loop(-60, -20, 20)
        loop["segments"][0]["through"] = [{"expr": "2 * size"}, -3.4202]
        reach = sweep_reach.reach_of(loop, {"size": 4.7}, [0.0, 0.0], across=[0.0, 1.0])
        self.assertGreater(reach, 9.0)

    def test_a_spline_counts_by_the_curve_between_its_points(self):
        loop = {"kind": "profile", "start": [0.0, 0.0],
                "segments": [{"kind": "spline", "through": [[2.0, 3.0], [4.0, 0.0]], "to": [6.0, -3.0]},
                             {"kind": "line", "to": [0.0, 0.0]}]}
        points_only = max(math.hypot(x, y) for x, y in ([2.0, 3.0], [4.0, 0.0], [6.0, -3.0]))
        self.assertGreaterEqual(sweep_reach.reach_of(loop, {}, [0.0, 0.0]), points_only)


if __name__ == "__main__":
    unittest.main()
