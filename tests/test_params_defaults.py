import unittest

from tests import context  # noqa: F401
from lib.params import defaults
from tests.params_fixtures import CUBE, D, H, W, reader_dicts


def p(name, value, unit, comment="", fav=False, kind=None):
    return dict(name=name, value=value, unit=unit, comment=comment, is_favorite=fav, kind=kind or "length")


class RangeTest(unittest.TestCase):
    def test_default_ranges(self):
        self.assertEqual(defaults.default_range("length", 20.0), (10.0, 40.0))
        self.assertEqual(defaults.default_range("number", 1.8), (0.9, 3.6))
        self.assertEqual(defaults.default_range("angle", 30.0), (0.0, 75.0))
        self.assertEqual(defaults.default_range("angle", 350.0), (305.0, 360.0))
        self.assertEqual(defaults.default_range("count", 3.0), (1.0, 6.0))
        self.assertEqual(defaults.default_range("count", 50.0), (1.0, 64.0))
        self.assertEqual(defaults.default_range("count", 100.0), (1.0, 100.0))
        self.assertEqual(defaults.default_range("length", 0.0), (0.0, 10.0))
        self.assertEqual(defaults.default_range("length", -4.0), (-8.0, -2.0))

    def test_comment_range_sets_the_range_and_the_label_stays_the_name(self):
        q = p("wall", 0.2, "mm", "Wall thickness [1..6]")
        self.assertEqual(defaults.label_for(q), "wall")
        self.assertEqual(defaults.size_range(q, "length", 2.0), (1.0, 6.0))

    def test_comment_range_that_misses_the_value_is_ignored(self):
        q = p("wall", 0.2, "mm", "Wall [5..6]")
        self.assertEqual(defaults.size_range(q, "length", 2.0), (1.0, 4.0))

    def test_label_is_the_name_whatever_the_comment_says_and_is_cut_to_120(self):
        self.assertEqual(defaults.label_for(p("a_b", 1, "mm")), "a_b")
        self.assertEqual(defaults.label_for(p("a_b", 1, "mm", "Some words")), "a_b")
        self.assertEqual(len(defaults.label_for(p("a" * 200, 1, "mm"))), 120)


class TickedTest(unittest.TestCase):
    def model(self, *reads, role=""):
        return [dict(name="d1", expression="x", value=1, unit="mm", role=role, dependency_parameters=list(reads))]

    def test_favourites_the_body_reads_are_ticked_through_derived_parameters(self):
        params = reader_dicts()
        model = self.model("FilterBox_height_mm")
        self.assertEqual(defaults.default_ticked(params, model), [H, CUBE])

    def test_no_favourite_read_ticks_every_plain_parameter_read(self):
        params = reader_dicts()
        for q in params:
            q["is_favorite"] = False
        model = self.model("FilterBox_width_mm", "FilterBox__PipeTop_offsetFromCenter_mm")
        self.assertEqual(defaults.default_ticked(params, model),
                         [W, CUBE, "FilterBox__PipeTop_offsetFromCenter_mm"])

    def test_parameters_the_body_does_not_read_are_not_ticked(self):
        self.assertEqual(defaults.default_ticked(reader_dicts(), []), [])
        self.assertEqual(defaults.default_ticked(reader_dicts(), self.model(D)), [D])

    def test_count_names_from_quantity_role(self):
        params = reader_dicts()
        self.assertEqual(defaults.count_names(params, self.model(W, role="Quantity")), {W})
        self.assertEqual(defaults.count_names(params, self.model(W, role="Distance")), set())

    def test_size_kind(self):
        self.assertEqual(defaults.size_kind(p("n", 3.0, "", kind="count"), {"n"}), "count")
        self.assertEqual(defaults.size_kind(p("n", 1.8, "", kind="count"), {"n"}), "number")
        self.assertEqual(defaults.size_kind(p("n", 3.0, "", kind="count")), "number")
        self.assertEqual(defaults.size_kind(p("a", 0.5, "deg", kind="angle")), "angle")


if __name__ == "__main__":
    unittest.main()
