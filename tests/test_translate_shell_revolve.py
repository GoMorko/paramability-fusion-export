"""Picks on the inner walls a shell leaves on a revolve follow the sizes and the thickness (faces/revolve_walls.py)."""
import math
import unittest

from tests import context  # noqa: F401
from tests.test_translate_revolve_picks import at_sizes, cup, marked, placer, rect_motion, size_param, turned_point
from tests.translator_helpers import assert_schema_ok, steps_of

from lib.design_model.values import Quantity
from lib.params import size_table
from lib.sketch_values.motion import Affine, Motion
from lib.translator import translate
from lib.translator.faces.shells import Shell

SIZES = ["Height", "Diameter", "Wall"]


def shelled_cup(edges=(), outline=None, wall=2.0):
    """The cup of Diameter 60 and Height 40, shelled Wall (`wall` mm) thick and open at the top, then a 1 mm round on
    the edges at the points `edges`."""
    capture = cup(outline=outline)
    capture["parameters"]["user"].append(size_param("Wall", wall))
    shell = capture["items"][2]["data"]
    shell["inside"] = wall
    shell["params"] = {"inside": {"name": "Wall", "expression": "Wall", "value": wall}}
    fillet = capture["items"][3]["data"]
    fillet["sets"][0]["edges"] = [{"token": "e%d" % n, "closed": True, "points": [p]} for n, p in enumerate(edges)]
    return capture


def face_chamfer(index, face, edge):
    """A 0.5 mm chamfer on the face at the point `face`, one of whose edges passes through `edge`."""
    data = {"corner_type": "chamfer", "sets": [{
        "kind": "equal", "distance": 0.5, "input_kinds": ["face"], "tangent_chain": True,
        "edges": [{"token": "c0", "closed": True, "points": [edge]}], "faces": [{"token": "f0", "point": face}]}]}
    return {"index": index, "name": "Chamfer1", "type": "ChamferFeature", "suppressed": False, "health": "ok",
            "message": "", "in_target_component": True, "bodies_after": [{"token": "t1", "name": "Body1"}],
            "data": data}


def run(capture, motion, sizes=SIZES, ranges=None):
    params = capture["parameters"]
    table = size_table.build(params["user"], sizes, params["model"], "mm", ranges=ranges)
    return table, translate(capture, size_table=table, motion=motion)


def picked(recipe, kind):
    selector = steps_of(recipe, kind)[0]["edges"]
    return (selector.get("faceEdges") or selector)["near"]


class InnerWallTest(unittest.TestCase):
    def assert_at(self, table, point, want, **sizes):
        for got, expected in zip(at_sizes(table, point, **sizes), want):
            self.assertAlmostEqual(got, expected, places=6)

    def test_the_inner_rim_and_the_inner_bottom_edge_follow_the_sizes_and_the_wall(self):
        table, result = run(shelled_cup(edges=[turned_point(28, 40, 30), turned_point(28, 2, 60)]), rect_motion())
        self.assertIsNone(result.refusal)
        assert_schema_ok(self, result.recipe)
        self.assertEqual(marked(result), set())
        rim, bottom = picked(result.recipe, "round")
        self.assert_at(table, rim, turned_point(37, 50, 30), Height=50, Diameter=80, Wall=3)
        self.assert_at(table, bottom, turned_point(37, 3, 60), Height=50, Diameter=80, Wall=3)

    def test_a_face_picked_on_the_inner_floor_follows_the_sizes(self):
        capture = shelled_cup(edges=[turned_point(28, 40, 30)])
        capture["items"].append(face_chamfer(4, turned_point(10, 2, 0), turned_point(28, 2, 0)))
        table, result = run(capture, rect_motion())
        self.assertIsNone(result.refusal)
        self.assertEqual(marked(result), set())
        floor = picked(result.recipe, "bevel")[0]
        x, y, z = at_sizes(table, floor, Height=50, Diameter=80, Wall=3)
        self.assertAlmostEqual(z, 3.0, places=6)
        self.assertTrue(0.0 <= math.hypot(x, y) < 37.0)

    def test_the_range_of_the_wall_stops_before_the_inner_floor_shrinks_to_nothing(self):
        # A wall 20 mm thick in a cup 30 mm from the axis to its side: at 30 mm the floor inside has no width left.
        capture = shelled_cup(edges=[turned_point(10, 20, 60)], wall=20)
        _, result = run(capture, rect_motion(), sizes=["Wall"])
        self.assertIsNone(result.refusal)
        self.assertEqual(marked(result), set())
        self.assertGreater(result.recipe["sizes"]["Wall"]["max"], 29.0)
        self.assertLess(result.recipe["sizes"]["Wall"]["max"], 30.0)

    def test_a_pick_on_an_inner_wall_whose_outer_side_a_size_turns_is_marked(self):
        # The side leans out by Flare at the top: the inner rim sits where the wall meets the open top.
        outline = [[0, 0], [30, 0], [32, 40], [0, 40]]
        lean = math.hypot(2, 40)
        capture = shelled_cup(edges=[turned_point(32 - 2 * lean / 40, 40, 30)], outline=outline)
        capture["parameters"]["user"].append(size_param("Flare", 2))
        values = {"1/p0/l0/points.2.0": Affine(30.0, {"Flare": 1.0}, "Sketch1")}
        motion = Motion(values=values, states=[{"values": {"Flare": 3.0}, "built": True}])
        _, result = run(capture, motion, sizes=["Flare"])
        self.assertIsNone(result.refusal)
        self.assertIn("Flare", marked(result))
        _, steady = run(capture, Motion(values={"1/p0/l0/points.2.0": Affine(32.0, {}, "Sketch1")},
                                        states=[{"values": {"Wall": 3.0}, "built": True}]), sizes=["Wall"])
        self.assertEqual(marked(steady), set())


CUP = [[0, 0], [30, 0], [30, 40], [0, 40]]


def shell_on(revolves, opened_at, **options):
    """A 2 mm shell of `revolves` (the first one is shelled open at the point `opened_at`)."""
    top = revolves[0].place(opened_at, False)
    return Shell(Quantity(2.0), [], [top], revolves, before=revolves, **options)


class DoubtfulWallTest(unittest.TestCase):
    RIM, BOTTOM = turned_point(28, 40, 30), turned_point(28, 2, 60)

    def test_a_cup_places_its_inner_walls(self):
        shell = shell_on([placer(CUP)], turned_point(10, 40, 45))
        for point in (self.RIM, self.BOTTOM):
            self.assertIsNotNone(shell.place(point, True))

    def test_a_second_outline_that_covers_the_wall_leaves_its_picks_to_be_marked(self):
        ring = placer([[30, 0], [35, 0], [35, 20], [30, 20]])
        shell = shell_on([placer(CUP), ring], turned_point(10, 40, 45))
        self.assertIsNone(shell.place(self.BOTTOM, True))
        self.assertTrue(shell.claims(self.BOTTOM))

    def test_a_face_opened_on_no_step_leaves_the_picks_to_be_marked(self):
        revolve = placer(CUP)
        shell = Shell(Quantity(2.0), [], [], [revolve], unknown_open=True, before=[revolve])
        self.assertIsNone(shell.place(self.RIM, True))
        self.assertTrue(shell.claims(self.RIM))

    def test_a_partial_turn_leaves_its_inner_walls_to_be_marked(self):
        shell = shell_on([placer(CUP, Quantity(270.0))], turned_point(10, 40, 45))
        self.assertIsNone(shell.place(self.RIM, True))
        self.assertTrue(shell.claims(self.RIM))

    def test_a_point_closer_than_the_wall_to_a_kept_face_is_not_placed(self):
        # A flange 2 mm thick: its top face lies the wall's thickness above its bottom face.
        flange = [[0, 0], [30, 0], [30, 2], [40, 2], [40, 4], [30, 4], [30, 40], [0, 40]]
        shell = shell_on([placer(flange)], turned_point(10, 40, 45))
        self.assertIsNone(shell.place(turned_point(35, 4, 30), False))


if __name__ == "__main__":
    unittest.main()
