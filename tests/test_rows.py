import unittest

from tests import context  # noqa: F401
from lib.package.rows import parse_rows_csv

PARAMS = [{"name": "width", "value": 20.0}, {"name": "angle", "value": 30.0}]


class RowsTest(unittest.TestCase):
    def test_parses_rows_and_blank_keeps_current(self):
        rows, problems = parse_rows_csv("name,width,angle\nSmall,20,\nLarge,40.5,45\n", PARAMS)
        self.assertEqual(problems, [])
        self.assertEqual(rows[0], {"name": "Small", "values": {"width": 20.0, "angle": 30.0}})
        self.assertEqual(rows[1]["values"], {"width": 40.5, "angle": 45.0})

    def test_header_must_start_with_name(self):
        _, problems = parse_rows_csv("size,width\nA,1", PARAMS)
        self.assertEqual(len(problems), 1)

    def test_unknown_column(self):
        _, problems = parse_rows_csv("name,depth\nA,1", PARAMS)
        self.assertIn("depth", problems[0])

    def test_bad_number_comma_decimal(self):
        _, problems = parse_rows_csv('name,width\nA,"2,5"', PARAMS)
        self.assertIn("Size 1", problems[0])

    def test_duplicate_names_ignore_case(self):
        _, problems = parse_rows_csv("name,width\nA,1\na,2", PARAMS)
        self.assertIn("Size 2", problems[0])

    def test_empty_and_long_name(self):
        _, problems = parse_rows_csv("name,width\n,1\n" + "x" * 61 + ",2", PARAMS)
        self.assertEqual(len(problems), 2)

    def test_row_cap(self):
        text = "name,width\n" + "\n".join(f"r{i},1" for i in range(33))
        _, problems = parse_rows_csv(text, PARAMS)
        self.assertIn("at most 32", problems[0])

    def test_no_rows(self):
        self.assertEqual(len(parse_rows_csv("name,width\n", PARAMS)[1]), 1)
        self.assertEqual(len(parse_rows_csv("", PARAMS)[1]), 1)


if __name__ == "__main__":
    unittest.main()
