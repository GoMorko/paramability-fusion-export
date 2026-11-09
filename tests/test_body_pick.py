import sys
import types
import unittest

from tests import context  # noqa: F401

from lib.export_plan.sizes_table import new_table
from lib.fusion_reader.bodies import is_pickable_body

# The dialog module imports adsk at load time; a stub is enough for the pure checks below.
if "adsk" not in sys.modules:
    adsk = types.ModuleType("adsk")
    adsk.core = types.ModuleType("adsk.core")
    sys.modules["adsk"], sys.modules["adsk.core"] = adsk, adsk.core
from lib.fusion_ui import export_dialog  # noqa: E402


class Body:
    def __init__(self, solid=True, context=None):
        self.isSolid = solid
        self.assemblyContext = context


class Args:
    def __init__(self, entity):
        self.selection = types.SimpleNamespace(entity=entity)
        self.isSelectable = None


class Item:
    def __init__(self, **kw):
        self.__dict__.update(kw)


def inputs_for(body, extra=None):
    items = {
        export_dialog.BODY_ID: Item(selectionCount=1, selection=lambda i: Item(entity=body)),
        export_dialog.sizes_table_ui.SIZES_GROUP_ID: Item(children=Item(count=0)),
        export_dialog.CHOICE_ID: Item(value="Size"),
        export_dialog.DEFAULT_ID: Item(selectedItem=None),
        export_dialog.UP_ID: Item(selectedItem=None),
    }
    items.update(extra or {})
    return Item(itemById=items.__getitem__)


class BodyPickTest(unittest.TestCase):
    def test_solid_bodies_are_pickable_in_a_component(self):
        self.assertTrue(is_pickable_body(Body(context=object())))
        self.assertTrue(is_pickable_body(Body()))
        self.assertFalse(is_pickable_body(Body(solid=False)))
        self.assertFalse(is_pickable_body(object()))

    def test_preselect_accepts_component_proxy_and_refuses_surface(self):
        args = Args(Body(context=object()))
        export_dialog.allow_preselect(args)
        self.assertTrue(args.isSelectable)
        args = Args(Body(solid=False))
        export_dialog.allow_preselect(args)
        self.assertFalse(args.isSelectable)

    def test_inputs_valid_for_a_component_body(self):
        self.assertTrue(export_dialog.inputs_valid(inputs_for(Body(context=object())), [], new_table([])))
        self.assertFalse(export_dialog.inputs_valid(inputs_for(Body(solid=False)), [], new_table([])))

    def test_text_box_mode_reads_the_sizes_text(self):
        table = new_table([])
        table.text_mode = True
        text_id = export_dialog.sizes_text_ui.SIZES_ID
        view = inputs_for(Body(), {text_id: Item(text="name\nSmall")})
        self.assertTrue(export_dialog.inputs_valid(view, [], table))
        view = inputs_for(Body(), {text_id: Item(text="name\nA\nA")})
        self.assertFalse(export_dialog.inputs_valid(view, [], table))


class ResolveBodyTest(unittest.TestCase):
    def setUp(self):
        sys.modules["adsk.core"].Matrix3D = types.SimpleNamespace(create=lambda: None)
        from lib.fusion_reader import step_export
        self.step_export = step_export

    def design_finding(self, body):
        return types.SimpleNamespace(findEntityByToken=lambda token: [body])

    def test_a_native_lookup_is_put_back_into_the_picked_occurrence(self):
        occurrence = object()
        placed = Body(context=occurrence)
        native = Body()
        native.createForAssemblyContext = lambda context: placed if context is occurrence else None
        picked = Body(context=occurrence)
        self.assertIs(self.step_export.resolve_body(self.design_finding(native), "t", picked), placed)

    def test_a_root_body_lookup_is_used_as_found(self):
        found = Body()
        self.assertIs(self.step_export.resolve_body(self.design_finding(found), "t", Body()), found)


if __name__ == "__main__":
    unittest.main()
