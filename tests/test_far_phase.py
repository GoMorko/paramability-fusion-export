"""The far rows run one size at a time, each size followed by its nearer rows (`ProbeRun._far_by_size`): a clean export
runs the rows it ran when the far rows of every size came in one batch, a size that showed trouble outside the part
goes last, and sizes whose far tries fail share the nearer rows."""
import copy
import re
import unittest
from unittest import mock

from tests import context  # noqa: F401
from tests import test_probe_flow as flow
from tests.probe_helpers import size, table
from tests.test_probe_motion import CAPTURE, MODEL, PARAMS, TICKED

from lib.export_plan.pipeline import ProbeRun, far_phase, probe_run
from lib.export_plan.probe_flow import ProbeGroup, SizeProbe
from lib.probe import plan


def measured(fusion, capture=CAPTURE, parts=1):
    """The rows a whole `ProbeRun.measure` ran, by key, for one probe or a group of `parts` probes."""
    tbl = table(PARAMS, TICKED, MODEL)
    sizes = [size(tbl, n, flow.UNITS[n]) for n in TICKED]
    probes = [SizeProbe.start(capture, tbl, fusion.read) for _ in range(parts)]
    probe = probes[0] if parts == 1 else ProbeGroup(probes, ["A", "B"][:parts])
    run = ProbeRun(flow.runner_port(fusion), "", probe)
    run.measure(probe.probe_rows(sizes), sizes)
    return [row["key"][len("probe: "):] for row, _ in run.rows]


def far_fails(exprs):
    """Every far end of cube, off and height fails, and so do the values near them."""
    cube, off, height = (flow.number(exprs[n]) for n in ("cube", "off", "height"))
    return not (6.9 < cube < 13.1 and 3.6 < off < 6.4 and 14 < height < 26)


class CleanExportTest(unittest.TestCase):
    def test_a_clean_export_runs_the_rows_of_one_far_batch_in_the_same_order(self):
        near = ["count (near min)", "count (near max)", "cube (near min)", "cube (near max)", "off (near min)",
                "off (near max)", "height (near min)", "height (near max)", "all near 0", "all near 1"]
        far = ["count (min)", "count (max)", "cube (min)", "cube (max)", "off (min)", "off (max)", "height (min)",
               "height (max)"]
        for parts in (1, 2):
            with self.subTest(parts=parts):
                fusion = flow.Fusion()
                self.assertEqual(measured(fusion, parts=parts), near + far + ["all min", "all max"])
                self.assertEqual(fusion.store.exprs, flow.START)


class FarOrderTest(unittest.TestCase):
    def test_a_size_whose_near_try_warned_outside_the_part_has_its_far_rows_last(self):
        capture = copy.deepcopy(CAPTURE)
        for item in capture["items"]:
            item["in_target_component"] = True
        capture["items"].append({"index": 9, "name": "Extrude6", "type": "ChamferFeature", "component": "other",
                                 "in_target_component": False, "data": {}})
        fusion = flow.Fusion()
        fusion.store.warns = lambda exprs: [(9, "Extrude6")] if flow.number(exprs["cube"]) != 10 else []
        keys = measured(fusion, capture)
        far = [k for k in keys if k.endswith(("(min)", "(max)"))]
        self.assertEqual(far, ["count (min)", "count (max)", "off (min)", "off (max)", "height (min)", "height (max)",
                               "cube (min)", "cube (max)"])


class NearerShareTest(unittest.TestCase):
    def test_sizes_whose_far_tries_fail_each_get_nearer_rows_under_the_cap(self):
        # With 12 nearer rows, the first two sizes alone would use them all (six each).
        with mock.patch.object(probe_run, "MAX_NEARER_ROWS", 12), mock.patch.object(plan, "MAX_NEARER_ROWS", 12):
            fusion = flow.Fusion(bad_when=far_fails)
            keys = measured(fusion)
        nearer = {name: sum(1 for k in keys if re.fullmatch(r"%s \((min|max|check) [-0-9.]+\)" % name, k))
                  for name in ("cube", "off", "height")}
        self.assertEqual(nearer, {"cube": 4, "off": 4, "height": 4})
        self.assertEqual(fusion.store.exprs, flow.START)

    def test_the_share_passes_unused_rows_on_and_leaves_room_for_the_far_rows_to_come(self):
        self.assertEqual(far_phase.nearer_share(24, 3, 64), 8)
        self.assertEqual(far_phase.nearer_share(22, 2, 60), 11)
        self.assertEqual(far_phase.nearer_share(1, 3, 64), 1)
        self.assertEqual(far_phase.nearer_share(24, 3, 6), 2)
        self.assertEqual(far_phase.nearer_share(24, 3, 3), 0)


if __name__ == "__main__":
    unittest.main()
