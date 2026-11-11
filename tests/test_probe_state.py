"""`read_state`: sketches, points, lines, parameters and the target box read by token."""
import unittest

from tests import context  # noqa: F401
from tests.fakes import FakeMatrix3D, FakeOccurrence, apply_matrix, turn_z
from tests.test_capture_reader import Coll, FakeDesign as CaptureDesign, Obj, P, body, entry, extrude, line
from tests.test_capture_reader_sweep import line3, quarter_arc, sketch_curve
from tests.test_capture_reader_tokens import SQUARE, profile, sketch
from lib.fusion_reader.probe_state import MAX_PROFILES, read_state
from lib.fusion_reader.read_geometry import ReadContext


class Params:
    def __init__(self, **values):
        self.values = values

    def itemByName(self, name):
        return Obj(value=self.values[name]) if name in self.values else None


class Design:
    def __init__(self, entities, user=None, model=None, target=None):
        self.entities = entities
        self.userParameters = Params(**(user or {}))
        self.rootComponent = Obj(entityToken="root", modelParameters=Params(**(model or {})), bRepBodies=Coll([]))
        self.target = target or body()

    def findEntityByToken(self, token):
        if token == self.target.entityToken:
            return [self.target]
        return self.entities.get(token, [])


def state(design, **request):
    target = design.target
    target.parentComponent = design.rootComponent
    return read_state(design, request, ReadContext(design, target))


class ReadStateTest(unittest.TestCase):
    def test_reads_sketch_point_line_and_parameters(self):
        sk = sketch()
        sk.profiles = Coll([profile(sk, SQUARE)])
        point = Obj("fusion::SketchPoint", worldGeometry=P(1, 2, 3))
        axis = Obj("fusion::SketchLine", worldGeometry=line((0, 0, 0), (0, 3, 0)))
        design = Design({"sk1": [sk], "p1": [point], "ln1": [axis]}, user={"width": 2.0}, model={"d1": 0.5})
        got = state(design, sketches=["sk1"], points=["p1"], lines=["ln1"], params=["width", "d1"], target=True)
        self.assertEqual(got["points"], {"p1": [1, 2, 3]})
        self.assertEqual(got["lines"], {"ln1": {"point": [0, 0, 0], "dir": [0, 1, 0]}})
        self.assertEqual(got["params"], {"width": 2.0, "d1": 0.5})
        self.assertEqual(got["box"], {"min": [0, 0, 0], "max": [40, 20, 10]})
        record = got["sketches"]["sk1"]
        self.assertEqual(record["frame"], {"origin": [0, 0, 0], "x": [1, 0, 0], "y": [0, 1, 0], "z": [0, 0, 1]})
        self.assertEqual([c["entity"] for c in record["profiles"][0]["loops"][0]["curves"]], ["c1", "c2", "c3", "c4"])

    def test_the_entity_without_an_assembly_context_wins_and_a_proxy_falls_back_to_its_native_object(self):
        native = Obj("fusion::SketchPoint", worldGeometry=P(1, 0, 0), assemblyContext=None)
        proxy = Obj("fusion::SketchPoint", worldGeometry=P(9, 9, 9), assemblyContext=Obj(), nativeObject=native)
        design = Design({"a": [proxy, native], "b": [proxy]})
        self.assertEqual(state(design, points=["a", "b"])["points"], {"a": [1, 0, 0], "b": [1, 0, 0]})

    def test_unreadable_parts_are_left_out(self):
        sk = sketch()
        sk.profiles = Coll([profile(sk, SQUARE)] * (MAX_PROFILES + 1))
        design = Design({"sk1": [sk], "bad": [Obj()]}, user={"width": 2.0})
        got = state(design, sketches=["sk1", "gone"], points=["bad", "gone"], lines=["bad"],
                    params=["width", "missing"])
        self.assertEqual((got["sketches"], got["points"], got["lines"]), ({}, {}, {}))
        self.assertEqual(got["params"], {"width": 2.0})

    def test_a_sketch_with_an_unreadable_profile_is_left_out(self):
        sk = sketch()
        sk.profiles = Coll([Obj()])
        self.assertEqual(state(Design({"sk1": [sk]}), sketches=["sk1"])["sketches"], {})

    def test_no_box_without_the_target_flag_or_target(self):
        self.assertNotIn("box", state(Design({}), sketches=[]))
        design = Design({})
        design.target.entityToken = "other"
        design.findEntityByToken = lambda token: []
        design.rootComponent.bRepBodies = Coll([])
        self.assertNotIn("box", state(design, target=True))


class PathCurvesTest(unittest.TestCase):
    def setUp(self):
        self.sk = sketch()
        self.sk.sketchCurves = Coll([sketch_curve(line3((0, 0, 0), (0, 50, 0)), self.sk, "c1"),
                                     sketch_curve(quarter_arc(), self.sk, "c2", "SketchArc"),
                                     sketch_curve(line3((0, 0, 0), (0, 50, 5)), self.sk, "off"),
                                     sketch_curve(line3((1, 1, 0), (2, 2, 0)), self.sk, "other")])
        self.sk.profiles = Coll([])
        self.design = Design({"sk1": [self.sk]})

    def test_the_asked_curves_are_read_in_the_sketch_plane_and_the_rest_is_left_out(self):
        record = state(self.design, sketches=["sk1"], curves={"sk1": ["c1", "c2", "off"]})["sketches"]["sk1"]
        self.assertEqual(record["curves"]["c1"], {"kind": "line", "start": [0, 0], "end": [0, 50]})
        self.assertEqual(record["curves"]["c2"]["kind"], "arc")
        self.assertEqual(sorted(record["curves"]), ["c1", "c2"])

    def test_a_sketch_asked_for_without_curves_has_none(self):
        self.assertNotIn("curves", state(self.design, sketches=["sk1"])["sketches"]["sk1"])


class ProbeAgreementTest(unittest.TestCase):
    def test_the_first_state_matches_the_capture_for_the_probe(self):
        from lib.fusion_reader.capture import read_capture
        from lib.probe import match, plan
        sk = sketch()
        sk.profiles = Coll([profile(sk, SQUARE)])
        target = body()
        timeline = CaptureDesign([entry((Obj("fusion::Sketch", name="Sketch1", bodies=Coll([]),
                                           parentComponent=Obj(entityToken="root")), "Sketch1")),
                                  extrude(profile(sk, SQUARE), target=target)], target)
        capture = read_capture(timeline, target, fusion="", name="", up_axis="z")
        found = plan.scan(capture)
        self.assertEqual(found.covered, {"sk1": "Sketch1"})
        design = Design({"sk1": [sk]}, target=target)
        first = state(design, sketches=["sk1"])
        self.assertEqual(match.readable(found, first), {"sk1"})


class BorrowedSketchTest(unittest.TestCase):
    """A sketch of another component is read native and placed into the target's coordinates at each state."""

    def setUp(self):
        self.matrix, self.apply = FakeMatrix3D, apply_matrix
        self.lid = Obj(entityToken="lid", name="Lid")
        self.place = turn_z(0, (5, 0, 20))
        self.occurrence = FakeOccurrence("Lid:1", self.place, component=self.lid)
        points = [(0, 0, 0), (10, 0, 0), (0, 10, 0)]
        self.sketch = sketch("skL")
        self.sketch.parentComponent = self.lid
        self.sketch.sketchPoints = Coll([
            Obj(worldGeometry=P(*p), createForAssemblyContext=lambda occ, p=p: Obj(
                worldGeometry=P(*self.apply(self.occurrence_place(), p)))) for p in points])
        self.sketch.profiles = Coll([profile(self.sketch, SQUARE)])
        self.design = Design({"skL": [self.sketch]})
        self.design.rootComponent.allOccurrencesByComponent = lambda c: Coll([self.occurrence])

    def occurrence_place(self):
        return self.place

    def move_lid(self, place):
        self.place = place
        self.occurrence.transform2 = self.matrix(place)

    def read(self, **request):
        return state(self.design, sketches=["skL"], **request)

    def test_the_frame_comes_in_the_targets_coordinates_with_the_native_frame_and_place(self):
        record = self.read(borrowed={"skL": {"path": "Lid:1"}})["sketches"]["skL"]
        self.assertEqual(record["frame"]["origin"], [5, 0, 20])
        self.assertEqual(record["native_frame"]["origin"], [0, 0, 0])
        self.assertEqual(record["placement"]["path"], "Lid:1")
        self.assertEqual(len(record["profiles"][0]["loops"][0]["curves"]), 4)

    def test_the_place_is_read_again_at_each_state(self):
        self.read()
        self.move_lid(turn_z(0, (12, 0, 20)))
        self.assertEqual(self.read()["sketches"]["skL"]["frame"]["origin"], [12, 0, 20])

    def test_without_a_path_a_component_with_one_occurrence_is_used(self):
        self.assertIn("skL", self.read()["sketches"])

    def test_a_sketch_of_a_tool_body_is_read_in_its_own_frame_without_a_place(self):
        record = self.read(native=["skL"])["sketches"]["skL"]
        self.assertEqual(record["frame"]["origin"], [0, 0, 0])
        self.assertNotIn("native_frame", record)
        self.design.rootComponent.allOccurrencesByComponent = lambda c: Coll([])
        self.assertIn("skL", self.read(native=["skL"])["sketches"])

    def test_a_path_that_matches_no_occurrence_leaves_the_sketch_out_with_a_reason(self):
        self.design.rootComponent.allOccurrencesByComponent = lambda c: Coll([self.occurrence, self.occurrence])
        got = self.read(borrowed={"skL": {"path": "Lid:2"}})
        self.assertEqual(got["sketches"], {})
        self.assertIn("place", got["unread"]["skL"])

    def test_a_place_that_does_not_match_the_points_leaves_the_sketch_out(self):
        self.occurrence.transform2 = self.matrix(turn_z(0, (99, 0, 0)))
        got = self.read(borrowed={"skL": {"path": "Lid:1"}})
        self.assertEqual(got["sketches"], {})
        self.assertIn("does not match", got["unread"]["skL"])


class BorrowedAgreementTest(unittest.TestCase):
    def test_the_first_state_of_a_borrowed_sketch_matches_the_capture_for_the_probe(self):
        from tests.test_capture_reader_component import Tray, read
        from lib.export_plan.probe_flow import borrowed_sketches, probe_view
        from lib.probe import match, plan
        tray = Tray()
        lid = Obj(entityToken="lid", name="Lid")
        place = turn_z(90, (110, 50, 32))
        occurrence = FakeOccurrence("Lid:1", place, component=lid)
        sk = sketch("skL")
        sk.name = "Rim"
        sk.parentComponent = lid
        sk.sketchDimensions = Coll([])
        sk.sketchPoints = Coll([Obj(worldGeometry=P(*p), createForAssemblyContext=lambda occ, p=p: Obj(
            worldGeometry=P(*apply_matrix(place, p)))) for p in [(0, 0, 0), (10, 0, 0), (0, 10, 0)]])
        native = profile(sk, SQUARE)
        sk.profiles = Coll([native])
        proxy = Obj("fusion::Profile", assemblyContext=occurrence, nativeObject=native, parentSketch=Obj(parentComponent=lid))
        ext = tray.extrude()
        ext[0].profile = proxy
        design = tray.design([tray.feature("Sketch", "Sketch1"), ext])
        design.rootComponent.allOccurrencesByComponent = lambda c: Coll([occurrence if c is lid else tray.occurrence])
        capture = read(design, tray.proxy)
        found = plan.scan(probe_view(capture))
        self.assertEqual(found.covered, {"skL": "Rim of Lid"})
        design.findEntityByToken = lambda token: [sk] if token == "skL" else []
        ctx = ReadContext(design, tray.proxy)
        first = read_state(design, {"sketches": ["skL"], "borrowed": borrowed_sketches(capture)}, ctx)
        self.assertEqual(match.readable(found, first), {"skL"})
