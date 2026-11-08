import unittest

from tests import context  # noqa: F401
from lib.package import units


class UnitsTest(unittest.TestCase):
    def test_kinds(self):
        self.assertEqual(units.unit_kind("mm"), "length")
        self.assertEqual(units.unit_kind("deg"), "angle")
        self.assertEqual(units.unit_kind(""), "count")
        self.assertEqual(units.unit_kind(None), "count")
        self.assertEqual(units.unit_kind("mm/s"), "unknown")
        self.assertEqual(units.unit_kind("kg"), "unknown")

    def test_manifest_unit(self):
        self.assertEqual(units.manifest_unit("in"), "mm")
        self.assertEqual(units.manifest_unit("rad"), "deg")
        self.assertEqual(units.manifest_unit("Unitless"), "")

    def test_unknown_unit_is_never_converted_as_a_count(self):
        self.assertEqual(units.manifest_unit("mm/s"), "")
        with self.assertRaises(ValueError):
            units.to_manifest_value(3, "mm/s")

    def test_conversions(self):
        self.assertAlmostEqual(units.cm_to_mm(2.5), 25.0)
        self.assertAlmostEqual(units.rad_to_deg(3.141592653589793), 180.0)
        self.assertEqual(units.to_manifest_value(4.0, "mm"), 40.0)
        self.assertEqual(units.to_manifest_value(3.141592653589793 / 2, "deg"), 90.0)
        self.assertEqual(units.to_manifest_value(3, ""), 3)


if __name__ == "__main__":
    unittest.main()
