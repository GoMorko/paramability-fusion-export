"""The sizes of one export: which Fusion parameters become recipe sizes, and the translation of expressions over them.

    table = size_table.build(params, ticked)

`params` are the user parameters as read by `fusion_reader.parameters.list_user_parameters` (Fusion internal values:
cm, rad). `ticked` are the Fusion names the person keeps as sizes. Optional keywords: `model_params` (the body's model
parameters, for inlining, counts and defaults), `design_unit` (what a bare number in a length expression means),
`fixed` (ticked names that cannot follow, with the reason; they become plain numbers), `quantity_params` (the model
parameters the steps use as a pattern quantity; the user parameters behind them become whole-number counts).

The table holds, per parameter, one entry whose `state` is:

- `free`: a plain number kept as a size (`table.sizes[recipe_name]` has `kind`, `value`, `min`, `max`, `label`);
- `derived`: a formula over other sizes (`{ expr, label }`);
- `constant`: a plain number that is not a size; every formula that reads it holds its number;
- `fixed`: fixed with a reason (shown unticked and greyed); it is not a size of the recipe;
- `not_offered`: a unit or formula that cannot be copied (the reason is kept).

`translate(expression)` turns a Fusion expression (a feature value read from a model parameter) into a formula over
the sizes; `depends(name)` lists the free sizes a parameter or an expression name depends on, which is what the
driver fixes when a value cannot follow.
"""
from dataclasses import dataclass

from ..package.manifest import MAX_FIXED_REASON
from . import defaults, names
from .expressions import (
    ANGLE, LENGTH, LENGTH_MM, MAX_FORMULA_LENGTH, SCALAR, ExpressionError, Typed, evaluate, parse, referenced_names,
    render, translate_tree)

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
    formula: str = ""  # written formula of a derived entry
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


def _round(x):
    return round(x, 9)


class SizeTable:
    def __init__(self, params, ticked, model_params=(), design_unit="mm", fixed=None, quantity_params=()):
        self._params = [p for p in params]
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
            if e.state in (FREE, DERIVED):
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
        if p.get("kind") not in ("length", "angle", "count") or defaults.dim_of_unit(p.get("unit")) is None:
            return Entry(p["name"], NOT_OFFERED, label=label, reason=f"The unit \"{p.get('unit')}\" is not supported.")
        value = _round(defaults.size_value(p))
        kind = defaults.size_kind(p, counts)
        base = dict(name=p["name"], label=label, kind=kind, value=value)
        if p["name"] in self._fixed_in:
            return Entry(state=FIXED, size_name=self._recipe_names[p["name"]], reason=self._fixed_in[p["name"]],
                         **base)
        if p["name"] in ticked:
            if free_count >= MAX_SIZES:
                return Entry(state=CONSTANT, reason=f"{MAX_SIZES} is the most sizes.", **base)
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
        if defaults.dim_of_unit(p.get("unit")) is None:
            entry = Entry(state=NOT_OFFERED, reason=f"The unit \"{p.get('unit')}\" is not supported.", **base)
            self._entries[name] = entry
            return entry
        self._active.add(name)
        try:
            tr = self._translate(p["expression"], expected=base["value"], dim=defaults.dim_of_unit(p.get("unit")))
        finally:
            self._active.discard(name)
        if not tr.ok:
            entry = Entry(state=NOT_OFFERED, reads=tr.reads, reason=tr.reason, **base)
        elif not tr.reads:
            entry = Entry(state=CONSTANT, **base)
        elif len(tr.formula) > MAX_FORMULA_LENGTH:
            entry = Entry(state=NOT_OFFERED, reads=tr.reads, reason="The formula is too long to copy.", **base)
        elif sum(1 for e in self._entries.values() if e.state in (FREE, DERIVED)) >= MAX_SIZES:
            entry = Entry(state=CONSTANT, reason=f"{MAX_SIZES} is the most sizes.", **base)
        else:
            entry = Entry(state=DERIVED, size_name=self._recipe_names[name], formula=tr.formula, reads=tr.reads, **base)
        self._entries[name] = entry
        return entry

    def _size_dict(self, e):
        if e.state == DERIVED:
            return {"expr": e.formula, "label": e.label}
        p = self._cand[e.name]
        lo, hi = defaults.size_range(p, e.kind, e.value)
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
                    raise ExpressionError(f"\"{name}\" has a unit that cannot be copied.")
                e = self._entries.get(name) or self._derived_entry(name)
                if e.state == FREE:
                    reads.append(name)
                    return Typed(("name", e.size_name), dim, False)
                if e.state == DERIVED:
                    reads.extend(e.reads)
                    return Typed(("name", e.size_name), dim, False)
                if e.state == NOT_OFFERED and p.get("kind") == "derived":
                    reads.extend(e.reads)
                    raise ExpressionError(f"\"{name}\" cannot be copied: {e.reason}")
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
                return inner
            raise ExpressionError(f"\"{name}\" is not a parameter that can be copied.")
        return resolve

    def _translate(self, expression, expected=None, dim=None):
        reads = []
        try:
            tree = parse(expression)
            typed = translate_tree(tree, self._resolver(reads, []), self._design_mm)
            if dim is not None and not typed.lit and typed.dim != dim:
                raise ExpressionError("The formula does not give the unit of its parameter.")
            text = render(typed.node)
        except ExpressionError as exc:
            return Translation(reads=self._merge_reads(reads, expression), reason=str(exc))
        merged = self._merge_reads(reads, expression)
        env = {e.size_name: e.value for e in self._entries.values() if e.state == FREE}
        env.update(self._derived_values())
        try:
            value = evaluate(text, env)
        except ExpressionError as exc:
            return Translation(reads=merged, reason=str(exc))
        if expected is not None and abs(value - expected) > VALUE_TOLERANCE + 1e-9 * abs(expected):
            return Translation(
                reads=merged,
                reason=f"The formula gives {_fmt(value)} but Fusion says {_fmt(expected)}.")
        if len(text) > MAX_FORMULA_LENGTH and merged:
            return Translation(reads=merged, reason="The formula is too long to copy.")
        return Translation(formula=text, reads=merged, dim=_DIM_NAMES.get(typed.dim, "other"), value=value)

    def _derived_values(self):
        env = {e.size_name: e.value for e in self._entries.values() if e.state == FREE}
        out = {}
        for e in self._entries.values():
            if e.state == DERIVED:
                out[e.size_name] = self._eval_derived(e, {**env, **out})
        return out

    def _merge_reads(self, reads, expression):
        """Free sizes read: those met while translating, plus everything the names in the text depend on."""
        found = list(reads)
        for name in referenced_names(expression):
            found.extend(self.depends(name))
        return tuple(dict.fromkeys(found))

    def translate(self, expression, expected=None):
        """Fusion expression text to a Translation over the sizes.

        `expected` is the value Fusion reports, in mm or degrees; a formula that does not reach it is refused.
        Never raises. An expression that reads no free size still gets a formula; callers write its `value` instead.
        """
        return self._translate(expression, expected)

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
        return e.size_name if e is not None and e.state in (FREE, DERIVED) else None

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
                         self._design_unit, merged, self._quantity_params)

    def report(self):
        """Plain data for report.json: renames, derived formulas with their value check, fixed and unoffered names."""
        derived = {}
        env = self._derived_values()
        for e in self.entries:
            if e.state == DERIVED:
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


def build(params, ticked, model_params=(), design_unit="mm", fixed=None, quantity_params=()):
    """SizeTable for the user parameters and the names ticked as sizes."""
    return SizeTable(params, ticked, model_params, design_unit, fixed, quantity_params)
