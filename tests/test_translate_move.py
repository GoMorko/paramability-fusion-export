"""Move features written as `move` steps (lib/translator/move.py)."""
import copy
import unittest

from tests import context  # noqa: F401
from tests.schema_check import check_recipe
from tests.translator_helpers import load_capture, steps_of, verdict_of

from lib.params import size_table
from lib.params.expressions import evaluate
from lib.translator import move, translate, vec
from lib.translator.context import Context

FLAT = {"origin": [0, 0, 0], "x": [1, 0, 0], "y": [0, 1, 0], "z": [0, 0, 1]}


def sized(capture):
    params = capture["parameters"]
    table = size_table.build(params["user"], [p["name"] for p in params["user"]], params["model"], "mm")
    return translate(capture, size_table=table)


def marked(result):
    return sorted({d["name"] for d in result.loose + result.fixed + [d for d in result.dropped if d.get("used")]})


def inner(result):
    return steps_of(result.recipe, "toolBody")[0]["features"]


def moved(edit, name="move_translate_sized"):
    """The capture with the data of its Move changed by `edit`."""
    capture = load_capture(name)
    edit(capture["items"][4]["data"])
    return capture


def as_measured(data, kind):
    """The Move rewritten as a kind that holds only the measured points."""
    for key in ("translate", "is_design_space", "params"):
        data.pop(key, None)
    data["move_type"] = kind


class WrittenMoveTest(unittest.TestCase):
    def test_a_distance_follows_its_size(self):
        result = sized(load_capture("move_translate_sized"))
        self.assertEqual(marked(result), [])
        self.assertEqual(result.recipe["version"], 15)
        self.assertEqual([s["kind"] for s in inner(result)], ["extrude", "move"])
        self.assertEqual(inner(result)[1]["translate"], [{"expr": "gap_mm"}, 0.0, 0.0])
        self.assertEqual(check_recipe(result.recipe), [])

    def test_an_angle_follows_its_size(self):
        result = sized(load_capture("move_rotate_sized"))
        self.assertEqual(marked(result), [])
        turn = inner(result)[1]["turn"]
        self.assertEqual((turn["axis"], turn["angleDeg"]), ([0.0, 0.0, 1.0], {"expr": "tilt_deg"}))
        self.assertEqual(check_recipe(result.recipe), [])

    def test_an_axis_that_runs_the_other_way_is_written_the_way_the_body_turned(self):
        capture = moved(lambda data: data["axis"].update(dir=[0, 0, -1]), "move_rotate_sized")
        self.assertEqual(inner(translate(capture))[1]["turn"]["axis"], [0.0, 0.0, 1.0])

    def test_a_free_move_is_written_as_numbers(self):
        def free(data):
            as_measured(data, "free")
            data["transform"] = dict(FLAT, origin=[20, 0, 0])
        self.assertEqual(inner(translate(moved(free)))[1]["translate"], [20.0, 0.0, 0.0])

    def test_a_free_move_that_was_not_read_is_measured(self):
        self.assertEqual(inner(translate(moved(lambda d: as_measured(d, "free"))))[1]["translate"], [20.0, 0.0, 0.0])

    def test_a_move_written_as_numbers_marks_every_size_also_one_no_step_reads(self):
        result = sized(moved(lambda d: as_measured(d, "pointToPoint")))
        self.assertEqual(inner(result)[1]["translate"], [20.0, 0.0, 0.0])
        self.assertEqual(marked(result), ["gap_mm", "peg_len_mm", "plate_h_mm"])

    def test_a_tool_of_the_walks_own_component_has_the_place_of_that_component(self):
        turned = {"origin": [0, 0, 0], "x": [0, 1, 0], "y": [-1, 0, 0], "z": [0, 0, 1]}
        root = Context({"target": {"token": "t1", "placement": {"frame": turned}}, "items": []})
        rod = root.child({"token": "t2", "foreign": True, "component": {"token": "rod"}, "place": {"frame": FLAT}}, "a_")
        self.assertEqual(move._component_frame(rod.child({"token": "t3"}, "b_")), FLAT)

    def test_a_round_body_with_two_corners_moves_by_its_distances(self):
        def round_body(data):
            data["points_before"] = [[[11, 10, 3], [11, 10, 7]]]
            data["points_after"] = [[[31, 10, 3], [31, 10, 7]]]
        self.assertEqual(inner(translate(moved(round_body)))[1]["translate"], [20.0, 0.0, 0.0])

    def test_design_space_distances_are_checked_in_the_frame_of_the_component(self):
        capture = moved(lambda data: data.update(is_design_space=True, translate=[0, 20, 0], params={}))
        capture["target"]["placement"] = {"frame": {"origin": [0, 0, 0], "x": [0, 1, 0], "y": [-1, 0, 0], "z": [0, 0, 1]}}
        self.assertEqual(inner(translate(capture))[1]["translate"], [0.0, 20.0, 0.0])

    def test_a_move_that_moves_nothing_writes_no_step(self):
        def still(data):
            data.update(translate=[0, 0, 0], params={}, points_after=copy.deepcopy(data["points_before"]))
        result = translate(moved(still))
        self.assertEqual(verdict_of(result, 5)["verdict"], "translated")
        self.assertEqual([s["kind"] for s in inner(result)], ["extrude"])

    def test_the_move_is_turned_with_a_y_up_design(self):
        capture = load_capture("move_translate_sized")
        capture["up_axis"] = "y"
        capture["items"][4]["data"].update(translate=[0, 0, 20], params={}, points_after=[
            [[p[0], p[1], p[2] + 20] for p in capture["items"][4]["data"]["points_before"][0]]])
        self.assertEqual(inner(translate(capture))[1]["translate"], [0.0, -20.0, 0.0])

    def test_a_move_of_the_exported_body_is_a_step_of_the_part(self):
        capture = load_capture("move_translate_sized")
        data = capture["items"][4]["data"]
        data["bodies"] = [{"token": "t1", "name": "Body1"}]
        capture["items"][4]["bodies_after"] = data["bodies"]
        del capture["items"][3:4], capture["items"][-1]
        capture["items"][-1].update(index=3)
        result = translate(capture)
        self.assertEqual([s["kind"] for s in result.recipe["features"]], ["extrude", "move"])

    def test_a_pick_after_a_sized_move_follows_it(self):
        result = sized(load_capture("paste_move_offset"))
        tool = steps_of(result.recipe, "toolBody")[0]["features"]
        near = tool[-1]["faces"]["near"][0]
        self.assertEqual(evaluate(near[1]["expr"], {"gap_mm": 30}), 30.0)
        self.assertEqual(evaluate(near[2]["expr"], {"peg_len_mm": 6}), 9.0)

    def test_a_repeat_of_a_step_a_later_move_carried_refuses(self):
        capture = load_capture("rpattern_row")
        pattern = capture["items"].pop()
        body = capture["items"][-1]["bodies_after"]
        points = [[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1]]
        capture["items"].append({
            "index": pattern["index"], "name": "Move1", "type": "MoveFeature", "suppressed": False, "health": "ok", "message": "",
            "in_target_component": True, "bodies_after": body, "data": {
                "input_kind": "bodies", "bodies": body, "move_type": "translateXYZ", "translate": [1, 0, 0],
                "is_design_space": False, "points_before": [points], "points_after": [[vec.add(p, [1, 0, 0]) for p in points]]}})
        capture["items"].append(dict(pattern, index=pattern["index"] + 1))
        self.assertEqual(translate(capture).refusal["name"], pattern["name"])


class RefusedMoveTest(unittest.TestCase):
    def test_each_move_that_cannot_be_copied_exactly_refuses(self):
        def mirrored(data):
            as_measured(data, "pointToPoint")
            data["points_after"] = [[[-p[0], p[1], p[2]] for p in data["points_before"][0]]]

        def two_corners(data):
            as_measured(data, "pointToPoint")
            data["points_before"], data["points_after"] = [[[0, 0, 0], [1, 0, 0]]], [[[5, 0, 0], [6, 0, 0]]]

        def mirrored_transform(data):
            as_measured(data, "free")
            data["transform"] = dict(FLAT, x=[-1, 0, 0])

        def other_transform(data):
            as_measured(data, "free")
            data["transform"] = dict(FLAT, origin=[21, 0, 0])

        cases = {
            "faces": lambda d: d.update(input_kind="faces"),
            "unreadable inputs": lambda d: d.update(input_kind="other"),
            "unknown type": lambda d: d.update(move_type="other"),
            "points after unread": lambda d: d.update(points_after=[[]]),
            "another body": lambda d: d.update(bodies=[{"token": "t9", "name": "Body9"}]),
            "distances unread": lambda d: d["translate"].__setitem__(1, None),
            "distances disagree": lambda d: d.update(translate=[21, 0, 0]),
            "not rigid": mirrored, "too few corners": two_corners, "mirrored transform": mirrored_transform,
            "transform disagrees": other_transform,
        }
        for name, edit in cases.items():
            with self.subTest(name):
                self.assertEqual(translate(moved(edit)).refusal["name"], "Combine1")

    def test_a_turn_that_cannot_be_copied_exactly_refuses(self):
        cases = {"axis unread": lambda d: d.update(axis={"kind": "other"}), "angle disagrees": lambda d: d.update(angle_deg=45.0)}
        for name, edit in cases.items():
            with self.subTest(name):
                self.assertEqual(translate(moved(edit, "move_rotate_sized")).refusal["name"], "Combine1")

    def test_a_move_that_names_no_body_and_may_change_the_part_refuses(self):
        capture = load_capture("extrude_plate")
        capture["items"].append(dict(capture["items"][0], index=2, name="Move1", type="MoveFeature", bodies_after=[],
                                     data={"input_kind": "other", "bodies": []}, target_changed=True))
        self.assertEqual(translate(capture).refusal["name"], "Move1")


class FitTest(unittest.TestCase):
    POINTS = [[0, 0, 0], [10, 0, 0], [0, 7, 0], [0, 0, 3], [10, 7, 3]]

    def test_a_written_turn_carries_the_points_the_fit_saw(self):
        for axis, angle in (([1, 2, 3], 37.0), ([0, 1, 0], 180.0), ([1, 1, 0], 180.0)):
            with self.subTest(angle=angle, axis=axis):
                after = [vec.add(vec.rotate(p, axis, angle), [4, 5, 6]) for p in self.POINTS]
                step = move.written(move.fit(self.POINTS, after))
                turn = step["turn"]
                back = [vec.add(vec.rotate(p, turn["axis"], turn["angleDeg"], turn["axisPoint"]), step["translate"])
                        for p in self.POINTS]
                self.assertTrue(vec.close(back, after, 1e-6))

    def test_a_shift_has_no_turn(self):
        self.assertNotIn("turn", move.written(move.fit(self.POINTS, [vec.add(p, [1, 2, 3]) for p in self.POINTS])))

    def test_points_on_one_line_cannot_be_fitted(self):
        line = [[0, 0, 0], [1, 0, 0], [2, 0, 0]]
        self.assertIsNone(move.fit(line, line))


if __name__ == "__main__":
    unittest.main()
