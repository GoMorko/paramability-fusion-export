"""Bodies made by Copy and Paste in the Orca copy (`orca_translate/paste.py`, with the facts of
`design_model/steps/paste.py`).

The captures come from `tests/orca_pastes.py`. The recipe is read back with `orca_cuts.Section`, and its volume is
counted on a 1 mm grid of cell centres, which is exact for the square bodies of these captures.
"""
import unittest

from tests import context  # noqa: F401
from tests import orca_pastes as op
from tests.orca_extents import B1 as PLATE_BODY
from tests.orca_extents import at, extrude, profile, rect, side
from tests.test_orca_body_patterns import holds, left_out, of_type, run, volume
from tests.translator_helpers import verdict_of

from lib.capture_model import gap_hints
from lib.orca_recipe.enums import BooleanMode, FeatureType
from lib.orca_translate import causes

BOX = {"min": [-2, -2, -4], "max": [44, 24, 18]}


def item(capture, index):
    return next(i for i in capture["items"] if i["index"] == index)


def peg_points(z0=4.0, z1=10.0):
    x, y = op.PEG_AT
    return op.corners(x - op.HALF, y - op.HALF, z0, x + op.HALF, y + op.HALF, z1)


def insert(capture, at, extra):
    """Put `extra` at timeline index `at` and move the steps from there one place on."""
    for later in capture["items"]:
        if later["index"] >= at:
            later["index"] += 1
    capture["items"].insert(at, dict(extra, index=at))
    return capture


def step_of(kind, name, body, index):
    return {"index": index, "name": name, "type": kind, "suppressed": False, "health": "ok",
            "in_target_component": True, "bodies_after": [dict(body)], "data": {}}


class CopiedTest(unittest.TestCase):
    def test_a_pasted_peg_moved_and_joined_is_built_again_and_follows_the_height_of_its_source(self):
        capture = op.pasted_peg()
        result = run(capture)
        self.assertEqual(result.left_out, [])
        self.assertEqual(len(of_type(result, FeatureType.TRANSFORM)), 1)
        self.assertEqual([b.mode for b in of_type(result, FeatureType.BOOLEAN)], [BooleanMode.ADD] * 2)
        self.assertEqual(verdict_of(result, op.PASTE)["verdict"], "copied")
        for peg_h in (6.0, 10.0):
            self.assertEqual(volume(result, BOX, {"peg_h": peg_h}), op.expected("pasted_peg", peg_h)["volume_mm3"])
        self.assertTrue(holds(result, [28.0, 10.0, 7.0]))
        self.assertEqual({p["name"]: p["outcome"] for p in result.parameters}, {"peg_h": "variable"})

    def test_a_pasted_cutter_moved_and_cut_makes_its_own_pocket(self):
        result = run(op.pasted_cutter())
        self.assertEqual(result.left_out, [])
        for cut_h in (8.0, 10.0, 4.0):
            self.assertEqual(volume(result, BOX, {"cut_h": cut_h}),
                             op.expected("pasted_cutter", cut_h)["volume_mm3"])
        self.assertFalse(holds(result, [28.0, 10.0, 3.0]))

    def test_steps_of_the_source_after_the_paste_do_not_reach_the_copy(self):
        capture = op.pasted_peg()
        taller = extrude(0, "Extrude3", [profile("Sketch2", at(10.0), rect(5.0, 7.0, 11.0, 13.0))],
                         operation="join", side_one=side(4.0), end_offset=4.0)
        taller["bodies_after"], taller["data"]["participants"] = [dict(op.B2)], [dict(op.B2)]
        insert(capture, op.PASTE + 1, taller)
        result = run(capture)
        self.assertEqual(result.left_out, [])
        self.assertTrue(holds(result, [8.0, 10.0, 12.0]))
        self.assertFalse(holds(result, [28.0, 10.0, 12.0]))
        self.assertEqual(volume(result, BOX), 3632.0 + 144.0)

    def test_an_exported_body_that_is_pasted_is_built_from_its_source(self):
        capture = op.pasted_peg()
        capture["items"] = capture["items"][:op.MOVE + 1]
        capture["target"] = dict(op.B3, box={"min": [25.0, 7.0, 4.0], "max": [31.0, 13.0, 10.0]}, volume_mm3=216.0)
        result = run(capture)
        self.assertEqual(result.left_out, [])
        self.assertEqual(verdict_of(result, op.PEG)["verdict"], "copied")
        self.assertEqual(volume(result, BOX), 216.0)
        self.assertTrue(holds(result, [28.0, 10.0, 7.0]))

    def test_the_part_pasted_onto_itself_is_joined_to_a_copy_of_itself(self):
        capture = op.pasted_peg()
        plate = op.corners(0.0, 0.0, 0.0, 40.0, 20.0, 4.0)
        capture["items"] = capture["items"][:op.PLATE + 1] + [
            dict(op.paste_item(plate, source=PLATE_BODY), index=2),
            dict(op.move_item(plate, [0.0, 0.0, 4.0]), index=3),
            dict(op.combine_item("join", 3200.0, 3200.0, 6400.0, tools=(op.B3,)), index=4)]
        capture["parameters"] = {"user": [], "model": []}
        capture["target"].update(box={"min": [0.0, 0.0, 0.0], "max": [40.0, 20.0, 8.0]}, volume_mm3=6400.0)
        result = run(capture)
        self.assertEqual(result.left_out, [])
        self.assertEqual(volume(result, BOX), 6400.0)


class LeftOutTest(unittest.TestCase):
    def test_a_source_of_another_component_leaves_the_combine_out(self):
        capture = op.pasted_peg()
        item(capture, op.PASTE)["data"]["sources"][0].update(foreign=True, component={"token": "c2", "name": "Lid"})
        gap = left_out(run(capture))
        self.assertEqual((gap["index"], gap["cause"]), (op.COMBINE, gap_hints.MADE_IN_OTHER_COMPONENT))

    def test_two_pasted_bodies_that_cannot_be_told_apart_leave_the_combine_out(self):
        capture = op.pasted_peg()
        data = item(capture, op.PASTE)["data"]
        other = {"token": "t9", "name": "Body9"}
        data["sources"].append(dict(other, points=peg_points()))
        moved = op.shifted(peg_points(), [0.0, 30.0, 0.0])
        data["result_bodies"] = [dict(op.B3, points=moved), dict(other, token="t8", points=moved)]
        item(capture, op.MOVE)["data"]["points_before"] = [moved]
        gap = left_out(run(capture))
        self.assertEqual((gap["index"], gap["cause"]), (op.COMBINE, gap_hints.REFUSED))

    def test_a_pasted_body_away_from_its_source_leaves_the_combine_out(self):
        capture = op.pasted_peg()
        data = item(capture, op.PASTE)["data"]
        data["result_bodies"][0]["points"] = op.shifted(peg_points(), [0.0, 5.0, 0.0])
        gap = left_out(run(capture))
        self.assertEqual((gap["index"], gap["cause"]), (op.COMBINE, causes.PASTE_PLACE))

    def test_a_source_with_a_step_the_copy_leaves_out_leaves_the_combine_out(self):
        capture = op.pasted_peg()
        item(capture, op.COMBINE)["data"]["tools"] = [dict(op.B3, volume=216.0)]
        insert(capture, op.PASTE, step_of("ShellFeature", "Shell1", op.B2, 0))
        result = run(capture)
        gap = left_out(result)
        self.assertEqual((gap["index"], gap["cause"]), (op.COMBINE + 1, gap_hints.AFTER_GAP))
        self.assertEqual(volume(result, BOX), 3200.0)

    def test_a_later_step_of_the_pasted_body_the_copy_leaves_out_leaves_the_combine_out(self):
        capture = insert(op.pasted_peg(), op.PASTE + 1, step_of("ScaleFeature", "Scale1", op.B3, 0))
        gap = left_out(run(capture))
        self.assertEqual((gap["index"], gap["cause"]), (op.COMBINE + 1, gap_hints.SCALE))

if __name__ == "__main__":
    unittest.main()
