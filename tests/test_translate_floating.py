"""A join that would float in the copy because it sits only on material of left out steps (lib/translator/floating.py)."""
import copy
import unittest

from tests import context  # noqa: F401
from tests.translator_helpers import load_capture

from lib.translator import translate
from lib.translator.notes import floats_reason


def _square(side, frame_z):
    return {"sketch": "Sketch2", "frame": {"origin": [0, 0, frame_z], "x": [1, 0, 0], "y": [0, 1, 0], "z": [0, 0, 1]},
            "loops": [{"outer": True, "curves": [
                {"kind": "line", "start": [0, 0], "end": [side, 0]}, {"kind": "line", "start": [side, 0], "end": [side, side]},
                {"kind": "line", "start": [side, side], "end": [0, side]}, {"kind": "line", "start": [0, side], "end": [0, 0]}]}]}


def capture(base="extrude_plate", join_z=50.0, gap=True):
    """The base body, a step the copy leaves out (a coil that changes the body), then a 4 mm square extrude joined at
    height `join_z`, as the last item. The plate of `extrude_plate` runs from 0 to 10 mm high."""
    found = load_capture(base)
    target = found["items"][-1]["bodies_after"]
    at = len(found["items"])
    coil = {"index": at, "name": "Coil1", "type": "CoilFeature", "suppressed": False, "health": "ok", "message": "",
            "in_target_component": True, "bodies_after": target, "target_changed": True, "data": {}}
    join = copy.deepcopy(load_capture("extrude_plate")["items"][1])
    join.update(index=at + 1 if gap else at, name="Extrude2", bodies_after=target)
    join["data"].update(operation="join", participants=target, profiles=[_square(4.0, join_z)],
                        side_one={"kind": "distance", "distance": 3.0, "taper_deg": 0.0}, end_offset=3.0)
    found["items"] += ([coil] if gap else []) + [join]
    return found


def join_verdict(result):
    return result.items[-1]


class FloatingJoinTest(unittest.TestCase):
    def test_a_join_that_meets_only_material_of_a_left_out_step_is_left_out_too(self):
        result = translate(capture())
        self.assertIsNone(result.refusal)
        self.assertEqual([g["name"] for g in result.gaps], ["Coil1", "Extrude2"])
        self.assertEqual(join_verdict(result)["note"], floats_reason())

    def test_a_join_that_sits_on_the_copied_part_stays(self):
        result = translate(capture(join_z=10.0))
        self.assertEqual(join_verdict(result)["verdict"], "translated")

    def test_a_join_away_from_the_part_stays_when_no_step_was_left_out(self):
        result = translate(capture(gap=False))
        self.assertEqual(join_verdict(result)["verdict"], "translated")

    def test_a_sweep_holds_its_material_within_its_path_grown_by_its_profile(self):
        # The sweep runs 40 mm up from the floor: a join 10 mm above its end floats, one on its end may sit on it.
        self.assertEqual(join_verdict(translate(capture(base="sweep_straight")))["verdict"], "leftOut")
        self.assertEqual(join_verdict(translate(capture(base="sweep_straight", join_z=40.0)))["verdict"], "translated")

    def test_a_join_stays_when_a_written_step_adds_material_the_copy_cannot_bound(self):
        # A revolve's material is not in the translator's model, so the join may sit on it.
        result = translate(capture(base="revolve_full"))
        self.assertEqual(join_verdict(result)["verdict"], "translated")


if __name__ == "__main__":
    unittest.main()
