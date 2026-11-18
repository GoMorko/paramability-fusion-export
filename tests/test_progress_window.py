"""The progress window of an export: one window for every batch of tries, hidden once at the end, whatever way the
export ends."""
import sys
import tempfile
import unittest
from unittest import mock

from tests import context  # noqa: F401
from tests import fakes
from tests.fakes import FakePartsPort, FakePort
from tests.test_parts_pipeline import BASE, second_body
from tests.test_pipeline import export, request

core = fakes.install_adsk_core()
from lib.design_edit.runner import ExportCancelled  # noqa: E402
from lib.export_plan.pipeline import run_parts_pipeline  # noqa: E402
from lib.fusion_ui import progress  # noqa: E402


class FakeDialog:
    """What `UserInterface.createProgressDialog()` gives, with a record of the calls."""

    def __init__(self, shows, cancel_after=None, hide_fails=False):
        self.shows, self.cancel_after, self.hide_fails = shows, cancel_after, hide_fails
        self.shown, self.hidden, self.values, self.first_maximum = 0, 0, [], None
        self.maximumValue = None
        shows.append(self)

    def show(self, title, text, low, high, delay):
        self.shown, self.first_maximum = self.shown + 1, high

    def hide(self):
        self.hidden += 1
        if self.hide_fails:
            raise RuntimeError("Fusion would not hide it")

    @property
    def progressValue(self):
        return self.values[-1]

    @progressValue.setter
    def progressValue(self, value):
        self.values.append(value)

    @property
    def wasCancelled(self):
        return self.cancel_after is not None and len(self.values) >= self.cancel_after


class Windows:
    """The fake Fusion: it counts the dialogs made and `adsk.doEvents` calls."""

    def __init__(self, **options):
        self.made, self.options = [], options

    def application(self):
        app = mock.Mock()
        app.get.return_value.userInterface.createProgressDialog = lambda: FakeDialog(self.made, **self.options)
        return app

    def __enter__(self):
        self.patches = [mock.patch.object(core, "Application", self.application(), create=True),
                        mock.patch.object(sys.modules["adsk"], "doEvents", lambda: None, create=True)]
        for patch in self.patches:
            patch.start()
        progress.close_all()
        return self

    def __exit__(self, *exc):
        progress.close_all()
        for patch in self.patches:
            patch.stop()


def window(verb):
    return progress.ProgressDialog("Export", verb=verb, keep_open=True)


class SharedWindowPort(FakePort):
    """A fake port that hands every batch of tries the same real `ProgressDialog`, as the Fusion ports do."""

    batches = 0

    def progress(self, verb):
        self.batches += 1
        self.windows = getattr(self, "windows", None) or progress.DialogSet(window)
        return self.windows.get(verb)


class SharedWindowPartsPort(FakePartsPort):
    def progress(self, verb):
        self.windows = getattr(self, "windows", None) or progress.DialogSet(window)
        return self.windows.get(verb)


class OneWindowTest(unittest.TestCase):
    def test_every_batch_of_tries_uses_one_window_that_opens_once_and_hides_at_the_end(self):
        with Windows() as fusion:
            port = SharedWindowPort()
            export(port)
            self.assertGreater(port.batches, 1)
            self.assertEqual(len(fusion.made), 1)
            dialog = fusion.made[0]
            self.assertEqual((dialog.shown, dialog.hidden), (1, 0))
            progress.close_all()
            self.assertEqual(dialog.hidden, 1)
            progress.close_all()
            self.assertEqual(dialog.hidden, 1)

    def test_the_step_count_runs_across_batches_and_the_window_grows_with_the_total(self):
        with Windows() as fusion:
            port = SharedWindowPort()
            export(port)
            dialog = fusion.made[0]
            self.assertEqual(dialog.values, list(range(len(dialog.values))))
            self.assertGreater(dialog.maximumValue, dialog.first_maximum)
            self.assertEqual(dialog.maximumValue, len(dialog.values))

    def test_a_cancel_in_one_batch_is_seen_by_the_same_window_and_the_window_is_hidden_after(self):
        with Windows(cancel_after=4) as fusion:
            port = SharedWindowPort()
            with self.assertRaises(ExportCancelled):
                export(port)
            progress.close_all()
            self.assertEqual(len(fusion.made), 1)
            self.assertEqual(fusion.made[0].hidden, 1)
            self.assertEqual(len(fusion.made[0].values), 4)

    def test_an_export_that_raises_leaves_a_window_that_close_all_hides(self):
        with Windows() as fusion:
            port = SharedWindowPort(fail_read_from=8)
            export(port)
            self.assertEqual(fusion.made[0].hidden, 0)
            progress.close_all()
            self.assertEqual(fusion.made[0].hidden, 1)

    def test_several_bodies_share_one_window(self):
        with Windows() as fusion:
            with tempfile.TemporaryDirectory() as tmp:
                run_parts_pipeline(SharedWindowPartsPort([BASE, second_body()]), request(), tmp)
            self.assertEqual(len(fusion.made), 1)
            progress.close_all()
            self.assertEqual(fusion.made[0].hidden, 1)


class CloseAllTest(unittest.TestCase):
    def test_a_window_that_cannot_be_hidden_is_logged_and_the_others_are_still_hidden(self):
        with Windows(hide_fails=True) as fusion:
            first, second = window("a"), window("b")
            for each in (first, second):
                each.step(1, 2, "x")
            progress.close_all()
            self.assertEqual([d.hidden for d in fusion.made], [1, 1])
            progress.close_all()
            self.assertEqual([d.hidden for d in fusion.made], [1, 1])

    def test_a_window_that_was_closed_is_made_again_for_the_next_step(self):
        with Windows() as fusion:
            windows = progress.DialogSet(window)
            windows.get("Trying").step(1, 3, "x")
            progress.close_all()
            windows.get("Trying").step(2, 3, "y")
            self.assertEqual(len(fusion.made), 2)
            self.assertEqual([d.shown for d in fusion.made], [1, 1])

    def test_a_window_that_ends_with_its_block_hides_there(self):
        with Windows() as fusion:
            with progress.ProgressDialog("Export") as shown:
                shown.step(1, 2, "x")
            self.assertEqual(fusion.made[0].hidden, 1)


if __name__ == "__main__":
    unittest.main()
