import unittest

from tests import context  # noqa: F401
from lib.dialog_model.sizes_table import (
    add_row, new_table, read_table, remove_row, set_row, table_to_csv, toggle_column)
from lib.dialog_model.sizes_text import read_sizes
from lib.package.units import internal_to_unit


def param(name, kind, unit, value, favourite=False):
    return {"name": name, "expression": "", "value": value, "display_value": internal_to_unit(value, unit),
            "unit": unit, "comment": "", "is_favorite": favourite, "kind": kind}


PARAMS = [
    param("width", "length", "mm", 2.0, True),
    param("angle", "angle", "deg", 0.5235987755982988, True),
    param("count", "count", "", 4.0, False),
    param("depth", "derived", "mm", 1.0, True),
    param("speed", "unsupported", "mm/s", 5.0, True),
]


class SizesTableTest(unittest.TestCase):
    def test_start_is_one_default_row_with_settable_favourites_that_reads_back(self):
        table = new_table(PARAMS)
        self.assertEqual(table.columns, ["width", "angle"])
        self.assertEqual(table_to_csv(table, PARAMS), "name,width,angle\nDefault,20,30\n")
        read = read_table(table, PARAMS)
        self.assertEqual(read.problems, [])
        self.assertEqual(read.rows, [{"name": "Default", "values": {"width": 20.0, "angle": 30.0}}])

    def test_values_are_converted_to_the_parameter_unit(self):
        table = new_table(PARAMS)
        set_row(table, 0, "Default", {"width": 2.54})
        inch = [dict(p, unit="in") if p["name"] == "width" else p for p in PARAMS]
        self.assertIn("Default,1,30", table_to_csv(table, inch))

    def test_toggle_keeps_order_and_typed_values(self):
        table = new_table(PARAMS)
        set_row(table, 0, "Default", {"width": 3.0})
        toggle_column(table, PARAMS, "count", True)
        self.assertEqual(table.columns, ["width", "angle", "count"])
        self.assertEqual(table.rows[0]["values"]["count"], 4.0)
        toggle_column(table, PARAMS, "width", False)
        toggle_column(table, PARAMS, "width", True)
        self.assertEqual(table.columns, ["width", "angle", "count"])
        self.assertEqual(table.rows[0]["values"]["width"], 3.0)

    def test_formula_and_unsupported_cannot_become_columns(self):
        table = new_table(PARAMS)
        toggle_column(table, PARAMS, "depth", True)
        toggle_column(table, PARAMS, "speed", True)
        self.assertEqual(table.columns, ["width", "angle"])

    def test_add_row_copies_selected_or_last_and_names_it(self):
        table = new_table(PARAMS)
        set_row(table, 0, "Default", {"width": 3.0})
        self.assertEqual(add_row(table), 1)
        set_row(table, 1, "Size 2", {"width": 5.0})
        add_row(table, copy_from=0)
        add_row(table)
        self.assertEqual([r["name"] for r in table.rows], ["Default", "Size 2", "Size 3", "Size 4"])
        self.assertEqual([r["values"]["width"] for r in table.rows], [3.0, 5.0, 3.0, 3.0])

    def test_new_name_skips_taken_names(self):
        table = new_table(PARAMS)
        set_row(table, 0, "size 2", {})
        add_row(table)
        self.assertEqual(table.rows[1]["name"], "Size 3")

    def test_remove_row_keeps_the_last_one(self):
        table = new_table(PARAMS)
        add_row(table)
        add_row(table)
        self.assertEqual(remove_row(table, 0), 0)
        self.assertEqual(remove_row(table), 1)
        self.assertIsNone(remove_row(table))
        self.assertEqual([r["name"] for r in table.rows], ["Size 2"])

    def test_problems_show_through_the_existing_checks(self):
        table = new_table(PARAMS)
        add_row(table)
        set_row(table, 1, "Default", {})
        self.assertIn("used twice", read_table(table, PARAMS).problems[0])
        set_row(table, 1, "", {})
        self.assertIn("name is empty", read_table(table, PARAMS).problems[0])
        table.columns = []
        set_row(table, 1, "Other", {})
        self.assertIn("at least one parameter column", read_table(table, PARAMS).problems[0])

    def test_names_with_commas_and_line_breaks_survive(self):
        table = new_table(PARAMS)
        set_row(table, 0, 'Big, "wide"\nfit', {})
        read = read_sizes(table_to_csv(table, PARAMS), PARAMS)
        self.assertEqual(read.problems, [])
        self.assertEqual(read.rows[0]["name"], 'Big, "wide" fit')


if __name__ == "__main__":
    unittest.main()
