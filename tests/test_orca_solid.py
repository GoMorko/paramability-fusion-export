"""The shapes the Orca copy keeps of what it builds (`orca_translate/solid.py`): lines through each kind of shape,
whether a tool meets a body, and the box of a body. Checked against shapes worked out by hand."""
import math
import unittest

from tests import context  # noqa: F401

from lib.orca_translate.solid import ADD, CUT, INTERSECT, HalfSpace, Moved, Prism, Solid, Tapered, Turned

XY = {"origin": [0, 0, 0], "x": [1, 0, 0], "y": [0, 1, 0], "z": [0, 0, 1]}
IDENTITY = ((1, 0, 0), (0, 1, 0), (0, 0, 1))


def square(lo, hi):
    (x0, y0), (x1, y1) = lo, hi
    return [{"kind": "line", "start": a, "end": b} for a, b in (
        ([x0, y0], [x1, y0]), ([x1, y0], [x1, y1]), ([x1, y1], [x0, y1]), ([x0, y1], [x0, y0]))]


def plate():
    """40 by 20 by 10 from the origin."""
    return Solid([(ADD, Prism(XY, [square((0, 0), (40, 20))], 0, 10))])


def assert_box(test, found, lo, hi, tol=1e-6):
    for got, want in zip(found["min"] + found["max"], list(lo) + list(hi)):
        test.assertAlmostEqual(got, want, delta=tol)


class ShapeTest(unittest.TestCase):
    def test_a_half_space_holds_the_side_its_normal_points_to(self):
        half = HalfSpace([25, 0, 0], [1, 0, 0])
        self.assertEqual(half.span([0, 0, 0], [1, 0, 0]), [(25.0, math.inf)])
        self.assertEqual(half.span([0, 0, 0], [-1, 0, 0]), [(-math.inf, -25.0)])
        self.assertEqual(half.span([30, 0, 0], [0, 1, 0]), [(-math.inf, math.inf)])
        self.assertEqual(half.span([20, 0, 0], [0, 1, 0]), [])

    def test_a_moved_shape_answers_where_it_was_moved(self):
        moved = Moved(Prism(XY, [square((0, 0), (10, 10))], 0, 10), IDENTITY, [100, 0, 0])
        self.assertEqual(moved.span([0, 5, 5], [1, 0, 0]), [(100.0, 110.0)])
        assert_box(self, moved.bounds(), (100, 0, 0), (110, 10, 10))

    def test_a_turned_outline_is_a_ring_about_its_axis(self):
        # The square 5 to 10 out from the Y axis, 20 high, turned a full circle: a tube.
        ring = Turned(XY, [square((5, 0), (10, 20))], [0, 0, 0], [0, 1, 0], 360)
        spans = ring.span([-20, 10, 0], [1, 0, 0])
        self.assertEqual(len(spans), 2)
        for (t0, t1), (a, b) in zip(spans, ((10, 15), (25, 30))):
            self.assertAlmostEqual(t0, a, delta=1e-6)
            self.assertAlmostEqual(t1, b, delta=1e-6)

    def test_a_turn_by_part_of_a_circle_keeps_to_its_angle(self):
        # A quarter turn by the right hand rule about +Y takes +X towards -Z.
        quarter = Turned(XY, [square((5, 0), (10, 20))], [0, 0, 0], [0, 1, 0], 90)
        self.assertNotEqual(quarter.span([-20, 10, -7.5], [1, 0, 0]), [])
        self.assertEqual(quarter.span([-20, 10, 7.5], [1, 0, 0]), [])
        assert_box(self, Solid([(ADD, quarter)]).box(), (0, 0, -10), (10, 20, 0), tol=0.02)

    def test_a_symmetric_turn_starts_half_its_angle_back(self):
        turned = Turned(XY, [square((5, 0), (10, 20))], [0, 0, 0], [0, 1, 0], 120, start=-60)
        assert_box(self, Solid([(ADD, turned)]).box(), (2.5, 0, -10 * math.sin(math.radians(60))),
                   (10, 20, 10 * math.sin(math.radians(60))), tol=0.02)


class SolidTest(unittest.TestCase):
    def test_the_box_of_a_plate_is_its_outline_and_height(self):
        assert_box(self, plate().box(), (0, 0, 0), (40, 20, 10))

    def test_cuts_and_intersects_change_the_box(self):
        part = plate()
        part.add(CUT, Prism(XY, [square((30, -5), (50, 25))], -math.inf, math.inf))
        part.add(INTERSECT, HalfSpace([0, 0, 2], [0, 0, 1]))
        assert_box(self, part.box(), (0, 0, 2), (30, 20, 10))

    def test_a_round_end_is_found_by_the_finer_lines(self):
        disc = Solid([(ADD, Prism(XY, [[{"kind": "circle", "center": [3.3, 1.7], "radius": 10}]], 0, 2))])
        assert_box(self, disc.box(), (-6.7, -8.3, 0), (13.3, 11.7, 2), tol=0.02)

    def test_moved_copies_of_a_body_add_to_the_box(self):
        part = plate()
        seed = Solid([(ADD, Prism(XY, [square((0, 0), (4, 4))], 10, 14))])
        part.add(ADD, Solid([(ADD, Moved(seed, IDENTITY, [k * 50.0, 0, 0])) for k in range(3)]))
        assert_box(self, part.box(), (0, 0, 0), (104, 20, 14))

    def test_a_body_with_no_end_has_no_box(self):
        self.assertIsNone(Solid([(ADD, HalfSpace([0, 0, 0], [0, 0, 1]))]).box())
        self.assertIsNone(Solid().box())

    def test_a_turned_tool_meets_the_body_only_where_it_reaches(self):
        part = plate()
        # Turned about -Y, the square swings from +X up into the plate; about +Y it swings below it.
        inside = Turned(XY, [square((0, 0), (5, 5))], [0, 0, 0], [0, -1, 0], 90)
        below = Turned(XY, [square((0, 0), (5, 5))], [0, 0, 0], [0, 1, 0], 90)
        far = Moved(inside, IDENTITY, [100, 0, 0])
        self.assertTrue(part.meets(inside))
        self.assertFalse(part.meets(far))
        self.assertFalse(part.meets(below))

    def test_a_thin_slot_in_a_tapered_block_is_found_and_a_cut_inside_it_meets_nothing(self):
        # A 60 by 20 block, 10 tall, its sides leaning in a little, with a slot 0.3 wide from x 30.4 up through y 20.
        corners = [(0, 0), (60, 0), (60, 20), (30.7, 20), (30.7, 5), (30.4, 5), (30.4, 20), (0, 20)]
        outline = [{"kind": "line", "start": list(a), "end": list(b)}
                   for a, b in zip(corners, corners[1:] + corners[:1])]
        block = Tapered(XY, outline, 0, 10, -0.001)
        spans = block.span([0, 10, 5], [1, 0, 0])
        self.assertEqual(len(spans), 2)
        self.assertAlmostEqual(spans[0][1], 30.395, delta=1e-6)
        self.assertAlmostEqual(spans[1][0], 30.705, delta=1e-6)
        # A cut across the slot, 0.2 long along x, square to the y z plane.
        across = {"origin": [0, 0, 0], "x": [0, 1, 0], "y": [0, 0, 1], "z": [1, 0, 0]}
        self.assertFalse(Solid([(ADD, block)]).meets(Prism(across, [square((8, 3), (12, 7))], 30.45, 30.65)))

    def test_a_copy_does_not_change_with_the_body_after_it(self):
        part = plate()
        before = part.copy()
        part.add(CUT, Prism(XY, [square((-1, -1), (41, 21))], 5, 20))
        assert_box(self, before.box(), (0, 0, 0), (40, 20, 10))
        assert_box(self, part.box(), (0, 0, 0), (40, 20, 5))

    def test_a_moved_body_carries_its_box(self):
        part = plate()
        part.moved(IDENTITY, [0, 0, 7])
        assert_box(self, part.box(), (0, 0, 7), (40, 20, 17))


if __name__ == "__main__":
    unittest.main()
