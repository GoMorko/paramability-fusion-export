"""App formulas (the size table's language) to OrcaSlicer 2.5 formulas, and Orca variable names.

Orca reads `+ - * /`, brackets, unary minus, numbers written with digits and a point (no exponent), names of other
variables, `pi` and the functions `sqrt abs sin cos tan min max deg rad` (one argument each, `min` and `max` two),
angles in degrees (`eval_expr` in Orca's CadDocument.cpp). A name is a letter or `_` followed by letters, digits and
`_`. Anything else in an app formula (a choice, a comparison, `round`, `mod`, `pow` of a non whole power) has no
Orca form: `OrcaFormulaError` says why and the caller writes the number instead.
"""
import math
import re

from ..params.expressions.errors import ExpressionError
from ..params.expressions.evaluation import evaluate
from ..params.expressions.formula import parse_formula
from ..params.expressions.text import format_number
from ..params.expressions.writing import render

# Names Orca reads as a constant or a function, so a variable may not take them.
RESERVED = frozenset({"pi", "sqrt", "abs", "sin", "cos", "tan", "min", "max", "deg", "rad"})
_ONE_ARGUMENT = ("sqrt", "abs", "sin", "cos", "tan")
_PICK = ("min", "max")
# A power written out as a product, up to this whole power.
MAX_POWER = 4
_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class OrcaFormulaError(ValueError):
    """An app formula that has no Orca form; the message is one plain sentence."""


def orca_number(value):
    """The text of a number as Orca reads it in a formula or a variable: digits with at most one point and 9
    decimals, a minus in front when below zero, never an exponent. Orca's reader (`eval_expr` in CadDocument.cpp)
    takes a number as a run of digits and points only, so "1e-05" would read as 1 followed by a name `e`. Every
    number the Orca copy writes as text, or tests as a variable value, goes through here. Raises OrcaFormulaError
    for a number that is not finite."""
    value = float(value)
    if not math.isfinite(value):
        raise OrcaFormulaError("It holds a number that is not finite.")
    return format_number(value)


def variable_names(size_names):
    """`{size name: Orca variable name}`: the same spelling, except a name Orca keeps for itself gets `_v` (and a
    number when that is taken)."""
    taken = set(size_names)
    out = {}
    for name in size_names:
        found = name
        if found in RESERVED or not _NAME.match(found):
            base = re.sub(r"[^A-Za-z0-9_]", "_", found) or "v"
            base = base if _NAME.match(base) else "v_" + base
            found, n = base + "_v", 2
            while found in taken:
                found, n = "%s_v%d" % (base, n), n + 1
        taken.add(found)
        out[name] = found
    return out


def _orca_tree(node, rename):
    """The app output tree `node` in the forms Orca reads, names renamed; raises OrcaFormulaError."""
    kind = node[0]
    if kind == "num":
        if not math.isfinite(node[1]):
            raise OrcaFormulaError("It holds a number that is not finite.")
        return node
    if kind == "name":
        return ("name", rename(node[1]))
    if kind == "neg":
        return ("neg", _orca_tree(node[1], rename))
    if kind == "bin":
        return ("bin", node[1], _orca_tree(node[2], rename), _orca_tree(node[3], rename))
    if kind == "call":
        name, args = node[1], node[2]
        if name == "pi" and not args:
            return ("name", "pi")
        if name in _ONE_ARGUMENT and len(args) == 1:
            return ("call", name, [_orca_tree(args[0], rename)])
        if name in _PICK and len(args) >= 2:
            parts = [_orca_tree(a, rename) for a in args]
            out = parts[-1]
            for part in reversed(parts[:-1]):
                out = ("call", name, [part, out])
            return out
        if name == "pow" and len(args) == 2 and args[1][0] == "num" and args[1][1] == int(args[1][1]) \
                and 1 <= args[1][1] <= MAX_POWER:
            base = _orca_tree(args[0], rename)
            out = base
            for _ in range(int(args[1][1]) - 1):
                out = ("bin", "*", out, base)
            return out
        raise OrcaFormulaError("Orca formulas cannot %s." % _CANNOT.get(name, "do one of the steps of this formula"))
    raise OrcaFormulaError("Orca formulas cannot %s." % _CANNOT.get(kind, "do one of the steps of this formula"))


# What an Orca formula cannot do, by the app function or the kind of step, in plain words.
_CANNOT = {
    "ceil": "round a number up", "floor": "round a number down", "round": "round a number",
    "mod": "take the rest of a division", "pow": "raise a number to a power other than 1, 2, 3 or 4",
    "acos": "work out an angle from a ratio", "asin": "work out an angle from a ratio",
    "atan": "work out an angle from a ratio", "atan2": "work out an angle from a ratio",
    "exp": "use powers of e", "ln": "use logarithms", "log": "use logarithms",
    "sign": "tell whether a number is above or below zero", "clamp": "keep a number between two limits",
    "cond": "choose between two values (if)", "cmp": "compare two values", "logic": "join conditions (and, or)",
    "not": "turn a condition around (not)",
}


def to_orca(formula, names):
    """The Orca text of an app formula. `names` maps each size name it reads to its Orca variable name; a name not in
    it raises OrcaFormulaError (the formula reads something that is no variable)."""
    def rename(name):
        if name not in names:
            raise OrcaFormulaError("It reads %s, which is not an Orca variable." % name)
        return names[name]
    try:
        tree = parse_formula(formula)
    except ExpressionError as exc:
        raise OrcaFormulaError(str(exc))
    return render(_orca_tree(tree, rename), orca_number)


def orca_value(text, env):
    """The number of an Orca formula over `env` (name to number), worked out as Orca does: angles in degrees and `pi`
    a constant. For checks; raises ExpressionError."""
    app = re.sub(r"\bpi\b(?!\s*\()", "pi()", text)
    return evaluate(app, env)


def variable_values(variables):
    """`{name: number}` of Orca variables (name to formula), each worked out after the ones it reads. Raises
    ExpressionError for a cycle or a name that is not there, as Orca does."""
    done, busy = {}, set()

    def value(name):
        if name in done:
            return done[name]
        if name in busy or name not in variables:
            raise ExpressionError("The variable %s cannot be worked out." % name)
        busy.add(name)
        reads = {n for n in re.findall(r"[A-Za-z_][A-Za-z0-9_]*", variables[name]) if n not in RESERVED}
        done[name] = orca_value(variables[name], {n: value(n) for n in reads})
        busy.discard(name)
        return done[name]

    for name in variables:
        value(name)
    return done
