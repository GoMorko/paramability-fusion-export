"""Reader of rib and web features: the curves as ordered chains, the settings by their API names, the parameters, and
the faces the feature made with their corners. The fakes use the member names of `RibFeature` and `WebFeature`."""
import json
import unittest

from tests import context  # noqa: F401
from tests.test_capture_reader import Coll, Obj, P, matrix
from tests.test_capture_reader_sweep import line3, read, sketch, sketch_curve

from lib.fusion_reader import read_rib


class Unreadable(Obj):
    """A feature whose `isSymmetric`, `draftAngle` and `curves` cannot be read."""

    @property
    def isSymmetric(self):
        raise RuntimeError("not available")

    @property
    def draftAngle(self):
        raise RuntimeError("not available")

    @property
    def curves(self):
        raise RuntimeError("roll the marker back first")


def parameter(cm, name, expression):
    return Obj(value=cm, name=name, expression=expression)


def face(point, normal, corners):
    return Obj("fusion::BRepFace", geometry=Obj("core::Plane"), pointOnFace=P(*point),
               evaluator=Obj(getNormalAtPoint=lambda at: (True, Obj(x=normal[0], y=normal[1], z=normal[2]))),
               vertices=Coll([Obj(geometry=P(*c)) for c in corners]))


PLANE = sketch(name="RibLine", token="sk1", transform=matrix())


def lines(*pairs):
    return [sketch_curve(line3(a, b), PLANE, token="ln%d" % n) for n, (a, b) in enumerate(pairs)]


def members(curves, **extra):
    found = dict(curves=curves, thickness=parameter(0.2, "d10", "rt"), isSymmetric=True, extentType=1,
                 depth=parameter(0.5, "d11", "rd"), isFlipped=False, draftAngle=None, filletRadius=None,
                 faces=Coll([]))
    found.update(extra)
    return found


def read_feature(kind, curves, made=Obj, **extra):
    data = read(kind, kind[:3] + "1", members(curves, **extra), kind=made)
    json.dumps(data)
    return data


class RibReaderTest(unittest.TestCase):
    def test_a_rib_reads_its_settings_parameters_and_one_chain_in_order(self):
        # The second line of the chain is listed first: the chain still runs from (0, 0) to (30, 0) to (30, 20).
        curves = lines(((30, 0, 0), (30, 20, 0)), ((0, 0, 0), (30, 0, 0)))
        data = read_feature("RibFeature", curves)
        self.assertEqual((data["kind"], data["thickness"], data["symmetric"], data["extent"], data["depth"]),
                         ("rib", 2.0, True, "distance", 5.0))
        self.assertEqual((data["flipped"], data["draft_deg"], data["fillet"]), (False, 0.0, 0.0))
        self.assertEqual([(c["entity"], c["flat"]["start"], c["flat"]["end"], c["opposed"])
                          for c in data["path"]["curves"]],
                         [("ln1", [0, 0], [30, 0], False), ("ln0", [30, 0], [30, 20], False)])
        self.assertEqual(data["path"]["sketch_token"], "sk1")
        self.assertEqual({k: v["expression"] for k, v in data["params"].items()}, {"thickness": "rt", "depth": "rd"})
        self.assertNotIn("extended", data)

    def test_the_faces_the_rib_made_carry_their_corners(self):
        made = [face((15, 0, 1), (0, -1, 0), [(0, 0, 0), (30, 0, 0), (30, 0, 2), (0, 0, 2)])]
        data = read_feature("RibFeature", lines(((0, 0, 0), (30, 0, 0))), faces=Coll(made))
        self.assertEqual(data["wall_faces"], [{"surface": "Plane", "point": [15, 0, 1], "normal": [0, -1, 0],
                                               "vertices": [[0, 0, 0], [30, 0, 0], [30, 0, 2], [0, 0, 2]]}])

    def test_a_face_with_too_many_corners_has_none(self):
        corners = [(n, 0, 0) for n in range(read_rib.MAX_FACE_VERTICES + 1)]
        made = [face((1, 0, 0), (0, -1, 0), corners)]
        data = read_feature("RibFeature", lines(((0, 0, 0), (30, 0, 0))), faces=Coll(made))
        self.assertIsNone(data["wall_faces"][0]["vertices"])

    def test_members_that_cannot_be_read_are_null(self):
        data = read_feature("RibFeature", lines(((0, 0, 0), (30, 0, 0))), made=Unreadable)
        self.assertIsNone(data["symmetric"])
        self.assertIsNone(data["draft_deg"])
        self.assertIsNone(data["paths"])
        self.assertNotIn("path", data)

    def test_to_next_has_no_depth(self):
        data = read_feature("RibFeature", lines(((0, 0, 0), (30, 0, 0))), extentType=0, depth=None)
        self.assertEqual((data["extent"], data["depth"]), ("toNext", None))
        self.assertNotIn("depth", data["params"])


class WebReaderTest(unittest.TestCase):
    def test_a_web_of_two_lines_apart_reads_two_chains_and_whether_fusion_extends_them(self):
        curves = lines(((0, 0, 0), (30, 0, 0)), ((15, -10, 0), (15, 10, 0)))
        data = read_feature("WebFeature", curves, isExtended=True)
        self.assertEqual((data["kind"], data["extended"]), ("web", True))
        self.assertEqual([[c["entity"] for c in p["curves"]] for p in data["paths"]], [["ln0"], ["ln1"]])

    def test_curves_that_branch_give_no_chains(self):
        curves = lines(((0, 0, 0), (10, 0, 0)), ((10, 0, 0), (20, 0, 0)), ((10, 0, 0), (10, 10, 0)))
        self.assertIsNone(read_feature("WebFeature", curves, isExtended=False)["paths"])


if __name__ == "__main__":
    unittest.main()
