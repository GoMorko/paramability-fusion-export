"""Rounds and chamfers whose sets of edges lie apart are copied one after the other (`translator/finishes/set_split.py`).

The fixture is the 40 by 20 by 10 mm box of `fillet_two_radii`: set 0 rounds the side edges at y 0, set 1 those at
y 20. The box height follows `wall_mm`, read before the round, so a step copied as several steps marks `wall_mm`.
"""
import copy
import unittest

from tests import context  # noqa: F401
from tests.test_translate_measured_rounds import changing_set, even, sampled
from tests.test_translate_sized import on_fixture, param, run
from tests.translator_helpers import assert_schema_ok, load_capture, steps_of, verdict_of

from lib.capture_model import gap_hints
from lib.design_model.steps import finish as sets_of
from lib.dialog_model import left_out_preview
from lib.export_plan import reach_pass
from lib.translator import translate
from lib.translator.context import Context
from lib.translator.finishes import set_split
from lib.translator.result import Entry, Refusal

TOP = {"token": "top", "point": [20.0, 10.0, 10.0]}


def box(low, high):
    return {"min": list(low), "max": list(high)}


def side(token, x, y, turn=90.0):
    """A side edge of the box at (x, y), with its box and the angle between its faces."""
    return {"token": token, "closed": False, "points": [[x, y, 5]], "box": box([x, y, 0], [x, y, 10]),
            "turn_deg": turn}


def chain_and_face(data):
    """Set 0 picked along tangent chains from its first edge, set 1 picked by a face, both of radius 2."""
    first, second = data["sets"]
    first.update(tangent_chain=True, edges=[dict(side("e0", 0, 0), seed=True), side("e1", 40, 0)])
    second.update(radius=2.0, tangent_chain=False, input_kinds=["face"], faces=[TOP],
                  edges=[side("e2", 40, 20), side("e3", 0, 20)])


def translated(edit, params=None):
    """The result and the loose sizes when the box height follows `wall_mm`; `params` go to the round."""
    capture, ticked = on_fixture("fillet_two_radii", edit)
    capture["items"][1]["data"]["params"] = {"side_one.distance": param("d1", "wall_mm * 5", 10.0)}
    if params:
        capture["items"][2]["data"]["params"] = params
    result, _ = run(capture, ticked)
    return result, [entry["name"] for entry in result.loose]


def one_step(test, edit, params=None):
    """`edit` leaves the round as one step, picked as before, with `wall_mm` marked."""
    result, loose = translated(edit, params)
    (step,) = steps_of(result.recipe, "round")
    test.assertFalse({"chain", "faceEdges"} & set(step["edges"]))
    test.assertEqual(loose, ["wall_mm"])


class SplitTest(unittest.TestCase):
    def test_sets_picked_in_different_ways_are_copied_one_after_the_other_with_their_own_picks(self):
        result, loose = translated(chain_and_face)
        first, second = steps_of(result.recipe, "round")
        # One point on the seed edge, its height following the box.
        self.assertEqual((first["edges"]["chain"], [p[:2] for p in first["edges"]["near"]]), ("tangent", [[0, 0]]))
        self.assertEqual(list(second["edges"]), ["faceEdges"])
        # The sizes that may move the sets near each other are marked.
        self.assertEqual(loose, ["wall_mm"])
        self.assertEqual(result.gaps, [])
        assert_schema_ok(self, result.recipe)

    def test_sets_that_meet_or_come_near_stay_one_step(self):
        def near(low, high):
            def edit(data):
                chain_and_face(data)
                data["sets"][1]["edges"][0]["box"] = box(low, high)
            return edit
        for name, low, high in (("shared corner", [40, 0, 10], [40, 20, 10]),
                                ("nearer than the rounds reach", [40, 7, 0], [40, 20, 10])):
            with self.subTest(name):
                one_step(self, near(low, high))

    def test_edges_nearer_than_their_measured_points_stay_one_step(self):
        def edit(first_edge, second_edge):
            def change(data):
                chain_and_face(data)
                data["sets"][0]["radius"] = data["sets"][1]["radius"] = 0.5
                data["sets"][0]["edges"] = [dict(first_edge, seed=True)]
                data["sets"][1]["edges"] = [second_edge]
            return change
        long_edge = {"token": "l", "closed": False, "points": [[20, 0, 10]], "box": box([0, 0, 10], [40, 0, 10]),
                     "turn_deg": 90.0}
        # A short edge 1.5 mm beside the long one, its middle 13 mm from the long one's middle.
        short = {"token": "s", "closed": False, "points": [[7, 1.5, 10]], "box": box([5, 1.5, 10], [9, 1.5, 10]),
                 "turn_deg": 90.0}
        # A hole rim 2 mm from the plate edge, its measured points and its seam away from that edge.
        rim = {"token": "h", "closed": True, "points": [[15, 7, 10], [5, 7, 10]], "box": box([5, 2, 10], [15, 12, 10]),
               "turn_deg": 90.0}
        for name, other in (("parallel edges", short), ("hole near an edge", rim)):
            with self.subTest(name):
                one_step(self, edit(long_edge, other))

    def test_a_sharp_angle_between_the_faces_keeps_one_step(self):
        def v_groove(data):
            chain_and_face(data)
            # Faces 30 degrees apart: each round touches its faces 3.7 times its radius from the edge.
            for one in data["sets"]:
                for edge in one["edges"]:
                    edge["turn_deg"] = 150.0
        one_step(self, v_groove)

    def test_a_radius_that_may_grow_too_far_keeps_one_step(self):
        def larger(data):
            chain_and_face(data)
            data["sets"][0]["radius"] = 6.0
        # At 6 mm the sets lie apart; at the top of its range (12 mm) the round would reach the other set.
        one_step(self, larger, {"sets.0.radius": param("d2", "corner_mm * 2", 6.0)})

    def test_a_capture_without_edge_boxes_stays_one_step(self):
        def no_boxes(data):
            chain_and_face(data)
            for one in data["sets"]:
                for edge in one["edges"]:
                    del edge["box"]
        one_step(self, no_boxes)

    def test_a_changing_radius_with_another_set_apart_gets_a_step_of_its_own(self):
        def edit(data):
            edge = dict(sampled([0, 0, 10], [40, 0, 10], even(1.0, 3.0)), box=box([0, 0, 10], [40, 0, 10]),
                        turn_deg=90.0)
            data["sets"] = [changing_set(edge), dict(data["sets"][1], edges=[side("e2", 40, 20), side("e3", 0, 20)])]
        result, _ = translated(edit)
        changing, plain = steps_of(result.recipe, "round")
        self.assertEqual((changing["size"], changing["sizeEnd"]), (1.0, 3.0))
        self.assertEqual(plain["size"], 3)
        self.assertEqual(result.gaps, [])


def unmeasured_chord(data):
    """Set 1 is a round by chord length whose faces were not measured, so it cannot be copied."""
    data["sets"][0]["edges"] = [side("e0", 0, 0), side("e1", 40, 0)]
    data["sets"][1] = {"kind": "chordLength", "chord_length": 2.0, "continuity": "tangent", "input_kinds": ["edge"],
                       "edges": [side("e2", 40, 20), side("e3", 0, 20)]}


class LeftOutTest(unittest.TestCase):
    def test_a_set_that_cannot_be_copied_is_left_out_alone(self):
        params = {"sets.0.radius": param("d2", "corner_mm - 1 mm", 2.0),
                  "sets.1.chord_length": param("d3", "pipe_d_mm / 6", 2.0)}
        result, loose = translated(unmeasured_chord, params)
        (step,) = steps_of(result.recipe, "round")
        self.assertEqual([p[:2] for p in step["edges"]["near"]], [[0, 0], [40, 0]])
        verdict = verdict_of(result, 2)
        (gap,) = result.gaps
        self.assertEqual((verdict["steps"], verdict["gap"]), ([step["id"]], gap["id"]))
        # The reason shows once: in the gap, not again as a note of the copied step.
        self.assertEqual(verdict["verdict"], "translated")
        self.assertEqual(gap["after"], step["id"])
        # The gap holds the set left out alone, and only the size it reads.
        self.assertEqual([one["kind"] for one in gap["data"]["sets"]], ["chordLength"])
        self.assertEqual(list(gap["data"]["params"]), ["sets.0.chord_length"])
        self.assertEqual(gap["sizes"], ["pipe_d_mm"])
        self.assertNotIn("bodyBefore", gap)
        self.assertNotIn("corner_mm", loose)
        assert_schema_ok(self, result.recipe)

    def test_the_part_left_out_is_listed_early_and_read_for_later_picks(self):
        result, _ = translated(unmeasured_chord)
        self.assertEqual([step["index"] for step in left_out_preview.find(result).steps], [2])
        self.assertEqual(reach_pass.left_out_indexes(result), [2])

    def test_a_set_left_out_next_to_a_copied_one_leaves_the_whole_step_out(self):
        def touching(data):
            unmeasured_chord(data)
            data["sets"][1]["edges"][0]["box"] = box([40, 0, 0], [40, 20, 10])
        result, _ = translated(touching)
        self.assertEqual(steps_of(result.recipe, "round"), [])
        self.assertEqual(verdict_of(result, 2)["verdict"], "leftOut")

    def test_a_pattern_or_mirror_of_a_step_written_in_part_is_left_out(self):
        def partly(capture, at, keep, far):
            data = capture["items"][at]["data"]
            data["sets"][0]["edges"] = [dict(edge, box=box(edge["points"][0], edge["points"][0]), turn_deg=90.0)
                                        for edge in data["sets"][0]["edges"]][:keep]
            data["sets"].append({"kind": "chordLength", "chord_length": 2.0, "continuity": "tangent",
                                 "input_kinds": ["edge"], "edges": [dict(side("far", *far))]})
        for name, at, keep, far in (("rpattern_fillet", 3, 2, (20, 60)), ("mirror_fillet", 3, 1, (15, 60))):
            with self.subTest(name):
                capture = copy.deepcopy(load_capture(name))
                partly(capture, at, keep, far)
                result = translate(capture)
                self.assertTrue(verdict_of(result, 3)["steps"])
                repeat = verdict_of(result, 4)
                self.assertEqual(repeat["verdict"], "leftOut")
                self.assertEqual([gap["id"] for gap in result.gaps if gap["id"] != repeat["gap"]], ["gap_3"])
                self.assertEqual(next(g for g in result.gaps if g["id"] == repeat["gap"])["dependsOn"], ["gap_3"])


def unread_set(data):
    """Set 1 could not be read (Fusion gave no inputs for it): its edges are not known."""
    data["sets"][0]["edges"] = [side("e0", 0, 0), side("e1", 40, 0)]
    data["sets"][1].update(input_kinds=[], edges=[], tangent_chain=True, read_error="xlFillet")


class UnreadSetTest(unittest.TestCase):
    def test_a_set_whose_edges_are_not_known_leaves_its_step_out_and_the_rest_is_copied(self):
        for name, run_with, kind in (("round", translated, "round"), ("chamfer", chamfered, "bevel")):
            with self.subTest(name):
                result, _ = run_with(unread_set)
                self.assertIsNotNone(result.recipe)
                self.assertEqual(steps_of(result.recipe, kind), [])
                self.assertEqual(verdict_of(result, 2)["verdict"], "leftOut")
                (gap,) = result.gaps
                self.assertEqual(gap["hint"], gap_hints.HINTS[gap_hints.SET_UNREAD])


def chamfer_set(index, *edges, kind="equal"):
    entry = {"kind": kind, "distance": 1.0, "input_kinds": ["edge"], "edges": list(edges)}
    if kind == "twoDistances":
        entry["distance_two"] = 2.0
    return sets_of.ChamferSet(index, entry)


class CopyApartTest(unittest.TestCase):
    """`copy_apart` with a group whose copy fails: its sets are tried one by one only when they lie apart."""

    @staticmethod
    def copy(kept_edges):
        sets = [chamfer_set(0, side("a", 0, 0)), chamfer_set(1, kept_edges),
                chamfer_set(2, side("c", 40, 20), kind="twoDistances")]
        ctx = Context({"items": [], "target": {}})
        item = {"index": 5, "name": "Chamfer1", "data": {"sets": [one.entry for one in sets]}}
        with ctx.recording():
            return set_split.copy_apart(
                ctx, item, sets, lambda one: Refusal("no sides") if one.index == 2 else None, lambda kept: [kept],
                lambda group: Refusal("together") if len(group) > 1 else [Entry({"kind": "bevel"})])

    def test_kept_sets_apart_are_copied_one_by_one(self):
        found = self.copy(side("b", 0, 20))
        self.assertEqual((len(found.entries), found.left_out.gap_item["data"]["sets"][0]["kind"]),
                         (2, "twoDistances"))

    def test_kept_sets_that_meet_are_not_split(self):
        self.assertIsNone(self.copy(dict(side("b", 0, 20), box=box([0, 0, 10], [0, 20, 10]))))


def chamfered(edit):
    capture, ticked = on_fixture("fillet_two_radii", edit)
    data = capture["items"][2]["data"]
    capture["items"][2]["type"] = "ChamferFeature"
    data.pop("rolling_ball", None)
    data["corner_type"] = "chamfer"
    for one in data["sets"]:
        one.pop("radius", None)
        one.pop("continuity", None)
        if one["kind"] == "constant":
            one["kind"] = "equal"
        one.setdefault("distance", 1.0)
    capture["items"][1]["data"]["params"] = {"side_one.distance": param("d1", "wall_mm * 5", 10.0)}
    result, _ = run(capture, ticked)
    return result, [entry["name"] for entry in result.loose]


class ChamferTest(unittest.TestCase):
    def test_chamfer_sets_of_one_size_picked_in_different_ways_are_copied_one_after_the_other(self):
        result, loose = chamfered(chain_and_face)
        first, second = steps_of(result.recipe, "bevel")
        self.assertEqual((first["edges"]["chain"], list(second["edges"])), ("tangent", ["faceEdges"]))
        self.assertEqual(loose, ["wall_mm"])

    def test_an_uneven_chamfer_set_whose_faces_cannot_be_told_is_left_out_alone(self):
        def uneven(data):
            data["sets"][0]["edges"] = [side("e0", 0, 0), side("e1", 40, 0)]
            data["sets"][1] = {"kind": "twoDistances", "distance": 1.0, "distance_two": 2.0, "input_kinds": ["edge"],
                               "edges": [side("e2", 40, 20), side("e3", 0, 20)]}
        result, _ = chamfered(uneven)
        (step,) = steps_of(result.recipe, "bevel")
        self.assertEqual(len(step["edges"]["near"]), 2)
        (gap,) = result.gaps
        self.assertEqual([one["kind"] for one in gap["data"]["sets"]], ["twoDistances"])
        self.assertEqual(verdict_of(result, 2)["gap"], gap["id"])


class ReachTest(unittest.TestCase):
    def test_box_gap_is_the_least_distance_between_edge_boxes(self):
        a = chamfer_set(0, side("a", 0, 0))
        self.assertEqual(sets_of.box_gap(a, chamfer_set(1, side("b", 3, 4))), 5.0)
        self.assertIsNone(sets_of.box_gap(a, chamfer_set(1, {"token": "b", "points": [[9, 0, 5]]})))

    def test_reach_grows_with_the_turn_of_the_faces_and_is_unknown_with_mid_radii(self):
        def round_set(turn, **more):
            entry = dict({"kind": "constant", "radius": 1.0, "continuity": "tangent", "input_kinds": ["edge"],
                          "edges": [side("a", 0, 0, turn)]}, **more)
            return sets_of.RoundSet(0, entry)
        self.assertEqual(sets_of.reach_terms(round_set(90.0)).terms[0][2], 1.0)
        self.assertAlmostEqual(sets_of.reach_terms(round_set(150.0)).terms[0][2], 3.7320508, places=6)
        self.assertIsNone(sets_of.reach_terms(round_set(175.0)))
        changing = dict(kind="variable", start_radius=1.0, end_radius=2.0)
        self.assertIsNotNone(sets_of.reach_terms(round_set(90.0, mid_count=0, **changing)))
        self.assertIsNone(sets_of.reach_terms(round_set(90.0, mid_count=1, **changing)))

    def test_only_sets_keeps_the_sets_and_their_parameters(self):
        item = {"index": 4, "data": {"sets": [{"kind": "a"}, {"kind": "b"}, {"kind": "c"}],
                                     "params": {"sets.0.radius": 1, "sets.2.radius": 3, "other": 9}}}
        gap = sets_of.only_sets(item, [2], renumber=True)
        self.assertEqual((gap["data"]["sets"], gap["data"]["params"]), ([{"kind": "c"}], {"sets.0.radius": 3, "other": 9}))
        kept = sets_of.only_sets(item, [0, 1])
        self.assertEqual((len(kept["data"]["sets"]), kept["data"]["params"]), (3, {"sets.0.radius": 1, "other": 9}))
        self.assertEqual(len(item["data"]["sets"]), 3)


if __name__ == "__main__":
    unittest.main()
