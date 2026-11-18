"""The steps to get the design back as it was saved: when the result gives them, what the start read keeps, what the
lines say, and that the add-in never closes or opens a design itself (fakes with the names of the Fusion API)."""
import pathlib
import types
import unittest

from tests import context  # noqa: F401
from tests import fakes
from tests.test_result_rows import view as plain_view
from lib.design_edit.saved_start import SavedStart
from lib.dialog_model.result_rows import reopen_view, result_view, section
from lib.export_plan.health import HealthInputs, make_health
from lib.export_plan.rollback import (REOPEN_UNSAVED, ExportOutcome, decide, reopen_lines, reopen_offered)
from lib.fusion_reader.saved_design import read_saved_start
from lib.params import size_table

core = fakes.install_adsk_core()
from lib.fusion_ui import result_dialog  # noqa: E402

FILE_ID = "urn:adsk.wipprod:dm.lineage:abc"
SAVED = SavedStart(in_cloud=True, modified=False, file_id=FILE_ID, version=4, name="Box", project="Prints")
UNSAVED = SavedStart(in_cloud=True, modified=True, file_id=FILE_ID, version=4, name="Box", project="Prints")
CHANGED = make_health(HealthInputs(unrestored=["wall"]))
NO_UNDO = decide(ExportOutcome(CHANGED, touched=True, undo_dropped=True))
UNDONE = decide(ExportOutcome(CHANGED, touched=True))
BACK = decide(ExportOutcome(make_health(HealthInputs()), touched=True))


class FakeDataFile:
    def __init__(self, version, name="Box", project="Prints", file_id=FILE_ID):
        self.id, self.versionNumber, self.name = file_id, version, name
        self.parentProject = types.SimpleNamespace(name=project)


class FakeDocument:
    def __init__(self, data_file, modified=False):
        self.dataFile, self.isModified = data_file, modified


class FakeEvent:
    """An `ApplicationCommandEvent`: handlers are added and removed, and a test fires it for a command id."""

    def __init__(self):
        self.handlers = []

    def add(self, handler):
        self.handlers.append(handler)
        return True

    def remove(self, handler):
        self.handlers.remove(handler)
        return True

    def fire(self, command_id):
        args = types.SimpleNamespace(commandId=command_id)
        for handler in list(self.handlers):
            handler.notify(args)


class OfferTest(unittest.TestCase):
    def test_a_saved_design_the_export_could_not_undo_gets_the_steps(self):
        self.assertTrue(NO_UNDO.undo_unavailable)
        self.assertTrue(reopen_offered(SAVED, NO_UNDO))
        self.assertTrue(reopen_offered(UNSAVED, NO_UNDO))
        self.assertTrue(reopen_offered(SavedStart(True, None, FILE_ID, 4), NO_UNDO))

    def test_a_design_without_a_saved_cloud_version_gets_no_steps(self):
        for start in (SavedStart(False, False), SavedStart(True, False, "", 4), SavedStart(True, False, FILE_ID),
                      None):
            self.assertFalse(reopen_offered(start, NO_UNDO), start)

    def test_a_design_that_is_back_or_that_fusion_undoes_gets_no_steps(self):
        self.assertFalse(reopen_offered(SAVED, BACK))
        self.assertFalse(reopen_offered(SAVED, UNDONE))


class StartReadTest(unittest.TestCase):
    def test_a_cloud_design_without_unsaved_changes_keeps_its_file_version_and_place(self):
        start = read_saved_start(FakeDocument(FakeDataFile(7)))
        self.assertEqual(start, SavedStart(True, False, FILE_ID, 7, "Box", "Prints"))
        self.assertTrue(start.can_reopen)

    def test_a_design_not_in_the_cloud_has_no_saved_version_and_unsaved_changes_are_kept(self):
        for document in (FakeDocument(None), None):
            self.assertFalse(read_saved_start(document).can_reopen)
        unreadable = read_saved_start(types.SimpleNamespace(dataFile=FakeDataFile(7)))
        changed = read_saved_start(FakeDocument(FakeDataFile(7), modified=True))
        self.assertTrue(unreadable.unsaved_at_start and changed.unsaved_at_start)
        self.assertFalse(read_saved_start(FakeDocument(FakeDataFile(7))).unsaved_at_start)


class LinesTest(unittest.TestCase):
    def test_the_steps_close_without_saving_then_open_the_saved_version_by_project_file_and_version(self):
        lines = reopen_lines(SAVED)
        self.assertNotIn(REOPEN_UNSAVED, lines)
        self.assertEqual([line[:2] for line in lines[1:]], ["1.", "2.", "3."])
        self.assertIn("Close", lines[1])
        self.assertIn("Don't Save", lines[2])
        for known in ("Prints", "Box", "version 4"):
            self.assertIn(known, lines[3])

    def test_the_warning_comes_first_only_when_fusion_showed_unsaved_changes(self):
        self.assertEqual(reopen_lines(UNSAVED)[0], REOPEN_UNSAVED)
        self.assertEqual(reopen_lines(SavedStart(True, None, FILE_ID, 4))[0], REOPEN_UNSAVED)
        self.assertEqual(reopen_lines(None)[0], REOPEN_UNSAVED)
        self.assertEqual(len(reopen_lines(UNSAVED)), len(reopen_lines(SAVED)) + 1)

    def test_a_name_that_is_not_known_is_left_out_of_the_last_step(self):
        last = reopen_lines(SavedStart(True, False, FILE_ID, 4))[-1]
        self.assertIn("version 4", last)
        self.assertNotIn("project", last)
        self.assertNotIn("file", last)
        self.assertEqual(reopen_lines(None)[-1], "3. Open the design again from the Data Panel.")


def offered_view(start=SAVED, rollback=NO_UNDO):
    params = [dict(name="wall", expression="2 mm", value=0.2, unit="mm", comment="", is_favorite=True, kind="length")]
    report = {"sizes": {"free": ["wall"], "fixed": [], "dropped": []}, "health": CHANGED}
    manifest = {"kind": "recipe", "notes": [], "parameters": [{}]}
    return result_view("box.paramability", manifest, report, size_table.build(params, ["wall"]), ["wall"], rollback,
                       reopen=reopen_lines(start) if reopen_offered(start, rollback) else False)


class WindowTest(unittest.TestCase):
    def test_only_an_offered_view_has_the_steps_section_first_and_open(self):
        shown = offered_view()
        self.assertEqual([s["key"] for s in shown["sections"]][:3], ["reopen", "check", "result"])
        text = " ".join(section(shown, "reopen")["lines"])
        for known in ("Box", "Prints", "version 4"):
            self.assertIn(known, text)
        command = fakes.FakeCommand()
        result_dialog.build(command, shown)
        box = command.commandInputs.itemById("pm_result_reopen")
        self.assertIn("Save", box.formattedText)
        plain = fakes.FakeCommand()
        result_dialog.build(plain, plain_view())
        self.assertIsNone(section(plain_view(), "reopen"))
        self.assertIsNone(plain.commandInputs.itemById("pm_result_reopen"))

    def test_an_abort_or_a_design_that_is_back_has_no_steps_section(self):
        for rollback in (UNDONE, BACK):
            shown = offered_view(rollback=rollback)
            self.assertIsNone(section(shown, "reopen"))
            self.assertFalse(shown["reopen"])

    def test_the_view_without_a_result_has_only_the_steps(self):
        shown = reopen_view(reopen_lines(UNSAVED))
        self.assertEqual([s["key"] for s in shown["sections"]], ["reopen"])
        self.assertEqual(shown["sections"][0]["lines"][0], REOPEN_UNSAVED)
        self.assertTrue(shown["reopen"])

    def test_the_window_has_no_input_to_click_and_no_input_hook(self):
        command = fakes.FakeCommand()
        result_dialog.build(command, offered_view())
        self.assertFalse(any("button" in key for key in command.commandInputs.items))
        self.assertFalse(hasattr(command, "inputChanged"))


class NoCloseOrOpenTest(unittest.TestCase):
    def test_showing_the_window_and_ending_commands_never_closes_or_opens_a_design(self):
        """Fusion does not support closing or opening a document inside a command event: a fake that fails the test
        when the add-in touches it must stay untouched through the whole life of the window."""
        def fail(*args):
            raise AssertionError("the add-in closed or opened a design")

        document = types.SimpleNamespace(close=fail, save=fail, dataFile=FakeDataFile(4), isModified=False)
        ui = types.SimpleNamespace(
            commandTerminated=FakeEvent(), activeCommand="", terminateActiveCommand=fail,
            commandDefinitions=types.SimpleNamespace(
                itemById=lambda i: None,
                addButtonDefinition=lambda *a: types.SimpleNamespace(commandCreated=FakeEvent(), execute=lambda: None)))
        app = types.SimpleNamespace(userInterface=ui, documents=types.SimpleNamespace(open=fail),
                                    activeDocument=document)
        previous = getattr(core, "Application", None)
        core.Application = types.SimpleNamespace(get=lambda: app)
        self.addCleanup(lambda: setattr(core, "Application", previous))
        result_dialog.start()
        self.addCleanup(result_dialog.remove)
        result_dialog.show(offered_view(), "SomeCommand")
        ui.commandTerminated.fire("SomeCommand")
        ui.commandTerminated.fire(result_dialog.COMMAND_ID)
        result_dialog.build(fakes.FakeCommand(), offered_view())

    def test_no_source_file_closes_or_opens_a_document(self):
        root = pathlib.Path(__file__).resolve().parent.parent / "ParamabilityExport"
        for path in root.rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            for banned in ("documents.open", ".close(False", "terminateActiveCommand"):
                self.assertNotIn(banned, text, str(path))


if __name__ == "__main__":
    unittest.main()
