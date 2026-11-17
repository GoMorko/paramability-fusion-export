import json
import unittest

from tests import context  # noqa: F401
from lib.fusion_reader.capture import read_capture
from tests.fakes import install_adsk_core
from tests.test_capture_reader import (CM, Coll, FakeDesign, Obj, P, body, entry, feature, matrix, param,
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
        # How the set was picked: the face input, and the edge the chain grew from.
        self.assertEqual(fillet_set["faces"], [{"token": "f1", "point": [0, 1, 2]}])
        self.assertTrue(fillet_set["tangent_chain"])
        self.assertEqual([e.get("seed", False) for e in fillet_set["edges"]], [True, False, False])

    def test_chain_is_not_followed_when_the_set_says_so(self):
        e1, e2 = edge("e1", 1), edge("e2", 2)
        picked = Obj("fusion::BRepEdge", entityToken="e1", evaluator=e1.evaluator, startVertex=e1.startVertex,
                     endVertex=e1.endVertex, tangentiallyConnectedEdges=Coll([e1, e2]))
        edge_set = with_edges("ConstantRadiusFilletEdgeSet", [picked], radius=param(0.1), isTangentChain=False,
                              continuity="TangentSurfaceContinuityType")
        data = read_data(feature("FilletFeature", "Fillet1", edgeSets=Coll([edge_set])))
        self.assertTrue(data["rolling_ball"])
        self.assertEqual([e["token"] for e in data["sets"][0]["edges"]], ["e1"])
        self.assertFalse(data["sets"][0]["tangent_chain"])
        self.assertNotIn("seed", data["sets"][0]["edges"][0])

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
        slim = [{k: v for k, v in s.items() if k not in ("edges", "input_kinds", "tangent_chain")} for s in data["sets"]]
        self.assertEqual(slim, [
            {"kind": "equal", "distance": 1.0},
            {"kind": "twoDistances", "distance": 1.0, "distance_two": 3.0, "flipped": True},
            {"kind": "distanceAngle", "distance": 2.0, "angle_deg": 45.0, "flipped": False},
            {"kind": "other", "type": "OtherChamferEdgeSet"},
        ])
        self.assertEqual(data["sets"][0]["edges"][0]["token"], "a")

def normal_face(normal):
    """A face whose outward normal is `normal` everywhere."""
    return Obj("fusion::BRepFace", evaluator=Obj(getNormalAtPoint=lambda p: (True, Obj(x=normal[0], y=normal[1], z=normal[2]))))


def cut_face(nearest, normal, on_face=True):
    """A chamfer face: every point projects to `nearest` (mm), where the normal is `normal`."""
    evaluator = Obj(getParameterAtPoint=lambda p: (True, "uv"), getPointAtParameter=lambda uv: (True, P(*nearest)),
                    getNormalAtParameter=lambda uv: (True, Obj(x=normal[0], y=normal[1], z=normal[2])),
                    isParameterOnFace=lambda uv: on_face)
    return Obj("fusion::BRepFace", evaluator=evaluator)


class UnevenChamferTest(unittest.TestCase):
    def setUp(self):
        core = install_adsk_core()
        core.Point3D = type("Point3D", (), {"create": staticmethod(lambda x, y, z: Obj(x=x, y=y, z=z))})

    def test_sides_and_the_nearest_chamfer_face_are_measured_per_point(self):
        picked = edge("a", 5)
        picked.faces = Coll([normal_face((0, 0, 1)), normal_face((0, -1, 0))])
        edge_set = with_edges("TwoDistancesChamferEdgeSet", [picked], distanceOne=param(0.1), distanceTwo=param(0.2))
        faces = Coll([cut_face((5, 0.1, 0), (0, 0.9, 0.1), on_face=False), cut_face((5, 1, 0), (0, -2, 1)),
                      cut_face((5, 3, 0), (1, 0, 0))])
        data = read_data(feature("ChamferFeature", "Chamfer1", edgeSets=Coll([edge_set]), faces=faces))
        (record,) = data["sets"][0]["edges"]
        self.assertEqual(record["sides"], [[[0, 0, 1], [0, -1, 0]]])
        self.assertEqual(record["cut_normals"], [[0, -0.894427191, 0.447213595]])

    def test_an_even_set_measures_nothing(self):
        picked = edge("a", 5)
        picked.faces = Coll([normal_face((0, 0, 1)), normal_face((0, -1, 0))])
        edge_set = with_edges("EqualDistanceChamferEdgeSet", [picked], distance=param(0.1))
        data = read_data(feature("ChamferFeature", "Chamfer1", edgeSets=Coll([edge_set]),
                                 faces=Coll([cut_face((5, 1, 0), (0, -1, 1))])))
        self.assertFalse({"sides", "cut_normals"} & set(data["sets"][0]["edges"][0]))


def flat_face(point, normal):
    """A flat face through `point` (mm) whose outward normal is `normal`."""
    return Obj("fusion::BRepFace", pointOnFace=P(*point), geometry=Obj("core::Plane"),
               evaluator=Obj(getNormalAtPoint=lambda p: (True, Obj(x=normal[0], y=normal[1], z=normal[2]))))


def top_front_edge(faces):
    """The straight edge from (0, 0, 10) to (40, 0, 10) mm between `faces`; its parameter is its x (mm)."""
    evaluator = Obj(getParameterExtents=lambda: (True, 0.0, 40.0), getPointAtParameter=lambda t: (True, P(t, 0, 10)),
                    getTangent=lambda t: (True, Obj(x=2.0, y=0.0, z=0.0)))
    return Obj("fusion::BRepEdge", entityToken="e1", evaluator=evaluator, startVertex=Obj(entityToken="v1"),
               endVertex=Obj(entityToken="v2"), geometry=Obj("core::Line3D"), faces=Coll(faces))


def round_face(radius_at, largest_along=False):
    """A round face on which every point is its own nearest point; `radius_at(x)` (mm) is its radius across the
    edge. With `largest_along` the larger curvature runs along the edge (a tight bend), so the radius across is the
    smaller curvature."""
    def curvature(p):
        across = 1.0 / (radius_at(p.x / CM) * CM)
        if largest_along:
            return True, Obj(x=1.0, y=0.0, z=0.0), across * 4, across
        return True, Obj(x=0.0, y=0.6, z=0.8), across, 0.0
    evaluator = Obj(getParameterAtPoint=lambda p: (True, p), getPointAtParameter=lambda uv: (True, uv),
                    isParameterOnFace=lambda uv: True, getCurvature=curvature)
    return Obj("fusion::BRepFace", evaluator=evaluator)


class MeasuredRoundTest(unittest.TestCase):
    """Chord length and changing radius sets: samples along each edge before the step, the round's radius after."""

    def setUp(self):
        core = install_adsk_core()
        core.Point3D = type("Point3D", (), {"create": staticmethod(lambda x, y, z: Obj(x=x, y=y, z=z))})

    def test_a_chord_length_set_samples_the_faces_and_measures_the_round_across_the_edge(self):
        faces = [flat_face((20, 10, 10), (0, 0, 1)), flat_face((20, 0, 5), (0, -1, 0))]
        edge_set = with_edges("ChordLengthFilletEdgeSet", [top_front_edge(faces)],
                              chordLength=Obj(value=0.2, name="d5", expression="chord_mm"))
        data = read_data(feature("FilletFeature", "Fillet1", edgeSets=Coll([edge_set]),
                                 faces=Coll([round_face(lambda x: 1.5)])))
        (entry,) = data["sets"]
        self.assertEqual((entry["kind"], entry["chord_length"]), ("chordLength", 2.0))
        self.assertEqual(data["params"]["sets.0.chord_length"]["expression"], "chord_mm")
        (record,) = entry["edges"]
        self.assertEqual(record["curve"], "Line3D")
        self.assertEqual([(s["at"], s["point"]) for s in record["samples"]],
                         [(0.0, [0, 0, 10]), (0.25, [10, 0, 10]), (0.5, [20, 0, 10]), (0.75, [30, 0, 10]),
                          (1.0, [40, 0, 10])])
        self.assertEqual(record["samples"][0]["sides"], [[0, 0, 1], [0, -1, 0]])
        self.assertEqual(record["side_faces"][1], {"face_point": [20, 0, 5], "surface": "Plane", "normal": [0, -1, 0]})
        self.assertEqual({s["radius"] for s in record["samples"]}, {1.5})

    def test_a_cylinder_beside_a_chord_length_edge_gives_its_axis(self):
        cylinder = Obj("fusion::BRepFace", pointOnFace=P(20, 0, 5),
                       geometry=Obj("core::Cylinder", axis=Obj(x=0.0, y=0.0, z=2.0)),
                       evaluator=Obj(getNormalAtPoint=lambda p: (True, Obj(x=0, y=-1, z=0))))
        edge_set = with_edges("ChordLengthFilletEdgeSet", [top_front_edge([flat_face((20, 10, 10), (0, 0, 1)),
                                                                            cylinder])],
                              chordLength=Obj(value=0.2, name="d5", expression="chord_mm"))
        data = read_data(feature("FilletFeature", "Fillet1", edgeSets=Coll([edge_set]),
                                 faces=Coll([round_face(lambda x: 1.5)])))
        flat, curved = data["sets"][0]["edges"][0]["side_faces"]
        self.assertNotIn("axis", flat)
        self.assertEqual((curved["surface"], curved["axis"]), ("Cylinder", [0, 0, 1]))

    def test_a_changing_radius_set_reads_both_radii_its_mid_points_and_the_radius_along_the_edge(self):
        edge_set = with_edges("VariableRadiusFilletEdgeSet", [top_front_edge([])], startRadius=param(0.1),
                              endRadius=param(0.3), midPositions=Coll([]))
        data = read_data(feature("FilletFeature", "Fillet1", edgeSets=Coll([edge_set]),
                                 faces=Coll([round_face(lambda x: 1 + x / 20, largest_along=True)])))
        (entry,) = data["sets"]
        self.assertEqual((entry["start_radius"], entry["end_radius"], entry["mid_count"]), (1.0, 3.0, 0))
        (record,) = entry["edges"]
        self.assertNotIn("sides", record["samples"][0])
        self.assertEqual([s["radius"] for s in record["samples"]], [1.0, 1.5, 2.0, 2.5, 3.0])

    def test_unreadable_mid_points_and_a_sample_that_fails_read_as_null(self):
        broken = top_front_edge([])
        broken.evaluator.getTangent = lambda t: (False, None)
        edge_set = with_edges("VariableRadiusFilletEdgeSet", [broken], startRadius=param(0.1), endRadius=param(0.3))
        data = read_data(feature("FilletFeature", "Fillet1", edgeSets=Coll([edge_set])))
        (entry,) = data["sets"]
        self.assertIsNone(entry["mid_count"])
        self.assertNotIn("samples", entry["edges"][0])


class ShellTest(unittest.TestCase):
    # Fusion returns None (no exception) for the side of a shell that has no wall.
    def test_faces_chain_and_inward_wall(self):
        neighbour = face("f2", x=5)
        top = face("f1", x=4, chain=[neighbour])
        data = read_data(feature("ShellFeature", "Shell1", inputEntities=Coll([top, face("f2", x=5)]),
                                 isTangentChain=True, insideThickness=param(0.2), outsideThickness=None,
                                 shellType="SharpOffsetShellType"))
        self.assertEqual(data, {
            "faces": [{"token": "f1", "point": [4, 1, 2]}, {"token": "f2", "point": [5, 1, 2]}],
            "bodies_input": False, "inside": 2.0, "outside": 0.0, "shell_type": "sharp",
            "volume_before": 8000.0, "volume_after": 8000.0})

    def test_body_input_rounded_type_and_outward_wall(self):
        data = read_data(feature("ShellFeature", "Shell1", inputEntities=Coll([body()]),
                                 insideThickness=None, outsideThickness=param(0.1),
                                 shellType="RoundedOffsetShellType"))
        self.assertEqual((data["faces"], data["bodies_input"], data["inside"], data["outside"], data["shell_type"]),
                         ([], True, 0.0, 1.0, "rounded"))

    def test_a_wall_on_both_sides_reads_both(self):
        data = read_data(feature("ShellFeature", "Shell1", inputEntities=Coll([face("f1")]),
                                 insideThickness=param(0.1), outsideThickness=param(0.2)))
        self.assertEqual((data["inside"], data["outside"]), (1.0, 2.0))

    def test_a_shell_member_that_cannot_be_read_is_not_guessed(self):
        data = read_data(feature("ShellFeature", "Shell1", inputEntities=Coll([face("f1")]),
                                 outsideThickness=None))
        self.assertEqual((data["shell_type"], data["inside"], data["outside"], len(data["faces"])),
                         ("other", None, 0.0, 1))


class DraftTest(unittest.TestCase):
    def test_faces_plane_and_angles(self):
        wall = face("f1", x=40)
        wall.boundingBox = Obj(minPoint=P(40, 0, 0), maxPoint=P(40, 20, 10))
        floor = Obj("fusion::ConstructionPlane", entityToken="xy", geometry=plane_geometry((0, 0, 0), (0, 0, 1)))
        one = Obj("fusion::AngleExtentDefinition", angle=Obj(name="d7", expression="3 deg", value=0.0523598776),
                  isSymmetric=False)
        data = read_data(feature("DraftFeature", "Draft1", inputFaces=Coll([wall]), isTangentChain=False,
                                 plane=floor, isDirectionFlipped=True, draftDefinition=one))
        self.assertEqual(data["faces"], [{"token": "f1", "point": [40, 1, 2],
                                          "box": {"min": [40, 0, 0], "max": [40, 20, 10]}}])
        self.assertEqual((data["plane"]["point"], data["plane"]["normal"]), ([0, 0, 0], [0, 0, 1]))
        self.assertEqual((data["angle_deg"], data["two_angles"], data["flipped"]), (3.0, False, True))
        self.assertEqual(data["params"]["angle_deg"]["expression"], "3 deg")
        two = Obj("fusion::TwoSidesAngleExtentDefinition", angleOne=param(0.05), angleTwo=param(0.1))
        data = read_data(feature("DraftFeature", "Draft1", inputFaces=Coll([wall]), plane=floor,
                                 draftDefinition=two))
        self.assertEqual((data["two_angles"], round(data["angle_two_deg"], 3)), (True, 5.73))


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


def source_feature(index, **kw):
    """A one-sided extrude cut, an input whose pattern elements may have their faces read."""
    kw.setdefault("extentType", "OneSideFeatureExtentType")
    kw.setdefault("operation", "CutFeatureOperation")
    return Obj("fusion::ExtrudeFeature", timelineObject=Obj(index=index), **kw)


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


class Unreadable:
    """A flag Fusion cannot answer."""

    def __bool__(self):
        raise RuntimeError("no answer")


class RectangularPatternTest(unittest.TestCase):
    def test_symmetric_flags_are_read_and_a_flag_that_fails_reads_as_not_symmetric(self):
        elements = [element(i + 1, (10 * (i - 1), 0, 0)) for i in range(3)]
        both = read_pattern("RectangularPatternFeature", elements, isSymmetricInDirectionOne=True,
                            isSymmetricInDirectionTwo=True, **rectangular())
        self.assertEqual((both["symmetric_one"], both["symmetric_two"]), (True, True))
        failing = read_pattern("RectangularPatternFeature", elements, isSymmetricInDirectionOne=Unreadable(),
                               **rectangular())
        self.assertEqual((failing["symmetric_one"], failing["symmetric_two"]), (False, False))
        self.assertEqual(len(failing["elements"]), 3)

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

    def test_unreadable_elements_are_a_read_error(self):
        target = body()
        pattern = feature("RectangularPatternFeature", "Pattern1", **rectangular())
        design = FakeDesign([sketch_entry(), entry(pattern)], target)
        item = read_capture(design, target, fusion="", name="", up_axis="z")["items"][1]
        self.assertIn("read_error", item["data"])


class CircularPatternTest(unittest.TestCase):
    def test_the_symmetric_flag_is_read_and_a_flag_that_fails_reads_as_not_symmetric(self):
        axis = Obj("fusion::ConstructionAxis", geometry=Obj(origin=P(5, 5, 0), direction=Obj(x=0.0, y=0.0, z=1.0)))
        common = dict(inputEntities=Coll([source_feature(1)]), patternEntityType="FeaturesPatternEntityType", axis=axis,
                      quantity=param(3.0), totalAngle=param(1.5707963267948966))
        for flag, expected in ((True, True), (Unreadable(), False)):
            data = read_pattern("CircularPatternFeature", [element(1, (0, 0, 0))], isSymmetric=flag, **common)
            self.assertEqual(data["symmetric"], expected)

    def test_full_turn_with_turned_elements(self):
        turned = element(2, (0, 0, 0), x=(0, 1, 0), y=(-1, 0, 0))
        data = read_pattern(
            "CircularPatternFeature", [element(1, (0, 0, 0)), turned],
            inputEntities=Coll([source_feature(1)]), patternEntityType="FeaturesPatternEntityType",
            axis=Obj("fusion::ConstructionAxis", geometry=Obj(origin=P(5, 5, 0),
                                                              direction=Obj(x=0.0, y=0.0, z=1.0))),
            quantity=param(6.0), totalAngle=param(2 * 3.141592653589793), isSymmetric=False,
            suppressedElementsIds=[4, 5])
        self.assertEqual(data["axis"], {"point": [5, 5, 0], "dir": [0.0, 0.0, 1.0], "entity_type": "ConstructionAxis"})
        self.assertEqual((data["quantity"], data["total_angle_deg"], data["symmetric"]), (6, 360.0, False))
        self.assertEqual(data["suppressed_ids"], [4, 5])
        self.assertEqual(data["elements"][1]["frame"]["x"], [0.0, 1.0, 0.0])
        self.assertEqual(data["sources"], [1])

    def test_an_edge_axis_says_where_the_edge_is(self):
        line = edge("e1", 5)
        line.geometry = Obj("core::Line3D", startPoint=P(0, 0, 0), endPoint=P(10, 0, 0))
        data = read_pattern("CircularPatternFeature", [element(1, (0, 0, 0))], inputEntities=Coll([source_feature(1)]),
                            patternEntityType="FeaturesPatternEntityType", axis=line, quantity=param(3.0),
                            totalAngle=param(2 * 3.141592653589793))
        self.assertEqual(data["axis"], {"point": [0, 0, 0], "dir": [1.0, 0.0, 0.0], "entity_type": "BRepEdge",
                                        "edge_points": [[5, 0, 0]]})

    def test_a_construction_axis_says_what_its_definition_is_built_on(self):
        straight = edge("e1", 5)
        straight.geometry = Obj("core::Line3D", startPoint=P(0, 0, 0), endPoint=P(10, 0, 0))
        corner = Obj("fusion::BRepVertex", entityToken="v1")
        other = Obj("fusion::BRepFace", entityToken="f8", parentComponent=Obj(entityToken="lid", name="Lid"))
        cases = (("ConstructionAxisEdgeDefinition", {"edgeEntity": straight}, ["BRepEdge"]),
                 ("ConstructionAxisTwoPointDefinition", {"pointEntityOne": corner, "pointEntityTwo": corner},
                  ["BRepVertex", "BRepVertex"]),
                 ("ConstructionAxisNormalToFaceAtPointDefinition", {"face": other, "pointEntity": corner},
                  [None, "BRepVertex"]))
        for name, members, kinds in cases:
            with self.subTest(name):
                axis = Obj("fusion::ConstructionAxis", entityToken="ax1", definition=Obj("fusion::" + name, **members),
                           geometry=Obj(origin=P(5, 5, 0), direction=Obj(x=0.0, y=0.0, z=1.0)))
                data = read_pattern("CircularPatternFeature", [element(1, (0, 0, 0))],
                                    inputEntities=Coll([source_feature(1)]), axis=axis, quantity=param(3.0),
                                    totalAngle=param(2 * 3.141592653589793))
                built = data["axis"]["built_on"]
                self.assertEqual([entry.get("entity_type") for entry in built], kinds)
                # An entity of another component is no place of the part, and not left out either.
                self.assertEqual([entry for entry in built if "entity_type" not in entry],
                                 [{"foreign": True, "component": {"token": "lid", "name": "Lid"}}] * kinds.count(None))

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
                                "plane": {"point": [0, 0, 0], "normal": [1.0, 0.0, 0.0],
                                          "entity_type": "ConstructionPlane"}, "combine": False,
                                "target_box_before": {"min": [0, 0, 0], "max": [40, 20, 10]}})

    def test_body_mirror_about_a_planar_face_with_combine(self):
        planar = face("f9", geometry=plane_geometry((0, 0, 10), (0, 0, 1)))
        data = read_data(feature("MirrorFeature", "Mirror1", inputEntities=Coll([body()]),
                                 patternEntityType="BodiesPatternEntityType", isCombine=True, mirrorPlane=planar))
        self.assertEqual((data["entity_type"], data["sources"], data["combine"]), ("bodies", [], True))
        self.assertEqual(data["plane"], {"point": [0, 0, 10], "normal": [0.0, 0.0, 1.0], "entity_type": "BRepFace",
                                         "face_point": [0, 1, 2], "surface": "Plane"})
        self.assertEqual(data["target_box_before"], {"min": [0, 0, 0], "max": [40, 20, 10]})

    def test_a_construction_plane_says_what_it_is_built_on(self):
        base = face("f1", geometry=plane_geometry((0, 0, 10), (0, 0, 1)))
        built = Obj("fusion::ConstructionPlane", entityToken="cp1", geometry=plane_geometry((0, 0, 15), (0, 0, 1)),
                    timelineObject=Obj(index=2),
                    definition=Obj("fusion::ConstructionPlaneOffsetDefinition", planarEntity=base))
        data = read_data(feature("MirrorFeature", "Mirror1", inputEntities=Coll([source_feature(1)]),
                                 patternEntityType="FeaturesPatternEntityType", mirrorPlane=built))
        plane = data["plane"]
        self.assertEqual((plane["token"], plane["made_by"], plane["definition"]),
                         ("cp1", 2, "ConstructionPlaneOffsetDefinition"))
        self.assertEqual(plane["built_on"], [{"entity_type": "BRepFace", "face_point": [0, 1, 2], "surface": "Plane"}])

    def test_a_construction_plane_through_points_edges_or_a_path_says_what_it_is_built_on(self):
        corner = Obj("fusion::BRepVertex", entityToken="v1")
        straight = edge("e1", 5)
        cases = (("ConstructionPlaneThreePointsDefinition",
                  {"pointEntityOne": corner, "pointEntityTwo": corner, "pointEntityThree": corner}, ["BRepVertex"] * 3),
                 ("ConstructionPlaneTwoEdgesDefinition", {"linearEntityOne": straight, "linearEntityTwo": straight},
                  ["BRepEdge"] * 2),
                 ("ConstructionPlaneDistanceOnPathDefinition", {"pathEntity": straight}, ["BRepEdge"]),
                 ("ConstructionPlaneTangentAtPointDefinition", {"tangentFace": face("f1"), "pointEntity": corner},
                  ["BRepFace", "BRepVertex"]))
        for name, members, kinds in cases:
            with self.subTest(name):
                built = Obj("fusion::ConstructionPlane", entityToken="cp1", definition=Obj("fusion::" + name, **members),
                            geometry=plane_geometry((0, 0, 15), (0, 0, 1)))
                data = read_data(feature("MirrorFeature", "Mirror1", inputEntities=Coll([source_feature(1)]),
                                         patternEntityType="FeaturesPatternEntityType", mirrorPlane=built))
                self.assertEqual(sorted(entry["entity_type"] for entry in data["plane"]["built_on"]), sorted(kinds))

    def test_an_origin_plane_says_only_that_it_is_one(self):
        origin = Obj("fusion::ConstructionPlane", entityToken="xy", geometry=plane_geometry((0, 0, 0), (0, 0, 1)))
        target = body()
        design = FakeDesign([sketch_entry(), entry(feature(
            "MirrorFeature", "Mirror1", inputEntities=Coll([source_feature(1)]),
            patternEntityType="FeaturesPatternEntityType", mirrorPlane=origin))], target)
        design.rootComponent.xYConstructionPlane = origin
        data = read_capture(design, target, fusion="", name="", up_axis="z")["items"][1]["data"]
        self.assertEqual(data["plane"], {"point": [0, 0, 0], "normal": [0.0, 0.0, 1.0], "token": "xy", "origin": True})

    def test_curved_mirror_plane_is_null(self):
        curved = face("f9", geometry=Obj("core::Cylinder"))
        data = read_data(feature("MirrorFeature", "Mirror1", inputEntities=Coll([source_feature(1)]),
                                 patternEntityType="FeaturesPatternEntityType", mirrorPlane=curved))
        self.assertIsNone(data["plane"])


if __name__ == "__main__":
    unittest.main()
