"""Feature values that follow sizes (the size table passed to translate)."""
import copy
import math
import unittest

from tests import context  # noqa: F401
from tests.translator_helpers import assert_schema_ok, left_out, load_capture, steps_of

from lib.params import size_table
from lib.params.expressions import evaluate
from lib.sketch_values.motion import Motion
from lib.translator import translate
from lib.translator.ranges.range_check import size_env
from lib.translator.values import Quantity, _gives_whole_numbers

TRAY = "filter_tray_sized"
H = "FilterBox_$_height__contains_CeramicMedium"
CUBE = "_CeramicMedium__Cube_width_mm"
TICKED = [H, CUBE, "wall_mm", "corner_mm", "pipe_d_mm", "holes_count"]


def table_of(capture, ticked):
    params = capture["parameters"]
    return size_table.build(params["user"], ticked, params["model"], capture.get("design_units", "mm"))


def run(capture, ticked=TICKED):
    return translate(capture, size_table=table_of(capture, ticked)), table_of(capture, ticked)


def on_tray(edit=None):
    capture = load_capture(TRAY)
    if edit:
        edit(capture)
    return capture


def on_fixture(name, edit, ticked=TICKED):
    """A fixture's items with the tray's parameters; `edit(data)` changes the data of its last item."""
    capture = load_capture(name)
    capture["capture"] = 3
    capture["parameters"] = load_capture(TRAY)["parameters"]
    edit(capture["items"][-1]["data"])
    return capture, ticked


def model_param(capture, name):
    return next(m for m in capture["parameters"]["model"] if m["name"] == name)


def param(name, expression, value):
    return {"name": name, "expression": expression, "value": value}


def resolved(recipe, table):
    """The recipe with every formula worked out at the default sizes and the sizes left out."""
    env = size_env(table, {})

    def walk(node):
        if isinstance(node, dict):
            if set(node) == {"expr"}:
                return round(evaluate(node["expr"], env), 6)
            return {k: walk(v) for k, v in node.items() if k not in ("sizes", "sizesAsWritten")}
        if isinstance(node, list):
            return [walk(v) for v in node]
        return round(node, 6) if isinstance(node, float) else node

    return walk(recipe)


SELECTORS = ("edges", "openFaces")


def same_as_plain(test, capture, result, table):
    """Worked out at the defaults, a sized recipe is the recipe made without sizes. A pick that names an extrude
    (`featureFace`, `featureEdges`) stands for the plain recipe's points, so picks are compared where both have points."""
    plain = copy.deepcopy(capture)
    for item in plain["items"]:
        item["data"].pop("params", None)
    sized, unsized = resolved(result.recipe, table), resolved(translate(plain).recipe, table)
    for a, b in zip(sized["features"], unsized["features"]):
        for key in SELECTORS:
            if key in a and "near" not in a[key]:
                a.pop(key), b.pop(key)
    test.assertEqual(sized, unsized)


class TrayTest(unittest.TestCase):
    def test_every_feature_value_follows_its_parameter(self):
        result, table = run(on_tray())
        recipe = result.recipe
        self.assertEqual((recipe["version"], recipe["sizesAsWritten"]), (12, True))
        self.assertEqual(steps_of(recipe, "extrude")[0]["distance"], {"expr": "FilterBox_height_mm"})
        self.assertEqual(steps_of(recipe, "shell")[0]["thickness"], {"expr": "wall_mm"})
        self.assertEqual(steps_of(recipe, "round")[0]["size"], {"expr": "corner_mm"})
        self.assertEqual(steps_of(recipe, "shell")[0]["openFaces"], {"featureFace": "extrude_1", "which": "end"})
        self.assertEqual(steps_of(recipe, "round")[0]["edges"], {"featureEdges": "extrude_1", "which": "sides"})
        hole = steps_of(recipe, "hole")[0]
        self.assertEqual((hole["diameter"], hole["depth"]), ({"expr": "pipe_d_mm"}, None))
        linear = steps_of(recipe, "pattern")[0]["linear"]
        self.assertEqual((linear["count"], linear["step"]), ({"expr": "holes_count"}, {"expr": "hole_pitch_mm"}))
        self.assertEqual(result.fixed, [])
        assert_schema_ok(self, recipe)
        same_as_plain(self, on_tray(), result, table)

    def test_sizes_are_the_ticked_ones_and_their_formulas(self):
        sizes = run(on_tray())[0].recipe["sizes"]
        self.assertEqual(
            sorted(sizes), sorted(["FilterBox___height__contains_CeramicMedium", CUBE, "wall_mm", "corner_mm",
                                   "pipe_d_mm", "holes_count", "FilterBox_height_mm", "hole_pitch_mm"]))
        self.assertEqual(sizes["hole_pitch_mm"]["expr"], CUBE + " + 4")
        self.assertEqual(sizes["holes_count"]["kind"], "count")

    def test_a_size_nothing_reads_is_left_out_with_a_note(self):
        capture = on_tray()
        result, _ = run(capture, TICKED + ["turn_deg"])
        self.assertNotIn("turn_deg", result.recipe.get("sizes", {}))
        self.assertTrue(any("turn_deg" in note for note in result.notes))

    def test_without_a_table_values_stay_numbers(self):
        recipe = translate(on_tray()).recipe
        self.assertEqual((recipe["version"], "sizes" in recipe, "sizesAsWritten" in recipe), (12, False, False))
        self.assertEqual(steps_of(recipe, "extrude")[0]["distance"], 32)

    def test_a_size_that_moves_a_sketch_stays_free_with_a_warning_and_the_sketch_value_is_its_number(self):
        def edit(capture):
            model_param(capture, "d1")["expression"] = CUBE + " * 4"
            model_param(capture, "d1")["dependency_parameters"] = [CUBE]
        capture = on_tray(edit)
        result, table = run(capture)
        self.assertEqual(result.fixed, [])
        (doubt,) = result.loose
        self.assertEqual(doubt["name"], CUBE)
        self.assertIn("sketch", doubt["reason"])
        self.assertIn(CUBE, result.recipe["sizes"])
        self.assertEqual(steps_of(result.recipe, "pattern")[0]["linear"]["step"], {"expr": "hole_pitch_mm"})
        self.assertEqual(steps_of(result.recipe, "shell")[0]["thickness"], {"expr": "wall_mm"})

    def test_a_formula_that_misses_the_measured_value_is_written_as_its_number(self):
        def edit(capture):
            capture["items"][2]["data"]["params"]["inside"]["value"] = 3.0
        result, _ = run(on_tray(edit))
        self.assertEqual((result.fixed, result.loose), ([], []))
        self.assertEqual(steps_of(result.recipe, "shell")[0]["thickness"], 2)
        self.assertNotIn("wall_mm", result.recipe["sizes"])
        (dropped,) = [d for d in result.dropped if d["name"] == "wall_mm"]
        self.assertTrue(dropped["used"])
        self.assertIn("a value of Shell1 cannot be copied", dropped["reason"])

    def test_a_length_that_reaches_zero_inside_the_range_marks_its_size(self):
        def edit(capture):
            data = capture["items"][1]["data"]
            data["side_one"]["distance"] = data["end_offset"] = 24.0
            data["params"]["side_one.distance"] = param("d3", "(corner_mm - 1.5 mm) * 16", 24.0)
        result, _ = run(on_tray(edit))
        self.assertEqual([f["name"] for f in result.loose], ["corner_mm"])
        self.assertEqual(steps_of(result.recipe, "extrude")[0]["distance"], 24)

    def test_a_length_that_reaches_zero_only_with_two_sizes_at_opposite_ends_marks_both(self):
        def edit(capture):
            data = capture["items"][1]["data"]
            data["side_one"]["distance"] = data["end_offset"] = 32.0
            data["params"]["side_one.distance"] = param("d3", "16 * corner_mm - 8 * wall_mm", 32.0)
        result, _ = run(on_tray(edit))
        self.assertEqual(sorted(f["name"] for f in result.loose), ["corner_mm", "wall_mm"])
        self.assertEqual(steps_of(result.recipe, "extrude")[0]["distance"], 32)

    def test_a_length_of_two_sizes_that_stays_positive_everywhere_keeps_them_free(self):
        def edit(capture):
            data = capture["items"][1]["data"]
            data["side_one"]["distance"] = data["end_offset"] = 32.0
            data["params"]["side_one.distance"] = param("d3", "8 * corner_mm + 4 * wall_mm", 32.0)
        result, _ = run(on_tray(edit))
        self.assertEqual((result.fixed, result.loose), ([], []))
        self.assertEqual(steps_of(result.recipe, "extrude")[0]["distance"], {"expr": "8 * corner_mm + 4 * wall_mm"})

    def test_a_formula_the_parser_cannot_read_marks_the_sizes_fusion_lists_for_it(self):
        def edit(capture):
            capture["items"][1]["data"]["params"]["side_one.distance"]["expression"] = "FilterBox_height_mm * 1 kg / 1 kg"
        result, _ = run(on_tray(edit))
        # The cube width is also read by the hole spacing, so it stays free with a warning; the height is read
        # nowhere else, so it is not a size.
        loose = {f["name"]: f["reason"] for f in result.loose}
        self.assertEqual(list(loose), [CUBE])
        self.assertIn("cannot be copied", loose[CUBE])
        self.assertNotIn("..", loose[CUBE])
        self.assertEqual(result.fixed, [])
        self.assertIn(CUBE, result.recipe["sizes"])
        self.assertNotIn(H, result.recipe["sizes"])
        self.assertEqual(steps_of(result.recipe, "extrude")[0]["distance"], 32)

    def test_left_out_copies_fix_the_count_and_keep_the_spacing_free(self):
        def edit(capture):
            data = capture["items"][6]["data"]
            data["elements"] = [data["elements"][0], data["elements"][2]]
        result, _ = run(on_tray(edit))
        self.assertEqual([f["name"] for f in result.dropped if "leaves copies out" in f["reason"]], ["holes_count"])
        pattern = steps_of(result.recipe, "pattern")[0]
        self.assertEqual((pattern["skip"], pattern["linear"]["count"]), ([1], 3))
        self.assertEqual(pattern["linear"]["step"], {"expr": "hole_pitch_mm"})

    def test_a_negative_parameter_is_written_negated(self):
        def edit(capture):
            data = capture["items"][1]["data"]
            data["side_one"]["distance"] = data["end_offset"] = -32.0
            data["params"]["side_one.distance"] = param("d3", "-FilterBox_height_mm", -32.0)
            capture["items"][2]["data"]["faces"][0]["point"] = [40, 30, -32]
            for edge in capture["items"][3]["data"]["sets"][0]["edges"]:
                edge["points"][0][2] = -16
        result, table = run(on_tray(edit))
        self.assertEqual(result.fixed, [])
        self.assertEqual(steps_of(result.recipe, "extrude")[0]["distance"], {"expr": "FilterBox_height_mm"})


class ValueKindsTest(unittest.TestCase):
    def check(self, capture, ticked, resolve_ok=True):
        result, table = run(capture, ticked)
        self.assertIsNotNone(result.recipe, result.refusal)
        assert_schema_ok(self, result.recipe)
        if resolve_ok:
            same_as_plain(self, capture, result, table)
        return result

    def test_symmetric_half_length_doubles_the_formula(self):
        def edit(data):
            data["params"] = {"symmetric.distance": param("d3", "FilterBox_height_mm / 2", 16.0)}
            data["symmetric"]["distance"] = 16.0
            data["end_offset"] = 16.0
        capture, ticked = on_fixture("extrude_symmetric_half", lambda d: None)
        item = capture["items"][1]["data"]
        edit(item)
        item["profiles"] = copy.deepcopy(load_capture("extrude_plate")["items"][1]["data"]["profiles"])
        result = self.check(capture, ticked)
        self.assertEqual(steps_of(result.recipe, "extrude")[0]["distance"], {"expr": "2 * (FilterBox_height_mm / 2)"})

    def test_taper_follows_an_angle_size(self):
        def edit(data):
            data["side_one"]["taper_deg"] = 5.0
            data["profile_area"], data["end_area"] = 800.0, 900.0
            data["params"] = {"side_one.taper_deg": param("d4", "turn_deg / 18", 5.0)}
        capture, ticked = on_fixture("extrude_plate", lambda d: None, TICKED + ["turn_deg"])
        edit(capture["items"][-1]["data"])
        result = self.check(capture, ticked)
        self.assertEqual(steps_of(result.recipe, "extrude")[0]["taperDeg"], {"expr": "-(turn_deg / 18)"})

    def tapered_through(self, formula, fusion_deg, motion=None):
        """The one way cut through all of `extrude_cut_through_one` with a taper of `fusion_deg` that follows
        `formula`, its measured walls leaning that way."""
        def edit(data):
            data.update(side_one={"kind": "throughAll", "positive": True, "taper_deg": fusion_deg}, end_offset=None,
                        side_leans=[math.sin(math.radians(fusion_deg))] * 4,
                        params={"side_one.taper_deg": param("d4", formula, fusion_deg)})
        capture, ticked = on_fixture("extrude_cut_through_one", edit, TICKED + ["turn_deg"])
        return translate(capture, size_table=table_of(capture, ticked), motion=motion)

    def test_a_cut_through_all_that_widens_but_would_close_at_other_sizes_cuts_their_range_and_is_copied(self):
        result = self.tapered_through("turn_deg - 89", 1.0)
        self.assertIsNotNone(result.recipe, result.refusal)
        self.assertEqual(steps_of(result.recipe, "extrude")[-1]["taperDeg"], {"expr": "-(turn_deg - 89)"})
        cut = next(c for c in result.cuts if c["name"] == "turn_deg")
        self.assertLess(cut["max"], 89 + 45)

    def test_a_cut_through_all_is_left_out_only_once_its_leaning_walls_meet_before_the_part_ends(self):
        # The 10 x 6 outline cuts 41 mm: its walls, 3 mm from the middle, meet at a lean of about 4.2 degrees.
        self.assertIsNone(left_out(self.tapered_through("-4", -4.0), 3))
        self.assertIsNotNone(left_out(self.tapered_through("-5", -5.0), 3))

    def narrowing(self):
        """A motion where the cut's outline is 2 * wall_mm + 2 mm high: it narrows as wall_mm goes down."""
        return Motion.from_json({"version": 1, "box_max": {"min": [0, 0, 0], "max": [40, 20, 10]}, "states": [],
                                 "values": {"3/p0/l0/height": {"const": 2.0, "terms": {"wall_mm": 2.0},
                                                               "sketch": "Sketch1"}}})

    def test_a_cut_through_all_whose_outline_narrows_with_a_size_cuts_that_size_where_it_would_close(self):
        result = self.tapered_through("turn_deg - 89", 1.0, self.narrowing())
        self.assertIsNotNone(result.recipe, result.refusal)
        self.assertEqual(steps_of(result.recipe, "extrude")[-1]["sketch"]["outer"]["height"],
                         {"expr": "2 * wall_mm + 2"})
        cut = next(c for c in result.cuts if c["name"] == "wall_mm")
        self.assertGreater(cut["min"], 1.0)

    def test_a_cut_through_all_whose_outline_follows_sizes_and_stays_open_keeps_their_ranges(self):
        result = self.tapered_through("-(turn_deg / 180)", -0.5, self.narrowing())
        self.assertIsNotNone(result.recipe, result.refusal)
        self.assertFalse([c for c in result.cuts if "would close" in c["reason"]])

    def test_a_cut_through_all_with_a_small_sized_taper_follows_it(self):
        result = self.tapered_through("-(turn_deg / 180)", -0.5)
        self.assertEqual(steps_of(result.recipe, "extrude")[-1]["taperDeg"], {"expr": "turn_deg / 180"})

    def test_the_angle_range_stops_where_the_taper_would_reach_45_degrees(self):
        def edit(data):
            data["side_one"]["taper_deg"] = 5.0
            data["profile_area"], data["end_area"] = 800.0, 900.0
            data["params"] = {"side_one.taper_deg": param("d4", "turn_deg - 85", 5.0)}
        capture, ticked = on_fixture("extrude_plate", edit, TICKED + ["turn_deg"])
        result = self.check(capture, ticked)
        turn = result.recipe["sizes"]["turn_deg"]
        self.assertEqual((turn["min"], turn["max"]), (45.0, 129.98))
        self.assertEqual((result.fixed, result.loose), ([], []))

    def test_revolve_turn_follows_an_angle_size(self):
        capture, ticked = on_fixture(
            "revolve_quarter", lambda d: d.update(params={"extent.angle_deg": param("d4", "turn_deg", 90.0)}),
            TICKED + ["turn_deg"])
        result = self.check(capture, ticked)
        self.assertEqual(steps_of(result.recipe, "revolve")[0]["angleDeg"], {"expr": "turn_deg"})

    def test_partial_circular_pattern_writes_count_and_angle(self):
        def edit(data):
            data["params"] = {"quantity": param("d4", "holes_count + 1", 4.0), "total_angle_deg": param("d5", "turn_deg", 90.0)}
        capture, ticked = on_fixture("cpattern_part", edit, TICKED + ["turn_deg"])
        result = self.check(capture, ticked)
        polar = steps_of(result.recipe, "pattern")[0]["polar"]
        self.assertEqual((polar["count"], polar["angleDeg"]), ({"expr": "holes_count + 1"}, {"expr": "turn_deg"}))

    def test_a_full_turn_keeps_its_angle_as_a_number_and_leaves_the_size_out(self):
        def edit(data):
            data["total_angle_deg"] = 360.0
            data["quantity"] = 4
            data["elements"] = [{"id": n + 1, "suppressed": False, "frame": _turn(n * 90.0)} for n in range(4)]
            data["params"] = {"total_angle_deg": param("d5", "turn_deg * 4", 360.0)}
        capture, ticked = on_fixture("cpattern_part", edit, TICKED + ["turn_deg"])
        result, _ = run(capture, ticked)
        self.assertEqual((result.fixed, result.loose), ([], []))
        self.assertNotIn("turn_deg", result.recipe.get("sizes", {}))
        self.assertNotIn("angleDeg", steps_of(result.recipe, "pattern")[0]["polar"])

    def test_chamfer_and_fillet_sets_keep_their_own_sizes(self):
        def edit(data):
            data["sets"][0]["radius"], data["sets"][1]["radius"] = 3.0, 2.0
            data["params"] = {"sets.0.radius": param("d4", "corner_mm", 3.0)}
        capture, ticked = on_fixture("fillet_two_radii", edit)
        result = self.check(capture, ticked)
        (step,) = steps_of(result.recipe, "round")
        self.assertEqual(step["size"], {"expr": "corner_mm"})
        self.assertEqual(step["edgeSizes"][-1], 2)

    def test_both_chamfer_distances_follow_sizes(self):
        def edit(data):
            data["sets"][0].update(distance=2.0, distance_two=3.0)
            for edge in data["sets"][0]["edges"]:
                side = edge["sides"][0][1]
                edge["cut_normals"] = [[3 * side[0], 3 * side[1], 2]]
            data["params"] = {"sets.0.distance": param("d4", "wall_mm", 2.0),
                              "sets.0.distance_two": param("d5", "corner_mm", 3.0)}
        capture, ticked = on_fixture("chamfer_two_sides", edit)
        result = self.check(capture, ticked)
        (step,) = steps_of(result.recipe, "bevel")
        self.assertEqual((step["size"], step["otherSize"]), ({"expr": "wall_mm"}, {"expr": "corner_mm"}))

    def test_blind_tipped_hole_outline_follows_its_sizes(self):
        def edit(data):
            data.update(extent={"kind": "distance", "depth": 10.0}, end_points=[[20, 30, -6.5]],
                        positions=[[20, 30, 2]], diameter=5.0, end_face_types=["cone"])
            data["side_cylinders"] = [{"origin": [20, 30, 2], "axis": [0, 0, -1], "radius": 2.5}]
            data["params"] = {"diameter": param("d6", "pipe_d_mm / 2 - 1 mm", 5.0),
                              "extent.depth": param("d7", "wall_mm * 5", 10.0)}
        capture, ticked = on_fixture("hole_blind_tip", edit)
        result = self.check(capture, ticked)
        points = steps_of(result.recipe, "revolve")[0]["sketch"]["outer"]["points"]
        self.assertTrue(any(isinstance(c, dict) for p in points for c in p))

    def test_counterbore_and_depth_follow_sizes(self):
        def edit(data):
            data.update(hole_type="counterbore", counterbore={"diameter": 20.0, "depth": 4.0},
                        extent={"kind": "distance", "depth": 10.0}, diameter=12.0)
            data["end_points"] = [[10, 10, 0]]
            data["end_face_types"] = ["plane"]
            data["side_cylinders"] = [{"origin": [10, 10, 10], "axis": [0, 0, -1], "radius": 6.0},
                                      {"origin": [10, 10, 10], "axis": [0, 0, -1], "radius": 10.0}]
            data["params"] = {
                "diameter": param("d4", "pipe_d_mm", 12.0), "counterbore.diameter": param("d5", "pipe_d_mm + 8 mm", 20.0),
                "counterbore.depth": param("d6", "wall_mm * 2", 4.0), "extent.depth": param("d7", "wall_mm * 5", 10.0)}
        capture, ticked = on_fixture("hole_counterbore_blind", edit)
        result = self.check(capture, ticked)
        (hole,) = steps_of(result.recipe, "hole")
        self.assertEqual(hole["counterbore"], {"diameter": {"expr": "pipe_d_mm + 8"}, "depth": {"expr": "wall_mm * 2"}})
        self.assertEqual(hole["depth"], {"expr": "wall_mm * 5"})


class HoleFitOverRangeTest(unittest.TestCase):
    """A counterbore or countersink that fits at the current values must also fit where its sizes cross."""

    def blind_counterbore(self, diameter, bore_diameter, bore_depth, depth):
        def edit(data):
            data.update(hole_type="counterbore", counterbore={"diameter": 20.0, "depth": 4.0},
                        extent={"kind": "distance", "depth": 10.0}, diameter=12.0)
            data["end_points"] = [[10, 10, 0]]
            data["end_face_types"] = ["plane"]
            data["side_cylinders"] = [{"origin": [10, 10, 10], "axis": [0, 0, -1], "radius": 6.0},
                                      {"origin": [10, 10, 10], "axis": [0, 0, -1], "radius": 10.0}]
            data["params"] = {"diameter": param("d4", diameter, 12.0),
                              "counterbore.diameter": param("d5", bore_diameter, 20.0),
                              "counterbore.depth": param("d6", bore_depth, 4.0),
                              "extent.depth": param("d7", depth, 10.0)}
        capture, ticked = on_fixture("hole_counterbore_blind", edit)
        return capture, ticked

    def test_a_counterbore_that_gets_deeper_than_its_hole_marks_the_size_the_depths_read(self):
        capture, ticked = self.blind_counterbore("pipe_d_mm", "pipe_d_mm + 8 mm", "pipe_d_mm / 3", "wall_mm * 5")
        result, _ = run(capture, ticked)
        self.assertEqual([f["name"] for f in result.loose], ["pipe_d_mm"])
        (hole,) = steps_of(result.recipe, "hole")
        self.assertEqual((hole["depth"], hole["counterbore"]["depth"]), (10, 4))

    def test_sizes_that_never_cross_stay_free(self):
        capture, ticked = self.blind_counterbore("pipe_d_mm", "pipe_d_mm + 8 mm", "wall_mm * 2", "wall_mm * 5")
        result, _ = run(capture, ticked)
        self.assertEqual(result.fixed, [])

    def test_a_counterbore_that_gets_narrower_than_its_hole_keeps_the_size_other_steps_read_free_and_writes_numbers(self):
        capture, ticked = self.blind_counterbore("pipe_d_mm", "wall_mm * 10", "wall_mm * 2", "wall_mm * 5")
        result = translate(capture, size_table=table_of(capture, ticked))
        self.assertEqual([f["name"] for f in result.loose], ["wall_mm"])
        self.assertIn("counterbore", result.loose[0]["reason"])
        (hole,) = steps_of(result.recipe, "hole")
        self.assertEqual((hole["diameter"], hole["counterbore"]["diameter"]), (12, 20))

    def test_a_countersink_that_gets_narrower_than_its_hole_writes_numbers_and_leaves_both_sizes_out(self):
        def edit(data):
            data.update(hole_type="countersink", countersink={"diameter": 20.0, "angle_deg": 90.0},
                        extent={"kind": "throughAll"}, diameter=12.0)
            data["params"] = {"diameter": param("d4", "pipe_d_mm", 12.0),
                              "countersink.diameter": param("d5", "wall_mm * 10", 20.0)}
        capture, ticked = on_fixture("hole_countersink_through", edit)
        result, _ = run(capture, ticked)
        self.assertEqual((result.fixed, result.loose), ([], []))
        self.assertNotIn("sizes", result.recipe)
        (hole,) = steps_of(result.recipe, "hole")
        self.assertEqual((hole["diameter"], hole["countersink"]["diameter"]), (12, 20))


def _turn(degrees):
    import math
    c, s = math.cos(math.radians(degrees)), math.sin(math.radians(degrees))
    return {"origin": [20 - 20 * c + 10 * s, 10 - 20 * s - 10 * c, 0], "x": [c, s, 0], "y": [-s, c, 0], "z": [0, 0, 1]}


class QuantityTest(unittest.TestCase):
    def test_operations_keep_formulas_readable(self):
        q = Quantity(10.0, "a + b", ("a",))
        self.assertEqual(q.scaled(0.5).text, "0.5 * (a + b)")
        self.assertEqual(q.scaled(-1).text, "-(a + b)")
        self.assertEqual(q.plus(-2).text, "a + b - 2")
        self.assertEqual(Quantity(1.0).plus(q).text, "1 + (a + b)")
        self.assertEqual(q.divided_by(Quantity(4.0, "n", ("n",))).text, "(a + b) / n")


class WholeCountTest(unittest.TestCase):
    def test_rounding_calls_count_as_whole_inside_a_formula(self):
        table = type("Table", (), {"sizes": {"depth": {"value": 1.5}, "n": {"value": 3, "kind": "count"}}})()
        cases = {"ceil(depth) * 2": True, "n * 2 + round(depth / 2)": True, "ceil(depth) / 2": False, "depth * 2": False}
        self.assertEqual({f: _gives_whole_numbers(table, f) for f in cases}, cases)

    def test_min_max_abs_mod_pow_and_choices_are_whole_when_their_parts_are(self):
        table = type("Table", (), {"sizes": {"depth": {"value": 1.5}, "n": {"value": 3, "kind": "count"},
                                             "m": {"expr": "n * 2 + 1"}, "h": {"expr": "depth * 2"}}})()
        cases = {
            "max(1, floor(depth / 2))": True, "max(1, depth / 2)": False, "min(n, 4) + abs(n - 5)": True,
            "n > 2 ? 3 : 2": True, "depth > 2 ? 3 : 2": True, "depth > 2 ? 2.5 : 3": False,
            "n > 2 ? n : depth": False, "mod(n, 2)": True, "mod(n, 2.5)": False, "pow(n, 2)": True,
            "pow(n, -1)": False, "pow(n, n)": False, "pow(depth, 2)": False, "m * 2": True, "h + 1": False,
            "-n + 2": True, "n / 2": False, "sqrt(n)": False, "n +": False, "unknown + 1": False,
        }
        self.assertEqual({f: _gives_whole_numbers(table, f) for f in cases}, cases)

    def test_derived_sizes_are_followed_to_a_depth_limit(self):
        sizes = {"n": {"value": 3, "kind": "count"}, "d0": {"expr": "n"}}
        sizes.update({"d%d" % i: {"expr": "d%d + 1" % (i - 1)} for i in range(1, 12)})
        table = type("Table", (), {"sizes": sizes})()
        self.assertEqual((_gives_whole_numbers(table, "d3"), _gives_whole_numbers(table, "d11")), (True, False))


if __name__ == "__main__":
    unittest.main()
