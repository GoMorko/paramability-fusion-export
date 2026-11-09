"""The sizes of one export: which Fusion parameters become recipe sizes, and the translation of expressions over them.

    table = size_table.build(params, ticked)

`params` are the user parameters as read by `fusion_reader.parameters.list_user_parameters` (Fusion internal values:
cm, rad). `ticked` are the Fusion names the person keeps as sizes. Optional keywords: `model_params` (the body's model
parameters, for inlining, counts and defaults), `design_unit` (what a bare number in a length expression means),
`fixed` (ticked names that cannot follow, with the reason; they become plain numbers), `quantity_params` (the model
parameters the steps use as a pattern quantity; the user parameters behind them become whole-number counts) and
`ranges` (min and max per size from the dialog, instead of the default range; a range equal to the default is not
typed, `typed_ends`). `minimums` raises the smallest value of some
sizes above their range (the translator does this when a smaller value would remove a pattern copy a step picks).

The table holds, per parameter, one entry whose `state` is:

- `free`: a plain number kept as a size (`table.sizes[recipe_name]` has `kind`, `value`, `min`, `max`, `label`);
- `derived`: a formula over other sizes (`{ expr, label }`). Past the size cap it has no size name, and every
  formula that reads it holds the formula itself;
- `constant`: a plain number that is not a size; every formula that reads it holds its number;
- `fixed`: fixed with a reason (shown unticked and greyed); it is not a size of the recipe;
- `not_offered`: a unit or formula that cannot be copied (the reason is kept).

Units only convert numbers: a formula whose unit differs from its parameter's (a count times `1 mm` in a length, a
plain number in a length) is scaled to the number Fusion reports, and the value check picks the reading.

`translate(expression)` turns a Fusion expression (a feature value read from a model parameter) into a formula over
the sizes; `depends(name)` lists the free sizes a parameter or an expression name depends on, which is what the
driver fixes when a value cannot follow.
"""
from dataclasses import dataclass

from ..package.manifest import MAX_FIXED_REASON
from . import defaults, names
from .expressions import (
    ANGLE, LENGTH, LENGTH_MM, MAX_FORMULA_LENGTH, SCALAR, ExpressionError, Typed, evaluate, scale_node,
    internal_factor, parse, parse_formula, referenced_names, render, translate_tree, unit_scale)

# Named sizes in one recipe, derived ones included (the app's recipe cap).
MAX_SIZES = 64
VALUE_TOLERANCE = 1e-6

FREE, DERIVED, CONSTANT, FIXED, NOT_OFFERED = "free", "derived", "constant", "fixed", "not_offered"


@dataclass
class Entry:
    name: str  # Fusion name
    state: str
    size_name: str = ""  # recipe name, set for free and derived
    label: str = ""
    kind: str = ""  # recipe size kind of a plain number
    value: float = 0.0  # mm, degrees or the plain number
    expression: str = ""  # Fusion text for a derived entry
    formula: str = ""  # written formula of a derived entry (also of a constant one that has a formula)
    reads: tuple = ()  # Fusion names of the free sizes a derived entry depends on
    reason: str = ""


@dataclass
class Translation:
    """Result of `SizeTable.translate`. `formula` is None when the expression cannot be written; `reason` says why."""
    formula: object = None
    reads: tuple = ()  # Fusion names of the free sizes the expression depends on, also when it cannot be written
    dim: str = ""  # "length", "angle" or "scalar" (the formula's unit: mm, degrees or none)
    value: object = None  # the formula at the current size values
    reason: str = ""

    @property
    def ok(self):
        return self.formula is not None


_DIM_NAMES = {LENGTH: "length", ANGLE: "angle", SCALAR: "scalar"}
_DIMS = {name: dim for dim, name in _DIM_NAMES.items()}
UNIT_REASON = "Its unit is not a length or an angle."


def _unit_factors(source, target, unit, design_mm):
    """Factors that may turn a formula of unit `source` into the number of a parameter of unit `target`, the most
    likely first. A plain number is read in the parameter's own unit or the design's; a quantity in a parameter
    without a unit is read as it stands, in Fusion's cm and radians, or in the design's unit."""
    if source == target:
        return [1.0]
    if source == SCALAR:
        own = unit_scale(unit)
        return [own[1] if own is not None and own[0] == target else 1.0, design_mm ** target[0], 1.0]
    if target == SCALAR:
        return [1.0, 1.0 / internal_factor(source), design_mm ** -source[0]]
    return [1.0]


def _round(x):
    return round(x, 9)


class SizeTable:
    def __init__(self, params, ticked, model_params=(), design_unit="mm", fixed=None, quantity_params=(),
                 ranges=None, max_sizes=MAX_SIZES, minimums=None, narrowed=None):
        self._params = [p for p in params]
        self._minimums = dict(minimums or {})
        self._narrowed = dict(narrowed or {})
        self._max_sizes = max_sizes
        self._ranges = dict(ranges or {})
        self._model = list(model_params)
        self._ticked_in = list(ticked)
        self._design_unit = design_unit
        self._fixed_in = dict(fixed or {})
        self._quantity_params = list(quantity_params)
        self._design_mm = LENGTH_MM.get((design_unit or "mm").lower(), 1.0)
        self.model_params = {m["name"]: m for m in self._model}
        self.entries = []
        self.sizes = {}
        self.renames = {}
        self._by_name = {}
        self._depth_stack = []
        self._compute()

    # ---- building --------------------------------------------------------------------------------------------

    def _compute(self):
        counts = defaults.count_names(self._params, self._model, self._quantity_params)
        candidates = list(self._params)
        self._cand = {p["name"]: p for p in candidates}
        self._recipe_names = names.assign([p["name"] for p in candidates])
        ticked = set(self._ticked_in)
        free_count = 0
        self._entries = {}
        for p in candidates:
            e = self._plain_entry(p, ticked, counts, free_count)
            if e is not None:
                self._entries[p["name"]] = e
                if e.state == FREE:
                    free_count += 1
        self._free_count = free_count
        self._active = set()
        for p in candidates:
            if p["name"] not in self._entries:
                self._derived_entry(p["name"])
        for p in candidates:
            e = self._entries[p["name"]]
            self.entries.append(e)
            if e.state in (FREE, DERIVED) and e.size_name:
                self.sizes[e.size_name] = self._size_dict(e)
                if e.size_name != e.name:
                    self.renames[e.name] = e.size_name

    def _plain_entry(self, p, ticked, counts, free_count):
        """Entry of a plain number parameter; None for a formula (handled by _derived_entry)."""
        if not defaults.is_numeric(p):
            return Entry(p["name"], NOT_OFFERED, reason="Text values are not offered.")
        if p.get("kind") == "derived":
            return None
        label = defaults.label_for(p)
        if defaults.dim_of_unit(p.get("unit")) is None:
            return Entry(p["name"], NOT_OFFERED, label=label, reason=UNIT_REASON)
        value = _round(defaults.size_value(p))
        kind = defaults.size_kind(p, counts)
        base = dict(name=p["name"], label=label, kind=kind, value=value)
        if not defaults.is_offered(p):
            # A unit built from lengths and angles (an area): its number is used, it is not a size.
            return Entry(state=CONSTANT, **base)
        if p["name"] in self._fixed_in:
            return Entry(state=FIXED, size_name=self._recipe_names[p["name"]], reason=self._fixed_in[p["name"]],
                         **base)
        if p["name"] in ticked:
            if free_count >= self._max_sizes:
                return Entry(state=CONSTANT, reason=f"{self._max_sizes} is the most sizes.", **base)
            return Entry(state=FREE, size_name=self._recipe_names[p["name"]], **base)
        return Entry(state=CONSTANT, **base)

    def _derived_entry(self, name):
        """Entry of a formula parameter: a derived size when it translates and reads a free size, else a number."""
        if name in self._entries:
            return self._entries[name]
        p = self._cand[name]
        base = dict(name=name, label=defaults.label_for(p), expression=p.get("expression", ""),
                    kind=defaults.size_kind(p), value=_round(defaults.size_value(p)))
        if name in self._active:
            raise ExpressionError(f"\"{name}\" reads itself.")
        dim = defaults.dim_of_unit(p.get("unit"))
        if dim is None:
            entry = Entry(state=NOT_OFFERED, reason=UNIT_REASON, **base)
            self._entries[name] = entry
            return entry
        self._active.add(name)
        try:
            tr = self._translate(p["expression"], expected=base["value"], dim=dim, unit=p.get("unit"))
        finally:
            self._active.discard(name)
        if not tr.ok:
            entry = Entry(state=NOT_OFFERED, reads=tr.reads, reason=tr.reason, **base)
        elif not tr.reads:
            entry = Entry(state=CONSTANT, formula=tr.formula, **base)
        elif len(tr.formula) > MAX_FORMULA_LENGTH:
            entry = Entry(state=NOT_OFFERED, reads=tr.reads, reason="The formula is too long to copy.", **base)
        else:
            named = sum(1 for e in self._entries.values() if e.state in (FREE, DERIVED) and e.size_name)
            size_name = self._recipe_names[name] if named < self._max_sizes else ""
            entry = Entry(state=DERIVED, size_name=size_name, formula=tr.formula, reads=tr.reads, **base)
        self._entries[name] = entry
        return entry

    def _size_dict(self, e):
        if e.state == DERIVED:
            return {"expr": e.formula, "label": e.label}
        p = self._cand[e.name]
        lo, hi = self._narrowed.get(e.name) or self._ranges.get(e.name) or defaults.size_range(p, e.kind, e.value)
        lo = max(lo, self._minimums.get(e.name, lo))
        size = {"kind": e.kind, "value": e.value, "min": lo, "max": hi, "label": e.label}
        if e.kind == "count":
            size["step"] = 1
        return size

    # ---- translation -----------------------------------------------------------------------------------------

    def _eval_derived(self, e, env):
        try:
            return evaluate(e.formula, env)
        except ExpressionError:
            return e.value

    def _resolver(self, reads, stack):
        def resolve(name):
            p = self._cand.get(name)
            if p is not None:
                dim = defaults.dim_of_unit(p.get("unit"))
                if dim is None or not defaults.is_numeric(p):
                    raise ExpressionError(f"It reads \"{name}\", whose unit is not a length or an angle.")
                e = self._entries.get(name) or self._derived_entry(name)
                if e.state == FREE:
                    reads.append(name)
                    return Typed(("name", e.size_name), dim, False)
                if e.state == DERIVED:
                    reads.extend(e.reads)
                    return Typed(("name", e.size_name) if e.size_name else parse_formula(e.formula), dim, False)
                if e.state == NOT_OFFERED and p.get("kind") == "derived" and e.reads:
                    # It follows sizes but its formula cannot be written, so neither can this one.
                    reads.extend(e.reads)
                    raise ExpressionError(f"It reads \"{name}\", which cannot be copied: {e.reason}")
                return Typed(("num", e.value), dim, False)
            m = self.model_params.get(name)
            if m is not None:
                if name in stack:
                    raise ExpressionError(f"\"{name}\" reads itself.")
                stack.append(name)
                try:
                    inner = translate_tree(parse(m["expression"]), self._resolver(reads, stack), self._design_mm)
                finally:
                    stack.pop()
                dim = defaults.dim_of_unit(m.get("unit"))
                if dim is None or dim == inner.dim:
                    return inner
                node = self._pick(self._readings(inner, dim, m.get("unit")), defaults.size_value(m))[0]
                return Typed(node, dim, False)
            raise ExpressionError(f"\"{name}\" is not a parameter that can be copied.")
        return resolve

    def _readings(self, typed, dim, unit):
        """The formula node scaled to each likely reading of it in a parameter of unit `dim` (`unit` its text)."""
        factors = _unit_factors(typed.dim, dim, unit, self._design_mm)
        return [scale_node(typed.node, f) for f in dict.fromkeys(factors)]

    def _pick(self, nodes, expected):
        """(node, written formula, value) of the first node that gives `expected` (any when it is None), else of the
        first node. Raises ExpressionError when the formula cannot be worked out."""
        env = self._env()
        first = None
        for node in nodes:
            text = render(node)
            value = evaluate(text, env)
            if expected is None or abs(value - expected) <= VALUE_TOLERANCE + 1e-9 * abs(expected):
                return node, text, value
            if first is None:
                first = (node, text, value)
        return first

    def _env(self):
        env = {e.size_name: e.value for e in self._entries.values() if e.state == FREE}
        env.update(self._derived_values())
        return env

    def _translate(self, expression, expected=None, dim=None, unit=""):
        """`dim` and `unit` are those of the parameter the expression sets; without them the formula keeps its own."""
        reads = []
        try:
            tree = parse(expression)
            typed = translate_tree(tree, self._resolver(reads, []), self._design_mm)
            merged = self._merge_reads(reads, expression)
            nodes = [typed.node] if dim is None else self._readings(typed, dim, unit)
            _, text, value = self._pick(nodes, expected)
        except ExpressionError as exc:
            return Translation(reads=self._merge_reads(reads, expression), reason=str(exc))
        if expected is not None and abs(value - expected) > VALUE_TOLERANCE + 1e-9 * abs(expected):
            return Translation(
                reads=merged,
                reason=f"The formula gives {_fmt(value)} but Fusion says {_fmt(expected)}.")
        if len(text) > MAX_FORMULA_LENGTH and merged:
            return Translation(reads=merged, reason="The formula is too long to copy.")
        out_dim = typed.dim if dim is None else dim
        return Translation(formula=text, reads=merged, dim=_DIM_NAMES.get(out_dim, "other"), value=value)

    def _derived_values(self):
        env = {e.size_name: e.value for e in self._entries.values() if e.state == FREE}
        out = {}
        for e in self._entries.values():
            if e.state == DERIVED and e.size_name:
                out[e.size_name] = self._eval_derived(e, {**env, **out})
        return out

    def _merge_reads(self, reads, expression):
        """Free sizes read: those met while translating, plus everything the names in the text depend on."""
        found = list(reads)
        for name in referenced_names(expression):
            found.extend(self.depends(name))
        return tuple(dict.fromkeys(found))

    def translate(self, expression, expected=None, dim=None, unit=""):
        """Fusion expression text to a Translation over the sizes.

        `expected` is the value Fusion reports, in mm or degrees; a formula that does not reach it is refused.
        `dim` ("length", "angle" or "scalar") and `unit` (Fusion unit text) are those of the value it sets; the formula
        is then scaled to that unit. Never raises. An expression that reads no free size still gets a formula; callers
        write its `value` instead.
        """
        return self._translate(expression, expected, _DIMS.get(dim), unit)

    def unit_of(self, name):
        """Fusion unit text of a user or model parameter, empty when unknown."""
        p = self._cand.get(name) or self.model_params.get(name) or {}
        return p.get("unit") or ""

    def depends(self, name):
        """Fusion names of the free sizes that a parameter (user or model) depends on, transitively.

        A free size depends on itself. An unknown name or a plain constant gives an empty set.
        """
        out = set()
        seen = set()
        stack = [name]
        while stack:
            current = stack.pop()
            if current in seen:
                continue
            seen.add(current)
            e = self._entries.get(current)
            if e is not None and e.state == FREE:
                out.add(current)
                continue
            p = self._cand.get(current) or self.model_params.get(current)
            if p is None:
                continue
            stack.extend(p.get("dependency_parameters", ()))
            stack.extend(referenced_names(p.get("expression", "")))
        return frozenset(out)

    # ---- queries ---------------------------------------------------------------------------------------------

    def entry(self, name):
        return self._entries.get(name)

    def size_name(self, name):
        """Recipe size name of a Fusion parameter that is a size, else None."""
        e = self._entries.get(name)
        return e.size_name or None if e is not None and e.state in (FREE, DERIVED) else None

    @property
    def ticked(self):
        """Fusion names kept as free sizes, in parameter order."""
        return [e.name for e in self.entries if e.state == FREE]

    @property
    def fixed(self):
        """[{ name, reason }] for the manifest: the recipe size name and the reason."""
        return [self.fixed_entry(e.name, e.reason) for e in self.entries if e.state == FIXED]

    def recipe_name(self, name):
        """The recipe size name of a Fusion parameter name. A name that is a recipe name already is kept."""
        if name in self._recipe_names:
            return self._recipe_names[name]
        if name in self._recipe_names.values():
            return name
        return names.sanitize(name)

    def fixed_entry(self, name, reason):
        """`{ name, reason }` of a fixed parameter for the manifest.

        `name` is the recipe size name (at most 64 characters). The reason holds the Fusion name when it differs.
        """
        recipe = self.recipe_name(name)
        text = " ".join(reason.split())
        if recipe != name and name not in text:
            text = "%s: %s" % (name, text)
        return {"name": recipe, "reason": text[:MAX_FIXED_REASON]}

    def with_fixed(self, reasons):
        """A new table where these Fusion names (reason text each) are fixed to their numbers."""
        merged = dict(self._fixed_in)
        merged.update(reasons)
        return SizeTable(self._params, [n for n in self._ticked_in if n not in merged], self._model,
                         self._design_unit, merged, self._quantity_params, self._ranges, self._max_sizes,
                         self._minimums, self._narrowed)

    def with_minimums(self, minimums):
        """A new table where these Fusion names (number each, in the size's own unit) start no lower than that."""
        merged = dict(self._minimums)
        merged.update(minimums)
        return SizeTable(self._params, self._ticked_in, self._model, self._design_unit, self._fixed_in,
                         self._quantity_params, self._ranges, self._max_sizes, merged, self._narrowed)

    def with_narrowed(self, ranges):
        """A new table where these Fusion names get the (min, max) given, in manifest numbers (mm, deg or plain).
        The export narrows a range at an end where Fusion cannot build the part. It is not a typed range."""
        merged = dict(self._narrowed)
        merged.update(ranges)
        return SizeTable(self._params, self._ticked_in, self._model, self._design_unit, self._fixed_in,
                         self._quantity_params, self._ranges, self._max_sizes, self._minimums, merged)

    def typed_ends(self, name):
        """(min typed, max typed) of a free size: the person set that end to another number than the default range
        (half to double, `defaults.default_range`), in the dialog or with a range comment. A range the export narrowed
        or a minimum the translator raised is not typed."""
        e = self._entries.get(name)
        if e is None or e.state != FREE:
            return False, False
        p = self._cand[name]
        lo, hi = self._ranges.get(name) or defaults.size_range(p, e.kind, e.value)
        base_lo, base_hi = defaults.default_range(e.kind, e.value)
        return abs(lo - base_lo) > VALUE_TOLERANCE, abs(hi - base_hi) > VALUE_TOLERANCE

    def typed_range(self, name):
        """True when the person typed either end of the range of this size (`typed_ends`)."""
        return any(self.typed_ends(name))

    def with_ticked(self, names):
        """A new table where these Fusion names are the ticked ones (the size cap still applies)."""
        return SizeTable(self._params, list(names), self._model, self._design_unit, self._fixed_in,
                         self._quantity_params, self._ranges, self._max_sizes, self._minimums, self._narrowed)

    def report(self):
        """Plain data for report.json: renames, derived formulas with their value check, fixed and unoffered names."""
        derived = {}
        env = self._derived_values()
        for e in self.entries:
            if e.state == DERIVED and e.size_name:
                derived[e.size_name] = {"from": e.expression, "formula": e.formula, "value": env.get(e.size_name),
                                        "fusion_value": e.value}
        return {
            "sizes": list(self.sizes),
            "renames": dict(self.renames),
            "derived": derived,
            "fixed": self.fixed,
            "not_offered": [{"name": e.name, "reason": e.reason} for e in self.entries if e.state == NOT_OFFERED],
        }


def _fmt(x):
    return ("%.6f" % x).rstrip("0").rstrip(".")


def build(params, ticked, model_params=(), design_unit="mm", fixed=None, quantity_params=(), ranges=None,
          max_sizes=MAX_SIZES):
    """SizeTable for the user parameters and the names ticked as sizes.

    `ranges` maps a Fusion name to the (min, max) the person typed; a ticked size without one gets its default range.
    `max_sizes` caps the named sizes (free and derived); past it a derived formula is written out where it is read.
    """
    return SizeTable(params, ticked, model_params, design_unit, fixed, quantity_params, ranges, max_sizes)
