"""The timing block of report.json: the stopwatch, the capture read's breakdown and the export's phases."""
import json
import unittest

from tests import context  # noqa: F401
from tests.test_capture_reader import FakeDesign, body, extrude, rect_profile, sketch_entry
from tests.test_parts_pipeline import FakePartsPort, export as export_parts
from tests.test_parts_pipeline import BASE
from tests.test_pipeline import FakePort, export

from lib.fusion_reader.capture import read_capture
from tests.translator_helpers import load_capture
from lib.translator.translate import translate
from lib.timing.capture_timer import CaptureTimer
from lib.timing.export_timing import PHASES, ExportTiming
from lib.timing.timer import Timer, span_on


class Clock:
    """A clock that moves by the given amounts, one per reading."""

    def __init__(self, *steps):
        self.now, self.steps = 0.0, list(steps)

    def __call__(self):
        if self.steps:
            self.now += self.steps.pop(0)
        return self.now


def broken_clock():
    raise RuntimeError("no clock")


class TimerTest(unittest.TestCase):
    def test_spans_add_up_and_a_nested_span_of_the_same_name_counts_once(self):
        timer = Timer(Clock(0, 1, 0, 2))
        with timer.span("a"):
            with timer.span("a"):
                pass
        with timer.span("a"):
            pass
        self.assertEqual(timer.entry("a"), {"count": 2, "seconds": 3.0})

    def test_an_error_in_the_block_is_not_hidden(self):
        timer = Timer()
        with self.assertRaises(ValueError):
            with timer.span("a"):
                raise ValueError("x")
        self.assertEqual(timer.count("a"), 1)

    def test_a_clock_that_fails_drops_the_measure_and_the_block_still_runs(self):
        timer = Timer(broken_clock)
        ran = []
        with timer.span("a"):
            ran.append(1)
        self.assertEqual((ran, timer.count("a")), ([1], 0))
        with span_on(object(), "a"):
            ran.append(2)
        self.assertEqual(ran, [1, 2])


class CaptureTimerTest(unittest.TestCase):
    def test_the_summary_sums_steps_by_type_and_component_and_lists_the_slowest(self):
        timer = CaptureTimer(Clock(*[0, 1, 0, 3, 0, 2]))
        for index, (name, type_name, component) in enumerate(
                [("S1", "Sketch", "c1"), ("E1", "ExtrudeFeature", "c1"), ("E2", "ExtrudeFeature", "c2")]):
            timer.describe(index, name, type_name, component)
            with timer.step(index):
                pass
        timer.note_component("c1", "Cup")
        summary = timer.summary(top=2)
        self.assertEqual(summary["by_type"], {"ExtrudeFeature": {"steps": 2, "seconds": 5.0},
                                              "Sketch": {"steps": 1, "seconds": 1.0}})
        self.assertEqual(summary["by_component"]["Cup"], {"steps": 2, "seconds": 4.0})
        self.assertEqual([(s["index"], s["name"], s["component"], s["seconds"]) for s in summary["slowest"]],
                         [(1, "E1", "Cup", 3.0), (2, "E2", "c2", 2.0)])


class CaptureReadTest(unittest.TestCase):
    def test_a_read_fills_the_timer_with_one_marker_move_per_position(self):
        target = body()
        design = FakeDesign([sketch_entry(), extrude(rect_profile(), target=target)], target)
        timer = CaptureTimer()
        capture = read_capture(design, target, fusion="", name="", up_axis="z", timer=timer)
        summary = timer.summary()
        self.assertEqual(summary["steps"], 2)
        self.assertEqual(summary["marker_moves"]["walk"], 3)
        self.assertEqual({row["type"] for row in summary["slowest"]}, {"Sketch", "ExtrudeFeature"})
        self.assertNotIn("timing", capture)
        self.assertEqual(json.loads(json.dumps(summary)), summary)


class ExportTimingTest(unittest.TestCase):
    def test_a_single_body_export_reports_the_phases_and_the_probe(self):
        timer = CaptureTimer()
        timer.describe(0, "Sketch1", "Sketch", "c")
        with timer.step(0):
            pass
        port = FakePort()
        port.timing = ExportTiming()
        port.timing.note_capture(timer.summary())
        result = export(port)
        timing = result.report["timing"]
        self.assertEqual(set(timing["phases"]), set(PHASES))
        self.assertEqual(timing["capture"]["steps"], 1)
        self.assertGreater(timing["probe"]["tries"], 0)
        self.assertEqual(set(timing["probe"]), {"tries", "tries_seconds", "rebuild", "read", "read_parts", "put_back",
                                               "try_seconds"})
        self.assertIn("total", timing)
        self.assertEqual(json.loads(result.files["report.json"])["timing"], timing)

    def test_a_several_body_export_lists_the_captures_by_part(self):
        port = FakePartsPort([BASE, BASE])
        port.timing = ExportTiming()
        port.timing.note_capture({"seconds": 1.0}, "Body1")
        timing = export_parts(port).report["timing"]
        self.assertEqual([c["part"] for c in timing["captures"]], ["Body1"])
        self.assertEqual(set(timing["phases"]), set(PHASES))

    def test_a_timer_that_fails_leaves_the_export_whole_and_drops_the_field(self):
        plain = export(FakePort())
        port = FakePort()
        port.timing = ExportTiming(broken_clock)
        result = export(port)
        self.assertNotIn("timing", result.report)
        self.assertNotIn("timing", json.loads(result.files["report.json"]))
        self.assertEqual(result.manifest, plain.manifest)
        self.assertEqual(result.files["recipe.json"], plain.files["recipe.json"])

    def test_the_second_walk_after_a_stop_is_timed(self):
        capture = load_capture("extrude_plate")
        capture["items"][-1]["type"] = "MysteryFeature"
        timer = Timer()
        result = translate(capture, timer=timer)
        self.assertIsNotNone(result.after_stop)
        self.assertEqual(timer.count("after_stop"), 1)
