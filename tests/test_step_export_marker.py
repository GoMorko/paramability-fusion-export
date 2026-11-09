import sys
import types
import unittest

from tests import context  # noqa: F401
from tests.fakes import FakeTimeline
from lib.export_plan.errors import StepExportError

# step_export imports adsk.core at load time; a stub with Matrix3D is enough here.
if "adsk" not in sys.modules:
    adsk = types.ModuleType("adsk")
    adsk.core = types.ModuleType("adsk.core")
    sys.modules["adsk"], sys.modules["adsk.core"] = adsk, adsk.core
if not hasattr(sys.modules["adsk.core"], "Matrix3D"):
    sys.modules["adsk.core"].Matrix3D = types.SimpleNamespace(create=lambda: None)
from lib.fusion_reader.step_export import export_body_step  # noqa: E402

N = types.SimpleNamespace


def coll(items):
    return N(count=len(items), item=lambda i: items[i])


def box():
    point = N(x=0, y=0, z=0)
    return N(minPoint=point, maxPoint=point)


class Design:
    """Two solid bodies in the root, so the body goes through the temporary component. New timeline items insert at
    the marker; deleting the occurrence removes only its own item, so the copy's item is left for the second pass."""

    def __init__(self, tokens, marker, write_ok=True):
        self.timeline = FakeTimeline(tokens, marker=marker)
        self.exported = []
        self.rootComponent = N(bRepBodies=coll([N(isSolid=True), N(isSolid=True)]), allOccurrences=coll([]),
                               occurrences=N(addNewComponent=self._add_component))
        self.exportManager = N(createSTEPExportOptions=lambda path, component: (path, component),
                               execute=lambda options: self.exported.append(options) or write_ok)

    def _add_component(self, matrix):
        entity = self.timeline.insert_at_marker("temp-occurrence")
        return N(component=N(bRepBodies=N(count=0)), deleteMe=entity.deleteMe)

    def body(self):
        def copy_to(occurrence):
            self.timeline.insert_at_marker("temp-copy")
            occurrence.component.bRepBodies.count = 1
            return N(boundingBox=box())
        return N(boundingBox=box(), copyToComponent=copy_to)


class MarkerInTheMiddleTest(unittest.TestCase):
    def test_the_copy_is_removed_and_the_steps_after_the_marker_survive(self):
        design = Design(["s1", "e1", "e2", "f1", "f2"], marker=3)
        export_body_step(design, design.body(), "part.step")
        self.assertEqual(len(design.exported), 1)
        self.assertEqual(design.timeline.tokens(), ["s1", "e1", "e2", "f1", "f2"])
        self.assertEqual(design.timeline.markerPosition, 3)

    def test_a_failed_write_still_removes_the_copy_and_puts_the_marker_back(self):
        design = Design(["s1", "e1", "f1"], marker=2, write_ok=False)
        with self.assertRaises(StepExportError):
            export_body_step(design, design.body(), "part.step")
        self.assertEqual((design.timeline.tokens(), design.timeline.markerPosition), (["s1", "e1", "f1"], 2))

    def test_a_marker_at_the_end_goes_after_items_the_cleanup_left_and_they_are_reported(self):
        design = Design(["s1", "e1"], marker=2)
        body = design.body()
        copy_to = body.copyToComponent

        def copy_with_a_stuck_item(occurrence):
            made = copy_to(occurrence)
            design.timeline.insert_at_marker("stuck")
            design.timeline.items[-1].entity.deleteMe = lambda: None
            return made

        body.copyToComponent = copy_with_a_stuck_item
        with self.assertRaises(StepExportError) as raised:
            export_body_step(design, body, "part.step")
        self.assertIn("left 1 step", str(raised.exception))
        self.assertEqual(design.timeline.markerPosition, len(design.timeline.items))

    def test_an_empty_copy_is_refused_before_writing(self):
        design = Design(["s1", "e1", "f1"], marker=2)
        body = design.body()
        body.copyToComponent = lambda occurrence: design.timeline.insert_at_marker("temp-copy") and None
        with self.assertRaises(StepExportError):
            export_body_step(design, body, "part.step")
        self.assertEqual(design.exported, [])
        self.assertEqual((design.timeline.tokens(), design.timeline.markerPosition), (["s1", "e1", "f1"], 2))


if __name__ == "__main__":
    unittest.main()
