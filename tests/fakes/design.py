"""Fake Fusion objects for the reader tests: the design and its user parameters, timelines, occurrences and
matrices, solids and the B-rep tools, and the faces, edges and features of the reach read."""
import math
import re


class FakeItem:
    def __init__(self, **kw):
        self.__dict__.update(kw)


class FakeParam(FakeItem):
    """A user parameter whose value follows a plain "<number> mm" expression."""

    def __setattr__(self, key, val):
        object.__setattr__(self, key, val)
        if key == "expression":
            match = re.match(r"\s*([-0-9.eE+]+)\s*mm\s*$", val)
            if match:
                object.__setattr__(self, "value", float(match.group(1)) / 10.0)


class FakeCollection:
    def __init__(self, items):
        self._items = items
        self.count = len(items)

    def item(self, i):
        return self._items[i]

    def itemByName(self, name):
        return next(i for i in self._items if i.name == name)


class FakeDesign:
    def __init__(self, params, timeline=()):
        self._params = [FakeParam(**p) for p in params]
        self.userParameters = FakeCollection(self._params)
        self.timeline = FakeCollection([FakeItem(**t) for t in timeline])
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
    """`(manager, types)` as `read_intersect.brep_tools` gives them."""
    return FakeBRepManager(failing, empty_fails), FakeBooleanTypes


# Faces, edges, features and a timeline for the reach read (`lib/fusion_reader/read_gap_reach.py`).


class FakeFace:
    def __init__(self, token, body=None):
        self.entityToken = token
        self.body = body


class FakeEdge:
    def __init__(self, token, faces):
        self.entityToken = token
        self.faces = FakeCollection(list(faces))


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
        return FakeCollection(list(found))


class FakeSolidBody:
    """A body whose component finds the faces whose point is the given one."""

    def __init__(self, token, faces_at):
        self.entityToken = token
        self.parentComponent = self
        self._faces_at = faces_at

    def findBRepUsingPoint(self, point, entity_type, *rest):
        return FakeCollection(list(self._faces_at.get(tuple(point), ())))


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
        return FakeItem(entity=self._features[i])


class FakeReachDesign:
    """A design that finds entities by token."""

    def __init__(self, timeline, entities=()):
        self.timeline = timeline
        self._entities = {e.entityToken: e for e in entities}

    def findEntityByToken(self, token):
        found = self._entities.get(token)
        return [found] if found is not None else []
