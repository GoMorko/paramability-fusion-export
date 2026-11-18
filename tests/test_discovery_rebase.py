"""The baseline of the rows is measured again before the discovery rows only when the unused timeline items were turned
back on after the tries (`ProbeRun.discover`, `PutBack.end_trim`)."""
import unittest
from unittest import mock

from tests import context  # noqa: F401
from tests.fakes import FakePort, TrimStore
from tests.test_pipeline import START
from tests.test_timeline_trim import PIPE_TRY, export, trim_capture

from lib.export_plan.timeline_trim import TimelineTrim


class WarnedWhenOn(TrimStore):
    """A store whose timeline item 6 shows a warning only while it is on: it was off for the tries, and has the warning
    in the person's design."""

    NAMES = ["Item0", "Item1", "Item2", "Item3", "Item4", "Item5", "Lid sketch", "Lid extrude", "Item8"]

    def warning_entries(self):
        return [] if 6 in self.off else [(6, "Lid sketch")]

    def timeline_health(self, known=None):
        return [{"index": i, "name": name, "type": "Sketch", "message": "", "suppressed": i in self.off,
                 "health": "warning" if i == 6 and i not in self.off else "ok"} for i, name in enumerate(self.NAMES)]


def discovery(faster, store=None):
    port = FakePort(capture=trim_capture(), store=store or TrimStore(START, note_sets=True))
    with mock.patch("lib.export_plan.pipeline.run.discovery_sizes", return_value=[dict(PIPE_TRY)]):
        result = export(port, faster=faster)
    return port, result, result.report["timing"]["probe"]["calls"]["computes"]


class DiscoveryRebaseTest(unittest.TestCase):
    def test_the_baseline_is_measured_again_when_items_were_turned_back_on(self):
        port, result, computes = discovery(faster=True)
        self.assertEqual(result.report["probe"]["timeline"]["suppressed"]["on"], True)
        self.assertEqual(computes["rebase"]["count"], 1)
        self.assertEqual(result.report["probe"]["discovery"][0]["param"], "pipe_offset_mm")

    def test_the_baseline_is_kept_when_no_item_was_turned_off(self):
        port, result, computes = discovery(faster=False)
        self.assertFalse(result.report["probe"]["timeline"]["suppressed"]["on"])
        self.assertNotIn("rebase", computes)
        self.assertEqual(computes["baseline"]["count"], 1)
        self.assertEqual(result.report["probe"]["discovery"][0]["param"], "pipe_offset_mm")
        self.assertEqual(port.store.exprs, START)

    def test_the_baseline_is_kept_when_the_store_turned_nothing_off(self):
        _, result, computes = discovery(faster=True, store=TrimStore(START, refuse=True))
        self.assertFalse(result.report["probe"]["timeline"]["suppressed"]["on"])
        self.assertNotIn("rebase", computes)

    def test_a_warning_an_item_has_once_it_is_back_on_does_not_stop_the_discovery_rows(self):
        port, result, _ = discovery(faster=True, store=WarnedWhenOn(START, note_sets=True))
        self.assertEqual(result.report["probe"]["discovery"][0]["param"], "pipe_offset_mm")
        self.assertNotIn("stopped", result.report["probe"])
        self.assertNotIn("tries_stopped", result.health)
        self.assertEqual(port.store.exprs, START)


class TrimEndTest(unittest.TestCase):
    def test_end_says_whether_it_turned_items_on(self):
        store = TrimStore(START)
        trim = TimelineTrim(store, lambda text: None, True)
        self.assertFalse(trim.end())  # nothing was turned off
        capture = trim_capture()
        trim.begin([capture], capture["marker"]["position"] - 2, lambda: True)
        self.assertEqual(store.off, (6, 7))
        self.assertTrue(trim.end())
        self.assertEqual(store.off, ())
        self.assertFalse(trim.end())

    def test_end_says_no_when_the_items_were_turned_back_on_at_once(self):
        store = TrimStore(START)
        trim = TimelineTrim(store, lambda text: None, True)
        capture = trim_capture()
        trim.begin([capture], capture["marker"]["position"] - 2, lambda: False)  # the body reads differently
        self.assertEqual(store.off, ())
        self.assertFalse(trim.end())


if __name__ == "__main__":
    unittest.main()
