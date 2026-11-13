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


def _join(index, name, target, side, at, height):
    """A `side` mm square extrude joined from `at` ([x, y, z] of its corner), `height` mm up."""
    join = copy.deepcopy(load_capture("extrude_plate")["items"][1])
    square = _square(side, at[2])
    square["frame"]["origin"] = list(at)
    join.update(index=index, name=name, bodies_after=target)
    join["data"].update(operation="join", participants=target, profiles=[square],
                        side_one={"kind": "distance", "distance": height, "taper_deg": 0.0}, end_offset=height)
    return join


def capture(base="extrude_plate", join_z=50.0, gap=True, before=(), side=4.0, corner=(0, 0), height=3.0):
    """The base body, the joins `before` (`(side, [x, y, z], height)` each), a step the copy leaves out (a coil that
    changes the body), then a `side` mm square extrude joined at height `join_z`, as the last item. The plate of
    `extrude_plate` runs from 0 to 10 mm high."""
    found = load_capture(base)
    target = found["items"][-1]["bodies_after"]
    for n, (post_side, post_at, post_height) in enumerate(before):
        found["items"].append(_join(len(found["items"]), "Post%d" % (n + 1), target, post_side, post_at, post_height))
    at = len(found["items"])
    coil = {"index": at, "name": "Coil1", "type": "CoilFeature", "suppressed": False, "health": "ok", "message": "",
            "in_target_component": True, "bodies_after": target, "target_changed": True, "data": {}}
    join = _join(at + 1 if gap else at, "Extrude2", target, side, [corner[0], corner[1], join_z], height)
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

    def test_a_left_out_join_depends_on_the_gap_that_grew_the_body_out_to_it(self):
        found = capture()
        coil = found["items"][-2]
        tall = copy.deepcopy(coil)
        tall.update(name="Coil0", index=coil["index"])
        coil["index"] += 1
        found["items"][-1]["index"] += 1

        def body(top, volume):
            return {"box": {"min": [0, 0, 0], "max": [40, 20, top]}, "volume_mm3": volume}

        # Coil0 grows the body up to the join at 50 mm; Coil1 adds material lower down, after it.
        tall.update(target_before=body(10, 8000.0), target_after=body(60, 9000.0))
        coil.update(target_before=body(60, 9000.0), target_after=body(60, 9500.0))
        found["items"].insert(len(found["items"]) - 2, tall)
        gaps = {g["name"]: g for g in translate(found).gaps}
        self.assertEqual(gaps["Extrude2"]["dependsOn"], [gaps["Coil0"]["id"]])

    def test_a_join_that_sits_on_the_copied_part_stays(self):
        result = translate(capture(join_z=10.0))
        self.assertEqual(join_verdict(result)["verdict"], "translated")

    def test_a_join_that_encloses_copied_material_stays(self):
        # A 2 mm post from 50 to 52 mm high, then an 8 mm join from 48 to 54 mm round it: no face of the join comes
        # near the post.
        result = translate(capture(before=[(2.0, [0, 0, 50], 2.0)], join_z=48.0, side=8.0, corner=(-3, -3),
                                   height=6.0))
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
