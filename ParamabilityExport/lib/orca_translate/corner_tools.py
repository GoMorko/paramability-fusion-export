"""Rounds and chamfers of side edges on an outline whose corners follow variables, as corner tools: the formulas,
the checks and the limits.

An outline built from plane cuts (`outline_cuts`), or a rectangle whose width and height follow variables, cannot
be drawn again with arcs: a drawn outline keeps its numbers. So a round of a side edge is made by a tool body cut
from the body that holds the outline, before that body goes into the part (`corner_hosts` writes it):

- a round: the tool is the region between the corner and the arc, bounded by the two side lines (each moved `DELTA`
  away from the arc centre) and by the two lines through the arc centre square to each side, less a cylinder at the
  arc centre (an Orca Hole through all). The arc centre lies at the round's size `r` from both sides;
- an even chamfer: the triangle between the corner and the line through the two chamfer points, bounded by the two
  side lines moved `DELTA` away as above.

Each line is a plane Cut with a bound `cut_offset` that keeps one side, between two Transforms when its direction
turns with an angle formula, as for the sides of the outline. The tool is cut from the body of the node of the
outline's half-plane formula (`halfplanes`) where the corner's two sides meet: at a convex corner that body holds the
material of the corner, so the round takes it; at an inward corner it is a tool body that `outline_cuts` cuts away
from the outline, holding the empty corner, so the round leaves that much more material. Both sides of every line
follow the same formulas as the outline, so the corner follows every variable the outline follows, and a round whose
size follows a parameter follows it too.

That is right only while the formulas still describe the corner (`Spec`, `holds`): the corner keeps its kind (convex
or inward), the rounds and chamfers of each side fit on it, and inside each tool the node's body is the corner of the
two sides only (checked in every cell of the lines of the outline and of the tool). `walk` finds how far each variable
may go while that holds, and the outline's own check (`outline_cuts.Planned.fits`) holds too.

Pure numbers and formulas: no features are written here.
"""
import math

from ..design_model.dimension_sizes import size_env
from ..params.expressions.errors import ExpressionError
from ..params.expressions.evaluation import evaluate
from ..params.size_table import FREE
from ..sketch_values.expr import ExprDomainError, cos, name, num, sin, tan
from . import halfplanes, limits
from ..design_model.values import Quantity

# How far (mm) a tool reaches past each side of the corner, so that its faces never lie on the faces of the body.
DELTA = 0.05
# A corner turns by at least this (degrees) and less than 180 less this; a round or chamfer is larger than this (mm),
# so a size that follows a variable is told a lower limit over it (an Orca Hole of no size stops the rebuild).
_TURN_MIN = 1e-3
SIZE_MIN = 0.01
# What the corners take from a side may pass its length by this much (mm): a side taken whole is gone.
_GONE = 1e-6
# A sample point lies this far (mm) inside a tool to count, and a line crosses a tool when its corners lie this far
# (mm) on both sides of it.
_INSIDE = 1e-9
# The formulas of a corner give the corner the copy measured within this (mm).
_SAME = 1e-5
_MATH_ERRORS = (ExprDomainError, ExpressionError, ZeroDivisionError, OverflowError, ValueError, KeyError)


class Spec:
    """One corner tool on a planned outline (`outline_cuts.Planned`): corner `k` (where side `k - 1` ends and side
    `k` starts), a round or an even chamfer (`chamfer`) of `size` (a `Quantity` over size names), `square` when
    the chamfer is set by a distance and 45 degrees and so needs a square corner, the timeline index `step` of the step
    that made it, and the `label` of the node of the half-plane formula whose body it is cut from. `settle` gives it
    the corner's kind `sign` (1 convex, -1 pointing into the outline); `number` makes the name of its size unique."""

    def __init__(self, planned, k, chamfer, size, step, label, number, square=False):
        n = len(planned.corners)
        self.k, self.chamfer, self.size = k, chamfer, size
        self.sign = 1
        self.step, self.label, self.square = step, label, square
        self.side_a, self.side_b = planned.sides[(k - 1) % n], planned.sides[k]
        self.corner = planned.corners[k]
        # A size that follows sizes enters the formulas as a name of its own, written as its formula.
        self.placeholder = "corner_size_%d_" % number if size.text is not None else None
        self.r = name(self.placeholder) if self.placeholder else num(size.n)
        self.phi_a = self.side_a.direction
        self.phi_b = self.side_b.direction
        self.tau = None
        self._cuts = self._chord = None

    def settle(self, env):
        """Fix the branch of the turn at the corner so that it lies between -180 and 180 degrees at `env`, and the
        corner's kind from it: a counter clockwise outline turns left at a convex corner."""
        now = self.phi_b.value(env) - self.phi_a.value(env)
        self.phi_b = self.phi_b - num(360.0 * round(now / 360.0))
        self.tau = self.phi_b - self.phi_a
        self.sign = 1 if self.tau.value(env) > 0 else -1
        self._cuts = self._chord = None

    # ---- the formulas ------------------------------------------------------------------------------------------

    def reach(self):
        """How far along each side from the corner the round or chamfer reaches."""
        if self.chamfer:
            return self.r
        return self.r * tan(self.tau * 0.5) * float(self.sign)

    def cuts(self):
        """The half-planes of the tool, each `(angle, offset, what)`: it keeps the points `p` with `n . p <= offset`,
        `n` the unit vector at `angle` (degrees). `what` names the line."""
        if self._cuts is None:
            self._cuts = self._made_cuts()
        return list(self._cuts)

    def _made_cuts(self):
        s = float(self.sign)
        px, py = self.corner
        reach = self.reach()

        def dot(angle):
            return cos(angle) * px + sin(angle) * py

        out = [(self.phi_a - num(90.0 * s), self.side_a.offset * s + num(DELTA), "side before"),
               (self.phi_b - num(90.0 * s), self.side_b.offset * s + num(DELTA), "side after")]
        if self.chamfer:
            out.append(self.chord() + ("chamfer line",))
            return out
        back = self.phi_a + num(180.0)
        out.insert(1, (back, dot(back) + reach, "end before"))
        out.append((self.phi_b, dot(self.phi_b) + reach, "end after"))
        return out

    def chord(self):
        """`(angle, offset)` of the half-plane on the corner's side of the line through the two points where the
        round or chamfer meets the sides."""
        if self._chord is None:
            self._chord = self._made_chord()
        return self._chord

    def _made_chord(self):
        s = float(self.sign)
        px, py = self.corner
        angle = self.phi_a + self.tau * 0.5 + num(90.0 * s)
        return angle, cos(angle) * px + sin(angle) * py + self.reach() * sin(self.tau * 0.5) * s

    def region(self):
        """The half-planes of the part of the tool a round or chamfer changes: the whole tool of a chamfer; for a
        round, the tool less the part beyond the chord, which lies inside the cylinder the Hole removes."""
        out = [(angle, offset) for angle, offset, _ in self.cuts()]
        return out if self.chamfer else out + [self.chord()]

    def centre(self):
        """The arc centre (x, y) of a round."""
        s = float(self.sign)
        px, py = self.corner
        reach = self.reach()
        return (px - reach * cos(self.phi_a) - self.r * sin(self.phi_a) * s,
                py - reach * sin(self.phi_a) + self.r * cos(self.phi_a) * s)

    def env(self, env):
        """`env` with the size's own name, when it has one."""
        if self.placeholder is None:
            return env
        return dict(env, **{self.placeholder: evaluate(self.size.text, env)})

    def value(self, expr, formulas, env):
        """The `Quantity` of a formula of this corner at the sizes now (`env`): its number, and its formula and
        the Fusion names it reads when sizes move it."""
        number = expr.value(self.env(env))
        if expr.is_constant:
            return Quantity(number)
        names = [n for n in expr.names() if n != self.placeholder]
        reads = list(formulas.free_reads(_names_only(names)))
        if self.placeholder in expr.names():
            reads += [n for n in self.size.reads if n not in reads]
        if not reads:
            return Quantity(number)
        text = expr.text(lambda n: self.size.text if n == self.placeholder else n)
        return Quantity(number, text, reads)


def _names_only(names):
    """A formula that reads exactly `names`, to ask which free sizes they are."""
    total = num(0.0)
    for n in names:
        total = total + name(n)
    return total


def turn_of(angle):
    """`(constant degrees, turn)` of an angle formula: the turn is the part that follows sizes (an `Expr`), or None."""
    rest = angle - num(angle.const)
    return angle.const, (None if rest.is_constant else rest)


# ---- the node of the half-plane formula ------------------------------------------------------------------------

def nodes(tree):
    """`{label: node}` of every node, labelled as `outline_cuts` labels the bodies it writes: "" for the top node,
    then "1.", "1.2." and so on for the tool bodies below it."""
    out = {}

    def visit(node, label):
        out[label] = node
        kids = [k for k in node[1] if k[0] != "lit"]
        for n, kid in enumerate(kids):
            visit(kid, "%s%d." % (label, n + 1))

    visit(tree, "")
    return out


def _lits(node):
    if node[0] == "lit":
        return {node[1]}
    out = set()
    for kid in node[1]:
        out |= _lits(kid)
    return out


def meeting(tree, a, b):
    """The label of the lowest node whose formula holds the sides `a` and `b`."""
    found = ""
    for label, node in nodes(tree).items():
        if {a, b} <= _lits(node) and len(label) >= len(found):
            found = label
    return found


def _holds(node, inside, forced, value):
    """`halfplanes.holds` with the node `forced` taken as `value`."""
    if node is forced:
        return value
    if node[0] == "lit":
        return inside[node[1]]
    if node[0] == "and":
        for kid in node[1]:
            if not _holds(kid, inside, forced, value):
                return False
        return True
    for kid in node[1]:
        if _holds(kid, inside, forced, value):
            return True
    return False


# ---- the checks ------------------------------------------------------------------------------------------------

def _lines_at(cuts, env):
    """The half-planes `cuts` ((angle, offset) formulas) at `env`, each `(unit normal, offset)`."""
    out = []
    for angle, offset in cuts:
        a = math.radians(angle.value(env))
        out.append(((math.cos(a), math.sin(a)), offset.value(env)))
    return out


def _corners_of(cuts):
    """The corners of the convex region the half-planes `cuts` keep, or None when it has fewer than three."""
    out = []
    for i in range(len(cuts)):
        for j in range(i + 1, len(cuts)):
            (n1, k1), (n2, k2) = cuts[i], cuts[j]
            den = n1[0] * n2[1] - n1[1] * n2[0]
            if abs(den) < 1e-12:
                continue
            p = ((k1 * n2[1] - k2 * n1[1]) / den, (n1[0] * k2 - n2[0] * k1) / den)
            if all(n[0] * p[0] + n[1] * p[1] <= k + 1e-7 * (1.0 + abs(k)) for n, k in cuts):
                out.append(p)
    return out if len(out) >= 3 else None


def _side_lines(points):
    n = len(points)
    out = []
    for i in range(n):
        a, b = points[i], points[(i + 1) % n]
        length = math.hypot(b[0] - a[0], b[1] - a[1])
        out.append((a, ((b[0] - a[0]) / length, (b[1] - a[1]) / length)))
    return out


def _gap(line, x):
    (a, d) = line
    return d[0] * (x[1] - a[1]) - d[1] * (x[0] - a[0])


# What `_cells_hold` answered, by everything it reads written out: the same tool on the same outline at the same
# numbers always gives the same answer, and the limit walks ask for the same ones again and again.
_CELLS = {}
_CELLS_MAX = 50000


def _cells_hold(planned, spec, points, env, node):
    """True when, at `env`, the body of `node` is the corner of its two sides (both sides' half-planes for a convex
    corner, either for an inward one) where the tool of `spec` changes it (`Spec.region`), and the outline's formula
    passes that body on unchanged there."""
    cuts = _lines_at(spec.region(), env)
    key = repr((planned.tree, spec.label, points, cuts, spec.sign, spec.side_a.index, spec.side_b.index))
    found = _CELLS.get(key)
    if found is None:
        found = _cells_checked(planned, spec, points, cuts, node)
        if len(_CELLS) >= _CELLS_MAX:
            _CELLS.clear()
        _CELLS[key] = found
    return found


def _cells_checked(planned, spec, points, cuts, node):
    corners = _corners_of(cuts)
    if corners is None:
        return False
    sides = _side_lines(points)
    flat = [(a[0], a[1], d[0], d[1]) for a, d in sides]
    size = max(max(abs(c) for c in p) for p in points) or 1.0
    crossing = []
    for line in sides:
        gaps = [_gap(line, p) for p in corners]
        if min(gaps) < _INSIDE and max(gaps) > -_INSIDE:
            crossing.append(line)
    tool = [((k * n[0], k * n[1]), (-n[1], n[0])) for n, k in cuts]
    a, b = spec.side_a.index, spec.side_b.index
    bound = [(n[0], n[1], k - _INSIDE) for n, k in cuts]
    for x in halfplanes.line_samples(crossing + tool, size):
        x0, x1 = x
        if any(n0 * x0 + n1 * x1 > limit for n0, n1, limit in bound):
            continue
        inside = [dx * (x1 - ay) - dy * (x0 - ax) > 0 for ax, ay, dx, dy in flat]
        local = (inside[a] and inside[b]) if spec.sign > 0 else (inside[a] or inside[b])
        if halfplanes.holds(node, inside) != local:
            return False
        if not _holds(planned.tree, inside, node, True) or _holds(planned.tree, inside, node, False):
            return False
    return True


def holds(planned, specs, env):
    """True when the corner tools `specs` give the rounded outline at the size values `env`: each corner keeps its
    kind and turns by more than `_TURN_MIN` and less than 180 degrees less that, each size stays above `SIZE_MIN`, a
    chamfer set by an angle stays on a square corner, what the corners take from each side fits on it, each tool
    lies inside the outline's block, and inside each tool the body it is cut from is the corner alone. The outline's
    own check (`Planned.fits`) is separate."""
    try:
        points = planned.points(env)
        taken = {}
        for spec in specs:
            local = spec.env(env)
            tau = spec.tau.value(local)
            if (1 if tau > 0 else -1) != spec.sign or not _TURN_MIN < abs(tau) < 180.0 - _TURN_MIN:
                return False
            if spec.square and abs(abs(tau) - 90.0) > 1e-6:
                return False
            if spec.r.value(local) <= SIZE_MIN:
                return False
            reach = spec.reach().value(local)
            for side in (spec.side_a.index, spec.side_b.index):
                taken[side] = taken.get(side, 0.0) + reach
        n = len(points)
        for side, reach in taken.items():
            a, b = points[side], points[(side + 1) % n]
            if math.hypot(b[0] - a[0], b[1] - a[1]) - reach < -_GONE:
                return False
        found = nodes(planned.tree)
        limit = planned.half * (1.0 - 0.05)
        for spec in specs:
            local = spec.env(env)
            corners = _corners_of(_lines_at([cut[:2] for cut in spec.cuts()], local))
            if corners is None or any(abs(p[0] - planned.centre[0]) > limit or abs(p[1] - planned.centre[1]) > limit
                                      for p in corners):
                return False
            if not _cells_hold(planned, spec, points, local, found[spec.label]):
                return False
    except _MATH_ERRORS:
        return False
    return True


def agrees(spec, env, shape):
    """True when the formulas of `spec` give, at the sizes now (`env`), the corner the copy measured
    (`outline_rounds._Shape`): the same reach, and for a round the same arc centre."""
    try:
        local = spec.env(env)
        if abs(spec.reach().value(local) - shape.reach) > _SAME:
            return False
        if spec.chamfer:
            return True
        cx, cy = spec.centre()
        return math.hypot(cx.value(local) - shape.center[0], cy.value(local) - shape.center[1]) <= _SAME
    except _MATH_ERRORS:
        return False


def loop_at(planned, specs, env):
    """The outline of `planned` with the corners of `specs` at the size values `env`, as capture curves: a line along
    each side less what the corners take, and an arc (a line for a chamfer) at each corner of a tool. None when a
    formula cannot be worked out there, or two tools share a corner."""
    try:
        points = planned.points(env)
        at = {}
        for spec in specs:
            if spec.k in at:
                return None
            local = spec.env(env)
            centre = None if spec.chamfer else tuple(c.value(local) for c in spec.centre())
            at[spec.k] = (spec.reach().value(local), spec.r.value(local), centre)
    except _MATH_ERRORS:
        return None
    n = len(points)

    def toward(a, b, d):
        length = math.hypot(b[0] - a[0], b[1] - a[1])
        return [a[0] + (b[0] - a[0]) * d / length, a[1] + (b[1] - a[1]) * d / length]

    out = []
    for k in range(n):
        a, b = points[k], points[(k + 1) % n]
        start = toward(a, b, at[k][0]) if k in at else list(a)
        end = toward(b, a, at[(k + 1) % n][0]) if (k + 1) % n in at else list(b)
        if math.hypot(end[0] - start[0], end[1] - start[1]) > _GONE:
            out.append({"kind": "line", "start": start, "end": end})
    for k, (reach, r, centre) in at.items():
        p = points[k]
        ta, tb = toward(p, points[k - 1], reach), toward(p, points[(k + 1) % n], reach)
        if centre is None:
            out.append({"kind": "line", "start": ta, "end": tb})
            continue
        mid = toward(centre, p, r)
        out.append({"kind": "arc", "center": list(centre), "radius": r, "start": ta, "end": tb, "mid": mid})
    return out


# ---- how far the variables may go ------------------------------------------------------------------------------

def reads(planned, specs):
    """Fusion names of the free sizes the outline and its corner tools read."""
    out = {n: None for _, names in planned.bound.values() for n in names}
    for spec in specs:
        for angle, offset, _ in spec.cuts():
            for expr in (angle, offset):
                names = [n for n in expr.names() if n != spec.placeholder]
                out.update(dict.fromkeys(planned.formulas.free_reads(_names_only(names))))
        out.update(dict.fromkeys(spec.size.reads))
    return tuple(out)


def walk(ctx, planned, specs):
    """`{Orca variable: (low, high)}`: how far each free size the outline and its tools read may go (the others
    kept) while the outline and every tool still hold (`Planned.fits`, `holds`); or the name of a size whose limits
    cannot be told."""
    wanted = set(reads(planned, specs))
    found = {}
    for entry in ctx.table.entries:
        if entry.state != FREE or entry.name not in wanted:
            continue

        def fits(value, entry=entry):
            env = size_env(ctx.table, {entry.name: value})
            return planned.fits(env) and holds(planned, specs, env)

        if not fits(entry.value):
            return entry.name
        low, high = limits.bounds(fits, entry.value)
        if low is not None or high is not None:
            found[ctx.names[entry.size_name]] = (low, high)
    return found
