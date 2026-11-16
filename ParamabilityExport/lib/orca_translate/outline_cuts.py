"""Outlines whose corners follow variables, built in Orca by plane cuts.

Orca binds variables to feature fields only: the entities of a drawn sketch keep their numbers, and a rebuild never
solves a sketch again. A plane Cut has a bound field, `cut_offset`, and a Transform has `xf_angle_deg`. So an outline
of straight lines whose corners are formulas of the sizes (`sketches.SketchFormulas`) can follow the variables when
it is built from cuts:

- each side is the line `n . p = offset`, with `n` the side's right normal (it points out of a counter clockwise
  outline) and `offset = n . corner` a formula of the sizes;
- a side whose direction does not change is a Cut with a fixed plane and a bound `cut_offset`;
- a side whose direction is a constant plus a formula (an angle size) is cut between two Transforms of the body about
  the sketch origin: the first turns the body back by the formula, so the side lies in a fixed direction, the Cut
  follows, the second turns the body forward again. Sides that turn by the same formula share one pair;
- an inward corner cannot be made by cuts of one body. The outline is a formula of the half-planes of its sides
  (`halfplanes`), each side once, "and" at convex corners and "or" at inward ones. An "and" node is a body cut by
  its sides; each "or" node below it is a tool body (through all, cut by the other side of its sides, with its own
  tools below) cut away from it. Differences only: a union of pieces leaves seams where Orca's face group rounds
  fail.

The bodies start as a square block on the sketch plane, much larger than the outline, extruded as the Fusion extrude
is. The finished block goes into the part as the extrude did (or is the part, for the first extrude). Its faces and
edges are those of the drawn outline, so rounds of a face group work on it as on a drawn one.

Orca builds whatever the cuts give: past some value of a variable the same cuts give another shape, without an error
(the outline crosses itself, a corner turns inward, the outline leaves the block, a choice of the sketch solver
flips). So the copy walks each variable the outline reads (the others kept) and finds where the formula stops giving
the outline (`Planned.fits`), and the parameter's line tells it. An outline whose limits cannot be found keeps its
drawn numbers.

Scope: one outer loop of straight lines without holes, of an extrude without taper, whose corners and side
directions the sketch solver gives. Anything else, and an outline that would take too many Orca features or tool
bodies nested too deep, keeps its drawn numbers.
"""
import math

from ..design_model.dimension_sizes import leaf_values, size_env
from ..geometry import vec
from ..orca_recipe.enums import BooleanMode, ExtrudeEnd, FeatureType, SketchShape
from ..orca_recipe.feature import CadFeature
from ..params.size_table import FREE
from ..sketch_values.expr import ExprDomainError, cos, num, sin
from . import halfplanes, limits
from ..design_model.values import Quantity
from .context import Body
from .formulas import OrcaFormulaError
from .sketches import reads_input

# Corners of the drawn outline and of the formulas agree within this (mm), and a side shorter than `_SHORTEST` (mm)
# at a variable's value ends the outline's range.
_CORNER_TOL = 1e-5
_SHORTEST = 1e-4
# A side's direction formula agrees with its corners within this share of its length.
_DIRECTION_TOL = 1e-6
# The block is a square around the outline, at least `_BLOCK_MIN` (mm) from its centre to a side, and at least
# `_BLOCK_GROW` times the outline's size. Its corners must stay `_BLOCK_MARGIN` of that inside it.
_BLOCK_MIN = 1000.0
_BLOCK_GROW = 20.0
_BLOCK_MARGIN = 0.05
# At most this many Orca features for one outline, and tool bodies nested this deep.
MAX_FEATURES = 60
MAX_DEPTH = 4
_MATH_ERRORS = (ExprDomainError, ZeroDivisionError, OverflowError, ValueError, KeyError)


class Side:
    """One side of the outline, from corner `index` to the next: `angle` the constant part of its direction (degrees),
    `turn` the part that follows variables (an `Expr` over size names, or None for a fixed direction), `offset` the
    formula of `n . corner`."""

    def __init__(self, index, direction, start):
        self.index = index
        self.direction = direction
        self.angle = direction.const % 360.0
        rest = direction - num(direction.const)
        self.turn = None if rest.is_constant else rest
        normal = (sin(direction), -cos(direction))
        self.offset = normal[0] * start[0] + normal[1] * start[1]


class Planned:
    """An outline the copy builds from cuts: its corners (formulas over size names, counter clockwise), sides, the
    half-plane formula (`tree`), the block around it and the limits of the variables it reads.

    `shape`, `bound`, `notes` and `moves` answer as a `sketches.SketchOut` does, for `sketch_sizes.sketch_doubts`: `bound`
    holds each formula with the Fusion names it reads."""

    def __init__(self, formulas, corners, sides, tree, now):
        self.formulas = formulas
        self.corners, self.sides, self.tree = corners, sides, tree
        xs, ys = [p[0] for p in now], [p[1] for p in now]
        self.centre = ((min(xs) + max(xs)) / 2.0, (min(ys) + max(ys)) / 2.0)
        size = max(max(xs) - min(xs), max(ys) - min(ys))
        self.half = max(_BLOCK_MIN, _BLOCK_GROW * size)
        self.shape, self.notes, self.moves, self.feature = "cuts", [], (), None
        self.bound = {}
        self.found = {}  # Orca variable -> (low, high)
        self._leaves = {n: leaf.value for n, leaf in formulas.solution.leaves.items()}
        self._guards = [a.guard for a in formulas.solution.assumptions if not a.guard.is_constant]

    def points(self, env):
        return [(x.value(env), y.value(env)) for x, y in self.corners]

    def fits(self, env):
        """True when the cuts give the outline at the size values `env`: the corners make a simple counter clockwise
        loop inside the block, every side runs along its direction formula, the sketch solver's choices hold and the
        half-plane formula gives the loop in every cell (`halfplanes.check`)."""
        try:
            pts = self.points(env)
            leaves = dict(self._leaves, **leaf_values(self.formulas.formulas, env))
            if any(guard.value(leaves) <= 0 for guard in self._guards):
                return False
            turns = [math.radians(side.direction.value(env)) for side in self.sides]
        except _MATH_ERRORS:
            return False
        if not halfplanes.simple(pts, _SHORTEST) or halfplanes.area(pts) <= 0:
            return False
        reach = self.half * (1.0 - _BLOCK_MARGIN)
        if any(abs(p[0] - self.centre[0]) > reach or abs(p[1] - self.centre[1]) > reach for p in pts):
            return False
        n = len(pts)
        for i, phi in enumerate(turns):
            a, b = pts[i], pts[(i + 1) % n]
            d = (b[0] - a[0], b[1] - a[1])
            length = math.hypot(*d)
            if d[0] * math.cos(phi) + d[1] * math.sin(phi) <= 0 or \
                    abs(d[0] * math.sin(phi) - d[1] * math.cos(phi)) > _DIRECTION_TOL * length:
                return False
        return halfplanes.check(pts, self.tree)

    def count(self):
        """The Orca features the outline takes in the part: the block's sketch and extrude, its cuts, turns and tool
        bodies, and the Boolean into the part."""
        return 3 + _count(self, self.tree)


def _count(planned, node):
    lits = [planned.sides[k[1]] for k in node[1] if k[0] == "lit"]
    turns = {side.turn.key() for side in lits if side.turn is not None}
    total = len(lits) + 2 * len(turns)
    for kid in node[1]:
        if kid[0] != "lit":
            total += 2 + _count(planned, kid)
    return total


# ---- the plan ----------------------------------------------------------------------------------------------------

def _same(a, b, tol=_CORNER_TOL * 10):
    return abs(a[0] - b[0]) <= tol and abs(a[1] - b[1]) <= tol


def corner_order(curves):
    """The corners of a loop of lines in loop order (each line's start once), or None when they do not close."""
    if not curves or any(c.get("kind") != "line" for c in curves):
        return None
    ends = [(tuple(c["start"]), tuple(c["end"])) for c in curves]
    order = [ends[0][0], ends[0][1]]
    rest = ends[1:]
    while rest:
        for k, (s, e) in enumerate(rest):
            if _same(s, order[-1]):
                order.append(e)
                break
            if _same(e, order[-1]):
                order.append(s)
                break
        else:
            return None
        rest.pop(k)
    if not _same(order[0], order[-1]):
        return None
    return order[:-1]


def plan(ctx, outline, formulas):
    """The `Planned` cuts of an outline, None when its sketch has no formulas or nothing of the outline follows a
    size (it is drawn as it is), or the reason (a plain phrase) why it keeps its numbers. The reason counts only
    when sizes move the outline (`sketch_sizes.sketch_doubts`)."""
    if formulas is None or ctx.table is None:
        return None
    if outline.holes:
        return "the copy builds an outline from cuts only when it has no holes inside"
    order = corner_order(outline.outer)
    if order is None or len(order) < 3:
        return "the copy builds an outline from cuts only when it is one closed loop of straight lines"
    corners = []
    for xy in order:
        found = formulas.point(xy)
        if found is not None and any(reads_input(e) for e in found):
            return _projected(formulas)
        over = [formulas.over_sizes(e) for e in found] if found is not None else [None]
        if None in over:
            return formulas.why or "its dimensions do not set all its corners"
        corners.append(tuple(over))
    if all(x.is_constant and y.is_constant for x, y in corners):
        return None
    env = size_env(ctx.table, {})
    try:
        now = [(x.value(env), y.value(env)) for x, y in corners]
    except _MATH_ERRORS:
        return "its corners cannot be worked out from its dimensions"
    if any(not _same(p, q, _CORNER_TOL) for p, q in zip(now, order)):
        return "its dimensions do not give the corners where they are drawn"
    if not halfplanes.simple(now, _SHORTEST):
        return "its corners do not make a plain closed outline (two corners meet, or sides cross)"
    if halfplanes.area(now) < 0:
        order, corners, now = order[::-1], corners[::-1], now[::-1]
    sides = []
    n = len(order)
    for i in range(n):
        leaf = formulas.line_angle(order[i], order[(i + 1) % n])
        if leaf is not None and reads_input(leaf):
            return _projected(formulas)
        direction = formulas.over_sizes(leaf) if leaf is not None else None
        if direction is None:
            direction = _fixed_direction(corners[i], corners[(i + 1) % n])
        if direction is None:
            return formulas.why or "a side turns in a way Orca cannot follow"
        sides.append(Side(i, direction, corners[i]))
    tree = halfplanes.formula(now)
    if tree is None or not halfplanes.check(now, tree):
        return "the copy cannot build this shape from straight cuts"
    planned = Planned(formulas, corners, sides, tree, now)
    if not planned.fits(env):
        return "its dimensions do not give the outline as drawn"
    if halfplanes.depth(tree) > MAX_DEPTH or planned.count() > MAX_FEATURES:
        return "building it from cuts would take too many Orca steps"
    problem = _bindable(ctx, planned, env)
    if problem:
        return problem
    return _limits(ctx, planned)


def _projected(formulas):
    """Why an outline placed by geometry projected into its sketch keeps its numbers."""
    return "its corners follow geometry projected into %s, which the copy cannot follow" % (
        formulas.record.get("sketch") or "its sketch")


def _fixed_direction(a, b):
    """The direction (degrees) from corner `a` to corner `b` when both gaps between them are numbers, else None."""
    dx, dy = b[0] - a[0], b[1] - a[1]
    if not (dx.is_constant and dy.is_constant) or math.hypot(dx.const, dy.const) <= _SHORTEST:
        return None
    return num(math.degrees(math.atan2(dy.const, dx.const)))


def _bindable(ctx, planned, env):
    """None when Orca can hold every formula of the cuts and turns, else why not. Fills `planned.bound`."""
    exprs = [("side %d" % (s.index + 1), s.offset) for s in planned.sides]
    exprs += [("turn %d" % (s.index + 1), s.turn) for s in planned.sides if s.turn is not None]
    for label, expr in exprs:
        if expr.is_constant:
            continue
        try:
            ctx.orca_formula(expr.text())
            expr.value(env)
        except OrcaFormulaError as exc:
            return "Orca cannot write the formula of one of its sides: %s" % str(exc).rstrip(".")
        except _MATH_ERRORS:
            return "the formula of one of its sides cannot be worked out"
        planned.bound[label] = (expr.text(), planned.formulas.free_reads(expr))
    return None


def _limits(ctx, planned):
    """Walk each free size the outline reads (the others kept) to where the cuts stop giving the outline, and keep
    what is found by Orca variable. The planned outline, or why its limits cannot be told."""
    reads = {name for _, names in planned.bound.values() for name in names}
    for entry in ctx.table.entries:
        if entry.state != FREE or entry.name not in reads:
            continue

        def fits(value, entry=entry):
            return planned.fits(size_env(ctx.table, {entry.name: value}))

        if not fits(entry.value):
            return "the copy cannot tell how far %s may change" % entry.name
        low, high = limits.bounds(fits, entry.value)
        if low is not None or high is not None:
            planned.found[ctx.names[entry.size_name]] = (low, high)
    return planned


# ---- writing -----------------------------------------------------------------------------------------------------

class Built:
    """An outline written from cuts by one step: what `again` needs to write it once more into another body (a
    pattern's tool), its `mode` into the body it went into, and the `features` it wrote. `marks` gives, for each
    node of the half-plane formula (labelled as `_Writer` labels its bodies), the last feature that built the node's
    body and the body's index in Orca's list then, where corner tools (`corner_hosts`) are cut from it; `told` the
    limits told for the outline (`{Orca variable: limits.Limit}`)."""

    def __init__(self, planned, frame, side, name, mode, features, marks=None):
        self.planned, self.frame, self.side, self.name = planned, frame, side, name
        self.mode, self.features = mode, features
        self.marks = dict(marks or {})
        self.told = {}


def _feature(kind, name, **values):
    return CadFeature(type=kind, name=name, thread_major_nominal=True, pattern_inclusive=True, **values)


def write(ctx, planned, frame, side, mode, name, index):
    """Write the outline into the body being built: the block (the body itself when it has none yet), its cuts and
    tools, and the Boolean of `mode` into the body. Binds every formula, tells the limits found, and keeps a `Built`
    record for the step at timeline `index`. Returns `(features, block sketch, block extrude)`."""
    writer = _Writer(ctx, planned, frame, name, lambda f, field, value, where, at: ctx.bind(f, field, value, where))
    made = writer.run(side, mode)
    built = Built(planned, frame, side, name, BooleanMode.NEW if made[3] else mode, made[0], writer.marks)
    ctx.cut_built.setdefault(index, []).append(built)

    def put_back():
        kept = ctx.cut_built.get(index) or []
        if built in kept:
            kept.remove(built)

    ctx.undo.append(put_back)
    built.told = limits.tell_found(ctx, planned.found)[0]
    return made[:3]


def again(ctx, built, name, corners=None):
    """Write a `Built` outline once more into the body being built (a tool body), adding to it, with the same
    formulas. `corners` (`{node label: [write(writer)]}`) write corner tools at the end of their node's body.
    Returns the features of the outline."""
    writer = _Writer(ctx, built.planned, built.frame, "%s: %s" % (name, built.name), _Again(ctx, built.features),
                     corners)
    return writer.run(built.side, BooleanMode.ADD)[0]


class _Again:
    """Gives a field the number and formula the same feature had the first time (the writer writes the features in
    the same order), without new lines for the parameters."""

    def __init__(self, ctx, features):
        self.ctx, self.features = ctx, features

    def __call__(self, feature, field, value, where, at):
        source = self.features[at]
        setattr(feature, field, getattr(source, field))
        text = source.expr.get(field)
        if text is None:
            return
        feature.bind(field, text)
        for entry in self.ctx.bound:
            if entry["feature"] == source.name and entry["field"] == field:
                self.ctx.bound.append(dict(entry, feature=feature.name))
                break


class _Writer:
    def __init__(self, ctx, planned, frame, name, bind, corners=None):
        self.ctx, self.planned, self.name, self.bind = ctx, planned, name, bind
        self.corners = corners or {}
        self.marks = {}
        self.origin = [float(c) for c in frame["origin"]]
        self.x, self.y = vec.unit(list(frame["x"])), vec.unit(list(frame["y"]))
        self.z = list(frame["z"])
        self.axis = vec.unit(vec.cross(self.x, self.y))
        self.env = size_env(ctx.table, {})
        self.where = "%s outline" % name
        self.features = []
        self.sketch_at = None

    def _bind(self, feature, field, value, where):
        """Bind a field of the feature that is written next."""
        self.bind(feature, field, value, where, len(self.features))

    def _add(self, feature):
        at = self.ctx.add(feature)
        self.features.append(feature)
        return at

    def _value(self, expr):
        if expr.is_constant:
            return Quantity(expr.const)
        return Quantity(expr.value(self.env), expr.text(), self.planned.formulas.free_reads(expr))

    def run(self, side, mode):
        """`(features, block sketch, block extrude, whether the block is the body itself)`."""
        ctx, planned = self.ctx, self.planned
        cx, cy = planned.centre
        centre = vec.add(self.origin, vec.add(vec.scale(self.x, cx), vec.scale(self.y, cy)))
        sketch = _feature(FeatureType.SKETCH, "%s sketch" % self.name, shape=SketchShape.RECTANGLE,
                          plane=ctx.place.plane(centre, self.x, self.y, self.z), width=2.0 * planned.half,
                          height=2.0 * planned.half)
        self.sketch_at = self._add(sketch)
        first = not ctx.has_body
        if not first:
            block_body = ctx.push(Body(None, "%s block" % self.name))
        block = _feature(FeatureType.EXTRUDE, self.name, sketch_ref=self.sketch_at, extrude_end=side.end,
                         flip=side.flip, mode=BooleanMode.NEW, symmetric=side.end == ExtrudeEnd.SYMMETRIC)
        if side.distance is not None:
            self._bind(block, "distance", side.distance, "%s distance" % self.name)
        if side.distance2 is not None:
            self._bind(block, "distance2", side.distance2, "%s second side" % self.name)
        self._add(block)
        ctx.has_body = True
        self._node(planned.tree, True, "")
        if not first:
            ctx.pop()
            self._boolean(block_body, mode, "%s into the part" % self.name)
        return self.features, sketch, block, first

    def _boolean(self, tool, mode, name):
        made = _feature(FeatureType.BOOLEAN, name, mode=mode, target_body=self.ctx.scope.index,
                        bool_tool_body=tool.index, bool_keep_tool=False)
        self._add(made)
        self.ctx.consume(tool)

    def _node(self, node, inside, label):
        """Cut the body being built by the sides of `node` (keeping their inside, or for a tool their outside), then
        cut away a tool body for each node below it. Then mark where the node's body is done (`marks`) and write the
        corner tools cut from it (`corners`)."""
        lits = [self.planned.sides[k[1]] for k in node[1] if k[0] == "lit"]
        for side in lits:
            if side.turn is None:
                self._cut(side, inside)
        groups = {}
        for side in lits:
            if side.turn is not None:
                groups.setdefault(side.turn.key(), (side.turn, []))[1].append(side)
        for n, (turn, members) in enumerate(groups.values()):
            self._turn(-turn, "%s turn %s%d" % (self.name, label, n + 1))
            for side in members:
                self._cut(side, inside)
            self._turn(turn, "%s turn back %s%d" % (self.name, label, n + 1))
        tools = [k for k in node[1] if k[0] != "lit"]
        for n, kid in enumerate(tools):
            path = "%s%d" % (label, n + 1)
            tool = self.ctx.push(Body(None, "%s tool %s" % (self.name, path)))
            self._add(_feature(FeatureType.EXTRUDE, "%s tool %s" % (self.name, path), sketch_ref=self.sketch_at,
                               extrude_end=ExtrudeEnd.THROUGH_ALL, mode=BooleanMode.NEW))
            self.ctx.has_body = True
            self._node(kid, not inside, path + ".")
            self.ctx.pop()
            self._boolean(tool, BooleanMode.CUT, "%s tool %s cut" % (self.name, path))
        self.marks[label] = (self.features[-1], self.ctx.scope.index)
        for write in self.corners.get(label, ()):
            write(self)

    def _cut(self, side, inside):
        """A Cut along the side in its fixed direction (after any turn), keeping its inside or its outside. The
        side's right normal points out of the outline, so the inside is below the plane."""
        c = math.radians(side.angle)
        normal = vec.add(vec.scale(self.x, math.sin(c)), vec.scale(self.y, -math.cos(c)))
        along = vec.add(vec.scale(self.x, math.cos(c)), vec.scale(self.y, math.sin(c)))
        plane = self.ctx.place.plane(self.origin, along, vec.cross(normal, along), normal)
        made = _feature(FeatureType.CUT, "%s side %d" % (self.name, side.index + 1), plane=plane,
                        cut_keep_upper=not inside, cut_keep_lower=inside)
        self._bind(made, "cut_offset", self._value(side.offset), self.where)
        self._add(made)

    def _turn(self, angle, name):
        """A Transform of the body about the sketch origin by `angle` (an `Expr`, degrees, counter clockwise in the
        sketch)."""
        made = _feature(FeatureType.TRANSFORM, name, xf_axis=tuple(self.ctx.place.direction(self.axis)),
                        xf_pivot=tuple(self.ctx.place.point(self.origin)))
        self._bind(made, "xf_angle_deg", self._value(angle), self.where)
        self._add(made)
