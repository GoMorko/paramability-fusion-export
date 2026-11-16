"""The comparison logic of `scripts/output_diff.py`: paths of changes, formula checks, lines per entry."""
import unittest

from tests import context  # noqa: F401

from scripts import output_diff as od


def entry(recipe, **more):
    out = {"recipe_sha": str(recipe), "recipe": recipe, "verdicts": [], "gaps": [], "fixed": [], "loose": [],
           "cuts": [], "dropped": [], "skipped": 0, "refusal": None, "texts": {}}
    out.update(more)
    return out


def orca_entry(variables, expr, **more):
    out = {"recipe_sha": "x", "features": [{"type": 1, "name": "A", "fields": {}, "expr": expr}],
           "variables": variables, "verdicts": [], "left_out": [], "parameters": [], "bound": 0, "texts": {}}
    out.update(more)
    return out


class WalkTest(unittest.TestCase):
    def test_changed_added_removed_and_length(self):
        found = od.walk({"a": {"b": 1}, "c": [1, 2], "d": 1}, {"a": {"b": 2}, "c": [1, 2, 3], "e": 1})
        paths = {od.format_path(p): (a, b) for p, a, b in found}
        self.assertEqual(paths["a.b"], (1, 2))
        self.assertEqual(paths["c.#length"], (2, 3))
        self.assertIs(paths["d"][1], od.MISSING)
        self.assertIs(paths["e"][0], od.MISSING)

    def test_equal_values_give_no_change(self):
        self.assertEqual(od.walk({"a": [1, {"b": 2}]}, {"a": [1, {"b": 2}]}), [])

    def test_path_text(self):
        self.assertEqual(od.format_path(("recipe", "features", 3, "sketch", "expr")), "recipe.features[3].sketch.expr")


class FormulaTest(unittest.TestCase):
    ENV = {"w": 10.0, "d": 4.0}

    def test_formulas_that_agree_are_the_same(self):
        same = od.compare_formulas(lambda e: 0.5 * e["w"] + e["d"], lambda e: e["d"] + e["w"] / 2, self.ENV)
        self.assertEqual(same, "same values")

    def test_a_difference_names_the_scenario(self):
        said = od.compare_formulas(lambda e: e["w"], lambda e: 10.0, self.ENV)
        self.assertIn("w at 75%", said)

    def test_a_formula_that_fails_on_one_side_differs(self):
        def fails(e):
            raise KeyError("x")
        self.assertIn("cannot be worked out", od.compare_formulas(lambda e: 1.0, fails, self.ENV))


class EntryTest(unittest.TestCase):
    def test_equal_entries_give_no_lines(self):
        self.assertEqual(od.entry_changes("p", entry({"a": 1}), entry({"a": 1}), False), [])

    def test_app_formula_with_the_same_values(self):
        recipe = lambda text: {"sizes": {"w": {"value": 10.0}}, "x": {"expr": text}}  # noqa: E731
        lines = od.entry_changes("p", entry(recipe("0.5 * w")), entry(recipe("w / 2")))
        self.assertEqual(len(lines), 1)
        self.assertIn("same values", lines[0])
        self.assertIn("recipe.x.expr", lines[0])

    def test_app_formula_with_other_values(self):
        recipe = lambda text: {"sizes": {"w": {"value": 10.0}}, "x": {"expr": text}}  # noqa: E731
        lines = od.entry_changes("p", entry(recipe("w")), entry(recipe("w + 1")))
        self.assertIn("values differ", lines[0])

    def test_orca_variable_and_feature_formulas(self):
        old = orca_entry({"W": "64", "H": "W / 2"}, {"distance": "H"})
        new = orca_entry({"W": "64", "H": "0.5 * W"}, {"distance": "W * 0.5"})
        lines = od.entry_changes("o", old, new)
        self.assertEqual(len(lines), 2)
        self.assertTrue(all("same values" in line for line in lines))
        other = orca_entry({"W": "64", "H": "W / 2"}, {"distance": "W"})
        self.assertIn("values differ", od.entry_changes("o", old, other)[0])

    def test_lists_name_what_left_and_what_came(self):
        old = entry({}, gaps=[[1, "a"], [2, "b"]])
        new = entry({}, gaps=[[2, "b"], [3, "c"]])
        (line,) = od.entry_changes("p", old, new)
        self.assertIn("removed [[1, \"a\"]]", line)
        self.assertIn("added [[3, \"c\"]]", line)

    def test_an_error_that_appears_or_goes(self):
        (line,) = od.entry_changes("p", entry({}), {"error": "X: y"})
        self.assertIn("error changed", line)
        self.assertEqual(od.entry_changes("p", {"error": "X: y"}, {"error": "X: y"}), [])

    def test_paths_are_capped_unless_all_are_asked_for(self):
        old = entry({"v": list(range(30))})
        new = entry({"v": [n + 1 for n in range(30)]})
        self.assertEqual(len(od.entry_changes("p", old, new)), od.SHOWN + 1)
        self.assertEqual(len(od.entry_changes("p", old, new, True)), 30)


class DiffTest(unittest.TestCase):
    def test_lines_carry_capture_mode_and_translator(self):
        before = {"a.json": {"plain": {"p": entry({"x": 1}), "o": None}}}
        after = {"a.json": {"plain": {"p": entry({"x": 2}), "o": None}}, "b.json": {}}
        lines = od.diff(before, after)
        self.assertEqual([l[:3] for l in lines], [("a.json", "plain", "paramability"), ("b.json", "-", "-")])

    def test_a_mode_that_goes_is_a_line(self):
        before = {"a.json": {"plain": {"p": entry({})}, "sized": {"p": entry({})}}}
        after = {"a.json": {"plain": {"p": entry({})}}}
        self.assertEqual(od.diff(before, after), [("a.json", "sized", "-", "mode disappeared")])


if __name__ == "__main__":
    unittest.main()
