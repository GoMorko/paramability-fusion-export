"""Fake command inputs and command for the dialog tests, and the `adsk.core` stand in they cast with."""
from tests.fakes.design import FakeItem


# Fake command inputs for the dialog tests. They keep what the code sets, like Fusion's inputs do.


class FakeInput:
    def __init__(self, input_id, **kw):
        self.id = input_id
        self.isEnabled = True
        self.isVisible = True
        self.__dict__.update(kw)


class FakeCheckbox(FakeInput):
    """Like Fusion's check box: its label cannot be set after creation."""

    def __init__(self, input_id, text="", value=False, **kw):
        super().__init__(input_id, value=value, **kw)
        self._text = text

    @property
    def text(self):
        return self._text

    @text.setter
    def text(self, _):
        raise RuntimeError("2 : InternalValidationError : button")


class FakeTextBox(FakeInput):
    def __init__(self, input_id, formattedText="", numRows=1, **kw):
        super().__init__(input_id, formattedText=formattedText, numRows=numRows, **kw)


class FakeStringInput(FakeInput):
    def __init__(self, input_id, value="", **kw):
        super().__init__(input_id, value=value, **kw)


class FakeListItems:
    def __init__(self):
        self.items = []

    def add(self, name, selected):
        self.items.append(FakeItem(name=name, isSelected=selected))


class FakeDropDown(FakeInput):
    def __init__(self, input_id, **kw):
        super().__init__(input_id, **kw)
        self.listItems = FakeListItems()

    @property
    def selectedItem(self):
        return next((i for i in self.listItems.items if i.isSelected), None)


class FakeSelection(FakeInput):
    def __init__(self, input_id, **kw):
        super().__init__(input_id, **kw)
        self.picked = []
        self.filters = []

    def addSelectionFilter(self, name):
        self.filters.append(name)

    def setSelectionLimits(self, low, high):
        self.limits = (low, high)

    def addSelection(self, entity):
        self.picked.append(entity)

    def clearSelection(self):
        self.picked.clear()

    @property
    def selectionCount(self):
        return len(self.picked)

    def selection(self, index):
        return FakeItem(entity=self.picked[index])


class FakeTable(FakeInput):
    """Cells by (row, column). selectedRow is -1 when nothing is selected, like Fusion."""

    def __init__(self, input_id, columns, ratio, **kw):
        super().__init__(input_id, **kw)
        self.columns, self.ratio, self.selectedRow = columns, ratio, -1
        self.cells, self.toolbar = {}, []

    def addCommandInput(self, item, row, column):
        self.cells[(row, column)] = item

    def addToolbarCommandInput(self, item):
        self.toolbar.append(item)

    def getInputAtPosition(self, row, column):
        return self.cells.get((row, column))

    @property
    def rowCount(self):
        return 1 + max((r for r, _ in self.cells), default=-1)


class FakeInputs:
    """A command's inputs (or a group's children): add* methods register inputs by id."""

    def __init__(self):
        self.items = {}

    def _add(self, item):
        self.items[item.id] = item
        return item

    def itemById(self, input_id):
        return self.items.get(input_id)

    def addSelectionInput(self, input_id, name, prompt):
        return self._add(FakeSelection(input_id))

    def addDropDownCommandInput(self, input_id, name, style):
        return self._add(FakeDropDown(input_id))

    def addTextBoxCommandInput(self, input_id, name, text, rows, read_only):
        return self._add(FakeTextBox(input_id, text, rows))

    def addStringValueInput(self, input_id, name, value):
        return self._add(FakeStringInput(input_id, value))

    def addBoolValueInput(self, input_id, name, is_check_box, resources, value):
        return self._add(FakeCheckbox(input_id, name, value, isCheckBox=is_check_box))

    def addTableCommandInput(self, input_id, name, columns, ratio):
        return self._add(FakeTable(input_id, columns, ratio))

    def addGroupCommandInput(self, input_id, name):
        group = self._add(FakeInput(input_id, name=name, isExpanded=False))
        group.children = FakeInputs()
        self.items.update(group.children.items)
        group.children.items = self.items
        return group


class FakeCommand:
    def __init__(self):
        self.commandInputs = FakeInputs()
        self.isOKButtonVisible = True
        self.cancelButtonText = "Cancel"

    def setDialogInitialSize(self, width, height):
        self.size = (width, height)


def install_adsk_core():
    """Make `import adsk.core` work and give the dialog code the Fusion classes it casts to. Safe to call twice."""
    import sys
    import types

    if "adsk" not in sys.modules:
        sys.modules["adsk"] = types.ModuleType("adsk")
        sys.modules["adsk.core"] = types.ModuleType("adsk.core")
        sys.modules["adsk"].core = sys.modules["adsk.core"]
    core = sys.modules["adsk.core"]

    def caster(kind):
        return type(kind, (), {"cast": staticmethod(lambda item: item)})

    for kind in ("BoolValueCommandInput", "StringValueCommandInput", "TableCommandInput", "TextBoxCommandInput"):
        setattr(core, kind, caster(kind))
    for kind in ("CommandCreatedEventHandler", "CommandEventHandler", "InputChangedEventHandler",
                 "ValidateInputsEventHandler", "SelectionEventHandler", "CustomEventHandler"):
        setattr(core, kind, type(kind, (), {}))
    core.DropDownStyles = types.SimpleNamespace(TextListDropDownStyle=0)
    return core
