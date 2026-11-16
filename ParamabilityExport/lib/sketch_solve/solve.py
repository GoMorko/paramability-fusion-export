"""Works out every point of a sketch as a formula of its dimensions, by propagation over the sketch's constraint graph.

Start from what is known (the origin, fixed entities, projected entities as constants or measured inputs, the
driving dimensions that match the drawing) and apply local rules until nothing changes:

- line directions: horizontal and vertical fix them, perpendicular and angle dimensions turn a known one, two known
  ends (in the extended reading also a known gap between the ends) give one (`DirFixed`, `DirLink`,
  `_directions_from_points`);
- linear relations between slots (`slots`): one with a single unknown gives it; one with two unknowns and constant
  factors joins them into a group (so a rectangle's sides share their x and y); two with the same two unknowns give
  both (two lines crossing);
- distances: a point at a known distance from a known point, with one more coordinate or a line through it, is the
  crossing of a circle with a line (two circles give that line first; `crossings`).

No numbers are solved for. Every value is checked against the solved drawing when it is made; where a rule has two
solutions, the one the drawing shows is kept and recorded as an `Assumption`. A rule that gives a value already known
must agree with it at the current sizes and at other size settings; if it does not, the reading is wrong and nothing
of the sketch is used. A value no rule reaches stays open with the reason why.
"""
import math

from ..sketch_values.expr import Expr, ExprDomainError, name, num
from . import rules
from .crossings import Conflict as _Conflict, Crossings
from .directions import Dir, from_points, matches
from .graph import GraphError, load
from .outcome import BLOCKED, CONFLICT, FREE, NO_RULE, REFUSED, UNREAD, Assumption, Solution, Usage, Value
from .setup import Setup, default_settings, input_name  # noqa: F401 (input_name and default_settings are public here)
from .slots import Lin, Rel, radius, slot_text, x, y

TOLERANCE = 1e-6
_MATH_ERRORS = (ExprDomainError, ZeroDivisionError, OverflowError, ValueError)


def solve_sketch(record, settings=None, constants=(), tol=TOLERANCE, extended=False, distance_parallel=True):
    """The `Solution` of one sketch graph record (docs/capture-format.md, "Sketch graphs").

    `settings` are other size settings to check redundant rules and choices at: a list of dicts from leaf name (a
    dimension's model parameter or an input name) to number, a leaf left out keeps its value now. Without them the
    solver makes `SETTINGS` of its own (`default_settings`), moving each dimension on its own. `constants` are refs
    (`("point", id)` or `("curve", id)`) of projected entities the caller knows do not move: they are constants
    instead of measured inputs.

    `extended` turns on the reading the Orca copy uses; the recipe output keeps the default. It reads a driving
    distance dimension between two lines as keeping them parallel, tests angles and parallel lines within what the
    rounding of the drawing allows for the lines' lengths (`checks.turn_slack`), and gives each line's direction
    (`Solution.directions`). With `distance_parallel` False, the extended reading leaves out the first rule: a
    caller compares both readings to find what rests on it (hand test OR18)."""
    solution = Solution((record or {}).get("sketch", "") if isinstance(record, dict) else "",
                        (record or {}).get("token", "") if isinstance(record, dict) else "")
    try:
        graph = load(record)
    except GraphError as error:
        solution.reason = str(error)
        solution.finish()
        return solution
    try:
        _Solver(graph, solution, settings, set(map(tuple, constants)), tol, extended,
                extended and distance_parallel).run()
    except Exception as error:  # a fault in the solver leaves the sketch to measuring, never stops the export
        solution.points, solution.radii = {}, {}
        solution.reason = "the solver stopped on an error (%s)" % error
    solution.finish()
    return solution


class _Solver(Setup, Crossings):
    def __init__(self, g, solution, settings, constants, tol, extended=False, distance_parallel=False):
        self.g, self.out, self.tol = g, solution, tol
        self.extended = extended
        self.distance_parallel = distance_parallel
        self.constants = constants
        self.given_settings = settings
        self.blocked = {}  # entity ref -> [labels]
        self.refused = {}  # entity ref -> [labels] of dimensions that failed their check
        self.used_dims = []  # (dim, shape)
        self.used_cons = []
        self.label_dim = {}
        self.leaves = {}
        self.items = []  # relations not yet resolved
        self.dir_items = []
        self.deferred = []
        self.guards = []

    # --- context the rules read ----------------------------------------------------------------------------------

    def on_line(self, line):
        return self._on_line.get(line, set())

    def twin(self, p):
        while p in self._twin:
            p = self._twin[p]
        return p

    def lines_through(self, a, b):
        """Lines with a direction that both points lie on."""
        return [line for line, points in self._on_line.items()
                if line in self.dirs.vector and a in points and b in points]

    def offset_distance(self, con):
        dim_id = con.raw.get("dimension")
        for dim in self.g.dimensions:
            if dim.id == dim_id and dim.type == "offset_curves" and dim.readable and dim.raw.get("driving"):
                param = dim.raw.get("param")
                value = dim.raw.get("value")
                if isinstance(value, (int, float)) and abs(abs(value) - abs(con.raw["distance"])) <= self.tol:
                    self.out.dimensions[dim.id] = Usage("used", measured=abs(con.raw["distance"]))
                    if param:
                        self._leaf_of_dimension(dim, param, abs(value))
                        return name(param)
                    return num(abs(value))
        return num(abs(con.raw["distance"]))

    def stays_parallel(self, a, b):
        da, db = self.dirs.known(a), self.dirs.known(b)
        cross = da.c * db.s - da.s * db.c
        return cross.is_constant and abs(cross.const) < 1e-12 or self._zero_everywhere(cross, 1.0)

    def refuse(self, label, reason):
        dim = self.label_dim.get(label)
        if dim is not None:
            self.out.dimensions[dim.id] = Usage("not_covered", reason)
            self._block(dim, label)

    # --- run -----------------------------------------------------------------------------------------------------

    def run(self):
        try:
            self._read_items()
            self._directions_setup()
            self._slots_setup()
            self._inputs_setup()
            self._envs_setup()
            self._rules_setup()
            self._loop()
            self._final_checks()
        except _Conflict as conflict:
            self.out.reason = str(conflict)
        self._report()

    def _add_all(self, made):
        for item in made:
            if isinstance(item, (rules.DirFixed, rules.DirLink)):
                self.dir_items.append(item)
            elif isinstance(item, rules.Deferred):
                self.deferred.append(item)
            else:
                self._add(item)

    def _add(self, item):
        """Adds a relation after checking it on the solved drawing."""
        if isinstance(item, Rel):
            residual = item.lin.base(self._base_slot, self._at_base)
            scale = 1.0 + sum(abs(self._at_base(c) * self._base_slot(s)) for s, c in item.lin.terms.items())
            if abs(residual) > self.tol * scale:
                raise _Conflict("%s does not hold on the drawing (off by %.3g)" % (item.source, residual))
        else:
            (ax, ay), (bx, by) = self.g.xy(item.a), self.g.xy(item.b)
            rho = item.rho.base(self._base_slot, self._at_base)
            if abs(math.hypot(bx - ax, by - ay) - abs(rho)) > self.tol * (1.0 + abs(rho)):
                raise _Conflict("%s does not hold on the drawing" % item.source)
        self.items.append(item)

    # --- numbers -------------------------------------------------------------------------------------------------

    def _base_slot(self, slot):
        return self.slots.base[slot]

    def _at_base(self, expr):
        return expr.value(self.base_env)

    def _valid_envs(self):
        """The settings at which every choice made so far still holds."""
        out = []
        for env in self.envs:
            try:
                if all(guard.value(env) > 0 for guard in self.guards):
                    out.append(env)
            except _MATH_ERRORS:
                pass
        return out

    def _zero_everywhere(self, expr, scale):
        """True when `expr` is zero at the current sizes and at every valid setting (relative to `scale`, an Expr or
        a number)."""
        for env in [self.base_env] + self._valid_envs():
            try:
                size = abs(scale.value(env)) if isinstance(scale, Expr) else abs(scale)
                if abs(expr.value(env)) > self.tol * (1.0 + size) * 10.0:
                    return False
            except _MATH_ERRORS:
                continue
        return True

    def _assume(self, text, guard, where):
        """Records a choice; `guard` is above zero on the solved drawing."""
        assumption = Assumption(text, guard, where)
        self.out.assumptions.append(assumption)
        if not guard.is_constant:
            self.guards.append(guard)

    # --- setting values ------------------------------------------------------------------------------------------

    def _set_slot(self, slot, value, source):
        root, m, k = self.slots.find(slot)
        if root in self.slots.value:
            known = self.slots.value[root].scaled(m) + k
            if not self._zero_everywhere(known - value, known):
                raise _Conflict("%s gives another value than the other rules" % source)
            return
        self._assign(root, (value - k).scaled(1.0 / m), source)

    def _assign(self, root, value, source):
        for slot in self.slots.group(root):
            _, m, k = self.slots.find(slot)
            try:
                got = self._at_base(value.scaled(m) + k)
            except _MATH_ERRORS:
                raise _Conflict("%s gives no value on the drawing" % source)
            want = self.slots.base[slot]
            if abs(got - want) > self.tol * (1.0 + abs(want) * 1e-3):
                raise _Conflict("%s gives %.6g for %s, the drawing has %.6g" % (source, got, slot_text(slot), want))
        self.slots.assign(root, value, source)

    # --- propagation ---------------------------------------------------------------------------------------------

    def _loop(self):
        while True:
            if self._directions() or self._build_deferred() or self._linear():
                continue
            if self._pairs() or self._distances() or self._directions_from_points():
                continue
            break

    def _directions(self):
        progress = False
        for item in list(self.dir_items):
            if isinstance(item, rules.DirFixed):
                candidates = [Dir.at(num(a)) for a in item.angles]
                if self._set_direction(item.line, candidates, item.source):
                    self.dir_items.remove(item)
                    progress = True
                continue
            for known, other in ((item.a, item.b), (item.b, item.a)):
                d = self.dirs.known(known)
                if d is None:
                    continue
                candidates = []
                for turn in item.turns:
                    for half in (0.0, 180.0):
                        candidates.append(d.turned(turn + half))
                        candidates.append(d.turned(-turn + half))
                if self._set_direction(other, candidates, item.source):
                    self.dir_items.remove(item)
                    progress = True
                break
        return progress

    def _set_direction(self, line, candidates, source):
        """Sets (or checks) a line's class direction from candidates; True when the item is done."""
        vector = self.dirs.base(line)
        fits = []
        for d in candidates:
            if matches(d, vector, self._at_base) and not any(_same_dir(d, f) for f in fits):
                fits.append(d)
        if not fits:
            raise _Conflict("%s does not fit the drawn line %d" % (source, line))
        if len(fits) > 1:
            return False
        d = fits[0]
        known = self.dirs.known(line)
        if known is not None:
            cross = known.c * d.s - known.s * d.c
            if not self._zero_everywhere(cross, 1.0):
                raise _Conflict("%s gives line %d another direction than the other rules" % (source, line))
            return True
        self.dirs.value[self.dirs.root(line)] = d
        self.dirs.source[self.dirs.root(line)] = source
        return True

    def _directions_from_points(self, only_fixed=False):
        progress = False
        for line in self.dirs.vector:
            if self.dirs.known(line) is not None:
                continue
            a, b = self.g.curves[line].points
            coords = [self.slots.known(s) for s in (x(a), y(a), x(b), y(b))]
            if any(c is None for c in coords):
                if not self.extended:
                    continue
                coords = self._gap_of_ends(a, b)
                if coords is None:
                    continue
            d = from_points(*coords)
            if not matches(d, self.dirs.base(line), self._at_base):
                d = d.reversed()
            self._set_direction(line, [d], "the ends of line %d" % line)
            progress = True
        return progress

    def _gap_of_ends(self, a, b):
        """`(0, 0, dx, dy)` when the gap from point `a` to point `b` is known on both axes although the points are
        not (their coordinates share groups, as the corners of a rectangle do), else None. The gap gives the line's
        direction: the diagonal of a centre rectangle, which a point on both diagonals then places."""
        gap = []
        for axis in (x, y):
            unknown, const = self.slots.reduce(Lin({axis(b): 1.0, axis(a): -1.0}))
            if unknown:
                return None
            gap.append(const)
        return num(0.0), num(0.0), gap[0], gap[1]

    def _build_deferred(self):
        progress = False
        for item in list(self.deferred):
            if item.ready(self):
                self.deferred.remove(item)
                for made in item.build(self):
                    self._add(made)
                progress = True
        return progress

    def _check_known(self, item):
        """A relation whose unknowns cancel out must hold at every setting."""
        unknown, const = self.slots.reduce(item.lin)
        scale = num(1.0)
        for slot, coef in item.lin.terms.items():
            known = self.slots.known(slot)
            if known is not None:
                scale = scale + coef * known
        if not self._zero_everywhere(const, scale):
            raise _Conflict("%s does not agree with the other rules when the sizes change" % item.source)

    def _linear(self):
        progress = False
        for item in list(self.items):
            if not isinstance(item, Rel):
                continue
            unknown, const = self.slots.reduce(item.lin)
            if not unknown:
                self._check_known(item)
                self.items.remove(item)
                continue
            if len(unknown) == 1:
                (root, a), = unknown.items()
                a0 = self._at_base(a)
                if abs(a0) <= 1e-9:
                    continue
                if not a.is_constant:
                    self._assume("%s divides by a value that must not reach zero" % item.source,
                                 a.scaled(1.0 if a0 > 0 else -1.0), slot_text(root))
                self._assign(root, (-const) / a, item.source)
                self.items.remove(item)
                progress = True
            elif len(unknown) == 2 and all(c.is_constant for c in unknown.values()):
                (r1, a), (r2, b) = unknown.items()
                if len(self.slots.group(r2)) > len(self.slots.group(r1)):
                    (r1, a), (r2, b) = (r2, b), (r1, a)
                # a * r1 + b * r2 + const = 0
                self.slots.join(r1, r2, -a.const / b.const, const.scaled(-1.0 / b.const))
                self.items.remove(item)
                progress = True
        return progress

    def _pairs(self):
        """Two relations over the same two unknowns give both (Cramer's rule)."""
        open_two = []
        for item in self.items:
            if isinstance(item, Rel):
                unknown, const = self.slots.reduce(item.lin)
                if len(unknown) == 2:
                    open_two.append((item, unknown, const))
        for i, (item1, u1, c1) in enumerate(open_two):
            for item2, u2, c2 in open_two[i + 1:]:
                if set(u1) != set(u2):
                    continue
                r1, r2 = sorted(u1)
                a1, b1, a2, b2 = u1[r1], u1[r2], u2[r1], u2[r2]
                det = a1 * b2 - a2 * b1
                d0 = self._at_base(det)
                size = abs(self._at_base(a1 * b2)) + abs(self._at_base(a2 * b1))
                if abs(d0) <= 1e-9 * max(size, 1e-12):
                    continue
                where = "%s and %s" % (item1.source, item2.source)
                if not det.is_constant:
                    self._assume("%s cross where they are not parallel" % where, det.scaled(1.0 if d0 > 0 else -1.0),
                                 slot_text(r1))
                # a1 r1 + b1 r2 + c1 = 0, a2 r1 + b2 r2 + c2 = 0
                self._assign(r1, (b1 * c2 - b2 * c1) / det, where)
                self._assign(r2, (a2 * c1 - a1 * c2) / det, where)
                self.items.remove(item1)
                self.items.remove(item2)
                return True
        return False

    # --- after the propagation -----------------------------------------------------------------------------------

    def _final_checks(self):
        for item in list(self.items):
            if isinstance(item, Rel) and not self.slots.reduce(item.lin)[0]:
                self._check_known(item)
        for assumption in self.out.assumptions:
            for at, env in enumerate(self.envs):
                try:
                    holds = assumption.guard.value(env) > 0
                except _MATH_ERRORS:
                    holds = False
                if not holds:
                    assumption.flips.append(at)

    def _report(self):
        g = self.g
        conflict = self.out.reason
        for point in g.points.values():
            ref = ("point", point.id)
            pair = []
            for slot in (x(point.id), y(point.id)):
                pair.append(self._value(ref, slot, conflict))
            self.out.points[point.id] = tuple(pair)
        for curve in g.curves.values():
            if curve.round:
                self.out.radii[curve.id] = self._value(("curve", curve.id), radius(curve.id), conflict)
        self.out.leaves = {n: leaf for n, leaf in self.leaves.items()
                           if leaf.kind == "input" or n in self.base_env}
        if self.extended:
            for line in self.dirs.vector:
                angle = None if conflict else self.dirs.angle_of(line)
                self.out.directions[line] = Value(angle) if angle is not None else Value(
                    code=CONFLICT if conflict else NO_RULE,
                    reason=conflict or "no rule gives its direction as an angle")
        if g.fully_constrained is False:
            self.out.notes.append("Fusion says the sketch is not fully constrained")

    def _value(self, ref, slot, conflict):
        if conflict:
            return Value(code=CONFLICT, reason=conflict)
        entity = self.g.points.get(ref[1]) if ref[0] == "point" else self.g.curves.get(ref[1])
        if not entity.readable:
            return Value(code=UNREAD, reason="it could not be read")
        if ref in self.blocked:
            return Value(code=BLOCKED, reason="%s, which the solver does not read" % ", ".join(
                dict.fromkeys(self.blocked[ref])))
        known = self.slots.known(slot) if slot in self.slots.base else None
        if known is not None:
            return Value(known)
        if ref in self.refused:
            return Value(code=REFUSED, reason="%s does not match the drawing, so it is not used" % ", ".join(
                dict.fromkeys(self.refused[ref])))
        if entity.free:
            return Value(code=FREE, reason="Fusion says it is not fully constrained, and no rule fixes it")
        return Value(code=NO_RULE, reason="no rule reaches it from what is known")


def _same_dir(a, b):
    return a.c.same(b.c) and a.s.same(b.s)
