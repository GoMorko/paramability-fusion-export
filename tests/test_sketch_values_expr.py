"""The symbolic value type of sketch formulas (lib/sketch_values/expr.py): normal form, linear values, formula text,
files and evaluation."""
import math
import unittest

from tests import context  # noqa: F401

from lib.sketch_values.expr import Expr, ExprDomainError, cos, name, num, sin, sqrt, tan


class NormalFormTest(unittest.TestCase):
    def test_cos_squared_plus_sin_squared_is_one(self):
        a, w = name("a"), name("w")
        self.assertTrue((w * cos(a) * cos(a) + w * sin(a) * sin(a)).same(w))

    def test_whole_quarter_turns_leave_the_argument(self):
        a = name("a")
        self.assertTrue(cos(a + 90).same(-sin(a)))
        self.assertTrue(sin(180 - a).same(sin(a)))
        self.assertTrue(cos(-a).same(cos(a)))
        self.assertTrue(cos(num(90)).same(0))

    def test_shared_factors_cancel_in_a_quotient(self):
        w, h = name("w"), name("h")
        self.assertTrue(((2 * w + 4) / (w + 2)).same(2))
        self.assertTrue(((w * h) / (w * 3)).same(h / 3))
        self.assertTrue((sqrt(w) * sqrt(w)).same(w))

    def test_a_linear_value_is_an_affine(self):
        w, h = name("w"), name("h")
        affine = (0.5 * w - h + 3).as_affine()
        self.assertEqual((affine.const, affine.terms), (3.0, {"w": 0.5, "h": -1.0}))
        self.assertIsNone((w * h).as_affine())
        self.assertIsNone(cos(w).as_affine())


class ValueTest(unittest.TestCase):
    def test_value_in_degrees(self):
        e = name("L") * cos(name("a")) + sqrt(name("w")) / tan(name("a"))
        env = {"L": 10.0, "a": 30.0, "w": 9.0}
        self.assertAlmostEqual(e.value(env), 10 * math.cos(math.radians(30)) + 3 / math.tan(math.radians(30)))

    def test_no_value_for_a_negative_square_root_or_a_zero_divisor(self):
        with self.assertRaises(ExprDomainError):
            sqrt(name("w") - 5).value({"w": 1.0})
        with self.assertRaises(ExprDomainError):
            (num(1) / (name("w") - 5)).value({"w": 5.0})

    def test_names_substitute_and_file_round_trip(self):
        e = name("d1") * sin(name("d2") + 30) / (name("d3") - name("d1")) + 2
        self.assertEqual(set(e.names()), {"d1", "d2", "d3"})
        back = Expr.from_json(e.json())
        self.assertTrue(back.same(e))
        moved = e.substitute({"d1": name("Width") * 2, "d3": 40})
        env = {"Width": 3.0, "d2": 15.0}
        self.assertAlmostEqual(moved.value(env), e.value({"d1": 6.0, "d2": 15.0, "d3": 40.0}))

    def test_formula_text(self):
        e = 0.5 * name("w") - name("h") * cos(name("a")) + 4
        self.assertEqual(e.text(), "-h * cos(a) + 0.5 * w + 4")
        self.assertEqual(e.text(lambda n: {"w": "Width_mm", "h": "a + b", "a": "Angle"}[n]),
                         "-(a + b) * cos(Angle) + 0.5 * Width_mm + 4")
        self.assertEqual((name("w") / (name("h") + 1)).text(), "w / (h + 1)")


if __name__ == "__main__":
    unittest.main()
