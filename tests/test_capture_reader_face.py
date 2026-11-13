"""Reader of a flat face used as an extrude outline: its plane, its edges as curves, and the extrude that made it."""
import math
import unittest

from tests import context  # noqa: F401
from tests.test_capture_reader import Coll, FakeDesign, Obj, P, body, entry, extrude, line, sketch_entry
from tests.test_capture_reader_offset import plane_face, side, with_outline
from tests.test_capture_reader_spline import curve_on

from lib.fusion_reader.capture import read_capture

WALLS = [side((0, -1, 0)), side((1, 0, 0)), side((0, 1, 0)), side((-1, 0, 0))]


def read(face, earlier=(), **kw):
    """The data of an extrude at timeline index 1 whose outline is `face`; `earlier` are the component's extrudes."""
    target = body()
    face.body, face.area = target, 8.0
    kw.setdefault("endFaces", Coll([Obj("fusion::BRepFace", pointOnFace=P(5, 5, 13))]))
    item = extrude(face, name="Extrude2", target=target, operation="JoinFeatureOperation",
                   timelineObject=Obj(index=1), **kw)
    design = FakeDesign([sketch_entry(), item], target)
    design.rootComponent.features = Obj(extrudeFeatures=Coll(list(earlier)))
    return read_capture(design, target, fusion="", name="", up_axis="z")["items"][1]["data"]


def earlier_extrude(index, **faces):
    found = {k: Coll(faces.get(k, ())) for k in ("startFaces", "endFaces", "sideFaces")}
    return Obj("fusion::ExtrudeFeature", name="Extrude%d" % index, timelineObject=Obj(index=index), **found)


class FaceOutlineReaderTest(unittest.TestCase):
    def test_a_top_face_gives_its_plane_its_edges_and_the_extrude_that_made_it(self):
        face = with_outline(plane_face(10), WALLS)
        made = earlier_extrude(0, endFaces=[Obj("fusion::BRepFace", entityToken="top")])
        later = earlier_extrude(1, endFaces=[Obj("fusion::BRepFace", entityToken="top")])
        data = read(face, [made, later])
        record = data["profiles"][0]
        self.assertEqual(record["frame"], {"origin": [0, 0, 10], "x": [1, 0, 0], "y": [0, 1, 0], "z": [0, 0, 1]})
        self.assertEqual(record["loops"][0]["curves"][1], {"kind": "line", "start": [40, 0], "end": [40, 20]})
        self.assertEqual(record["made_by"], {"index": 0, "name": "Extrude0", "which": "end"})
        self.assertEqual((record["face_point"], record["body"]["token"]), ([5, 5, 10], "b1"))
        self.assertEqual((data["profile_area"], data["end_offset"]), (800.0, 3.0))

    def test_a_free_edge_is_sampled_over_the_edge_only(self):
        face = plane_face(0)
        half = curve_on(lambda t: (10 * math.cos(math.pi * t), 10 * math.sin(math.pi * t)))
        whole = curve_on(lambda t: (10 * math.cos(math.pi * t), 10 * math.sin(math.pi * t)), extents=(0.0, 2.0))
        edges = [Obj("fusion::BRepEdge", geometry=whole, evaluator=half.evaluator),
                 Obj("fusion::BRepEdge", geometry=line((-10, 0, 0), (10, 0, 0)))]
        face.loops = Coll([Obj(isOuter=True, edges=Coll(edges))])
        free = read(face)["profiles"][0]["loops"][0]["curves"][0]
        self.assertEqual((free["kind"], free["start"], free["end"]), ("other", [10.0, 0.0], [-10.0, 0.0]))

    def test_a_face_no_extrude_lists_has_no_maker(self):
        made = earlier_extrude(0, sideFaces=[Obj("fusion::BRepFace", entityToken="wall")])
        self.assertNotIn("made_by", read(with_outline(plane_face(10), WALLS), [made])["profiles"][0])

    def test_a_curved_face_and_unreadable_edges(self):
        curved = read(Obj("fusion::BRepFace", geometry=Obj("core::Cylinder")))["profiles"][0]
        self.assertEqual(curved, {"face": True, "type": "BRepFace", "surface": "Cylinder"})
        unread = plane_face(10)
        unread.loops = Obj(count=1)
        self.assertEqual(read(unread)["profiles"][0]["problem"], "unread")


if __name__ == "__main__":
    unittest.main()
