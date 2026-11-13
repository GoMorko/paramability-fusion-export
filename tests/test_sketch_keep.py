"""Sketch points kept at the first read and moved back after a solver flip (lib/fusion_reader/sketch_keep.py)."""
import unittest

from tests import context  # noqa: F401

from lib.fusion_reader.sketch_keep import SketchKeeper


class Point:
    def __init__(self, x, y, reference=False, fixed=False):
        self.at = [x, y, 0.0]
        self.isReference, self.isFixed = reference, fixed

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
        return [self.sketches[token]] if token in self.sketches else []


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

    def test_only_the_named_sketches_with_points_out_of_place_are_touched(self):
        moved, still, other = Point(1.0, 2.0), Point(0.0, 0.0), Point(4.0, 4.0)
        first, second, third = Sketch([moved]), Sketch([still]), Sketch([other])
        keeper = SketchKeeper(Design({"a": first, "b": second, "c": third}), ["a", "b", "c"], vector=lambda *d: d)
        moved.at, other.at = [1.0, 3.0, 0.0], [5.0, 5.0, 0.0]
        self.assertEqual(keeper.put_back(["a", "b"]), 1)
        self.assertEqual((moved.at, other.at), ([1.0, 2.0, 0.0], [5.0, 5.0, 0.0]))
        self.assertEqual((first.deferred, second.deferred, third.deferred), ([True, False], [], []))

    def test_a_sketch_whose_points_changed_is_left_alone(self):
        own = Point(1.0, 2.0)
        sketch = Sketch([own])
        keeper = SketchKeeper(Design({"sk": sketch}), ["sk"], vector=lambda *d: d)
        own.at = [3.0, 3.0, 0.0]
        sketch.sketchPoints = [own, Point(0.0, 0.0)]
        self.assertEqual(keeper.put_back(), 0)
        self.assertEqual(own.at, [3.0, 3.0, 0.0])


if __name__ == "__main__":
    unittest.main()
