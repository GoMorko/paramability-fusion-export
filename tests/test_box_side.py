"""Which side of a plane a box lies on (lib/geometry/vec.py `box_side`), shared by mirrors, splits and drafts."""
import unittest

from tests import context  # noqa: F401

from lib.geometry.vec import box_side


def box(lo_z, hi_z):
    return {"min": [0.0, 0.0, lo_z], "max": [1.0, 1.0, hi_z]}


class BoxSideTest(unittest.TestCase):
    def test_a_box_on_one_side_across_or_in_the_plane(self):
        up = [0.0, 0.0, 1.0]
        self.assertEqual(box_side(box(0.0, 2.0), [0, 0, 0], up, 0.01), 1)
        self.assertEqual(box_side(box(-2.0, 0.005), [0, 0, 0], up, 0.01), -1)
        self.assertEqual(box_side(box(-1.0, 1.0), [0, 0, 0], up, 0.01), 0)
        self.assertEqual(box_side(box(0.0, 0.0), [0, 0, 0], up, 0.01), 0)
        self.assertEqual(box_side(box(0.0, 0.0), [0, 0, 0], up, 0.01, flat=1), 1)


if __name__ == "__main__":
    unittest.main()
