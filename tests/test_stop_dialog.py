import unittest

from tests import context  # noqa: F401
from tests import fakes
from tests.test_recipe_dialog import make_dialog, offer
from tests.test_recipe_export import plate_then_emboss

core = fakes.install_adsk_core()
from lib.export_plan.stop_warning import summarize  # noqa: E402
from lib.fusion_ui import recipe_dialog, timeline_select  # noqa: E402


class WarningBoxTest(unittest.TestCase):
    def test_a_stop_shows_the_step_the_reason_in_a_tooltip_and_the_timeline_button(self):
        _, inputs = make_dialog([offer("wall")])
        recipe_dialog.show_stop(inputs, summarize(plate_then_emboss()))
        box = inputs.itemById(recipe_dialog.WARN_ID)
        self.assertTrue(box.isVisible)
        self.assertTrue(box.formattedText.startswith("<b>Copy stops at Emboss1 (emboss).</b>"))
        self.assertIn("Emboss steps", box.tooltipDescription)
        self.assertTrue(inputs.itemById(recipe_dialog.SHOW_ID).isVisible)

    def test_a_stop_without_a_step_has_no_timeline_button(self):
        _, inputs = make_dialog([offer("wall")])
        recipe_dialog.show_stop(inputs, summarize(RuntimeError("x")))
        self.assertTrue(inputs.itemById(recipe_dialog.WARN_ID).isVisible)
        self.assertFalse(inputs.itemById(recipe_dialog.SHOW_ID).isVisible)

    def test_picking_a_clean_body_hides_the_warning(self):
        _, inputs = make_dialog([offer("wall")])
        recipe_dialog.show_stop(inputs, summarize(plate_then_emboss()))
        recipe_dialog.show_stop(inputs, None)
        self.assertFalse(inputs.itemById(recipe_dialog.WARN_ID).isVisible)
        self.assertFalse(inputs.itemById(recipe_dialog.SHOW_ID).isVisible)

    def test_the_picker_gets_its_body_back_after_a_step_was_selected(self):
        body = type("Body", (), {"entityToken": "b1"})()
        _, inputs = make_dialog([offer("wall")], body)
        picker = inputs.itemById(recipe_dialog.BODY_ID)
        picker.picked[:] = []
        recipe_dialog.restore_body(inputs, body)
        self.assertEqual(picker.picked, [body])


class _Selections:
    def __init__(self, fail=False):
        self.added, self.cleared, self.fail = [], 0, fail

    def clear(self):
        self.cleared += 1

    def add(self, entity):
        if self.fail:
            raise RuntimeError("not selectable")
        self.added.append(entity)


class _Timeline:
    count = 3
    markerPosition = 3

    def __init__(self, entities):
        self.entities = entities

    def item(self, index):
        return type("Obj", (), {"entity": self.entities[index]})()


class SelectStepTest(unittest.TestCase):
    def setUp(self):
        self.selections = _Selections()
        ui = type("UI", (), {"activeSelections": self.selections})()
        app = type("App", (), {"userInterface": ui})
        self.old = getattr(core, "Application", None)
        core.Application = type("Application", (), {"get": staticmethod(lambda: app)})
        self.addCleanup(lambda: setattr(core, "Application", self.old) if self.old else delattr(core, "Application"))

    def test_the_feature_is_selected_and_the_marker_stays(self):
        timeline = _Timeline(["f0", "f1", "f2"])
        design = type("Design", (), {"timeline": timeline})()
        self.assertEqual(timeline_select.select_step(design, 1), "")
        self.assertEqual(self.selections.added, ["f1"])
        self.assertEqual(timeline.markerPosition, 3)

    def test_a_step_without_a_feature_or_outside_the_timeline_gives_a_message(self):
        design = type("Design", (), {"timeline": _Timeline(["f0", None, "f2"])})()
        self.assertEqual(timeline_select.select_step(design, 1), timeline_select.CANNOT_SELECT)
        self.assertEqual(timeline_select.select_step(design, 7), timeline_select.CANNOT_SELECT)
        self.assertEqual(self.selections.added, [])

    def test_a_refused_selection_gives_a_message(self):
        self.selections.fail = True
        design = type("Design", (), {"timeline": _Timeline(["f0", "f1", "f2"])})()
        self.assertEqual(timeline_select.select_step(design, 0), timeline_select.CANNOT_SELECT)
