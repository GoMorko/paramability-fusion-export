"""Picks and reaches that follow sizes on the sized filter tray."""
import unittest
from unittest import mock

from tests import context  # noqa: F401
from tests.translator_helpers import assert_schema_ok, load_capture, steps_of
from tests.test_translate_sized import CUBE, H, param, run

from lib.params.expressions import evaluate
from lib.translator import translate
from lib.translator.values import _env

HEIGHT = "FilterBox_height_mm"
TOP = [40, 30, 32]


def tray(edit=None, keep=None):
    """The tray capture; `keep` lists the item positions to keep, `edit(capture)` changes it."""
    capture = load_capture("filter_tray_sized")
    if keep is not None:
        capture["items"] = [capture["items"][n] for n in keep]
    if edit:
        edit(capture)
    return capture


def fixed_names(result):
    return sorted(f["name"] for f in result.fixed)


def loose_names(result):
    return sorted(f["name"] for f in result.loose)


def at(recipe, table, value, sizes=None):
    """A written number or formula worked out at the default sizes, or at `sizes` (recipe name to value)."""
    if not isinstance(value, dict):
        return value
    return round(evaluate(value["expr"], _env(table, sizes or {})), 6)


def tab(start=None, side_one=None, index=10):
    """A join extrude of a 10 mm square beside the tray, from the base plane up to the top face."""
    square = [[80, 0], [90, 0], [90, 10], [80, 10]]
    curves = [{"kind": "line", "start": square[n], "end": square[(n + 1) % 4]} for n in range(4)]
    frame = {"origin": [0, 0, 0], "x": [1, 0, 0], "y": [0, 1, 0], "z": [0, 0, 1]}
    return {
        "index": index, "name": "Tab", "type": "ExtrudeFeature", "suppressed": False, "health": "ok", "message": "",
        "in_target_component": True, "bodies_after": [{"token": "t1", "name": "Body1"}],
        "data": {
            "operation": "join", "profiles": [{"sketch": "Sketch9", "frame": frame,
                                               "loops": [{"outer": True, "curves": curves}]}],
            "start": start or {"kind": "profilePlane"}, "extent_type": "one",
            "side_one": side_one or {"kind": "toEntity", "plane": {"point": TOP, "normal": [0, 0, 1]}, "offset": 0.0,
                                     "entity_type": "BRepFace", "face_point": TOP},
            "side_two": None, "symmetric": None, "thin": False, "participants": [{"token": "t1", "name": "Body1"}],
            "target_box_before": {"min": [0, 0, 0], "max": [80, 60, 32]}, "end_offset": 32.0,
        },
    }


class PicksTest(unittest.TestCase):
    def test_shell_and_round_name_the_extrude_and_nothing_is_fixed(self):
        result, _ = run(tray())
        self.assertEqual(result.fixed, [])
        self.assertEqual(steps_of(result.recipe, "shell")[0]["openFaces"], {"featureFace": "extrude_1", "which": "end"})
        self.assertEqual(steps_of(result.recipe, "round")[0]["edges"], {"featureEdges": "extrude_1", "which": "sides"})

    def test_some_side_edges_follow_the_height_by_formula(self):
        def edit(capture):
            edges = capture["items"][3]["data"]["sets"][0]["edges"]
            del edges[3]
        result, table = run(tray(edit))
        self.assertEqual(result.fixed, [])
        near = steps_of(result.recipe, "round")[0]["edges"]["near"]
        self.assertEqual(near[0], [0, 0, {"expr": "0.5 * " + HEIGHT}])
        big = {"FilterBox___height__contains_CeramicMedium": 2.5, CUBE: 30}
        self.assertEqual(at(result.recipe, table, near[0][2], big), 38.5)
        assert_schema_ok(self, result.recipe)

    def test_a_pick_on_unknown_geometry_marks_the_earlier_sizes(self):
        def edit(capture):
            capture["items"][3]["data"]["sets"][0]["edges"] = [{"token": "e9", "closed": False, "points": [[5, 5, 16]]}]
        result, _ = run(tray(edit))
        self.assertEqual((fixed_names(result), loose_names(result)), ([], sorted([H, CUBE, "wall_mm"])))
        self.assertIn("Fillet1 picks", result.loose[0]["reason"])
        self.assertEqual(steps_of(result.recipe, "round")[0]["edges"], {"near": [[5, 5, 16]]})
        self.assertEqual(steps_of(result.recipe, "round")[0]["size"], {"expr": "corner_mm"})

    def test_an_edge_inside_one_side_wall_follows_that_wall(self):
        def edit(capture):
            capture["items"][3]["data"]["sets"][0]["edges"] = [{"token": "e9", "closed": False, "points": [[0, 30, 16]]}]
        result, table = run(tray(edit))
        self.assertEqual((fixed_names(result), loose_names(result)), ([], []))
        (point,) = steps_of(result.recipe, "round")[0]["edges"]["near"]
        big = {"FilterBox___height__contains_CeramicMedium": 2.5, CUBE: 30}
        self.assertEqual(at(result.recipe, table, point[2], big), 38.5)

    def test_a_mirrored_round_follows_the_sizes_its_pick_follows(self):
        def edit(capture):
            edges = capture["items"][3]["data"]["sets"][0]["edges"]
            edges[:] = [e for e in edges if e["points"][0][0] == 0]
            capture["items"].append({
                "index": 11, "name": "Mirror1", "type": "MirrorFeature", "suppressed": False, "health": "ok",
                "message": "", "in_target_component": True, "bodies_after": [{"token": "t1", "name": "Body1"}],
                "data": {"entity_type": "features", "sources": [3], "plane": {"point": [40, 0, 0], "normal": [1, 0, 0]},
                         "combine": False}})
        result, _ = run(tray(edit, keep=[0, 1, 2, 3]))
        self.assertEqual(result.fixed, [])
        near = steps_of(result.recipe, "round")[1]["edges"]["near"]
        self.assertEqual(near, [[80, 0, {"expr": "0.5 * " + HEIGHT}], [80, 60, {"expr": "0.5 * " + HEIGHT}]])

    def test_without_sizes_picks_stay_points(self):
        recipe = translate(tray()).recipe
        self.assertEqual(steps_of(recipe, "shell")[0]["openFaces"], {"near": [TOP]})


def _round_on_tab_top():
    """A round on the front top edge of the tab of `tab()` started on the tray top, 5 mm tall."""
    return {"index": 11, "name": "Fillet9", "type": "FilletFeature", "suppressed": False, "health": "ok",
            "message": "", "in_target_component": True, "bodies_after": [{"token": "t1", "name": "Body1"}],
            "data": {"sets": [{"kind": "constant", "radius": 1.0, "continuity": "tangent", "input_kinds": ["edge"],
                               "edges": [{"token": "e9", "closed": False, "points": [[85, 0, 37]]}]}]}}


class ReachTest(unittest.TestCase):
    def test_up_to_a_moving_face_follows_its_height(self):
        result, table = run(tray(lambda c: c["items"].append(tab()), keep=[0, 1]))
        self.assertEqual(result.fixed, [])
        self.assertEqual(steps_of(result.recipe, "extrude")[1]["distance"], {"expr": HEIGHT})

    def test_up_to_a_construction_plane_stays_a_number(self):
        side = {"kind": "toEntity", "plane": {"point": [0, 0, 20], "normal": [0, 0, 1]}, "offset": 0.0,
                "entity_type": "ConstructionPlane"}

        def edit(capture):
            capture["items"].append(tab(side_one=side))
            capture["items"][-1]["data"]["end_offset"] = 20.0
        result, _ = run(tray(edit, keep=[0, 1]))
        self.assertEqual(result.fixed, [])
        self.assertEqual(steps_of(result.recipe, "extrude")[1]["distance"], 20)

    def test_up_to_an_unknown_face_marks_the_earlier_sizes(self):
        side = {"kind": "toEntity", "plane": {"point": [0, 0, 20], "normal": [0, 0, 1]}, "offset": 0.0,
                "entity_type": "BRepFace", "face_point": [5, 5, 20]}

        def edit(capture):
            capture["items"].append(tab(side_one=side))
            capture["items"][-1]["data"]["end_offset"] = 20.0
        result, _ = run(tray(edit, keep=[0, 1]))
        self.assertEqual((fixed_names(result), loose_names(result)), ([], sorted([H, CUBE])))

    def test_a_start_on_a_moving_face_moves_the_sketch_with_it(self):
        start = {"kind": "fromEntity", "plane": {"point": TOP, "normal": [0, 0, 1]}, "entity_type": "BRepFace",
                 "face_point": TOP}

        def edit(capture):
            capture["items"].append(tab(start=start, side_one={"kind": "distance", "distance": 5.0, "taper_deg": 0.0}))
            capture["items"][-1]["data"]["end_offset"] = 37.0
            capture["items"].append(_round_on_tab_top())
        result, _ = run(tray(edit, keep=[0, 1]))
        self.assertEqual(result.fixed, [])
        self.assertEqual(steps_of(result.recipe, "extrude")[1]["sketch"]["on"]["origin"], [0, 0, {"expr": HEIGHT}])
        self.assertEqual(steps_of(result.recipe, "round")[0]["edges"]["near"], [[85, 0, {"expr": HEIGHT + " + 5"}]])

    def test_an_offset_start_follows_its_parameter(self):
        def edit(capture):
            capture["items"].append(tab(start={"kind": "offset", "offset": 4.0},
                                        side_one={"kind": "distance", "distance": 5.0, "taper_deg": 0.0}))
            capture["items"][-1]["data"].update(end_offset=9.0, params={"start.offset": param("d30", "wall_mm * 2", 4.0)})
        result, _ = run(tray(edit, keep=[0, 1]))
        self.assertEqual(steps_of(result.recipe, "extrude")[1]["sketch"]["on"]["origin"],
                         [0, 0, {"expr": "wall_mm * 2"}])

    def test_a_moving_start_that_reaches_to_a_face_leaves_its_size_out(self):
        def edit(capture):
            capture["items"].append(tab(start={"kind": "offset", "offset": 4.0}))
            capture["items"][-1]["data"]["params"] = {"start.offset": param("d30", "wall_mm * 2", 4.0)}
        result, _ = run(tray(edit, keep=[0, 1]))
        self.assertEqual((result.fixed, result.loose), ([], []))
        self.assertNotIn("wall_mm", result.recipe["sizes"])


class CapsTest(unittest.TestCase):
    def test_a_formula_past_the_length_cap_fixes_its_sizes(self):
        with mock.patch("lib.translator.translate.MAX_FORMULA_LENGTH", 20):
            result, _ = run(tray(lambda c: c["items"][3]["data"]["sets"][0]["edges"].pop()))
        self.assertEqual(fixed_names(result), sorted([H, CUBE]))
        self.assertIn("too long", result.fixed[0]["reason"])
        self.assertEqual(steps_of(result.recipe, "round")[0]["edges"]["near"][0], [0, 0, 16])

    def test_an_extent_pattern_with_a_sized_count_never_divides_by_zero(self):
        def edit(capture):
            data = capture["items"][6]["data"]
            data["distance_type"], data["distance_one"] = "extent", 48.0
            data["params"]["distance_one"] = param("d9", "hole_pitch_mm * 2", 48.0)
        result, table = run(tray(edit))
        step = steps_of(result.recipe, "pattern")[0]["linear"]["step"]
        self.assertEqual(step, {"expr": "(hole_pitch_mm * 2) / (max(holes_count - 1, 1))"})
        self.assertEqual(at(result.recipe, table, step, {"holes_count": 1}), 48)

    def test_a_count_whose_formula_can_give_a_part_number_marks_its_size(self):
        def edit(capture):
            capture["items"][6]["data"]["params"]["quantity_one"] = param("d8", CUBE + " / 20 mm * 3", 3.0)
        result, _ = run(tray(edit))
        self.assertIn(CUBE, loose_names(result))
        self.assertEqual(steps_of(result.recipe, "pattern")[0]["linear"]["count"], 3)

    def test_a_count_of_counts_stays_sized(self):
        def edit(capture):
            capture["items"][6]["data"]["params"]["quantity_one"] = param("d8", "holes_count * 1", 3.0)
        result, _ = run(tray(edit))
        self.assertEqual(steps_of(result.recipe, "pattern")[0]["linear"]["count"], {"expr": "holes_count"})


if __name__ == "__main__":
    unittest.main()
