"""The sketch graph reader: entities, each dimension type, each constraint type, members that cannot be read."""
import unittest
from types import SimpleNamespace

from tests import context  # noqa: F401
from tests.sketch_graph_fakes import (Param, Thing, arc, broken, circle, constraint, dimension, line, point, sketch)

from lib.fusion_reader.read_constraints import read_sketch_graph

PART = Thing(key="part", entityToken="cmp_part", name="Part")
CTX = SimpleNamespace(component=PART)
FACE = Thing("BRepFace", "face")
PLANE = Thing("ConstructionPlane", "plane")


class Scene:
    """Points a0 a1 b0 b1 and c0 c1 (centres), lines a (a0 a1) and b (b0 b1), circles ca and cb, arc ar."""

    def __init__(self):
        self.p = {k: point(k, i, 2 * i) for i, k in enumerate(("a0", "a1", "b0", "b1", "c0", "c1"))}
        self.a, self.b = line("a", self.p["a0"], self.p["a1"]), line("b", self.p["b0"], self.p["b1"])
        self.ca, self.cb = circle("ca", self.p["c0"], 5.0), circle("cb", self.p["c1"], 8.0)
        self.ar = arc("ar", self.p["c0"], self.p["a0"], self.p["a1"], 3.0)
        self.things = {"a": self.a, "b": self.b, "ca": self.ca, "cb": self.cb, "ar": self.ar, "face": FACE,
                       "plane": PLANE, **self.p}

    def read(self, dimensions=(), constraints=()):
        sk = sketch(list(self.p.values()), [self.a, self.b, self.ca, self.cb, self.ar], dimensions, constraints)
        graph = read_sketch_graph(sk, CTX)
        self.refs = {key: _ref(graph, thing) for key, thing in self.things.items()}
        return graph


def _ref(graph, thing):
    token = thing.entityToken
    for kind, table in (("point", graph["points"]), ("curve", graph["curves"])):
        for record in table:
            if record["token"] == token:
                if kind == "point":
                    return ["point", record["id"]]
                return [record["kind"] if record["kind"] in ("line", "arc", "circle") else "curve", record["id"]]
    return ["surface", "BRepFace"] if thing is FACE else ["surface", "ConstructionPlane"]


def member(thing):
    """The entity as another wrapper with another token, the way a dimension or constraint hands it out."""
    return thing.wrapper(retoken=True)


class EntitiesTest(unittest.TestCase):
    def test_points_and_curves_get_ids_values_in_mm_and_flags(self):
        s = Scene()
        s.p["a1"] = point("a1", 12.5, -3, isFixed=True, isFullyConstrained=False)
        s.a = line("a", s.p["a0"], s.p["a1"], isConstruction=True)
        graph = s.read()
        a1 = next(r for r in graph["points"] if r["token"] == "tok_a1")
        self.assertEqual((a1["xy"], a1["fixed"], a1["free"], a1["reference"]), ([12.5, -3.0], True, True, None))
        record = next(r for r in graph["curves"] if r["token"] == "tok_a")
        self.assertEqual((record["kind"], record["construction"]), ("line", True))
        self.assertEqual(record["points"], [s.refs["a0"][1], s.refs["a1"][1]])

    def test_arc_and_circle_name_their_centre_and_radius_in_mm(self):
        s = Scene()
        graph = s.read()
        by_token = {r["token"]: r for r in graph["curves"]}
        self.assertEqual((by_token["tok_ca"]["kind"], by_token["tok_ca"]["radius"], by_token["tok_ca"]["center"]),
                         ("circle", 5.0, s.refs["c0"][1]))
        arc_record = by_token["tok_ar"]
        self.assertEqual((arc_record["radius"], arc_record["center"], arc_record["points"]),
                         (3.0, s.refs["c0"][1], [s.refs["a0"][1], s.refs["a1"][1]]))

    def test_the_origin_is_marked_whether_or_not_the_point_list_holds_it(self):
        origin = point("origin", 0, 0, isFixed=True)
        implicit = read_sketch_graph(sketch([point("p", 1, 1)], origin=origin), CTX)
        listed = read_sketch_graph(sketch([origin, point("p", 1, 1)], origin=origin), CTX)
        self.assertEqual([(p["origin"], p.get("implicit", False)) for p in implicit["points"]],
                         [(False, False), (True, True)])
        self.assertEqual(implicit["origin"], 1)
        self.assertEqual([(p["origin"], p.get("implicit", False)) for p in listed["points"]],
                         [(True, False), (False, False)])
        self.assertEqual(listed["origin"], 0)

    def test_a_reference_says_where_it_comes_from(self):
        other = Thing(key="pipe", entityToken="cmp_pipe", name="Pipe")
        body = Thing("BRepBody", "pb", body=None, assemblyContext=Thing(key="occ", component=other))
        edge = Thing("BRepEdge", "e1", assemblyContext=Thing(key="occ", component=other), body=body)
        own_edge = Thing("BRepEdge", "e2", parentComponent=PART)
        sk = sketch(curves=[
            circle("c_other", point("c1", 0, 0), 4.0, isReference=True, referencedEntity=edge),
            circle("c_own", point("c2", 0, 0), 4.0, isReference=True, referencedEntity=own_edge),
            circle("c_none", point("c3", 0, 0), 4.0, isReference=True, referencedEntity=None),
            circle("c_plain", point("c4", 0, 0), 4.0)])
        graph = read_sketch_graph(sk, CTX)
        refs = {r["token"]: r["reference"] for r in graph["curves"]}
        self.assertEqual(refs["tok_c_other"], {"source": "other", "component": "cmp_pipe", "token": "tok_e1"})
        self.assertEqual(refs["tok_c_own"], {"source": "own", "component": "cmp_part", "token": "tok_e2"})
        self.assertEqual(refs["tok_c_none"], {"source": "none", "component": "", "token": ""})
        self.assertIsNone(refs["tok_c_plain"])

    def test_an_unknown_curve_type_is_kept_as_other_with_its_name(self):
        odd = Thing("SketchNurbsFuture", "n", isConstruction=False, isFixed=False, isFullyConstrained=True,
                    isReference=False, isLinked=False)
        graph = read_sketch_graph(sketch(curves=[odd]), CTX)
        self.assertEqual((graph["curves"][0]["kind"], graph["curves"][0]["name"]), ("other", "SketchNurbsFuture"))

    def test_entity_members_that_raise_are_listed_unread_and_the_rest_is_read(self):
        s = Scene()
        s.p["a1"] = broken(point("a1", 4, 8), "geometry", "isFixed")
        graph = s.read()
        record = next(r for r in graph["points"] if r["token"] == "tok_a1")
        self.assertEqual((record["xy"], record["fixed"], sorted(record["unread"])), (None, None, ["geometry", "isFixed"]))
        self.assertEqual(record["free"], False)


class DimensionsTest(unittest.TestCase):
    def check(self, dim, **expected):
        s = Scene()
        graph = s.read(dimensions=[dim(s)])
        [record] = graph["dimensions"]
        for key, value in expected.items():
            self.assertEqual(record[key], value(s) if callable(value) else value, key)
        return record

    def test_linear_dimension_keeps_orientation_and_both_entities(self):
        for number, name in ((0, "aligned"), (1, "horizontal"), (2, "vertical")):
            self.check(lambda s: dimension("SketchLinearDimension", "d", 25.0, Param("d7", "Wall * 2", ["Wall"]),
                                           entityOne=member(s.p["a0"]), entityTwo=member(s.a), orientation=number),
                       type="linear", orientation=name, on=lambda s: [s.refs["a0"], s.refs["a"]], value=25.0,
                       param="d7", expression="Wall * 2", reads=["Wall"], driving=True, text=[1.0, 2.0])

    def test_offset_dimension_measures_a_line_and_a_parallel_line_or_point(self):
        self.check(lambda s: dimension("SketchOffsetDimension", "d", 7.0, line=member(s.a), entityTwo=member(s.b)),
                   type="offset", on=lambda s: [s.refs["a"], s.refs["b"]], value=7.0)

    def test_angular_dimension_value_is_in_degrees(self):
        self.check(lambda s: dimension("SketchAngularDimension", "d", 30.0, lineOne=member(s.a), lineTwo=member(s.b)),
                   type="angular", on=lambda s: [s.refs["a"], s.refs["b"]], value=30.0)

    def test_diameter_and_radial_dimensions_name_their_circle(self):
        for cls, kind in (("SketchDiameterDimension", "diameter"), ("SketchRadialDimension", "radial")):
            self.check(lambda s: dimension(cls, "d", 10.0, entity=member(s.ca)),
                       type=kind, on=lambda s: [s.refs["ca"]], value=10.0)

    def test_concentric_circle_dimension_names_both_circles(self):
        self.check(lambda s: dimension("SketchConcentricCircleDimension", "d", 4.0, circleOne=member(s.ca),
                                       circleTwo=member(s.cb)),
                   type="concentric_circles", on=lambda s: [s.refs["ca"], s.refs["cb"]], value=4.0)

    def test_linear_diameter_and_tangent_distance_dimensions(self):
        self.check(lambda s: dimension("SketchLinearDiameterDimension", "d", 9.0, line=member(s.a),
                                       entityTwo=member(s.b)),
                   type="linear_diameter", on=lambda s: [s.refs["a"], s.refs["b"]])
        self.check(lambda s: dimension("SketchTangentDistanceDimension", "d", 9.0, entityOne=member(s.a),
                                       circleOrArc=member(s.ca)),
                   type="tangent_distance", on=lambda s: [s.refs["a"], s.refs["ca"]])

    def test_ellipse_radius_dimensions_name_the_ellipse(self):
        for cls, kind in (("SketchEllipseMajorRadiusDimension", "ellipse_major_radius"),
                          ("SketchEllipseMinorRadiusDimension", "ellipse_minor_radius")):
            self.check(lambda s: dimension(cls, "d", 6.0, ellipse=member(s.ca)),
                       type=kind, on=lambda s: [s.refs["ca"]], value=6.0)

    def test_surface_dimensions_name_the_face_or_plane_without_an_id(self):
        self.check(lambda s: dimension("SketchDistanceBetweenPointAndSurfaceDimension", "d", 2.0,
                                       point=member(s.p["a0"]), surface=member(FACE)),
                   type="point_surface", on=lambda s: [s.refs["a0"], ["surface", "BRepFace"]])
        self.check(lambda s: dimension("SketchDistanceBetweenLineAndPlanarSurfaceDimension", "d", 2.0,
                                       line=member(s.a), planarSurface=member(PLANE)),
                   type="line_surface", on=lambda s: [s.refs["a"], ["surface", "ConstructionPlane"]])

    def test_offset_curves_dimension_and_its_constraint_point_at_each_other(self):
        s = Scene()
        offset = constraint("OffsetConstraint", "off", parentCurves=[member(s.a)], childCurves=[member(s.b)],
                            distance=0.5, isTopologyMatched=True, dimension=None)
        dim = dimension("SketchOffsetCurvesDimension", "od", 5.0, offsetConstraint=offset)
        offset.dimension = dim
        graph = s.read(dimensions=[dim], constraints=[offset])
        [d], [c] = graph["dimensions"], graph["constraints"]
        self.assertEqual((d["type"], d["on"], d["offset_constraint"], d["value"]), ("offset_curves", [], 0, 5.0))
        self.assertEqual((c["type"], c["dimension"], c["distance"], c["parents"], c["children"]),
                         ("offset", 0, 5.0, [s.refs["a"]], [s.refs["b"]]))
        self.assertNotIn("_offset", d)
        self.assertNotIn("_dimension", c)

    def test_a_driven_dimension_says_so(self):
        self.check(lambda s: dimension("SketchDiameterDimension", "d", 10.0, driving=False, entity=member(s.ca)),
                   driving=False)

    def test_a_dimension_without_a_parameter_has_no_name(self):
        self.check(lambda s: dimension("SketchDiameterDimension", "d", 10.0, entity=member(s.ca)),
                   param=None, expression=None, reads=[])

    def test_an_unknown_dimension_type_is_kept_with_its_name_and_entities(self):
        s = Scene()
        graph = s.read(dimensions=[dimension("SketchFutureDimension", "d", 3.0, entityOne=member(s.a),
                                             circleOne=member(s.ca))])
        [record] = graph["dimensions"]
        self.assertEqual((record["type"], record["unknown"], record["name"], record["value"]),
                         ("other", True, "adsk::fusion::SketchFutureDimension", None))
        self.assertEqual(record["on"], [s.refs["a"], s.refs["ca"]])

    def test_members_that_raise_are_listed_and_leave_a_null_place(self):
        s = Scene()
        dim = broken(dimension("SketchLinearDimension", "d", 5.0, entityOne=member(s.a), entityTwo=member(s.b),
                               orientation=1), "entityTwo", "value", "isDriving")
        [record] = s.read(dimensions=[dim])["dimensions"]
        self.assertEqual(record["on"], [s.refs["a"], None])
        self.assertEqual((record["value"], record["driving"]), (None, None))
        self.assertEqual(sorted(record["unread"]), ["entityTwo", "isDriving", "value"])
        self.assertEqual(record["orientation"], "horizontal")

    def test_an_unreadable_dimension_object_becomes_an_unknown_record(self):
        s = Scene()
        graph = s.read(dimensions=[Thing("SketchLinearDimension", "d")])  # no members at all
        [record] = graph["dimensions"]
        self.assertTrue(set(record["unread"]) >= {"entityOne", "entityTwo", "value", "isDriving"})
        self.assertEqual(record["on"], [None, None])


class ConstraintsTest(unittest.TestCase):
    def check(self, type_name, kind, members, expected_on):
        s = Scene()
        made = {name: member(s.things[key]) for name, key in members.items()}
        [record] = s.read(constraints=[constraint(type_name, "c", **made)])["constraints"]
        self.assertEqual((record["type"], record["on"]), (kind, [s.refs[k] for k in expected_on]), type_name)
        self.assertNotIn("unknown", record)

    def test_each_single_entity_constraint(self):
        self.check("HorizontalConstraint", "horizontal", {"line": "a"}, ["a"])
        self.check("VerticalConstraint", "vertical", {"line": "b"}, ["b"])

    def test_each_two_entity_constraint_keeps_the_member_order(self):
        pairs = (("CoincidentConstraint", "coincident", ("point", "entity"), ("a0", "a")),
                 ("HorizontalPointsConstraint", "horizontal_points", ("pointOne", "pointTwo"), ("a0", "b1")),
                 ("VerticalPointsConstraint", "vertical_points", ("pointOne", "pointTwo"), ("a0", "b1")),
                 ("ParallelConstraint", "parallel", ("lineOne", "lineTwo"), ("a", "b")),
                 ("CollinearConstraint", "collinear", ("lineOne", "lineTwo"), ("b", "a")),
                 ("PerpendicularConstraint", "perpendicular", ("line", "curve"), ("a", "b")),
                 ("EqualConstraint", "equal", ("curveOne", "curveTwo"), ("ca", "cb")),
                 ("TangentConstraint", "tangent", ("curveOne", "curveTwo"), ("a", "ar")),
                 ("SmoothConstraint", "smooth", ("curveOne", "curveTwo"), ("ar", "a")),
                 ("ConcentricConstraint", "concentric", ("entityOne", "entityTwo"), ("ca", "cb")),
                 ("MidPointConstraint", "midpoint", ("point", "midPointCurve"), ("c0", "a")),
                 ("CoincidentToSurfaceConstraint", "coincident_surface", ("point", "surface"), ("a0", "face")),
                 ("LineOnPlanarSurfaceConstraint", "line_on_surface", ("line", "planarSurface"), ("a", "plane")))
        for type_name, kind, names, keys in pairs:
            with self.subTest(type_name):
                s = Scene()
                made = {n: member(s.things[k]) for n, k in zip(names, keys)}
                [record] = s.read(constraints=[constraint(type_name, "c", **made)])["constraints"]
                expected = [["surface", "BRepFace"] if k == "face" else ["surface", "ConstructionPlane"]
                            if k == "plane" else s.refs[k] for k in keys]
                self.assertEqual((record["type"], record["on"]), (kind, expected))

    def test_perpendicular_falls_back_to_the_retired_member_names(self):
        s = Scene()
        old = constraint("PerpendicularConstraint", "c", lineOne=member(s.a), lineTwo=member(s.b))
        [record] = s.read(constraints=[old])["constraints"]
        self.assertEqual((record["on"], record.get("unread")), ([s.refs["a"], s.refs["b"]], None))

    def test_symmetry_names_both_entities_and_the_axis(self):
        self.check("SymmetryConstraint", "symmetry", {"entityOne": "a0", "entityTwo": "a1", "symmetryLine": "b"},
                   ["a0", "a1", "b"])

    def test_polygon_and_patterns_list_every_entity_and_skip_a_missing_direction(self):
        s = Scene()
        polygon = constraint("PolygonConstraint", "p", centerPoint=member(s.p["c0"]),
                             points=[member(s.p["a0"]), member(s.p["a1"])])
        pattern = constraint("RectangularPatternConstraint", "r", entities=[member(s.a)], createdEntities=[member(s.b)],
                             directionOneEntity=member(s.a), directionTwoEntity=None, isSuppressed=True)
        circular = constraint("CircularPatternConstraint", "o", entities=[member(s.ca)], createdEntities=[],
                              centerPoint=member(s.p["c1"]), isSuppressed=False)
        poly, rect, circ = s.read(constraints=[polygon, pattern, circular])["constraints"]
        self.assertEqual((poly["type"], poly["on"]), ("polygon", [s.refs["c0"], s.refs["a0"], s.refs["a1"]]))
        self.assertEqual((rect["type"], rect["on"], rect["suppressed"]),
                         ("rectangular_pattern", [s.refs["a"], s.refs["b"], s.refs["a"]], True))
        self.assertEqual((circ["type"], circ["on"], circ["suppressed"]),
                         ("circular_pattern", [s.refs["ca"], s.refs["c1"]], False))

    def test_an_unknown_constraint_type_keeps_its_name_and_every_entity_it_names(self):
        s = Scene()
        future = constraint("FutureConstraint", "c", entityOne=member(s.a), curveTwo=member(s.cb),
                            points=[member(s.p["a0"])])
        [record] = s.read(constraints=[future])["constraints"]
        self.assertEqual((record["type"], record["unknown"], record["name"]),
                         ("other", True, "adsk::fusion::FutureConstraint"))
        self.assertEqual(record["on"], [s.refs["a"], s.refs["cb"], s.refs["a0"]])

    def test_surface_constraints_the_reader_has_not_checked_stay_unknown(self):
        s = Scene()
        for name in ("LineParallelToPlanarSurfaceConstraint", "PerpendicularToSurfaceConstraint"):
            [record] = s.read(constraints=[constraint(name, "c", line=member(s.a))])["constraints"]
            self.assertEqual((record["type"], record["unknown"]), ("other", True))

    def test_a_member_that_raises_leaves_a_null_place_and_is_listed(self):
        s = Scene()
        c = broken(constraint("CoincidentConstraint", "c", point=member(s.p["a0"]), entity=member(s.a)), "entity")
        [record] = s.read(constraints=[c])["constraints"]
        self.assertEqual((record["on"], record["unread"]), ([s.refs["a0"], None], ["entity"]))

    def test_a_listed_entity_that_the_sketch_lists_not_is_added_as_implicit(self):
        s = Scene()
        axis = line("axis", point("ax0", -5, 0), point("ax1", 5, 0), isFixed=True)
        graph = s.read(constraints=[constraint("CoincidentConstraint", "c", point=member(s.p["a0"]),
                                               entity=member(axis))])
        [record] = graph["constraints"]
        added = next(r for r in graph["curves"] if r.get("implicit"))
        self.assertEqual((record["on"][1], added["implicit"], added["fixed"]), (["line", added["id"]], True, True))


if __name__ == "__main__":
    unittest.main()
