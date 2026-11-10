"""Measured references of other components over the probe states: what is asked, what is fitted, what is refused."""
import unittest

from tests import context  # noqa: F401
from tests.probe_helpers import capture, state, table
from tests.test_probe_motion import CAPTURE, MODEL, PARAMS, TICKED, read_at

from lib.probe import plan, ref_fit
from lib.probe.build import build
from lib.sketch_values import coverage
from lib.sketch_values.motion import Affine, Motion, Stuck

COVER = {"token": "cmp_cover", "name": "Cover"}


def plane_ref(**extra):
    return dict({"slot": "plane", "type": "ConstructionPlane", "token": "cp9", "component": COVER, "path": "Cover:1",
                 "point": [0, 0, 20], "normal": [0, 0, 1]}, **extra)


def axis_ref(**extra):
    return dict({"slot": "axis", "type": "ConstructionAxis", "token": "ax9", "component": COVER, "path": "Cover:1",
                 "point": [10, 0, 0], "dir": [0, 0, 1]}, **extra)


def step(index, kind, key, ref):
    return {"index": index, "name": "Step%d" % index, "type": kind, "data": {key: dict(ref, assembly=True, ref=ref)}}


def with_refs(*items):
    return capture(*CAPTURE["items"], *items)


MIRROR = step(8, "MirrorFeature", "plane", plane_ref())
PATTERN = step(9, "CircularPatternFeature", "axis", axis_ref())


def read(refs=None, **sizes):
    out = read_at(**sizes)
    if refs is not None:
        out["refs"] = refs
    return out


def at(refs, **sizes):
    return state(sizes, read(refs, **sizes))


def plane_at(z, normal=(0, 0, 1)):
    return {"8.plane": {"point": [0, 0, z], "normal": list(normal)}}


def with_e0(refs, *states):
    return [state({}, read(refs), e0=True)] + list(states)


def run(items, states):
    return build(with_refs(*items), table(PARAMS, TICKED, MODEL), states)


class RefsOfACaptureTest(unittest.TestCase):
    def test_each_reference_gets_a_key_and_what_of_it_is_followed(self):
        point = step(10, "HoleFeature", "x", {})
        point["data"] = {"position_refs": [
            {"slot": "positions.0", "type": "SketchPoint", "token": "pt", "component": COVER, "point": [1, 2, 3]},
            {"slot": "positions.0", "type": "BRepEdge", "token": "ed", "component": COVER},
            {"slot": "positions.0", "type": "SketchPoint", "component": COVER, "point": [1, 2, 3]}]}
        direction = {"slot": "direction_one", "type": "ConstructionAxis", "token": "ax", "dir": [1, 0, 0]}
        found = plan.refs(with_refs(MIRROR, PATTERN, point,
                                    {"index": 11, "name": "Pattern2", "type": "RectangularPatternFeature",
                                     "data": {"direction_one_place": {"assembly": True, "ref": direction}}}))
        self.assertEqual([(r["key"], r["shape"]) for r in found],
                         [("8.plane", "plane"), ("9.axis", "axis"), ("10.positions.0", "point"),
                          ("10.positions.1", None), ("10.positions.2", None), ("11.direction_one", "direction")])
        self.assertEqual([r["reason"] for r in found[3:5]], [plan.NO_PLACE, plan.NO_TOKEN])

    def test_a_step_that_is_suppressed_or_in_another_component_has_no_references(self):
        for edit in ({"suppressed": True}, {"in_target_component": False}):
            with self.subTest(edit):
                self.assertEqual(plan.refs(with_refs(dict(MIRROR, **edit))), [])

    def test_the_request_lists_the_references_to_read_and_can_be_limited(self):
        items = [MIRROR, PATTERN]
        tbl = table(PARAMS, TICKED, MODEL)
        wanted = plan.request(with_refs(*items), tbl)["refs"]
        self.assertEqual(wanted["8.plane"], {"token": "cp9", "type": "ConstructionPlane", "path": "Cover:1",
                                             "shape": "plane"})
        self.assertEqual(list(plan.request(with_refs(*items), tbl, wanted={"9.axis"})["refs"]), ["9.axis"])
        self.assertNotIn("refs", plan.request(CAPTURE, tbl))


class PlaneTest(unittest.TestCase):
    def test_a_plane_that_follows_a_size_gets_a_formula_for_its_move(self):
        motion = run([MIRROR], with_e0(plane_at(20), at(plane_at(30), height=30), at(plane_at(50), height=50),
                                       at(plane_at(20), cube=20)))
        value = motion.get("8/r/plane/offset")
        self.assertIsInstance(value, Affine)
        self.assertEqual(value.terms, {"height": 1.0})
        self.assertAlmostEqual(value.value({"height": 20.0}), 0.0)
        self.assertAlmostEqual(value.value({"height": 35.0}), 15.0)
        self.assertEqual(motion.refs, {"8.plane": ""})

    def test_a_plane_that_does_not_move_is_measured_and_has_no_key(self):
        motion = run([MIRROR], with_e0(plane_at(20), at(plane_at(20), height=30), at(plane_at(20), cube=20)))
        self.assertEqual(motion.refs, {"8.plane": ""})
        self.assertFalse([k for k in motion.values if "/r/" in k])

    def test_a_move_along_the_plane_is_not_a_move(self):
        slid = {"8.plane": {"point": [5, 7, 20], "normal": [0, 0, 1]}}
        motion = run([MIRROR], with_e0(plane_at(20), at(slid, height=30)))
        self.assertFalse([k for k in motion.values if "/r/" in k])

    def test_a_plane_that_tilts_is_stuck_with_the_sizes_that_tilt_it(self):
        tilted = plane_at(20, (0, 0.6, 0.8))
        motion = run([MIRROR], with_e0(plane_at(20), at(plane_at(30), height=30), at(plane_at(50), height=50),
                                       at(tilted, off=9), at(plane_at(20), cube=20)))
        value = motion.get("8/r/plane/offset")
        self.assertIsInstance(value, Stuck)
        self.assertEqual((value.cause, value.movers), ("turns", ("off",)))
        self.assertEqual(value.rest.terms, {"height": 1.0})

    def test_a_state_that_does_not_read_the_plane_is_stuck_for_its_sizes(self):
        motion = run([MIRROR], with_e0(plane_at(20), at({}, off=9), at(plane_at(30), height=30),
                                       at(plane_at(50), height=50)))
        value = motion.get("8/r/plane/offset")
        self.assertEqual((value.cause, value.movers), ("unread", ("off",)))

    def test_a_state_fusion_could_not_build_is_left_out(self):
        broken = state({"height": 99}, None, built=False)
        motion = run([MIRROR], with_e0(plane_at(20), broken, at(plane_at(30), height=30), at(plane_at(50), height=50)))
        self.assertEqual(motion.get("8/r/plane/offset").terms, {"height": 1.0})

    def test_a_move_that_is_no_formula_of_the_sizes_is_stuck(self):
        curved = [at(plane_at(20 + (h - 20) ** 2 / 10), height=h) for h in (30, 40, 50)]
        value = run([MIRROR], with_e0(plane_at(20), *curved)).get("8/r/plane/offset")
        self.assertIsInstance(value, Stuck)
        self.assertEqual(value.movers, ("height",))


class StartReadTest(unittest.TestCase):
    def test_a_first_read_that_differs_from_the_capture_is_not_followed(self):
        motion = run([MIRROR], with_e0(plane_at(21), at(plane_at(31), height=30), at(plane_at(51), height=50)))
        self.assertEqual(motion.refs, {"8.plane": ref_fit.NOT_MATCHED})
        self.assertFalse([k for k in motion.values if "/r/" in k])

    def test_a_reference_the_reader_could_not_read_gives_the_readers_reason(self):
        first = read({})
        first["unread"] = {"8.plane": "It was not found."}
        motion = run([MIRROR], [state({}, first, e0=True)])
        self.assertEqual(motion.refs, {"8.plane": "It was not found."})

    def test_without_a_first_read_nothing_is_measured(self):
        motion = run([MIRROR], [state({}, None, e0=True)])
        self.assertEqual(motion.refs, {"8.plane": ref_fit.NOT_LOOKED_AT})

    def test_a_reference_the_probe_cannot_follow_says_why(self):
        bare = step(8, "MirrorFeature", "plane", plane_ref())
        del bare["data"]["plane"]["ref"]["point"]
        motion = run([bare], with_e0(None))
        self.assertEqual(motion.refs, {"8.plane": plan.NO_PLACE})

    def test_a_motion_of_a_capture_without_references_has_none(self):
        motion = build(CAPTURE, table(PARAMS, TICKED, MODEL), with_e0(None))
        self.assertEqual(motion.refs, {})
        self.assertNotIn("refs", motion.json())


class AxisAndPointTest(unittest.TestCase):
    def axis_at(self, x, z=0):
        return {"9.axis": {"point": [x, 0, z], "dir": [0, 0, 1]}}

    def test_an_axis_follows_its_move_across_its_direction_only(self):
        motion = run([PATTERN], with_e0(self.axis_at(10, 0), at(self.axis_at(14, 30), off=9),
                                        at(self.axis_at(10, 77), height=40), at(self.axis_at(8, 5), off=3)))
        value = motion.get("9/r/axis/point/0")
        self.assertEqual(value.terms, {"off": 1.0})
        self.assertAlmostEqual(value.value({"off": 9.0}), 4.0)
        self.assertEqual([k for k in motion.values if "/r/" in k], ["9/r/axis/point/0"])

    def test_an_axis_that_turns_is_stuck_on_every_coordinate(self):
        bent = {"9.axis": {"point": [10, 0, 0], "dir": [0, 1, 0]}}
        motion = run([PATTERN], with_e0(self.axis_at(10), at(bent, off=9)))
        stuck = [motion.get("9/r/axis/point/%d" % c) for c in range(3)]
        self.assertEqual({(v.cause, v.movers) for v in stuck}, {("turns", ("off",))})

    def test_a_point_follows_each_coordinate(self):
        point = step(10, "HoleFeature", "x", {})
        point["data"] = {"position_refs": [{"slot": "positions.0", "type": "SketchPoint", "token": "pt",
                                            "component": COVER, "point": [1, 2, 3]}]}
        here = lambda x, z: {"10.positions.0": {"point": [x, 2, z]}}  # noqa: E731
        motion = run([point], with_e0(here(1, 3), at(here(6, 3), off=10), at(here(3, 3), off=7),
                                      at(here(1, 13), height=30), at(here(1, 33), height=50),
                                      at(here(1, 3), cube=20)))
        self.assertEqual(motion.get("10/r/positions.0/point/0").terms, {"off": 1.0})
        self.assertEqual(motion.get("10/r/positions.0/point/2").terms, {"height": 1.0})
        self.assertIsNone(motion.get("10/r/positions.0/point/1"))

    def test_a_direction_that_stays_has_no_key_and_one_that_turns_is_stuck(self):
        place = {"slot": "direction_one", "type": "ConstructionAxis", "token": "ax", "component": COVER, "dir": [1, 0, 0]}
        item = {"index": 11, "name": "Pattern2", "type": "RectangularPatternFeature",
                "data": {"direction_one_place": {"assembly": True, "dir": [1, 0, 0], "ref": place}}}
        still = {"11.direction_one": {"dir": [1, 0, 0]}}
        bent = {"11.direction_one": {"dir": [0, 1, 0]}}
        motion = run([item], with_e0(still, at(still, off=9)))
        self.assertEqual((motion.refs, [k for k in motion.values if "/r/" in k]), ({"11.direction_one": ""}, []))
        motion = run([item], with_e0(still, at(bent, off=9)))
        self.assertEqual(motion.get("11/r/direction_one/dir").cause, "turns")


class MotionFileTest(unittest.TestCase):
    def setUp(self):
        self.table = table(PARAMS, TICKED, MODEL)
        self.motion = run([MIRROR, PATTERN], with_e0(
            {**plane_at(20), "9.axis": {"point": [10, 0, 0], "dir": [0, 0, 1]}},
            at({**plane_at(30), "9.axis": {"point": [10, 0, 0], "dir": [0, 0, 1]}}, height=30),
            at({**plane_at(50), "9.axis": {"point": [10, 0, 0], "dir": [0, 0, 1]}}, height=50)))

    def test_references_are_saved_and_loaded_with_their_values(self):
        again = Motion.from_json(self.motion.json())
        self.assertEqual(again.refs, {"8.plane": "", "9.axis": ""})
        self.assertEqual(again.get("8/r/plane/offset").terms, {"height": 1.0})

    def test_the_three_answers_for_a_size_and_a_reference(self):
        answer = lambda key, size: coverage.ref_answer(self.table, self.motion, key, size)  # noqa: E731
        self.assertEqual((answer("8.plane", "height").kind, answer("8.plane", "height").keys),
                         (coverage.MOVED, ("8/r/plane/offset",)))
        self.assertEqual(answer("8.plane", "cube").kind, coverage.STILL)
        self.assertEqual(answer("9.axis", "height").kind, coverage.STILL)
        self.assertEqual(answer("7.plane", "height").reason, coverage.NOT_LOOKED)
        self.motion.refs["9.axis"] = "its first read did not match the capture"
        self.assertEqual(answer("9.axis", "height").kind, coverage.NOT_MEASURED)
        self.motion.untried = ["cube"]
        self.assertEqual(answer("8.plane", "cube").reason, coverage.NOT_TRIED)


if __name__ == "__main__":
    unittest.main()
