"""The values a sketch solution gives, put under the keys the motion file uses (`sketch_values.keys`). Pure.

The solver (`sketch_solve`) gives a formula for each point and radius of a sketch, by the ids of the sketch graph
record. A step reads a profile of that sketch, and the probe keys its numbers by the loops and curves of the profile
(`match`). This module links the two:

- a profile curve is found in the graph by its sketch entity token; its ends, centre and radius are the solver's
  values for that curve (`Drawing.draw`). A curve that is only a piece of a sketch curve (its ends are crossings with
  other curves) has no values of its own and is left open;
- the numbers of a profile at some size settings are made by building the profile again from those values and running
  it through `match.state_values`, as a profile read in Fusion would be. That keeps one place that decides what a key
  means;
- the formula of a key is fitted over the solver's values of its own curves (`fit_formulas`): a constant plus a sum of
  coefficients times point coordinates and radii. A key that is not such a sum (a width along a slanted line, the
  middle of an arc) has numbers but no formula. A loop is drawn from the solution only when all its curves are; a loop
  with an open curve keeps its captured numbers, and none of its keys have values.

A hole point or a revolve axis point is the solver's point put through the frame of its sketch (`Points`).
"""
import math
import re

from ..sketch_values import expr as ex
from ..sketch_values import keys as motion_keys
from . import match
from .fit import Column, fit_value

POSITION = 1e-4
EVAL_ERRORS = (ex.ExprDomainError, KeyError, ZeroDivisionError, OverflowError, ValueError)

# Why a key has no values of its own.
NOT_IN_SKETCH = "not_in_sketch"  # the profile curve or hole point is not an entity of the sketch graph
PIECE = "piece"  # the profile curve is only a part of a sketch curve
KIND = "kind"  # a curve that the solver does not work out
PLANE = "plane"  # the place of the sketch plane
NO_FRAME = "no_frame"  # the sketch frame was not read
NO_MATCH = "no_match"  # the outline built from the solution is not the captured one
LOOP = "loop"  # the curve is drawn, but another curve of its loop is open
UNREAD = "unread"

_LOOP = re.compile(r"/l(\d+)/")
_CURVE = re.compile(r"/c(\d+)\.(\d+)/")
_CURVES = ("line", "arc", "circle")


class Open(Exception):
    """A value that cannot be drawn: `code` (a solver code or one above) and the reason in words."""

    def __init__(self, code, reason=""):
        super().__init__(reason or code)
        self.code, self.reason = code, reason or code


def _near(p, q):
    return abs(p[0] - q[0]) <= POSITION and abs(p[1] - q[1]) <= POSITION


class Drawing:
    """A sketch graph record with its `Solution`: the formula of a point or radius, and the sketch's own curves and
    points found by token. A token that two entities share finds none."""

    def __init__(self, record, solution):
        self.solution = solution
        self.points = {p["id"]: p for p in record.get("points") or [] if isinstance(p, dict) and "id" in p}
        self._curves, self._point_tokens = {}, {}
        for table, source in ((self._curves, record.get("curves")), (self._point_tokens, record.get("points"))):
            found = {}
            for entity in source or []:
                if isinstance(entity, dict) and entity.get("token"):
                    found.setdefault(entity["token"], []).append(entity)
            table.update({t: e[0] for t, e in found.items() if len(e) == 1})

    def curve(self, token):
        return self._curves.get(token)

    def point_by_token(self, token):
        return self._point_tokens.get(token)

    def xy(self, pid):
        return tuple(self.points[pid]["xy"])

    def point(self, pid):
        """`(x, y)` `Expr` of a sketch point, or raises `Open` with the solver's reason."""
        pair = self.solution.points.get(pid)
        if pair is None:
            raise Open(UNREAD, self.solution.reason or "the solver has no value for a point")
        for value in pair:
            if not value.derived:
                raise Open(value.code, value.reason)
        return pair[0].expr, pair[1].expr

    def radius(self, cid):
        value = self.solution.radii.get(cid)
        if value is None:
            raise Open(UNREAD, self.solution.reason or "the solver has no value for a radius")
        if not value.derived:
            raise Open(value.code, value.reason)
        return value.expr

    def draw(self, curve):
        """The `Drawn` of one profile curve, or raises `Open`."""
        kind = curve.get("kind")
        found = self.curve(curve.get("entity"))
        if kind not in _CURVES:
            raise Open(KIND, "an outline curve of kind %s is not worked out" % kind)
        if found is None:
            raise Open(NOT_IN_SKETCH, "the outline curve is not a curve of the sketch")
        if found.get("kind") != kind:
            raise Open(KIND, "the outline curve and the sketch curve differ in kind")
        parts = {}
        if kind == "circle":
            self._centre(curve, found, parts)
            parts["radius"] = self.radius(found["id"])
            return Drawn(curve, parts)
        a, b = found["points"]
        if _near(curve["start"], self.xy(a)) and _near(curve["end"], self.xy(b)):
            first, second = a, b
        elif _near(curve["start"], self.xy(b)) and _near(curve["end"], self.xy(a)):
            first, second = b, a
        else:
            raise Open(PIECE, "the outline curve is a part of a longer sketch curve")
        parts["start"], parts["end"] = self.point(first), self.point(second)
        if kind == "arc":
            self._centre(curve, found, parts)
            parts["radius"] = self.radius(found["id"])
        return Drawn(curve, parts)

    def _centre(self, curve, found, parts):
        if not _near(curve["center"], self.xy(found["center"])):
            raise Open(PIECE, "the outline curve is a part of a longer sketch curve")
        parts["center"] = self.point(found["center"])


class Drawn:
    """A profile curve with the solver values that draw it: `parts` has `start`, `end`, `center` as `(x, y)` of
    `Expr`, and `radius`."""

    def __init__(self, curve, parts):
        self.curve, self.parts = curve, parts
        self.sense = 1.0
        if curve["kind"] == "arc":
            c, s, m = curve["center"], curve["start"], curve["mid"]
            cross = (s[0] - c[0]) * (m[1] - c[1]) - (s[1] - c[1]) * (m[0] - c[0])
            self.sense = 1.0 if cross >= 0 else -1.0

    def scalars(self):
        """`[(name, Expr)]` of every number the curve is drawn from."""
        out = []
        for field in ("start", "end", "center"):
            if field in self.parts:
                out += [(field + ".x", self.parts[field][0]), (field + ".y", self.parts[field][1])]
        if "radius" in self.parts:
            out.append(("radius", self.parts["radius"]))
        return out

    def at(self, env):
        """The profile curve with the numbers the solution gives over `env` (leaf name to number); raises one of
        `EVAL_ERRORS` when a value has no number there."""
        out = dict(self.curve)
        for field in ("start", "end", "center"):
            if field in self.parts:
                out[field] = [self.parts[field][0].value(env), self.parts[field][1].value(env)]
        if "radius" in self.parts:
            out["radius"] = self.parts["radius"].value(env)
        if self.curve["kind"] == "arc":
            out["mid"] = _arc_mid(out["center"], out["start"], out["end"], out["radius"], self.sense)
        return out


def _arc_mid(c, s, e, r, sense):
    """The point halfway along an arc from `s` to `e` that turns counter clockwise (`sense` 1) or clockwise."""
    a0, a1 = math.atan2(s[1] - c[1], s[0] - c[0]), math.atan2(e[1] - c[1], e[0] - c[0])
    sweep = (a1 - a0) % (2 * math.pi) if sense > 0 else -((a0 - a1) % (2 * math.pi))
    middle = a0 + sweep / 2.0
    return [c[0] + r * math.cos(middle), c[1] + r * math.sin(middle)]


class Profile:
    """The keys of one profile target (`plan.scan`): which curves of its loops the solver draws, the numbers at size
    settings, and fitted formulas."""

    def __init__(self, target, drawing):
        self.target = target
        self.loops, self.open = [], {}
        for k, loop in enumerate(target["profile"]["loops"]):
            row = []
            for j, curve in enumerate(loop.get("curves") or []):
                try:
                    row.append(drawing.draw(curve))
                except Open as found:
                    row.append(None)
                    self.open[(k, j)] = (found.code, found.reason)
            self.loops.append(row)

    def code_of(self, key):
        """`(code, reason)` when the key has no values of its own, else None."""
        if key.endswith("/plane"):
            return PLANE, "the sketch plane does not come from the dimensions"
        found = _CURVE.search(key)
        if found:
            k = int(found.group(1))
            return self.open.get((k, int(found.group(2)))) or self._loop_open(k, LOOP, "another curve of its loop is open")
        found = _LOOP.search(key)
        if found:
            return self._loop_open(int(found.group(1)))
        return None

    def _loop_open(self, k, code=None, reason=""):
        """The first open curve of loop `k` as `(code, reason)`, or `(code, reason)` given when only another curve of
        the loop is open; None when the loop is drawn whole."""
        found = next((v for (loop, _), v in sorted(self.open.items()) if loop == k), None)
        return (code, reason) if found is not None and code else found

    def direct(self, env):
        """The key numbers of the profile drawn from the solution over `env`, as `match.state_values` gives them for a
        read; None when a value has no number there or the outline is not the captured one."""
        try:
            loops = [{"outer": bool(src.get("outer")),
                      "curves": [d.at(env) for d in row] if None not in row else [dict(c) for c in src["curves"]]}
                     for row, src in zip(self.loops, self.target["profile"]["loops"])]
        except EVAL_ERRORS:
            return None
        read = {"sketches": {self.target["sketch_token"]: {"frame": self.target["profile"]["frame"],
                                                           "profiles": [{"loops": loops}]}}}
        return match.state_values(self.target, read)[0]

    def formulas(self, keys, envs):
        """`{ key: (Expr over leaf names or None, why not) }` fitted over the numbers at `envs` (index 0 the settings now).
        A key draws its formula from the values of its own loop, or of its own curve for a curve key."""
        directs = [self.direct(env) for env in envs]
        columns = {}
        for k, row in enumerate(self.loops):
            for j, drawn in enumerate(row):
                for name, expr in (drawn.scalars() if drawn is not None else ()):
                    columns["%d.%d.%s" % (k, j, name)] = ((k, j), expr)
        values = {}
        for name, (_, expr) in columns.items():
            found = []
            for env in envs:
                try:
                    found.append(expr.value(env))
                except EVAL_ERRORS:
                    found.append(0.0)
            values[name] = found
        exprs = {name: expr for name, (_, expr) in columns.items()}
        out = {}
        for key in keys:
            series = [d.get(key) if d is not None else None for d in directs]
            if any(v is None for v in series):
                out[key] = (None, "it has no number at some size settings")
                continue
            owner, loop = _CURVE.search(key), _LOOP.search(key)
            pool = [Column(name, 1, values[name]) for name, (at, _) in columns.items()
                    if (owner and at == (int(owner.group(1)), int(owner.group(2))))
                    or (not owner and loop and at[0] == int(loop.group(1)))]
            out[key] = _compose(fit_value(series, pool), exprs)
        return out


def _compose(result, exprs):
    if result.kind == "const":
        return ex.num(result.const), ""
    if result.kind == "affine":
        total = ex.num(result.const)
        for name, coefficient in result.terms.items():
            total = total + exprs[name].scaled(coefficient)
        return total, ""
    return None, "it is not a sum of the sketch's coordinates (%s)" % (result.cause or "curve")


class Points:
    """Hole points (`positions/<n>/<axis>`) and the start of a revolve axis line (`axis/point/<axis>`): world
    coordinates, so the solver's sketch point is put through the frame of its sketch (the first read's)."""

    def __init__(self, target, drawing, frame):
        self.target, self.frame = target, frame
        self.places = {}  # key -> (x Expr, y Expr) or an Open
        item = target["item"]
        if target["kind"] == "hole":
            entities = [drawing.point_by_token(t) for t in target["point_tokens"]]
            names = [(entity, lambda c, n=n: motion_keys.hole_point(item, n, c)) for n, entity in enumerate(entities)]
        else:
            line = drawing.curve(target["entity"])
            entity = drawing.points.get(line["points"][0]) if line and line.get("kind") == "line" else None
            names = [(entity, lambda c: motion_keys.axis_point(item, c))]
        for entity, key_of in names:
            try:
                if frame is None:
                    raise Open(NO_FRAME, "the sketch frame was not read")
                if entity is None:
                    raise Open(NOT_IN_SKETCH, "the point is not a point of the sketch")
                place = drawing.point(entity["id"])
            except Open as found:
                place = found
            for c in range(3):
                self.places[key_of(c)] = place

    def code_of(self, key):
        place = self.places.get(key)
        return (place.code, place.reason) if isinstance(place, Open) else None

    def _expr(self, key):
        c = int(key.rsplit("/", 1)[1])
        x, y = self.places[key]
        f = self.frame
        return ex.num(f["origin"][c]) + x.scaled(f["x"][c]) + y.scaled(f["y"][c])

    def direct(self, env):
        out = {}
        for key, place in self.places.items():
            if isinstance(place, Open):
                continue
            try:
                out[key] = self._expr(key).value(env)
            except EVAL_ERRORS:
                return None
        return out

    def formulas(self, keys, envs):
        return {k: (self._expr(k), "") for k in keys if isinstance(self.places.get(k), tuple)}


def derivation(target, drawing, frame):
    """The `Profile` or `Points` of a probe target."""
    if target["kind"] == "profile":
        return Profile(target, drawing)
    return Points(target, drawing, frame)
