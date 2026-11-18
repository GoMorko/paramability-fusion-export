"""The reopen of the design from its last save: when the result offers it, what the start read keeps, and what the
click does in Fusion (fakes with the names of the Fusion API)."""
import types
import unittest
from unittest import mock

from tests import context  # noqa: F401
from tests import fakes
from tests.test_result_rows import view as plain_view
from lib.design_edit.saved_start import SavedStart, reopen
from lib.dialog_model.result_rows import reopen_view, result_view, section
from lib.export_plan.health import HealthInputs, make_health
from lib.export_plan.rollback import ExportOutcome, decide, reopen_offered
from lib.fusion_reader.saved_design import FusionReopen, read_saved_start
from lib.params import size_table

core = fakes.install_adsk_core()
from lib.fusion_ui import reopen as reopen_ui, result_dialog  # noqa: E402

FILE_ID = "urn:adsk.wipprod:dm.lineage:abc"
SAVED = SavedStart(in_cloud=True, modified=False, file_id=FILE_ID, version=4, name="Box", project="Prints")
CHANGED = make_health(HealthInputs(unrestored=["wall"]))
NO_UNDO = decide(ExportOutcome(CHANGED, touched=True, undo_dropped=True))
UNDONE = decide(ExportOutcome(CHANGED, touched=True))
BACK = decide(ExportOutcome(make_health(HealthInputs()), touched=True))


class FakeDataFile:
    def __init__(self, version, versions=(), name="Box", project="Prints", file_id=FILE_ID):
        self.id, self.versionNumber, self.name = file_id, version, name
        self.parentProject = types.SimpleNamespace(name=project)
        self.versions = types.SimpleNamespace(count=len(versions), item=lambda i: versions[i])


class FakeDocument:
    def __init__(self, data_file, modified=False, closes=True, calls=None):
        self.dataFile, self.isModified, self.isValid = data_file, modified, True
        self._closes = closes
        self.calls = calls if calls is not None else []

    def close(self, save_changes):
        self.calls.append(("close", save_changes))
        if self._closes:
            self.isValid = False
        return self._closes

    def save(self, description):
        self.calls.append(("save", description))
        return True


class FakeApp:
    """`Application` with `data.findFileById`, `documents.open` and the `userInterface` the reopen reads."""

    def __init__(self, latest, opens=True, calls=None):
        self.calls = calls if calls is not None else []
        self.data = types.SimpleNamespace(findFileById=lambda file_id: latest if file_id == FILE_ID else None)
        self.documents = types.SimpleNamespace(open=self._open)
        self._opens = opens
        self.userInterface = types.SimpleNamespace(activeCommand=result_dialog.COMMAND_ID,
                                                   terminateActiveCommand=self._terminate)
        self.fired = []

    def _open(self, data_file, visible):
        self.calls.append(("open", data_file.versionNumber, visible))
        return object() if self._opens else None

    def _terminate(self):
        self.calls.append(("end window",))
        self.userInterface.activeCommand = ""
        return True

    def fireCustomEvent(self, event_id):
        self.fired.append(event_id)
        return True


def setup(latest=None, opens=True, closes=True, modified=False):
    calls = []
    latest = latest or FakeDataFile(4)
    return FakeApp(latest, opens, calls), FakeDocument(latest, modified, closes, calls), calls


class OfferTest(unittest.TestCase):
    def test_a_saved_unchanged_design_the_export_could_not_undo_is_offered_the_reopen(self):
        self.assertTrue(NO_UNDO.undo_unavailable)
        self.assertTrue(reopen_offered(SAVED, NO_UNDO))

    def test_unsaved_changes_at_the_start_or_an_unknown_state_never_offer_it(self):
        for start in (SavedStart(True, True, FILE_ID, 4), SavedStart(True, None, FILE_ID, 4),
                      SavedStart(False, False), SavedStart(True, False, "", 4), None):
            self.assertFalse(reopen_offered(start, NO_UNDO), start)

    def test_a_design_that_is_back_or_that_fusion_undoes_is_not_offered_it(self):
        self.assertFalse(reopen_offered(SAVED, BACK))
        self.assertFalse(reopen_offered(SAVED, UNDONE))


class StartReadTest(unittest.TestCase):
    def test_a_cloud_design_without_unsaved_changes_keeps_its_file_version_and_place(self):
        start = read_saved_start(FakeDocument(FakeDataFile(7)))
        self.assertEqual(start, SavedStart(True, False, FILE_ID, 7, "Box", "Prints"))
        self.assertTrue(start.can_reopen)

    def test_a_design_with_changes_not_in_the_cloud_or_unreadable_cannot_be_reopened(self):
        unreadable = types.SimpleNamespace(dataFile=FakeDataFile(7))
        for document in (FakeDocument(FakeDataFile(7), modified=True), FakeDocument(None), unreadable, None):
            self.assertFalse(read_saved_start(document).can_reopen)


class ReopenTest(unittest.TestCase):
    def test_the_reopen_closes_without_saving_then_opens_the_kept_version(self):
        app, document, calls = setup()
        self.assertEqual(reopen(SAVED, FusionReopen(app, document)), "")
        self.assertEqual(calls, [("close", False), ("open", 4, True)])

    def test_a_newer_version_in_the_cloud_opens_the_kept_version(self):
        app, document, calls = setup(FakeDataFile(6, versions=[FakeDataFile(6), FakeDataFile(5), FakeDataFile(4)]))
        document.dataFile = FakeDataFile(4)
        self.assertEqual(reopen(SAVED, FusionReopen(app, document)), "")
        self.assertEqual(calls, [("close", False), ("open", 4, True)])

    def test_a_kept_version_that_cannot_be_found_closes_nothing(self):
        app, document, calls = setup(FakeDataFile(6, versions=[FakeDataFile(6)]))
        self.assertTrue(reopen(SAVED, FusionReopen(app, document)))
        app.data.findFileById = lambda file_id: None
        self.assertTrue(reopen(SAVED, FusionReopen(app, document)))
        self.assertEqual(calls, [])

    def test_a_design_that_is_no_longer_that_file_is_not_closed(self):
        app, document, calls = setup()
        document.dataFile = FakeDataFile(4, file_id="urn:other")
        self.assertTrue(reopen(SAVED, FusionReopen(app, document)))
        self.assertEqual(calls, [])

    def test_a_close_that_fails_opens_nothing_and_saves_nothing(self):
        app, document, calls = setup(closes=False)
        self.assertTrue(reopen(SAVED, FusionReopen(app, document)))
        self.assertEqual(calls, [("close", False)])

    def test_an_open_that_fails_after_the_close_says_where_the_design_is(self):
        app, document, calls = setup(opens=False)
        message = reopen(SAVED, FusionReopen(app, document))
        self.assertIn("Box", message)
        self.assertIn("Prints", message)
        self.assertEqual(calls, [("close", False), ("open", 4, True)])


def offered_view():
    params = [dict(name="wall", expression="2 mm", value=0.2, unit="mm", comment="", is_favorite=True, kind="length")]
    report = {"sizes": {"free": ["wall"], "fixed": [], "dropped": []}, "health": CHANGED}
    manifest = {"kind": "recipe", "notes": [], "parameters": [{}]}
    return result_view("box.paramability", manifest, report, size_table.build(params, ["wall"]), ["wall"], NO_UNDO,
                       reopen=True)


class WindowTest(unittest.TestCase):
    def test_only_an_offered_view_has_the_reopen_section_and_its_button(self):
        shown = offered_view()
        self.assertEqual([s["key"] for s in shown["sections"]][:2], ["check", "reopen"])
        command = fakes.FakeCommand()
        result_dialog.build(command, shown)
        self.assertIsNotNone(command.commandInputs.itemById(result_dialog.REOPEN_ID))
        plain = fakes.FakeCommand()
        result_dialog.build(plain, plain_view())
        self.assertIsNone(section(plain_view(), "reopen"))
        self.assertIsNone(plain.commandInputs.itemById(result_dialog.REOPEN_ID))
        self.assertTrue(reopen_view()["reopen"])

    def test_the_click_reopens_only_after_its_event_and_ends_the_window_first(self):
        app, document, calls = setup()
        with mock.patch.object(core, "Application", types.SimpleNamespace(get=lambda: app), create=True):
            reopen_ui.keep(document, SAVED)
            result_dialog.on_input("pm_result_sizes")
            self.assertEqual(app.fired, [])
            result_dialog.on_input(result_dialog.REOPEN_ID)
            self.assertEqual(app.fired, [reopen_ui.EVENT_ID])
            self.assertEqual(calls, [])
            reopen_ui.run_pending()
        self.assertEqual(calls, [("end window",), ("close", False), ("open", 4, True)])

    def test_without_a_kept_design_the_click_does_nothing(self):
        app, _, calls = setup()
        with mock.patch.object(core, "Application", types.SimpleNamespace(get=lambda: app), create=True):
            reopen_ui.forget()
            result_dialog.on_input(result_dialog.REOPEN_ID)
            reopen_ui.run_pending()
        self.assertEqual((app.fired, calls), ([], []))


if __name__ == "__main__":
    unittest.main()
