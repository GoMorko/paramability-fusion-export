"""The setup stages of the sketch solver: what it reads from the graph before the propagation starts.

- `_read_items`: the constraints and driving dimensions the solver uses, each checked against the drawing;
- `_directions_setup`: the direction classes of the lines (parallel, collinear and offset lines share one; in the
  extended reading with `distance_parallel`, so do the two lines of a distance dimension), the points tied together
  and the points on each line;
- `_slots_setup`: the unknowns (coordinates, line offsets and lengths, radii) with their values on the drawing;
- `_inputs_setup`: the values known at the start (fixed geometry, projected geometry as measured inputs);
- `_envs_setup`: the size settings the rules and choices are checked at;
- `_rules_setup`: the rules of every curve, constraint and dimension.

`Setup` is a part of the solver (`solve._Solver`), as `crossings.Crossings` is: it fills the solver's state.
"""
from ..sketch_values.expr import name, num
from . import checks, rules
from .directions import Directions
from .outcome import Leaf, Usage
from .slots import Slots, length, offset, radius, x, y

SETTINGS = 3


def input_name(ref, field):
    """The leaf name of a measured input: `@p3.x`, `@p3.y` for a point, `@c5.r` for a radius. `@` is not a letter
    Fusion allows in a parameter name, so an input never meets a parameter."""
    return "@%s%d.%s" % ("p" if ref[0] == "point" else "c", ref[1], field)


def default_settings(leaves, count=SETTINGS):
    """`count` other size settings for the given leaves (name to value now): each leaf moved by 4 to 14 percent of
    its value (at least of 1), up or down, in a fixed pattern that differs per leaf and per setting. Measured inputs
    (`@` names) keep their value: how a projection moves is known only to the caller, and moving its points one by
    one could break a tie that holds in every real setting."""
    out = []
    for k in range(count):
        env = {}
        for i, (leaf, value) in enumerate(sorted(leaves.items())):
            if leaf.startswith("@"):
                continue
            share = 0.04 + 0.10 * ((0.618034 * (i + 1) + 0.414214 * (k + 1)) % 1.0)
            up = 1.0 if (i + k) % 2 == 0 else -1.0
            env[leaf] = value + up * share * max(abs(value), 1.0)
        out.append(env)
    return out


class Setup:
    # --- reading -------------------------------------------------------------------------------------------------

    def _readable_ref(self, ref):
        if ref is None:
            return False
        if ref[0] == "point":
            return self.g.points[ref[1]].readable
        curve = self.g.curves[ref[1]]
        return curve.readable and all(self.g.points[p].readable for p in curve.all_points())

    def _block(self, item, label):
        """Keeps every entity an item names open: the solver does not use the item."""
        verb = "measured by" if item.group == "dimension" else "tied by"
        for ref in item.on:
            for e in self.g.entities(ref):
                self.blocked.setdefault(e, []).append("%s %s" % (verb, label))

    def _read_items(self):
        g = self.g
        for curve in g.curves.values():
            if not curve.readable or curve.kind not in ("line", "arc", "circle"):
                for e in g.entities(("curve", curve.id)):
                    self.blocked.setdefault(e, []).append("on curve %d (%s)" % (curve.id, curve.kind))
        for con in g.constraints:
            label = con.label()
            if con.raw.get("suppressed") is True:
                self.out.constraints[con.id] = Usage("suppressed")
                continue
            if not con.readable or not all(self._readable_ref(r) for r in con.on):
                self.out.constraints[con.id] = Usage("unread", "it could not be read in full")
                self._block(con, label)
                continue
            problem = checks.constraint_problem(g, con, self.tol)
            if problem:
                self.out.constraints[con.id] = Usage("not_used", problem)
                self._block(con, label)
                continue
            self.out.constraints[con.id] = Usage("used")
            self.used_cons.append(con)
        for dim in g.dimensions:
            label = dim.label()
            self.label_dim[label] = dim
            value = dim.raw.get("value")
            if dim.type == "offset_curves":
                self.out.dimensions[dim.id] = Usage("not_used", "it is read with its offset constraint")
                continue
            if (not dim.readable or not isinstance(value, (int, float)) or dim.raw.get("driving") is None
                    or not all(self._readable_ref(r) for r in dim.on)):
                self.out.dimensions[dim.id] = Usage("unread", "it could not be read in full")
                self._block(dim, label)
                continue
            shape, why = checks.dimension_shape(g, dim)
            measured = checks.measure(g, shape) if shape is not None else None
            if dim.raw.get("driving") is False:
                self.out.dimensions[dim.id] = Usage("driven", "a driven dimension only measures", measured)
                continue
            if shape is None:
                self.out.dimensions[dim.id] = Usage("not_covered", why)
                self._block(dim, label)
                continue
            if not checks.dimension_holds(g, shape, float(value), self.tol, self.extended):
                self.out.dimensions[dim.id] = Usage("refused", "it does not match the drawing", measured)
                for ref in dim.on:
                    for e in g.entities(ref):
                        self.refused.setdefault(e, []).append(label)
                continue
            self.out.dimensions[dim.id] = Usage("used", measured=measured)
            self.used_dims.append((dim, shape))

    def _directions_setup(self):
        g = self.g
        vectors = {}
        for curve in g.curves.values():
            if curve.kind == "line" and curve.readable and all(g.points[p].readable for p in curve.points):
                d = g.direction(curve.id)
                if d is not None:
                    vectors[curve.id] = d
        self.dirs = Directions(vectors)
        for con in self.used_cons:
            if con.type in ("parallel", "collinear") and all(r[1] in vectors for r in con.on):
                self.dirs.join(con.on[0][1], con.on[1][1])
            if con.type == "offset":
                for parent, child, _ in checks.offset_pairs(g, con, self.tol):
                    if parent in vectors and child in vectors and g.curves[child].kind == "line":
                        self.dirs.join(parent, child)
        if self.distance_parallel:
            # Fusion keeps the two lines of a distance dimension parallel (hand test OR18 in docs/hand-tests.md).
            for _, shape in self.used_dims:
                if shape.kind == "line_line" and shape.line in vectors and shape.other in vectors:
                    if not self.dirs.same_class(shape.line, shape.other):
                        self.out.parallel_by_distance.append((shape.line, shape.other))
                    self.dirs.join(shape.line, shape.other)
        twin = {}
        for con in self.used_cons:
            if con.type == "coincident" and con.on[1][0] == "point":
                a, b = self.twin_root(twin, con.on[0][1]), self.twin_root(twin, con.on[1][1])
                if a != b:
                    twin[b] = a
        self._twin = twin
        on_line = {}
        for curve in g.curves.values():
            if curve.kind == "line" and len(curve.points) == 2:
                on_line[curve.id] = set(curve.points)
        for con in self.used_cons:
            if con.type == "coincident" and g.is_line(con.on[1]):
                on_line.setdefault(con.on[1][1], set()).add(con.on[0][1])
            if con.type == "midpoint":
                on_line.setdefault(con.on[1][1], set()).add(con.on[0][1])
        for line, points in on_line.items():
            roots = {self.twin(p) for p in points}
            on_line[line] = {p for p in g.points if self.twin(p) in roots}
        self._on_line = on_line

    @staticmethod
    def twin_root(twin, p):
        while p in twin:
            p = twin[p]
        return p

    def _slots_setup(self):
        g = self.g
        base = {}
        for point in g.points.values():
            if point.readable:
                base[x(point.id)], base[y(point.id)] = point.xy
        for line in self.dirs.vector:
            bx, by = self.dirs.base(line)
            (ax, ay), (ex, ey) = g.ends(line)
            base[offset(line)] = -by * ax + bx * ay
            base[length(line)] = bx * (ex - ax) + by * (ey - ay)
        for curve in g.curves.values():
            if curve.round and curve.readable:
                base[radius(curve.id)] = curve.radius
        self.slots = Slots(base)

    def _reference_of(self, ref):
        """The reference record of an entity, or of a curve that holds a point; None for own geometry."""
        if ref[0] == "point":
            own = self.g.points[ref[1]].reference
            if own is not None:
                return own
            for curve in self.g.curves.values():
                if curve.reference is not None and ref[1] in curve.all_points():
                    return curve.reference
            return None
        return self.g.curves[ref[1]].reference

    def _fixed(self, ref):
        if ref[0] == "point":
            point = self.g.points[ref[1]]
            return point.fixed or point.origin or any(
                c.fixed for c in self.g.curves.values() if ref[1] in c.all_points())
        return self.g.curves[ref[1]].fixed

    def _inputs_setup(self):
        """Known values at the start: constants and measured inputs."""
        g = self.g
        self.start = []  # (slot, Expr, why)
        for point in g.points.values():
            if not point.readable:
                continue
            ref = ("point", point.id)
            reference = self._reference_of(ref)
            if self._fixed(ref) or (reference is not None and (reference.get("source") not in ("own", "other")
                                                               or ref in self.constants)):
                self.start += [(x(point.id), num(point.xy[0]), "fixed"), (y(point.id), num(point.xy[1]), "fixed")]
            elif reference is not None:
                for field, slot, value in (("x", x(point.id), point.xy[0]), ("y", y(point.id), point.xy[1])):
                    leaf = input_name(ref, field)
                    self.leaves[leaf] = Leaf(leaf, "input", value, entity=ref, field=field, token=point.token)
                    self.start.append((slot, name(leaf), "input"))
                self.out.own.discard(ref)
            else:
                self.out.own.add(ref)
        for curve in g.curves.values():
            ref = ("curve", curve.id)
            if not curve.round or not curve.readable:
                continue
            reference = curve.reference
            if curve.fixed or (reference is not None and (reference.get("source") not in ("own", "other")
                                                          or ref in self.constants)):
                self.start.append((radius(curve.id), num(curve.radius), "fixed"))
            elif reference is not None:
                leaf = input_name(ref, "r")
                self.leaves[leaf] = Leaf(leaf, "input", curve.radius, entity=ref, field="r", token=curve.token)
                self.start.append((radius(curve.id), name(leaf), "input"))
            else:
                self.out.own.add(ref)
        for point in g.points.values():
            if not point.readable and point.reference is None:
                self.out.own.add(("point", point.id))

    def _leaf_of_dimension(self, dim, param, value):
        self.leaves[param] = Leaf(param, "dimension", value, dimension=dim.id, expression=dim.raw.get("expression"),
                                  reads=dim.raw.get("reads") or ())

    def _dimension_value(self, dim):
        value = float(dim.raw["value"])
        param = dim.raw.get("param")
        if not param:
            return num(value)
        self._leaf_of_dimension(dim, param, value)
        return name(param)

    def _envs_setup(self):
        values = {d.raw["param"]: float(d.raw["value"]) for d, _ in self.used_dims if d.raw.get("param")}
        for con in self.used_cons:
            if con.type == "offset":
                for dim in self.g.dimensions:
                    if dim.id == con.raw.get("dimension") and dim.raw.get("param") and dim.raw.get("driving"):
                        values[dim.raw["param"]] = abs(float(dim.raw.get("value") or 0.0))
        values.update({n: leaf.value for n, leaf in self.leaves.items() if leaf.kind == "input"})
        self.base_env = values
        given = self.given_settings
        raw = default_settings(values) if given is None else given
        self.envs = [dict(values, **{k: float(v) for k, v in env.items() if k in values}) for env in raw]
        self.out.settings = self.envs

    def _rules_setup(self):
        g = self.g
        for curve in g.curves.values():
            if curve.readable and curve.kind in ("line", "arc"):
                self._add_all(rules.curve_rules(self, curve.id))
        for con in self.used_cons:
            try:
                self._add_all(rules.constraint_rules(self, con, con.label()))
            except rules.Ambiguous:
                self.out.constraints[con.id] = Usage("not_used", "the drawing cannot tell its two solutions apart")
                self._block(con, con.label())
        for dim, shape in self.used_dims:
            label = dim.label()
            try:
                made = rules.dimension_rules(self, shape, self._dimension_value(dim), label)
            except rules.Ambiguous:
                made = None
                self.out.dimensions[dim.id] = Usage("not_used", "the drawing cannot tell its two solutions apart")
                self._block(dim, label)
                continue
            if made is None:
                self.out.dimensions[dim.id] = Usage("not_covered", "it measures to a line with no length")
                self._block(dim, label)
                continue
            self._add_all(made)
        for slot, value, why in self.start:
            self._set_slot(slot, value, why)
