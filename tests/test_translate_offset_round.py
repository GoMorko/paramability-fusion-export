"""Offset faces on a whole round face (a pin or a bore): the radius changes by the distance (recipe version 17)."""
import copy
import unittest

from tests import context  # noqa: F401
from tests.test_translate_sized import TRAY, run
from tests.schema_check import check_recipe
from tests.translator_helpers import left_out, load_capture, steps_of

from lib.translator import translate
from lib.translator.finishes import offset_round

TOP = {"origin": [0, 0, 10], "x": [1, 0, 0], "y": [0, 1, 0], "z": [0, 0, 1]}
BOTTOM = {"origin": [0, 0, 0], "x": [1, 0, 0], "y": [0, -1, 0], "z": [0, 0, -1]}


def circle(radius, center=(0, 0)):
    return {"kind": "circle", "center": list(center), "radius": radius}


def annulus(frame, extra=()):
    """The end face of the tube (extrude_ring: outer radius 10, inner radius 6) with `extra` curves."""
    return {"frame": frame, "space": "sketch", "loops": [{"outer": True, "curves": [circle(10)]},
                                                          {"outer": False, "curves": [circle(6), *extra]}]}


def disk(frame):
    """The end face of a solid pin of radius 10."""
    return {"frame": frame, "space": "sketch", "loops": [{"outer": True, "curves": [circle(10)]}]}


def round_face(radius, outward, top=None, bottom=None, **fields):
    """A round face of the tube: radius 6 is the bore (outward False), radius 10 the outside (outward True)."""
    face = {"kind": "round", "token": "c", "origin": [0, 0, 0], "axis": [0, 0, 1], "radius": radius,
            "point": [radius, 0, 3], "outward": outward, "meets_offset": False,
            "ends": [{"kind": "circle", "center": [0, 0, 10], "normal": [0, 0, 1], "radius": radius,
                      "face": top or annulus(TOP)},
                     {"kind": "circle", "center": [0, 0, 0], "normal": [0, 0, -1], "radius": radius,
                      "face": bottom or annulus(BOTTOM)}]}
    face.update(fields)
    return face


def tube_with_offset(distance, face, after_radius, params=None):
    """The tube, then `face` offset by `distance`; Fusion left a cylinder of `after_radius` on the axis."""
    capture = load_capture("extrude_ring")
    data = {"distance": distance, "faces": [face], "faces_after": [],
            "rounds_after": [{"origin": [0, 0, 5], "axis": [0, 0, -1], "radius": after_radius}]}
    if params:
        data["params"] = params
    capture["items"].append({"index": 2, "name": "OffsetFaces1", "type": "OffsetFacesFeature", "suppressed": False,
                             "health": "ok", "message": "", "in_target_component": True,
                             "bodies_after": [{"token": "t1", "name": "Body1"}], "data": data})
    return capture


def sized(capture):
    capture["capture"] = 3
    capture["parameters"] = load_capture(TRAY)["parameters"]
    return capture


class RoundOffsetTest(unittest.TestCase):
    def test_a_bore_pulled_out_is_one_step_with_a_point_halfway_along_it(self):
        result = translate(tube_with_offset(-0.2, round_face(6, False), 6.2))
        # Version 17 gives offsetFaces no new field, so the shape of the step is checked against version 16.
        self.assertEqual(check_recipe(dict(result.recipe, version=16)), [])
        step = steps_of(result.recipe, "offsetFaces")[0]
        self.assertEqual((step["faces"], step["distance"]), ({"near": [[6.0, 0.0, 5.0]]}, -0.2))
        self.assertEqual(result.recipe["version"], offset_round.VERSION)

    def test_the_cylinder_fusion_left_decides_the_sign(self):
        grown = translate(tube_with_offset(0.5, round_face(10, True), 10.5))
        self.assertEqual(steps_of(grown.recipe, "offsetFaces")[0]["distance"], 0.5)
        refusal = left_out(translate(tube_with_offset(0.5, round_face(10, True), 9.5)))
        self.assertEqual(refusal["reason"], offset_round.NOT_MEASURED)

    def test_a_face_that_is_not_a_whole_ring_between_square_flat_ends_is_left_out(self):
        tilted = dict(TOP, z=[0, 0.6, 0.8], y=[0, 0.8, -0.6])
        cases = {
            "part of a circle": round_face(6, False, ends=[{"kind": "other", "type": "edges"}]),
            "a round at an end": round_face(6, False, top={"kind": "other", "type": "Torus"}),
            "a sloped end": round_face(6, False, top=annulus(tilted)),
        }
        for name, face in cases.items():
            with self.subTest(name):
                refusal = left_out(translate(tube_with_offset(-0.2, face, 6.2)))
                self.assertEqual(refusal["reason"], offset_round.NOT_WHOLE)

    def test_a_ring_that_would_reach_another_edge_of_an_end_face_is_left_out(self):
        cases = {
            "the bore reaches the outside": (round_face(6, False), -4.5, 10.5, offset_round.RUNS_INTO),
            "the outside shrinks into the bore": (round_face(10, True), -4.5, 5.5, offset_round.RUNS_INTO),
            "an edge already on the ring": (round_face(6, False, top=annulus(TOP, [circle(1, (6, 0))])), -0.2, 6.2,
                                             offset_round.RUNS_INTO),
            "a pin that closes": (round_face(10, True, top=disk(TOP), bottom=disk(BOTTOM)), -10.0, 0.0,
                                  offset_round.CLOSES),
        }
        for name, (face, distance, after, reason) in cases.items():
            with self.subTest(name):
                refusal = left_out(translate(tube_with_offset(distance, face, after)))
                self.assertEqual(refusal["reason"], reason)

    def test_a_round_face_that_cannot_be_read_or_meets_another_moved_face_is_left_out(self):
        cases = {offset_round.UNREADABLE: {"kind": "round", "token": "c"},
                 offset_round.MEETS: round_face(6, False, meets_offset=True)}
        for reason, face in cases.items():
            with self.subTest(reason):
                self.assertEqual(left_out(translate(tube_with_offset(-0.2, face, 6.2)))["reason"], reason)

    def test_a_distance_that_follows_a_size_stays_a_number_where_the_ring_could_reach_another_edge(self):
        # wall_mm is 2 mm and may go from 1 to 4 mm. The bore (radius 6) grown by wall_mm reaches the outside (radius
        # 10) at 4 mm; the outside shrunk by wall_mm reaches the bore at 4 mm.
        cases = (("-wall_mm / 10", round_face(6, False), True), ("-wall_mm", round_face(6, False), False),
                 ("-wall_mm", round_face(10, True), False))
        for expression, face, follows in cases:
            with self.subTest(expression=expression, radius=face["radius"]):
                distance = -0.2 if follows else -2.0
                after = face["radius"] + (distance if face["outward"] else -distance)
                params = {"distance": {"name": "d9", "expression": expression, "value": distance}}
                result, _ = run(sized(tube_with_offset(distance, face, after, params)))
                written = steps_of(result.recipe, "offsetFaces")[0]["distance"]
                self.assertEqual(written == {"expr": expression}, follows)
                kept_out = [f["name"] for f in result.dropped if f["used"]]
                self.assertEqual("wall_mm" in kept_out, not follows)

    def test_a_later_pick_on_the_moved_ring_follows_the_distance(self):
        params = {"distance": {"name": "d9", "expression": "-wall_mm / 10", "value": -0.2}}
        capture = sized(tube_with_offset(-0.2, round_face(6, False), 6.2, params))
        chamfer = copy.deepcopy(load_capture("chamfer_equal")["items"][2])
        chamfer["index"] = 3
        chamfer["data"]["sets"][0]["edges"] = [{"token": "e0", "closed": True, "points": [[0, 6.2, 10]]}]
        capture["items"].append(chamfer)
        result, _ = run(capture)
        self.assertEqual(result.fixed, [])
        near = steps_of(result.recipe, "bevel")[0]["edges"]["near"][0]
        self.assertEqual(near[0], 0.0)
        self.assertEqual(near[1], {"expr": "6 - (-wall_mm / 10)"})


if __name__ == "__main__":
    unittest.main()
