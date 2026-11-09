import json
import unittest

from tests import context  # noqa: F401
from lib.fusion_reader.capture import read_capture
from tests.test_capture_reader import (Coll, FakeDesign, Obj, P, body, entry, feature, matrix, param,
                                       sketch_entry)


def edge(token, x, closed=False):
    """A straight edge whose middle point is (x, 0, 0); a closed one starts and ends at the same vertex."""
    evaluator = Obj(getParameterExtents=lambda: (True, x - 1.0, x + 1.0),
                    getPointAtParameter=lambda t: (True, P(t, 0, 0)))
    return Obj("fusion::BRepEdge", entityToken=token, evaluator=evaluator, startVertex=Obj(entityToken="v" + token),
               endVertex=Obj(entityToken="v" + token if closed else "w" + token))


def face(token, x=0.0, edges=(), chain=(), geometry=None):
    return Obj("fusion::BRepFace", entityToken=token, pointOnFace=P(x, 1, 2), edges=Coll(edges),
               tangentiallyConnectedFaces=Coll(chain), geometry=geometry)


def plane_geometry(origin, normal):
    return Obj("core::Plane", origin=P(*origin), normal=Obj(x=normal[0], y=normal[1], z=normal[2]))


def read(entity_and_name, **extra):
    """Capture items of a one feature timeline."""
    target = body()
    design = FakeDesign([sketch_entry(), entry(entity_and_name, **extra)], target)
    return read_capture(design, target, fusion="", name="", up_axis="z")["items"][1]


def read_data(entity_and_name):
    item = read(entity_and_name)
    json.dumps(item)
    return item["data"]


def with_edges(edge_set_type, edges, **kw):
    return Obj("fusion::" + edge_set_type, edges=Coll(edges), **kw)


class FilletTest(unittest.TestCase):
    def test_constant_set_with_edge_and_face_inputs_expanded_and_unique(self):
        e1, e2, e3 = edge("e1", 1), edge("e2", 2), edge("e3", 3, closed=True)
        chain_edge = Obj("fusion::BRepEdge", entityToken="e1", evaluator=e1.evaluator,
                         startVertex=e1.startVertex, endVertex=e1.endVertex,
                         tangentiallyConnectedEdges=Coll([e1, e2]))
        edge_set = with_edges("ConstantRadiusFilletEdgeSet", [chain_edge, face("f1", edges=[e2, e3])],
                              radius=param(0.2), isTangentChain=True, continuity="TangentSurfaceContinuityType")
        data = read_data(feature("FilletFeature", "Fillet1", edgeSets=Coll([edge_set]), isRollingBallCorner=False))
        self.assertFalse(data["rolling_ball"])
        (fillet_set,) = data["sets"]
        self.assertEqual((fillet_set["kind"], fillet_set["radius"], fillet_set["continuity"]),
                         ("constant", 2.0, "tangent"))
        self.assertEqual(fillet_set["input_kinds"], ["edge", "face"])
        self.assertEqual([(e["token"], e["closed"], e["points"]) for e in fillet_set["edges"]],
                         [("e1", False, [[1, 0, 0]]), ("e2", False, [[2, 0, 0]]), ("e3", True, [[2.5, 0, 0], [3.5, 0, 0]])])

    def test_chain_is_not_followed_when_the_set_says_so(self):
        e1, e2 = edge("e1", 1), edge("e2", 2)
        picked = Obj("fusion::BRepEdge", entityToken="e1", evaluator=e1.evaluator, startVertex=e1.startVertex,
                     endVertex=e1.endVertex, tangentiallyConnectedEdges=Coll([e1, e2]))
        edge_set = with_edges("ConstantRadiusFilletEdgeSet", [picked], radius=param(0.1), isTangentChain=False,
                              continuity="TangentSurfaceContinuityType")
        data = read_data(feature("FilletFeature", "Fillet1", edgeSets=Coll([edge_set])))
        self.assertTrue(data["rolling_ball"])
        self.assertEqual([e["token"] for e in data["sets"][0]["edges"]], ["e1"])

    def test_set_kinds_continuity_and_feature_inputs(self):
        sets = [
            with_edges("VariableRadiusFilletEdgeSet", [edge("a", 1)]),
            with_edges("ChordLengthFilletEdgeSet", [edge("b", 1)]),
            with_edges("SomethingNewFilletEdgeSet", [Obj("fusion::ExtrudeFeature")]),
            with_edges("ConstantRadiusFilletEdgeSet", [edge("c", 1)], radius=param(0.1),
                       continuity="CurvatureSurfaceContinuityType"),
            with_edges("ConstantRadiusFilletEdgeSet", [edge("d", 1)], radius=param(0.1)),
        ]
        data = read_data(feature("FilletFeature", "Fillet1", edgeSets=Coll(sets)))
        self.assertEqual([s["kind"] for s in data["sets"]], ["variable", "chordLength", "other", "constant", "constant"])
        self.assertEqual(data["sets"][2]["type"], "SomethingNewFilletEdgeSet")
        self.assertEqual((data["sets"][2]["input_kinds"], data["sets"][2]["edges"]), (["feature"], []))
        self.assertEqual([s.get("continuity") for s in data["sets"][3:]], ["curvature", "other"])

    def test_unreadable_edge_sets_become_a_read_error(self):
        item = read(feature("FilletFeature", "Fillet1"))
        self.assertIn("read_error", item["data"])


class ChamferTest(unittest.TestCase):
    def test_edge_set_kinds(self):
        sets = [
            with_edges("EqualDistanceChamferEdgeSet", [edge("a", 1)], distance=param(0.1)),
            with_edges("TwoDistancesChamferEdgeSet", [edge("b", 1)], distanceOne=param(0.1), distanceTwo=param(0.3),
                       isFlipped=True),
            with_edges("DistanceAndAngleChamferEdgeSet", [edge("c", 1)], distance=param(0.2),
                       angle=param(3.141592653589793 / 4)),
            with_edges("OtherChamferEdgeSet", [edge("d", 1)]),
        ]
        data = read_data(feature("ChamferFeature", "Chamfer1", edgeSets=Coll(sets),
                                 cornerType="ChamferCornerType"))
        self.assertEqual(data["corner_type"], "chamfer")
        slim = [{k: v for k, v in s.items() if k not in ("edges", "input_kinds")} for s in data["sets"]]
        self.assertEqual(slim, [
            {"kind": "equal", "distance": 1.0},
            {"kind": "twoDistances", "distance": 1.0, "distance_two": 3.0, "flipped": True},
            {"kind": "distanceAngle", "distance": 2.0, "angle_deg": 45.0, "flipped": False},
            {"kind": "other", "type": "OtherChamferEdgeSet"},
        ])
        self.assertEqual(data["sets"][0]["edges"][0]["token"], "a")

    def test_corner_type_names(self):
        def corner(value):
            kw = {} if value is None else {"cornerType": value}
            return read_data(feature("ChamferFeature", "C", edgeSets=Coll([]), **kw))["corner_type"]
        self.assertEqual([corner(None), corner("MiterCornerType"), corner("WeirdCornerType")],
                         ["chamfer", "miter", "other"])


class ShellTest(unittest.TestCase):
    def test_faces_chain_and_thickness(self):
        neighbour = face("f2", x=5)
        top = face("f1", x=4, chain=[neighbour])
        data = read_data(feature("ShellFeature", "Shell1", inputEntities=Coll([top, face("f2", x=5)]),
                                 isTangentChain=True, insideThickness=param(0.2), outsideThickness=param(0.0),
                                 shellType="SharpOffsetShellType"))
        self.assertEqual(data, {
            "faces": [{"token": "f1", "point": [4, 1, 2]}, {"token": "f2", "point": [5, 1, 2]}],
            "bodies_input": False, "inside": 2.0, "outside": 0.0, "shell_type": "sharp"})

    def test_body_input_rounded_type_and_missing_members(self):
        data = read_data(feature("ShellFeature", "Shell1", inputEntities=Coll([body()]),
                                 insideThickness=param(0.1), shellType="RoundedOffsetShellType"))
        self.assertEqual((data["faces"], data["bodies_input"], data["outside"], data["shell_type"]),
                         ([], True, 0.0, "rounded"))
        data = read_data(feature("ShellFeature", "Shell1", inputEntities=Coll([face("f1")]),
                                 insideThickness=param(0.1)))
        self.assertEqual((data["shell_type"], len(data["faces"])), ("sharp", 1))


def element(index, shift, suppressed=False, x=(1, 0, 0), y=(0, 1, 0)):
    return Obj("fusion::PatternElement", id=index, isSuppressed=suppressed,
               transform=matrix(origin=shift, x=x, y=y))


class MarkerAwareFeature(Obj):
    """patternElements is only readable once the marker is just after the item."""

    def __init__(self, design, own_index, elements, **kw):
        super().__init__(**kw)
        self._design, self._own, self._elements = design, own_index, elements

    @property
    def patternElements(self):
        if self._design.timeline.markerPosition != self._own + 1:
            raise RuntimeError("elements read at the wrong marker")
        return Coll(self._elements)


def source_feature(index):
    return Obj("fusion::ExtrudeFeature", timelineObject=Obj(index=index))


def rectangular(**kw):
    kw.setdefault("inputEntities", Coll([source_feature(1)]))
    kw.setdefault("patternEntityType", "FeaturesPatternEntityType")
    kw.setdefault("directionOneEntity", Obj("fusion::SketchLine", worldGeometry=Obj(
        "core::Line3D", startPoint=P(0, 0, 0), endPoint=P(5, 0, 0))))
    kw.setdefault("quantityOne", param(3.0))
    kw.setdefault("distanceOne", param(2.0))
    kw.setdefault("patternDistanceType", "SpacingPatternDistanceType")
    return kw


def read_pattern(type_name, elements, **kw):
    target = body()
    pattern = MarkerAwareFeature(None, 2, elements, objectType="adsk::fusion::" + type_name,
                                 parentComponent=Obj(entityToken="root"), bodies=Coll([]), **kw)
    design = FakeDesign([sketch_entry(), entry((source_feature(1), "Source")), entry((pattern, "Pattern1"))], target)
    pattern._design = design
    item = read_capture(design, target, fusion="", name="", up_axis="z")["items"][2]
    json.dumps(item)
    return item["data"]


class RectangularPatternTest(unittest.TestCase):
    def test_row_with_elements_read_after_the_item(self):
        elements = [element(i + 1, (20 * i, 0, 0)) for i in range(3)]
        data = read_pattern("RectangularPatternFeature", elements, suppressedElementsIds=[2],
                            isSymmetricInDirectionOne=True, **rectangular())
        self.assertEqual(data["entity_type"], "features")
        self.assertEqual(data["sources"], [1])
        self.assertEqual((data["direction_one"], data["quantity_one"], data["distance_one"]), ([1.0, 0.0, 0.0], 3, 20.0))
        self.assertEqual((data["direction_two"], data["quantity_two"], data["distance_two"]), (None, 1, 0.0))
        self.assertEqual((data["distance_type"], data["symmetric_one"], data["symmetric_two"]),
                         ("spacing", True, False))
        self.assertEqual(data["suppressed_ids"], [2])
        self.assertEqual([(e["id"], e["suppressed"], e["frame"]["origin"]) for e in data["elements"]],
                         [(1, False, [0, 0, 0]), (2, False, [20, 0, 0]), (3, False, [40, 0, 0])])
        self.assertEqual(data["elements"][0]["frame"]["x"], [1.0, 0.0, 0.0])

    def test_grid_with_vector_direction_extent_and_suppressed_element(self):
        data = read_pattern(
            "RectangularPatternFeature", [element(1, (0, 0, 0)), element(2, (0, 10, 0), suppressed=True)],
            **rectangular(directionOne=Obj(x=0.0, y=2.0, z=0.0),
                          directionTwoEntity=Obj("fusion::ConstructionAxis", geometry=Obj(
                              origin=P(0, 0, 0), direction=Obj(x=0.0, y=0.0, z=-1.0))),
                          quantityTwo=param(2.0), distanceTwo=param(1.0),
                          patternDistanceType="ExtentPatternDistanceType"))
        self.assertEqual((data["direction_one"], data["direction_two"]), ([0.0, 1.0, 0.0], [0.0, 0.0, -1.0]))
        self.assertEqual((data["quantity_two"], data["distance_two"], data["distance_type"]), (2, 10.0, "extent"))
        self.assertTrue(data["elements"][1]["suppressed"])

    def test_non_feature_patterns_have_no_sources(self):
        data = read_pattern("RectangularPatternFeature", [element(1, (0, 0, 0))],
                            **rectangular(inputEntities=Coll([body()]), patternEntityType="BodiesPatternEntityType"))
        self.assertEqual((data["entity_type"], data["sources"]), ("bodies", []))

    def test_entity_type_falls_back_to_the_inputs_then_other(self):
        known = read_pattern("RectangularPatternFeature", [], **rectangular(
            inputEntities=Coll([face("f1")]), patternEntityType="NewKindOfEntityType"))
        self.assertEqual(known["entity_type"], "faces")
        unknown = read_pattern("RectangularPatternFeature", [], **rectangular(
            inputEntities=Coll([Obj("fusion::Weird")]), patternEntityType="NewKindOfEntityType"))
        self.assertEqual(unknown["entity_type"], "other")

    def test_unreadable_elements_are_a_read_error(self):
        target = body()
        pattern = feature("RectangularPatternFeature", "Pattern1", **rectangular())
        design = FakeDesign([sketch_entry(), entry(pattern)], target)
        item = read_capture(design, target, fusion="", name="", up_axis="z")["items"][1]
        self.assertIn("read_error", item["data"])


class CircularPatternTest(unittest.TestCase):
    def test_full_turn_with_turned_elements(self):
        turned = element(2, (0, 0, 0), x=(0, 1, 0), y=(-1, 0, 0))
        data = read_pattern(
            "CircularPatternFeature", [element(1, (0, 0, 0)), turned],
            inputEntities=Coll([source_feature(1)]), patternEntityType="FeaturesPatternEntityType",
            axis=Obj("fusion::ConstructionAxis", geometry=Obj(origin=P(5, 5, 0),
                                                              direction=Obj(x=0.0, y=0.0, z=1.0))),
            quantity=param(6.0), totalAngle=param(2 * 3.141592653589793), isSymmetric=False,
            suppressedElementsIds=[4, 5])
        self.assertEqual(data["axis"], {"point": [5, 5, 0], "dir": [0.0, 0.0, 1.0]})
        self.assertEqual((data["quantity"], data["total_angle_deg"], data["symmetric"]), (6, 360.0, False))
        self.assertEqual(data["suppressed_ids"], [4, 5])
        self.assertEqual(data["elements"][1]["frame"]["x"], [0.0, 1.0, 0.0])
        self.assertEqual(data["sources"], [1])

    def test_unreadable_axis_is_marked_other(self):
        data = read_pattern("CircularPatternFeature", [], inputEntities=Coll([source_feature(1)]),
                            quantity=param(3.0), totalAngle=param(1.0))
        self.assertEqual(data["axis"], {"kind": "other"})


class MirrorTest(unittest.TestCase):
    def test_features_across_a_construction_plane(self):
        data = read_data(feature(
            "MirrorFeature", "Mirror1", inputEntities=Coll([source_feature(1)]),
            patternEntityType="FeaturesPatternEntityType", isCombine=False,
            mirrorPlane=Obj("fusion::ConstructionPlane", geometry=plane_geometry((0, 0, 0), (1, 0, 0)))))
        self.assertEqual(data, {"entity_type": "features", "sources": [1],
                                "plane": {"point": [0, 0, 0], "normal": [1.0, 0.0, 0.0]}, "combine": False,
                                "target_box_before": {"min": [0, 0, 0], "max": [40, 20, 10]}})

    def test_body_mirror_about_a_planar_face_with_combine(self):
        planar = face("f9", geometry=plane_geometry((0, 0, 10), (0, 0, 1)))
        data = read_data(feature("MirrorFeature", "Mirror1", inputEntities=Coll([body()]),
                                 patternEntityType="BodiesPatternEntityType", isCombine=True, mirrorPlane=planar))
        self.assertEqual((data["entity_type"], data["sources"], data["combine"]), ("bodies", [], True))
        self.assertEqual(data["plane"], {"point": [0, 0, 10], "normal": [0.0, 0.0, 1.0]})
        self.assertEqual(data["target_box_before"], {"min": [0, 0, 0], "max": [40, 20, 10]})

    def test_target_box_is_null_while_the_target_does_not_exist(self):
        target = body()
        mirror = entry(feature("MirrorFeature", "Mirror1", inputEntities=Coll([body()]),
                               patternEntityType="BodiesPatternEntityType", isCombine=True,
                               mirrorPlane=Obj("fusion::ConstructionPlane",
                                               geometry=plane_geometry((0, 0, 0), (1, 0, 0)))))
        design = FakeDesign([sketch_entry(), mirror], target, appears_at=2)
        data = read_capture(design, target, fusion="", name="", up_axis="z")["items"][1]["data"]
        self.assertIsNone(data["target_box_before"])

    def test_curved_mirror_plane_is_null(self):
        curved = face("f9", geometry=Obj("core::Cylinder"))
        data = read_data(feature("MirrorFeature", "Mirror1", inputEntities=Coll([source_feature(1)]),
                                 patternEntityType="FeaturesPatternEntityType", mirrorPlane=curved))
        self.assertIsNone(data["plane"])


if __name__ == "__main__":
    unittest.main()
