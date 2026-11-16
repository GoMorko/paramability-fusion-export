"""Export for Orca passes by a Split Face that leaves the solid as it was, and leaves out one that may not."""
import unittest

from tests import context  # noqa: F401
from tests.test_translate_other_bodies import BODY, _item, tray_with

from lib.orca_translate import translate


def _split_face(changed):
    return tray_with(_item(7, "SplitFace1", "SplitFaceFeature", [BODY], target_changed=changed))


class OrcaSplitFaceTest(unittest.TestCase):
    def test_a_split_face_that_leaves_the_solid_alone_is_skipped(self):
        result = translate(_split_face(False), None)
        self.assertNotIn("SplitFace1", [g["name"] for g in result.left_out])
        self.assertEqual({v["name"]: v["verdict"] for v in result.items}["SplitFace1"], "skipped")

    def test_a_split_face_that_may_have_changed_the_solid_is_left_out(self):
        for changed in (True, None):
            with self.subTest(target_changed=changed):
                result = translate(_split_face(changed), None)
                self.assertIn("SplitFace1", [g["name"] for g in result.left_out])


if __name__ == "__main__":
    unittest.main()
