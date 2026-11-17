"""Typical printing formulas, made up, and whether each follows its sizes.

Each case is a set of user parameters (as the reader gives them) or a feature value that reads them, and the test asks
whether the size table and `values.quantity` keep the formula so the shape follows a size changed in Paramability.
A case marked expected failure waits for the change that fixes that class of formula.
"""
import unittest

from tests import context  # noqa: F401
from tests.params_fixtures import mm, plain_param, reader_dicts

from lib.params import size_table
from lib.translator.values import quantity


class Ctx:
    """The parts of the translator context that `quantity` uses."""

    def __init__(self, table):
        self.table = table
        self.doubts = []
        self.cuts = {}

    def ask(self, item, path, same_as=None):
        pass

    def doubt(self, names, why, fixed=False, cut=None):
        self.doubts.append((tuple(names), why))

    def cut(self, ranges, why):
        self.cuts.update(ranges)
        self.doubt(list(ranges), why, cut=ranges)


def inch(value):
    return value * 2.54


def table_of(raw, ticked, model=(), unit="mm", quantities=()):
    params = reader_dicts(raw, {})
    return size_table.build(params, ticked, list(model), unit, quantity_params=list(quantities))


def model_param(name, expression, value, unit="mm"):
    """A model parameter dict; `value` is mm, degrees or a plain number."""
    return {"name": name, "expression": expression, "value": value, "unit": unit, "role": "", "kind": "derived",
            "created_by": {"kind": "feature", "component": ""}}


def value_of(table, param, literal, dim="length", whole=False, absolute=False):
    """`values.quantity` of one feature value, and the context that recorded what it could not follow."""
    ctx = Ctx(table)
    item = {"data": {"params": {"v": {"name": param["name"], "expression": param["expression"], "value": literal}}}}
    return quantity(ctx, item, "v", literal, dim=dim, whole=whole, absolute=absolute), ctx


def entry_state(table, name):
    return table.entry(name).state


BOX = [
    plain_param("Width", "40 mm", mm(40), "mm"),
    plain_param("Wall", "2 mm", mm(2), "mm"),
    plain_param("Inner", "Width - 2 * Wall", mm(36), "mm"),
    plain_param("Lid", "Width + 2 * Wall + 0.4 mm", mm(44.4), "mm"),
    plain_param("Radius", "Wall * 1.5", mm(3), "mm"),
]

# A bin built from whole units, as Gridfinity style designs do.
BIN = [
    plain_param("Units_X", "3", 3, "", isFavorite=True),
    plain_param("Units_Y", "2", 2, "", isFavorite=True),
    plain_param("Pitch", "42 mm", mm(42), "mm"),
    plain_param("Tolerance", "0.5 mm", mm(0.5), "mm"),
    plain_param("Outer_X", "Units_X * Pitch - Tolerance", mm(125.5), "mm"),
    plain_param("Outer_Y", "Units_Y * Pitch - Tolerance", mm(83.5), "mm"),
    plain_param("Slots", "Units_X * Units_Y * 2", 12, ""),
]

INCH = [
    plain_param("Width", "2 in", inch(2), "in"),
    plain_param("Outer", "Width + 1/8 in", inch(2.125), "in"),
    plain_param("Bolt", "3/8 in", inch(0.375), "in"),
    plain_param("Slack", "Width + 1/8", inch(2.125), "in"),
]

GRID = [
    plain_param("Width", "100 mm", mm(100), "mm"),
    plain_param("Pitch", "20 mm", mm(20), "mm"),
]

PLAIN_FORMULAS = [
    plain_param("Wall", "3 * 0.4 mm", mm(1.2), "mm"),
    plain_param("Plate", "25.4 * 2 mm", mm(50.8), "mm"),
]


class FormulaCorpusTest(unittest.TestCase):
    def test_box_and_lid_formulas_become_derived_sizes(self):
        table = table_of(BOX, ["Width", "Wall"])
        self.assertEqual({n: entry_state(table, n) for n in ("Inner", "Lid", "Radius")},
                         {"Inner": "derived", "Lid": "derived", "Radius": "derived"})
        self.assertEqual(table.sizes["Inner"]["expr"].replace(" ", ""), "Width-2*Wall")

    def test_box_feature_values_follow_the_sizes(self):
        table = table_of(BOX, ["Width", "Wall"], [model_param("d1", "Width - 2 * Wall", 36)])
        q, ctx = value_of(table, {"name": "d1", "expression": "Width - 2 * Wall"}, 36, absolute=True)
        self.assertTrue(q.sized)
        self.assertEqual(ctx.doubts, [])

    def test_bin_sizes_and_counts_follow_the_units(self):
        slots = model_param("d2", "Units_X * Units_Y * 2", 12, "")
        table = table_of(BIN, ["Units_X", "Units_Y"], [slots], quantities=[slots])
        self.assertEqual(entry_state(table, "Outer_X"), "derived")
        q, ctx = value_of(table, {"name": "d2", "expression": "Units_X * Units_Y * 2"}, 12, dim="scalar", whole=True)
        self.assertTrue(q.sized)
        self.assertEqual(ctx.doubts, [])

    def test_inch_fractions_follow_their_size_with_or_without_a_unit_word(self):
        table = table_of(INCH, ["Width"], unit="in")
        self.assertEqual({n: entry_state(table, n) for n in ("Outer", "Slack")}, {"Outer": "derived", "Slack": "derived"})

    def test_formula_of_numbers_is_a_size_that_can_be_ticked(self):
        table = table_of(PLAIN_FORMULAS, ["Wall", "Plate"])
        self.assertEqual({n: entry_state(table, n) for n in ("Wall", "Plate")}, {"Wall": "free", "Plate": "free"})
        self.assertAlmostEqual(table.sizes["Wall"]["value"], 1.2)

    def test_guarded_count_follows_the_size(self):
        table = table_of(GRID, ["Width"])
        expression = "max(1; floor(Width / Pitch))"
        q, ctx = value_of(table, {"name": "d3", "expression": expression}, 5, dim="scalar", whole=True)
        self.assertTrue(q.sized)
        self.assertEqual(ctx.doubts, [])

    def test_count_chosen_with_if_follows_the_size(self):
        table = table_of(GRID, ["Width"])
        expression = "if(Width > 30 mm; 3; 2)"
        q, ctx = value_of(table, {"name": "d3", "expression": expression}, 3, dim="scalar", whole=True)
        self.assertTrue(q.sized)
        self.assertEqual(ctx.doubts, [])

    def test_count_that_can_be_a_part_number_stays_a_number(self):
        table = table_of(GRID, ["Width"])
        for expression, literal in (("max(1; Width / Pitch)", 5), ("if(Width > 30 mm; 2.5; 3)", 2.5)):
            q, ctx = value_of(table, {"name": "d3", "expression": expression}, literal, dim="scalar", whole=True)
            self.assertFalse(q.sized, expression)
            self.assertEqual(len(ctx.doubts), 1, expression)

    def test_depth_that_is_a_difference_of_sizes_follows_with_cut_ranges(self):
        raw = [plain_param("Outer", "30 mm", mm(30), "mm"), plain_param("Width", "20 mm", mm(20), "mm")]
        table = table_of(raw, ["Outer", "Width"], [model_param("d1", "Outer - Width", 10)])
        q, ctx = value_of(table, {"name": "d1", "expression": "Outer - Width"}, 10, absolute=True)
        self.assertTrue(q.sized)
        self.assertTrue(ctx.cuts)


if __name__ == "__main__":
    unittest.main()
