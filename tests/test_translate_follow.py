"""Picks and reaches that follow sizes on the sized filter tray."""
import unittest
from types import SimpleNamespace
from unittest import mock

import copy

from tests import context  # noqa: F401
from tests.probe_helpers import table, user
from tests.translator_helpers import assert_schema_ok, load_capture, steps_of
from tests.test_translate_loft import SIZES, SQUARES, circle_hole, loft_data
from tests.test_translate_sized import CUBE, H, param, run
from tests.test_translate_sketch_motion import motion_of
from tests.test_translate_sketch_motion import run as run_sketch
from tests.test_translate_sweep import (PIPE, PIPE_ITEM, PLATE, arc_xy, edited_after, line, pipe_along, sized,
                                        with_options)

from lib.sketch_values.motion import Affine, Motion

from lib.params.expressions import evaluate
from lib.translator import translate
from lib.translator.translate import _fix_long_formulas
from lib.translator.values import Sized, _env

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

    def test_a_moving_start_that_reaches_to_a_face_keeps_its_end_on_the_face(self):
        def edit(capture):
            capture["items"].append(tab(start={"kind": "offset", "offset": 4.0}))
            capture["items"][-1]["data"]["params"] = {"start.offset": param("d30", "wall_mm * 2", 4.0)}
        result, _ = run(tray(edit, keep=[0, 1]))
        self.assertEqual((result.fixed, result.loose), ([], []))
        tab_step = steps_of(result.recipe, "extrude")[1]
        self.assertEqual(tab_step["sketch"]["on"]["origin"], [0, 0, {"expr": "wall_mm * 2"}])
        self.assertEqual(tab_step["distance"], {"expr": HEIGHT + " - (wall_mm * 2)"})


class CapsTest(unittest.TestCase):
    def test_a_formula_past_the_length_cap_fixes_its_sizes(self):
        with mock.patch("lib.translator.translate.MAX_FORMULA_LENGTH", 20):
            result, _ = run(tray(lambda c: c["items"][3]["data"]["sets"][0]["edges"].pop()))
        self.assertEqual(fixed_names(result), sorted([H, CUBE]))
        self.assertIn("too long", result.fixed[0]["reason"])
        self.assertEqual(steps_of(result.recipe, "round")[0]["edges"]["near"][0], [0, 0, 16])

    def test_a_long_formula_whose_terms_cancel_is_written_shorter_and_reads_only_what_is_left(self):
        # A plane's move less the same move of another plane: the long part cancels out.
        bend = "wall_mm * (cos(0.5 * angle_deg) / sin(0.5 * angle_deg))"
        twice = bend + " + " + bend
        long_sum = "height_mm + %s - 40 - (height_mm / 3 + %s) + 9.5" % (twice, twice)
        value = Sized(expr=long_sum)
        value.n, value.reads = 12.0, ("height_mm", "wall_mm", "angle_deg")
        sizes = table([user("height_mm", "50 mm", 50), user("wall_mm", "3 mm", 3), user("angle_deg", "120 deg", 120,
                                                                                         "deg")],
                      ["height_mm", "wall_mm", "angle_deg"])
        doubts = []
        ctx = SimpleNamespace(table=sizes, doubt=lambda names, why, fixed=False: doubts.append((names, fixed)))
        with mock.patch("lib.translator.translate.MAX_FORMULA_LENGTH", len(long_sum) - 1):
            _fix_long_formulas({"features": [{"label": "Cap", "distance": value}]}, ctx)
        self.assertEqual((value["expr"], value.reads, doubts), ("2 * height_mm / 3 - 30.5", ("height_mm",), []))

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


def round_on(sets, index=3):
    """A round of 0.2 mm over `sets`, each `(closed, points)` one edge, after the item at index - 1."""
    edges = [{"token": "e%d" % n, "closed": closed, "points": points} for n, (closed, points) in enumerate(sets)]
    return {"index": index, "name": "Fillet1", "type": "FilletFeature", "suppressed": False, "health": "ok",
            "message": "", "in_target_component": True, "bodies_after": [{"token": "t1", "name": "Body1"}],
            "data": {"sets": [{"kind": "constant", "radius": 0.2, "continuity": "tangent", "input_kinds": ["edge"],
                               "edges": edges}]}}


def with_round(capture, sets):
    capture = copy.deepcopy(capture)
    capture["items"].append(round_on(sets, capture["items"][-1]["index"] + 1))
    return capture


def edges_of_round(result):
    return steps_of(result.recipe, "round")[0]["edges"]


WIRE = Motion({"2/p0/l0/radius": Affine(0, {"wire_mm": 0.5}, "Sketch1")})
# The pipe's wire is a circle of 3 mm: its two ends, as the closed edges a round picks.
PIPE_END = [(True, [[30, 40, 3], [30, 40, -3]])]
PIPE_START = [(True, [[0, 3, 0], [0, -3, 0]])]


class SweepFacesTest(unittest.TestCase):
    """Picks on the faces of a sweep step: its two end faces are named, the rest marks the sizes the sweep reads."""

    def test_all_edges_of_an_end_face_name_the_sweep_and_mark_nothing(self):
        for which, sets in (("end", PIPE_END), ("start", PIPE_START)):
            with self.subTest(which):
                result = sized(with_round(load_capture(PIPE), sets), WIRE)
                self.assertEqual(edges_of_round(result), {"featureEdges": "sweep_2", "which": which})
                self.assertEqual((result.loose, result.fixed), ([], []))
                assert_schema_ok(self, result.recipe)

    def test_a_path_drawn_from_the_far_end_has_its_end_face_where_the_written_path_ends(self):
        for which, sets in (("end", PIPE_END), ("start", PIPE_START)):
            with self.subTest(which):
                result = sized(with_round(load_capture("sweep_far_end"), sets), WIRE)
                self.assertEqual(edges_of_round(result), {"featureEdges": "sweep_2", "which": which})

    def test_an_outline_kept_in_one_direction_has_its_end_face_square_to_the_outline_and_not_to_the_path(self):
        curves = [line((0, 0, 0), (10, 0, 0)), arc_xy((10, 10), 10, -90, -45),
                  line((17.071068, 2.928932, 0), (30, 15.857864, 0))]
        capture = edited_after(pipe_along(curves), orientation="parallel")
        result = sized(with_round(capture, [(True, [[30, 15.857864, 3], [30, 15.857864, -3]])]), WIRE)
        self.assertEqual(edges_of_round(result), {"featureEdges": "sweep_2", "which": "end"})

    def test_a_twist_leaves_only_the_start_face_placed(self):
        capture = with_options(PIPE, PIPE_ITEM, twist_deg=90.0)
        start = sized(with_round(capture, PIPE_START), WIRE)
        self.assertEqual(edges_of_round(start), {"featureEdges": "sweep_2", "which": "start"})
        end = sized(with_round(capture, PIPE_END), WIRE)
        self.assertEqual(edges_of_round(end), {"near": [[30.0, 40.0, 3.0], [30.0, 40.0, -3.0]]})
        self.assertEqual([f["name"] for f in end.loose], ["wire_mm"])

    def test_a_closed_path_has_no_end_faces(self):
        points = [[20, 0, -0.5], [20, 1, 0], [20, 0, 0.5], [20, -1, 0]]
        capture = with_round(load_capture("sweep_closed_twist"), [(False, [p]) for p in points])
        self.assertNotIn("featureEdges", edges_of_round(sized(capture)))

    def test_an_outline_with_an_opening_has_no_end_faces(self):
        capture = load_capture(PIPE)
        capture["items"][PIPE_ITEM]["data"]["profiles"][0]["loops"].append(circle_hole([0.0, 0.0], 1.0, "c1"))
        capture["items"][PIPE_ITEM]["target_after"]["volume_mm3"] = None
        result = sized(with_round(capture, PIPE_END), WIRE)
        self.assertEqual(edges_of_round(result), {"near": [[30.0, 40.0, 3.0], [30.0, 40.0, -3.0]]})


def square_wire_on_plate():
    """The plate with a sweep of a 2 mm square wire along a path sketch on it; `wire_mm` is the side of the square."""
    capture = load_capture(PLATE)
    data = capture["items"][3]["data"]
    square = [[[-1, -1], [1, -1]], [[1, -1], [1, 1]], [[1, 1], [-1, 1]], [[-1, 1], [-1, -1]]]
    data["profiles"][0]["loops"][0]["curves"] = [
        {"kind": "line", "start": a, "end": b, "entity": "r%d" % n} for n, (a, b) in enumerate(square)]
    data["path"].update(kind="sketch", edges=[], sketch="Sketch9")
    data["areas"] = [4.0]
    capture["items"][3]["target_after"]["volume_mm3"] = None
    return capture


SQUARE_WIRE = Motion({"3/p0/l0/width": Affine(0, {"wire_mm": 1.0}, "Sketch2"),
                      "3/p0/l0/height": Affine(0, {"wire_mm": 1.0}, "Sketch2")})


class SweepPointsTest(unittest.TestCase):
    """A pick that is not a whole end face keeps its points and marks only the sizes the sweep reads."""

    def loose_of(self, sets):
        result = sized(with_round(square_wire_on_plate(), sets), SQUARE_WIRE, ["wire_mm", "plate_mm"])
        self.assertEqual(edges_of_round(result), {"near": [p for _, points in sets for p in points]})
        return [f["name"] for f in result.loose]

    def test_an_edge_at_a_corner_of_the_outline_or_of_an_end_face_keeps_its_point_and_marks_the_wire(self):
        for label, sets in (("side", [(False, [[17.5, 1, 5]])]), ("end", [(False, [[40, 30, 5]])])):
            with self.subTest(label):
                self.assertEqual(self.loose_of(sets), ["wire_mm"])

    def test_all_four_edges_of_the_end_face_name_the_sweep(self):
        ends = [(False, [p]) for p in ([41, 30, 4], [40, 30, 5], [39, 30, 4], [40, 30, 3])]
        result = sized(with_round(square_wire_on_plate(), ends), SQUARE_WIRE, ["wire_mm", "plate_mm"])
        self.assertEqual(edges_of_round(result), {"featureEdges": "sweep_3", "which": "end"})
        self.assertEqual(result.loose, [])

    def test_an_edge_that_is_not_at_a_corner_of_the_outline_marks_every_size_before(self):
        side = [(False, [[17.5, 0.5, 5]])]
        self.assertEqual(sorted(self.loose_of(side)), ["plate_mm", "wire_mm"])


LOFT_TOP = [(False, [p]) for p in ([0, -5, 30], [5, 0, 30], [0, 5, 30], [-5, 0, 30])]
LOFT_BOTTOM = [(False, [p]) for p in ([0, -10, 0], [10, 0, 0], [0, 10, 0], [-10, 0, 0])]


class LoftFacesTest(unittest.TestCase):
    def run_loft(self, capture, sets):
        return run_sketch(with_round(capture, sets), SIZES, motion_of(SQUARES))

    def test_all_edges_of_an_end_face_name_the_loft_and_mark_nothing(self):
        for which, sets in (("end", LOFT_TOP), ("start", LOFT_BOTTOM)):
            with self.subTest(which):
                result = self.run_loft(load_capture(SQUARES), sets)
                self.assertEqual(edges_of_round(result), {"featureEdges": "loft_2", "which": which})
                self.assertEqual((result.loose, result.fixed), ([], []))
                assert_schema_ok(self, result.recipe)

    def test_one_edge_of_an_end_face_keeps_its_point_and_marks_the_sizes_the_loft_reads(self):
        result = self.run_loft(load_capture(SQUARES), LOFT_TOP[:1])
        self.assertEqual(edges_of_round(result), {"near": [[0, -5, 30]]})
        self.assertEqual(sorted(f["name"] for f in result.loose), sorted(SIZES))

    def test_outlines_with_openings_have_no_end_faces(self):
        capture = load_capture(SQUARES)
        for profile, radius in zip(loft_data(capture)["profiles"], (3, 1.5)):
            profile["loops"].append(circle_hole([0, 0], radius, "h"))
        result = self.run_loft(capture, LOFT_TOP)
        self.assertNotIn("featureEdges", edges_of_round(result))


if __name__ == "__main__":
    unittest.main()
