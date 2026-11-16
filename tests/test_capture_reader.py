import json
import math
import unittest
from unittest import mock

from tests import context  # noqa: F401
from lib.fusion_reader import capture as capture_module
from lib.fusion_reader import read_sketch
from lib.fusion_reader.capture import CaptureReadError, read_capture
from lib.fusion_reader.read_geometry import edge_record

CM = 0.1  # one mm in Fusion cm


class Obj:
    def __init__(self, type_name=None, **kw):
        if type_name:
            kw["objectType"] = "adsk::%s" % type_name
        self.__dict__.update(kw)

    # Fusion objects of one entity are equal; the fake says so by its token.
    def __eq__(self, other):
        token = self.__dict__.get("entityToken")
        return self is other or (token is not None and isinstance(other, Obj)
                                 and other.__dict__.get("entityToken") == token)

    def __hash__(self):
        return hash(self.__dict__.get("entityToken", id(self)))


class Coll:
    def __init__(self, items=()):
        self._items = list(items)
        self.count = len(self._items)

    def item(self, i):
        return self._items[i]


def P(x, y, z=0.0):
    """Point or vector from mm values."""
    return Obj(x=x * CM, y=y * CM, z=z * CM)


def param(value):
    return Obj(value=value)


def matrix(origin=(0, 0, 0), x=(1, 0, 0), y=(0, 1, 0), z=(0, 0, 1)):
    return Obj(getAsCoordinateSystem=lambda: (P(*origin), Obj(x=x[0], y=x[1], z=x[2]),
                                              Obj(x=y[0], y=y[1], z=y[2]), Obj(x=z[0], y=z[1], z=z[2])))


def line(a, b):
    return Obj("core::Line3D", startPoint=P(*a), endPoint=P(*b))


def curve_of(geometry):
    return Obj(geometry=geometry)


def profile_of(geometries, sketch=None, outer=True):
    sketch = sketch or Obj("fusion::Sketch", name="Sketch1", transform=matrix())
    loop = Obj(isOuter=outer, profileCurves=Coll([curve_of(g) for g in geometries]))
    return Obj("fusion::Profile", parentSketch=sketch, profileLoops=Coll([loop]))


def rect_profile(w=40, h=20):
    return profile_of([line((0, 0), (w, 0)), line((w, 0), (w, h)), line((w, h), (0, h)), line((0, h), (0, 0))])


def body(token="b1", name="Body1", lo=(0, 0, 0), hi=(40, 20, 10), volume=8.0):
    return Obj("fusion::BRepBody", entityToken=token, name=name, volume=volume,
               boundingBox=Obj(minPoint=P(*lo), maxPoint=P(*hi)))


def feature(type_name, name, bodies=(), **kw):
    kw.setdefault("parentComponent", Obj(entityToken="root"))
    kw.setdefault("bodies", Coll(bodies))
    return Obj("fusion::" + type_name, **kw), name


class FakeTimeline:
    def __init__(self, entries, fail_at=None):
        self.entries = entries  # (entity, name, extra) tuples
        self._pos = len(entries)
        self.history = []
        self.fail_at = fail_at
        self.timelineGroups = Coll([])

    @property
    def count(self):
        return len(self.entries)

    @property
    def markerPosition(self):
        return self._pos

    @markerPosition.setter
    def markerPosition(self, value):
        self.history.append(value)
        self._pos = value

    def moveToEnd(self):
        self._pos = len(self.entries)
        return True

    def item(self, i):
        if self.fail_at == i:
            raise RuntimeError("item gone")
        entity, name, extra = self.entries[i]
        fields = dict(isSuppressed=False, healthState="HealthyFeatureHealthState", errorOrWarningMessage="")
        fields.update(extra)
        return Obj("fusion::TimelineObject", entity=entity, name=name, index=i, **fields)


class FakeDesign:
    def __init__(self, entries, target, appears_at=1, fail_at=None):
        self.timeline = FakeTimeline(entries, fail_at)
        self.rootComponent = Obj(entityToken="root", bRepBodies=Coll([]))
        self._target = target
        self._appears_at = appears_at

    def findEntityByToken(self, token):
        if token == self._target.entityToken and self.timeline.markerPosition >= self._appears_at:
            return [self._target]
        return []


def entry(pair, **extra):
    entity, name = pair
    return (entity, name, extra)


def sketch_entry():
    return entry(feature("Sketch", "Sketch1", bodies=()))


def extrude(profile, name="Extrude1", target=None, **kw):
    kw.setdefault("operation", "NewBodyFeatureOperation")
    kw.setdefault("extentType", "OneSideFeatureExtentType")
    kw.setdefault("startExtent", Obj("fusion::ProfilePlaneStartDefinition"))
    kw.setdefault("extentOne", Obj("fusion::DistanceExtentDefinition", distance=param(1.0)))
    kw.setdefault("taperAngleOne", param(0.0))
    kw.setdefault("isThinExtrude", False)
    kw.setdefault("endFaces", Coll([Obj("fusion::BRepFace", pointOnFace=P(5, 5, 10))]))
    return entry(feature("ExtrudeFeature", name, bodies=[target] if target else [], profile=profile, **kw))


class WalkTest(unittest.TestCase):
    def setUp(self):
        self.target = body()
        self.design = FakeDesign([sketch_entry(), extrude(rect_profile(), target=self.target)], self.target)
        self.capture = read_capture(self.design, self.target, fusion="2.0.1", name="Clip", up_axis="z")

    def test_envelope_and_json_safe(self):
        c = self.capture
        self.assertEqual((c["capture"], c["fusion"], c["design"], c["up_axis"]), (3, "2.0.1", "Clip", "z"))
        self.assertEqual(c["target"], {"token": "b1", "name": "Body1",
                                       "box": {"min": [0, 0, 0], "max": [40, 20, 10]}, "volume_mm3": 8000.0,
                                       "component": {"token": "root", "name": "", "root": True}, "placement": None})
        self.assertEqual(c["targets"], [c["target"]])
        self.assertEqual([i["type"] for i in c["items"]], ["Sketch", "ExtrudeFeature"])
        self.assertEqual(json.loads(json.dumps(c)), c)

    def test_the_capture_carries_the_sketch_graphs_and_survives_a_graph_read_that_raises(self):
        self.assertEqual(self.capture["sketch_graphs"], [])
        read = lambda: read_capture(self.design, self.target, fusion="", name="", up_axis="z")  # noqa: E731
        with mock.patch("lib.fusion_reader.capture.sketch_graphs", return_value=[{"sketch": "Sketch1"}]):
            self.assertEqual(read()["sketch_graphs"], [{"sketch": "Sketch1"}])
        with mock.patch("lib.fusion_reader.capture.sketch_graphs", side_effect=RuntimeError("no")):
            capture = read()
        self.assertEqual(capture["sketch_graphs"], [])
        self.assertEqual([i["type"] for i in capture["items"]], ["Sketch", "ExtrudeFeature"])

    def test_item_fields(self):
        sketch, ext = self.capture["items"]
        self.assertEqual(sketch["data"], {})
        self.assertEqual((ext["index"], ext["name"], ext["health"], ext["component"], ext["in_target_component"]),
                         (1, "Extrude1", "ok", "root", True))
        self.assertNotIn("entity_context", ext)
        self.assertEqual(ext["bodies_after"], [{"token": "b1", "name": "Body1"}])

    def test_marker_moves_once_per_position_and_ends_at_end(self):
        self.assertEqual(self.design.timeline.history, [0, 1, 2])
        self.assertEqual(self.design.timeline.markerPosition, 2)

    def test_bodies_before_lists_the_root_bodies_at_the_marker_before_the_item(self):
        design = FakeDesign([sketch_entry(), extrude(rect_profile(), target=self.target)], self.target)
        roots = [Coll([]), Coll([self.target])]
        timeline = design.timeline
        design.rootComponent = Obj(entityToken="root", bRepBodies=None)
        original = timeline.item

        def item(i):
            design.rootComponent.bRepBodies = roots[min(i, 1)]
            return original(i)

        timeline.item = item
        items = read_capture(design, self.target, fusion="", name="", up_axis="z")["items"]
        self.assertEqual(items[0]["bodies_before"], [])
        self.assertEqual(items[1]["bodies_before"], [{"token": "b1", "name": "Body1"}])

    def test_unreadable_root_bodies_leave_bodies_before_out(self):
        design = FakeDesign([sketch_entry()], self.target)
        design.rootComponent.bRepBodies = None
        item = read_capture(design, self.target, fusion="", name="", up_axis="z")["items"][0]
        self.assertNotIn("bodies_before", item)

    def test_with_the_marker_rolled_back_only_the_steps_before_it_are_read(self):
        later = extrude(rect_profile(), name="Later", target=self.target, operation="JoinFeatureOperation")
        design = FakeDesign([sketch_entry(), extrude(rect_profile(), target=self.target), later], self.target)
        design.timeline._pos = 2
        capture = read_capture(design, self.target, fusion="", name="", up_axis="z")
        self.assertEqual([i["name"] for i in capture["items"]], ["Sketch1", "Extrude1"])
        self.assertEqual(capture["marker"], {"position": 2, "count": 3})
        self.assertEqual(design.timeline.history, [0, 1, 2])
        self.assertEqual(design.timeline.markerPosition, 2)

    def test_a_failed_walk_puts_the_marker_back_at_the_end_or_where_it_was_rolled_back_to(self):
        entries = [sketch_entry(), extrude(rect_profile(), target=self.target), sketch_entry()]
        for rolled_back in (3, 2):
            with self.subTest(marker=rolled_back):
                design = FakeDesign(entries, self.target, fail_at=1)
                design.timeline._pos = rolled_back
                with self.assertRaises(RuntimeError):
                    read_capture(design, self.target, fusion="", name="", up_axis="z")
                self.assertEqual(design.timeline.markerPosition, rolled_back)

    def test_a_group_after_the_marker_does_not_stop_the_read(self):
        entries = [sketch_entry(), extrude(rect_profile(), target=self.target), sketch_entry(), sketch_entry()]
        design = FakeDesign(entries, self.target)
        design.timeline._pos = 2
        design.timeline.timelineGroups = Coll([Obj(startIndex=1, endIndex=3)])
        items = read_capture(design, self.target, fusion="", name="", up_axis="z")["items"]
        self.assertEqual(len(items), 2)

    def test_target_box_is_read_before_the_item_and_none_while_the_body_does_not_exist(self):
        second = extrude(rect_profile(), name="Extrude2", target=self.target, operation="JoinFeatureOperation")
        design = FakeDesign([sketch_entry(), extrude(rect_profile(), target=self.target), second],
                            self.target, appears_at=2)
        items = read_capture(design, self.target, fusion="", name="", up_axis="z")["items"]
        self.assertIsNone(items[1]["data"]["target_box_before"])
        self.assertEqual(items[2]["data"]["target_box_before"], {"min": [0, 0, 0], "max": [40, 20, 10]})

    def test_unknown_type_suppressed_and_error_health(self):
        loft = entry(feature("ThickenFeature", "Coil1"))
        hidden_entity, hidden_name = feature("ExtrudeFeature", "Hidden")
        design = FakeDesign([loft, (hidden_entity, hidden_name, {})], self.target)
        design.timeline.entries[0][2]["healthState"] = "ErrorFeatureHealthState"
        design.timeline.entries[0][2]["errorOrWarningMessage"] = "Cannot build"
        design.timeline.entries[1][2]["isSuppressed"] = True
        items = read_capture(design, self.target, fusion="", name="", up_axis="z")["items"]
        self.assertEqual((items[0]["type"], items[0]["data"], items[0]["health"], items[0]["message"]),
                         ("ThickenFeature", {}, "error", "Cannot build"))
        self.assertTrue(items[1]["suppressed"])
        self.assertEqual(items[1]["data"], {})

    def test_item_without_entity_and_group_objects(self):
        design = FakeDesign([(None, "Mystery", {})], self.target)
        design.timeline.entries.append((feature("Sketch", "G")[0], "Group1", {"isGroup": True}))
        design.timeline._pos = 2
        items = read_capture(design, self.target, fusion="", name="", up_axis="z")["items"]
        self.assertEqual([(i["name"], i["type"]) for i in items], [("Mystery", "none")])

    def test_reader_failure_gives_read_error_and_the_walk_goes_on(self):
        broken = Obj("fusion::ExtrudeFeature", parentComponent=Obj(entityToken="root"), bodies=Coll([]))
        design = FakeDesign([(broken, "Broken", {}), extrude(rect_profile(), target=self.target)], self.target)
        items = read_capture(design, self.target, fusion="", name="", up_axis="z")["items"]
        self.assertIn("read_error", items[0]["data"])
        self.assertEqual(items[1]["data"]["operation"], "newBody")

    def test_feature_outside_the_target_component_is_listed_but_not_read(self):
        other = Obj("fusion::ExtrudeFeature", parentComponent=Obj(entityToken="child"), bodies=Coll([]))
        design = FakeDesign([(other, "Elsewhere", {})], self.target)
        items = read_capture(design, self.target, fusion="", name="", up_axis="z")["items"]
        self.assertEqual((items[0]["component"], items[0]["in_target_component"], items[0]["data"]),
                         ("child", False, {}))

    def other_run_design(self, gone_at=None):
        """Own extrude, three steps of another component, own extrude. With `gone_at`, the target is gone from that
        marker position on, as when a step of the other component takes it as a tool body."""
        others = [(Obj("fusion::ExtrudeFeature", parentComponent=Obj(entityToken="child"), bodies=Coll([])),
                   "Other%d" % n, {}) for n in range(3)]
        entries = [extrude(rect_profile(), target=self.target)] + others + [
            extrude(rect_profile(), name="Extrude2", target=self.target, operation="JoinFeatureOperation")]
        design = FakeDesign(entries, self.target)
        if gone_at is not None:
            found = design.findEntityByToken
            design.findEntityByToken = lambda token: [] if design.timeline.markerPosition >= gone_at else found(token)
        return design

    def test_the_target_is_not_measured_between_steps_of_another_component(self):
        design = self.other_run_design()
        with mock.patch.object(capture_module, "_target_state", wraps=capture_module._target_state) as measured:
            items = read_capture(design, self.target, fusion="", name="", up_axis="z")["items"]
        # Positions 2 and 3 lie between steps of the other component; the other four are measured.
        self.assertEqual(measured.call_count, 4)
        self.assertEqual([i["target_changed"] for i in items[1:4]], [False, False, False])
        self.assertEqual(items[2]["target_before"], items[1]["target_after"])
        self.assertNotIn("target_measured", items[2])

    def test_a_run_that_changed_the_target_is_measured_again_step_by_step(self):
        design = self.other_run_design(gone_at=3)
        items = read_capture(design, self.target, fusion="", name="", up_axis="z")["items"]
        self.assertEqual([i["target_changed"] for i in items[1:4]], [False, True, None])
        self.assertEqual(design.timeline.markerPosition, 5)

    def test_a_move_of_another_component_that_is_undone_later_in_the_run_is_still_seen(self):
        moves = [(Obj("fusion::MoveFeature", parentComponent=Obj(entityToken="child"), bodies=Coll([])), "Move%d" % n,
                  {}) for n in range(2)]
        other = (Obj("fusion::ExtrudeFeature", parentComponent=Obj(entityToken="child"), bodies=Coll([])), "Other", {})
        entries = [extrude(rect_profile(), target=self.target), other] + moves + [
            extrude(rect_profile(), name="Extrude2", target=self.target, operation="JoinFeatureOperation")]
        design = FakeDesign(entries, self.target)
        moved = body(lo=(5, 0, 0), hi=(45, 20, 10))
        found = design.findEntityByToken
        design.findEntityByToken = lambda token: [moved] if design.timeline.markerPosition == 3 else found(token)
        items = read_capture(design, self.target, fusion="", name="", up_axis="z")["items"]
        self.assertEqual([i["target_changed"] for i in items[1:4]], [False, True, True])

    def test_extra_readers_plug_in_before_and_after(self):
        fillet = entry(feature("FilletFeature", "Fillet1"))
        design = FakeDesign([fillet], self.target)
        readers = {"FilletFeature": (lambda f, ctx: {"a": 1}, lambda f, ctx, data: {"b": data["a"] + 1})}
        items = read_capture(design, self.target, fusion="", name="", up_axis="z", extra_readers=readers)["items"]
        self.assertEqual(items[0]["data"], {"a": 1, "b": 2})


class UnreadableTest(unittest.TestCase):
    def capture(self, entries, target=None):
        target = target or body()
        return read_capture(FakeDesign(entries, target), target, fusion="", name="", up_axis="z")

    def test_unreadable_bodies_are_null_not_empty(self):
        move = Obj("fusion::MoveFeature", parentComponent=Obj(entityToken="root"))
        item = self.capture([(move, "Move1", {})])["items"][0]
        self.assertIsNone(item["bodies_after"])
        self.assertTrue(item["read_error"].startswith("bodies"))
        empty = self.capture([entry(feature("ThickenFeature", "E"))])["items"][0]
        self.assertEqual(empty["bodies_after"], [])
        self.assertNotIn("read_error", empty)

    def test_unreadable_extrude_members_read_as_unknown(self):
        target = body()
        ext = extrude(rect_profile(), target=target, extentType="WeirdFeatureExtentType", taperAngleOne=None,
                      startExtent=Obj("fusion::OddStartDefinition"))
        data = self.capture([sketch_entry(), ext], target)["items"][1]["data"]
        self.assertEqual(data["extent_type"], "other")
        self.assertEqual(data["side_one"]["kind"], "other")
        self.assertEqual(data["start"], {"kind": "other", "type": "OddStartDefinition"})
        ext = extrude(rect_profile(), target=target, taperAngleOne=None, startExtent=None)
        data = self.capture([sketch_entry(), ext], target)["items"][1]["data"]
        self.assertIsNone(data["side_one"]["taper_deg"])
        self.assertEqual(data["start"]["kind"], "other")

    def test_a_distance_fusion_refuses_reads_as_another_way_of_setting_the_length(self):
        target = body()
        refused = Obj("fusion::DistanceExtentDefinition")  # reading `distance` raises
        data = self.capture([sketch_entry(), extrude(rect_profile(), target=target, extentOne=refused)],
                            target)["items"][1]["data"]
        self.assertEqual(data["side_one"], {"kind": "other", "type": "DistanceExtentDefinition"})
        symmetric = extrude(rect_profile(), target=target, extentType="SymmetricFeatureExtentType",
                            symmetricExtent=Obj("fusion::SymmetricExtentDefinition"))
        self.assertIsNone(self.capture([sketch_entry(), symmetric], target)["items"][1]["data"]["symmetric"])

    def test_a_symmetric_extrude_through_all_reads_its_extent_like_one_side(self):
        target = body()
        through = extrude(rect_profile(), target=target, extentType="SymmetricFeatureExtentType",
                          symmetricExtent=Obj("fusion::SymmetricExtentDefinition", taperAngle=param(0.05)),
                          extentOne=Obj("fusion::ThroughAllExtentDefinition", isPositiveDirection=True))
        data = self.capture([sketch_entry(), through], target)["items"][1]["data"]
        self.assertEqual((data["symmetric"], data["side_one"]["kind"], round(data["side_one"]["taper_deg"], 6)),
                         (None, "throughAll", round(math.degrees(0.05), 6)))

    def test_end_face_types_follow_the_end_points(self):
        target = body()
        hole = entry(feature("HoleFeature", "H", bodies=[target], holeType="SimpleHoleType",
                             holeTapType="SimpleHoleTapType", holeDiameter=param(0.5), position=P(0, 0, 0),
                             extentDefinition=Obj("fusion::DistanceExtentDefinition", distance=param(0.8)),
                             endFaces=Coll([Obj(pointOnFace=P(0, 0, 1), geometry=Obj("core::Cone")),
                                            Obj(pointOnFace=P(0, 0, 2), geometry=Obj("core::Plane")),
                                            Obj(pointOnFace=P(0, 0, 3), geometry=Obj("core::Torus")),
                                            Obj(pointOnFace=P(0, 0, 4))])))
        data = self.capture([hole], target)["items"][0]["data"]
        self.assertEqual(data["end_face_types"], ["cone", "plane", None, None])
        self.assertEqual(len(data["end_points"]), 4)

    def test_group_children_not_in_the_walk_refuse_the_capture(self):
        target = body()
        design = FakeDesign([sketch_entry(), sketch_entry()], target)
        design.timeline.timelineGroups = Coll([Obj(startIndex=1, endIndex=3)])
        with self.assertRaises(CaptureReadError):
            read_capture(design, target, fusion="", name="", up_axis="z")
        self.assertEqual(design.timeline.markerPosition, 2)
        design.timeline.timelineGroups = Coll([Obj(startIndex=0, endIndex=1)])
        read_capture(design, target, fusion="", name="", up_axis="z")


class ExtrudeDataTest(unittest.TestCase):
    def read(self, **kw):
        target = body()
        profile = kw.pop("profile", None) or rect_profile()
        design = FakeDesign([sketch_entry(), extrude(profile, target=target, **kw)], target)
        return read_capture(design, target, fusion="", name="", up_axis="z")["items"][1]["data"]

    def test_one_sided_distance_profile_and_end_offset(self):
        data = self.read()
        self.assertEqual(data["operation"], "newBody")
        self.assertEqual(data["start"], {"kind": "profilePlane"})
        self.assertEqual(data["extent_type"], "one")
        self.assertEqual(data["side_one"], {"kind": "distance", "distance": 10.0, "taper_deg": 0.0})
        self.assertIsNone(data["side_two"])
        self.assertEqual(data["end_offset"], 10.0)
        profile = data["profiles"][0]
        self.assertEqual(profile["sketch"], "Sketch1")
        self.assertEqual(profile["frame"], {"origin": [0, 0, 0], "x": [1, 0, 0], "y": [0, 1, 0], "z": [0, 0, 1]})
        self.assertEqual(profile["loops"][0]["outer"], True)
        self.assertEqual(profile["loops"][0]["curves"][1], {"kind": "line", "start": [40, 0], "end": [40, 20]})

    def test_profile_and_end_face_areas_in_mm2(self):
        profile = rect_profile()
        profile.areaProperties = lambda: Obj(area=8.0)  # 800 mm2
        data = self.read(profile=profile, endFaces=Coll([Obj(pointOnFace=P(5, 5, 10), area=7.0)]))
        self.assertEqual((data["profile_area"], data["end_area"]), (800.0, 700.0))
        unknown = self.read()
        self.assertEqual((unknown["profile_area"], unknown["end_area"]), (None, None))

    def test_the_end_face_parallel_to_the_sketch_is_measured_with_its_normal(self):
        def face(z, area, normal):
            return Obj("fusion::BRepFace", pointOnFace=P(5, 5, z), area=area,
                       evaluator=Obj(getNormalAtPoint=lambda p: (True, Obj(x=normal[0], y=normal[1], z=normal[2]))))
        wall, cap = face(3, 0.5, (1, 0, 0)), face(10, 8.0, (0, 0, 1))
        data = self.read(endFaces=Coll([wall, cap]))
        self.assertEqual((data["end_offset"], data["end_area"], data["end_normal"]), (10.0, 800.0, [0, 0, 1]))
        # No face is parallel: the first one is measured, and its normal shows that it is not a cap.
        data = self.read(endFaces=Coll([wall]))
        self.assertEqual((data["end_offset"], data["end_normal"]), (3.0, [1, 0, 0]))
        # A normal that cannot be read is null.
        self.assertIsNone(self.read(endFaces=Coll([Obj(pointOnFace=P(5, 5, 10), area=7.0)]))["end_normal"])

    def test_side_walls_give_their_lean_along_the_sketch_normal(self):
        def wall(nz):
            normal = Obj(x=math.sqrt(1 - nz * nz), y=0, z=nz)
            return Obj("fusion::BRepFace", pointOnFace=P(0, 0, 5),
                       evaluator=Obj(getNormalAtPoint=lambda p: (True, normal)))
        self.assertEqual(self.read(sideFaces=Coll([wall(0.1), wall(0.0)]))["side_leans"], [0.1, 0.0])
        self.assertNotIn("side_leans", self.read())

    def test_negative_distance_keeps_its_sign_and_end_offset_follows_the_end_face(self):
        data = self.read(extentOne=Obj("fusion::DistanceExtentDefinition", distance=param(-0.8)),
                         endFaces=Coll([Obj(pointOnFace=P(5, 5, -8))]))
        self.assertEqual(data["side_one"]["distance"], -8.0)
        self.assertEqual(data["end_offset"], -8.0)

    def test_two_sides_with_tapers_and_start_offset(self):
        data = self.read(
            extentType="TwoSidesFeatureExtentType",
            extentTwo=Obj("fusion::DistanceExtentDefinition", distance=param(0.4)),
            taperAngleOne=param(math.radians(5)), taperAngleTwo=param(0.0),
            startExtent=Obj("fusion::OffsetStartDefinition", offset=param(0.3)),
            operation="CutFeatureOperation")
        self.assertEqual(data["extent_type"], "two")
        self.assertEqual(data["operation"], "cut")
        self.assertEqual(data["side_one"]["taper_deg"], 5.0)
        self.assertEqual(data["side_two"]["distance"], 4.0)
        self.assertEqual(data["start"], {"kind": "offset", "offset": 3.0})

    def test_symmetric_through_all_and_to_entity(self):
        sym = self.read(extentType="SymmetricFeatureExtentType",
                        symmetricExtent=Obj("fusion::SymmetricExtentDefinition", distance=param(0.5),
                                            isFullLength=False, taperAngle=param(0.0)))
        self.assertEqual(sym["symmetric"], {"distance": 5.0, "full_length": False, "taper_deg": 0.0})
        self.assertIsNone(sym["side_one"])
        through = self.read(extentOne=Obj("fusion::ThroughAllExtentDefinition", isPositiveDirection=False))
        self.assertEqual(through["side_one"], {"kind": "throughAll", "positive": False, "taper_deg": 0.0})
        face = Obj("fusion::BRepFace", geometry=Obj("core::Plane", origin=P(0, 0, 12), normal=Obj(x=0, y=0, z=1)),
                   pointOnFace=P(2, 3, 12))
        to_face = self.read(extentOne=Obj("fusion::ToEntityExtentDefinition", entity=face))
        self.assertEqual(to_face["side_one"]["plane"], {"point": [0, 0, 12], "normal": [0, 0, 1]})
        self.assertEqual((to_face["side_one"]["entity_type"], to_face["side_one"]["face_point"]),
                         ("BRepFace", [2, 3, 12]))
        unknown = self.read(extentOne=Obj("fusion::SomethingNewExtentDefinition"))
        self.assertEqual(unknown["side_one"], {"kind": "other", "type": "SomethingNewExtentDefinition"})

    def test_several_profiles_and_face_profile(self):
        faceish = Obj("fusion::BRepFace")
        data = self.read(profile=Coll([rect_profile(), faceish]))
        self.assertEqual(len(data["profiles"]), 2)
        self.assertEqual(data["profiles"][1], {"face": True, "type": "BRepFace", "surface": None, "problem": "unread"})


class SketchCurveTest(unittest.TestCase):
    def curves(self, geometries, sketch=None):
        return read_sketch.read_profile(profile_of(geometries, sketch))["loops"][0]["curves"]

    def test_circle_arc_ellipse_and_free_curve(self):
        arc = Obj("core::Arc3D", center=P(0, 0), radius=5 * CM, startPoint=P(5, 0), endPoint=P(0, 5),
                  evaluator=Obj(getParameterExtents=lambda: (True, 0.0, 2.0),
                                getPointAtParameter=lambda t: (True, P(5 * math.cos(t * math.pi / 4),
                                                                       5 * math.sin(t * math.pi / 4)))))
        nurbs = Obj("core::NurbsCurve3D", evaluator=Obj(getParameterExtents=lambda: (True, 0.0, 1.0),
                                                        getPointAtParameter=lambda t: (True, P(10 * t, 2 * t))))
        circle = Obj("core::Circle3D", center=P(3, 4), radius=2 * CM)
        ellipse = Obj("core::Ellipse3D", center=P(1, 1), majorAxis=Obj(x=0.0, y=2.0, z=0.0),
                      majorRadius=6 * CM, minorRadius=3 * CM)
        got = self.curves([circle, arc, ellipse, nurbs])
        self.assertEqual(got[0], {"kind": "circle", "center": [3, 4], "radius": 2.0})
        self.assertEqual(got[1]["kind"], "arc")
        self.assertAlmostEqual(got[1]["mid"][0], 5 * math.cos(math.pi / 4), places=5)
        self.assertEqual((got[1]["start"], got[1]["end"], got[1]["radius"]), ([5, 0], [0, 5], 5.0))
        self.assertEqual(got[2], {"kind": "ellipse", "center": [1, 1], "major_dir": [0, 1],
                                  "major_radius": 6.0, "minor_radius": 3.0})
        self.assertEqual((got[3]["kind"], got[3]["type"], len(got[3]["samples"])), ("other", "NurbsCurve3D", 17))
        self.assertEqual((got[3]["start"], got[3]["end"]), ([0, 0], [10, 2]))

    def test_model_space_geometry_is_mapped_into_sketch_space(self):
        # sketch plane at z = 5; the sketch maps model (x, y, z) to (x, y, z - 5)
        sketch = Obj("fusion::Sketch", name="Tilted", transform=matrix(origin=(0, 0, 5)),
                     modelToSketchSpace=lambda p: Obj(x=p.x, y=p.y, z=p.z - 5 * CM))
        got = self.curves([line((1, 2, 5), (3, 2, 5)), line((3, 2, 5), (3, 4, 5))], sketch)
        self.assertEqual(got[0], {"kind": "line", "start": [1, 2], "end": [3, 2]})
        profile = read_sketch.read_profile(profile_of([line((1, 2, 5), (3, 2, 5))], sketch))
        self.assertEqual((profile["frame"]["origin"], profile["space"]), ([0, 0, 5], "model"))

    def test_flat_points_on_a_standing_sketch_are_sketch_space(self):
        # A sketch on the YZ plane: its model points would have z off 0, so flat points are in sketch space.
        standing = matrix(x=(0, 1, 0), y=(0, 0, 1), z=(1, 0, 0))
        sketch = Obj("fusion::Sketch", name="Side", transform=standing, modelToSketchSpace=lambda p: Obj(x=p.y, y=p.z, z=p.x))
        pieces = [line((0, 0), (4, 0)), line((4, 0), (4, 3)), line((4, 3), (0, 0))]
        profile = read_sketch.read_profile(profile_of(pieces, sketch))
        self.assertEqual(profile["space"], "sketch")
        self.assertEqual(profile["loops"][0]["curves"][1], {"kind": "line", "start": [4, 0], "end": [4, 3]})

    def test_space_in_the_plane_z_zero(self):
        flipped = matrix(y=(0, -1, 0), z=(0, 0, -1))
        to_sketch = lambda p: Obj(x=p.x, y=-p.y, z=-p.z)
        sketch = Obj("fusion::Sketch", name="Bottom", transform=flipped, modelToSketchSpace=to_sketch)

        def profile_with(entity_geometry):
            geometry = line((1, 2), (3, 2))
            curve = Obj(geometry=geometry)
            if entity_geometry is not None:
                curve.sketchEntity = Obj(geometry=entity_geometry)
            loop = Obj(isOuter=True, profileCurves=Coll([curve]))
            return Obj("fusion::Profile", parentSketch=sketch, profileLoops=Coll([loop]))

        self.assertEqual(read_sketch.read_profile(profile_with(None))["space"], "ambiguous")
        self.assertEqual(read_sketch.read_profile(profile_with(line((1, 2), (3, 2))))["space"], "sketch")
        self.assertEqual(read_sketch.read_profile(profile_with(line((1, -2), (3, -2))))["space"], "model")
        self.assertEqual(read_sketch.read_profile(rect_profile())["space"], "sketch")


class RevolveTest(unittest.TestCase):
    def read(self, axis, extent, start_faces=None, **kw):
        target = body()
        face_axis = Obj("fusion::SketchLine", worldGeometry=line((0, 0, 0), (0, 3, 0))) if axis is None else axis
        rev = entry(feature("RevolveFeature", "Revolve1", bodies=[target], operation="NewBodyFeatureOperation",
                            profile=rect_profile(), axis=face_axis, isProjectAxis=False,
                            extentDefinition=extent, startFaces=start_faces, **kw))
        design = FakeDesign([sketch_entry(), rev], target)
        return read_capture(design, target, fusion="", name="", up_axis="z")["items"][1]["data"]

    def test_full_turn_has_no_start_normal(self):
        data = self.read(None, Obj("fusion::AngleExtentDefinition", angle=param(2 * math.pi), isSymmetric=False),
                         start_faces=Coll([Obj(pointOnFace=P(0, 0))]))
        self.assertEqual((data["axis"]["point"], data["axis"]["dir"]), ([0, 0, 0], [0, 1, 0]))
        self.assertEqual(data["extent"], {"kind": "angle", "angle_deg": 360.0, "symmetric": False})
        self.assertIsNone(data["start_face_normal"])

    def test_part_turn_measures_the_start_face_normal(self):
        face = Obj("fusion::BRepFace", pointOnFace=P(7, 0, 0),
                   evaluator=Obj(getNormalAtPoint=lambda p: (True, Obj(x=0.0, y=0.0, z=-1.0))))
        data = self.read(None, Obj("fusion::AngleExtentDefinition", angle=param(math.pi / 2), isSymmetric=True),
                         start_faces=Coll([face]))
        self.assertEqual(data["extent"], {"kind": "angle", "angle_deg": 90.0, "symmetric": True})
        self.assertEqual(data["start_face_normal"], [0, 0, -1])

    def test_axis_sources_two_sides_and_unknown(self):
        cyl = Obj("fusion::BRepFace", geometry=Obj("core::Cylinder", origin=P(1, 2, 3), axis=Obj(x=0, y=0, z=2.0)))
        con = Obj("fusion::ConstructionAxis", geometry=Obj("core::InfiniteLine3D", origin=P(0, 0, 4),
                                                           direction=Obj(x=1.0, y=0.0, z=0.0)))
        two = Obj("fusion::TwoSidesAngleExtentDefinition", angleOne=param(math.radians(30)),
                  angleTwo=param(math.radians(60)))
        self.assertEqual(self.read(cyl, two)["axis"], {"point": [1, 2, 3], "dir": [0, 0, 1], "entity_type": "BRepFace",
                                                       "surface": "Cylinder"})
        data = self.read(con, two)
        self.assertEqual(data["axis"], {"point": [0, 0, 4], "dir": [1, 0, 0], "entity_type": "ConstructionAxis"})
        self.assertEqual(data["extent"], {"kind": "twoSidesAngle", "angle_one_deg": 30.0, "angle_two_deg": 60.0})
        odd = self.read(Obj("fusion::Vertex"), Obj("fusion::NewExtentDefinition"))
        self.assertEqual(odd["axis"], {"kind": "other", "type": "Vertex"})
        self.assertEqual(odd["extent"], {"kind": "other", "type": "NewExtentDefinition"})


class HoleTest(unittest.TestCase):
    def read(self, **kw):
        target = body()
        base = dict(
            holeType="SimpleHoleType", holeTapType="SimpleHoleTapType", holeDiameter=param(0.5),
            tipAngle=param(math.radians(118)), direction=Obj(x=0.0, y=0.0, z=-1.0), position=P(10, 10, 10),
            holePositionDefinition=Obj("fusion::SketchPointsHolePositionDefinition", sketchPoints=Coll([
                Obj(worldGeometry=P(10, 10, 10)), Obj(worldGeometry=P(20, 10, 10))])),
            extentDefinition=Obj("fusion::DistanceExtentDefinition", distance=param(0.8)),
            sideFaces=Coll([Obj(geometry=Obj("core::Cylinder", origin=P(10, 10, 10), axis=Obj(x=0, y=0, z=-1.0),
                                             radius=0.25))]),
            endFaces=Coll([Obj(pointOnFace=P(10, 10, 2))]))
        base.update(kw)
        hole = entry(feature("HoleFeature", "Hole1", bodies=[target], **base))
        design = FakeDesign([hole], target)
        return read_capture(design, target, fusion="", name="", up_axis="z")["items"][0]["data"]

    def test_simple_blind_hole_with_measured_faces(self):
        data = self.read()
        self.assertEqual((data["hole_type"], data["tap_type"], data["diameter"]), ("simple", "simple", 5.0))
        self.assertEqual(data["tip_angle_deg"], 118.0)
        self.assertEqual(data["direction"], [0, 0, -1])
        self.assertEqual(data["positions"], [[10, 10, 10], [20, 10, 10]])
        self.assertEqual(data["extent"], {"kind": "distance", "depth": 8.0})
        self.assertEqual(data["side_cylinders"], [{"origin": [10, 10, 10], "axis": [0, 0, -1], "radius": 2.5}])
        self.assertEqual(data["end_points"], [[10, 10, 2]])
        self.assertIsNone(data["counterbore"])
        self.assertIsNone(data["thread_modeled"])

    def test_counterbore_countersink_through_and_single_position(self):
        cb = self.read(holeType="CounterboreHoleType", counterboreDiameter=param(0.9), counterboreDepth=param(0.3),
                       extentDefinition=Obj("fusion::ThroughAllExtentDefinition"),
                       holePositionDefinition=Obj("fusion::PointHolePositionDefinition"))
        self.assertEqual(cb["counterbore"], {"diameter": 9.0, "depth": 3.0})
        self.assertEqual(cb["extent"], {"kind": "throughAll"})
        self.assertEqual(cb["positions"], [[10, 10, 10]])
        cs = self.read(holeType="CountersinkHoleType", countersinkDiameter=param(1.0),
                       countersinkAngle=param(math.radians(90)))
        self.assertEqual(cs["countersink"], {"diameter": 10.0, "angle_deg": 90.0})

    def test_tapped_hole_reports_the_thread(self):
        data = self.read(holeTapType="TappedHoleTapType", thread=Obj(isModeled=True))
        self.assertEqual((data["tap_type"], data["thread_modeled"]), ("tapped", True))
        taper = self.read(holeTapType="TaperTappedHoleTapType", thread=Obj(isModeled=False))
        self.assertEqual((taper["tap_type"], taper["thread_modeled"]), ("taperTapped", False))


class CombineThreadTest(unittest.TestCase):
    def test_combine_and_thread(self):
        target = body()
        tool = body("b2", "Body2")
        combine = entry(feature("CombineFeature", "Combine1", bodies=[target], targetBody=target,
                                toolBodies=Coll([tool]), operation="CutFeatureOperation", isKeepToolBodies=True))
        modeled = entry(feature("ThreadFeature", "Thread1", isModeled=False))
        design = FakeDesign([combine, modeled], target)
        items = read_capture(design, target, fusion="", name="", up_axis="z")["items"]
        self.assertEqual(items[0]["data"], {
            "target": {"token": "b1", "name": "Body1"}, "tools": [{"token": "b2", "name": "Body2", "volume": 8000.0}],
            "operation": "cut", "keep_tools": True, "volume_before": None, "volume_after": 8000.0})
        self.assertEqual(items[1]["data"], {"modeled": False})


def cylinder_face(axis=(0, 0, 1), radius=4.0, span=(0.0, 10.0), outward=True):
    """A cylinder face about the line through (20, 10, 0) along `axis`, with its end vertices at `span` (mm)."""
    ends = [P(20 + axis[0] * t, 10 + axis[1] * t, axis[2] * t) for t in span]
    side = -1.0 if not outward else 1.0
    return Obj("fusion::BRepFace", geometry=Obj("core::Cylinder", origin=P(20, 10, 0), axis=Obj(x=axis[0], y=axis[1], z=axis[2]),
                                                 radius=radius * CM),
               pointOnFace=P(20 + radius, 10, 5), vertices=Coll([Obj(geometry=e) for e in ends]),
               evaluator=Obj(getNormalAtPoint=lambda p: (True, Obj(x=side, y=0.0, z=0.0))))


class ThreadReadTest(unittest.TestCase):
    def read(self, **kw):
        target = body()
        # Member names and units as the Fusion API has them: ThreadInfo lengths in cm and the angle in degrees,
        # isRightHanded on the feature, the faces in inputCylindricalFaces.
        info = Obj(threadType="ISO Metric profile", threadSize="8", threadDesignation="M8x1.25", threadClass="6g",
                   isInternal=False, threadAngle=60.0, threadPitch=0.125, majorDiameter=0.8, minorDiameter=0.646,
                   pitchDiameter=0.7)
        base = dict(isModeled=True, threadInfo=info, isRightHanded=True, isFullLength=True, threadLength=param(1.0),
                    threadOffset=param(0.0), inputCylindricalFaces=Coll([cylinder_face()]),
                    faces=Coll([cylinder_face(span=(0.0, 9.0))]))
        base.update(kw)
        thread = entry(feature("ThreadFeature", "Thread1", bodies=[target], **base))
        design = FakeDesign([thread], target)
        return read_capture(design, target, fusion="", name="", up_axis="z")["items"][0]["data"]

    def test_a_modeled_thread_gives_its_info_its_length_and_its_cylinder(self):
        data = self.read()
        self.assertEqual((data["thread_type"], data["designation"], data["internal"], data["right_hand"]),
                         ("ISO Metric profile", "M8x1.25", False, True))
        self.assertEqual((data["pitch"], data["major_diameter"], data["minor_diameter"], data["angle_deg"]),
                         (1.25, 8.0, 6.46, 60.0))
        self.assertEqual((data["full_length"], data["length"], data["offset"]), (True, 10.0, 0.0))
        (face,) = data["faces"]
        self.assertEqual((face["surface"], face["radius"], face["span"], face["outward"]), ("Cylinder", 4.0, [0.0, 10.0], True))
        self.assertEqual(data["made_span"], [0.0, 9.0])

    def test_an_inward_face_and_members_that_cannot_be_read_stay_null(self):
        data = self.read(threadInfo=Obj(threadType="ISO Metric profile"), isRightHanded=None,
                         inputCylindricalFaces=Coll([cylinder_face(outward=False)]))
        self.assertIsNone(data["pitch"])
        self.assertFalse(data["faces"][0]["outward"])

    def test_members_the_api_does_not_have_read_as_missing(self):
        old = Obj(threadType="ISO Metric profile", pitch=0.125, majorDiameter=0.8, minorDiameter=0.646)
        data = self.read(threadInfo=old, inputCylindricalFaces=None, inputFaces=Coll([cylinder_face()]))
        self.assertEqual((data["pitch"], data["faces"]), (None, []))

    def test_the_single_input_face_is_used_when_the_collection_is_missing(self):
        data = self.read(inputCylindricalFaces=None, inputCylindricalFace=cylinder_face())
        self.assertEqual(len(data["faces"]), 1)

    def test_a_face_that_is_not_a_cylinder_has_no_axis(self):
        plane = Obj("fusion::BRepFace", geometry=Obj("core::Plane"), pointOnFace=P(0, 0, 0))
        (face,) = self.read(inputCylindricalFaces=Coll([plane]))["faces"]
        self.assertNotIn("axis", face)


class HoleThreadReadTest(unittest.TestCase):
    def read(self, **kw):
        target = body()
        thread = Obj(isModeled=True, isFullLength=False, threadDepth=0.5, threadType="ANSI Unified Screw Threads",
                     threadPitch=0.1, majorDiameter=0.6, minorDiameter=0.5, isRightHanded=True)
        base = dict(holeType="SimpleHoleType", holeTapType="TappedHoleTapType", holeDiameter=param(0.6),
                    tipAngle=param(math.radians(118)), direction=Obj(x=0.0, y=0.0, z=-1.0), position=P(10, 10, 10),
                    holePositionDefinition=Obj("fusion::PointHolePositionDefinition"), thread=thread,
                    extentDefinition=Obj("fusion::DistanceExtentDefinition", distance=param(0.8)))
        base.update(kw)
        hole = entry(feature("HoleFeature", "Hole1", bodies=[target], **base))
        design = FakeDesign([hole], target)
        return read_capture(design, target, fusion="", name="", up_axis="z")["items"][0]["data"]

    def test_the_thread_of_a_tapped_hole_gives_its_numbers_and_depth(self):
        thread = self.read()["thread"]
        self.assertEqual((thread["thread_type"], thread["pitch"], thread["major_diameter"], thread["minor_diameter"]),
                         ("ANSI Unified Screw Threads", 1.0, 6.0, 5.0))
        self.assertEqual((thread["full_length"], thread["depth"], thread["right_hand"]), (False, 5.0, True))

    def test_a_plain_hole_has_no_thread_record(self):
        self.assertIsNone(self.read(holeTapType="SimpleHoleTapType")["thread"])

    def test_a_hole_up_to_a_face_names_the_face(self):
        face = Obj("fusion::BRepFace", geometry=Obj("core::Plane", origin=P(0, 0, 4), normal=Obj(x=0.0, y=0.0, z=1.0)),
                   pointOnFace=P(5, 5, 4), entityToken="f1")
        extent = self.read(extentDefinition=Obj("fusion::ToEntityExtentDefinition", entity=face))["extent"]
        self.assertEqual((extent["kind"], extent["entity_type"], extent["face_point"]), ("toEntity", "BRepFace", [5, 5, 4]))


class CombineVolumeTest(unittest.TestCase):
    def read(self, volume_at):
        target = body()
        combine = entry(feature("CombineFeature", "Combine1", bodies=[target], targetBody=target,
                                toolBodies=Coll([body("b2", "Body2")]), operation="CutFeatureOperation"))
        design = FakeDesign([combine], target, appears_at=0)
        type(target).volume = property(lambda self: volume_at(design.timeline.markerPosition))
        try:
            return read_capture(design, target, fusion="", name="", up_axis="z")["items"][0]["data"]
        finally:
            del type(target).volume

    def test_the_volume_of_the_target_is_read_around_the_combine(self):
        data = self.read(lambda marker: 8.0 if marker == 0 else 7.0)
        self.assertEqual((data["volume_before"], data["volume_after"]), (8000.0, 7000.0))

    def test_a_volume_that_cannot_be_read_is_null(self):
        def volume(marker):
            if marker == 0:
                raise RuntimeError("no volume")
            return 7.0
        data = self.read(volume)
        self.assertEqual((data["volume_before"], data["volume_after"]), (None, 7000.0))


class EdgeRecordTest(unittest.TestCase):
    def test_open_and_closed_edges(self):
        evaluator = Obj(getParameterExtents=lambda: (True, 0.0, 4.0),
                        getPointAtParameter=lambda t: (True, P(t, 0, 0)))
        open_edge = Obj(entityToken="e1", evaluator=evaluator, startVertex=Obj(entityToken="v1"),
                        endVertex=Obj(entityToken="v2"))
        closed_edge = Obj(entityToken="e2", evaluator=evaluator, startVertex=Obj(entityToken="v1"),
                          endVertex=Obj(entityToken="v1"))
        self.assertEqual(edge_record(open_edge), {"token": "e1", "closed": False, "points": [[2, 0, 0]]})
        self.assertEqual(edge_record(closed_edge)["points"], [[1, 0, 0], [3, 0, 0]])


if __name__ == "__main__":
    unittest.main()
