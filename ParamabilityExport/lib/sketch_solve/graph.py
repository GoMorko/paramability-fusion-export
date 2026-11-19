"""One sketch graph record (`capture.sketch_graphs`, agent-docs/capture-format.md, "Sketch graphs") as plain Python objects,
with the solved geometry Fusion gave: point positions, line directions and radii in mm and degrees.

`load` refuses a record that cannot be used at all (an error, a cut, a broken list) with `GraphError`. Single
dimensions or constraints that cannot be read are kept and marked `readable = False`; the solver keeps their entities
open instead of ignoring them.
"""
import math

CURVE_KINDS = ("line", "arc", "circle", "curve", "ellipse", "elliptical_arc", "conic", "spline", "other")


class GraphError(ValueError):
    """The record cannot be solved at all; the text says why in plain words."""


class Point:
    def __init__(self, raw):
        self.id = raw["id"]
        xy = raw.get("xy")
        self.xy = (float(xy[0]), float(xy[1])) if _is_pair(xy) else None
        self.origin = raw.get("origin") is True
        self.fixed = raw.get("fixed") is True
        self.free = raw.get("free") is True
        self.reference = raw.get("reference") if isinstance(raw.get("reference"), dict) else None
        self.token = raw.get("token") or ""
        self.readable = self.xy is not None and not raw.get("unread")


class Curve:
    def __init__(self, raw):
        self.id = raw["id"]
        self.kind = raw.get("kind") or "other"
        self.points = tuple(raw.get("points") or ())
        self.center = raw.get("center")
        radius = raw.get("radius")
        self.radius = float(radius) if _is_number(radius) else None
        self.construction = raw.get("construction") is True
        self.fixed = raw.get("fixed") is True
        self.free = raw.get("free") is True
        self.reference = raw.get("reference") if isinstance(raw.get("reference"), dict) else None
        self.token = raw.get("token") or ""
        self.readable = not raw.get("unread") and self._complete()

    def _complete(self):
        if self.kind == "line":
            return len(self.points) == 2 and all(isinstance(p, int) for p in self.points)
        if self.kind == "arc":
            return (isinstance(self.center, int) and self.radius is not None and len(self.points) == 2
                    and all(isinstance(p, int) for p in self.points))
        if self.kind == "circle":
            return isinstance(self.center, int) and self.radius is not None
        return True

    @property
    def round(self):
        """True for an arc or a circle."""
        return self.kind in ("arc", "circle")

    def all_points(self):
        """Every point id the curve holds: its ends and, for an arc or circle, its centre."""
        out = list(self.points)
        if self.round and isinstance(self.center, int):
            out.append(self.center)
        return tuple(p for p in out if isinstance(p, int))


class Item:
    """A dimension or a constraint: its type, the entities it names (`on`, refs `("point" | "curve", id)` or None),
    and the raw record for the type's extra fields."""

    def __init__(self, raw, group):
        self.id = raw.get("id")
        self.group = group
        self.type = raw.get("type") or "other"
        self.name = raw.get("name") or ""
        self.raw = raw
        self.on = ()
        self.readable = True

    def label(self):
        """How a reason names it: `dimension 3 (linear)`, `constraint 5 (SmoothConstraint)`."""
        kind = self.name.split("::")[-1] if self.type == "other" and self.name else self.type
        return "%s %s (%s)" % (self.group, self.id, kind)


class Graph:
    """The record as objects. `points` and `curves` map id to `Point` and `Curve`; `dimensions` and `constraints` are
    lists of `Item`."""

    def __init__(self, record):
        self.sketch = record.get("sketch") or ""
        self.token = record.get("token") or ""
        self.fully_constrained = record.get("fully_constrained")
        self.origin = record.get("origin")
        self.points = {}
        self.curves = {}
        for raw in record.get("points") or []:
            if not isinstance(raw, dict) or not isinstance(raw.get("id"), int):
                raise GraphError("a point record has no id")
            self.points[raw["id"]] = Point(raw)
        for raw in record.get("curves") or []:
            if not isinstance(raw, dict) or not isinstance(raw.get("id"), int):
                raise GraphError("a curve record has no id")
            self.curves[raw["id"]] = Curve(raw)
        for curve in self.curves.values():
            if any(p not in self.points for p in curve.all_points()):
                curve.readable = False
        if isinstance(self.origin, int) and self.origin in self.points:
            self.points[self.origin].origin = True
        self.dimensions = [self._item(raw, "dimension") for raw in record.get("dimensions") or []]
        self.constraints = [self._item(raw, "constraint") for raw in record.get("constraints") or []]

    def _item(self, raw, group):
        if not isinstance(raw, dict):
            raise GraphError("a %s record is not readable" % group)
        item = Item(raw, group)
        refs = []
        for ref in raw.get("on") or []:
            refs.append(self._ref(ref))
        item.on = tuple(refs)
        if raw.get("unread") or raw.get("unknown") or any(r is None for r in refs):
            item.readable = False
        return item

    def _ref(self, ref):
        if not isinstance(ref, (list, tuple)) or len(ref) != 2:
            return None
        kind, at = ref
        if kind == "point" and at in self.points:
            return ("point", at)
        if kind in CURVE_KINDS and at in self.curves:
            return ("curve", at)
        return None

    # --- solved geometry -----------------------------------------------------------------------------------------

    def xy(self, pid):
        return self.points[pid].xy

    def is_line(self, ref):
        return ref is not None and ref[0] == "curve" and self.curves[ref[1]].kind == "line"

    def is_round(self, ref):
        return ref is not None and ref[0] == "curve" and self.curves[ref[1]].round

    def ends(self, cid):
        a, b = self.curves[cid].points
        return self.xy(a), self.xy(b)

    def direction(self, cid):
        """The unit vector from the start to the end of a line, or None when it has no length."""
        (ax, ay), (bx, by) = self.ends(cid)
        length = math.hypot(bx - ax, by - ay)
        if length < 1e-9:
            return None
        return ((bx - ax) / length, (by - ay) / length)

    def entities(self, ref):
        """The refs a ref stands for: a point, or a curve and every point it holds."""
        if ref is None:
            return ()
        if ref[0] == "point":
            return (ref,)
        return (ref,) + tuple(("point", p) for p in self.curves[ref[1]].all_points())


def load(record):
    """The `Graph` of a sketch graph record; raises `GraphError` when the record cannot be solved at all."""
    if not isinstance(record, dict):
        raise GraphError("the sketch record is missing")
    if record.get("error"):
        raise GraphError("the sketch could not be read: %s" % record["error"])
    if record.get("cut"):
        raise GraphError("the sketch is too large to read (%s)" % record["cut"])
    lists = [n for n in record.get("unread") or [] if n != "isFullyConstrained"]
    if lists:
        raise GraphError("part of the sketch could not be read (%s)" % ", ".join(map(str, lists)))
    return Graph(record)


def _is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _is_pair(value):
    return isinstance(value, (list, tuple)) and len(value) == 2 and all(_is_number(v) for v in value)
