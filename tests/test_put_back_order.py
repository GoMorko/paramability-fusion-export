"""The order of the Fusion calls an export makes to put the design back, on every way it ends. A recording store,
port, sketch keeper and Undo step note each call in one list; each batch of try rows counts as one entry."""
import dataclasses
import tempfile
import unittest
from unittest import mock

from tests import context  # noqa: F401
from tests.fakes import FakePartsPort, FakePort, TrimStore, shifted
from tests.test_parts_pipeline import request as parts_request
from tests.test_pipeline import START
from tests.test_pipeline import request as single_request
from tests.test_timeline_trim import trim_capture

from lib.design_edit.errors import StepExportError
from lib.design_edit.runner import ExportCancelled
from lib.export_plan import undo_steps
from lib.export_plan.pipeline import ProbeRun, run_parts_pipeline, run_pipeline

# Store calls made before every read; they say nothing about the order of the put back.
QUIET = {"marker_holds", "read_value", "error_items", "error_entries"}


class Log:
    """The calls in order. While `rows` is above zero the calls are not noted: a batch of rows is one entry."""

    def __init__(self):
        self.calls, self.rows = [], 0

    def note(self, text):
        if not self.rows:
            self.calls.append(text)


def _shown(args):
    """The arguments of a call, short: index pairs by index, a dict by its names, long texts by their count."""
    out = []
    for arg in args:
        if isinstance(arg, dict):
            arg = ", ".join(arg) if len(arg) < 3 else "%d values" % len(arg)
        elif isinstance(arg, (list, tuple)) and arg and all(isinstance(a, str) and len(a) > 40 for a in arg):
            arg = "lines=%d" % len(arg)
        elif isinstance(arg, (list, tuple)):
            arg = [a[0] if isinstance(a, tuple) else a for a in arg]
        out.append(str(arg))
    return "(%s)" % ", ".join(out) if out else ""


class Recorded:
    """`target` with each call of a member noted in `log` as "<prefix>.<name>(<args>)"."""

    def __init__(self, target, log, prefix, quiet=()):
        object.__setattr__(self, "_target", target)
        object.__setattr__(self, "_log", log)
        object.__setattr__(self, "_prefix", prefix)
        object.__setattr__(self, "_quiet", set(quiet))

    def __getattr__(self, name):
        value = getattr(self._target, name)
        if not callable(value) or name in self._quiet:
            return value

        def call(*args, **kw):
            self._log.note("%s.%s%s" % (self._prefix, name, _shown(args)))
            return value(*args, **kw)
        return call

    def __setattr__(self, name, value):
        setattr(self._target, name, value)


class OrderStore(TrimStore):
    """A trim store with two timeline steps. `changed` names a step that reads in a warning once a value changed,
    until a full rebuild with the marker home and every value back (never without `heals`); `stuck_param` a parameter
    that will not go back to its saved expression; `broken_above` a depth that leaves a step in error for good."""

    def __init__(self, changed=None, heals=True, stuck=(), stuck_param=None, broken_above=None):
        super().__init__(START, stays_off=stuck, stuck=[stuck_param] if stuck_param else (),
                         breaks=("depth_mm", broken_above) if broken_above is not None else None)
        self.saved = dict(START)
        self.changed, self.heals, self.warning, self.home = changed, heals, False, False

    def set_expression(self, name, expression):
        super().set_expression(name, expression)
        if expression != self.saved[name]:
            self.warning = self.changed is not None

    def unroll_marker(self):
        self.home = True
        return super().unroll_marker()

    def recompute(self):
        if self.heals and self.home and self.exprs == self.saved:
            self.warning = False
        return super().recompute()

    def timeline_health(self):
        steps = [{"index": 0, "name": "Sketch1", "type": "Sketch", "health": "ok", "message": "", "suppressed": False},
                 {"index": 1, "name": self.changed or "Fillet1", "type": "FilletFeature",
                  "health": "warning" if self.warning else "ok", "message": "", "suppressed": False}]
        if self.broken:
            steps.append({"index": 2, "name": "RemoveBody1", "type": "RemoveFeature", "health": "error",
                          "message": "", "suppressed": False})
        return steps

    def turn_on(self, steps):
        return []

    def return_marker(self):
        return ""


class Keeper:
    def __init__(self, port):
        self.port, self.deferred_left = port, []

    def put_back(self):
        self.port.flipped = False
        return 1


def order_port(store, flip=False, **options):
    """The single body port over an `OrderStore`; with `flip` the sketch goes to its other solution in the first try
    and stays there with the values back until the keeper puts it back."""
    def read(request):
        if flip and port.store.exprs != START:
            port.flipped = True
        return shifted(port.e0, 0.5) if port.flipped and port.store.exprs == START else port.e0

    port = FakePort(capture=trim_capture(), store=store, reader=read, keeper=lambda tokens: Keeper(port), **options)
    port.flipped = False
    return port


def order_parts_port(store, **options):
    """Two bodies over an `OrderStore`."""
    return FakePartsPort([trim_capture(), trim_capture()], store=store, **options)


def recorded(port):
    """`port` with its store, reads, sketch keeper, warnings, log and Undo steps noted in one `Log`."""
    log = Log()
    port.store = Recorded(port.store, log, "store", QUIET)
    reader, keeper, port_log = port.probe_reader, port.sketch_keeper, port.log

    def probe_reader(*index):
        read = reader(*index)

        def noted(request):
            log.note("read(%s)" % ("outline" if "params" not in request else "full"))
            return read(request)
        return noted

    def sketch_keeper(tokens):
        kept = keeper(tokens)
        return Recorded(kept, log, "keeper") if kept is not None else None

    def noted_log(text):
        log.note("log(%s)" % text.split(":")[0])
        port_log(text)

    def warning(name, method):
        def warn(*args):
            log.note("port.%s%s" % (name, _shown(args)))
            return method(*args)
        return warn

    port.probe_reader, port.sketch_keeper, port.log = probe_reader, sketch_keeper, noted_log
    for name in ("warn_unrestored", "warn_left_off", "warn_steps"):
        setattr(port, name, warning(name, getattr(port, name)))
    undo_steps.attach(port, undo_steps.UndoSteps(lambda flag: log.note("undo.drop") or True, port.log))
    return port, log


def export(port, parts=False):
    """The calls of one export and its health (None when it raised)."""
    port, log = recorded(port)
    original = ProbeRun.try_rows

    def try_rows(run, rows):
        log.note("rows")
        log.rows += 1
        try:
            return original(run, rows)
        finally:
            log.rows -= 1

    run, asked = (run_parts_pipeline, parts_request()) if parts else (run_pipeline, single_request())
    health = None
    with mock.patch.object(ProbeRun, "try_rows", try_rows), tempfile.TemporaryDirectory() as tmp:
        try:
            health = run(port, dataclasses.replace(asked, faster_tries=True), tmp).health
        except (ExportCancelled, StepExportError):
            pass
    return log.calls, health


# What every export that tries sizes does first: values and steps saved, the marker held, unused items turned off
# (each a read that checks the design reads the same).
START_ONE = ["store.saved_expressions", "store.timeline_health", "read(full)", "store.roll_marker(9)", "read(full)",
             "store.suppress_items([6, 7])", "read(full)"]
START_TWO = ["store.saved_expressions", "store.timeline_health", "read(full)", "read(full)", "store.roll_marker(9)",
             "read(full)", "read(full)", "store.suppress_items([6, 7])", "read(full)", "read(full)"]
# The end check with nothing changed: the marker back, then the steps compared with the start.
END_CHECK = ["store.unroll_marker", "store.return_marker", "store.timeline_health"]
# The end check found a changed step: a full rebuild, then the steps and the marker read again.
FULL_COMPUTE = ["store.recompute", "store.timeline_health"]
VALUES_AGAIN = ["store.set_expressions(8 values)", "store.current_expressions", "store.recompute",
                "store.timeline_health"]
STUCK_BACK = ["store.current_expressions", "store.set_expressions(box_count)", "store.set_expression(box_count, 3)",
              "store.set_expression(box_count, 3)", "store.recompute"]


class SingleBodyOrderTest(unittest.TestCase):
    maxDiff = None

    def test_a_clean_export_puts_everything_back_then_drops_the_last_undo_step(self):
        calls, health = export(order_port(OrderStore()))
        self.assertEqual(calls, START_ONE + [
            "rows", "rows", "rows", "rows",
            "read(full)",  # the discovery base
            "store.current_expressions", "store.unsuppress_items", "read(outline)", "undo.drop",  # tries done
            "read(full)",  # the probe's last read
            "store.current_expressions", "read(full)", *END_CHECK,
            "read(full)",  # the body compared with its start
            "store.current_expressions", "undo.drop",  # closed
        ])
        self.assertTrue(health["undo_dropped"])

    def test_a_sketch_put_back_an_end_rebuild_and_a_step_left_off(self):
        calls, health = export(order_port(OrderStore(changed="Fillet1", stuck=["Lid sketch"]), flip=True))
        self.assertEqual(calls, START_ONE + [
            "rows", "rows", "rows", "rows",
            "read(full)", "keeper.put_back", "store.recompute", "read(full)",
            "store.current_expressions", "store.unsuppress_items", "log(steps still turned off)", "read(outline)",
            "undo.drop",
            "read(full)",
            "store.current_expressions", "read(full)", *END_CHECK, *FULL_COMPUTE, "store.return_marker",
            "read(outline)",  # the sketches after the end rebuild
            "read(full)",  # the body compared with its start
            "store.current_expressions", "port.warn_left_off(['Lid sketch'], True)",  # closed, no Undo drop
        ])
        self.assertEqual(health["end_actions"], ["full_compute"])

    def test_a_step_that_stays_changed_gets_the_values_again_and_keeps_the_undo_data(self):
        calls, health = export(order_port(OrderStore(changed="Fillet1", heals=False)))
        self.assertEqual(calls, START_ONE + [
            "rows", "rows", "rows", "rows",
            "read(full)",
            "store.current_expressions", "store.unsuppress_items", "read(outline)", "undo.drop",
            "read(full)",
            "store.current_expressions", "read(full)", *END_CHECK, *FULL_COMPUTE, *VALUES_AGAIN,
            "store.return_marker", "read(outline)", "read(full)",
            "store.current_expressions",
        ])
        self.assertEqual(health["end_actions"], ["full_compute", "values_again"])

    def test_a_failed_probe_puts_back_after_its_log_line(self):
        calls, health = export(order_port(OrderStore(), fail_read_from=8))
        self.assertEqual(calls, START_ONE + [
            "rows", "log(size probe failed)",
            "store.current_expressions", "store.unsuppress_items", "read(outline)",
            "log(putting a sketch back after the tries failed)",  # not read back: the Undo data is kept
            "store.current_expressions", "read(full)", "log(reading the sketches after the restore failed)",
            *END_CHECK, "read(full)",
            "store.current_expressions",
        ])
        self.assertEqual(health["probe"], "failed")

    def test_a_cancel_puts_back_then_warns_about_values_steps_and_items(self):
        store = OrderStore(changed="Fillet1", heals=False, stuck=["Lid sketch"], stuck_param="box_count")
        calls, health = export(order_port(store, cancel_at=4))
        def walk(count, size):
            return ["store.set_expressions(box_count, cube_mm)", "store.set_expression(box_count, %s)" % count,
                    "store.set_expression(cube_mm, %s mm)" % size, "store.recompute"]
        back = ["store.current_expressions", "store.set_expressions(box_count, cube_mm)",
                "store.set_expression(box_count, 3)", "store.set_expression(cube_mm, 26 mm)",
                "store.set_expression(box_count, 3)", "store.recompute"]
        check = ["store.timeline_health", "store.recompute", "store.timeline_health"]
        self.assertEqual(calls, START_ONE + [
            "rows",
            # The check the cancelled try asked for runs before any Undo drop: Fillet1 stays worse after both ways back.
            *STUCK_BACK, *check, *walk("-0.625", "26.65"), *back, *check,
            *walk(2, "21.125"), *walk(1, "22.75"), *walk(1, "24.375"), *back, *check, "log(tries stopped)",
            "store.unsuppress_items", "log(steps still turned off)", "read(outline)",  # no Undo drop
            *STUCK_BACK, "store.unroll_marker",  # closed: values and marker back, then the warnings
            "port.warn_unrestored(['box_count'])",
            "store.return_marker", "store.timeline_health", *FULL_COMPUTE, "store.set_expressions(8 values)",
            *STUCK_BACK, "store.recompute", "store.timeline_health", "store.return_marker",
            "port.warn_steps(lines=1)", "port.warn_left_off(['Lid sketch'], True)",
        ])
        self.assertIsNone(health)

    def test_a_failing_warning_does_not_hide_the_cancel(self):
        store = OrderStore(changed="Fillet1", heals=False, stuck=["Lid sketch"], stuck_param="box_count")
        port = order_port(store, cancel_at=4)

        def broken(*args):
            raise RuntimeError("no message box")
        port.warn_unrestored = port.warn_left_off = broken
        with tempfile.TemporaryDirectory() as tmp, self.assertRaises(ExportCancelled):
            run_pipeline(port, dataclasses.replace(single_request(), faster_tries=True), tmp)
        self.assertEqual(len(port.warned_steps), 1)  # the warning after the failed one still runs
        failed = [text.split(":")[0] for text in port.logs if text.startswith("telling the person")]
        self.assertEqual(failed, ["telling the person about the parameters that did not go back failed",
                                  "telling the person about the timeline items left off failed"])

    def test_tries_stopped_on_a_broken_design(self):
        calls, health = export(order_port(OrderStore(broken_above=70)))
        self.assertEqual(calls, START_ONE + [
            "rows", "read(outline)", "rows",
            "store.current_expressions", "store.unsuppress_items", "read(outline)",  # a step worse: no Undo drop
            "read(full)",
            "store.current_expressions", "read(full)", *END_CHECK, *FULL_COMPUTE, *VALUES_AGAIN,
            "store.return_marker", "read(outline)", "read(full)",
            "store.current_expressions",
        ])
        self.assertIn("tries_stopped", health)

    def test_a_step_file_that_fails_before_the_tries(self):
        calls, _ = export(order_port(OrderStore(), fail_step_at=1))
        self.assertEqual(calls, ["store.saved_expressions", "store.timeline_health",
                                 "store.current_expressions", "store.return_marker", "store.timeline_health"])


class SeveralBodiesOrderTest(unittest.TestCase):
    maxDiff = None

    def test_a_clean_export_of_two_bodies(self):
        calls, health = export(order_parts_port(OrderStore(changed="Fillet1")), parts=True)
        self.assertEqual(calls, START_TWO + [
            "rows", "rows", "rows", "rows",
            "read(full)", "read(full)",
            "store.current_expressions", "store.unsuppress_items", "read(outline)", "read(outline)", "undo.drop",
            "read(full)", "read(full)",
            "store.current_expressions", "read(full)", "read(full)", *END_CHECK, *FULL_COMPUTE,
            "store.return_marker", "read(outline)", "read(outline)", "read(full)", "read(full)",
            "store.current_expressions", "undo.drop",
        ])
        self.assertEqual(health["steps_recovered"], ["Fillet1"])

    def test_a_cancel(self):
        calls, _ = export(order_parts_port(OrderStore(changed="Fillet1", heals=False, stuck=["Lid sketch"]),
                                         cancel_at=3), parts=True)
        self.assertEqual(calls, START_TWO + [
            "rows",
            "store.current_expressions", "store.unsuppress_items", "log(steps still turned off)", "read(outline)",
            "read(outline)", "undo.drop",
            "store.current_expressions", "store.unroll_marker",
            "store.return_marker", "store.timeline_health", *FULL_COMPUTE, *VALUES_AGAIN, "store.return_marker",
            "port.warn_steps(lines=1)", "port.warn_left_off(['Lid sketch'], True)",
        ])

    def test_a_failed_probe(self):
        calls, health = export(order_parts_port(OrderStore(), fail_read_from=9), parts=True)
        self.assertEqual(calls, START_TWO + [
            "rows", "log(size probe failed)",
            "store.current_expressions", "store.unsuppress_items", "read(outline)",
            "log(putting a sketch back after the tries failed)",
            "store.current_expressions", "read(full)", "log(reading the sketches after the restore failed)",
            *END_CHECK, "read(full)", "read(full)",
            "store.current_expressions",
        ])
        self.assertEqual(health["probe"], "failed")

    def test_a_step_file_that_fails_before_the_tries(self):
        calls, _ = export(order_parts_port(OrderStore(), fail_step_at=2), parts=True)
        self.assertEqual(calls, ["store.saved_expressions", "store.timeline_health",
                                 "store.current_expressions", "store.return_marker", "store.timeline_health"])


if __name__ == "__main__":
    unittest.main()
