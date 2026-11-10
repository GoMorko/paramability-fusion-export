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


def single_states(sizes, now, ends):
    """Columns and `varied` for states that each change one size to one of its `ends`, state 0 at `now`."""
    states = [dict(now)] + [dict(now, **{name: end}) for name in sizes for end in ends[name]]
    columns = [Column(name, 2, [s[name] for s in states]) for name in sizes]
    return states, columns, lambda at: {n for n in sizes if states[at][n] != now[n]}


class CandidateTests(unittest.TestCase):
    def test_columns_that_change_where_the_value_moves_come_before_better_ranked_ones_that_do_not(self):
        states = 16
        width = [10 + (5 if i == 15 else 0) for i in range(states)]
        crowd = [Column("f%d" % n, 1, [1 + (1 if i == n + 1 else 0) for i in range(states)]) for n in range(13)]
        x = [w * 0.5 for w in width]
        x[14], width[14] = 7.5, 15  # a second state of the width, so the fit is checked
        result = fit_value(x, crowd + [Column("width", 2, width)])
        self.assertEqual(result.terms, {"width": 0.5})

    def test_four_sizes_on_one_value_fit(self):
        now = {"a": 1.0, "b": 2.0, "c": 3.0, "d": 4.0}
        states, columns, _ = single_states(list(now), now, {n: (v / 2, v * 2) for n, v in now.items()})
        x = [s["a"] - s["b"] + 2 * s["c"] + 0.5 * s["d"] for s in states]
        self.assertEqual(fit_value(x, columns).terms, {"a": 1.0, "b": -1.0, "c": 2.0, "d": 0.5})


class NarrowedBlameTests(unittest.TestCase):
    def test_only_the_size_that_curves_on_its_own_is_blamed_and_the_others_still_follow(self):
        import math
        from lib.probe.series import fit_series
        now = {"angle": 120.0, "leg": 12.0, "wall": 3.0}
        ends = {"angle": (75.0, 165.0), "leg": (6.0, 24.0), "wall": (1.5, 6.0)}
        states, columns, varied = single_states(list(now), now, ends)
        states.append({"angle": 165.0, "leg": 24.0, "wall": 6.0})
        columns = [Column(c.name, 2, c.values + [states[-1][c.name]]) for c in columns]
        x = [-s["leg"] * math.cos(math.radians(s["angle"])) + s["wall"] for s in states]
        values = {}
        fit_series(values, {"k": x}, [], columns, lambda at: {n for n in now if states[at][n] != now[n]})
        stuck = values["k"]
        self.assertEqual(list(stuck.movers), ["angle"])
        self.assertEqual(stuck.rest.terms, {"leg": 0.5, "wall": 1.0})

    def test_a_value_whose_other_sizes_do_not_add_up_blames_every_size_that_moved_it(self):
        from lib.probe.series import fit_series
        now = {"a": 2.0, "b": 3.0}
        states, columns, varied = single_states(list(now), now, {"a": (1.0, 4.0), "b": (1.5, 6.0)})
        states.append({"a": 4.0, "b": 6.0})
        columns = [Column(c.name, 2, c.values + [states[-1][c.name]]) for c in columns]
        varied = lambda at: {n for n in now if states[at][n] != now[n]}  # noqa: E731
        x = [s["a"] * s["b"] for s in states]
        values = {}
        fit_series(values, {"k": x}, [], columns, varied)
        self.assertEqual(sorted(values["k"].movers), ["a", "b"])


if __name__ == "__main__":
    unittest.main()
