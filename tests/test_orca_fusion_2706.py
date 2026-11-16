"""Copies of made-up test models exported from Fusion 2706 (tests/fixtures/captures/p7_*.json): what that Fusion gives
for a full length thread, a symmetric revolve and a sketch on a face, in the Orca copy and the recipe."""
import unittest

from tests import context  # noqa: F401
from tests.orca_sized import fixture, table_of

from lib.orca_recipe.enums import FeatureType
from lib.orca_translate import translate
from lib.probe.plane_sizes import plane_driven
from lib import translator


def outcomes(result):
    return {p["name"]: p["outcome"] for p in result.parameters}


class Fusion2706Test(unittest.TestCase):
    def test_a_full_length_thread_without_length_or_offset_is_copied(self):
        result = translate(fixture("p7_threaded_rod"))
        self.assertEqual(result.left_out, [])
        self.assertEqual(len([f for f in result.recipe.features if f.type == FeatureType.THREAD]), 1)

    def test_a_symmetric_revolve_of_270_degrees_to_each_side_is_a_closed_ring(self):
        capture = fixture("p7_revolve_symmetric_ring")
        result = translate(capture, table_of(capture))
        (made,) = [f for f in result.recipe.features if f.type == FeatureType.REVOLVE]
        self.assertEqual((made.revolve_angle, result.left_out), (360.0, []))
        self.assertEqual(outcomes(result)["Sweep"], "fixed")

    def test_the_height_under_a_boss_on_a_face_without_a_reference_is_marked(self):
        capture = fixture("p7_boss_on_face_mirror")
        result = translate(capture, table_of(capture))
        self.assertEqual(result.left_out, [])
        self.assertEqual(outcomes(result)["T21_Height"], "partly")


class RecipeBossOnFaceTest(unittest.TestCase):
    """Fusion gives no reference for the boss sketch on the plate's top face, which T21_Height moves."""

    def test_without_a_probe_the_height_is_marked(self):
        capture = fixture("p7_boss_on_face_mirror")
        result = translator.translate(capture, size_table=table_of(capture))
        self.assertIn("T21_Height", {d["name"] for d in result.loose + result.fixed + result.dropped})

    def test_the_probe_tries_the_height_so_the_boss_plane_is_measured(self):
        capture = fixture("p7_boss_on_face_mirror")
        self.assertIn("T21_Height", plane_driven(capture, table_of(capture)))


if __name__ == "__main__":
    unittest.main()
