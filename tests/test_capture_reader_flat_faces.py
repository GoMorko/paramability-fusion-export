"""Reader of a join through all: the flat faces of the target body square to the sketch normal, read before it."""
import unittest

from tests import context  # noqa: F401
from tests.test_capture_reader import Coll, FakeDesign, Obj, body, extrude, read_capture, rect_profile, sketch_entry
from tests.test_capture_reader_emboss import face_of

THROUGH = Obj("fusion::ThroughAllExtentDefinition", isPositiveDirection=True)


def read(faces, operation="JoinFeatureOperation", extent=THROUGH):
    target = body()
    target.faces = Coll([face(target) for face in faces])
    step = extrude(rect_profile(), target=target, operation=operation, extentOne=extent)
    design = FakeDesign([sketch_entry(), step], target)
    return read_capture(design, target, fusion="", name="", up_axis="z")["items"][1]["data"]


class FlatFacesTest(unittest.TestCase):
    def test_a_join_through_all_lists_the_flat_faces_square_to_its_sketch_with_their_side(self):
        faces = [lambda b: face_of("Plane", 10, b), lambda b: face_of("Plane", 0, b, normal=(0, 0, -1)),
                 lambda b: face_of("Plane", 5, b, normal=(1, 0, 0)), lambda b: face_of("Cylinder", 7, b)]
        self.assertEqual(read(faces)["target_flat_faces"], [[10.0, 1], [0.0, -1]])

    def test_a_face_that_cannot_be_read_gives_none(self):
        broken = lambda b: Obj("fusion::BRepFace", geometry=Obj("core::Plane"), body=b)  # noqa: E731
        self.assertIsNone(read([lambda b: face_of("Plane", 10, b), broken])["target_flat_faces"])

    def test_a_cut_or_a_join_with_a_distance_does_not_read_them(self):
        self.assertNotIn("target_flat_faces", read([], operation="CutFeatureOperation"))
        self.assertNotIn("target_flat_faces", read([], extent=Obj("fusion::DistanceExtentDefinition",
                                                                  distance=Obj(value=1.0))))


if __name__ == "__main__":
    unittest.main()
