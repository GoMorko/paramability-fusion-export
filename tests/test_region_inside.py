"""Whether an outline lies in a face region (lib/geometry/region_inside.py)."""
import unittest

from tests import context  # noqa: F401

from lib.geometry.region_inside import inside

TOL = 1e-3


def rect(x0, y0, x1, y1):
    corners = [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]
    return {"curves": [{"kind": "line", "start": a, "end": b} for a, b in zip(corners, corners[1:] + corners[:1])]}


def circle(x, y, r):
    return {"curves": [{"kind": "circle", "center": [x, y], "radius": r}]}


def half_disc(r):
    """The upper half of a disc at the origin: an arc and its chord."""
    return {"curves": [{"kind": "arc", "center": [0.0, 0.0], "radius": r, "start": [r, 0.0], "mid": [0.0, r],
                        "end": [-r, 0.0]},
                       {"kind": "line", "start": [-r, 0.0], "end": [r, 0.0]}]}


class InsideTest(unittest.TestCase):
    def test_an_outline_that_fills_a_hole_of_the_face_is_not_inside(self):
        # Every edge of the outline lies on the edge of the hole: only the side of the face it lies on tells.
        post = [rect(27.0, 17.0, 33.0, 23.0)]
        self.assertTrue(inside(post, [rect(0.0, 0.0, 60.0, 40.0)], TOL))
        self.assertTrue(inside(post, [rect(27.0, 17.0, 33.0, 23.0)], TOL))
        self.assertFalse(inside(post, [rect(0.0, 0.0, 60.0, 40.0), rect(27.0, 17.0, 33.0, 23.0)], TOL))

    def test_arcs_that_touch_count_as_inside_and_arcs_that_cross_do_not(self):
        self.assertTrue(inside([circle(0.0, 0.0, 3.0)], [circle(0.0, 0.0, 3.0)], TOL))
        self.assertTrue(inside([circle(0.0, 0.0, 3.0)], [circle(0.0, 0.0, 3.0005)], TOL))
        self.assertFalse(inside([circle(0.0, 0.0, 3.0)], [circle(0.01, 0.0, 3.0)], TOL))
        self.assertTrue(inside([half_disc(3.0)], [circle(0.0, 0.0, 3.0)], TOL))
        self.assertFalse(inside([circle(0.0, 0.0, 3.0)], [half_disc(3.0)], TOL))
        # A square in a circle: its corners at 4.24 mm from the centre.
        self.assertTrue(inside([rect(-3.0, -3.0, 3.0, 3.0)], [circle(0.0, 0.0, 4.3)], TOL))
        self.assertFalse(inside([rect(-3.0, -3.0, 3.0, 3.0)], [circle(0.0, 0.0, 4.2)], TOL))


if __name__ == "__main__":
    unittest.main()
