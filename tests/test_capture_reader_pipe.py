"""Reader of pipe features: section, cover of the path, path curves and made end faces."""
import unittest

from tests import context  # noqa: F401
from tests.test_capture_reader import Coll, Obj, body
from tests.test_capture_reader_sweep import face, line3, parameter, path, read, sketch, sketch_curve, step


def read_pipe(kind=Obj, **members):
    base = dict(path=path(step(sketch_curve(line3((0, 0, 0), (0, 50, 0)), sketch()))),
                sectionType="CircularPipeSectionType", sectionSize=parameter(1.0, "d1", "pipe_mm"), isHollow=True,
                sectionThickness=parameter(0.2, "d2", "2 mm"), distanceOne=parameter(1.0, "d3", "1"),
                distanceTwo=None, operation="NewBodyFeatureOperation", participantBodies=Coll([body()]),
                startFaces=Coll([face(0)]), endFaces=Coll([face(50)]))
    base.update(members)
    return read("PipeFeature", "Pipe1", base, kind)


class TwoBroken(Obj):
    @property
    def distanceTwo(self):
        raise RuntimeError("not available")


class SizeBroken(Obj):
    @property
    def sectionSize(self):
        raise RuntimeError("not available")


class PipeReaderTest(unittest.TestCase):
    def test_the_section_cover_operation_and_parameters_are_read(self):
        data = read_pipe()
        self.assertEqual((data["section"], data["section_size"], data["hollow"], data["section_thickness"]),
                         ("circular", 10.0, True, 2.0))
        self.assertEqual((data["distance_one"], data["distance_two"], data["operation"]), (1.0, None, "newBody"))
        self.assertNotIn("distance_two_unread", data)
        self.assertEqual({k: v["name"] for k, v in data["params"].items()},
                         {"section_size": "d1", "section_thickness": "d2", "distance_one": "d3"})

    def test_the_path_and_the_made_end_faces_are_read(self):
        data = read_pipe()
        self.assertEqual((data["path"]["kind"], len(data["path"]["curves"])), ("sketch", 1))
        self.assertEqual(data["path"]["curves"][0]["kind"], "line")
        self.assertEqual((data["faces_after"]["start"][0]["point"][2], data["faces_after"]["end"][0]["point"][2]),
                         (0.0, 50.0))

    def test_a_solid_pipe_has_no_wall(self):
        self.assertIsNone(read_pipe(isHollow=False)["section_thickness"])

    def test_a_second_distance_is_read_and_one_that_raises_is_marked_unread(self):
        self.assertEqual(read_pipe(distanceTwo=parameter(0.5, "d4", "0.5"))["distance_two"], 0.5)
        data = read_pipe(TwoBroken)
        self.assertEqual((data["distance_two"], data["distance_two_unread"]), (None, True))

    def test_square_and_unknown_sections_are_named(self):
        self.assertEqual(read_pipe(sectionType="SquarePipeSectionType")["section"], "square")
        self.assertEqual(read_pipe(sectionType="OtherPipeSectionType")["section"], "other")

    def test_a_section_size_that_cannot_be_read_is_null(self):
        data = read_pipe(SizeBroken)
        self.assertIsNone(data["section_size"])
        self.assertNotIn("section_size", data["params"])


if __name__ == "__main__":
    unittest.main()
