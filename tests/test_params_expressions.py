import math
import unittest

from tests import context  # noqa: F401
from lib.params.expressions import ExpressionError, Typed, evaluate, parse, referenced_names, render, translate_tree
from lib.params.expressions import ANGLE, LENGTH, SCALAR


def translate(text, names=None, design_mm=1.0):
    """Translate with names mapped to (size name, dim); returns the Typed result."""
    names = names or {}

    def resolve(name):
        if name not in names:
            raise ExpressionError(f"Unknown {name}")
        size, dim = names[name]
        return Typed(("name", size), dim, False)

    return translate_tree(parse(text), resolve, design_mm)


def formula(text, names=None, design_mm=1.0):
    return render(translate(text, names, design_mm).node)


SIZES = {"w": ("w", LENGTH), "h": ("h", LENGTH), "n": ("n", SCALAR), "t": ("t", ANGLE)}


class TranslateTest(unittest.TestCase):
    def test_filter_box_formula_keeps_names_with_a_dollar_sign_and_drops_units(self):
        names = {"W$": ("W_", SCALAR), "cube_mm": ("cube_mm", LENGTH)}
        t = translate("W$ * cube_mm + 2 mm", names)
        self.assertEqual(render(t.node), "W_ * cube_mm + 2")
        self.assertEqual(t.dim, LENGTH)

    def test_units_become_mm_and_degrees(self):
        self.assertEqual(formula("1 in + 2 cm"), "25.4 + 20")
        self.assertEqual(formula("0.05 mm"), "0.05")
        self.assertEqual(formula("2 MM + 1 ft"), "2 + 304.8")
        self.assertEqual(formula('w + 2"', SIZES), "w + 50.8")
        self.assertEqual(formula("t + 10° + 100 grad", SIZES), "t + 10 + 90")

    def test_a_bare_unit_word_is_one_of_that_unit(self):
        t = translate("w / mm", SIZES)
        self.assertEqual((render(t.node), t.dim), ("w", SCALAR))
        self.assertEqual(formula("w / in", SIZES), "w / 25.4")
        self.assertEqual(translate("n * 1 mm", SIZES).dim, LENGTH)

    def test_a_unit_after_any_operand_multiplies_it(self):
        t = translate("(n + 1) mm", SIZES)
        self.assertEqual((render(t.node), t.dim), ("n + 1", LENGTH))
        t = translate("ceil(w / 42 mm)", SIZES)
        self.assertEqual((render(t.node), t.dim), ("ceil(w / 42)", SCALAR))
        self.assertEqual(formula("n rad", SIZES), "n * 180 / pi()")

    def test_caret_and_percent(self):
        self.assertEqual(formula("n ^ 2", SIZES), "pow(n, 2)")
        self.assertEqual(translate("w ^ 2 / mm", SIZES).dim, LENGTH)
        self.assertEqual(formula("w % 3 mm", SIZES), "mod(w, 3)")

    def test_bare_number_next_to_a_length_uses_the_design_unit(self):
        names = {"wall": ("wall", LENGTH)}
        self.assertEqual(formula("wall + 5", names), "wall + 5")
        self.assertEqual(formula("wall + 5", names, design_mm=25.4), "wall + 127")
        self.assertEqual(formula("wall < 5", names, design_mm=25.4), "wall < 127")

    def test_brackets_and_functions_with_either_separator(self):
        names = {"a": ("a", LENGTH), "b": ("b", LENGTH)}
        self.assertEqual(formula("(a + b) * 2", names), "(a + b) * 2")
        self.assertEqual(formula("a - (b - 1 mm)", names), "a - (b - 1)")
        self.assertEqual(formula("min(a, 5 mm)", names), "min(a, 5)")
        self.assertEqual(formula("max(a; 5; 2 mm)", names), "max(a, 5, 2)")
        self.assertEqual(formula("sqrt(a * a)", names), "sqrt(a * a)")

    def test_if_becomes_a_choice(self):
        t = translate("if(w < 500mm; 2; if(w < 1200mm; 3; 4))", SIZES)
        self.assertEqual((render(t.node), t.dim, t.lit), ("w < 500 ? 2 : w < 1200 ? 3 : 4", SCALAR, True))
        t = translate("if(n == 2; w; 0)", SIZES)
        self.assertEqual((render(t.node), t.dim), ("n == 2 ? w : 0", LENGTH))

    def test_comparisons_and_logic_words(self):
        self.assertEqual(formula("if((w < 400 mm) and (h < 400 mm); 12 mm; 18 mm)", SIZES),
                         "w < 400 && h < 400 ? 12 : 18")
        self.assertEqual(formula("w > h or not (n <> 2)", SIZES), "w > h || !(n != 2)")
        self.assertEqual(formula("w > h OR NOT n AND h > 0", SIZES), "w > h || !n && h > 0")
        self.assertEqual(formula("(w >= h) * 2", SIZES), "(w >= h) * 2")
        self.assertEqual(formula("(w <= h) + (w == h) + (w <> h)", SIZES), "(w <= h) + (w == h) + (w != h)")

    def test_trig_takes_degrees_and_inverse_trig_gives_an_angle(self):
        self.assertEqual(formula("w * sin(t)", SIZES), "w * sin(t)")
        self.assertEqual(formula("cos(30)"), "cos(30)")
        t = translate("atan(w / h)", SIZES)
        self.assertEqual((render(t.node), t.dim), ("atan(w / h)", ANGLE))

    def test_hyperbolic_functions_are_written_with_exp_and_ln(self):
        one_radian = 57.29577951308232
        for name, arg, expected in (("sinh", one_radian, math.sinh(1)), ("cosh", one_radian, math.cosh(1)),
                                    ("tanh", one_radian, math.tanh(1))):
            with self.subTest(name):
                t = translate(f"{name}(t)", SIZES)
                self.assertEqual(t.dim, SCALAR)
                self.assertAlmostEqual(evaluate(render(t.node), {"t": arg}), expected)
        for name, arg, expected in (("asinh", 2.0, math.asinh(2)), ("acosh", 2.0, math.acosh(2)),
                                    ("atanh", 0.5, math.atanh(0.5))):
            with self.subTest(name):
                t = translate(f"{name}(n)", SIZES)
                self.assertEqual(t.dim, ANGLE)
                self.assertAlmostEqual(evaluate(render(t.node), {"n": arg}), math.degrees(expected))

    def test_functions_the_app_has_too_pass_through_without_case(self):
        for text, expected in (("tan(t)", "tan(t)"), ("SIN(t)", "sin(t)"), ("asin(n)", "asin(n)"),
                               ("acos(n)", "acos(n)"), ("pow(w; 2)", "pow(w, 2)"), ("abs(w - h)", "abs(w - h)"),
                               ("floor(w / 2)", "floor(w / 2)"), ("round(w)", "round(w)"), ("ceil(n)", "ceil(n)")):
            with self.subTest(text):
                self.assertEqual(formula(text, SIZES), expected)

    def test_plain_functions_constants_and_sign(self):
        self.assertEqual(formula("exp(n) + ln(n) + log(n)", SIZES), "exp(n) + ln(n) + log(n)")
        self.assertEqual(formula("PI * w + E", SIZES), "pi() * w + exp(1)")
        self.assertEqual(formula("sign(w - 1200 mm) + 1", SIZES), "(w - 1200 > 0) + 1")

    def test_units_only_convert_numbers(self):
        names = {"a": ("a", LENGTH), "n": ("n", SCALAR), "t": ("t", ANGLE)}
        self.assertEqual(formula("a + n", names, design_mm=10.0), "a + n * 10")
        self.assertEqual(formula("max(n, a)", names), "max(n, a)")
        self.assertEqual(formula("a < t", names), "a < t")
        t = translate("sqrt(a)", names)
        self.assertEqual((render(t.node), t.dim), ("sqrt(a)", (0.5, 0)))
        self.assertEqual(translate("a ^ n", names).dim, LENGTH)

    def test_refusals(self):
        names = {"a": ("a", LENGTH), "n": ("n", SCALAR)}
        for text in ("a $ 2", "a +", "2 kg", "a < n < 2", "random()", "foo(a)"):
            with self.assertRaises(ExpressionError, msg=text):
                translate(text, names)

    def test_evaluate_matches_the_app(self):
        self.assertAlmostEqual(evaluate("W_ * cube + 2", {"W_": 1.8, "cube": 18.0}), 34.4)
        self.assertEqual(evaluate("round(2.5) + abs(-1) + pow(2, 3)", {}), 12.0)
        self.assertAlmostEqual(evaluate("sin(30)", {}), 0.5)
        self.assertEqual(evaluate("cos(90) + sin(-180)", {}), 0.0)
        self.assertAlmostEqual(evaluate("atan2(1, 1) + log(1000) + ln(exp(2)) + sign(-3)", {}), 45 + 3 + 2 - 1)
        self.assertEqual(evaluate("mod(-1, 4)", {}), 3.0)
        self.assertEqual(evaluate("w > 3 && !(w == 5) ? 1 : 2", {"w": 4}), 1.0)
        self.assertEqual(evaluate("d != 0 ? 1 / d : 0", {"d": 0}), 0.0)
        for text in ("1 / 0", "tan(90)", "sqrt(-1)", "asin(2)"):
            with self.assertRaises(ExpressionError, msg=text):
                evaluate(text, {})

    def test_owner_exports_translate(self):
        for text, values, expected in (
                ("ceil(w / 42 mm)", {"w": 100.0}, 3.0),
                ("if(h < 500 mm; 2; 3) * w / mm", {"h": 600.0, "w": 7.0}, 21.0),
        ):
            self.assertEqual(evaluate(formula(text, SIZES), values), expected)

    def test_referenced_names_in_order_without_functions_units_or_constants(self):
        self.assertEqual(referenced_names("min(b, a) + b * 2 mm"), ["b", "a"])
        self.assertEqual(referenced_names("if(c > PI; a / mm; d) and e"), ["c", "a", "d", "e"])
        self.assertEqual(referenced_names("a +"), [])


if __name__ == "__main__":
    unittest.main()
