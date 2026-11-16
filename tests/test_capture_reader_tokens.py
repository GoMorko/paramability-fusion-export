"""Tokens the capture records so the size probe can find sketch geometry again (docs/capture-format.md)."""
import math
import unittest

from tests import context  # noqa: F401
from tests.test_capture_reader import Coll, FakeDesign, Obj, P, body, entry, feature, line, matrix
from lib.fusion_reader import read_sketch
from lib.fusion_reader.capture import read_capture


def sketch(token="sk1", reference=None):
    members = {"name": "Sketch1", "transform": matrix(), "entityToken": token}
    if reference is not None:
        members["referencePlane"] = reference
    return Obj("fusion::Sketch", **members)


def profile(sk, tokens):
    curves = [Obj(geometry=line(a, b), sketchEntity=Obj(entityToken=t) if t else None) for (a, b), t in tokens]
    loop = Obj(isOuter=True, profileCurves=Coll(curves))
    return Obj("fusion::Profile", parentSketch=sk, profileLoops=Coll([loop]))


SQUARE = [(((0, 0), (10, 0)), "c1"), (((10, 0), (10, 10)), "c2"), (((10, 10), (0, 10)), "c3"), (((0, 10), (0, 0)), "c4")]


class ProfileTokensTest(unittest.TestCase):
    def test_sketch_token_curve_entities_and_reference(self):
        plane = Obj("fusion::ConstructionPlane", entityToken="cp1")
        record = read_sketch.read_profile(profile(sketch(reference=plane), SQUARE))
        self.assertEqual(record["sketch_token"], "sk1")
        self.assertEqual(record["reference"], {"kind": "constructionPlane", "token": "cp1"})
        self.assertEqual([c["entity"] for c in record["loops"][0]["curves"]], ["c1", "c2", "c3", "c4"])

    def test_a_construction_plane_says_what_it_is_built_on(self):
        from tests.test_capture_reader_finish import face, plane_geometry
        base = face("f1", geometry=plane_geometry((0, 0, 10), (0, 0, 1)))
        plane = Obj("fusion::ConstructionPlane", entityToken="cp1", timelineObject=Obj(index=2),
                    geometry=plane_geometry((0, 0, 8), (0, 0, 1)),
                    definition=Obj("fusion::ConstructionPlaneOffsetDefinition", planarEntity=base))
        reference = read_sketch.read_profile(profile(sketch(reference=plane), SQUARE))["reference"]
        self.assertEqual((reference["token"], reference["made_by"], reference["definition"]),
                         ("cp1", 2, "ConstructionPlaneOffsetDefinition"))
        self.assertEqual(reference["built_on"], [{"entity_type": "BRepFace", "face_point": [0, 1, 2],
                                                  "surface": "Plane"}])

    def test_reference_kinds(self):
        kinds = {"BRepFace": "face", "Plane": "plane", "Vertex": "other"}
        for name, kind in kinds.items():
            with self.subTest(name):
                ref = Obj("fusion::" + name, entityToken="t")
                self.assertEqual(read_sketch.read_profile(profile(sketch(reference=ref), SQUARE))["reference"]["kind"], kind)

    def test_missing_members_leave_the_keys_out(self):
        record = read_sketch.read_profile(profile(Obj("fusion::Sketch", name="S", transform=matrix()),
                                                  [(a, None) for a, _ in SQUARE]))
        for key in ("sketch_token", "reference"):
            self.assertNotIn(key, record)
        self.assertNotIn("entity", record["loops"][0]["curves"][0])


def read_item(feature_pair):
    target = body()
    design = FakeDesign([entry(feature_pair)], target)
    return read_capture(design, target, fusion="", name="", up_axis="z")["items"][0]["data"]


class FeatureTokensTest(unittest.TestCase):
    def hole(self, points):
        return feature("HoleFeature", "Hole1", holeType="SimpleHoleType", holeTapType="SimpleHoleTapType",
                       holeDiameter=Obj(value=0.5), tipAngle=Obj(value=math.radians(118)),
                       direction=Obj(x=0.0, y=0.0, z=-1.0), position=P(0, 0, 0),
                       holePositionDefinition=Obj("fusion::SketchPointsHolePositionDefinition",
                                                  sketchPoints=Coll(points)),
                       extentDefinition=Obj("fusion::ThroughAllExtentDefinition"), sideFaces=Coll([]),
                       endFaces=Coll([]))

    def point(self, token, sk, at):
        return Obj(entityToken=token, parentSketch=sk, worldGeometry=P(*at))

    def test_hole_on_sketch_points_has_sketch_and_point_tokens(self):
        sk = sketch()
        data = read_item(self.hole([self.point("p1", sk, (1, 2, 3)), self.point("p2", sk, (4, 5, 6))]))
        self.assertEqual((data["sketch_token"], data["sketch"], data["point_tokens"]), ("sk1", "Sketch1", ["p1", "p2"]))

    def test_hole_points_on_two_sketches_have_no_point_tokens(self):
        data = read_item(self.hole([self.point("p1", sketch("a"), (1, 2, 3)), self.point("p2", sketch("b"), (4, 5, 6))]))
        self.assertEqual(data["sketch_token"], "a")
        self.assertNotIn("point_tokens", data)

    def revolve(self, axis):
        return read_item(feature("RevolveFeature", "Revolve1", operation="NewBodyFeatureOperation",
                                 profile=profile(sketch(), SQUARE), axis=axis, isProjectAxis=False,
                                 extentDefinition=Obj("fusion::AngleExtentDefinition", angle=Obj(value=6.28),
                                                      isSymmetric=False)))

    def test_revolve_axis_from_a_sketch_line_names_the_line_its_sketch_and_where_that_sits(self):
        plane = Obj("fusion::ConstructionPlane", entityToken="cp1")
        projected = Obj("fusion::SketchLine", isReference=True)
        sk = Obj("fusion::Sketch", name="Sketch1", transform=matrix(), entityToken="sk1", referencePlane=plane,
                 sketchCurves=Coll([projected]), sketchPoints=Coll([]))
        axis = Obj("fusion::SketchLine", worldGeometry=line((0, 0, 0), (0, 3, 0)), entityToken="ln1", parentSketch=sk)
        found = self.revolve(axis)["axis"]
        self.assertEqual((found["entity"], found["sketch_token"], found["sketch"], found["entity_type"]),
                         ("ln1", "sk1", "Sketch1", "SketchLine"))
        self.assertEqual((found["sketch_reference"], found["sketch_projected"]),
                         ({"kind": "constructionPlane", "token": "cp1"}, True))

    def test_revolve_axis_from_a_construction_axis_says_what_it_is(self):
        axis = Obj("fusion::ConstructionAxis", entityToken="ax1",
                   geometry=Obj("core::InfiniteLine3D", origin=P(0, 0, 4), direction=Obj(x=1.0, y=0.0, z=0.0)))
        self.assertEqual(self.revolve(axis)["axis"], {"point": [0, 0, 4], "dir": [1, 0, 0], "token": "ax1",
                                                      "entity_type": "ConstructionAxis"})

    def test_a_revolve_axis_that_cannot_be_used_records_what_it_is(self):
        curved = Obj("fusion::BRepEdge", geometry=Obj("core::Arc3D"))
        self.assertEqual(self.revolve(curved)["axis"], {"kind": "other", "type": "BRepEdge", "geometry": "Arc3D"})
        broken = Obj("fusion::ConstructionAxis", entityToken="ax1")  # no geometry: reading it raises
        found = self.revolve(broken)["axis"]
        self.assertEqual((found["kind"], found["type"]), ("other", "ConstructionAxis"))
        self.assertTrue(found["error"])

    def test_extrude_target_token_for_construction_planes_and_faces(self):
        plane = Obj("fusion::ConstructionPlane", entityToken="cp1",
                    geometry=Obj("core::Plane", origin=P(0, 0, 5), normal=Obj(x=0.0, y=0.0, z=1.0)))
        face = Obj("fusion::BRepFace", entityToken="f1", pointOnFace=P(1, 1, 5),
                   geometry=Obj("core::Plane", origin=P(0, 0, 5), normal=Obj(x=0.0, y=0.0, z=1.0)))
        for entity, token in ((plane, "cp1"), (face, "f1")):
            data = read_item(feature("ExtrudeFeature", "E", operation="NewBodyFeatureOperation",
                                     extentType="OneSideFeatureExtentType", profile=profile(sketch(), SQUARE),
                                     startExtent=Obj("fusion::FromEntityStartDefinition", entity=entity),
                                     extentOne=Obj("fusion::DistanceExtentDefinition", distance=Obj(value=1.0)),
                                     taperAngleOne=Obj(value=0.0), isThinExtrude=False, endFaces=Coll([])))
            self.assertEqual(data["start"].get("token"), token)

    def test_rectangular_pattern_direction_from_a_sketch_line_names_its_sketch(self):
        direction = Obj("fusion::SketchLine", worldGeometry=line((0, 0, 0), (5, 0, 0)), parentSketch=sketch("sk7"))
        data = read_item(feature("RectangularPatternFeature", "R", inputEntities=Coll([]),
                                 directionOneEntity=direction, quantityOne=Obj(value=3),
                                 distanceOne=Obj(value=2.0), patternElements=Coll([])))
        # The sketch's plane and projections could not be read: null, which counts as "may move".
        self.assertEqual(data["direction_one_sketch"], {"sketch_token": "sk7", "sketch": "Sketch1", "reference": None,
                                                        "projected": None})
        self.assertNotIn("direction_two_sketch", data)


class ProjectionTest(unittest.TestCase):
    def test_a_sketch_holds_projections_when_a_curve_or_a_point_other_than_its_origin_is_projected(self):
        origin = Obj("fusion::SketchPoint", entityToken="o", isReference=True)

        def holds(curves=(), points=()):
            return read_sketch.holds_projection(Obj("fusion::Sketch", originPoint=origin, sketchCurves=Coll(curves),
                                                    sketchPoints=Coll([origin] + list(points))))
        own, projected = Obj(isReference=False), Obj(isReference=True)
        self.assertEqual((holds([own], [own]), holds([projected]), holds([own], [projected])), (False, True, True))
        self.assertIsNone(read_sketch.holds_projection(Obj("fusion::Sketch")))
