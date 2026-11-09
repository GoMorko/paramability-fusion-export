import unittest

from tests import context  # noqa: F401
from lib.params import names


class NamesTest(unittest.TestCase):
    def test_valid_names_are_kept(self):
        self.assertEqual(names.assign(["_CeramicMedium__Cube_width_mm"]), {"_CeramicMedium__Cube_width_mm": "_CeramicMedium__Cube_width_mm"})

    def test_dollar_becomes_underscore(self):
        old = "FilterBox_$_width__contains_CeramicMedium"
        self.assertEqual(names.assign([old])[old], "FilterBox___width__contains_CeramicMedium")

    def test_digit_start_other_characters_and_reserved(self):
        self.assertEqual(names.sanitize("2nd wall"), "p_2nd_wall")
        self.assertEqual(names.sanitize("wäll"), "w_ll")
        self.assertEqual(names.sanitize("if"), "if_")
        self.assertEqual(names.sanitize(""), "p_")

    def test_cut_to_64(self):
        self.assertEqual(len(names.sanitize("a" * 100)), 64)

    def test_clashes_keep_valid_names_and_number_the_rest(self):
        result = names.assign(["a$b", "a_b", "a b"])
        self.assertEqual(result, {"a_b": "a_b", "a$b": "a_b_2", "a b": "a_b_3"})

    def test_clash_suffix_fits_64_characters(self):
        long = "x" * 64
        result = names.assign([long, long + "$"])
        self.assertEqual(result[long + "$"], "x" * 62 + "_2")
        self.assertEqual(len(result[long + "$"]), 64)

    def test_case_is_kept(self):
        self.assertEqual(names.assign(["Width", "width"]), {"Width": "Width", "width": "width"})


if __name__ == "__main__":
    unittest.main()
