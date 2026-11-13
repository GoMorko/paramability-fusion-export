"""Sketch points kept at the first read and moved back after a solver flip (lib/fusion_reader/sketch_keep.py)."""
import unittest

from tests import context  # noqa: F401

from lib.fusion_reader.sketch_keep import SketchKeeper


class Point:
    count = 0

    def __init__(self, x, y, reference=False, fixed=False):
        self.at = [x, y, 0.0]
        self.isReference, self.isFixed = reference, fixed
        Point.count += 1
        self.entityToken = "pt%d" % Point.count

    @property
    def geometry(self):
        x, y, z = self.at
        return type("P", (), {"x": x, "y": y, "z": z})()

    def move(self, delta):
        self.at = [a + d for a, d in zip(self.at, delta)]
        return True


class Sketch:
    def __init__(self, points):
        self.sketchPoints = points
        self.deferred = []

    @property
    def isComputeDeferred(self):
        return bool(self.deferred and self.deferred[-1])

    @isComputeDeferred.setter
    def isComputeDeferred(self, value):
        self.deferred.append(value)


class Design:
    def __init__(self, sketches):
        self.sketches = sketches

    def findEntityByToken(self, token):
        if token in self.sketches:
            return [self.sketches[token]]
        return [p for sketch in self.sketches.values() for p in sketch.sketchPoints if p.entityToken == token]


class SketchKeeperTest(unittest.TestCase):
    def test_own_points_go_back_with_the_compute_deferred_and_projected_points_stay(self):
        own, projected = Point(1.0, 2.0), Point(5.0, 5.0, reference=True)
        sketch = Sketch([own, projected])
        keeper = SketchKeeper(Design({"sk": sketch}), ["sk", "gone"], vector=lambda *d: d)
        own.at, projected.at = [1.0, -2.0, 0.0], [5.0, 7.0, 0.0]
        self.assertEqual(keeper.put_back(), 1)
        self.assertEqual((own.at, projected.at), ([1.0, 2.0, 0.0], [5.0, 7.0, 0.0]))
        self.assertEqual(sketch.deferred, [True, False])
        self.assertEqual(keeper.put_back(), 0)
        self.assertEqual(sketch.deferred, [True, False])  # a sketch with every point in place is not touched

    def test_points_are_matched_by_token_so_a_point_that_is_gone_leaves_the_others_their_place(self):
        gone, own, other = Point(9.0, 9.0), Point(1.0, 2.0), Point(4.0, 4.0)
        sketch = Sketch([gone, own, other])
        keeper = SketchKeeper(Design({"sk": sketch}), ["sk"], vector=lambda *d: d)
        own.at, other.at = [3.0, 3.0, 0.0], [5.0, 4.0, 0.0]
        sketch.sketchPoints = [own, other, Point(0.0, 0.0)]
        self.assertEqual(keeper.put_back(), 2)
        self.assertEqual((own.at, other.at), ([1.0, 2.0, 0.0], [4.0, 4.0, 0.0]))


if __name__ == "__main__":
    unittest.main()
