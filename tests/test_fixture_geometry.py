import importlib.util
import json
import os
import unittest

from tests.translator_helpers import fixture_path

SCRIPT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts", "fixture_geometry.py")
HAS_NUMPY = importlib.util.find_spec("numpy") is not None


@unittest.skipUnless(HAS_NUMPY, "scripts/fixture_geometry.py needs numpy")
class FixtureGeometryTest(unittest.TestCase):
    """The stored box and volume of a few fixtures still match what the script computes from the capture."""

    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location("fixture_geometry", SCRIPT)
        cls.geometry = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.geometry)

    def check(self, name, volume_tolerance=0.0):
        with open(fixture_path(name), encoding="utf-8") as f:
            capture = json.load(f)
        box, volume, _ = self.geometry.evaluate(capture)
        self.assertEqual(capture["target"]["box"], box, name)
        self.assertAlmostEqual(capture["target"]["volume_mm3"], volume, delta=volume_tolerance + 0.05, msg=name)

    def test_plain_prism(self):
        self.check("extrude_plate")

    def test_prism_with_a_through_hole(self):
        self.check("hole_through")

    def test_mirrored_body(self):
        self.check("mirror_body")

    def test_revolve(self):
        self.check("revolve_full")

    def test_finished_part_has_no_volume(self):
        with open(fixture_path("fillet_four_edges"), encoding="utf-8") as f:
            self.assertIsNone(json.load(f)["target"]["volume_mm3"])


if __name__ == "__main__":
    unittest.main()
