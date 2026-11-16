"""A rectangular pattern whose direction comes from an axis or edge of another component."""
import json
import unittest

from tests import context  # noqa: F401
from tests.fakes import FakeOccurrence, apply_matrix, turn_z
from tests.test_capture_reader import Coll, Obj, P
from tests.test_capture_reader_component import Tray, param_value, read

from lib.params import geometry_links

LID_PLACE = turn_z(90, (110, 50, 32))


def line(origin, direction):
    return Obj("core::InfiniteLine3D", origin=P(*origin), direction=Obj(x=direction[0], y=direction[1], z=direction[2]))


class ForeignDirectionTest(unittest.TestCase):
    def setUp(self):
        self.tray = Tray()
        self.lid = Obj(entityToken="lid", name="Lid")
        self.occurrence = FakeOccurrence("Lid:1", LID_PLACE, component=self.lid)

    def axis(self, direction=(0, 0, 1)):
        """An axis of the lid and the proxy of it the pattern gets, seen through the lid's occurrence."""
        native = Obj("fusion::ConstructionAxis", entityToken="ax1", parentComponent=self.lid,
                     geometry=line((0, 0, 0), direction))
        shown = tuple(apply_matrix(LID_PLACE, direction)[i] - LID_PLACE[0][i] for i in range(3))
        return Obj("fusion::ConstructionAxis", entityToken="ax1:path", assemblyContext=self.occurrence,
                   nativeObject=native, geometry=line(apply_matrix(LID_PLACE, (0, 0, 0)), shown))

    def pattern(self, **kw):
        base = dict(inputEntities=Coll([]), patternEntityType="FeaturesPatternEntityType", quantityOne=param_value(3),
                    distanceOne=param_value(2.0), patternDistanceType="SpacingPatternDistanceType",
                    patternElements=Coll([]))
        base.update(kw)
        entry = self.tray.feature("RectangularPatternFeature", "Pattern1", **base)
        data = read(self.tray.design([self.tray.feature("Sketch", "S"), entry]), self.tray.proxy)["items"][1]["data"]
        json.dumps(data)
        return data

    def test_the_direction_is_brought_into_the_target_frame_and_its_reference_is_written(self):
        data = self.pattern(directionOneEntity=self.axis((1, 0, 0)))
        place = data["direction_one_place"]
        # The lid is turned 90 degrees, the tray too: the lid's x is the tray's x.
        self.assertEqual(data["direction_one"], [1.0, 0.0, 0.0])
        self.assertEqual((place["assembly"], place["dir"], "foreign" in place), (True, [1.0, 0.0, 0.0], False))
        self.assertEqual((place["ref"]["slot"], place["ref"]["token"], place["ref"]["component"]["token"],
                          place["ref"]["dir"]), ("direction_one", "ax1", "lid", [1.0, 0.0, 0.0]))
        self.assertEqual([r["key"] for r in geometry_links.item_refs({"index": 1, "data": data})],
                         ["1.direction_one"])

    def test_a_direction_that_cannot_be_read_marks_the_pattern_foreign(self):
        bare = Obj("fusion::ConstructionAxis", entityToken="ax2", assemblyContext=self.occurrence,
                   nativeObject=Obj("fusion::ConstructionAxis", entityToken="ax2", parentComponent=self.lid))
        data = self.pattern(directionOneEntity=bare)
        self.assertIsNone(data["direction_one"])
        self.assertTrue(data["direction_one_place"]["foreign"])

    def test_a_direction_whose_target_place_is_unknown_marks_the_pattern_foreign(self):
        self.tray.proxy.nativeObject = None
        data = self.pattern(directionOneEntity=self.axis())
        self.assertTrue(data["direction_one_place"]["foreign"])

    def test_an_own_direction_says_what_it_is_and_is_no_measured_reference(self):
        own = Obj("fusion::ConstructionAxis", entityToken="own", parentComponent=self.tray.component,
                  geometry=line((0, 0, 0), (0, 1, 0)))
        data = self.pattern(directionOneEntity=own)
        self.assertEqual(data["direction_one"], [0.0, 1.0, 0.0])
        place = data["direction_one_place"]
        self.assertEqual((place["own"], place["entity_type"], place["token"]), (True, "ConstructionAxis", "own"))
        self.assertFalse(place.get("assembly") or place.get("foreign"))
        self.assertEqual(geometry_links.item_refs({"index": 1, "data": data}), [])
        self.assertNotIn("direction_two_place", data)


if __name__ == "__main__":
    unittest.main()
