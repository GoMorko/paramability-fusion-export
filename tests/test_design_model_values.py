"""The value type both translators write (`design_model/values.py`): a number with, when sizes move it, a formula
over those sizes."""
import unittest

from tests import context  # noqa: F401

from lib.design_model.values import Quantity, Sized, negated, negated_text, number, numbers_of, reads_in
from lib.orca_translate.context import Context


class QuantityTest(unittest.TestCase):
    def test_operations_keep_formulas_readable(self):
        q = Quantity(10.0, "a + b", ("a",))
        self.assertEqual(q.scaled(0.5).text, "0.5 * (a + b)")
        self.assertEqual(q.scaled(-1).text, "-(a + b)")
        self.assertEqual(q.plus(-2).text, "a + b - 2")
        self.assertEqual(Quantity(1.0).plus(q).text, "1 + (a + b)")
        self.assertEqual(q.divided_by(Quantity(4.0, "n", ("n",))).text, "(a + b) / n")

    def test_negating_a_name_or_a_group_takes_the_minus_off_instead_of_stacking_it(self):
        self.assertEqual(negated_text("w"), "-w")
        self.assertEqual(negated_text("-w"), "w")
        self.assertEqual(negated_text("-(a + b)"), "a + b")
        self.assertEqual(negated_text("a + b"), "-(a + b)")

    def test_magnitude_drops_the_sign_of_the_number_and_of_its_formula(self):
        below = Quantity(-4.0, "-w", ("w",)).magnitude()
        self.assertEqual((below.n, below.text), (4.0, "w"))
        above = Quantity(4.0, "w", ("w",))
        self.assertIs(above.magnitude(), above)
        self.assertEqual(Quantity(-3.0).magnitude().n, 3.0)


class WrittenValueTest(unittest.TestCase):
    def test_a_written_formula_remembers_its_number_and_the_sizes_it_reads(self):
        written = Quantity(5.0, "w + 1", ("w",)).json()
        self.assertIsInstance(written, Sized)
        self.assertEqual((dict(written), number(written), reads_in({"a": [written]})), ({"expr": "w + 1"}, 5.0, ("w",)))
        flipped = negated(written)
        self.assertEqual((flipped["expr"], number(flipped), flipped.reads), ("-(w + 1)", -5.0, ("w",)))
        self.assertEqual(numbers_of({"a": [written, 2.0]}), {"a": [5.0, 2.0]})


class OrcaSharesTheTypeTest(unittest.TestCase):
    def test_a_context_value_is_the_shared_quantity(self):
        ctx = Context({"items": []}, None, None)
        self.assertIsInstance(ctx.quantity({"data": {}}, "x", 3), Quantity)


if __name__ == "__main__":
    unittest.main()
