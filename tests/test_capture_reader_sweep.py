"""Reader of sweep and loft features: outlines, path curves, section kinds, end conditions and made end faces."""
import math
import unittest

from tests import context  # noqa: F401
from tests.test_capture_reader import Coll, FakeDesign, Obj, P, body, entry, matrix, rect_profile

from lib.fusion_reader.capture import read_capture
from lib.translator.gap_picks import pick_records

ROOT = Obj(entityToken="root")
OTHER = Obj(entityToken="other")
# Sketch space (x, y, z) lands at the point (10, y, x) in the component: a sketch plane standing on the x axis.
STANDING = matrix(origin=(10, 0, 0), x=(0, 1, 0), y=(0, 0, 1), z=(1, 0, 0))


def sketch(name="Path1", token="sk_path", transform=None, component=ROOT):
    return Obj("fusion::Sketch", name=name, entityToken=token, transform=transform or STANDING,
               parentComponent=component)


def curve3(kind, trace, **members):
    """A curve whose evaluator follows `trace(t) -> (x, y, z)` in mm, t from 0 to 1."""
    evaluator = Obj(getParameterExtents=lambda: (True, 0.0, 1.0), getPointAtParameter=lambda t: (True, P(*trace(t))))
    return Obj("core::" + kind, evaluator=evaluator, **members)


def line3(a, b):
    return curve3("Line3D", lambda t: tuple(a[i] + (b[i] - a[i]) * t for i in range(3)), startPoint=P(*a),
                  endPoint=P(*b))


def quarter_arc(radius=20.0):
    def trace(t):
        return radius * math.cos(t * math.pi / 2), radius * math.sin(t * math.pi / 2), 0.0
    return curve3("Arc3D", trace, startPoint=P(radius, 0, 0), endPoint=P(0, radius, 0), center=P(0, 0, 0),
                  normal=Obj(x=0, y=0, z=1), radius=radius / 10.0)


def sketch_curve(geometry, parent, token="c1", kind="SketchLine"):
    return Obj("fusion::" + kind, geometry=geometry, parentSketch=parent, entityToken=token)


def edge(token="e1", component=ROOT, a=(0, 0, 0), b=(30, 0, 0)):
    return Obj("fusion::BRepEdge", entityToken=token, geometry=line3(a, b), evaluator=line3(a, b).evaluator,
               body=Obj(entityToken="eb", parentComponent=component))


def step(entity, opposed=False, check=None):
    return Obj("fusion::PathEntity", entity=entity, isOpposedToEntity=opposed, curve=check)


def path(*steps, closed=False):
    return Obj("fusion::Path", isClosed=closed, count=len(steps), item=lambda i: steps[i])


def parameter(value, name, expression):
    return Obj(value=value, name=name, expression=expression)


def read(made, name, members, kind=Obj):
    """The data of one feature of type `made` built from `members` (as `kind`, to give it a member that throws)."""
    target = body()
    stub = kind("fusion::" + made, parentComponent=ROOT, bodies=Coll([target]), **members)
    design = FakeDesign([entry((stub, name))], target, appears_at=0)
    return read_capture(design, target, fusion="", name="", up_axis="z")["items"][0]["data"]


def read_sweep(kind=Obj, **members):
    base = dict(profile=profile(), path=path(step(sketch_curve(line3((0, 0, 0), (0, 50, 0)), sketch()))),
                guideRail=None, operation="JoinFeatureOperation", isSolid=True,
                orientation="PerpendicularOrientationType", distanceOne=parameter(1.0, "d1", "1"),
                distanceTwo=parameter(0.0, "d2", "0"), taperAngle=parameter(0.0, "d3", "0 deg"),
                twistAngle=parameter(math.radians(90), "d4", "90 deg"),
                profileScaling="SweepProfileScaleOption", extent="PerpendicularExtent",
                participantBodies=Coll([body()]),
                startFaces=Coll([face(0)]), endFaces=Coll([face(50)]))
    base.update(members)
    return read("SweepFeature", "Sweep1", base, kind)


def read_loft(kind=Obj, **members):
    base = dict(loftSections=Coll([]), centerLineOrRails=None, isClosed=False, isTangentEdgesMerged=True,
                isSolid=True, operation="NewBodyFeatureOperation", participantBodies=Coll([body()]),
                startFace=face(0), endFace=face(30))
    base.update(members)
    return read("LoftFeature", "Loft1", base, kind)


def profile(width=40, area=4.0):
    found = rect_profile(width, 20)
    found.areaProperties = lambda: Obj(area=area)
    return found


def face(z, geometry="Plane"):
    normal = Obj(x=0, y=0, z=1)
    return Obj("fusion::BRepFace", entityToken="f%s" % z, geometry=Obj("core::" + geometry), pointOnFace=P(5, 5, z),
               evaluator=Obj(getNormalAtPoint=lambda p: (True, normal)))


class RailBroken(Obj):
    @property
    def guideRail(self):
        raise RuntimeError("not available")


class Broken(Obj):
    @property
    def distanceTwo(self):
        raise RuntimeError("not available")


class NoTwist(Obj):
    @property
    def twistAngle(self):
        raise RuntimeError("3 : the twist is not available")


class SweepSettingsTest(unittest.TestCase):
    def test_a_setting_fusion_does_not_give_keeps_what_fusion_said(self):
        data = read_sweep(NoTwist)
        self.assertEqual(data["unread"], {"twist_deg": "3 : the twist is not available"})
        self.assertNotIn("unread", read_sweep())

    def test_the_settings_and_the_outline_are_read(self):
        data = read_sweep()
        self.assertEqual((data["operation"], data["solid"], data["orientation"], data["scaling"]),
                         ("join", True, "perpendicular", "scale"))
        self.assertEqual((data["distance_one"], data["distance_two"], data["taper_deg"], data["twist_deg"]),
                         (1.0, 0.0, 0.0, 90.0))
        self.assertEqual((data["extent"], data["areas"], data["rail"]), ("PerpendicularExtent", [400.0], None))
        self.assertEqual(data["profiles"][0]["sketch"], "Sketch1")
        self.assertEqual(data["participants"], [{"token": "b1", "name": "Body1"}])
        self.assertEqual(data["params"]["twist_deg"], {"name": "d4", "expression": "90 deg", "value": 90.0})
        self.assertEqual(data["params"]["distance_one"]["value"], 1.0)

    def test_a_point_and_a_normal_on_each_made_end_face(self):
        faces = read_sweep()["faces_after"]
        self.assertEqual(faces["start"], [{"point": [5, 5, 0], "normal": [0, 0, 1]}])
        self.assertEqual(faces["end"][0]["point"], [5, 5, 50])

    def test_scaling_and_orientation_names_that_are_not_known_read_as_other(self):
        data = read_sweep(orientation="SomethingNew", profileScaling="NoScalingOption")
        self.assertEqual((data["orientation"], data["scaling"]), ("other", "none"))

    def test_a_setting_that_throws_or_is_missing_is_null_and_the_rest_is_still_read(self):
        members = dict(profile=profile(), path=None, guideRail=None, operation="JoinFeatureOperation",
                       distanceOne=parameter(1.0, "d1", "1"), taperAngle=parameter(0.0, "d3", "0 deg"))
        data = read("SweepFeature", "Sweep1", members, Broken)
        self.assertNotIn("read_error", data)
        self.assertEqual((data["distance_two"], data["twist_deg"], data["extent"], data["orientation"]),
                         (None, None, None, None))
        self.assertEqual((data["path"], data["participants"]), (None, None))
        self.assertEqual(data["faces_after"], {"start": None, "end": None})
        self.assertEqual((data["distance_one"], data["operation"]), (1.0, "join"))
        unreadable = read_sweep(profile=Obj("fusion::Profile"))
        self.assertEqual((unreadable["profiles"], unreadable["areas"]), (None, None))


class SweepPathTest(unittest.TestCase):
    def test_sketch_curves_are_read_in_the_component_frame_and_flat_in_the_sketch(self):
        sk = sketch()
        arc_sketch = sketch_curve(quarter_arc(), sk, "c2", "SketchArc")
        first = step(sketch_curve(line3((0, 0, 0), (0, 50, 0)), sk), check=line3((1, 2, 3), (4, 5, 6)))
        data = read_sweep(path=path(first, step(arc_sketch, opposed=True)))["path"]
        self.assertEqual((data["kind"], data["closed"], data["sketch"], data["sketch_token"]),
                         ("sketch", False, "Path1", "sk_path"))
        self.assertEqual(data["frame"]["origin"], [10, 0, 0])
        line, arc = data["curves"]
        self.assertEqual((line["kind"], line["start"], line["end"], line["entity"], line["opposed"]),
                         ("line", [10, 0, 0], [10, 0, 50], "c1", False))
        self.assertEqual(line["flat"], {"kind": "line", "start": [0, 0], "end": [0, 50]})
        self.assertEqual(line["check"], {"start": [1, 2, 3], "end": [4, 5, 6]})
        self.assertEqual((arc["kind"], arc["center"], arc["start"], arc["end"], arc["radius"], arc["opposed"]),
                         ("arc", [10, 0, 0], [10, 20, 0], [10, 0, 20], 20.0, True))
        self.assertEqual(arc["normal"], [1, 0, 0])
        self.assertAlmostEqual(arc["mid"][1], 20 * math.cos(math.pi / 4), places=4)
        self.assertEqual(arc["flat"]["kind"], "arc")

    def test_a_full_circle_is_a_closed_path_with_a_normal(self):
        circle = curve3("Circle3D", lambda t: (10 * math.cos(2 * math.pi * t), 10 * math.sin(2 * math.pi * t), 0),
                        center=P(0, 0, 0), normal=Obj(x=0, y=0, z=1), radius=1.0)
        data = read_sweep(path=path(step(sketch_curve(circle, sketch(), kind="SketchCircle")), closed=True))["path"]
        self.assertTrue(data["closed"])
        self.assertEqual((data["curves"][0]["kind"], data["curves"][0]["radius"], data["curves"][0]["normal"]),
                         ("circle", 10.0, [1, 0, 0]))

    def test_a_spline_is_sampled_in_three_dimensions(self):
        spline = curve3("NurbsCurve3D", lambda t: (30 * t, 10 * math.sin(math.pi * t), 5 * t))
        fitted = sketch_curve(spline, sketch(), kind="SketchFittedSpline")
        curve = read_sweep(path=path(step(fitted)))["path"]["curves"][0]
        self.assertEqual((curve["kind"], curve["type"]), ("other", "NurbsCurve3D"))
        self.assertEqual((curve["start"], curve["end"]), ([10, 0, 0], [15, 30, 0]))
        self.assertGreater(len(curve["samples"]), 8)
        self.assertTrue(any(abs(p[2] - 10.0) < 0.5 for p in curve["samples"]))

    def test_a_curve_off_the_sketch_plane_has_no_flat_form(self):
        slanted = line3((0, 0, 0), (0, 40, 30))
        curve = read_sweep(path=path(step(sketch_curve(slanted, sketch()))))["path"]["curves"][0]
        self.assertIsNone(curve["flat"])
        self.assertEqual(curve["end"], [40, 0, 40])

    def test_a_guide_rail_is_read_like_a_path(self):
        rail = path(step(sketch_curve(line3((0, 0, 0), (0, 50, 0)), sketch("Rail", "sk_rail"), "r1")))
        data = read_sweep(guideRail=rail)["rail"]
        self.assertEqual((data["kind"], data["sketch_token"], data["curves"][0]["entity"]), ("sketch", "sk_rail", "r1"))

    def test_a_guide_rail_that_cannot_be_read_is_not_taken_for_no_rail(self):
        self.assertEqual(read_sweep(kind=RailBroken)["rail"], {"kind": "unread"})
        self.assertIsNone(read_sweep()["rail"])

    def test_a_path_of_more_entities_than_are_read_is_marked_truncated(self):
        def many(count):
            return path(*[step(sketch_curve(line3((0, i, 0), (0, i + 1, 0)), sketch(), "c%d" % i))
                          for i in range(count)])
        found = read_sweep(path=many(257))["path"]
        self.assertEqual((len(found["curves"]), found["truncated"]), (256, True))
        self.assertNotIn("truncated", read_sweep(path=many(256))["path"])

    def test_a_path_sketch_says_what_it_sits_on_and_whether_it_holds_projected_curves(self):
        sk = sketch()
        sk.referencePlane = Obj("fusion::ConstructionPlane", entityToken="cp1")
        sk.sketchCurves = Coll([Obj(isReference=False), Obj(isReference=True)])
        found = read_sweep(path=path(step(sketch_curve(line3((0, 0, 0), (0, 50, 0)), sk))))["path"]
        self.assertEqual((found["reference"], found["projected"]), ({"kind": "constructionPlane", "token": "cp1"}, True))

    def test_edges_are_pick_records_and_not_pick_free_curves(self):
        data = read_sweep(path=path(step(edge("e1")), step(edge("e2", a=(30, 0, 0), b=(30, 20, 0)))))
        self.assertEqual(data["path"]["kind"], "edges")
        self.assertEqual([e["token"] for e in data["path"]["edges"]], ["e1", "e2"])
        self.assertEqual(data["path"]["edges"][0]["body"]["token"], "eb")
        self.assertEqual(data["path"]["curves"][0]["start"], [0, 0, 0])
        self.assertEqual([r["kind"] for r in pick_records({"data": data})], ["edge", "edge"])
        self.assertNotIn("foreign", data["path"])

    def test_an_edge_of_another_component_is_marked_foreign(self):
        found = read_sweep(path=path(step(edge("e1")), step(edge("e2", component=OTHER))))["path"]
        self.assertTrue(found["foreign"])
        self.assertTrue(found["edges"][1]["foreign"])
        self.assertNotIn("foreign", found["edges"][0])

    def test_a_curve_of_another_components_sketch_is_marked_foreign(self):
        found = read_sweep(path=path(step(sketch_curve(line3((0, 0, 0), (0, 50, 0)), sketch(component=OTHER)))))["path"]
        self.assertTrue(found["foreign"])
        self.assertTrue(found["curves"][0]["foreign"])

    def test_a_path_of_edges_and_curves_is_mixed_and_an_unknown_entity_is_other(self):
        curve = sketch_curve(line3((0, 0, 0), (0, 50, 0)), sketch())
        self.assertEqual(read_sweep(path=path(step(edge()), step(curve)))["path"]["kind"], "mixed")
        found = read_sweep(path=path(step(curve), step(Obj("fusion::Weird"))))["path"]
        self.assertEqual(found["kind"], "other")
        self.assertEqual(found["curves"][1], {"kind": "other", "type": "Weird", "opposed": False, "check": None})

    def test_a_path_that_cannot_be_listed_has_no_curves(self):
        broken = Obj("fusion::Path", isClosed=False)
        found = read_sweep(path=broken)["path"]
        self.assertEqual((found["kind"], found["curves"], found["edges"]), ("other", None, []))


def section(entity, end="LoftFreeEndCondition", **condition):
    return Obj(entity=entity, endCondition=Obj("fusion::" + end, **condition))


class LoftTest(unittest.TestCase):
    def test_profile_sections_follow_the_profile_list_in_order(self):
        data = read_loft(loftSections=Coll([section(profile(40, 4.0)), section(profile(20, 2.0))]))
        self.assertEqual([(s["kind"], s["profile"], s["end"]) for s in data["sections"]],
                         [("profile", 0, "free"), ("profile", 1, "free")])
        self.assertEqual((len(data["profiles"]), data["areas"]), (2, [400.0, 200.0]))
        self.assertEqual((data["operation"], data["closed"], data["merge_tangent"], data["solid"]),
                         ("newBody", False, True, True))
        self.assertEqual((data["rails"], data["centerline"]), ([], None))
        self.assertEqual((data["faces_after"]["start"][0]["point"], data["faces_after"]["end"][0]["point"]),
                         ([5, 5, 0], [5, 5, 30]))

    def test_end_condition_kinds_and_their_angles_and_weights(self):
        angle = parameter(math.radians(10), "d9", "10 deg")
        data = read_loft(loftSections=Coll([
            section(profile(), "LoftDirectionEndCondition", angle=angle, weight=parameter(1.5, "d10", "1.5")),
            section(profile(), "LoftTangentEndCondition", weight=2.0),
            section(profile(), "LoftSmoothEndCondition"),
            section(profile(), "LoftPointSharpEndCondition"),
            section(profile(), "LoftPointTangentEndCondition"),
            section(profile(), "LoftSomethingNewEndCondition"),
        ]))
        self.assertEqual([s["end"] for s in data["sections"]],
                         ["direction", "tangent", "smooth", "pointSharp", "pointTangent", "other"])
        self.assertEqual((data["sections"][0]["angle"], data["sections"][0]["weight"]), (10.0, 1.5))
        self.assertEqual(data["sections"][1]["weight"], 2.0)
        self.assertEqual(data["params"]["sections.0.angle"], {"name": "d9", "expression": "10 deg", "value": 10.0})
        self.assertEqual(data["params"]["sections.0.weight"]["value"], 1.5)
        self.assertNotIn("sections.1.weight", data["params"])
        self.assertNotIn("angle", data["sections"][2])

    def test_a_section_without_a_readable_end_condition_has_a_null_end(self):
        data = read_loft(loftSections=Coll([Obj(entity=profile())]))
        self.assertEqual((data["sections"][0]["kind"], data["sections"][0]["end"]), ("profile", None))

    def test_points_faces_and_other_entities_are_sections_of_their_own_kind(self):
        point = Obj("fusion::SketchPoint", geometry=P(5, 0, 0), parentSketch=sketch(), entityToken="p1")
        vertex = Obj("fusion::BRepVertex", geometry=P(1, 2, 3), entityToken="v1", body=Obj(parentComponent=ROOT))
        data = read_loft(loftSections=Coll([
            section(point), section(vertex), section(face(10, "Cylinder")), section(Obj("fusion::Path"))]))
        kinds = data["sections"]
        self.assertEqual((kinds[0]["kind"], kinds[0]["point"]), ("point", [10, 5, 0]))
        self.assertEqual((kinds[1]["kind"], kinds[1]["point"]), ("point", [1, 2, 3]))
        self.assertEqual((kinds[2]["kind"], kinds[2]["face"]["surface"]), ("face", "Cylinder"))
        self.assertEqual((kinds[3]["kind"], kinds[3]["type"]), ("other", "Path"))
        self.assertEqual(data["profiles"], [])

    def test_a_section_given_as_a_collection_is_one_profile_or_lists_what_it_holds(self):
        edges = Coll([Obj("fusion::BRepEdge"), Obj("fusion::BRepEdge")])
        data = read_loft(loftSections=Coll([section(Coll([profile(40, 4.0)])), section(edges)]))
        self.assertEqual(data["sections"][0]["kind"], "profile")
        self.assertEqual((data["sections"][1]["items"], data["sections"][1]["count"]), (["BRepEdge", "BRepEdge"], 2))

    def test_rails_and_a_centre_line_are_read_like_paths(self):
        one = path(step(sketch_curve(line3((0, 0, 0), (0, 50, 0)), sketch("RailA", "rail_a"))))
        two = path(step(sketch_curve(line3((0, 0, 0), (0, 40, 0)), sketch("RailB", "rail_b"))))
        rails = Obj("fusion::LoftCenterLineOrRails", count=2, isCenterLine=False, item=lambda i: (one, two)[i])
        data = read_loft(centerLineOrRails=rails)
        self.assertEqual([r["sketch_token"] for r in data["rails"]], ["rail_a", "rail_b"])
        self.assertIsNone(data["centerline"])
        centre = Obj("fusion::LoftCenterLineOrRails", count=1, isCenterLine=True, item=lambda i: one)
        data = read_loft(centerLineOrRails=centre)
        self.assertEqual((data["rails"], data["centerline"]["sketch_token"]), ([], "rail_a"))

    def test_a_closed_loft_is_flagged_and_unreadable_members_are_null(self):
        class Stub(Obj):
            @property
            def centerLineOrRails(self):
                raise RuntimeError("not available")

        data = read("LoftFeature", "Loft1", dict(isClosed=True), Stub)
        self.assertTrue(data["closed"])
        self.assertEqual((data["sections"], data["profiles"], data["rails"], data["centerline"], data["merge_tangent"]),
                         (None, None, None, None, None))


if __name__ == "__main__":
    unittest.main()
