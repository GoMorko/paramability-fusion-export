import unittest

from tests import context  # noqa: F401
from lib.export_plan import dialog_rows as rows
from lib.export_plan.size_offers import initial_table, offers
from lib.params import size_table


def length(name, value=0.2, comment="", **extra):
    return dict(name=name, expression="2 mm", value=value, unit="mm", comment=comment, is_favorite=True,
                kind="length", **extra)


def offer(state="size", **extra):
    base = {"param": "wall", "state": state, "ticked": state == "size", "enabled": state in ("size", "keep"),
            "now": "2 mm", "comment": "", "formula": "", "kind": "length", "value": 2.0, "min": 1.0, "max": 4.0,
            "reason": ""}
    return {**base, **extra}


class OffersRangeTest(unittest.TestCase):
    def test_offers_carry_the_default_range_the_comment_rule_gives(self):
        params = [length("wall", comment="Wall [1..6]"), length("gap")]
        lines = {o["param"]: o for o in offers(initial_table(params), params)}
        self.assertEqual((lines["wall"]["min"], lines["wall"]["max"]), (1.0, 6.0))
        self.assertEqual((lines["gap"]["min"], lines["gap"]["max"]), (1.0, 4.0))
        self.assertEqual(lines["wall"]["comment"], "Wall [1..6]")

    def test_the_typed_range_reaches_the_recipe_size(self):
        params = [length("wall")]
        table = size_table.build(params, ["wall"], ranges={"wall": (0.5, 9.0)})
        self.assertEqual((table.sizes["wall"]["min"], table.sizes["wall"]["max"]), (0.5, 9.0))
        self.assertEqual(table.with_fixed({"gone": "x"}).sizes["wall"]["max"], 9.0)


class CellTextTest(unittest.TestCase):
    def test_each_state_has_its_plain_words(self):
        self.assertEqual(rows.status_text(offer(), True), "size")
        self.assertEqual(rows.status_text(offer("keep"), False), "stays 2 mm")
        self.assertEqual(rows.status_text(offer("formula"), False), "formula")
        locked = offer("locked", reason="wall stays fixed for now: it changes a sketch. Sketches that follow sizes "
                                        "come in a later version.")
        self.assertEqual(rows.status_text(locked, False), "fixed, changes a sketch")

    def test_the_range_cells_are_open_only_for_a_ticked_plain_row(self):
        self.assertTrue(rows.row_cells(offer(), True)["range_enabled"])
        self.assertFalse(rows.row_cells(offer("keep"), False)["range_enabled"])
        self.assertEqual(rows.row_cells(offer("formula", min=None, max=None), False)["min"], "")

    def test_a_typed_range_is_kept_over_the_default_in_the_cells(self):
        self.assertEqual(rows.row_cells(offer(), True, "0.5", "9")["max"], "9")

    def test_a_long_name_breaks_after_an_underscore_and_is_escaped(self):
        text, lines = rows.wrap_name("FilterBox_$_depth__contains_CeramicMedium")
        self.assertEqual(lines, 2)
        self.assertEqual(text, "FilterBox_$_depth__<br>contains_CeramicMedium")
        self.assertEqual(rows.wrap_name("wall<1>"), ("wall&lt;1&gt;", 1))

    def test_a_component_export_swaps_now_for_used_by(self):
        self.assertEqual(rows.columns(), ("tick", "name", "now", "min", "max", "status"))
        self.assertEqual(rows.columns(used_by=True)[2], "used_by")

    def test_details_show_comment_formula_or_reason_of_the_row(self):
        self.assertIn("Comment: Wall [1..4]", rows.details_html(offer(comment="Wall [1..4]"), True))
        self.assertIn("from 1 to 4", rows.details_html(offer(), True))
        self.assertIn("Tick it", rows.details_html(offer("keep"), False))
        self.assertIn("a * b", rows.details_html(offer("formula", formula="a * b"), False))
        self.assertIn("Why.", rows.details_html(offer("locked", reason="Why."), False))


class RangeCheckTest(unittest.TestCase):
    def check(self, lo, hi, **extra):
        return rows.check_range(offer(**extra), lo, hi)

    def test_a_range_around_the_value_is_accepted_with_a_unit_or_a_comma(self):
        self.assertEqual(self.check("1 mm", "4,5"), ("", (1.0, 4.5)))

    def test_each_wrong_range_says_what_to_fix(self):
        self.assertIn("type a number", self.check("", "4")[0])
        self.assertIn("Min must be below Max", self.check("4", "4")[0])
        self.assertIn("must sit between", self.check("3", "9")[0])

    def test_a_count_needs_whole_numbers_inside_the_cap(self):
        count = dict(kind="count", value=4.0, now="4")
        self.assertEqual(self.check("1", "8", **count)[0], "")
        self.assertIn("whole numbers", self.check("1.5", "8", **count)[0])
        self.assertIn("whole numbers", self.check("0", "8", **count)[0])
        self.assertIn("at most 64", self.check("1", "70", **count)[0])

    def test_only_ticked_rows_are_read_and_the_first_problem_is_kept(self):
        offs = [offer(param="a"), offer("keep", param="b"), offer(param="c")]
        ranges, problem = rows.read_ranges(offs, [True, False, True], ["1", "x", "5"], ["4", "x", "9"])
        self.assertEqual(ranges, {"a": (1.0, 4.0)})
        self.assertIn("c: the number now", problem)


class CountLineTest(unittest.TestCase):
    def test_a_problem_beats_the_limit_which_beats_the_count(self):
        self.assertEqual(rows.count_line(6, "wall: bad."), "wall: bad.")
        self.assertIn("up to 16", rows.count_line(16, over=True))
        self.assertEqual(rows.count_line(6),
                         "6 of 16 sizes ticked. Every parameter also comes along as a variable.")


if __name__ == "__main__":
    unittest.main()
