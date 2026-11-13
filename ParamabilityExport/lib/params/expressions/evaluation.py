"""The value of a written formula over named numbers, to check it against the number Fusion reports."""
import math

from .errors import ExpressionError
from .formula import parse_formula
from .functions import APP_FUNCTIONS

_COMPARISONS = {
    "<": lambda a, b: a < b, "<=": lambda a, b: a <= b, ">": lambda a, b: a > b, ">=": lambda a, b: a >= b,
    "==": lambda a, b: a == b, "!=": lambda a, b: a != b,
}


def _truth(value):
    return 1.0 if value else 0.0


def eval_tree(node, env):
    kind = node[0]
    if kind == "num":
        return node[1]
    if kind == "name":
        if node[1] not in env:
            raise ExpressionError(f"Unknown name {node[1]}.")
        return float(env[node[1]])
    if kind == "neg":
        return -eval_tree(node[1], env)
    if kind == "not":
        return _truth(eval_tree(node[1], env) == 0)
    if kind == "cond":
        return eval_tree(node[2] if eval_tree(node[1], env) != 0 else node[3], env)
    if kind == "logic":
        left = eval_tree(node[2], env) != 0
        if left == (node[1] == "||"):
            return _truth(left)
        return _truth(eval_tree(node[3], env) != 0)
    if kind == "cmp":
        return _truth(_COMPARISONS[node[1]](eval_tree(node[2], env), eval_tree(node[3], env)))
    if kind == "call":
        entry = APP_FUNCTIONS.get(node[1])
        if entry is None:
            raise ExpressionError(f"Unknown function {node[1]}.")
        count, fn = entry
        args = [eval_tree(a, env) for a in node[2]]
        if len(args) < 2 if count is None else len(args) != count:
            raise ExpressionError(f"{node[1]} has the wrong number of values.")
        try:
            return float(fn(args))
        except (ValueError, OverflowError) as exc:
            raise ExpressionError(str(exc))
    a, b = eval_tree(node[2], env), eval_tree(node[3], env)
    if node[1] == "+":
        return a + b
    if node[1] == "-":
        return a - b
    if node[1] == "*":
        return a * b
    if b == 0:
        raise ExpressionError("Division by zero.")
    return a / b


def evaluate(formula, env):
    """Value of a written formula over `env` (name to number), with the app's function semantics.

    Reads what `render` writes. Only the branch a choice takes is worked out, as in the app.
    """
    return evaluate_tree(parse_formula(formula), env)


def evaluate_tree(tree, env):
    """Value of a parsed formula (`parse_formula`) over `env`, for a formula worked out at many settings."""
    value = eval_tree(tree, env)
    if math.isnan(value) or math.isinf(value):
        raise ExpressionError("The formula does not give a number.")
    return value
