"""`%` in a Fusion formula: copied only when its left side stays at or above zero over the size ranges."""
import unittest

from tests import context  # noqa: F401
from lib.params import size_table
from lib.params.size_table import CONSTANT, DERIVED, NOT_OFFERED
from tests.params_fixtures import mm, plain_param, reader_dicts


def table(remainder_of, ticked=("w",)):
    """A width of 100 mm (range 50 to 200) and `r`, the remainder expression over it (value 2 mm)."""
    raw = [plain_param("w", "100 mm", mm(100.0), "mm", isFavorite=True), plain_param("r", remainder_of, mm(2.0), "mm")]
    return size_table.build(reader_dicts(raw, {"r": ["w"]}), list(ticked))


class ModuloTest(unittest.TestCase):
    def test_a_left_side_that_stays_positive_is_written_as_mod(self):
        entry = table("w % 7 mm").entry("r")
        self.assertEqual((entry.state, entry.formula), (DERIVED, "mod(w, 7)"))

    def test_a_left_side_that_reaches_below_zero_over_the_range_is_not_copied(self):
        entry = table("(w - 120 mm) % 7 mm").entry("r")
        self.assertEqual(entry.state, NOT_OFFERED)
        self.assertEqual(entry.reads, ("w",))
        self.assertTrue(entry.reason)

    def test_a_sized_formula_that_reads_such_a_value_is_not_copied(self):
        tr = table("(w - 120 mm) % 7 mm").translate("r + 1 mm")
        self.assertFalse(tr.ok)
        self.assertEqual(tr.reads, ("w",))

    def test_a_formula_of_numbers_with_a_negative_left_side_is_a_plain_number_since_it_is_never_worked_out(self):
        self.assertEqual(table("(0 mm - 20 mm) % 7 mm", ticked=()).entry("r").state, CONSTANT)

    def test_the_range_the_person_typed_decides(self):
        raw = [plain_param("w", "130 mm", mm(130.0), "mm", isFavorite=True), plain_param("r", "(w - 120 mm) % 7 mm", mm(3.0), "mm")]
        for ranges, state in (({}, NOT_OFFERED), ({"w": (125.0, 200.0)}, DERIVED)):
            built = size_table.build(reader_dicts(raw, {"r": ["w"]}), ["w"], ranges=ranges)
            self.assertEqual(built.entry("r").state, state)


if __name__ == "__main__":
    unittest.main()
