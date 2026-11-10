"""The size probe with a step that uses a plane of another component: request, rows, motion, discovery, restore."""
import unittest

from tests import context  # noqa: F401
from tests.fakes import FakeStore
from tests.probe_helpers import capture, size, table, user
from tests.test_probe_flow import START, Fusion, number, states
from tests.test_probe_motion import CAPTURE, MODEL, PARAMS, TICKED, read_at
from tests.test_probe_refs import MIRROR, plane_at, with_refs

from lib.design_edit.runner import RowExport
from lib.export_plan.probe_flow import SizeProbe, covers_a_sketch
from lib.probe import plan
from lib.sketch_values.motion import Motion

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

    def test_the_request_lists_the_references_and_the_first_read_gives_them(self):
        fusion = Cover()
        probe = self.start(fusion)
        self.assertEqual(list(fusion.requests[0]["refs"]), ["8.plane"])
        self.assertEqual(list(probe.request["refs"]), ["8.plane"])
        self.assertEqual([r["key"] for r in probe.refs], ["8.plane"])

    def test_a_size_that_acts_on_the_reference_gets_rows_and_the_plane_a_formula(self):
        fusion = Cover()
        probe = self.start(fusion)
        self.assertIn("gap", plan.sketch_driven(self.table))
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
        self.assertEqual(probe.also_changes, ["gap", "off"])

    def test_references_alone_are_enough_to_start_a_probe(self):
        self.assertTrue(covers_a_sketch(capture(MIRROR)))
        self.assertFalse(covers_a_sketch(capture()))
        fusion = Cover()
        probe = SizeProbe.start(capture(MIRROR), self.table, fusion.read)
        self.assertEqual((probe.request["sketches"], list(probe.request["refs"])), ([], ["8.plane"]))
        self.assertIsNone(SizeProbe.start(capture(MIRROR), self.table, lambda request: {"refs": {}}))


if __name__ == "__main__":
    unittest.main()
