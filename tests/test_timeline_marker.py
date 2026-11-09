import os
import tempfile
import unittest

from tests import context  # noqa: F401
from tests.fakes import FakeDesign
from tests.translator_helpers import load_capture
from lib.export_plan.apply import measure_baseline
from lib.export_plan.marker import marker_note, read_marker
from lib.export_plan.recipe_export import plan_single_export
from lib.fusion_reader.rows import DesignParameterStore
from tests.row_helpers import apply_row


class Timeline:
    def __init__(self, items, marker):
        self.items, self.markerPosition = items, marker

    @property
    def count(self):
        return len(self.items)

    def item(self, i):
        return self.items[i]

    def moveToEnd(self):
        self.markerPosition = self.count


class Item:
    def __init__(self, name, health=0):
        self.name, self.healthState, self.isSuppressed = name, health, False


class RolledBackDesign(FakeDesign):
    """A design whose recompute moves the marker to the end and breaks the step after the marker."""

    def __init__(self, marker):
        super().__init__([dict(name="width", expression="20 mm", value=2.0, unit="mm")])
        self.timeline = Timeline([Item("Sketch1"), Item("Extrude1"), Item("Fillet1")], marker)

    def computeAll(self):
        self.timeline.markerPosition = self.timeline.count
        self.timeline.items[2].healthState = 2
        return True


class StoreAtTheMarkerTest(unittest.TestCase):
    def test_a_row_keeps_the_marker_and_ignores_steps_after_it(self):
        design = RolledBackDesign(marker=2)
        baseline = measure_baseline(DesignParameterStore(design))
        self.assertEqual(apply_row(design, {"width": 40.0}, {"width": "mm"}, baseline), {"width": 40.0})
        self.assertEqual(design.timeline.markerPosition, 2)


class MarkerHelpersTest(unittest.TestCase):
    def test_the_dialog_line_shows_only_for_a_rolled_back_marker(self):
        self.assertIsNone(marker_note(read_marker(Timeline([Item("a")], 1))))
        self.assertIsNone(marker_note(None))
        self.assertIsNotNone(marker_note(read_marker(Timeline([Item("a"), Item("b")], 1))))

    def test_the_report_records_the_marker(self):
        with tempfile.TemporaryDirectory() as tmp:
            step = os.path.join(tmp, "part.step")
            with open(step, "wb") as f:
                f.write(b"ISO-10303-21;")
            marker = {"position": 2, "count": 5}
            _, _, report = plan_single_export(load_capture("extrude_plate"), step, "Plate", "w", "z", marker=marker)
        self.assertEqual(report["marker"], marker)


if __name__ == "__main__":
    unittest.main()
