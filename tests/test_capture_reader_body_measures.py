"""Each item carries the target body's box and volume from the marker before and after it."""
import unittest

from tests import context  # noqa: F401
from tests.test_capture_reader import FakeDesign, Obj, P, body, entry, extrude, feature, rect_profile, sketch_entry

from lib.fusion_reader.capture import read_capture


def read(design, target):
    return read_capture(design, target, fusion="", name="", up_axis="z")["items"]


def design_with_growing_target():
    """Sketch, extrude (the target appears after it), then a coil that makes the target taller and heavier."""
    target = body(volume=8.0)
    design = FakeDesign([sketch_entry(), extrude(rect_profile(), target=target),
                         entry(feature("ThickenFeature", "Coil1"))], target, appears_at=2)
    original = design.findEntityByToken

    def find(token):
        if design.timeline.markerPosition >= 3:
            target.volume, target.boundingBox = 9.0, Obj(minPoint=P(0, 0, 0), maxPoint=P(40, 20, 12))
        return original(token)

    design.findEntityByToken = find
    return design, target


class BodyMeasuresTest(unittest.TestCase):
    def test_each_item_gets_the_target_measured_before_and_after_it(self):
        design, target = design_with_growing_target()
        sketch, made, loft = read(design, target)
        self.assertEqual((sketch["target_before"], sketch["target_after"]), (None, None))
        self.assertEqual(made["target_before"], None)
        self.assertEqual(made["target_after"], {"box": {"min": [0, 0, 0], "max": [40, 20, 10]}, "volume_mm3": 8000.0})
        self.assertEqual(loft["target_before"], made["target_after"])
        self.assertEqual(loft["target_after"], {"box": {"min": [0, 0, 0], "max": [40, 20, 12]}, "volume_mm3": 9000.0})

    def test_an_unreadable_target_gives_null_and_the_other_side_stays(self):
        design, target = design_with_growing_target()
        original, good = design.findEntityByToken, target.boundingBox
        reads = []

        def find(token):
            found = original(token)
            if design.timeline.markerPosition >= 3:
                reads.append(token)
                target.boundingBox = None if len(reads) == 1 else good  # only the walk's own read fails
            return found

        design.findEntityByToken = find
        made, loft = read(design, target)[1:]
        self.assertEqual(loft["target_before"], made["target_after"])
        self.assertIsNone(loft["target_after"])


if __name__ == "__main__":
    unittest.main()
