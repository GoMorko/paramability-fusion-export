"""Revolves in the Orca copy (`orca_translate/revolve.py`): the outline with a construction line on the axis, the
turning sense from the measured start face, the angle bound to its parameter, and what Orca cannot turn."""
import math
import unittest

from tests import context  # noqa: F401
from tests.orca_sized import fixture, revolve_sized, table_of
from tests.probe_helpers import user

from lib.capture_model import gap_hints
from lib.orca_recipe.enums import BooleanMode, EntityType, FeatureType
from lib.orca_translate import FIXED, causes, translate
from lib.orca_translate.place import plane_point


def revolve_of(result):
    (made,) = [f for f in result.recipe.features if f.type == FeatureType.REVOLVE]
    return made, result.recipe.features[made.sketch_ref]


def axis_of(made, sketch):
    """The turning axis in Orca coordinates: its point and its unit direction."""
    line = sketch.entities[made.revolve_axis_entity]
    a, b = plane_point(sketch.plane, line.p0), plane_point(sketch.plane, line.p1)
    d = [q - p for p, q in zip(a, b)]
    n = math.sqrt(sum(v * v for v in d))
    return a, [v / n for v in d]


def on_offset_plane(capture, profile):
    """Put the sketch of `profile` on Plane1, an offset of the origin XY plane by the user parameter `lift`."""
    params = capture.setdefault("parameters", {})
    params.setdefault("user", []).append(user("lift", "5 mm", 5.0))
    params.setdefault("model", []).append(
        {"name": "d_lift", "expression": "lift", "value": 0.5, "unit": "mm", "kind": "derived", "role": "",
         "dependency_parameters": ["lift"], "created_by": {"kind": "constructionPlane", "token": "cp1", "name": ""}})
    profile["reference"] = {"kind": "constructionPlane", "token": "cp1",
                            "definition": "ConstructionPlaneOffsetDefinition", "built_on": [{"origin": True}]}
    return capture


class RevolveTest(unittest.TestCase):
    def test_a_full_turn_names_a_construction_line_on_the_axis(self):
        result = translate(fixture("revolve_full"))
        made, sketch = revolve_of(result)
        line = sketch.entities[made.revolve_axis_entity]
        self.assertEqual((line.type, line.construction), (EntityType.LINE, True))
        self.assertEqual(made.revolve_axis_entity, len(sketch.entities) - 1)
        self.assertEqual((made.revolve_angle, made.mode), (360.0, BooleanMode.NEW))
        point, direction = axis_of(made, sketch)
        self.assertEqual([round(v, 9) for v in direction], [0.0, 1.0, 0.0])
        self.assertEqual([round(v, 9) for v in point], [round(v, 9) for v in result.place.point([0, 0, 0])])

    def test_the_turning_sense_follows_the_start_face(self):
        forward = axis_of(*revolve_of(translate(fixture("revolve_quarter"))))[1]
        backward = axis_of(*revolve_of(translate(fixture("revolve_quarter_reversed"))))[1]
        # A quarter turn about +Y takes +X to -Z, where revolve_quarter lies; the reversed one lies at +Z.
        self.assertEqual([round(v, 9) for v in forward], [0.0, 1.0, 0.0])
        self.assertEqual([round(v, 9) for v in backward], [0.0, -1.0, 0.0])

    def test_the_angle_follows_its_parameter(self):
        capture = revolve_sized()
        result = translate(capture, table_of(capture))
        made, _ = revolve_of(result)
        self.assertEqual((made.revolve_angle, made.expr), (90.0, {"revolve_angle": "turn_deg"}))
        self.assertEqual(result.parameters[0]["outcome"], "variable")

    def test_a_turn_to_both_sides_starts_half_its_angle_back_with_a_fixed_angle(self):
        capture = fixture("revolve_symmetric")
        result = translate(capture)
        made, sketch = revolve_of(result)
        self.assertEqual(made.revolve_angle, 120.0)
        # The sketch plane is turned 60 degrees back about the axis, so its normal leaves +Z.
        self.assertAlmostEqual(abs(sketch.plane.normal[2]), 0.5)

    def test_a_turn_to_two_sides_starts_the_angle_of_one_side_back(self):
        # Turned 30 degrees one way and 60 the other about +Y: the start face at -60 degrees (side one turns the right
        # hand way) or at -30 degrees (the other way) puts the sketch plane there.
        for back in (60, 30):
            capture = fixture("revolve_two_sides")
            r = math.radians(-back)
            capture["items"][-1]["data"]["start_face_normal"] = [math.sin(r), 0.0, math.cos(r)]
            made, sketch = revolve_of(translate(capture))
            self.assertEqual(made.revolve_angle, 90.0)
            self.assertAlmostEqual(sketch.plane.normal[0], -math.sin(math.radians(back)))
            self.assertEqual([round(v, 9) for v in axis_of(made, sketch)[1]], [0.0, 1.0, 0.0])

    def test_a_turn_to_two_sides_that_does_not_tell_the_side_is_left_out(self):
        capture = fixture("revolve_two_sides")
        capture["items"][-1]["data"].update(start_face_normal=[-1.0, 0.0, 0.0])
        capture["items"][-1]["data"]["extent"].update(angle_one_deg=90.0, angle_two_deg=30.0)
        self.assertEqual([g["cause"] for g in translate(capture).left_out], [gap_hints.REVOLVE_SIDES])

    def test_sizes_that_move_the_sketch_plane_are_marked(self):
        capture = fixture("revolve_quarter")
        on_offset_plane(capture, capture["items"][-1]["data"]["profiles"][0])
        result = translate(capture, table_of(capture))
        self.assertEqual(len(revolve_of(result)), 2)
        self.assertEqual([p["outcome"] for p in result.parameters if p["name"] == "lift"], [FIXED])

    def test_a_cut_turned_into_the_part_is_written_and_one_that_misses_is_left_out(self):
        result = translate(fixture("revolve_cut_quarter"))
        made, _ = revolve_of(result)
        self.assertEqual(made.mode, BooleanMode.CUT)
        capture = fixture("revolve_cut_quarter")
        data = capture["items"][-1]["data"]
        data["axis"]["point"] = [0, 0, 105]
        for profile in data["profiles"]:
            profile["frame"]["origin"] = [0, 0, 105]
        self.assertEqual([(g["index"], g["cause"]) for g in translate(capture).left_out],
                         [(capture["items"][-1]["index"], causes.MISSES_PART)])

    def test_what_orca_cannot_turn_is_left_out_with_its_cause(self):
        across = fixture("revolve_full")
        across["items"][1]["data"]["axis"]["point"] = [7, 0, 0]
        holed = fixture("revolve_full")
        holed["items"][1]["data"]["profiles"][0]["loops"].append(
            {"outer": False, "curves": [{"kind": "circle", "center": [7.5, 10], "radius": 1}]})
        cases = {"axis off the plane": (fixture("revolve_axis_off_plane"), causes.REVOLVE_AXIS),
                 "across the axis": (across, causes.REVOLVE_ACROSS_AXIS),
                 "outline with holes": (holed, causes.OUTLINE_HOLES)}
        for name, (capture, cause) in cases.items():
            with self.subTest(name):
                self.assertEqual([(g["index"], g["cause"]) for g in translate(capture).left_out], [(1, cause)])


if __name__ == "__main__":
    unittest.main()
