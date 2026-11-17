"""Picks on the faces and edges of a revolve follow its outline, its axis and its turn (faces/revolve_placer.py)."""
import math
import unittest

from tests import context  # noqa: F401
from tests.translator_helpers import assert_schema_ok, steps_of

from lib.design_model.values import Quantity
from lib.params import size_table
from lib.params.expressions.evaluation import evaluate
from lib.sketch_values.motion import Affine, Motion
from lib.translator import translate
from lib.translator.faces.revolve_placer import RevolvePlacer, Turn
from lib.translator.faces.shells import Shell
from lib.translator.ranges.range_check import recipe_size_values

XZ = {"origin": [0, 0, 0], "x": [1, 0, 0], "y": [0, 0, 1], "z": [0, -1, 0]}
SIZES = ["Height", "Diameter"]


def _param(name, mm):
    return {"name": name, "expression": "%s mm" % mm, "value": mm / 10.0, "unit": "mm", "comment": "",
            "is_favorite": True, "value_type": "numeric", "dependency_parameters": [], "dependent_parameters": [],
            "kind": "length", "display_value": mm}


def _item(index, name, kind, data=None, bodies=True):
    return {"index": index, "name": name, "type": kind, "suppressed": False, "health": "ok", "message": "",
            "in_target_component": True, "bodies_after": [{"token": "t1", "name": "Body1"}] if bodies else [],
            "data": data or {}}


def _lines(points):
    return [{"kind": "line", "start": a, "end": b} for a, b in zip(points, points[1:] + points[:1])]


def _at(radius, height, degrees):
    """The model point at `radius` from the z axis, `degrees` about it from the x axis, at `height`."""
    turn = math.radians(degrees)
    return [radius * math.cos(turn), radius * math.sin(turn), height]


def cup(outline=None, angle=360.0, shell_point=None, rim_point=None):
    """A cup of Diameter 60 and Height 40: the outline (the rect from the axis to the side wall, by default) on the XZ
    plane turned about the z axis, a shell 2 mm thick open at the top, and a 1 mm round on the outer rim."""
    points = outline or [[0, 0], [30, 0], [30, 40], [0, 40]]
    profile = {"sketch": "Sketch1", "frame": XZ, "loops": [{"outer": True, "curves": _lines(points)}]}
    revolve = {"operation": "newBody", "profiles": [profile],
               "axis": {"point": [0, 0, 0], "dir": [0, 0, 1], "entity_type": "SketchLine", "sketch": "Sketch1"},
               "project_axis": False, "extent": {"kind": "angle", "angle_deg": angle, "symmetric": False},
               "participants": [{"token": "t1", "name": "Body1"}],
               "start_face_normal": None if angle >= 360 else [0, 1, 0]}
    shell = {"faces": [{"token": "f1", "point": shell_point or _at(10, 40, 45)}], "bodies_input": False,
             "inside": 2.0, "outside": 0.0, "shell_type": "sharp"}
    fillet = {"rolling_ball": True, "sets": [{"kind": "constant", "radius": 1.0, "continuity": "tangent",
                                              "input_kinds": ["edge"], "edges": [
                                                  {"token": "e0", "closed": True,
                                                   "points": [rim_point or _at(30, 40, 30)]}]}]}
    items = [_item(0, "Sketch1", "Sketch", bodies=False), _item(1, "Revolve1", "RevolveFeature", revolve),
             _item(2, "Shell1", "ShellFeature", shell), _item(3, "Fillet1", "FilletFeature", fillet)]
    return {"capture": 3, "fusion": "2.0.0", "design": "Test", "up_axis": "z",
            "target": {"token": "t1", "name": "Body1"}, "items": items,
            "parameters": {"user": [_param("Height", 40), _param("Diameter", 60)], "model": []}}


def rect_motion():
    """The probe saw the rect run from the axis to Diameter / 2 and from the floor to Height."""
    values = {"1/p0/l0/center.0": Affine(0.0, {"Diameter": 0.25}, "Sketch1"),
              "1/p0/l0/center.1": Affine(0.0, {"Height": 0.5}, "Sketch1"),
              "1/p0/l0/width": Affine(0.0, {"Diameter": 0.5}, "Sketch1"),
              "1/p0/l0/height": Affine(0.0, {"Height": 1.0}, "Sketch1")}
    return Motion(values=values, states=[{"values": {"Height": 45.0, "Diameter": 66.0}, "built": True}])


def run(capture, motion, ranges=None):
    params = capture["parameters"]
    table = size_table.build(params["user"], SIZES, params["model"], "mm", ranges=ranges)
    return table, translate(capture, size_table=table, motion=motion)


def at_sizes(table, point, **sizes):
    env = recipe_size_values(table, {table.size_name(k): v for k, v in sizes.items()})
    return [evaluate(c["expr"], env) if isinstance(c, dict) else c for c in point]


def marked(result):
    return {f["name"] for f in result.loose} | {f["name"] for f in result.fixed}


class CupTest(unittest.TestCase):
    def test_the_opening_and_the_rim_round_follow_both_sizes(self):
        table, result = run(cup(), rect_motion())
        self.assertIsNone(result.refusal)
        assert_schema_ok(self, result.recipe)
        self.assertEqual(marked(result), set())
        opening = steps_of(result.recipe, "shell")[0]["openFaces"]["near"][0]
        rim = steps_of(result.recipe, "round")[0]["edges"]["near"][0]
        for point, want in ((opening, _at(10 * 80 / 60, 50, 45)), (rim, _at(40, 50, 30))):
            for got, expected in zip(at_sizes(table, point, Height=50, Diameter=80), want):
                self.assertAlmostEqual(got, expected, places=6)


class PickedCurveTest(unittest.TestCase):
    def test_the_range_stops_where_the_picked_curve_shrinks_to_nothing(self):
        # A step in the side wall at 16 + Ledge (28 mm): the rim edge sits on the short wall above it.
        outline = [[0, 0], [30, 0], [30, 28], [26, 28], [26, 40], [0, 40]]
        capture = cup(outline=outline, rim_point=_at(26, 40, 30))
        capture["parameters"]["user"].append(_param("Ledge", 12))
        values = {"1/p0/l0/points.2.1": Affine(16.0, {"Ledge": 1.0}, "Sketch1"),
                  "1/p0/l0/points.3.1": Affine(16.0, {"Ledge": 1.0}, "Sketch1")}
        motion = Motion(values=values, states=[{"values": {"Ledge": 14.0}, "built": True}])
        params = capture["parameters"]
        table = size_table.build(params["user"], ["Ledge"], params["model"], "mm")
        result = translate(capture, size_table=table, motion=motion)
        self.assertIsNone(result.refusal)
        self.assertEqual(marked(result), set())
        # At Ledge 24 (the end of its range) the wall above the step has no height left.
        self.assertEqual(result.recipe["sizes"]["Ledge"]["max"], 23.99)



def placer(points, total=None, axis_moves=True):
    """The placer of `points` turned about the sketch y axis (the z axis), `total` degrees (a full turn when None).
    With `axis_moves` the axis is taken to move with sizes, so every face of the revolve moves."""
    profile = {"frame": XZ, "loops": [{"outer": True, "curves": _lines(points)}]}
    moving = [Affine(0.0), Affine(0.0)] if axis_moves else None
    turn = Turn(profile, None, None, [0, 0], moving, [0, 1], 0.0, total)
    return RevolvePlacer("revolve_1", "Revolve1", turn, [])


class RevolvePlacerTest(unittest.TestCase):
    CUP = [[0, 0], [30, 0], [30, 40], [0, 40]]

    def test_a_point_on_two_curves_away_from_their_corners_is_claimed(self):
        # A slot 0.0008 mm wide down from the top: a point between its walls lies on both.
        notch = [[0, 0], [30, 0], [30, 40], [10.0008, 40], [10.0008, 20], [10, 20], [10, 40], [0, 40]]
        found = placer(notch)
        for edge in (False, True):
            self.assertIsNone(found.place(_at(10.0004, 30, 60), edge))
        self.assertTrue(found.claims(_at(10.0004, 30, 60)))
        self.assertIsNotNone(found.place(_at(30, 20, 60), False))

    def test_an_end_face_of_a_partial_turn_is_claimed_not_placed(self):
        found = placer(self.CUP, Quantity(180.0, "Angle", ("Angle",)))
        for point in (_at(10, 20, 180), _at(30, 20, 180), _at(10, 20, 0)):
            self.assertIsNone(found.place(point, False))
            self.assertTrue(found.claims(point))
        self.assertIsNotNone(found.place(_at(30, 20, 90), False))
        self.assertIsNone(found.place(_at(30, 20, 270), False))
        self.assertFalse(found.claims(_at(30, 20, 270)))

    def test_an_edge_inside_a_face_that_stays_is_left_to_other_steps(self):
        # Only the angle follows a size: the side wall stays, so a cut through it still places its edges.
        found = placer(self.CUP, Quantity(180.0, "Angle", ("Angle",)), axis_moves=False)
        self.assertIsNone(found.place(_at(30, 20, 90), True))
        self.assertFalse(found.claims(_at(30, 20, 90)))
        self.assertTrue(found.claims(_at(10, 20, 180)))

    def test_a_shell_claims_the_faces_it_opens_and_its_inner_walls(self):
        revolve = placer(self.CUP)
        top = revolve.place(_at(10, 40, 45), False)
        shell = Shell(Quantity(2.0), [], [top], [revolve])
        for inside in (_at(29, 40, 30), _at(28, 40, 30), _at(28, 20, 30), _at(10, 2, 30)):
            self.assertTrue(shell.claims(inside), inside)
        for kept in (_at(30, 40, 30), _at(30, 20, 30), _at(10, 0, 30)):
            self.assertFalse(shell.claims(kept), kept)
        self.assertTrue(Shell(Quantity(2.0), [], [], [revolve], unknown_open=True).claims(_at(30, 20, 30)))


if __name__ == "__main__":
    unittest.main()
