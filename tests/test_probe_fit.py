import unittest

from tests import context  # noqa: F401

from lib.probe.fit import Column, fit_value


def cols(**named):
    return [Column(n, rank, v) for rank, (n, v) in enumerate(named.items(), start=1)]


WIDTH = [32, 62, 62, 12, 17, 7, 122]  # a derived width over seven states


class FitValueTests(unittest.TestCase):
    def test_a_value_that_does_not_move_is_a_constant(self):
        result = fit_value([5, 5.00002, 5, 5], cols(w=WIDTH[:4]))
        self.assertEqual((result.kind, result.const), ("const", 5))

    def test_product_column_is_exact(self):
        result = fit_value([v / 2 + 3 for v in WIDTH], cols(w=WIDTH, other=[1, 1, 2, 3, 4, 5, 6]))
        self.assertEqual(result.kind, "affine")
        self.assertEqual(result.terms, {"w": 0.5})
        self.assertAlmostEqual(result.const, 3)

    def test_two_columns_in_rank_order(self):
        offset = [5, 5, 5, 7, 5, 5, 9]
        x = [0.5 * w - o for w, o in zip(WIDTH, offset)]
        result = fit_value(x, cols(offset=offset, w=WIDTH))
        self.assertEqual(result.terms, {"offset": -1.0, "w": 0.5})

    def test_better_ranked_of_two_equal_columns_wins(self):
        result = fit_value(WIDTH, [Column("d12", 3, WIDTH), Column("width", 1, WIDTH)])
        self.assertEqual(list(result.terms), ["width"])

    def test_scaled_copy_of_a_column_is_not_a_second_term(self):
        result = fit_value(WIDTH, [Column("width", 1, WIDTH), Column("half", 2, [w / 2 for w in WIDTH])])
        self.assertEqual(result.terms, {"width": 1.0})

    def test_coefficient_snaps_to_a_twenty_fourth_and_one_off_the_grid_is_kept(self):
        third = [w / 3 + 2e-7 * (i % 2) for i, w in enumerate(WIDTH)]
        self.assertEqual(fit_value(third, cols(w=WIDTH)).terms, {"w": 8 / 24})
        self.assertEqual(fit_value([w * 0.1 for w in WIDTH], cols(w=WIDTH)).terms, {"w": 0.1})

    def test_within_one_ten_thousandth_is_exact_and_beyond_is_not(self):
        near = [w + (5e-5 if i == 2 else 0) for i, w in enumerate(WIDTH)]
        far = [w + (5e-4 if i == 2 else 0) for i, w in enumerate(WIDTH)]
        self.assertEqual(fit_value(near, cols(w=WIDTH)).kind, "affine")
        self.assertEqual(fit_value(far, cols(w=WIDTH)).kind, "stuck")

    def test_a_curved_move_gives_up(self):
        result = fit_value([w * w / 100.0 for w in WIDTH], cols(w=WIDTH))
        self.assertEqual((result.kind, result.cause), ("stuck", "curve"))

    def test_too_few_states_is_untried(self):
        result = fit_value([10, 20], cols(w=[10, 20]))
        self.assertEqual((result.kind, result.cause), ("stuck", "untried"))

    def test_a_state_without_the_value_is_left_out(self):
        x = [w / 2 for w in WIDTH]
        x[3] = None
        self.assertEqual(fit_value(x, cols(w=WIDTH)).terms, {"w": 0.5})


if __name__ == "__main__":
    unittest.main()
