"""The range sampler: what a formula does over the corners of the ranges of the sizes it reads."""
import unittest

from tests import context  # noqa: F401

from lib.translator import range_check
from lib.translator.range_check import MAX_CORNER_SIZES, MAX_SETTINGS, largest_share, sweep


class Table:
    """The part of a size table the sampler uses: recipe sizes by name, Fusion names equal to recipe names."""

    def __init__(self, **sizes):
        self.sizes = {n: {"value": v, "min": lo, "max": hi} for n, (v, lo, hi) in sizes.items()}

    def size_name(self, name):
        return name if name in self.sizes else None


BOX = Table(width=(40, 20, 80), wall=(5, 2.5, 10))


class SweepTest(unittest.TestCase):
    def test_a_mixed_corner_is_found_where_each_size_alone_stays_positive(self):
        span = sweep(BOX, "width - 2 * wall", ("width", "wall"))
        self.assertEqual((span.low, span.high), (0, 75))
        self.assertFalse(span.above(0.0))
        self.assertTrue(span.at_least(0.0))

    def test_a_formula_that_stays_positive_everywhere_says_so(self):
        span = sweep(BOX, "width - wall", ("width", "wall"))
        self.assertEqual((span.low, span.high), (10, 77.5))
        self.assertTrue(span.above(0.0))

    def test_a_setting_that_cannot_be_worked_out_is_reported_and_never_passes(self):
        span = sweep(BOX, "10 / (width - 20)", ("width",))
        self.assertTrue(span.failed)
        self.assertFalse(span.above(-1000.0))
        self.assertFalse(span.at_most(1000.0))

    def test_bounds_replace_the_range_of_a_size(self):
        span = sweep(BOX, "width - 2 * wall", ("width", "wall"), bounds={"wall": (2.5, 5)})
        self.assertEqual(span.low, 10)
        self.assertTrue(span.above(0.0))

    def test_extra_settings_are_tested_besides_the_corners(self):
        span = sweep(BOX, "width - 2 * wall", ("width",), extra=[{"width": 5}])
        self.assertEqual(span.low, -5)

    def test_a_name_that_is_not_a_size_keeps_its_current_value(self):
        span = sweep(BOX, "width + 1", ("width", "unknown"))
        self.assertEqual((span.low, span.high), (21, 81))


class ManySizesTest(unittest.TestCase):
    NAMES = ["s%d" % n for n in range(MAX_CORNER_SIZES + 3)]
    MANY = Table(**{n: (5, 0, 10) for n in NAMES})

    def test_up_to_the_corner_limit_every_corner_is_tested(self):
        names = self.NAMES[:MAX_CORNER_SIZES]
        settings = range_check.corners(self.MANY, names)
        found = {tuple(s[n] for n in names) for s in settings if len(s) == len(names)}
        self.assertEqual(len(found), 2 ** MAX_CORNER_SIZES)

    def test_beyond_it_the_sample_is_bounded_and_always_the_same(self):
        first = range_check.corners(self.MANY, self.NAMES)
        self.assertLessEqual(len(first), MAX_SETTINGS)
        self.assertEqual(first, range_check.corners(self.MANY, self.NAMES))

    def test_beyond_it_all_low_all_high_and_opposite_pairs_are_still_tested(self):
        settings = range_check.corners(self.MANY, self.NAMES)
        self.assertIn({n: 0 for n in self.NAMES}, settings)
        self.assertIn({n: 10 for n in self.NAMES}, settings)
        self.assertIn({"s0": 0, "s1": 10}, settings)
        span = sweep(self.MANY, "s0 - s1", self.NAMES)
        self.assertEqual((span.low, span.high), (-10, 10))


class ShareTest(unittest.TestCase):
    def test_largest_share_that_still_holds(self):
        self.assertAlmostEqual(largest_share(lambda t: t <= 0.3), 0.3, places=6)
        self.assertEqual(largest_share(lambda t: True), 1.0)


if __name__ == "__main__":
    unittest.main()
