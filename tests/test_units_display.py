import unittest

from tests import context  # noqa: F401
from lib.package.units import internal_to_unit


class DisplayUnitsTest(unittest.TestCase):
    def test_length_units_from_cm(self):
        self.assertAlmostEqual(internal_to_unit(2.0, "mm"), 20.0)
        self.assertAlmostEqual(internal_to_unit(2.54, "in"), 1.0)
        self.assertAlmostEqual(internal_to_unit(2.0, "cm"), 2.0)

    def test_angles_and_counts(self):
        self.assertAlmostEqual(internal_to_unit(3.141592653589793, "deg"), 180.0)
        self.assertAlmostEqual(internal_to_unit(1.5, "rad"), 1.5)
        self.assertEqual(internal_to_unit(4, ""), 4)


if __name__ == "__main__":
    unittest.main()
