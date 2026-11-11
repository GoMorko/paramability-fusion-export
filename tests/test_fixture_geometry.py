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

    def test_prism_hole_mirror_revolve_and_loft_fixtures_match_their_stored_geometry(self):
        for name in ("extrude_plate", "hole_through", "mirror_body", "revolve_full", "loft_two_squares"):
            with self.subTest(name):
                self.check(name)


if __name__ == "__main__":
    unittest.main()
