"""The result window: its groups and their order, the short message and when it opens (fakes with the
names of the Fusion API)."""
import types
import unittest
from unittest import mock

from tests import context  # noqa: F401
from tests import fakes
from tests.test_reopen import FakeEvent, offered_view
from tests.test_result_rows import view as plain_view

core = fakes.install_adsk_core()
import config  # noqa: E402
from lib.fusion_ui import result_dialog  # noqa: E402


def group_ids(command):
    return [key for key in command.commandInputs.items if key.startswith("pm_group_")]


def expanded(command):
    return [key[len("pm_group_"):] for key in group_ids(command) if command.commandInputs.items[key].isExpanded]


def big_view():
    return plain_view(extra={"gaps": [{"name": "Extrude5", "reason": "No."}]}, fixed=[{"name": "gap", "reason": "x"}])


class GroupsTest(unittest.TestCase):
    def test_the_reopen_group_is_first_with_its_button_and_the_rest_follow(self):
        command = fakes.FakeCommand()
        result_dialog.build(command, offered_view())
        self.assertEqual(group_ids(command)[:3], ["pm_group_reopen", "pm_group_check", "pm_group_result"])
        self.assertIn(result_dialog.REOPEN_ID, command.commandInputs.items)

    def test_without_the_reopen_the_result_comes_first(self):
        command = fakes.FakeCommand()
        result_dialog.build(command, big_view())
        self.assertEqual(group_ids(command)[0], "pm_group_result")
        self.assertNotIn("pm_group_reopen", group_ids(command))

    def test_only_the_reopen_the_check_and_the_result_start_open(self):
        command = fakes.FakeCommand()
        result_dialog.build(command, offered_view())
        self.assertEqual(expanded(command), ["reopen", "check", "result"])
        plain = fakes.FakeCommand()
        result_dialog.build(plain, big_view())
        self.assertEqual(expanded(plain), ["result"])
        self.assertEqual(group_ids(plain), ["pm_group_result", "pm_group_sizes", "pm_group_left_out"])

    def test_a_long_section_is_a_text_box_with_a_row_limit(self):
        command = fakes.FakeCommand()
        lines = ["line %d with some words" % n for n in range(40)]
        result_dialog.add_text(command.commandInputs, "pm_long", "Sizes", lines)
        self.assertEqual(command.commandInputs.itemById("pm_long").numRows, result_dialog.MAX_ROWS)

    def test_the_window_has_an_initial_size(self):
        command = fakes.FakeCommand()
        result_dialog.build(command, big_view())
        self.assertEqual(command.size, result_dialog.DIALOG_SIZE)

    def test_when_groups_fail_the_sections_are_text_boxes_with_their_heading(self):
        command = fakes.FakeCommand()
        command.commandInputs.addGroupCommandInput = mock.Mock(side_effect=RuntimeError("no groups"))
        shown = offered_view()
        result_dialog.build(command, shown)
        for found in shown["sections"]:
            self.assertIn("# " + found["title"], command.commandInputs.itemById("pm_result_" + found["key"]).formattedText)
        self.assertIn(result_dialog.REOPEN_ID, command.commandInputs.items)


class SummaryTest(unittest.TestCase):
    def test_the_message_for_a_window_that_cannot_open_is_short_but_names_the_file_sizes_and_left_out_steps(self):
        shown = big_view()
        self.assertLess(len(shown["summary"]), len(shown["message"]))
        self.assertIn("box.paramability", shown["summary"])
        self.assertIn("1 size", shown["summary"])
        self.assertIn("1 step is left out", shown["summary"])
        self.assertNotIn("Sizes", shown["summary"])

    def test_a_design_that_may_be_changed_keeps_its_advice_in_the_summary(self):
        shown = offered_view()
        self.assertIn("design may be changed", shown["summary"])


class FakeUI:
    """A `UserInterface` with the command end event, the running command and the command definitions the window needs."""

    def __init__(self, running=""):
        self.commandTerminated = FakeEvent()
        self.activeCommand = running
        self.opened = []
        self.add_fails = False
        self.commandDefinitions = types.SimpleNamespace(itemById=lambda i: None, addButtonDefinition=self._add)

    def _add(self, command_id, name, tooltip, resources):
        if self.add_fails:
            raise RuntimeError("no command")
        return types.SimpleNamespace(commandCreated=FakeEvent(), execute=lambda: self.opened.append(command_id))


class ResultWindowTest(unittest.TestCase):
    def setUp(self):
        self.boxes, self.logs, self.notices = [], [], []
        self.ui = FakeUI(running=config.EXPORT_COMMAND_ID)
        app = types.SimpleNamespace(userInterface=self.ui)
        patches = [
            mock.patch.object(core, "Application", types.SimpleNamespace(get=lambda: app), create=True),
            mock.patch.object(result_dialog, "message_box", self.boxes.append),
            mock.patch.object(result_dialog, "log", self.logs.append),
            mock.patch.object(result_dialog, "status_notice", self.notices.append),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        result_dialog.start()
        self.addCleanup(result_dialog.remove)

    def test_the_window_opens_once_and_only_after_the_export_command_has_ended(self):
        result_dialog.show(big_view(), config.EXPORT_COMMAND_ID)
        self.assertEqual(self.ui.opened, [])
        self.assertEqual(self.notices, [result_dialog.WAITING])
        self.ui.commandTerminated.fire(config.EXPORT_COMMAND_ID)
        self.assertEqual(self.ui.opened, [result_dialog.COMMAND_ID])
        self.ui.commandTerminated.fire(config.EXPORT_COMMAND_ID)
        self.assertEqual(self.ui.opened, [result_dialog.COMMAND_ID])
        self.assertEqual(self.boxes, [])

    def test_a_command_that_ends_is_ignored_unless_it_is_the_export_that_showed_the_result(self):
        result_dialog.show(big_view(), config.EXPORT_COMMAND_ID)
        for other in (config.ORCA_COMMAND_ID, config.ROWS_COMMAND_ID, "SelectCommand", ""):
            self.ui.commandTerminated.fire(other)
        self.assertEqual(self.ui.opened, [])

    def test_a_result_shown_while_no_command_of_the_caller_runs_opens_at_once(self):
        self.ui.activeCommand = ""
        result_dialog.show(big_view(), config.EXPORT_COMMAND_ID)
        self.assertEqual(self.ui.opened, [result_dialog.COMMAND_ID])
        self.assertEqual(self.notices, [])

    def test_a_pending_result_is_dropped_when_the_next_export_starts(self):
        result_dialog.show(big_view(), config.EXPORT_COMMAND_ID)
        result_dialog.drop_pending()
        self.ui.commandTerminated.fire(config.EXPORT_COMMAND_ID)
        self.assertEqual(self.ui.opened, [])
        self.assertEqual(self.boxes, [])

    def test_a_window_that_cannot_start_shows_the_short_message_once(self):
        self.ui.add_fails = True
        shown = big_view()
        result_dialog.show(shown, config.EXPORT_COMMAND_ID)
        self.ui.commandTerminated.fire(config.EXPORT_COMMAND_ID)
        self.ui.commandTerminated.fire(config.EXPORT_COMMAND_ID)
        self.assertEqual(self.boxes, [shown["summary"]])
        self.assertEqual(self.ui.opened, [])

    def test_removing_the_add_in_takes_the_handler_off_and_drops_the_pending_result(self):
        result_dialog.show(big_view(), config.EXPORT_COMMAND_ID)
        self.assertEqual(len(self.ui.commandTerminated.handlers), 1)
        result_dialog.remove()
        self.assertEqual(self.ui.commandTerminated.handlers, [])
        self.ui.commandTerminated.fire(config.EXPORT_COMMAND_ID)
        self.assertEqual(self.ui.opened, [])

    def test_when_the_end_of_commands_cannot_be_heard_the_window_opens_at_once(self):
        result_dialog.remove()
        result_dialog.show(big_view(), config.EXPORT_COMMAND_ID)
        self.assertEqual(self.ui.opened, [result_dialog.COMMAND_ID])


if __name__ == "__main__":
    unittest.main()
