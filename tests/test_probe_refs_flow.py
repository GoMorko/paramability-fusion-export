"""The size probe with a step that uses a plane of another component: request, rows, motion, discovery, restore."""
import unittest

from tests import context  # noqa: F401
from tests.fakes import FakeStore
from tests.probe_helpers import capture, model, size, table, user
from tests.test_probe_flow import START, Fusion, number, states
from tests.test_probe_motion import CAPTURE, MODEL, PARAMS, TICKED, read_at
from tests.test_probe_refs import MIRROR, plane_at, with_refs
from tests.test_translate_ref_motion import marked, motion_with, run as translate_with
from tests.translator_helpers import load_capture

from lib.design_edit.runner import RowExport
from lib.export_plan.probe_flow import SizeProbe, covers_a_sketch
from lib.probe import plan
from lib.sketch_values.motion import Motion
from lib.translator.sizes import probed_sizes

UNITS = {"count": "", "cube": "mm", "off": "mm", "height": "mm", "gap": "mm"}
LINK = {"param": "gap", "sketch": "", "component": "Cover", "via": "reference", "step": "Mirror1", "ref": "8.plane"}
CAPTURED = with_refs(MIRROR)


class Cover(Fusion):
    """The Cover plane sits 20 mm up and follows `gap` twice over (a step of 2 mm per mm); `start` is where it sits
    when the capture is read; `edit(refs, gap)` changes what the reader gives."""

    def __init__(self, start=20, edit=None):
        super().__init__()
        self.store = FakeStore(dict(START, gap="4 mm"))
        self.start, self.edit = start, edit

    def read(self, request):
        out = super().read(request)
        if request.get("refs"):
            gap = number(self.store.exprs["gap"])
            refs = {"8.plane": plane_at(self.start + (gap - 4) * 2)["8.plane"]}
            if self.edit:
                self.edit(refs, gap)
            out["refs"] = refs
        return out


def run(fusion, probe, sizes):
    rows = probe.probe_rows(sizes)
    rows += probe.far_rows(sizes, plan.MAX_PROBE_ROWS - len(rows))
    reads = []
    job = RowExport(fusion.store, UNITS, lambda path: reads.append(probe.read_now()))
    results = job.run(rows, "", lambda *a: True, tolerate_build_errors=True)
    probe.add_states(states([{p: r["state"][p] for p in r["varied"]} for r in rows], results, reads))
    return rows


class RefProbeTest(unittest.TestCase):
    def setUp(self):
        self.params = PARAMS + [user("gap", "4 mm", 4)]
        self.table = table(self.params, TICKED + ["gap"], MODEL).with_links([LINK])
        self.sizes = [size(self.table, n, UNITS[n]) for n in TICKED + ["gap"]]

    def start(self, fusion, captured=CAPTURED):
        probe = SizeProbe.start(captured, self.table, fusion.read)
        self.assertIsNotNone(probe)
        return probe

    def test_a_size_that_acts_on_the_reference_gets_rows_and_the_plane_a_formula(self):
        fusion = Cover()
        probe = self.start(fusion)
        self.assertIn("gap", probed_sizes(self.table))
        rows = run(fusion, probe, self.sizes)
        self.assertIn("gap (max)", [r["name"] for r in rows])
        self.assertEqual(probe.finish(probe.read_now(), {}), [])
        value = probe.motion.get("8/r/plane/offset")
        self.assertEqual(value.terms, {"gap": 2.0})
        self.assertEqual(probe.motion.refs, {"8.plane": ""})
        self.assertEqual(Motion.from_json(probe.report()["motion"]).refs, {"8.plane": ""})
        self.assertIn("refs", probe.report()["states"][1]["read"])
        self.assertEqual(probe.restore_gap_mm, 0.0)
        self.assertEqual(fusion.store.exprs, dict(START, gap="4 mm"))

    def test_a_reference_that_does_not_read_back_as_captured_is_not_read_again_and_says_so(self):
        fusion = Cover(start=21)
        probe = self.start(fusion)
        self.assertEqual((probe.refs, "refs" in probe.request), ([], False))
        run(fusion, probe, self.sizes)
        probe.finish(probe.read_now(), {})
        self.assertEqual(list(probe.motion.refs), ["8.plane"])
        self.assertNotEqual(probe.motion.refs["8.plane"], "")
        self.assertNotIn("refs", fusion.requests[-1])

    def test_the_restore_gap_counts_a_reference_that_did_not_come_back(self):
        fusion = Cover()
        probe = self.start(fusion)
        far = dict(read_at(), refs=plane_at(23.5))
        self.assertAlmostEqual(probe.measure_restore(far), 3.5)
        self.assertEqual(probe.measure_restore(dict(read_at(), refs={})), 0.0)

    def test_an_unticked_size_that_moves_the_reference_is_found_by_its_try(self):
        fusion = Cover()
        probe = self.start(fusion)
        moved, still = dict(read_at(), refs=plane_at(24)), dict(read_at(), refs=plane_at(20))
        probe.discover([({"varied": ["gap"]}, {}, moved), ({"varied": ["cube"]}, {}, still),
                        ({"varied": ["off"]}, {}, dict(read_at(), refs={}))])
        # A try whose read lacks the place is not a move: nothing was compared there.
        self.assertEqual(probe.also_changes, ["gap"])
        self.assertEqual([d["unread"] for d in probe.discovery], [[], [], ["8.plane"]])

    def test_references_alone_are_enough_to_start_a_probe(self):
        self.assertTrue(covers_a_sketch(capture(MIRROR)))
        self.assertFalse(covers_a_sketch(capture()))
        fusion = Cover()
        probe = SizeProbe.start(capture(MIRROR), self.table, fusion.read)
        self.assertEqual((probe.request["sketches"], list(probe.request["refs"])), ([], ["8.plane"]))
        self.assertIsNone(SizeProbe.start(capture(MIRROR), self.table, lambda request: {"refs": {}}))


class WallBody(Fusion):
    """Sketches as in `Fusion`, and a body that grows with `wall`, which no sketch or reference shows."""

    def __init__(self, grows=True):
        super().__init__()
        self.store = FakeStore(dict(START, wall="2 mm"))
        self.grows = grows

    def read(self, request):
        out = super().read(request)
        if self.grows and "box" in out:
            wall = number(self.store.exprs["wall"])
            out["box"] = {"min": out["box"]["min"], "max": out["box"]["max"][:2] + [out["box"]["max"][2] + wall]}
        return out


class BodyOnlyTest(unittest.TestCase):
    """A ticked size that changes the body but no sketch or reference the probe follows."""

    def setUp(self):
        self.table = table(PARAMS + [user("wall", "2 mm", 2)], TICKED + ["wall"], MODEL)
        self.units = dict(UNITS, wall="mm")
        self.sizes = [size(self.table, n, self.units[n]) for n in TICKED + ["wall"]]

    def probed(self, fusion, captured=CAPTURE):
        probe = SizeProbe.start(captured, self.table, fusion.read)
        rows = probe.probe_rows(self.sizes, extra=["wall"])
        reads = []
        job = RowExport(fusion.store, self.units, lambda path: reads.append(probe.read_now()))
        results = job.run(rows, "", lambda *a: True, tolerate_build_errors=True)
        probe.add_states(states([{p: r["state"][p] for p in r["varied"]} for r in rows], results, reads))
        probe.finish(probe.read_now(), {})
        return probe

    def test_a_size_that_only_changes_the_body_is_kept_in_the_motion(self):
        probe = self.probed(WallBody())
        self.assertEqual(probe.motion.body_moved, ["wall"])
        self.assertEqual(Motion.from_json(probe.report()["motion"]).body_moved, ["wall"])
        self.assertEqual(self.probed(WallBody(grows=False)).motion.body_moved, [])

    def test_a_size_that_only_sets_a_placed_offset_plane_explains_its_body_change(self):
        plane = {"entity_type": "ConstructionPlane", "token": "cp9", "definition": "ConstructionPlaneOffsetDefinition",
                 "built_on": [{"entity_type": "ConstructionPlane", "token": "xy", "origin": True}]}
        split = {"index": 8, "name": "Split1", "type": "SplitBodyFeature",
                 "data": {"tool": {"kind": "plane", "plane": plane}}}
        offset = model("d9", "wall", 2, kind="constructionPlane", token="cp9")
        for label, extra, moved in (("plane alone", [], []),
                                    ("also a step value", [model("d10", "wall", 2, kind="feature")], ["wall"])):
            with self.subTest(label):
                self.table = table(PARAMS + [user("wall", "2 mm", 2)], TICKED + ["wall"], MODEL + [offset] + extra)
                probe = self.probed(WallBody(), dict(CAPTURE, items=CAPTURE["items"] + [split]))
                self.assertEqual(probe.motion.body_moved, moved)

    def test_a_size_that_changes_the_body_is_not_dropped_as_changing_nothing(self):
        motion = motion_with("component_ref_reach")
        motion.body_moved = ["ear_mm"]
        result = translate_with(load_capture("component_ref_reach"), motion)
        (ear,) = [d for d in result.dropped if d["name"] == "ear_mm"]
        self.assertIn("ear_mm", marked(result))
        self.assertTrue(ear["used"])
        self.assertFalse(ear.get("tried"))

    def test_an_unticked_size_that_only_changes_the_body_is_found_by_its_try(self):
        probe = SizeProbe.start(CAPTURE, self.table, Fusion().read)
        grown = read_at()
        grown["box"] = {"min": [0, 0, 0], "max": [32, 20, 25]}
        probe.discover([({"varied": ["wall"]}, {}, grown), ({"varied": ["cube"]}, {}, read_at())])
        self.assertEqual(probe.also_changes, ["wall"])


class DiscoveryCapTest(unittest.TestCase):
    def test_candidates_past_the_cap_are_kept_as_not_tried(self):
        table_ = table(PARAMS, TICKED, MODEL)
        probe = SizeProbe.start(CAPTURE, table_, Fusion().read)
        candidates = [{"param": "p%d" % n, "size": "p%d" % n, "unit": "mm", "value": 1, "min": 0, "max": 5, "end": 5}
                      for n in range(plan.MAX_DISCOVERY + 3)]
        rows = probe.discovery_rows(candidates, 100)
        self.assertEqual(len(rows), plan.MAX_DISCOVERY)
        left = [d for d in probe.report()["discovery"] if d["tried"] is False]
        self.assertEqual([d["param"] for d in left], ["p12", "p13", "p14"])
        self.assertTrue(all(d["moved"] is None and d["reason"] for d in left))
        self.assertEqual(probe.also_changes, [])


if __name__ == "__main__":
    unittest.main()
