import unittest

from tests import context  # noqa: F401
from lib.dialog_model import dialog_rows as rows
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


class FormulaOfNumbersTest(unittest.TestCase):
    def test_a_formula_of_numbers_is_offered_as_a_size_and_not_as_a_formula(self):
        params = [{**length("wall", value=0.12), "expression": "3 * 0.4 mm"}]
        line = offers(initial_table(params), params)[0]
        self.assertEqual((line["state"], line["ticked"], line["enabled"]), ("size", True, True))


class CellTextTest(unittest.TestCase):
    def test_each_state_has_its_plain_words(self):
        self.assertEqual(rows.status_text(offer(), True), "size")
        self.assertEqual(rows.status_text(offer("keep"), False), "stays 2 mm")
        self.assertEqual(rows.status_text(offer("formula"), False), "formula")
        locked = offer("locked", reason="wall stays fixed: it moves a joint.")
        self.assertEqual(rows.status_text(locked, False), "fixed, moves a joint")
        doubtful = offer(doubt="wall may give unexpected results: it moves a joint.")
        self.assertEqual(rows.status_text(doubtful, True), "size, may be unexpected")
        self.assertIn("it moves a joint", rows.details_html(doubtful, True))

    def test_the_range_cells_are_open_only_for_a_ticked_plain_row_and_a_typed_range_wins(self):
        self.assertTrue(rows.row_cells(offer(), True)["range_enabled"])
        self.assertFalse(rows.row_cells(offer("keep"), False)["range_enabled"])
        self.assertEqual(rows.row_cells(offer("formula", min=None, max=None), False)["min"], "")
        self.assertEqual(rows.row_cells(offer(), True, "0.5", "9")["max"], "9")

    def test_a_long_name_is_cut_in_the_middle_and_short_ones_stay(self):
        name = "FilterBox_$_depth__contains_CeramicMedium"
        text, lines = rows.name_cell(name)
        self.assertEqual(lines, 1)
        self.assertLessEqual(len(text), rows.NAME_WIDTH)
        self.assertTrue(text.startswith("FilterBox_") and text.endswith("CeramicMedium"))
        self.assertEqual(rows.name_cell("wall<1>"), ("wall&lt;1&gt;", 1))

    def test_a_text_needs_one_row_per_line_it_fills_up_to_the_cap(self):
        self.assertEqual(rows.text_rows(["short"]), 1)
        self.assertEqual(rows.text_rows(["a" * (rows.LINE_WIDTH + 1), "b"]), 3)
        self.assertEqual(rows.text_rows(["a" * 1000]), rows.MAX_ROWS)
        self.assertEqual(rows.text_rows([]), 1)

    def test_quotes_stay_plain_and_markup_is_escaped_for_a_read_only_box(self):
        self.assertEqual(rows.escape('a "b" <c> & d'), 'a "b" &lt;c&gt; &amp; d')
        html_text = rows.details_html(offer(comment='say "hi"', param='w"all'), True)
        self.assertIn('<b>w"all</b>', html_text)
        self.assertIn('Comment: say "hi"', html_text)
        self.assertNotIn("&quot;", rows.details_panel(None, False, None, None, 'x "y"')[0])


class RangeCheckTest(unittest.TestCase):
    def check(self, lo, hi, **extra):
        return rows.check_range(offer(**extra), lo, hi)

    def test_a_range_around_the_value_is_accepted_with_a_unit_or_a_comma(self):
        self.assertEqual(self.check("1 mm", "4,5"), ("", (1.0, 4.5)))

    def test_each_wrong_range_says_what_to_fix(self):
        for lo, hi in (("", "4"), ("4", "4"), ("3", "9")):
            with self.subTest((lo, hi)):
                self.assertTrue(self.check(lo, hi)[0])

    def test_a_count_needs_whole_numbers_inside_the_cap(self):
        count = dict(kind="count", value=4.0, now="4")
        self.assertEqual(self.check("1", "8", **count)[0], "")
        for lo, hi in (("1.5", "8"), ("0", "8"), ("1", "70")):
            with self.subTest((lo, hi)):
                self.assertTrue(self.check(lo, hi, **count)[0])

    def test_only_ticked_rows_are_read_and_the_first_problem_is_kept(self):
        offs = [offer(param="a"), offer("keep", param="b"), offer(param="c")]
        ranges, problem = rows.read_ranges(offs, [True, False, True], ["1", "x", "5"], ["4", "x", "9"])
        self.assertEqual(ranges, {"a": (1.0, 4.0)})
        self.assertIn("c:", problem)


class UnitTest(unittest.TestCase):
    INCH = dict(range_unit="in", now="1 in", value=25.4, min=12.7, max=50.8)

    def test_the_default_range_shows_in_the_design_unit_and_angles_say_deg(self):
        cells = rows.row_cells(offer(**self.INCH), True)
        self.assertEqual((cells["min"], cells["max"]), ("0.5", "2"))
        angle = rows.row_cells(offer(kind="angle", range_unit="deg", min=10.0, max=90.0), True)
        self.assertEqual((angle["min"], angle["max"]), ("10 deg", "90 deg"))

    def test_a_typed_number_is_read_in_the_design_unit_and_typed_units_are_converted(self):
        self.assertEqual(rows.check_range(offer(**self.INCH), "0.75", "2")[1], (19.05, 50.8))
        self.assertEqual(rows.check_range(offer(**self.INCH), "15 mm", "5 cm")[1], (15.0, 50.0))
        self.assertEqual(rows.parse_number("90 deg", "deg"), 90.0)

    def test_a_unit_of_another_kind_or_on_a_count_is_refused(self):
        self.assertIsNone(rows.parse_number("2 deg", "in"))
        self.assertIsNone(rows.parse_number("2 mm", ""))
        self.assertIsNone(rows.parse_number("2 parsecs", "mm"))

    def test_the_default_texts_give_back_the_exact_default_numbers(self):
        self.assertEqual(rows.check_range(offer(**self.INCH), "0.5", "2")[1], (12.7, 50.8))
        thin = offer(**{**self.INCH, "min": 1.0, "now": "1 in"})
        self.assertEqual(rows.check_range(thin, rows.cell_text(thin, 1.0), "2")[1][0], 1.0)

    def test_a_comma_is_a_decimal_mark_only_when_the_meaning_is_clear(self):
        self.assertEqual(rows.parse_number("0,125", "mm"), 0.125)
        self.assertEqual(rows.parse_number("4,5", "mm"), 4.5)
        for text in ("1,000", "2,500", "1,000,000", "1.000,5"):
            self.assertIsNone(rows.parse_number(text, "mm"), text)

    def test_the_shown_value_is_accepted_as_min_up_to_the_digits_shown(self):
        near = offer(value=0.1234567891, min=1.0, max=4.0, now="0.1234567891 mm")
        self.assertEqual(rows.check_range(near, "0.123456789", "4")[0], "")


class CountLineTest(unittest.TestCase):
    def test_a_problem_beats_the_limit_which_beats_the_count(self):
        self.assertEqual(rows.count_line(6, "wall: bad."), "wall: bad.")
        self.assertIn("up to 64", rows.count_line(64, over=True))
        self.assertIn("6 of 64", rows.count_line(6))


if __name__ == "__main__":
    unittest.main()
