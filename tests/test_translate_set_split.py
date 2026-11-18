"""Rounds and chamfers whose sets of edges lie apart are copied one after the other (`translator/finishes/set_split.py`).

The fixture is the 40 by 20 by 10 mm box of `fillet_two_radii`: set 0 rounds the side edges at y 0, set 1 those at
y 20. The box height follows `wall_mm`, read before the round, so a pick the copy cannot follow marks `wall_mm`.
"""
import unittest

from tests import context  # noqa: F401
from tests.test_translate_measured_rounds import changing_set, even, sampled
from tests.test_translate_sized import on_fixture, param, run
from tests.translator_helpers import assert_schema_ok, steps_of, verdict_of

from lib.design_model.steps import finish as sets_of
from lib.dialog_model import left_out_preview
from lib.export_plan import reach_pass

TOP = {"token": "top", "point": [20.0, 10.0, 10.0]}


def side(token, x, y):
    """A side edge of the box at (x, y), with its two corners."""
    return {"token": token, "closed": False, "points": [[x, y, 5]], "ends": [[x, y, 0], [x, y, 10]]}


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


class SplitTest(unittest.TestCase):
    def test_sets_picked_in_different_ways_are_copied_one_after_the_other_with_their_own_picks(self):
        result, loose = translated(chain_and_face)
        first, second = steps_of(result.recipe, "round")
        # One point on the seed edge, its height following the box.
        self.assertEqual((first["edges"]["chain"], [p[:2] for p in first["edges"]["near"]]), ("tangent", [[0, 0]]))
        self.assertEqual(list(second["edges"]), ["faceEdges"])
        self.assertEqual(loose, [])
        self.assertEqual(result.gaps, [])
        assert_schema_ok(self, result.recipe)

    def test_sets_that_meet_at_a_corner_or_near_one_stay_one_step(self):
        def meet(corner):
            def edit(data):
                chain_and_face(data)
                data["sets"][1]["edges"][0]["ends"][1] = corner
            return edit
        for name, corner in (("shared corner", [40, 0, 10]), ("corner nearer than the rounds reach", [40, 7, 10])):
            with self.subTest(name):
                result, loose = translated(meet(corner))
                (step,) = steps_of(result.recipe, "round")
                self.assertFalse({"chain", "faceEdges"} & set(step["edges"]))
                self.assertEqual(loose, ["wall_mm"])

    def test_a_capture_without_corners_stays_one_step(self):
        def no_ends(data):
            chain_and_face(data)
            for one in data["sets"]:
                for edge in one["edges"]:
                    del edge["ends"]
        result, loose = translated(no_ends)
        self.assertEqual(len(steps_of(result.recipe, "round")), 1)
        self.assertEqual(loose, ["wall_mm"])

    def test_a_changing_radius_with_another_set_apart_gets_a_step_of_its_own(self):
        def edit(data):
            edge = dict(sampled([0, 0, 10], [40, 0, 10], even(1.0, 3.0)), ends=[[0, 0, 10], [40, 0, 10]])
            data["sets"] = [changing_set(edge), dict(data["sets"][1], edges=[side("e2", 40, 20), side("e3", 0, 20)])]
        result, _ = translated(edit)
        changing, plain = steps_of(result.recipe, "round")
        self.assertEqual((changing["size"], changing["sizeEnd"]), (1.0, 3.0))
        self.assertEqual(plain["size"], 3)
        self.assertEqual(result.gaps, [])


class LeftOutTest(unittest.TestCase):
    @staticmethod
    def unmeasured_chord(data):
        """Set 1 is a round by chord length whose faces were not measured, so it cannot be copied."""
        data["sets"][0]["edges"] = [side("e0", 0, 0), side("e1", 40, 0)]
        data["sets"][1] = {"kind": "chordLength", "chord_length": 2.0, "continuity": "tangent", "input_kinds": ["edge"],
                           "edges": [side("e2", 40, 20), side("e3", 0, 20)]}

    def test_a_set_that_cannot_be_copied_is_left_out_alone(self):
        params = {"sets.0.radius": param("d2", "corner_mm - 1 mm", 2.0),
                  "sets.1.chord_length": param("d3", "pipe_d_mm / 6", 2.0)}
        result, loose = translated(self.unmeasured_chord, params)
        (step,) = steps_of(result.recipe, "round")
        self.assertEqual([p[:2] for p in step["edges"]["near"]], [[0, 0], [40, 0]])
        verdict = verdict_of(result, 2)
        (gap,) = result.gaps
        self.assertEqual((verdict["verdict"], verdict["steps"], verdict["gap"]),
                         ("translatedWithNote", [step["id"]], gap["id"]))
        self.assertEqual(gap["after"], step["id"])
        # The gap holds the set left out alone, and only the size it reads.
        self.assertEqual([one["kind"] for one in gap["data"]["sets"]], ["chordLength"])
        self.assertEqual(list(gap["data"]["params"]), ["sets.0.chord_length"])
        self.assertEqual(gap["sizes"], ["pipe_d_mm"])
        self.assertNotIn("bodyBefore", gap)
        self.assertNotIn("corner_mm", loose)
        assert_schema_ok(self, result.recipe)

    def test_the_part_left_out_is_listed_early_and_read_for_later_picks(self):
        result, _ = translated(self.unmeasured_chord)
        self.assertEqual([step["index"] for step in left_out_preview.find(result).steps], [2])
        self.assertEqual(reach_pass.left_out_indexes(result), [2])

    def test_a_set_left_out_next_to_a_copied_one_leaves_the_whole_step_out(self):
        def touching(data):
            self.unmeasured_chord(data)
            data["sets"][1]["edges"][0]["ends"][0] = [40, 0, 0]
        result, _ = translated(touching)
        self.assertEqual(steps_of(result.recipe, "round"), [])
        self.assertEqual(verdict_of(result, 2)["verdict"], "leftOut")


def as_chamfer(edit):
    """`edit` on the round, then the round as a chamfer of 1 mm on each set."""
    def chamfer(data):
        edit(data)
        data.pop("rolling_ball", None)
        data["corner_type"] = "chamfer"
        for one in data["sets"]:
            for key in ("radius", "continuity"):
                one.pop(key, None)
            one.setdefault("kind", "equal")
            if one["kind"] == "constant":
                one["kind"] = "equal"
            one.setdefault("distance", 1.0)
    return chamfer


def chamfered(edit):
    capture, ticked = on_fixture("fillet_two_radii", as_chamfer(edit))
    capture["items"][2]["type"] = "ChamferFeature"
    capture["items"][1]["data"]["params"] = {"side_one.distance": param("d1", "wall_mm * 5", 10.0)}
    result, _ = run(capture, ticked)
    return result, [entry["name"] for entry in result.loose]


class ChamferTest(unittest.TestCase):
    def test_chamfer_sets_of_one_size_picked_in_different_ways_are_copied_one_after_the_other(self):
        result, loose = chamfered(chain_and_face)
        first, second = steps_of(result.recipe, "bevel")
        self.assertEqual((first["edges"]["chain"], list(second["edges"])), ("tangent", ["faceEdges"]))
        self.assertEqual(loose, [])

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


class ApartTest(unittest.TestCase):
    def test_sets_are_apart_only_when_their_corners_lie_beyond_twice_their_reaches(self):
        def round_set(*edges):
            return sets_of.RoundSet(0, {"kind": "constant", "radius": 1.0, "continuity": "tangent",
                                        "input_kinds": ["edge"], "edges": list(edges)})
        a = round_set(side("a", 0, 0))
        for name, x, expected in (("far", 4.5, True), ("near", 3.5, False), ("same corner", 0, False)):
            with self.subTest(name):
                self.assertEqual(sets_of.apart(a, round_set(side("b", x, 0))), expected)
        self.assertFalse(sets_of.apart(a, round_set({"token": "b", "closed": False, "points": [[9, 0, 5]]})))

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
