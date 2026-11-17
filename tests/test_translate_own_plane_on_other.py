"""A construction plane of the part built on an entity of another component (`built_on` holds `{ "foreign": true }`),
in a part that sits in an occurrence: the plane is the part's own, so a step that uses it is copied. The capture does
not say which sizes move the entity it is built on, so every ticked size may move the plane: the probe's measured
move decides, and without one each ticked size is marked. A plane of another component itself still leaves the step
out."""
import unittest

from tests import context  # noqa: F401
from tests.test_reach_follow import measured
from tests.test_translate_sized import table_of
from tests.translator_helpers import load_capture, steps_of, verdict_of

from lib.capture_model import gap_hints
from lib.sketch_values.motion import Motion
from lib.translator import translate

OFFSET = "ConstructionPlaneOffsetDefinition"
# Turned a quarter about Z and lifted: a copy that placed the plane by the occurrence would put it elsewhere.
TURNED = {"origin": [100, 50, 7], "x": [0, 1, 0], "y": [-1, 0, 0], "z": [0, 0, 1]}
# Read before the extrude through Extrude1, and read by no step.
TICKED = ["_CeramicMedium__Cube_width_mm", "wall_mm"]
ROOT_XY = {"foreign": True, "component": {"token": "cRoot", "name": "Filter box"}, "root": True}


def reaching(plane):
    """The Tray fixture, placed by `TURNED`, with Extrude2 reaching up to `plane` at z = 40 in the part's
    coordinates."""
    capture = load_capture("component_foreign_extent")
    for target in [capture["target"]] + capture["targets"]:
        target["placement"]["frame"] = dict(TURNED)
    capture["items"][3]["data"]["side_one"] = dict(plane, kind="toEntity", offset=0.0, chained=False,
                                                   plane={"point": [0, 0, 40], "normal": [0, 0, 1]})
    return capture


def own_plane(built_on):
    return {"entity_type": "ConstructionPlane", "token": "cp_lid_line", "definition": OFFSET, "built_on": built_on}


def marked(result):
    """The sizes a doubt reached: marked or fixed, and those no formula reads that the copy could not follow (`used`)."""
    return {f["name"] for f in result.loose + result.fixed} | {f["name"] for f in result.dropped if f["used"]}


class OwnPlaneOnAnotherComponentTest(unittest.TestCase):
    def test_the_extrude_is_copied_and_ends_at_the_plane_in_the_parts_coordinates(self):
        for base in (ROOT_XY, {"foreign": True}, own_plane([{"foreign": True}])):
            with self.subTest(base):
                result = translate(reaching(own_plane([base])))
                self.assertIsNone(result.refusal)
                self.assertEqual(verdict_of(result, 3)["verdict"], "translated")
                self.assertEqual(steps_of(result.recipe, "extrude")[1]["distance"], 40.0)

    def test_an_extrude_of_a_sketch_on_such_a_plane_is_copied(self):
        capture = load_capture("component_foreign_extent")
        data = capture["items"][3]["data"]
        data.update(side_one={"kind": "distance", "distance": 8.0, "taper_deg": 0.0}, end_offset=8.0)
        data["profiles"][0]["reference"] = dict(own_plane([ROOT_XY]), kind="constructionPlane")
        result = translate(capture, size_table=table_of(capture, TICKED))
        self.assertEqual(verdict_of(result, 3)["verdict"], "translated")
        self.assertEqual(marked(result), set(TICKED))

    def test_without_a_measured_move_every_ticked_size_is_marked(self):
        capture = reaching(own_plane([ROOT_XY]))
        result = translate(capture, size_table=table_of(capture, TICKED), motion=Motion.from_json({"values": {}}))
        self.assertEqual(verdict_of(result, 3)["verdict"], "translated")
        self.assertEqual(marked(result), set(TICKED))

    def test_a_measured_plane_that_stays_marks_no_size(self):
        capture = reaching(own_plane([ROOT_XY]))
        result = translate(capture, size_table=table_of(capture, TICKED), motion=measured("3.side_one", also={}))
        self.assertEqual(verdict_of(result, 3)["verdict"], "translated")
        self.assertEqual(marked(result), set())

    def test_a_plane_of_another_component_still_leaves_the_step_out(self):
        result = translate(reaching(dict(own_plane([]), foreign=True)))
        self.assertEqual(verdict_of(result, 3)["verdict"], "leftOut")
        self.assertEqual([g["hint"] for g in result.gaps], [gap_hints.HINTS[gap_hints.OTHER_COMPONENT]])


if __name__ == "__main__":
    unittest.main()
