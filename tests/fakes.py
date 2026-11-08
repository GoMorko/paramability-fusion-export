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
