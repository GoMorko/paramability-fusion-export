import sys
import types
import unittest

from tests import context  # noqa: F401


class FakeCheckbox:
    """Like Fusion's check box: its label cannot be set after creation."""

    def __init__(self, text, value):
        self.__dict__.update(_text=text, value=value, isEnabled=True, tooltip="")

    @property
    def text(self):
        return self._text

    @text.setter
    def text(self, _):
        raise RuntimeError("2 : InternalValidationError : button")


class FakeTextBox:
    def __init__(self):
        self.formattedText = ""
        self.isVisible = True


class FakeInputs:
    def __init__(self, items):
        self.items = items

    def itemById(self, item_id):
        return self.items.get(item_id)


class _CheckboxType:
    @staticmethod
    def cast(item):
        return item if isinstance(item, FakeCheckbox) else None


if "adsk" not in sys.modules:
    sys.modules["adsk"] = types.ModuleType("adsk")
    sys.modules["adsk.core"] = types.ModuleType("adsk.core")
    sys.modules["adsk"].core = sys.modules["adsk.core"]
sys.modules["adsk.core"].BoolValueCommandInput = _CheckboxType
from lib.fusion_ui import recipe_dialog  # noqa: E402


def offer(param, ticked, enabled, reason="", text=None):
    return {"param": param, "text": text or param, "ticked": ticked, "enabled": enabled, "reason": reason}


def make_dialog(offers):
    items = {recipe_dialog.BOX_PREFIX + str(i): FakeCheckbox(o["param"], o["ticked"]) for i, o in enumerate(offers)}
    for i, o in enumerate(offers):
        items[recipe_dialog.BOX_PREFIX + str(i)].isEnabled = o["enabled"]
    items[recipe_dialog.LIMIT_ID] = FakeTextBox()
    items[recipe_dialog.FIXED_ID] = FakeTextBox()
    return FakeInputs(items)


class ApplyOffersTest(unittest.TestCase):
    def test_new_body_updates_ticks_enabled_state_and_reasons(self):
        offers = [offer("width", True, True), offer("depth", False, False, "Old reason")]
        inputs = make_dialog(offers)
        fresh = [offer("width", False, False, "Cut by a sketch", "width, 5 mm"), offer("depth", True, True)]
        recipe_dialog.apply_offers(inputs, offers, fresh)
        width, depth = inputs.itemById("pm_size_0"), inputs.itemById("pm_size_1")
        self.assertEqual((width.value, width.isEnabled), (False, False))
        self.assertEqual((depth.value, depth.isEnabled), (True, True))
        self.assertIn("Cut by a sketch", width.tooltip)
        self.assertEqual(offers, fresh)
        self.assertEqual(inputs.itemById(recipe_dialog.FIXED_ID).formattedText, "width, 5 mm: Cut by a sketch")

    def test_one_failing_line_leaves_the_others_updated_and_its_entry_old(self):
        offers = [offer("a", True, True), offer("b", True, True)]
        inputs = make_dialog(offers)

        class Broken(FakeCheckbox):
            @property
            def isEnabled(self):
                return True

            @isEnabled.setter
            def isEnabled(self, _):
                if getattr(self, "armed", False):
                    raise RuntimeError("boom")

        broken = Broken("a", True)
        broken.armed = True
        inputs.items["pm_size_0"] = broken
        fresh = [offer("a", False, False, "x"), offer("b", False, True)]
        recipe_dialog.apply_offers(inputs, offers, fresh)
        self.assertEqual(offers[0]["ticked"], True)
        self.assertEqual(offers[1], fresh[1])
        self.assertFalse(inputs.itemById("pm_size_1").value)


if __name__ == "__main__":
    unittest.main()
