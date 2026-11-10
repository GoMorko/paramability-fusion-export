"""Fakes of the Fusion sketch API for the sketch graph reader. Lengths are given in mm and angles in degrees; the
fakes store Fusion's cm and radians. Two wrappers of one entity are equal (`key`) but carry different tokens, and a
collection hands out a new wrapper at every `item()`, like Fusion does. The entities a dimension or constraint
holds are wrappers with another token (`wrapper(retoken=True)`), so only identity can match them."""
import math

CM = 0.1


class Thing:
    """A Fusion object: members from keywords, `objectType` from the type name, equality by `key`."""

    def __init__(self, type_name=None, key=None, **members):
        if type_name:
            members["objectType"] = "adsk::fusion::%s" % type_name
        members.setdefault("entityToken", "tok_%s" % key)
        self.__dict__.update(members)
        self.key = key

    def __eq__(self, other):
        return self is other or (self.key is not None and isinstance(other, Thing) and other.key == self.key)

    def __hash__(self):
        return hash(self.key)

    def wrapper(self, retoken=False):
        """Another wrapper of the same entity; `retoken` gives it another token text too."""
        copy = type(self).__new__(type(self))
        copy.__dict__.update(self.__dict__)
        if retoken:
            copy.entityToken = self.entityToken + "'"
        return copy


class Raises:
    """A member whose read raises."""

    def __get__(self, obj, owner=None):
        raise RuntimeError("retired member")


def broken(thing, *names):
    """`thing` with the named members raising on read (they live on a subclass, as a property would)."""
    cls = type("Broken", (Thing,), {name: Raises() for name in names})
    clone = cls(key=thing.key)
    clone.__dict__.update({k: v for k, v in thing.__dict__.items() if k not in names})
    return clone


class Coll:
    def __init__(self, items=()):
        self._items = list(items)
        self.count = len(self._items)

    def item(self, i):
        item = self._items[i]
        return item.wrapper() if isinstance(item, Thing) else item


class Param:
    def __init__(self, name, expression, reads=()):
        self.name, self.expression = name, expression
        self.dependencyParameters = Coll([Param(r, "1 mm") for r in reads])


def xy(x, y):
    return Thing(x=x * CM, y=y * CM, z=0.0)


def point(key, x, y, **flags):
    members = dict(geometry=xy(x, y), isFixed=False, isFullyConstrained=True, isReference=False, isLinked=False)
    members.update(flags)
    return Thing("SketchPoint", key, **members)


def _curve(type_name, key, **members):
    base = dict(isConstruction=False, isFixed=False, isFullyConstrained=True, isReference=False, isLinked=False)
    base.update(members)
    return Thing(type_name, key, **base)


def line(key, start, end, **flags):
    return _curve("SketchLine", key, startSketchPoint=start, endSketchPoint=end, isCenterLine=False, **flags)


def arc(key, center, start, end, radius, **flags):
    return _curve("SketchArc", key, centerSketchPoint=center, startSketchPoint=start, endSketchPoint=end,
                  radius=radius * CM, **flags)


def circle(key, center, radius, **flags):
    return _curve("SketchCircle", key, centerSketchPoint=center, radius=radius * CM, **flags)


def dimension(type_name, key, value, parameter=None, driving=True, **members):
    """A dimension; `value` is in mm (or degrees for an angular one)."""
    angular = type_name == "SketchAngularDimension"
    members.setdefault("parameter", parameter)
    return Thing(type_name, key, value=math.radians(value) if angular else value * CM, isDriving=driving,
                 textPosition=xy(1.0, 2.0), **members)


def constraint(type_name, key, **members):
    return Thing(type_name, key, **members)


def sketch(points=(), curves=(), dimensions=(), constraints=(), origin=None, fully_constrained=True, **members):
    origin = origin or point("origin", 0, 0, isFixed=True)
    return Thing("Sketch", "sketch", name="Sketch1", originPoint=origin, isFullyConstrained=fully_constrained,
                 sketchPoints=Coll(points), sketchCurves=Coll(curves), sketchDimensions=Coll(dimensions),
                 geometricConstraints=Coll(constraints), **members)


def rectangle(width, height):
    """A rectangle from the origin: four lines on four shared points, horizontal and vertical constraints, a
    coincident corner on the origin, a width dimension (parameter `d1` reading `Width`) and a height dimension
    (`d2`, the plain number `height`)."""
    origin = point("origin", 0, 0, isFixed=True)
    p1, p2, p3 = point("p1", width, 0), point("p2", width, height), point("p3", 0, height)
    bottom, right, top, left = (line("l0", origin, p1), line("l1", p1, p2), line("l2", p2, p3), line("l3", p3, origin))
    wrap = lambda thing: thing.wrapper(retoken=True)  # noqa: E731
    cons = [constraint("HorizontalConstraint", "c0", line=wrap(bottom)),
            constraint("VerticalConstraint", "c1", line=wrap(right)),
            constraint("HorizontalConstraint", "c2", line=wrap(top)),
            constraint("VerticalConstraint", "c3", line=wrap(left)),
            constraint("CoincidentConstraint", "c4", point=wrap(origin), entity=wrap(bottom))]
    dims = [dimension("SketchLinearDimension", "d0", width, Param("d1", "Width", reads=["Width"]),
                      entityOne=wrap(origin), entityTwo=wrap(p1), orientation=1),
            dimension("SketchLinearDimension", "d1", height, Param("d2", "%g mm" % height),
                      entityOne=wrap(origin), entityTwo=wrap(p3), orientation=2)]
    return sketch([p1, p2, p3], [bottom, right, top, left], dims, cons, origin=origin)
