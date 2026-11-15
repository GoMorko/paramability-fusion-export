"""Coil: copied as the recipe's coil step from what the reader measured; each case it cannot copy is left out."""
import copy
import unittest
from types import SimpleNamespace

from tests import context  # noqa: F401
from tests.coil_helpers import coil_capture, edit_coil, with_sizes
from tests.translator_helpers import assert_schema_ok, left_out, load_capture, steps_of

from lib.capture_model import gap_hints
from lib.params import size_table
from lib.translator import translate
from lib.translator.combine import step as combine_step
from lib.translator.result import Refusal

COIL = 2


def coil_of(result):
    return steps_of(result.recipe, "coil")[0]


def gap_of(result):
    found = left_out(result, COIL)
    assert found is not None, "the coil was copied"
    return found


def as_tool(capture):
    """The coil as a new body next to the part, joined to it by a Combine (item 3)."""
    coil = capture["items"][COIL]
    coil["bodies_after"] = [{"token": "t1", "name": "Body1"}, {"token": "c1", "name": "Body2"}]
    coil["target_changed"] = False
    capture["items"].append({
        "index": 3, "name": "Combine1", "type": "CombineFeature", "suppressed": False, "health": "ok",
        "message": "", "in_target_component": True, "bodies_after": [{"token": "t1", "name": "Body1"}],
        "data": {"target": {"token": "t1", "name": "Body1"}, "tools": [{"token": "c1", "name": "Body2"}],
                 "operation": "join", "keep_tools": False}})
    return capture


def sized(capture):
    params = capture["parameters"]
    ticked = [u["name"] for u in params["user"]]
    return translate(capture, size_table=size_table.build(params["user"], ticked, params["model"], "mm"))


class CoilCopyTest(unittest.TestCase):
    def test_a_round_wire_joined_to_the_part_is_a_coil_step_on_the_end_face(self):
        result = translate(coil_capture())
        self.assertIsNone(result.refusal)
        step = coil_of(result)
        self.assertEqual((step["combine"], step["pitch"], step["turns"], "hand" in step), ("add", 4.0, 3.0, False))
        self.assertEqual(step["sketch"]["on"], {"origin": [20.0, 10.0, 14.0], "normal": [0.0, -1.0, 0.0],
                                                "xDir": [1.0, 0.0, 0.0]})
        self.assertEqual(step["sketch"]["outer"], {"kind": "circle", "center": [4.0, 0.0], "radius": 1.0})
        self.assertEqual(step["axis"], {"point": [0.0, 0.0], "dir": [0.0, 1.0]})
        assert_schema_ok(self, result.recipe)

    def test_a_left_hand_coil_says_so_and_keeps_the_rise_along_the_axis(self):
        step = coil_of(translate(coil_capture(hand="left")))
        self.assertEqual(step["hand"], "left")
        self.assertEqual(step["sketch"]["on"]["normal"], [0.0, 1.0, 0.0])

    def test_a_square_wire_is_a_rect_and_a_triangle_wire_a_polygon(self):
        square = coil_of(translate(coil_capture(shape="square")))["sketch"]["outer"]
        self.assertEqual((square["kind"], square["width"], square["height"]), ("rect", 2.0, 2.0))
        triangle = coil_of(translate(coil_capture(shape="triangle")))["sketch"]["outer"]
        self.assertEqual((triangle["kind"], len(triangle["points"])), ("polygon", 3))

    def test_every_pair_of_parameters_gives_the_same_helix(self):
        for kind in ("revolutions_height", "revolutions_pitch", "height_pitch"):
            with self.subTest(kind=kind):
                step = coil_of(translate(coil_capture(kind=kind, turns=2.75)))
                self.assertEqual((step["pitch"], step["turns"]), (4.0, 2.75))

    def test_the_operation_follows_the_volumes(self):
        for operation, combine in (("join", "add"), ("cut", "cut"), ("newBody", "new")):
            with self.subTest(operation=operation):
                capture = coil_capture(operation=operation)
                result = translate(as_tool(capture) if operation == "newBody" else capture)
                self.assertEqual(coil_of(result)["combine"], "add" if operation == "newBody" else combine)

    def test_a_coil_that_is_a_tool_of_a_combine_is_written_onto_the_part(self):
        result = translate(as_tool(coil_capture(operation="newBody")))
        self.assertEqual([s["kind"] for s in result.recipe["features"]], ["extrude", "coil"])
        self.assertEqual(coil_of(result)["combine"], "add")
        assert_schema_ok(self, result.recipe)


class CoilGapTest(unittest.TestCase):
    def left_out_by(self, edit, **kwargs):
        result = translate(edit_coil(coil_capture(**kwargs), edit))
        return gap_of(result)["reason"], result

    def test_a_taper_angle_is_not_copied(self):
        reason, _ = self.left_out_by(lambda d: d["params"]["taper_deg"].update(value=5.0, expression="5 deg"))
        self.assertIn("taper", reason)

    def test_parameters_that_do_not_say_the_type_leave_the_coil_out(self):
        self.assertIn("sizes", self.left_out_by(lambda d: d["params"].pop("revolutions"))[0])

    def test_a_capture_without_coil_details_asks_for_a_new_export(self):
        capture = coil_capture()
        capture["items"][COIL]["data"] = {}
        self.assertIn("Export again", gap_of(translate(capture))["reason"])

    def test_half_turns_are_not_copied(self):
        self.assertIn("half", self.left_out_by(lambda d: None, turns=2.5)[0])

    def test_end_faces_lost_in_the_part_leave_the_coil_out(self):
        for edit in (lambda d: d["faces"]["flat"].pop(), lambda d: d.update(faces=None)):
            with self.subTest():
                self.assertIn("end faces", self.left_out_by(edit)[0])

    def test_an_end_face_that_is_not_the_whole_wire_leaves_the_coil_out(self):
        self.assertIn("end faces", self.left_out_by(lambda d: d["faces"]["flat"][0].update(area=1.0))[0])

    def test_a_wire_that_is_not_a_plain_outline_leaves_the_coil_out(self):
        def second_loop(d):
            d["faces"]["flat"][0]["loops"].append(copy.deepcopy(d["faces"]["flat"][0]["loops"][0]))
        self.assertIn("wire", self.left_out_by(second_loop)[0])

    def test_edges_off_the_helix_leave_the_coil_out(self):
        def bend(d):
            d["faces"]["edges"][0][8][2] += 1.0
        self.assertIn("plain helix", self.left_out_by(bend)[0])

    def test_a_wrong_hand_does_not_fit(self):
        def mirror(d):
            for flat in d["faces"]["flat"]:
                flat["frame"]["z"] = [-v for v in flat["frame"]["z"]]
        self.assertIn("plain helix", self.left_out_by(mirror)[0])

    def test_a_spiral_has_no_rise(self):
        def flatten(d):
            for flat in d["faces"]["flat"]:
                flat["frame"]["origin"][2] = 14.0
            for edge in d["faces"]["edges"]:
                for point in edge:
                    point[2] = 14.0
        reason, _ = self.left_out_by(flatten, kind="revolutions_pitch")
        self.assertIn("spiral", reason)

    def test_the_turns_must_not_touch(self):
        reason, _ = self.left_out_by(lambda d: None, size=4.5, diameter=20.0, pitch=4.0)
        self.assertIn("touch", reason)

    def test_a_cut_that_could_also_be_an_intersect_is_left_out(self):
        reason, _ = self.left_out_by(lambda d: d["made"][0].update(volume=100.0), operation="cut")
        self.assertIn("combines", reason)

    def test_a_new_body_with_the_wrong_volume_is_left_out(self):
        capture = as_tool(coil_capture(operation="newBody"))
        capture["items"][COIL]["data"]["made"][0]["volume"] *= 1.5
        found = gap_of_index(translate(capture), COIL + 1)
        self.assertIn("Coil1 (coil)", found["reason"])

    def test_a_coil_past_the_recipe_caps_is_left_out_and_the_ones_before_stay(self):
        capture = coil_capture()
        first = capture["items"][COIL]
        before = first["data"]["volumes_before"][0]["volume"]
        after = first["data"]["made"][0]["volume"]
        for n in range(1, 9):
            more = copy.deepcopy(first)
            more["index"], more["name"] = COIL + n, "Coil%d" % (n + 1)
            more["data"]["volumes_before"][0]["volume"] = before + n * (after - before)
            more["data"]["made"][0]["volume"] = before + (n + 1) * (after - before)
            capture["items"].append(more)
        result = translate(capture)
        self.assertEqual(len(steps_of(result.recipe, "coil")), 8)
        self.assertIn("at most 8", gap_of_index(result, COIL + 8)["reason"])

    def test_the_turns_of_all_coils_stay_within_the_cap(self):
        capture = coil_capture(turns=60.0, pitch=2.5, size=1.0, diameter=8.0)
        second = copy.deepcopy(capture["items"][COIL])
        second["index"], second["name"] = COIL + 1, "Coil2"
        first_data = capture["items"][COIL]["data"]
        gain = first_data["made"][0]["volume"] - first_data["volumes_before"][0]["volume"]
        second["data"]["volumes_before"][0]["volume"] += gain
        second["data"]["made"][0]["volume"] += gain
        capture["items"].append(second)
        result = translate(capture)
        self.assertEqual(len(steps_of(result.recipe, "coil")), 1)
        self.assertIn("100 turns", gap_of_index(result, COIL + 1)["reason"])

    def test_a_tool_body_with_a_coil_and_other_steps_is_refused(self):
        tool = SimpleNamespace(steps=[{"kind": "extrude"}, {"kind": "coil"}])
        found = combine_step.tool_steps([(tool, (None, None))], "add")
        self.assertIsInstance(found, Refusal)
        self.assertEqual(found.cause, gap_hints.COIL_TOOL)


def gap_of_index(result, index):
    found = left_out(result, index)
    assert found is not None, "the coil was copied"
    return found


class CoilSizesTest(unittest.TestCase):
    def test_diameter_wire_turns_and_height_follow_their_sizes(self):
        result = sized(with_sizes(coil_capture()))
        step = coil_of(result)
        self.assertEqual(step["sketch"]["outer"]["radius"], {"expr": "0.5 * coil_s"})
        self.assertIn("coil_d", step["sketch"]["outer"]["center"][0]["expr"])
        self.assertEqual((step["pitch"], step["turns"]), ({"expr": "coil_h / coil_n"}, {"expr": "coil_n"}))
        self.assertEqual((result.fixed, result.loose, result.dropped), ([], [], []))
        assert_schema_ok(self, result.recipe)

    def test_the_ranges_are_cut_where_the_wire_would_reach_the_axis_or_the_turns_touch(self):
        sizes = sized(with_sizes(coil_capture())).recipe["sizes"]
        self.assertGreater(sizes["coil_d"]["min"], 5.0)
        self.assertLess(sizes["coil_s"]["max"], 4.0)

    def test_a_pitch_and_a_height_give_the_turns(self):
        step = coil_of(sized(with_sizes(coil_capture(kind="height_pitch"))))
        self.assertEqual((step["pitch"], step["turns"]), ({"expr": "coil_p"}, {"expr": "coil_h / coil_p"}))

    def test_a_height_that_is_not_the_rise_marks_its_sizes_and_stays_a_number(self):
        def stray(capture):
            capture["items"][COIL]["data"]["params"]["height"]["value"] += 1.5
        capture = with_sizes(coil_capture())
        stray(capture)
        result = sized(capture)
        step = coil_of(result)
        self.assertEqual((step["pitch"], step["turns"]), (4.0, {"expr": "coil_n"}))
        self.assertIn("coil_h", [d["name"] for d in result.dropped])

    def test_a_wire_that_is_not_round_or_square_keeps_its_numbers_and_marks_the_sizes(self):
        result = sized(with_sizes(coil_capture(shape="triangle")))
        step = coil_of(result)
        self.assertEqual(step["sketch"]["outer"]["kind"], "polygon")
        self.assertEqual({d["name"] for d in result.dropped}, {"coil_d", "coil_s"})

    def test_a_wire_in_a_place_the_diameter_does_not_explain_marks_the_diameter(self):
        capture = with_sizes(coil_capture())
        capture["items"][COIL]["data"]["params"]["diameter"]["value"] += 0.7
        result = sized(capture)
        self.assertEqual(coil_of(result)["sketch"]["outer"]["center"], [4.0, 0.0])
        self.assertIn("coil_d", [d["name"] for d in result.dropped])

    def test_a_taper_that_a_size_could_change_is_marked(self):
        capture = with_sizes(coil_capture())
        data = capture["items"][COIL]["data"]
        data["params"]["taper_deg"].update(expression="coil_t", name="d7")
        capture["parameters"]["user"].append({"name": "coil_t", "expression": "0 deg", "value": 0.0, "unit": "deg",
                                              "comment": "", "is_favorite": True, "value_type": "numeric",
                                              "dependency_parameters": [], "dependent_parameters": [],
                                              "kind": "angle", "display_value": 0.0})
        capture["parameters"]["model"].append({"name": "d7", "expression": "coil_t", "value": 0.0, "unit": "deg",
                                               "kind": "derived", "role": "TaperAngle",
                                               "dependency_parameters": ["coil_t"],
                                               "created_by": {"kind": "feature", "token": "tok_d7", "name": "Coil1",
                                                              "sketch": "", "component": ""}})
        result = sized(capture)
        self.assertIn("coil_t", [d["name"] for d in result.dropped])


if __name__ == "__main__":
    unittest.main()
