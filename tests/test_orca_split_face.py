"""Export for Orca passes by a Split Face that leaves the solid as it was, and leaves out one that may not."""
import unittest

from tests import context  # noqa: F401
from tests.translator_helpers import load_capture

from lib.orca_translate import translate


BODY = {"token": "t1", "name": "Body1"}


def _split_face(changed):
    capture = load_capture("filter_tray_sized")
    capture["items"].append({
        "index": 7, "name": "SplitFace1", "type": "SplitFaceFeature", "suppressed": False, "health": "ok",
        "message": "", "in_target_component": True, "bodies_after": [BODY], "data": {}, "target_changed": changed})
    return capture


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
