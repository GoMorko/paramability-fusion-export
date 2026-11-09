"""Reader of extrudes of sketch text: the outline areas and the volume of the part before and after the item, which the
translator compares (an extrude of plain outlines carries neither)."""
import unittest

from tests import context  # noqa: F401
from tests.test_capture_reader import FakeDesign, Obj, P, extrude, line, rect_profile
from tests.test_capture_reader_emboss import identity, lid

from lib.fusion_reader.capture import read_capture


def text_of_square(size=10):
    sketch = Obj("fusion::Sketch", name="Sketch2", entityToken="sk2", transform=identity(),
                 modelToSketchSpace=lambda p: p)
    corners = [(0, 0), (size, 0), (size, size), (0, size)]
    curves = [line(corners[n], corners[(n + 1) % 4]) for n in range(4)]
    box = Obj(minPoint=P(0, 0), maxPoint=P(size, size))
    return Obj("fusion::SketchText", parentSketch=sketch, asCurves=lambda: curves, boundingBox=box)


def read(profile, operation, after=8300.0):
    target = lid(after)
    step = extrude(profile, target=target, operation=operation)
    design = FakeDesign([step], target, appears_at=0)
    target.timeline = design.timeline
    return read_capture(design, target, fusion="", name="", up_axis="z")["items"][0]["data"]


class ExtrudeVolumeTest(unittest.TestCase):
    def test_a_new_body_of_text_is_measured_from_nothing_to_the_body_it_made(self):
        data = read(text_of_square(), "NewBodyFeatureOperation", after=300.0)
        self.assertEqual((data["areas"], data["volume_before"], data["volume_after"]), ([100.0], 0.0, 300.0))

    def test_a_join_of_text_is_measured_on_the_part_before_and_after(self):
        data = read(text_of_square(), "JoinFeatureOperation")
        self.assertEqual((data["areas"], data["volume_before"], data["volume_after"]), ([100.0], 8000.0, 8300.0))

    def test_plain_outlines_are_not_measured(self):
        data = read(rect_profile(), "JoinFeatureOperation")
        self.assertFalse({"areas", "volume_before", "volume_after"} & set(data))


if __name__ == "__main__":
    unittest.main()
