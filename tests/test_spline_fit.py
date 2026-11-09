"""The Python port of the app's spline interpolation, and the choice of points that follows a free curve."""
import json
import math
import os
import unittest
from unittest import mock

from tests import context  # noqa: F401

from lib.translator import spline_fit

VECTORS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "spline_vectors.json")


def circle_samples(radius, count=400, sweep=2 * math.pi, start=0.0):
    return [[radius * math.cos(start + sweep * i / (count - 1)), radius * math.sin(start + sweep * i / (count - 1))]
            for i in range(count)]


class PortTest(unittest.TestCase):
    def test_curve_and_slope_match_the_app_for_each_point_set(self):
        with open(VECTORS, encoding="utf-8") as f:
            cases = json.load(f)["cases"]
        for case in cases:
            curve = spline_fit.interpolate(case["points"])
            for sample in case["samples"]:
                for got, want in ((curve.at(sample["u"]), sample["p"]), (curve.at(sample["u"], 1), sample["d1"])):
                    self.assertLess(max(abs(a - b) for a, b in zip(got, want)), 1e-9, case["points"])

    def test_a_repeated_point_in_a_row_has_no_curve(self):
        self.assertIsNone(spline_fit.interpolate([[0, 0], [1, 1], [1, 1], [2, 0]]))


class FitTest(unittest.TestCase):
    def check(self, samples):
        pieces = spline_fit.fit(samples)
        self.assertIsNotNone(pieces)
        self.assertLessEqual(spline_fit.max_error(samples, pieces), spline_fit.TOLERANCE_MM)
        for piece in pieces:
            self.assertLessEqual(len(piece) - 2, spline_fit.MAX_THROUGH)
        for a, b in zip(pieces, pieces[1:]):
            self.assertEqual(a[-1], b[0])
        return pieces

    def test_a_gentle_curve_needs_few_points(self):
        samples = [[x, 3 * math.sin(x / 4.0)] for x in [i * 0.1 for i in range(200)]]
        pieces = self.check(samples)
        self.assertEqual(len(pieces), 1)
        self.assertLess(len(pieces[0]), 20)

    def test_a_curve_that_needs_more_than_one_segment_is_split(self):
        samples = [[x, 2 * math.sin(x * 1.5)] for x in [i * 0.06 for i in range(300)]]
        with mock.patch.object(spline_fit, "MAX_THROUGH", 6):
            pieces = spline_fit.fit(samples)
        self.assertGreater(len(pieces), 1)
        self.assertTrue(all(len(piece) - 2 <= 6 for piece in pieces))
        self.assertLessEqual(spline_fit.max_error(samples, pieces), spline_fit.TOLERANCE_MM)

    def test_a_closed_loop_ends_where_it_starts(self):
        pieces = self.check(circle_samples(6.0))
        self.assertLess(math.dist(pieces[0][0], pieces[-1][-1]), 1e-9)

    def test_a_straight_run_is_a_two_point_piece(self):
        self.assertEqual(spline_fit.fit([[0, 0], [5, 0], [10, 0]]), [[[0.0, 0.0], [10.0, 0.0]]])

    def test_no_samples_have_no_fit(self):
        self.assertIsNone(spline_fit.fit([]))
        self.assertIsNone(spline_fit.fit([[1, 1], [1, 1]]))
