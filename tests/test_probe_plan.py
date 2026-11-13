import unittest

from tests import context  # noqa: F401
from tests.probe_helpers import (
    capture, circle, extrude, loop, model, profile, read, rect_curves, size, sketch_state, table, user)

from lib.probe import match, plan

PARAMS = [user("count", "3", 3, ""), user("cube", "10 mm", 10), user("W", "count * cube + 2 mm", 32),
          user("off", "5 mm", 5), user("height", "20 mm", 20), user("wall", "2 mm", 2)]
MODEL = [model("d1", "W", 32, sketch="Sketch1"), model("d2", "height", 20, kind="constructionPlane", token="cp1"),
         model("d3", "wall", 2, kind="extrude")]


def square(token="sk1", name="Sketch1", **extra):
    out = profile(name, token, [loop(rect_curves("r", 0, 0, 10, 10))])
    out.update(extra)
    return out


class ScanTests(unittest.TestCase):
    def test_profile_hole_and_axis_records_with_tokens_are_covered(self):
        hole = {"index": 2, "type": "HoleFeature", "data": {"sketch_token": "sk2", "sketch": "Holes",
                                                           "positions": [[1, 2, 3]], "point_tokens": ["p1"]}}
        axis = {"index": 3, "type": "RevolveFeature", "data": {"profiles": [], "axis": {
            "point": [0, 0, 0], "dir": [0, 1, 0], "entity": "l1", "sketch_token": "sk3"}}}
        found = plan.scan(capture(extrude(1, square()), hole, axis))
        self.assertEqual(found.covered, {"sk1": "Sketch1", "sk2": "Holes", "sk3": ""})
        self.assertEqual([t["kind"] for t in found.targets], ["profile", "hole", "axis"])

    def test_a_profile_without_curve_tokens_leaves_its_sketch_uncovered(self):
        bare = square()
        for curve in bare["loops"][0]["curves"]:
            del curve["entity"]
        found = plan.scan(capture(extrude(1, bare), extrude(2, square())))
        self.assertEqual((found.covered, found.uncovered), ({}, {"sk1"}))

    def test_one_unknown_record_uncovers_the_sketch_for_every_record(self):
        pattern = {"index": 5, "type": "RectangularPatternFeature", "data": {"direction_one": {"sketch_token": "sk1"}}}
        found = plan.scan(capture(extrude(1, square()), pattern))
        self.assertEqual(found.covered, {})
        self.assertEqual(found.targets, [])

    def test_an_uncovered_sketch_keeps_its_name_for_the_reason_the_person_reads(self):
        bare = square()
        for curve in bare["loops"][0]["curves"]:
            del curve["entity"]
        pattern = {"index": 5, "type": "RectangularPatternFeature",
                   "data": {"direction_one": {"sketch_token": "sk7", "sketch": "Spine"}}}
        found = plan.scan(capture(extrude(1, bare), pattern))
        self.assertEqual(found.named, {"sk1": "Sketch1", "sk7": "Spine"})
        self.assertEqual(found.uncovered, {"sk1", "sk7"})

    def test_a_curve_the_translator_cannot_copy_is_not_covered(self):
        other = square()
        other["loops"][0]["curves"][0] = {"kind": "other", "entity": "x", "start": [0, 0], "end": [1, 1]}
        self.assertEqual(plan.scan(capture(extrude(1, other))).covered, {})

    def test_hole_point_tokens_must_match_the_positions(self):
        hole = {"index": 2, "type": "HoleFeature", "data": {"sketch_token": "sk2", "positions": [[1, 2, 3]],
                                                           "point_tokens": []}}
        self.assertEqual(plan.scan(capture(hole)).covered, {})

    def test_suppressed_and_foreign_records_are_ignored(self):
        item = extrude(1, dict(square(), foreign=True))
        hidden = dict(extrude(2, square("sk9")), suppressed=True)
        self.assertEqual(plan.scan(capture(item, hidden)).covered, {})


def sweep(index, path, *profiles):
    return {"index": index, "name": "Sweep%d" % index, "type": "SweepFeature",
            "data": {"profiles": list(profiles), "path": path}}


def path_of(*curves, token="skP", name="Path", **extra):
    out = {"closed": False, "kind": "sketch", "sketch": name, "sketch_token": token, "frame": IDENT_FRAME,
           "curves": list(curves), "edges": []}
    out.update(extra)
    return out


def flat_line(entity, a, b):
    return {"kind": "line", "start": [*a, 0], "end": [*b, 0], "entity": entity, "flat": {"kind": "line", "start": a,
                                                                                         "end": b}}


IDENT_FRAME = {"origin": [0, 0, 0], "x": [1, 0, 0], "y": [0, 1, 0], "z": [0, 0, 1]}


class PathScanTests(unittest.TestCase):
    def test_a_sweep_path_of_sketch_lines_is_covered_beside_its_outline(self):
        item = sweep(3, path_of(flat_line("l0", [0, 0], [0, 20]), flat_line("l1", [0, 20], [10, 20])), square())
        found = plan.scan(capture(item))
        self.assertEqual(found.covered, {"sk1": "Sketch1", "skP": "Path"})
        self.assertEqual([t["kind"] for t in found.targets], ["profile", "path"])
        asked = plan.request(capture(item), table(PARAMS, ["count"], MODEL))
        self.assertEqual(asked["curves"], {"skP": ["l0", "l1"]})

    def test_a_path_with_a_free_curve_or_edges_is_left_as_measured_and_leaves_its_sketch_alone(self):
        free = dict(flat_line("l1", [0, 20], [10, 20]), kind="other")
        for label, found_path in (("free curve", path_of(flat_line("l0", [0, 0], [0, 20]), free)),
                                  ("edges", path_of(kind="edges")),
                                  ("foreign", path_of(flat_line("l0", [0, 0], [0, 20]), foreign=True))):
            with self.subTest(label):
                found = plan.scan(capture(sweep(3, found_path, square())))
                self.assertEqual((found.covered, found.uncovered), ({"sk1": "Sketch1"}, set()))
                self.assertNotIn("curves", plan.request(capture(sweep(3, found_path, square())),
                                                        table(PARAMS, ["count"], MODEL)))


class RequestTests(unittest.TestCase):
    def test_request_lists_tokens_and_parameters(self):
        tbl = table(PARAMS, ["count", "cube"], MODEL)
        hole = {"index": 2, "type": "HoleFeature", "data": {"sketch_token": "sk2", "positions": [[1, 2, 3]],
                                                           "point_tokens": ["p1"]}}
        asked = plan.request(capture(extrude(1, square()), hole), tbl)
        self.assertEqual((asked["sketches"], asked["points"], asked["lines"]), (["sk1", "sk2"], ["p1"], []))
        self.assertTrue(asked["target"])
        self.assertTrue({"count", "cube", "W", "d1", "d2"} <= set(asked["params"]))

    def test_no_covered_sketch_gives_no_request(self):
        self.assertIsNone(plan.request(capture(), table(PARAMS, ["count"], MODEL)))

    def test_only_the_sketches_that_matched_at_the_start_are_asked_for(self):
        tbl = table(PARAMS, ["count"], MODEL)
        cap = capture(extrude(1, square()), extrude(2, square("sk2", "Sketch2")))
        self.assertEqual(plan.request(cap, tbl, covered={"sk2"})["sketches"], ["sk2"])


class KeptSizesTests(unittest.TestCase):
    def setUp(self):
        self.tbl = table(PARAMS, ["count", "cube", "off", "height", "wall"], MODEL)

    def test_sizes_that_reach_a_sketch_dimension_or_plane_are_driven(self):
        self.assertEqual(plan.sketch_driven(self.tbl), ["count", "cube", "height"])

    def test_kept_are_the_free_sizes_of_the_recipe_plus_the_driven_ones(self):
        self.assertEqual(plan.kept_sizes(self.tbl, ["off"]), ["count", "cube", "off", "height"])


def built(rows, failed=()):
    """Probe states for single-size rows: built, except the rows named in `failed`."""
    return [{"values": {r["varied"][0]: r["state"][r["varied"][0]]}, "built": r["name"] not in failed}
            for r in rows if len(r["varied"]) == 1]


class ProbeRowTests(unittest.TestCase):
    def setUp(self):
        self.tbl = table(PARAMS, ["count", "cube", "off"], MODEL)
        self.sizes = [size(self.tbl, "count", ""), size(self.tbl, "cube"), size(self.tbl, "off")]

    def test_a_moved_size_first_gets_a_row_a_quarter_below_and_above_its_value(self):
        rows, untried = plan.probe_rows(self.sizes, {"count"})
        self.assertEqual([r["name"] for r in rows], ["count (near min)", "count (near max)"])
        self.assertEqual([r["state"]["count"] for r in rows], [2.25, 3.75])
        self.assertEqual(rows[0]["varied"], ["count"])
        self.assertFalse(rows[0]["step"])
        self.assertEqual(untried, [])

    def test_the_near_values_stay_inside_the_range_and_a_count_moves_by_whole_numbers(self):
        tight = size_dict("tight", 10.0, 9.0, 11.0)
        count = size_dict("n", 2.0, 1.0, 5.0, kind="count")
        zero = size_dict("z", 0.0, -8.0, 4.0)
        edge = size_dict("e", 1.0, 1.0, 5.0, kind="count")
        found = {s["param"]: plan.near_values(s) for s in (tight, count, zero, edge)}
        self.assertEqual(found, {"tight": (9.0, 11.0), "n": (1.0, 3.0), "z": (-2.0, 1.0), "e": (None, 2.0)})

    def test_row_values_are_in_the_units_fusion_shows(self):
        rows, _ = plan.probe_rows(self.sizes, {"cube"})
        self.assertEqual({r["name"]: r["values"]["cube"] for r in rows}, {"cube (near min)": 7.5, "cube (near max)": 12.5})
        far = plan.far_rows(self.sizes, {"cube"}, 10)
        self.assertEqual({r["name"]: r["values"]["cube"] for r in far}, {"cube (min)": 5, "cube (max)": 20})

    def test_two_moved_sizes_add_near_pair_rows_and_later_far_rows_with_all_at_min_and_at_max(self):
        moved = {"count", "cube"}
        rows, _ = plan.probe_rows(self.sizes, moved)
        self.assertEqual([r["name"] for r in rows], ["count (near min)", "count (near max)", "cube (near min)",
                                                     "cube (near max)"])
        pairs = plan.pair_rows(self.sizes, moved, built(rows), 2)
        self.assertEqual([r["name"] for r in pairs], ["all lower", "all higher"])
        self.assertEqual(pairs[0]["state"], {"count": 2.25, "cube": 7.5, "off": 5.0})
        self.assertEqual(pairs[1]["state"], {"count": 3.75, "cube": 12.5, "off": 5.0})
        far = plan.far_rows(self.sizes, moved, 20)
        self.assertEqual([r["name"] for r in far], ["count (min)", "count (max)", "cube (min)", "cube (max)"])
        ends = plan.far_pair_rows(self.sizes, moved, built(rows + far), 2)
        self.assertEqual([r["name"] for r in ends], ["all min", "all max"])
        self.assertEqual(ends[0]["state"], {"count": 1.5, "cube": 5, "off": 2.5})
        self.assertEqual(ends[1]["state"], {"count": 6, "cube": 20, "off": 10})

    def test_rows_past_a_value_that_did_not_build_are_not_planned(self):
        moved = {"count", "cube"}
        rows, _ = plan.probe_rows(self.sizes, moved)
        states = built(rows, failed={"cube (near min)"})
        # cube did not build at 7.5: the lower pair would vary count alone, so it is left out, and the minimum of
        # cube is not tried.
        pairs = plan.pair_rows(self.sizes, moved, states, 2)
        self.assertEqual([r["name"] for r in pairs], ["all higher"])
        far = plan.far_rows(self.sizes, moved, 20, states=states)
        self.assertEqual([r["name"] for r in far], ["count (min)", "count (max)", "cube (max)"])
        ends = plan.far_pair_rows(self.sizes, moved, built(rows + far, failed={"cube (near min)"}), 2)
        # All sizes at their minimum keep cube at its value, since it did not build below it.
        self.assertEqual([r["state"]["cube"] for r in ends], [10.0, 20])

    def test_the_far_ends_only_take_the_rows_that_are_left(self):
        self.assertEqual([r["name"] for r in plan.far_rows(self.sizes, {"count", "cube"}, 2)],
                         ["count (min)", "count (max)"])
        self.assertEqual(plan.far_rows(self.sizes, {"count", "cube"}, 1), [])

    def test_a_far_end_the_near_value_already_reached_is_not_tried_again(self):
        tight = [size_dict("tight", 10.0, 9.0, 30.0)]
        self.assertEqual([r["name"] for r in plan.probe_rows(tight, {"tight"})[0]],
                         ["tight (near min)", "tight (near max)"])
        self.assertEqual([r["values"]["tight"] for r in plan.far_rows(tight, {"tight"}, 10)], [30.0])

    def test_the_row_limit_leaves_a_size_untried(self):
        rows, untried = plan.probe_rows(self.sizes, {"count", "cube"}, limit=3)
        self.assertEqual(untried, ["cube"])
        self.assertEqual([r["name"] for r in rows], ["count (near min)", "count (near max)"])

    def test_a_size_that_reaches_no_sketch_gets_no_row_and_is_never_untried(self):
        # `off` only feeds step values: it is exact from its formula, so only the moved size is tried.
        rows, untried = plan.probe_rows(self.sizes, {"count"}, limit=2)
        far = plan.far_rows(self.sizes, {"count"}, 20)
        self.assertEqual(untried, [])
        self.assertEqual({p for r in rows + far for p in r["varied"]}, {"count"})

    def test_rows_carry_the_line_the_progress_window_shows(self):
        rows, _ = plan.probe_rows(self.sizes, {"cube", "count"})
        rows += plan.pair_rows(self.sizes, {"cube", "count"}, built(rows), 2)
        self.assertEqual([r["label"] for r in rows],
                         ["count at 2.25", "count at 3.75", "cube at 7.5 mm", "cube at 12.5 mm",
                          "several sizes together", "several sizes together"])

    def test_a_label_gives_the_value_in_the_unit_the_person_typed(self):
        inches = dict(size_dict("gap", 25.4, 2.54, 254.0), unit="in")
        angle = dict(size_dict("tilt", 30.0, 0.0, 90.0, kind="angle"), unit="deg")
        self.assertEqual(plan.probe_rows([inches], {"gap"})[0][1]["label"], "gap at 1.25 in")
        self.assertEqual(plan.probe_rows([angle], {"tilt"})[0][1]["label"], "tilt at 37.5 deg")

    def test_a_row_tried_again_nearer_says_so_and_a_discovery_row_says_what_it_checks(self):
        sizes = [size_dict("gap", 10.0, 0.0, 100.0)]
        states = [{"values": {"gap": 100.0}, "built": False}]
        retry = plan.nearer_rows(sizes, states)
        self.assertEqual(retry[0]["label"], "gap at 55 mm" + plan.RETRY_NOTE)
        candidate = dict(size_dict("lid", 5.0, 0.0, 9.0), end=9.0)
        self.assertEqual(plan.discovery_rows([candidate], 5)[0]["label"], "checking if lid changes this part")


class CandidateProfileTests(unittest.TestCase):
    def test_among_profiles_with_the_same_curves_the_nearest_to_the_capture_is_taken(self):
        cap = capture(extrude(1, square()))
        target = plan.scan(cap).targets[0]
        near = {"loops": [loop(rect_curves("r", 1, 0, 11, 10))]}
        far = {"loops": [loop(rect_curves("r", 50, 0, 60, 10))]}
        values, cause = match.state_values(target, read(sketch_state("sk1", [far, near])))
        self.assertIsNone(cause)
        self.assertEqual(values["1/p0/l0/center.0"], 6.0)

    def test_a_circle_and_its_sketch_frame_offset_in_plane_map_back(self):
        prof = profile("S", "s", [loop([circle((5, 5), 2, "c")])])
        target = plan.scan(capture(extrude(1, prof))).targets[0]
        shifted = {"origin": [3, 0, 0], "x": [1, 0, 0], "y": [0, 1, 0], "z": [0, 0, 1]}
        state_profile = {"loops": [loop([circle((2, 5), 2, "c")])]}
        values, _ = match.state_values(target, read(sketch_state("s", [state_profile], shifted)))
        self.assertEqual(values["1/p0/l0/center.0"], 5.0)


def size_dict(name, value, low, high, kind="length"):
    return {"param": name, "size": name, "unit": "" if kind == "count" else "mm", "kind": kind, "value": value,
            "min": low, "max": high}


def tried(name, *pairs):
    return [{"values": {name: value}, "built": built} for value, built in pairs]


class NearerRowsTests(unittest.TestCase):
    def values(self, rows):
        return [r["state"][r["varied"][0]] for r in rows]

    def test_a_side_that_did_not_build_is_tried_half_then_a_quarter_then_a_tenth_of_the_way(self):
        d = size_dict("d", 16.0, 8.0, 32.0)
        steps = [tried("d", (8.0, False), (32.0, False)),
                 tried("d", (8.0, False), (32.0, False), (12.0, False), (24.0, False)),
                 tried("d", (8.0, False), (32.0, False), (12.0, False), (24.0, False), (14.0, False), (20.0, True))]
        self.assertEqual([self.values(plan.nearer_rows([d], s)) for s in steps], [[12.0, 24.0], [14.0, 20.0], [15.2, 22.0]])
        done = steps[2] + tried("d", (15.2, False), (22.0, False), (21.0, False))
        self.assertEqual(plan.nearer_rows([d], done), [])

    def test_a_side_with_a_value_that_built_and_a_farther_one_that_did_not_is_halved_between_them(self):
        d = size_dict("d", 10.0, 5.0, 20.0)
        built_then_failed = tried("d", (7.5, True), (12.5, True), (5.0, True), (20.0, False))
        self.assertEqual(self.values(plan.nearer_rows([d], built_then_failed)), [16.25])
        closer = built_then_failed + tried("d", (16.25, True), (18.125, False))
        self.assertEqual(self.values(plan.nearer_rows([d], closer)), [17.1875])
        close_enough = closer + tried("d", (17.1875, True))
        self.assertEqual(plan.nearer_rows([d], close_enough), [])

    def test_a_count_is_halved_to_a_whole_number_and_stops_when_none_is_left(self):
        n = size_dict("n", 2.0, 1.0, 10.0, kind="count")
        self.assertEqual(self.values(plan.nearer_rows([n], tried("n", (3.0, True), (10.0, False)))), [6.0])
        self.assertEqual(plan.nearer_rows([n], tried("n", (3.0, True), (4.0, False), (1.0, True))), [])

    def test_a_side_whose_nearest_try_did_not_build_is_not_halved(self):
        d = size_dict("d", 10.0, 5.0, 20.0)
        states = tried("d", (12.5, False), (20.0, True))
        self.assertEqual(plan.nearer_rows([d], states), [])

    def test_a_size_that_moved_with_one_reading_gets_a_second_one_half_way(self):
        d = size_dict("d", 16.0, 16.0, 32.0)
        self.assertEqual(self.values(plan.nearer_rows([d], tried("d", (32.0, True)), moved=["d"])), [24.0])
        self.assertEqual(plan.nearer_rows([d], tried("d", (32.0, True))), [])

    def test_counts_stay_whole_and_sizes_without_any_built_row_come_first(self):
        count = size_dict("n", 3.0, 1.0, 6.0, kind="count")
        width = size_dict("w", 10.0, 5.0, 20.0)
        states = tried("n", (1.0, False), (6.0, True)) + tried("w", (5.0, False), (20.0, False))
        rows = plan.nearer_rows([count, width], states, limit=2)
        self.assertEqual([(r["varied"][0], r["state"][r["varied"][0]]) for r in rows], [("w", 7.5), ("w", 15.0)])
        self.assertEqual(self.values(plan.nearer_rows([count], states)), [2.0])

    def test_the_check_rows_set_every_other_size_to_its_measured_ends(self):
        sizes = [size_dict("a", 120.0, 75.0, 165.0, "angle"), size_dict("b", 12.0, 6.0, 24.0),
                 size_dict("c", 3.0, 1.5, 6.0)]
        spans = {"a": {"low": 75.0, "high": 165.0}, "b": {"low": 9.0, "high": 24.0}, "c": {"low": 1.5, "high": 6.0}}
        rows = plan.check_rows(sizes, {"a"}, spans, room=10)
        self.assertEqual([r["state"] for r in rows[-2:]],
                         [{"a": 120.0, "b": 9.0, "c": 1.5}, {"a": 120.0, "b": 24.0, "c": 6.0}])
        # The reads of the rows are kept by key: the two half way rows of one size must not share one.
        self.assertEqual(len({r["key"] for r in rows}), len(rows))


if __name__ == "__main__":
    unittest.main()
