"""Fake parameter store and fake Fusion design for tests."""
import math
import re


class FakeStore:
    """Parameter store holding expressions as text. Values are the leading number as Fusion stores it (mm to cm, deg to rad)."""

    def __init__(self, expressions, bad_when=None, reject=(), flaky=()):
        self.exprs = dict(expressions)
        self.bad_when = bad_when or (lambda exprs: False)
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
        return ["Fillet1"] if self.bad_when(self.exprs) else []


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
        self._timeline.items = [i for i in self._timeline.items if i.entity is not self]
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
