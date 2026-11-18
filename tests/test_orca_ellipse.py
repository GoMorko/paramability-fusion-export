"""Ellipses in the Orca copy: a full ellipse is one Orca ellipse entity, an elliptical arc stays out."""
import copy
import math
import unittest

from tests import context  # noqa: F401
from tests.translator_helpers import load_capture

from lib.orca_recipe.enums import EntityType, FeatureType
from lib.orca_translate import translate
from lib.orca_translate.sketches import entities_of


def run(capture):
    return translate(capture, None)


class EllipseTest(unittest.TestCase):
    def test_a_turned_ellipse_keeps_its_centre_major_radius_and_direction(self):
        result = run(load_capture("extrude_ellipse_turned"))
        sketch = next(f for f in result.recipe.features if f.type == FeatureType.SKETCH)
        (entity,) = sketch.entities
        self.assertEqual(entity.type, EntityType.ELLIPSE)
        self.assertEqual(entity.center, (0.0, 0.0))
        self.assertAlmostEqual(entity.radius, 10.0)
        self.assertAlmostEqual(entity.rminor, 5.0)
        self.assertAlmostEqual(entity.rotation, math.radians(30), places=5)
        self.assertEqual(result.left_out, [])

    def test_an_ellipse_with_its_axes_the_wrong_way_round_is_not_written(self):
        curve = {"kind": "ellipse", "center": [0, 0], "major_dir": [1, 0], "major_radius": 4, "minor_radius": 6}
        self.assertIsNone(entities_of([[curve]]))

    def test_an_elliptical_arc_stays_left_out(self):
        capture = copy.deepcopy(load_capture("extrude_ellipse_turned"))
        loop = capture["items"][1]["data"]["profiles"][0]["loops"][0]
        loop["curves"] = [{"kind": "other", "type": "NurbsCurve3D", "start": [10, 0], "end": [0, 5],
                           "mid": [7.07, 3.54], "samples": [[10, 0], [7.07, 3.54], [0, 5]]}]
        result = run(capture)
        self.assertEqual([f for f in result.recipe.features if f.type == FeatureType.SKETCH], [])
        self.assertEqual(len(result.left_out), 1)


if __name__ == "__main__":
    unittest.main()
