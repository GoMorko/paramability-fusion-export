"""Bodies made by Copy and Paste in the Orca copy (`orca_translate/paste.py`, with the facts of
`design_model/steps/paste.py`).

The captures come from `tests/orca_pastes.py`. The recipe is read back with `orca_cuts.Section`, and its volume is
counted on a 1 mm grid of cell centres, which is exact for the square bodies of these captures.
"""
import unittest

from tests import context  # noqa: F401
from tests import orca_pastes as op
from tests.orca_extents import B1 as PLATE_BODY
from tests.orca_extents import UP, at, capture, extrude, profile, rect, side, sketch_item
from tests.orca_outline import finish
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


def pasted_onto_itself(later, moved):
    """A 40 x 20 x 4 plate (Extrude1) with a 4 x 4 x 2 boss joined on it (Extrude2), pasted as Body3, moved 30 mm
    along Y when `moved`, then the steps `later` on Body3 and a Combine that joins Body3 to the plate."""
    plate = op.corners(0.0, 0.0, 0.0, 40.0, 20.0, 4.0)
    boss = extrude(3, "Extrude2", [profile("Sketch2", at(4.0), rect(2.0, 2.0, 6.0, 6.0))], operation="join",
                   side_one=side(2.0), end_offset=2.0)
    items = [sketch_item(0, "Sketch1"),
             extrude(1, "Extrude1", [profile("Sketch1", UP, rect(0.0, 0.0, 40.0, 20.0))], side_one=side(4.0),
                     end_offset=4.0),
             sketch_item(2, "Sketch2"), boss, dict(op.paste_item(plate, source=PLATE_BODY), index=4)]
    steps = ([op.move_item(plate, [0.0, 30.0, 0.0])] if moved else []) + list(later)
    steps.append(op.combine_item("join", 3232.0, 3232.0, 6464.0, tools=(op.B3,)))
    items += [dict(found, index=5 + n) for n, found in enumerate(steps)]
    return capture(items, ((0.0, 0.0, 0.0), (40.0, 50.0 if moved else 20.0, 6.0)), 6464.0 if moved else 3232.0)


def boss_pattern():
    """A pattern of features of Extrude2 on Body3: two copies 10 mm apart along X."""
    elements = [{"id": k, "suppressed": False, "frame": {"origin": [10.0 * k, 0.0, 0.0], "x": [1.0, 0.0, 0.0],
                                                          "y": [0.0, 1.0, 0.0], "z": [0.0, 0.0, 1.0]}}
                for k in range(2)]
    found = step_of("RectangularPatternFeature", "RectangularPattern1", op.B3, 0)
    found["data"] = {"entity_type": "features", "sources": [op.PEG], "direction_one": [1.0, 0.0, 0.0],
                     "quantity_one": 2, "distance_one": 10.0, "direction_two": None, "quantity_two": 1,
                     "distance_two": 0.0, "distance_type": "spacing", "symmetric_one": False,
                     "symmetric_two": False, "elements": elements, "suppressed_ids": [],
                     "direction_one_place": {"origin": True, "own": True}}
    return found


class PastedOntoItselfTest(unittest.TestCase):
    """The part pasted onto itself: its steps are written twice, and later steps of the copy must not take the
    part's features for the copy's."""

    def test_a_pattern_of_features_on_the_copy_leaves_the_combine_out(self):
        for moved in (True, False):
            result = run(pasted_onto_itself([boss_pattern()], moved))
            gap = left_out(result)
            self.assertEqual(gap["cause"], causes.NOT_REPEATABLE)
            self.assertEqual(of_type(result, FeatureType.PATTERN), [])

    def test_a_round_on_the_copy_redraws_the_outline_of_the_copy_and_not_of_the_part(self):
        fillet = finish(0, "Fillet1", [([(0.0, 0.0, 2.0), (40.0, 0.0, 2.0), (40.0, 20.0, 2.0), (0.0, 20.0, 2.0)],
                                        1.0)])
        fillet["bodies_after"] = [dict(op.B3)]
        result = run(pasted_onto_itself([fillet], moved=False))
        self.assertEqual(result.left_out, [])
        part_sketch, copy_sketch = [f for f in of_type(result, FeatureType.SKETCH) if f.name == "Extrude1 sketch"]
        self.assertEqual(len(part_sketch.entities or []), 0)
        self.assertEqual(len(copy_sketch.entities), 8)


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
