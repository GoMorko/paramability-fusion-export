import math
import unittest

from tests import context  # noqa: F401
from tests.translator_helpers import close

from lib.translator import loops
from lib.translator.result import Refusal


def line(a, b):
    return {"kind": "line", "start": list(a), "end": list(b)}


def arc(start, end, mid, center, radius):
    return {"kind": "arc", "start": list(start), "end": list(end), "mid": list(mid), "center": list(center), "radius": radius}


def area(points):
    return abs(sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(points, points[1:] + points[:1]))) / 2.0


class SingleCurveTest(unittest.TestCase):
    def test_circle(self):
        loop = loops.loop_of([{"kind": "circle", "center": [3, 4], "radius": 2.5}])
        self.assertEqual(loop, {"kind": "circle", "center": [3, 4], "radius": 2.5})

    def test_ellipse_takes_angle_from_major_dir(self):
        curve = {"kind": "ellipse", "center": [0, 0], "major_dir": [0, 1], "major_radius": 8, "minor_radius": 3}
        loop = loops.loop_of([curve])
        self.assertEqual((loop["kind"], loop["radiusX"], loop["radiusY"]), ("ellipse", 8, 3))
        self.assertTrue(close(loop["angleDeg"], 90.0, 1e-9))

    def test_axis_aligned_ellipse_has_no_angle(self):
        curve = {"kind": "ellipse", "center": [0, 0], "major_dir": [1, 0], "major_radius": 8, "minor_radius": 3}
        self.assertNotIn("angleDeg", loops.loop_of([curve]))

    def test_closed_single_arc_is_a_circle(self):
        loop = loops.loop_of([arc((5, 0), (5, 0), (-5, 0), (0, 0), 5)])
        self.assertEqual((loop["kind"], loop["radius"]), ("circle", 5))


class ChainTest(unittest.TestCase):
    def test_axis_aligned_rect_from_shuffled_lines(self):
        lines = [line((40, 20), (0, 20)), line((0, 0), (40, 0)), line((0, 20), (0, 0)), line((40, 0), (40, 20))]
        loop = loops.loop_of(lines)
        self.assertEqual(loop, {"kind": "rect", "center": [20, 10], "width": 40, "height": 20})

    def test_rect_starting_on_a_vertical_edge_keeps_width_along_x(self):
        lines = [line((0, 0), (0, 20)), line((0, 20), (40, 20)), line((40, 20), (40, 0)), line((40, 0), (0, 0))]
        loop = loops.loop_of(lines)
        self.assertEqual((loop["width"], loop["height"]), (40, 20))
        self.assertNotIn("angleDeg", loop)

    def test_turned_rect_width_is_along_the_turned_x(self):
        c, s = math.cos(math.radians(120)), math.sin(math.radians(120))
        # The first edge runs along 120 degrees; the width edge is the one at 30 degrees.
        a = (0.0, 0.0)
        b = (4 * c, 4 * s)
        d = (10 * math.cos(math.radians(30)), 10 * math.sin(math.radians(30)))
        e = (b[0] + d[0], b[1] + d[1])
        loop = loops.loop_of([line(a, b), line(b, e), line(e, d), line(d, a)])
        self.assertEqual(loop["kind"], "rect")
        self.assertTrue(close(loop["angleDeg"], 30.0, 1e-6))
        self.assertTrue(close((loop["width"], loop["height"]), (10.0, 4.0), 1e-6))

    def test_parallelogram_is_a_polygon(self):
        loop = loops.loop_of([line((0, 0), (10, 0)), line((10, 0), (13, 5)), line((13, 5), (3, 5)), line((3, 5), (0, 0))])
        self.assertEqual(loop["kind"], "polygon")

    def test_out_of_order_reversed_lines_chain_into_polygon(self):
        pts = [(0, 0), (30, 0), (30, 10), (10, 10), (10, 30), (0, 30)]
        edges = [line(pts[i], pts[(i + 1) % 6]) for i in range(6)]
        shuffled = [edges[3], line(*[edges[0]["end"], edges[0]["start"]]), edges[5], edges[1], line(*[edges[4]["end"], edges[4]["start"]]), edges[2]]
        loop = loops.loop_of(shuffled)
        self.assertEqual((loop["kind"], len(loop["points"])), ("polygon", 6))
        self.assertAlmostEqual(area(loop["points"]), 500.0)

    def test_chain_tolerates_small_gaps(self):
        lines = [line((0, 0), (10, 0)), line((10, 0.00005), (10, 10)), line((10, 10), (0, 10)), line((0, 10), (0, 0))]
        self.assertEqual(loops.loop_of(lines)["kind"], "rect")

    def test_slot_keeps_arc_mids(self):
        curves = [
            line((0, 5), (20, 5)),
            arc((20, 5), (20, -5), (25, 0), (20, 0), 5),
            line((20, -5), (0, -5)),
            arc((0, -5), (0, 5), (-5, 0), (0, 0), 5),
        ]
        loop = loops.loop_of(list(reversed(curves)))
        self.assertEqual(loop["kind"], "profile")
        kinds = [s["kind"] for s in loop["segments"]]
        self.assertEqual(sorted(kinds), ["arc", "arc", "line", "line"])
        throughs = {tuple(s["through"]) for s in loop["segments"] if s["kind"] == "arc"}
        self.assertEqual(throughs, {(25, 0), (-5, 0)})
        self.assertEqual(loop["segments"][-1]["to"], loop["start"])

    def test_reversed_arc_keeps_its_mid(self):
        curves = [line((0, 0), (10, 0)), arc((10, 10), (10, 0), (15, 5), (10, 5), 5), line((10, 10), (0, 10)), line((0, 10), (0, 0))]
        loop = loops.loop_of(curves)
        arcs = [s for s in loop["segments"] if s["kind"] == "arc"]
        self.assertEqual(arcs[0]["through"], [15, 5])
        self.assertEqual(arcs[0]["to"], [10, 10])


class RefusalTest(unittest.TestCase):
    def test_open_chain_names_the_sketch(self):
        refusal = loops.loop_of([line((0, 0), (10, 0)), line((10, 0), (10, 10)), line((10, 10), (0, 9))], "Sketch7")
        self.assertIsInstance(refusal, Refusal)
        self.assertEqual(refusal.reason, "An outline in Sketch7 is not closed.")

    def test_two_lines_do_not_close_an_area(self):
        self.assertIsInstance(loops.loop_of([line((0, 0), (10, 0)), line((10, 0), (0, 0))]), Refusal)

    def test_spline_curves_refuse(self):
        refusal = loops.loop_of([{"kind": "other", "type": "NurbsCurve3D", "start": [0, 0], "end": [0, 0], "samples": []}])
        self.assertEqual(refusal.reason, "Curved outlines of this kind are not copied yet.")

    def test_circle_mixed_with_lines_refuses(self):
        self.assertIsInstance(loops.loop_of([{"kind": "circle", "center": [0, 0], "radius": 1}, line((0, 0), (1, 0))]), Refusal)


class FlipYTest(unittest.TestCase):
    def test_flip_each_kind_and_back(self):
        samples = [
            {"kind": "circle", "center": [3, 4], "radius": 2},
            {"kind": "rect", "center": [3, 4], "width": 5, "height": 2, "angleDeg": 30},
            {"kind": "ellipse", "center": [3, 4], "radiusX": 5, "radiusY": 2, "angleDeg": 20},
            {"kind": "polygon", "points": [[0, 0], [4, 1], [2, 5]]},
            {"kind": "profile", "start": [0, 1], "segments": [{"kind": "arc", "through": [2, 3], "to": [4, 1]}, {"kind": "line", "to": [0, 1]}]},
        ]
        for loop in samples:
            flipped = loops.flip_y(loop)
            self.assertNotEqual(flipped, loop)
            self.assertEqual(loops.flip_y(flipped), loop)

    def test_flip_values(self):
        rect = loops.flip_y({"kind": "rect", "center": [3, 4], "width": 5, "height": 2, "angleDeg": 30})
        self.assertEqual((rect["center"], rect["angleDeg"]), ([3, -4], -30))
        profile = loops.flip_y({"kind": "profile", "start": [0, 1], "segments": [{"kind": "arc", "through": [2, 3], "to": [4, 1]}]})
        self.assertEqual((profile["start"], profile["segments"][0]["through"]), ([0, -1], [2, -3]))


if __name__ == "__main__":
    unittest.main()
