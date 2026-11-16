"""Sketch dimensions over the sizes of an export, and the size settings a sketch is tried at. Pure numbers and formulas.

A dimension's model parameter (`d16`) has an expression over user parameters. `dimension_formulas` turns each into a
formula over recipe size names, the way the translators write formulas, so two dimensions that read one size move
together. `override_sets` makes the size settings a sketch is solved and fitted at: each size it reads a quarter below
and above its value (`near_values`), then all of them low and all of them high. `size_values` gives every size value
at one setting, the derived sizes included. The probe's shadow check (`probe/derived.py`) and the Orca output
(`orca_translate/sketches.py`) both read these.
"""
from ..geometry.tolerances import SAME_SIZE
from ..params import defaults
from ..params.expressions.errors import ExpressionError
from ..params.expressions.evaluation import evaluate
from ..params.expressions.formula import parse_formula
from ..params.expressions.units import ANGLE, LENGTH, SCALAR
from ..params.size_table import DERIVED, FREE
from ..sketch_values import expr as ex

# Sizes a sketch is moved by at most: each costs two settings in the solver.
MAX_SIZES = 12
# How far from its value a size is first tried, as a share of the value, below and above.
NEAR_SHARE = 0.25
_DIM_NAMES = {LENGTH: "length", ANGLE: "angle", SCALAR: "scalar"}
_FUNCTIONS = {"sqrt": ex.sqrt, "sin": ex.sin, "cos": ex.cos, "tan": ex.tan}


class Formula:
    """One dimension's expression over size names: `text` as the translator writes it, `expr` the same as an `Expr`
    (None when it uses something an `Expr` cannot hold), `reads` the Fusion names of the free sizes it follows. Without
    `text`, `reason` says why the expression could not be written."""

    def __init__(self, text="", expr=None, reads=(), reason=""):
        self.text, self.expr, self.reads, self.reason = text, expr, tuple(reads), reason

    @property
    def usable(self):
        return bool(self.text)


def expr_of(formula):
    """The `Expr` of a written formula (numbers, names, `+ - * /`, negation, `sqrt`, `sin`, `cos`, `tan`); raises
    `ExpressionError` for anything else."""
    def go(node):
        kind = node[0]
        if kind == "num":
            return ex.num(node[1])
        if kind == "name":
            return ex.name(node[1])
        if kind == "neg":
            return -go(node[1])
        if kind == "bin":
            a, b = go(node[2]), go(node[3])
            return a + b if node[1] == "+" else a - b if node[1] == "-" else a * b if node[1] == "*" else a / b
        if kind == "call" and node[1] in _FUNCTIONS and len(node[2]) == 1:
            return _FUNCTIONS[node[1]](go(node[2][0]))
        raise ExpressionError("The formula uses more than an Expr holds.")
    try:
        return go(parse_formula(formula))
    except ex.ExprDomainError as error:
        raise ExpressionError(str(error))


def _unit_of(table, dimension):
    model = table.model_params.get(dimension.get("param"))
    if model is not None:
        return model.get("unit") or ""
    return "deg" if dimension.get("type") == "angular" else "mm"


def dimension_formulas(table, record):
    """`{ parameter name: Formula }` for each driving dimension of a sketch graph record that has a parameter, an
    expression and a value. The value Fusion measured is the number the formula must give at the current sizes."""
    out = {}
    for dimension in record.get("dimensions") or []:
        param, expression, value = dimension.get("param"), dimension.get("expression"), dimension.get("value")
        if (not param or not isinstance(expression, str) or dimension.get("driving") is False
                or not isinstance(value, (int, float)) or isinstance(value, bool)):
            continue
        unit = _unit_of(table, dimension)
        dim = _DIM_NAMES.get(defaults.dim_of_unit(unit))
        found = table.translate(expression, expected=float(value), dim=dim, unit=unit)
        if not found.ok:
            out[param] = Formula(reason=found.reason or "the expression could not be written")
            continue
        try:
            out[param] = Formula(found.formula, expr_of(found.formula), found.reads)
        except ExpressionError:
            out[param] = Formula(found.formula, None, found.reads)
    return out


def moving_sizes(table, formulas):
    """The free sizes the formulas read, as `near_values` takes them, in table order, at most `MAX_SIZES`."""
    reads = {name for f in formulas.values() for name in f.reads}
    out = []
    for e in table.entries:
        if e.state == FREE and e.name in reads and e.size_name in table.sizes:
            size = table.sizes[e.size_name]
            out.append({"param": e.name, "value": size["value"], "min": size["min"], "max": size["max"],
                        "kind": size.get("kind")})
    return out[:MAX_SIZES]


def override_sets(sizes):
    """Size settings as `{ Fusion name: manifest number }`: each size a quarter below and above its value (one at a
    time), then every size low and every size high when there are two or more."""
    out, near = [], {s["param"]: near_values(s) for s in sizes}
    for size in sizes:
        out.extend({size["param"]: v} for v in near[size["param"]] if v is not None)
    if len(sizes) >= 2:
        for side in (0, 1):
            moved = {s["param"]: near[s["param"]][side] for s in sizes if near[s["param"]][side] is not None}
            if len(moved) >= 2:
                out.append(moved)
    return out


def near_values(size):
    """`(low, high)`: the value `NEAR_SHARE` of itself below and above, inside the range. A value of zero moves by that
    share of the way to the range ends. A count is a whole number and at least one step from the value. A side that
    cannot move off the value is None."""
    value, lo, hi = size["value"], size["min"], size["max"]
    step = NEAR_SHARE * abs(value)
    sides = [value - step, value + step] if step > SAME_SIZE else [value + NEAR_SHARE * (lo - value),
                                                                 value + NEAR_SHARE * (hi - value)]
    out = []
    for number, sign in zip(sides, (-1, 1)):
        if size.get("kind") == "count":
            number = float(round(number))
            if abs(number - value) <= SAME_SIZE:
                number = value + sign
        number = min(max(number, lo), hi)
        out.append(number if abs(number - value) > SAME_SIZE else None)
    return tuple(out)


def size_values(table, overrides):
    """`(env, derived)`: size values by recipe name (free sizes with `overrides`, then the named derived ones) and the
    value of every derived user parameter by Fusion name (None where its formula fails)."""
    env = {e.size_name: overrides.get(e.name, e.value) for e in table.entries if e.state == FREE}
    derived = {}
    pending = [e for e in table.entries if e.state == DERIVED]
    while pending:
        later = []
        for e in pending:
            try:
                derived[e.name] = evaluate(e.formula, env)
            except ExpressionError:
                later.append(e)
                continue
            if e.size_name:
                env[e.size_name] = derived[e.name]
        if len(later) == len(pending):
            derived.update({e.name: None for e in later})
            break
        pending = later
    return env, derived


def size_env(table, overrides):
    """Size values by recipe name at `overrides` (Fusion name to number), the derived sizes included."""
    return size_values(table, overrides)[0]


def leaf_values(formulas, env):
    """`{ parameter name: number }` of each dimension at the size values `env`; a dimension whose formula cannot be
    worked out there is left out."""
    out = {}
    for name, formula in formulas.items():
        if not formula.usable:
            continue
        try:
            out[name] = evaluate(formula.text, env)
        except ExpressionError:
            continue
    return out
