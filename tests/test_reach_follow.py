"""Extrudes that start from or reach to a face or construction plane of the part that no written step places
(lib/translator/reach_motion.py): the probe reads the face or plane at every try, the length follows its measured
move, and only a size that moves it in a way the copy cannot follow is marked."""
import copy
import unittest

from tests import context  # noqa: F401
from tests.probe_helpers import size
from tests.translator_helpers import load_capture, steps_of

from lib.export_plan.probe_flow import SizeProbe
from lib.params import size_table
from lib.probe import plan
from lib.sketch_values.motion import Motion
from lib.translator import translate

# Inside the plate, on no face of a written step: a face the slabs cannot place.
HIDDEN = [30, 15, 8]
OFFSET = "ConstructionPlaneOffsetDefinition"


def face_at(point, token="f9", body="t1"):
    return {"entity_type": "BRepFace", "token": token, "face_point": list(point), "surface": "Plane",
            "body": {"token": body, "name": "Body1"}}


def reaching(capture, index, target, at):
    """`capture` with the extrude at `index` reaching up to `target` at height `at`."""
    data = capture["items"][index]["data"]
    data["side_one"] = dict(target, kind="toEntity", offset=0.0, plane={"point": [0, 0, at], "normal": [0, 0, 1]})
    data["end_offset"] = at - data["profiles"][0]["frame"]["origin"][2]
    return capture


def post_on_hidden_face():
    """The sketch_offset_plane fixture with the post (Extrude3) reaching to a face at HIDDEN."""
    return reaching(load_capture("sketch_offset_plane"), 5, face_at(HIDDEN), HIDDEN[2])


def table_of(capture, ticked):
    params = capture["parameters"]
    return size_table.build(params["user"], ticked, params["model"], capture.get("design_units", "mm"))


def run(capture, ticked, motion):
    return translate(capture, size_table=table_of(capture, ticked), motion=motion)


def reasons(result):
    return {f["name"]: f["reason"] for f in result.loose + result.fixed}


def expr(value):
    return value["expr"] if isinstance(value, dict) else value


# The pocket sketch sits on Plane1, which lift_mm moves: the steps before the post read lift_mm too.
LIFTED = {"4/p0/plane": {"terms": {"lift_mm": 1}}}
FOLLOWS_PLATE = {"const": -10, "terms": {"plate_mm": 1}}


def measured(key, value=None, also=LIFTED, **extra):
    """A motion file in which the reference `key` was measured, with `value` as its offset when it moves."""
    item, _, slot = key.partition(".")
    values = dict(also, **({"%s/r/%s/offset" % (item, slot): value} if value is not None else {}))
    return Motion.from_json(dict({"values": values, "refs": {key: ""}}, **extra))


class FaceOfAnEarlierStepTest(unittest.TestCase):
    def test_the_length_follows_the_measured_face_and_a_size_that_does_not_move_it_is_not_marked(self):
        result = run(post_on_hidden_face(), ["plate_mm", "lift_mm"], measured("5.side_one", FOLLOWS_PLATE))
        post = steps_of(result.recipe, "extrude")[2]
        self.assertEqual(expr(post["distance"]), "plate_mm - 2")
        self.assertEqual(reasons(result), {})

    def test_only_the_size_the_copy_cannot_follow_is_marked(self):
        stuck = {"stuck": ["plate_mm"], "cause": "curve"}
        for label, motion in (("no formula", measured("5.side_one", stuck)),
                              ("not tried", measured("5.side_one", untried=["plate_mm"]))):
            with self.subTest(label):
                found = reasons(run(post_on_hidden_face(), ["plate_mm", "lift_mm"], motion))
                self.assertEqual(list(found), ["plate_mm"])

    def test_without_a_measurement_every_size_read_before_is_marked(self):
        found = reasons(run(post_on_hidden_face(), ["plate_mm", "lift_mm"], Motion.from_json({"values": LIFTED})))
        self.assertEqual(set(found), {"plate_mm", "lift_mm"})


class ReachPastItsStartTest(unittest.TestCase):
    """The face moves twice as fast as the plate: below a plate of 6 the post would reach past its own start."""

    STEEP = {"const": -20, "terms": {"plate_mm": 2}}

    def test_the_range_is_cut_where_the_length_stays_positive_and_the_size_is_not_marked(self):
        result = run(post_on_hidden_face(), ["plate_mm", "lift_mm"], measured("5.side_one", self.STEEP))
        self.assertEqual(expr(steps_of(result.recipe, "extrude")[2]["distance"]), "2 * plate_mm - 12")
        self.assertEqual(reasons(result), {})
        self.assertEqual([(c["name"], c["min"], c["max"]) for c in result.cuts], [("plate_mm", 6.01, 20.0)])

    def test_a_typed_range_keeps_the_mark(self):
        capture = post_on_hidden_face()
        params = capture["parameters"]
        table = size_table.build(params["user"], ["plate_mm", "lift_mm"], params["model"], "mm",
                                 ranges={"plate_mm": (2.0, 20.0)})
        result = translate(capture, size_table=table, motion=measured("5.side_one", self.STEEP))
        self.assertIn("reach past the face it starts from", reasons(result)["plate_mm"])
        self.assertEqual(result.cuts, [])


class PlaneOnAFaceTest(unittest.TestCase):
    def test_a_reach_to_a_plane_built_on_a_face_the_slabs_cannot_place_follows_the_measured_plane(self):
        plane = {"entity_type": "ConstructionPlane", "token": "cp9", "definition": OFFSET, "made_by": 4,
                 "built_on": [face_at(HIDDEN)]}
        capture = reaching(load_capture("sketch_offset_plane"), 5, plane, 7)
        result = run(capture, ["plate_mm", "lift_mm"], measured("5.side_one", FOLLOWS_PLATE))
        self.assertEqual(expr(steps_of(result.recipe, "extrude")[2]["distance"]), "plate_mm - 3")
        self.assertEqual(reasons(result), {})


def plane_on_hidden_face():
    return {"entity_type": "ConstructionPlane", "token": "cp9", "definition": OFFSET, "made_by": 4,
            "built_on": [face_at(HIDDEN)]}


class StartAndReachBothMoveTest(unittest.TestCase):
    """The post's sketch plane and the plane it reaches to both move: only what the length really does counts."""

    def two_sided(self):
        """Two sides: up to a plane on the hidden face (at 8), down to a plane that stays (at -20)."""
        capture = load_capture("sketch_offset_plane")
        capture["parameters"]["user"].append(dict(capture["parameters"]["user"][1], name="slot_mm"))
        data = reaching(capture, 5, plane_on_hidden_face(), 8)["items"][5]["data"]
        data["extent_type"] = "two"
        data["side_two"] = {"kind": "toEntity", "offset": 0.0, "plane": {"point": [0, 0, -20], "normal": [0, 0, 1]},
                            "entity_type": "ConstructionPlane", "token": "cp8", "definition": OFFSET,
                            "built_on": [{"origin": True}]}
        return capture

    def test_a_cut_keeps_the_ends_that_only_lengthen_the_reach_or_move_both_planes_alike(self):
        # The sketch plane moves with half the plate, the reach plane with the whole plate less the slot; lift_mm
        # moves both alike. Side one is 0.5 * plate_mm - slot_mm + 13 long: a short plate with a tall slot passes it.
        values = dict(LIFTED, **{"5/p0/plane": {"const": -13, "terms": {"plate_mm": 0.5, "lift_mm": 1}},
                                 "5/r/side_one/offset": {"const": -8, "terms": {"plate_mm": 1, "slot_mm": -1,
                                                                                "lift_mm": 1}}})
        result = run(self.two_sided(), ["plate_mm", "lift_mm", "slot_mm"],
                     Motion.from_json({"values": values, "refs": {"5.side_one": ""}}))
        self.assertEqual(reasons(result), {})
        sizes = result.recipe["sizes"]
        self.assertEqual((sizes["lift_mm"]["min"], sizes["lift_mm"]["max"]), (4.0, 16.0))
        self.assertEqual(sizes["plate_mm"]["max"], 20.0)
        self.assertGreater(sizes["slot_mm"]["max"], 12.0)
        self.assertGreater(sizes["plate_mm"]["min"], 5.0)
        self.assertGreater(0.5 * sizes["plate_mm"]["min"] - sizes["slot_mm"]["max"] + 13, 0)

    def test_a_start_on_a_moving_face_reaching_to_a_plane_that_moves_alike_keeps_its_length(self):
        capture = reaching(load_capture("sketch_offset_plane"), 5, plane_on_hidden_face(), 8)
        capture["items"][5]["data"]["start"] = dict(face_at([30, 15, 2], token="f8"), kind="fromEntity",
                                                    plane={"point": [0, 0, 2], "normal": [0, 0, 1]})
        moves = {"5/r/side_one/offset": FOLLOWS_PLATE, "5/r/start/offset": FOLLOWS_PLATE}
        motion = Motion.from_json({"values": dict(LIFTED, **moves), "refs": {"5.side_one": "", "5.start": ""}})
        result = run(capture, ["plate_mm", "lift_mm"], motion)
        post = steps_of(result.recipe, "extrude")[2]
        self.assertEqual((post["distance"], post["sketch"]["on"]["origin"][2]), (6.0, {"expr": "plate_mm - 8"}))
        self.assertEqual((reasons(result), result.cuts), ({}, []))


class FaceOfTheBodyFromAToolTest(unittest.TestCase):
    """The tool body of combine_cut_tool_two_steps_sized starts at z = 3 and reaches to a face of the plate."""

    def setUp(self):
        self.capture = reaching(load_capture("combine_cut_tool_two_steps_sized"), 3, face_at([30, 15, 9]), 9)

    def test_a_face_that_stays_marks_nothing_and_one_that_moves_is_followed(self):
        moving = {"const": -10, "terms": {"plate_h_mm": 1}}
        for label, value, length in (("stays", None, 6.0), ("moves", moving, "plate_h_mm - 4")):
            with self.subTest(label):
                result = run(copy.deepcopy(self.capture), ["plate_h_mm", "peg_len_mm"],
                             measured("3.side_one", value, also={}))
                self.assertEqual(reasons(result), {})
                tool = next(s for s in result.recipe["features"] if s["kind"] == "toolBody")
                self.assertEqual(expr(steps_of(tool, "extrude")[0]["distance"]), length)


def read_at(capture, plate=10.0):
    """The probe read of `post_on_hidden_face` with the plate `plate` thick: the hidden face lies 2 below its top."""
    sketches = {}
    for item in capture["items"]:
        for profile in (item.get("data") or {}).get("profiles") or []:
            sketches.setdefault(profile["sketch_token"], {"frame": copy.deepcopy(profile["frame"]), "profiles": []})[
                "profiles"].append({"loops": profile["loops"]})
    return {"sketches": sketches, "points": {}, "lines": {}, "box": {"min": [0, 0, 0], "max": [40, 20, plate]},
            "params": {"plate_mm": plate / 10, "d1": plate / 10, "lift_mm": 0.8, "d20": 0.8},
            "refs": {"5.side_one": {"point": [0, 0, plate - 2], "normal": [0, 0, 1]}}}


class ProbeTest(unittest.TestCase):
    def test_the_probe_tries_a_size_that_only_sets_an_earlier_length_and_the_copy_follows_the_face(self):
        capture = post_on_hidden_face()
        table = table_of(capture, ["plate_mm"])
        probe = SizeProbe.start(capture, table, lambda request: read_at(capture))
        self.assertTrue(probe.request["refs"]["5.side_one"]["own"])
        rows = probe.probe_rows([size(table, "plate_mm")])
        self.assertIn("plate_mm (near min)", [r["name"] for r in rows])
        probe.add_states([({"plate_mm": r["state"]["plate_mm"]}, {"name": r["name"]},
                           read_at(capture, r["state"]["plate_mm"])) for r in rows])
        probe.finish(read_at(capture), {})
        result = translate(capture, size_table=table, motion=probe.motion)
        self.assertEqual(expr(steps_of(result.recipe, "extrude")[2]["distance"]), "plate_mm - 2")
        self.assertEqual(reasons(result), {})

    def test_a_face_without_a_token_and_a_plane_on_an_origin_plane_are_not_read(self):
        capture = post_on_hidden_face()
        del capture["items"][5]["data"]["side_one"]["token"]
        self.assertEqual(plan.refs(capture), [])
        self.assertEqual(plan.refs(load_capture("sketch_offset_plane")), [])


if __name__ == "__main__":
    unittest.main()
