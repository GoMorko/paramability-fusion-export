"""Split Body and Move in the Orca copy (`orca_translate/bodies.py`): a split keeps the part's side (an Orca Cut by
the plane, or a Boolean with the tool body), a Move becomes an Orca Transform."""
import copy
import unittest

from tests import context  # noqa: F401
from tests.orca_sized import fixture, split_by_body, split_by_plane, table_of
from tests.translator_helpers import verdict_of

from lib.orca_recipe.enums import BooleanMode, FeatureType
from lib.orca_translate import causes, translate
from lib.orca_translate.formulas import orca_value


def of_type(result, kind):
    return [f for f in result.recipe.features if f.type == kind]


class SplitTest(unittest.TestCase):
    def test_a_split_by_a_plane_keeps_the_side_of_the_piece_exported(self):
        for keep, upper in (("t1", False), ("t2", True)):
            result = translate(split_by_plane(keep))
            (cut,) = of_type(result, FeatureType.CUT)
            self.assertEqual((cut.cut_keep_upper, cut.cut_keep_lower), (upper, not upper), keep)
            self.assertEqual(cut.plane.normal, (1.0, 0.0, 0.0))
            self.assertAlmostEqual(cut.plane.origin[0], result.place.point([25, 0, 0])[0])

    def test_a_piece_with_a_new_name_is_built_by_the_steps_of_the_body_it_came_from(self):
        result = translate(split_by_plane("t2"))
        self.assertEqual(verdict_of(result, 1)["verdict"], "copied")
        self.assertEqual(result.place.point([25, 0, 0])[0] + 7.5, 128.0)

    def test_pieces_on_both_sides_of_the_plane_leave_the_split_out(self):
        capture = split_by_plane("t1")
        capture["items"][2]["data"]["pieces"][1]["box"]["min"][0] = 20
        result = translate(capture)
        self.assertEqual(verdict_of(result, 2)["verdict"], "leftOut")
        self.assertEqual(of_type(result, FeatureType.CUT), [])

    def test_a_split_by_a_body_keeps_what_lies_inside_or_outside_it(self):
        for inside, mode in ((True, BooleanMode.INTERSECT), (False, BooleanMode.CUT)):
            result = translate(split_by_body(inside))
            (boolean,) = of_type(result, FeatureType.BOOLEAN)
            self.assertEqual((boolean.mode, boolean.target_body, boolean.bool_tool_body), (mode, 0, 1))
            self.assertEqual(verdict_of(result, 3)["verdict"], "copied")

    def test_a_split_by_a_curved_face_is_left_out(self):
        capture = split_by_plane("t1")
        capture["items"][2]["data"]["tool"] = {"kind": "surface", "type": "Cylinder"}
        self.assertEqual(verdict_of(translate(capture), 2)["verdict"], "leftOut")

    def test_the_part_after_a_split_is_the_piece_that_is_left(self):
        capture = split_by_plane("t1")
        cut = copy.deepcopy(capture["items"][1])
        cut.update(index=3, name="Notch", bodies_after=[{"token": "t1", "name": "Body1"}])
        cut["data"].update(operation="cut", side_one={"kind": "throughAll", "positive": True},
                           target_box_before=capture["target"]["box"], end_offset=None)
        cut["data"]["profiles"][0]["loops"][0]["curves"] = [{"kind": "circle", "center": [32, 10], "radius": 2}]
        capture["items"].append(cut)
        result = translate(capture)
        # The notch sits in the piece the split took away, so it removes nothing from the part.
        self.assertEqual(verdict_of(result, 3)["verdict"], "leftOut")


class MoveTest(unittest.TestCase):
    def test_a_move_along_the_axes_is_a_transform_by_its_numbers(self):
        capture = fixture("move_translate_sized")
        result = translate(capture, table_of(capture))
        (move,) = of_type(result, FeatureType.TRANSFORM)
        data = capture["items"][4]["data"]
        self.assertEqual([round(v, 6) for v in move.xf_translate], [round(v, 6) for v in data["translate"]])
        self.assertEqual((move.xf_angle_deg, move.expr), (0.0, {}))
        gap = [p for p in result.parameters if p["name"] == "gap_mm"][0]
        self.assertEqual(gap["outcome"], "fixed")

    def test_a_turn_about_an_axis_turns_about_that_axis(self):
        capture = fixture("move_rotate_sized")
        result = translate(capture, table_of(capture))
        (move,) = of_type(result, FeatureType.TRANSFORM)
        self.assertEqual((move.xf_angle_deg, tuple(move.xf_axis)), (90.0, (0.0, 0.0, 1.0)))
        self.assertEqual(tuple(move.xf_pivot), tuple(result.place.point([0, 0, 0])))

    def test_a_turn_by_a_negative_angle_turns_the_same_way_in_orca(self):
        # -90 degrees about -Z is the +90 degree turn about +Z that the points of the fixture show.
        for bound in (False, True):
            with self.subTest(bound=bound):
                capture = fixture("move_rotate_sized")
                data = capture["items"][4]["data"]
                data.update(angle_deg=-90.0, axis=dict(data["axis"], dir=[0, 0, -1]))
                data["params"]["angle_deg"].update(expression="-tilt_deg", value=-90.0)
                result = translate(capture, table_of(capture) if bound else None)
                (move,) = of_type(result, FeatureType.TRANSFORM)
                self.assertEqual((move.xf_angle_deg, tuple(move.xf_axis)), (90.0, (0.0, 0.0, 1.0)))
                if bound:
                    for tilt in (90.0, 30.0):
                        self.assertAlmostEqual(orca_value(move.expr["xf_angle_deg"], {"tilt_deg": tilt}), tilt)
                else:
                    self.assertEqual(move.expr, {})

    def test_a_move_that_the_points_do_not_show_is_left_out(self):
        capture = fixture("move_rotate_sized")
        capture["items"][4]["data"]["angle_deg"] = 45.0
        result = translate(capture)
        self.assertEqual([(g["name"], g["cause"]) for g in result.left_out],
                         [("Combine1", causes.MOVE_MISMATCH)])

    def test_a_move_of_another_body_leaves_the_part(self):
        capture = fixture("move_translate_sized")
        move = capture["items"][4]
        move["bodies_after"] = move["bodies_after"] + [{"token": "t1", "name": "Body1"}]
        del capture["items"][5:]
        self.assertEqual(verdict_of(translate(capture), 4)["verdict"], "skipped")


if __name__ == "__main__":
    unittest.main()
