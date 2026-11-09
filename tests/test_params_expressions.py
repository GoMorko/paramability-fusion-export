import unittest

from tests import context  # noqa: F401
from lib.params.expressions import ExpressionError, Typed, evaluate, parse, referenced_names, render, translate_tree
from lib.params.expressions import LENGTH, SCALAR


def translate(text, names=None, design_mm=1.0):
    """Translate with names mapped to (size name, dim); returns the Typed result."""
    names = names or {}

    def resolve(name):
        if name not in names:
            raise ExpressionError(f"Unknown {name}")
        size, dim = names[name]
        return Typed(("name", size), dim, False)

    return translate_tree(parse(text), resolve, design_mm)


class TranslateTest(unittest.TestCase):
    def test_filter_box_formula_keeps_owner_names_and_drops_units(self):
        names = {"W$": ("W_", SCALAR), "cube_mm": ("cube_mm", LENGTH)}
        t = translate("W$ * cube_mm + 2 mm", names)
        self.assertEqual(render(t.node), "W_ * cube_mm + 2")
        self.assertEqual(t.dim, LENGTH)

    def test_units_become_mm(self):
        self.assertEqual(render(translate("1 in + 2 cm").node), "25.4 + 20")
        self.assertEqual(render(translate("0.05 mm").node), "0.05")

    def test_caret_becomes_pow(self):
        names = {"wall": ("wall", SCALAR)}
        self.assertEqual(render(translate("wall ^ 2", names).node), "pow(wall, 2)")

    def test_bare_number_added_to_a_length_uses_the_design_unit(self):
        names = {"wall": ("wall", LENGTH)}
        self.assertEqual(render(translate("wall + 5", names).node), "wall + 5")
        self.assertEqual(render(translate("wall + 5", names, design_mm=25.4).node), "wall + 127")

    def test_brackets_and_functions(self):
        names = {"a": ("a", LENGTH), "b": ("b", LENGTH)}
        self.assertEqual(render(translate("(a + b) * 2", names).node), "(a + b) * 2")
        self.assertEqual(render(translate("a - (b - 1 mm)", names).node), "a - (b - 1)")
        self.assertEqual(render(translate("min(a, 5 mm)", names).node), "min(a, 5)")
        self.assertEqual(render(translate("sqrt(a * a)", names).node), "sqrt(a * a)")

    def test_refusals(self):
        names = {"a": ("a", LENGTH), "n": ("n", SCALAR)}
        for text in ("sin(a)", "a + 1 deg", "a ^ n", "a $ 2", "a +", "2 kg", "PI * a"):
            with self.assertRaises(ExpressionError, msg=text):
                translate(text, names)

    def test_evaluate_matches_the_written_formula(self):
        self.assertAlmostEqual(evaluate("W_ * cube + 2", {"W_": 1.8, "cube": 18.0}), 34.4)
        self.assertEqual(evaluate("round(2.5) + abs(-1) + pow(2, 3)", {}), 12.0)
        with self.assertRaises(ExpressionError):
            evaluate("1 / 0", {})

    def test_referenced_names_in_order_without_function_names(self):
        self.assertEqual(referenced_names("min(b, a) + b * 2 mm"), ["b", "a"])
        self.assertEqual(referenced_names("a +"), [])


if __name__ == "__main__":
    unittest.main()
