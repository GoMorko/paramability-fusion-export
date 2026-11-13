"""Fake parameter store and fake Fusion design for tests."""
import math
import re


class FakeStore:
    """Parameter store holding expressions as text. Values are the leading number as Fusion stores it (mm to cm, deg to rad)."""

    def __init__(self, expressions, bad_when=None, reject=(), flaky=(), bad_item="Fillet1"):
        self.exprs = dict(expressions)
        self.bad_when = bad_when or (lambda exprs: False)
        self.bad_item = bad_item  # the timeline item that goes into error when `bad_when` holds
        self.reject = set(reject)  # values that set_expression always refuses
        self.flaky = set(flaky)  # names refused once, then accepted
        self.recomputes = 0

    def saved_expressions(self):
        return dict(self.exprs)

    current_expressions = saved_expressions

    def set_expression(self, name, expression):
        if expression in self.reject:
            raise RuntimeError("refused")
        if name in self.flaky:
            self.flaky.discard(name)
            raise RuntimeError("busy")
        self.exprs[name] = expression

    def recompute(self):
        self.recomputes += 1
        return True

    def read_value(self, name):
        number = float(re.match(r"\s*([-0-9.eE+]+)", self.exprs[name]).group(1))
        if "deg" in self.exprs[name]:
            return math.radians(number)
        return number / 10.0  # lengths are mm, stored as cm

    def error_items(self):
        return [self.bad_item] if self.bad_when(self.exprs) else []


class _Item:
    def __init__(self, **kw):
        self.__dict__.update(kw)


class _Param(_Item):
    """A user parameter whose value follows a plain "<number> mm" expression."""

    def __setattr__(self, key, val):
        object.__setattr__(self, key, val)
        if key == "expression":
            match = re.match(r"\s*([-0-9.eE+]+)\s*mm\s*$", val)
            if match:
                object.__setattr__(self, "value", float(match.group(1)) / 10.0)


class _Collection:
    def __init__(self, items):
        self._items = items
        self.count = len(items)

    def item(self, i):
        return self._items[i]

    def itemByName(self, name):
        return next(i for i in self._items if i.name == name)


class FakeDesign:
    def __init__(self, params, timeline=()):
        self._params = [_Param(**p) for p in params]
        self.userParameters = _Collection(self._params)
        self.timeline = _Collection([_Item(**t) for t in timeline])
        self.computed = 0

    def computeAll(self):
        self.computed += 1
        return True


class FakeEntity:
    def __init__(self, timeline, token):
        self._timeline = timeline
        self.entityToken = token

    def deleteMe(self):
        """Removes its item; the marker moves back by one when the item sat before it, like Fusion."""
        timeline = self._timeline
        index = next(n for n, i in enumerate(timeline.items) if i.entity is self)
        del timeline.items[index]
        if index < timeline.marker:
            timeline.marker -= 1
        return True


class FakeTimelineItem:
    def __init__(self, entity):
        self.entity = entity


class FakeTimeline:
    """Timeline of tokens. New items insert at the marker, like Fusion."""

    def __init__(self, tokens, marker=None):
        self.items = [FakeTimelineItem(FakeEntity(self, t)) for t in tokens]
        self.marker = len(self.items) if marker is None else marker

    @property
    def count(self):
        return len(self.items)

    @property
    def markerPosition(self):
        return self.marker

    @markerPosition.setter
    def markerPosition(self, value):
        self.marker = value

    def moveToEnd(self):
        self.marker = len(self.items)

    def item(self, i):
        return self.items[i]

    def insert_at_marker(self, token):
        entity = FakeEntity(self, token)
        self.items.insert(self.marker, FakeTimelineItem(entity))
        self.marker += 1
        return entity

    def tokens(self):
        return [i.entity.entityToken for i in self.items]


# Occurrences, proxies and bodies for the reader tests. Matrices are plain (origin, x, y, z) tuples in mm.

IDENTITY = ((0, 0, 0), (1, 0, 0), (0, 1, 0), (0, 0, 1))


def turn_z(deg, origin=(0, 0, 0)):
    c, s = math.cos(math.radians(deg)), math.sin(math.radians(deg))
    return (origin, (c, s, 0), (-s, c, 0), (0, 0, 1))


def turn_x(deg, origin=(0, 0, 0)):
    c, s = math.cos(math.radians(deg)), math.sin(math.radians(deg))
    return (origin, (1, 0, 0), (0, c, s), (0, -s, c))


def apply_matrix(m, p):
    o, x, y, z = m
    return tuple(o[i] + p[0] * x[i] + p[1] * y[i] + p[2] * z[i] for i in range(3))


def compose_matrices(outer, inner):
    """The matrix that applies `inner` first, then `outer`."""
    turn = lambda d: tuple(apply_matrix(outer, d)[i] - outer[0][i] for i in range(3))  # noqa: E731
    return (apply_matrix(outer, inner[0]), turn(inner[1]), turn(inner[2]), turn(inner[3]))


class Vec:
    def __init__(self, x, y, z):
        self.x, self.y, self.z = x, y, z


class FakeMatrix3D:
    """Matrix3D stand-in: getAsCoordinateSystem gives the origin in cm and the axes as they are."""

    def __init__(self, matrix):
        self.matrix = matrix

    def getAsCoordinateSystem(self):
        o, x, y, z = self.matrix
        return Vec(*(c / 10.0 for c in o)), Vec(*x), Vec(*y), Vec(*z)


class FakeOccurrence:
    """An occurrence. `native` is the native occurrence of a proxy; `parent` is its assemblyContext."""

    def __init__(self, name, transform2, parent=None, native=None, referenced=False, component=None):
        self.name = name
        self.transform2 = FakeMatrix3D(transform2) if transform2 is not None else None
        self.assemblyContext = parent
        self.nativeObject = native
        self.isReferencedComponent = referenced
        self.component = component

    @property
    def fullPathName(self):
        names, occurrence = [], self
        while occurrence is not None:
            names.append(occurrence.name)
            occurrence = occurrence.assemblyContext
        return "+".join(reversed(names))


class _Geo:
    def __init__(self, point_mm):
        self.geometry = Vec(*(c / 10.0 for c in point_mm))
        self.pointOnFace = self.geometry


class _List:
    def __init__(self, items):
        self._items = items
        self.count = len(items)

    def item(self, i):
        return self._items[i]


class FakeSolid:
    """A body with vertices and faces (points in mm), either native or the proxy of one."""

    def __init__(self, vertices=(), faces=(), context=None, native=None, component=None, token="b1", name="Body1"):
        self.vertices = _List([_Geo(p) for p in vertices])
        self.faces = _List([_Geo(p) for p in faces])
        self.assemblyContext = context
        self.nativeObject = native
        self.parentComponent = component
        self.entityToken = token
        self.name = name


class FakeCellBody:
    """A body made of named cells of one cm3 each, for boolean tests: a boolean is a set operation on the cells."""

    def __init__(self, cells):
        self.cells = set(cells)

    @property
    def volume(self):
        return float(len(self.cells))


class FakeBRepManager:
    """TemporaryBRepManager stand-in. `copy` leaves the original alone, like Fusion; `failing` makes every boolean
    report failure, `empty_fails` only an intersect that leaves nothing."""

    def __init__(self, failing=False, empty_fails=False):
        self.failing = failing
        self.empty_fails = empty_fails
        self.copies = 0

    def copy(self, body):
        self.copies += 1
        return FakeCellBody(body.cells)

    def booleanOperation(self, target, tool, kind):
        if self.failing or (self.empty_fails and kind == FakeBooleanTypes.IntersectionBooleanType
                            and not target.cells & tool.cells):
            return False
        target.cells = target.cells & tool.cells if kind == FakeBooleanTypes.IntersectionBooleanType \
            else target.cells | tool.cells
        return True


class FakeBooleanTypes:
    IntersectionBooleanType = "intersection"
    UnionBooleanType = "union"
    DifferenceBooleanType = "difference"


def fake_brep_tools(failing=False, empty_fails=False):
    """`(manager, types)` as `read_intersect._brep_tools` gives them."""
    return FakeBRepManager(failing, empty_fails), FakeBooleanTypes


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
        self.items.append(_Item(name=name, isSelected=selected))


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
        return _Item(entity=self.picked[index])


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


# Faces, edges, features and a timeline for the reach read (`lib/fusion_reader/read_gap_reach.py`).


class FakeFace:
    def __init__(self, token, body=None):
        self.entityToken = token
        self.body = body


class FakeEdge:
    def __init__(self, token, faces):
        self.entityToken = token
        self.faces = _Collection(list(faces))


class FakeMadeFeature:
    """A timeline feature with the faces it created. `faces=None` makes the member raise, like an unreadable one.
    `complete` is the list Fusion gives with the marker right after the feature, when later steps took faces out of
    `faces`."""

    def __init__(self, faces, complete=None):
        self._faces, self._complete = faces, complete
        self.timeline, self.place = None, None

    @property
    def faces(self):
        right_after = self.timeline is not None and self.timeline.markerPosition == self.place + 1
        found = self._complete if right_after and self._complete is not None else self._faces
        if found is None:
            raise RuntimeError("faces unreadable")
        return _Collection(list(found))


class FakeSolidBody:
    """A body whose component finds the faces whose point is the given one."""

    def __init__(self, token, faces_at):
        self.entityToken = token
        self.parentComponent = self
        self._faces_at = faces_at

    def findBRepUsingPoint(self, point, entity_type, *rest):
        return _Collection(list(self._faces_at.get(tuple(point), ())))


class FakeMarkerTimeline:
    """A timeline of features with a marker. `refuse` is a position whose assignment raises; `moves_allowed` ignores
    every assignment after that many, like a design that cannot be rolled back."""

    def __init__(self, features, marker=None, refuse=None, moves_allowed=None):
        self._features = features
        for place, feature in enumerate(features):
            if isinstance(feature, FakeMadeFeature):
                feature.timeline, feature.place = self, place
        self._marker = len(features) if marker is None else marker
        self._refuse, self._allowed, self._moves = refuse, moves_allowed, 0
        self.visited = []

    count = property(lambda self: len(self._features))

    @property
    def markerPosition(self):
        return self._marker

    @markerPosition.setter
    def markerPosition(self, value):
        if value == self._refuse:
            raise RuntimeError("marker refused")
        if self._allowed is not None and self._moves >= self._allowed:
            return
        self._moves += 1
        self._marker = value
        self.visited.append(value)

    def moveToEnd(self):
        if self._allowed is not None:
            return False
        self._marker = len(self._features)
        return True

    def item(self, i):
        return _Item(entity=self._features[i])


class FakeReachDesign:
    """A design that finds entities by token."""

    def __init__(self, timeline, entities=()):
        self.timeline = timeline
        self._entities = {e.entityToken: e for e in entities}

    def findEntityByToken(self, token):
        found = self._entities.get(token)
        return [found] if found is not None else []
