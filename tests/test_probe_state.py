"""`read_state`: sketches, points, lines, parameters and the target box read by token."""
import unittest

from tests import context  # noqa: F401
from tests.test_capture_reader import Coll, FakeDesign as CaptureDesign, Obj, P, body, entry, extrude, line
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

    def test_empty_request_reads_nothing(self):
        self.assertEqual(state(Design({})), {"sketches": {}, "points": {}, "lines": {}, "params": {}})


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
