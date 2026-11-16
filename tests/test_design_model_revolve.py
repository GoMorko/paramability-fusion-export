"""Which way a one sided revolve turned (`design_model/steps/revolve.py`) when its caps do not tell."""
import math
import unittest

from tests import context  # noqa: F401

from lib.design_model.steps import revolve as rv

# A sketch on the front face (y = 0) of a box 40 x 20 x 10, with the rectangle x 10..15, z 2..10 turned a quarter
# turn about the top front edge (along x, through z = 10).
FRAME = {"origin": [0.0, 0.0, 0.0], "x": [1.0, 0.0, 0.0], "y": [0.0, 0.0, 1.0], "z": [0.0, -1.0, 0.0]}
AXIS, AXIS_POINT = [1.0, 0.0, 0.0], [0.0, 0.0, 10.0]
# The way the outline moves at the sketch on a right hand turn about +x.
TURN = [0.0, 1.0, 0.0]


def line(a, b):
    return {"kind": "line", "start": list(a), "end": list(b)}


def box(low, high):
    return {"min": list(low), "max": list(high)}


def join(made, curves=None):
    curves = curves or [line((10, 10), (10, 2)), line((10, 2), (15, 2)), line((15, 2), (15, 10)),
                        line((15, 10), (10, 10))]
    return {"operation": "join", "profiles": [{"frame": FRAME, "loops": [{"outer": True, "curves": curves}]}],
            "start_face_normal": None, "end_face_normal": [0.0, 0.0, 1.0], "made_box": made}


BEFORE = box((0, 0, 0), (40, 20, 10))


def sense(data, bodies=(None, None)):
    return rv.sense(data, TURN, AXIS, 90.0, False, rv.outline_points(data), AXIS_POINT, bodies)


class JoinTurnTest(unittest.TestCase):
    def test_the_body_before_and_after_a_join_tell_the_turn_when_its_faces_merged(self):
        # The start cap merged into the front face, so the made faces span the whole box: they fit neither swept
        # box alone. With the box before, only the turn to -y (the left hand turn about +x) holds them.
        made = box((0, -8, 2), (40, 20, 10))
        after = box((0, -8, 0), (40, 20, 10))
        self.assertIsNone(sense(join(made)))
        self.assertEqual(sense(join(made), (BEFORE, after)), -1.0)

    def test_a_box_a_little_looser_than_the_shape_rules_out_no_turn(self):
        # Fusion's boxes of curved faces and bodies may stand out of the shape. Boxes 0.3 mm loose still give the
        # turn to -y; the turn to +y stays ruled out, as its box misses the 8 mm the part grew toward -y.
        made = box((-0.3, -8.3, 1.7), (40.3, 20.3, 10.3))
        after = box((-0.3, -8.3, -0.3), (40.3, 20.3, 10.3))
        self.assertEqual(sense(join(made), (BEFORE, after)), -1.0)
        # A part that grew by less than a loose box may stand out shows no turn.
        small = box((0, -0.4, 0), (40, 20, 10))
        self.assertIsNone(sense(join(small), (BEFORE, small)))

    def test_a_join_inside_the_part_does_not_tell_the_turn(self):
        inside = box((0, 0, 0), (40, 20, 10))
        self.assertIsNone(sense(join(inside), (box((0, -10, 0), (40, 30, 10)), box((0, -10, 0), (40, 30, 10)))))

    def test_the_body_after_must_fit_as_well_as_the_made_faces(self):
        # The made faces fit the turn to -y, but the body after reaches past what that turn and the box before hold.
        made = box((0, -8, 2), (40, 20, 10))
        self.assertIsNone(sense(join(made), (BEFORE, box((0, -8, 0), (40, 20, 30)))))

    def test_the_points_of_a_circle_lie_outside_it(self):
        # The box the points sweep must hold the box the circle sweeps, so no chord between them cuts into it.
        circle = {"kind": "circle", "center": [12.0, 4.0], "radius": 2.0}
        points = [(p[0], p[2]) for p in rv.outline_points(join(None, [circle]))]
        for a, b in zip(points, points[1:]):
            middle = ((a[0] + b[0]) / 2.0 - 12.0, (a[1] + b[1]) / 2.0 - 4.0)
            self.assertGreaterEqual(math.hypot(*middle), 2.0 - 1e-9)


if __name__ == "__main__":
    unittest.main()
