"""The result window: its groups and their order, the short message, and the later fires of its event (fakes with the
names of the Fusion API)."""
import types
import unittest
from unittest import mock

from tests import context  # noqa: F401
from tests import fakes
from tests.test_reopen import SAVED, offered_view, setup
from tests.test_result_rows import view as plain_view
from lib.fusion_ui import reopen as reopen_ui

core = fakes.install_adsk_core()
from lib.fusion_ui import event_retry, result_dialog  # noqa: E402


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


class FakeTimer:
    """A `threading.Timer` that runs only when the test says so."""
    made = []

    def __init__(self, delay, function, args=()):
        self.delay, self.function, self.args = delay, function, args
        self.cancelled = self.started = False
        self.daemon = False
        FakeTimer.made.append(self)

    def start(self):
        self.started = True

    def cancel(self):
        self.cancelled = True


def run_timers(limit=20):
    """Run the pending timers one after the other, as the clock would; returns how many ran."""
    ran = 0
    while ran < limit:
        pending = [t for t in FakeTimer.made if t.started and not t.cancelled and not getattr(t, "ran", False)]
        if not pending:
            break
        pending[0].ran = True
        pending[0].function(*pending[0].args)
        ran += 1
    return ran


class RefusingApp:
    """An `Application` whose fires answer from a script (True or False), then False. A True fire runs the handler."""

    def __init__(self, answers, on_fire=None):
        self.answers, self.fired, self.on_fire = list(answers), [], on_fire
        self.userInterface = types.SimpleNamespace(
            commandDefinitions=types.SimpleNamespace(itemById=lambda i: None), activeCommand="")
        self.logged = []

    def unregisterCustomEvent(self, event_id):
        return True

    def registerCustomEvent(self, event_id):
        return types.SimpleNamespace(add=lambda handler: True)

    def fireCustomEvent(self, event_id):
        self.fired.append(event_id)
        ok = self.answers.pop(0) if self.answers else False
        if ok and self.on_fire:
            self.on_fire()
        return ok

    def log(self, text):
        self.logged.append(text)


class RetryTest(unittest.TestCase):
    def setUp(self):
        FakeTimer.made.clear()
        self.boxes, self.logs = [], []
        self.patches = [
            mock.patch.object(event_retry, "new_timer", FakeTimer),
            mock.patch.object(result_dialog, "message_box", self.boxes.append),
            mock.patch.object(result_dialog, "log", self.logs.append),
            mock.patch.object(event_retry, "log", self.logs.append),
            mock.patch.object(reopen_ui, "message_box", lambda *a, **k: self.boxes.append(a)),
            mock.patch.object(reopen_ui, "log", self.logs.append),
            mock.patch.object(result_dialog, "status_notice", lambda text: self.logs.append("status: " + text)),
            mock.patch.object(reopen_ui, "status_notice", lambda text: self.logs.append("status: " + text)),
        ]
        for patch in self.patches:
            patch.start()
        self.addCleanup(lambda: [patch.stop() for patch in self.patches])
        self.addCleanup(event_retry.cancel)

    def use(self, app):
        patch = mock.patch.object(core, "Application", types.SimpleNamespace(get=lambda: app), create=True)
        patch.start()
        self.addCleanup(patch.stop)

    def test_a_fire_that_works_later_opens_the_window_once_and_shows_no_message_box(self):
        opened = []
        app = RefusingApp([False, False, False, True], on_fire=lambda: opened.append(True))
        self.use(app)
        result_dialog.show(big_view())
        self.assertEqual(len(app.fired), 2)  # the fire and the one after registering the event again
        self.assertEqual(len(FakeTimer.made), 1)
        self.assertEqual(FakeTimer.made[0].delay, event_retry.DELAYS[0])
        run_timers()
        self.assertEqual(len(app.fired), 4)
        self.assertEqual(len(opened), 1)
        self.assertEqual(self.boxes, [])
        self.assertEqual(len(FakeTimer.made), 2)  # no try after the one that fired
        self.assertTrue(any(line.startswith("status: ") for line in self.logs))

    def test_a_fire_that_raises_is_tried_again_the_same_way(self):
        app = RefusingApp([])
        calls = []

        def fire(event_id):
            calls.append(event_id)
            if len(calls) < 3:
                raise RuntimeError("busy")
            return True
        app.fireCustomEvent = fire
        self.use(app)
        result_dialog.show(big_view())
        run_timers()
        self.assertEqual(self.boxes, [])
        self.assertEqual(len(calls), 3)

    def test_when_every_try_fails_the_summary_goes_to_the_log_once_and_no_box_opens(self):
        app = RefusingApp([])
        self.use(app)
        result_dialog.show(big_view())
        self.assertEqual(run_timers(), len(event_retry.DELAYS))
        self.assertEqual(self.boxes, [])
        self.assertEqual(sum(1 for line in self.logs if line == result_dialog.summary(big_view())), 1)
        self.assertEqual(run_timers(), 0)

    def test_a_window_that_cannot_start_shows_the_short_message_once(self):
        app = RefusingApp([True])
        app.userInterface.commandDefinitions = types.SimpleNamespace(itemById=mock.Mock(side_effect=RuntimeError("x")))
        self.use(app)
        shown = big_view()
        result_dialog.show(shown)
        result_dialog.on_event(None)
        result_dialog.on_event(None)
        self.assertEqual(self.boxes, [shown["summary"]])

    def test_removing_the_add_in_cancels_the_pending_tries(self):
        app = RefusingApp([])
        app.userInterface.commandDefinitions = types.SimpleNamespace(itemById=lambda i: None)
        self.use(app)
        result_dialog.show(big_view())
        stale = FakeTimer.made[0]
        result_dialog.remove()
        self.assertTrue(stale.cancelled)
        before = len(app.fired)
        stale.function(*stale.args)  # a timer that had already started
        self.assertEqual(len(app.fired), before)
        self.assertEqual(run_timers(), 0)

    def test_the_reopen_is_tried_again_in_the_same_way(self):
        app, document, calls = setup()
        script = RefusingApp([False, False, True])
        app.fireCustomEvent = script.fireCustomEvent
        app.unregisterCustomEvent = script.unregisterCustomEvent
        app.registerCustomEvent = script.registerCustomEvent
        self.use(app)
        reopen_ui.keep(document, SAVED)
        reopen_ui.request(result_dialog.COMMAND_ID)
        self.assertEqual(len(script.fired), 2)
        run_timers()
        self.assertEqual(len(script.fired), 3)
        self.assertEqual(self.boxes, [])
        reopen_ui.run_pending()
        self.assertEqual(calls, [("end window",), ("close", False), ("open", 4, True)])

    def test_a_reopen_that_never_fires_is_logged_and_the_pending_tries_end_with_the_add_in(self):
        app, document, _ = setup()
        script = RefusingApp([])
        app.fireCustomEvent = script.fireCustomEvent
        app.unregisterCustomEvent = script.unregisterCustomEvent
        app.registerCustomEvent = script.registerCustomEvent
        self.use(app)
        reopen_ui.keep(document, SAVED)
        reopen_ui.request(result_dialog.COMMAND_ID)
        timer = FakeTimer.made[0]
        reopen_ui.remove()
        self.assertTrue(timer.cancelled)
        self.assertEqual(self.boxes, [])


if __name__ == "__main__":
    unittest.main()
