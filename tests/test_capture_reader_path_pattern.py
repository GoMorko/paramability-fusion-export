"""Reader of path patterns: the path, the settings and the parameters behind the count and the distance."""
import json
import unittest

from tests import context  # noqa: F401
from tests.test_capture_reader import Coll, Obj
from tests.test_capture_reader_sweep import ROOT, edge, line3, parameter, path, read, sketch, sketch_curve, step


class NoOrientation(Obj):
    @property
    def isOrientationAlongPath(self):
        raise RuntimeError("not available")


def read_path_pattern(kind=Obj, **members):
    base = dict(inputEntities=Coll([]), patternEntityType="FeaturesPatternEntityType",
                path=path(step(sketch_curve(line3((0, 0, 0), (0, 50, 0)), sketch()))),
                quantity=parameter(3, "d5", "count"), distance=parameter(1.5, "d6", "pitch"),
                patternDistanceType="SpacingPatternDistanceType", startPoint=0.25, isFlipDirection=True,
                isSymmetric=False, isOrientationAlongPath=True, patternElements=Coll([]), suppressedElementsIds=[])
    base.update(members)
    data = read("PathPatternFeature", "PathPattern1", base, kind)
    json.dumps(data)
    return data


class PathPatternReaderTest(unittest.TestCase):
    def test_the_path_settings_and_parameters_are_read(self):
        data = read_path_pattern()
        self.assertEqual((data["path"]["kind"], data["path"]["sketch"], len(data["path"]["curves"])),
                         ("sketch", "Path1", 1))
        self.assertEqual(data["path"]["curves"][0]["kind"], "line")
        self.assertEqual((data["quantity"], data["distance"], data["distance_type"]), (3, 15.0, "spacing"))
        self.assertEqual((data["start_point"], data["flip"], data["symmetric"], data["along_path"]),
                         (0.25, True, False, True))
        self.assertEqual({path: ref["name"] for path, ref in data["params"].items()},
                         {"quantity": "d5", "distance": "d6"})
        self.assertNotIn("path_place", data)

    def test_a_path_of_one_edge_of_the_part_says_what_it_is(self):
        data = read_path_pattern(path=path(step(edge(component=ROOT))))
        self.assertEqual(data["path"]["kind"], "edges")
        self.assertEqual((data["path_place"]["own"], data["path_place"]["entity_type"]), (True, "BRepEdge"))

    def test_settings_that_cannot_be_read_are_null(self):
        data = read_path_pattern(kind=NoOrientation, startPoint=1.5)
        self.assertIsNone(data["along_path"])
        self.assertIsNone(data["start_point"])


if __name__ == "__main__":
    unittest.main()
