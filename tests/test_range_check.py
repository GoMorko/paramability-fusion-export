"""The range sampler: what a formula does over the corners of the ranges of the sizes it reads."""
import unittest
import unittest.mock

from tests import context  # noqa: F401

from lib.translator.ranges import kept_ranges, range_check
from lib.translator.ranges.range_check import MAX_CORNER_SIZES, MAX_SETTINGS, largest_share, sweep


class Table:
    """The part of a size table the sampler uses: recipe sizes by name, Fusion names equal to recipe names."""

    def __init__(self, **sizes):
        self.sizes = {n: {"value": v, "min": lo, "max": hi} for n, (v, lo, hi) in sizes.items()}

    def size_name(self, name):
        return name if name in self.sizes else None


BOX = Table(width=(40, 20, 80), wall=(5, 2.5, 10))


class MiddlesTest(unittest.TestCase):
    def test_each_size_is_tried_at_its_middle_alone_and_with_the_others_at_their_ends(self):
        found = range_check.middles(BOX, ("width", "wall"))
        self.assertIn({"width": 50.0, "wall": 6.25}, found)
        self.assertIn({"width": 50.0}, found)
        self.assertIn({"width": 50.0, "wall": 2.5}, found)
        self.assertIn({"width": 20, "wall": 6.25}, found)
        self.assertEqual(len(found), 7)

    def test_a_size_without_a_range_gives_nothing(self):
        self.assertEqual(range_check.middles(BOX, ("depth",)), [])


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


INNER = Table(a=(30, 20, 40), b=(35, 25, 45), s=(5, 0, 20), w=(3, 1, 3), m=(10, 4, 16))


class InsideExtremesTest(unittest.TestCase):
    def test_abs_of_a_difference_reaches_zero_inside_the_ranges(self):
        span = sweep(INNER, "abs(a - b) - 1", ("a", "b"))
        self.assertLessEqual(span.low, -0.999)
        self.assertFalse(span.above(0.0))

    def test_a_divisor_that_changes_sign_inside_the_range_fails(self):
        span = sweep(INNER, "w / (s - 3.3)", ("w", "s"))
        self.assertTrue(span.failed)

    def test_a_divisor_that_reaches_a_small_value_inside_is_seen_in_the_high_end(self):
        span = sweep(INNER, "w / (abs(s - 3.3) + 0.01)", ("w", "s"))
        self.assertFalse(span.failed)
        self.assertGreater(span.high, 290)
        self.assertFalse(span.at_most(30))

    def test_a_choice_is_tested_on_both_sides_of_its_switch(self):
        span = sweep(INNER, "s > 7.5 && s < 12 ? 100 : 0", ("s",))
        self.assertEqual((span.low, span.high), (0, 100))

    def test_a_mod_by_a_size_that_changes_sign_fails_and_a_min_over_a_difference_is_followed(self):
        self.assertTrue(sweep(INNER, "mod(7, s - 3.3)", ("s",)).failed)
        self.assertLess(sweep(INNER, "min(a, 50 - b) - 14", ("a", "b")).low, 0)

    def test_a_formula_of_sums_and_products_adds_no_inner_settings(self):
        with unittest.mock.patch.object(range_check, "inner_settings", side_effect=AssertionError):
            sweep(INNER, "a * b - 2 * s", ("a", "b", "s"))

    def test_the_inner_settings_stay_bounded_for_many_sizes(self):
        many = Table(**{"s%d" % n: (5, 0, 10) for n in range(12)})
        names = list(many.sizes)
        self.assertLessEqual(len(range_check.inner_settings(many, names)), range_check.MAX_INNER)
        self.assertEqual(len(range_check.inner_settings(INNER, ("a", "b", "s"))), 125)


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


class CutTable(Table):
    """A table that also answers whether a size's range was typed (none was)."""

    def typed_range(self, name):
        return False


class HoldingRangesWhereTest(unittest.TestCase):
    """`holding_ranges_where` cuts the ranges of the sizes a test reads to where the test holds."""

    TABLE = CutTable(a=(5, 1, 10), b=(5, 1, 10), c=(5, 1, 10))

    def holds(self, rule):
        """A test over the corners (or one end) of the ranges, as the path check builds it."""
        def holds(bounds, only=None):
            settings = (range_check.corners(self.TABLE, ("a", "b", "c"), bounds) if only is None
                        else [{}, {only[0]: bounds[only[0]][only[1]]}])
            return all(rule(range_check.size_env(self.TABLE, setting)) for setting in settings)
        return holds

    def cut(self, rule, balanced=True):
        return kept_ranges.holding_ranges_where(self.TABLE, ("a", "b", "c"), self.holds(rule), balanced=balanced)

    def test_a_test_that_holds_over_the_ranges_cuts_nothing(self):
        self.assertEqual(self.cut(lambda env: env["a"] < 11), {})

    def test_the_sizes_a_test_fails_for_share_the_cut_and_the_others_keep_their_ranges(self):
        found = self.cut(lambda env: env["a"] - env["b"] < 5)
        self.assertEqual(sorted(found), ["a", "b"])
        self.assertEqual((found["a"][0], found["b"][1]), (1, 10))
        self.assertLess(found["a"][1] - found["b"][0], 5)
        self.assertGreater(found["a"][1], 6.5)

    def test_unbalanced_the_far_ends_take_the_cut(self):
        found = self.cut(lambda env: env["a"] - env["b"] < 5, balanced=False)
        self.assertEqual(sorted(found), ["a"])
        self.assertEqual(found["a"][0], 1)
        self.assertAlmostEqual(found["a"][1], 6.0, places=6)

    def test_a_test_that_fails_at_the_values_now_has_no_cut_that_helps(self):
        self.assertIsNone(self.cut(lambda env: env["a"] != 5))


class ShareTest(unittest.TestCase):
    def test_largest_share_that_still_holds(self):
        self.assertAlmostEqual(largest_share(lambda t: t <= 0.3), 0.3, places=6)
        self.assertEqual(largest_share(lambda t: True), 1.0)


if __name__ == "__main__":
    unittest.main()
