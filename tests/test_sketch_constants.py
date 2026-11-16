"""The entities of a sketch that no size moves (`sketch_solve.constants`)."""
import unittest

from tests import context  # noqa: F401

from lib.sketch_solve.constants import constants_of


class ConstantsTest(unittest.TestCase):
    @staticmethod
    def record():
        axis = {"id": 0, "kind": "line", "points": [1, 2], "implicit": True, "reference": {"source": "own"}}
        other = {"id": 1, "kind": "circle", "center": 3, "radius": 2.0, "reference": {"source": "other"}}
        edge = {"id": 2, "kind": "circle", "center": 4, "radius": 2.0, "reference": {"source": "own"}}
        points = [{"id": 0, "xy": [0, 0], "origin": True}, {"id": 1, "xy": [-5, 0]}, {"id": 2, "xy": [5, 0]},
                  {"id": 3, "xy": [9, 9]}, {"id": 4, "xy": [7, 7]}]
        return {"points": points, "curves": [axis, other, edge]}

    def test_an_origin_axis_and_a_projection_no_size_reaches_are_constants(self):
        found = constants_of(self.record(), linked=False)
        self.assertEqual(sorted(found), [("curve", 0), ("curve", 1), ("point", 1), ("point", 2), ("point", 3)])

    def test_a_projection_of_another_component_that_a_size_reaches_is_an_input(self):
        found = constants_of(self.record(), linked=True)
        self.assertEqual(sorted(found), [("curve", 0), ("point", 1), ("point", 2)])

    def test_a_projected_origin_of_the_sketchs_own_component_is_a_constant(self):
        def record(reference, component=None):
            points = [{"id": 0, "xy": [0, 0], "origin": True}, {"id": 1, "xy": [0, 0], "reference": reference}]
            return dict({"points": points, "curves": []}, **({"component": component} if component else {}))
        own = {"source": "own", "component": "cP", "origin": True}
        self.assertEqual(constants_of(record(own, {"token": "cP"}), linked=True), [("point", 1)])
        self.assertEqual(constants_of(record(own), linked=True), [("point", 1)])
        # The root origin projected into a sketch of the root that another component's step uses.
        root = {"source": "other", "component": "cR", "origin": True}
        self.assertEqual(constants_of(record(root, {"token": "cR"}), linked=True), [("point", 1)])
        # The origin of a third component moves with that component.
        self.assertEqual(constants_of(record(root, {"token": "cP"}), linked=True), [])
        self.assertEqual(constants_of(record({"source": "own", "component": "cP"}, {"token": "cP"}), linked=True), [])


if __name__ == "__main__":
    unittest.main()
