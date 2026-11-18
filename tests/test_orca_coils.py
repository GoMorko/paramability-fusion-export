"""Coils in the Orca copy (`orca_translate/coils.py`): Orca's sweep along a helix does not give Fusion's coil, so a
coil is left out with its own cause and the rest of the part is still copied."""
import unittest

from tests import context  # noqa: F401
from tests.coil_helpers import coil_capture
from tests.test_orca_extents import run

from lib.orca_recipe.enums import FeatureType
from lib.orca_translate import causes


class CoilTest(unittest.TestCase):
    def test_a_coil_is_left_out_and_the_part_before_it_is_copied(self):
        result = run(coil_capture())
        self.assertEqual([(g["name"], g["cause"]) for g in result.left_out], [("Coil1", causes.COIL_SHAPE)])
        self.assertIn(FeatureType.EXTRUDE, [f.type for f in result.recipe.features])
        self.assertNotIn(FeatureType.SWEEP, [f.type for f in result.recipe.features])
        self.assertNotIn(FeatureType.HELIX, [f.type for f in result.recipe.features])


if __name__ == "__main__":
    unittest.main()
