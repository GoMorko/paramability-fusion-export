"""Split Body and Move in the Orca copy (`orca_translate/bodies.py`): a split keeps the part's side (an Orca Cut by
the plane, or a Boolean with the tool body), a Move becomes an Orca Transform."""
import copy
import importlib
import unittest
from unittest import mock

from tests import context  # noqa: F401
from tests.orca_sized import B1, B2, B3, fixture, split_by_body, split_by_plane, table_of
from tests.translator_helpers import verdict_of

from lib.orca_recipe.enums import BooleanMode, FeatureType
from lib.orca_translate import causes, translate
from lib.orca_translate.formulas import orca_value

# The module: the package's `translate` is the function.
orca_walk = importlib.import_module("lib.orca_translate.translate")


def of_type(result, kind):
    return [f for f in result.recipe.features if f.type == kind]


def _bridge(capture, index):
    """A join extrude at `index` that changes Body1 and Body2 together (it lists both as participants)."""
    join = copy.deepcopy(capture["items"][1])
    join.update(index=index, name="Bridge", bodies_before=[B1, B2], bodies_after=[B1])
    join["data"].update(operation="join", participants=[B1, B2])
    return join


PLATE = {"token": "t9", "name": "Plate"}


def _split_tool(bridge_first):
    """`split_by_plane` as a tool: a plate (Plate, exported) is extruded and Body1 cut from it by Combine1. The Bridge
    join, which changes Body1 and Body2 together, comes before the plate when `bridge_first`, else after Combine1."""
    capture = split_by_plane("t1")
    plate = copy.deepcopy(capture["items"][1])
    plate.update(name="Plate", bodies_after=[PLATE])
    plate["data"].update(participants=[])
    plate["data"]["profiles"][0]["loops"][0]["curves"] = [
        {"kind": "line", "start": a, "end": b} for a, b in
        (([-10, -10], [50, -10]), ([50, -10], [50, 30]), ([50, 30], [-10, 30]), ([-10, 30], [-10, -10]))]
    combine = {"name": "Combine1", "type": "CombineFeature", "suppressed": False, "health": "ok",
               "in_target_component": True, "bodies_before": [PLATE, B1, B2], "bodies_after": [PLATE, B2],
               "data": {"target": PLATE, "tools": [dict(B1, volume=5000.0)], "operation": "cut",
                        "keep_tools": False, "volume_before": 24000.0, "volume_after": 19000.0}}
    steps = [_bridge(capture, 0), plate, combine] if bridge_first else [plate, combine, _bridge(capture, 0)]
    for index, step in enumerate(steps, start=3):
        step["index"] = index
    capture["items"] += steps
    capture["target"] = dict(PLATE, box={"min": [-10, -10, 0], "max": [50, 30, 10]}, volume_mm3=19000.0)
    return capture


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

    def test_a_step_before_the_split_reads_the_measures_of_the_body_it_came_from(self):
        capture = split_by_plane("t2")
        whole = {"min": [0, 0, 0], "max": [40, 20, 10]}
        step = capture["items"][1]
        step["data"]["target_box_before"] = {"min": [0, 0, 0], "max": [1, 1, 1]}  # read on the exported piece
        step["body_states"] = {"t1": {"box_before": whole, "volume_before": 8000.0, "volume_after": 8000.0}}
        seen = []
        extrude = orca_walk.HANDLERS["ExtrudeFeature"]

        def spy(ctx, item):
            seen.append(item["data"]["target_box_before"])
            return extrude(ctx, item)

        with mock.patch.dict(orca_walk.HANDLERS, {"ExtrudeFeature": spy}):
            result = translate(capture)
        self.assertEqual(seen[-1], whole)
        self.assertEqual(verdict_of(result, 1)["verdict"], "copied")

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

    def test_a_split_whose_other_piece_is_later_changed_with_the_part_is_left_out(self):
        capture = split_by_plane("t1")
        capture["items"].append(_bridge(capture, 3))
        result = translate(capture)
        self.assertEqual([g["cause"] for g in result.left_out if g["index"] == 2], [causes.PIECE_USED_LATER])
        self.assertEqual(of_type(result, FeatureType.CUT), [])

    def test_a_split_inside_a_tool_body_counts_only_the_steps_before_the_combine_that_takes_the_tool(self):
        before = translate(_split_tool(bridge_first=True))
        self.assertEqual([g["cause"] for g in before.left_out if g["index"] == 5], [causes.PIECE_USED_LATER])
        after = translate(_split_tool(bridge_first=False))
        self.assertEqual(verdict_of(after, 4)["verdict"], "copied")

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
