"""Parse tree of a Fusion expression to a typed output node: units converted away, functions renamed."""
from collections import namedtuple

from .errors import ExpressionError
from .evaluation import evaluate
from .reading import parse
from .units import ANGLE, DEG_PER_RAD, SCALAR, unit_factor
from .writing import render

# One operand while translating: the output node, its unit powers (length, angle) and whether it is a bare
# literal (a number typed without a unit, whose unit is read from the other side of a sum).
Typed = namedtuple("Typed", "node dim lit")

# Fusion function names by how they translate. Names are matched without case.
_SAME_UNIT_FUNCTIONS = ("abs", "ceil", "floor", "round")
_TRIG = ("sin", "cos", "tan")
_INVERSE_TRIG = ("asin", "acos", "atan")
_HYPERBOLIC = ("sinh", "cosh", "tanh")
_INVERSE_HYPERBOLIC = ("asinh", "acosh", "atanh")
_PLAIN = ("exp", "ln", "log")
_PICK_FUNCTIONS = ("min", "max")


def scale_node(node, factor):
    """The output node times `factor` (radians to degrees is written as `* 180 / pi()`)."""
    if factor == 1.0:
        return node
    if node[0] == "num":
        return ("num", node[1] * factor)
    if factor == DEG_PER_RAD:
        return ("bin", "/", ("bin", "*", node, ("num", 180.0)), ("call", "pi", []))
    return ("bin", "*", node, ("num", factor))


def _mul(a, b):
    if b == ("num", 1.0):
        return a
    if a == ("num", 1.0):
        return b
    return ("bin", "*", a, b)


def _div(a, b):
    return a if b == ("num", 1.0) else ("bin", "/", a, b)


def _dim_add(a, b):
    return (a[0] + b[0], a[1] + b[1])


def _dim_sub(a, b):
    return (a[0] - b[0], a[1] - b[1])


def _bare_factor(dim, design_mm):
    """Factor of a number without a unit that stands next to a value of `dim`: the design's length unit for a
    length (squared for an area), degrees for an angle."""
    return design_mm ** dim[0]


def _align(a, b, design_mm):
    """Bring two operands to one unit. Returns (node a, node b, dim, lit).

    A value without a unit takes the unit of the other side. Two different units are kept as written.
    """
    if a.dim == b.dim:
        return a.node, b.node, a.dim, a.lit and b.lit
    if a.dim == SCALAR:
        return scale_node(a.node, _bare_factor(b.dim, design_mm)), b.node, b.dim, False
    if b.dim == SCALAR:
        return a.node, scale_node(b.node, _bare_factor(a.dim, design_mm)), a.dim, False
    return a.node, b.node, a.dim, False


def _constant(node):
    """Value of an output node that holds numbers only, else None."""
    try:
        return evaluate(render(node), {})
    except ExpressionError:
        return None


def _folded(node):
    """The node as one number when it holds numbers only."""
    value = _constant(node)
    return node if value is None else ("num", value)


def _radians(node):
    """An angle node in degrees as radians."""
    return ("bin", "/", ("bin", "*", node, ("call", "pi", [])), ("num", 180.0))


def _exp(node):
    return ("call", "exp", [node])


def _hyperbolic(name, x):
    """sinh, cosh or tanh of a node in radians, written with exp (the app has no hyperbolic functions)."""
    if name == "tanh":
        e2 = _exp(("bin", "*", ("num", 2.0), x))
        return ("bin", "/", ("bin", "-", e2, ("num", 1.0)), ("bin", "+", e2, ("num", 1.0)))
    return ("bin", "/", ("bin", "-" if name == "sinh" else "+", _exp(x), _exp(("neg", x))), ("num", 2.0))


def _inverse_hyperbolic(name, x):
    """asinh, acosh or atanh of a node, in radians, written with ln and sqrt."""
    if name == "atanh":
        ratio = ("bin", "/", ("bin", "+", ("num", 1.0), x), ("bin", "-", ("num", 1.0), x))
        return ("bin", "/", ("call", "ln", [ratio]), ("num", 2.0))
    square = ("bin", "+" if name == "asinh" else "-", ("bin", "*", x, x), ("num", 1.0))
    return ("call", "ln", [("bin", "+", x, ("call", "sqrt", [square]))])


def translate_tree(tree, resolve, design_mm=1.0, modulo=None):
    """Typed result for a parse tree. `resolve(name)` gives a Typed for a parameter or raises ExpressionError.

    `modulo`, when given, collects the left operand node of every `%`: the app's `mod` takes the sign of its right
    operand, so a caller that cannot tell what Fusion does for a negative left operand checks those nodes."""

    def go(node):
        kind = node[0]
        if kind == "num":
            return Typed(("num", node[1]), SCALAR, True)
        if kind == "name":
            return resolve(node[1])
        if kind == "const":
            return Typed(("call", "exp", [("num", 1.0)]) if node[1] == "E" else ("call", "pi", []), SCALAR, True)
        if kind == "unitword":
            dim, factor = unit_factor(node[1])
            return Typed(("num", factor), dim, False)
        if kind == "unit":
            a = go(node[1])
            dim, factor = unit_factor(node[2], loose=True)
            value = _constant(a.node)
            out = ("num", value * factor) if value is not None else scale_node(a.node, factor)
            return Typed(out, _dim_add(a.dim, dim), False)
        if kind == "neg":
            a = go(node[1])
            return Typed(("neg", a.node), a.dim, a.lit)
        if kind == "not":
            return Typed(("not", go(node[1]).node), SCALAR, False)
        if kind == "logic":
            return Typed(("logic", node[1], go(node[2]).node, go(node[3]).node), SCALAR, False)
        if kind == "cmp":
            an, bn, _, _ = _align(go(node[2]), go(node[3]), design_mm)
            return Typed(("cmp", node[1], an, bn), SCALAR, False)
        if kind == "call":
            return call(node[1], [go(a) for a in node[2]])
        op = node[1]
        a, b = go(node[2]), go(node[3])
        if op in "+-":
            an, bn, dim, lit = _align(a, b, design_mm)
            return Typed(("bin", op, an, bn), dim, lit)
        if op == "%":
            an, bn, dim, lit = _align(a, b, design_mm)
            if modulo is not None:
                modulo.append(an)
            return Typed(("call", "mod", [an, bn]), dim, lit)
        if op == "*":
            return Typed(_mul(a.node, b.node), _dim_add(a.dim, b.dim), a.lit and b.lit)
        if op == "/":
            return Typed(_div(a.node, b.node), _dim_sub(a.dim, b.dim), a.lit and b.lit)
        return power(a, b)

    def power(a, b):
        if a.dim == SCALAR:
            return Typed(("call", "pow", [a.node, b.node]), SCALAR, a.lit and b.lit)
        n = _constant(b.node)
        dim = a.dim if n is None else (a.dim[0] * n, a.dim[1] * n)
        return Typed(("call", "pow", [a.node, b.node]), dim, False)

    def need(name, args, count):
        if len(args) != count:
            raise ExpressionError(f"{name} needs {count} value{'s' if count != 1 else ''}.")

    def call(name, args):
        if name in _SAME_UNIT_FUNCTIONS:
            need(name, args, 1)
            a = args[0]
            return Typed(("call", name, [a.node]), a.dim, a.lit)
        if name in _TRIG:
            need(name, args, 1)
            return Typed(("call", name, [args[0].node]), SCALAR, False)
        if name in _INVERSE_TRIG:
            need(name, args, 1)
            return Typed(("call", name, [args[0].node]), ANGLE, False)
        if name in _HYPERBOLIC:
            need(name, args, 1)
            return Typed(_folded(_hyperbolic(name, _folded(_radians(args[0].node)))), SCALAR, False)
        if name in _INVERSE_HYPERBOLIC:
            need(name, args, 1)
            return Typed(_folded(scale_node(_inverse_hyperbolic(name, args[0].node), DEG_PER_RAD)), ANGLE, False)
        if name in _PLAIN:
            need(name, args, 1)
            return Typed(("call", name, [args[0].node]), SCALAR, False)
        if name == "sign":
            # Fusion's sign gives 1 above zero and 0 otherwise.
            need(name, args, 1)
            return Typed(("cmp", ">", args[0].node, ("num", 0.0)), SCALAR, False)
        if name == "sqrt":
            need(name, args, 1)
            a = args[0]
            return Typed(("call", "sqrt", [a.node]), (a.dim[0] / 2, a.dim[1] / 2), a.lit)
        if name == "pow":
            need(name, args, 2)
            return power(args[0], args[1])
        if name == "if":
            need(name, args, 3)
            an, bn, dim, lit = _align(args[1], args[2], design_mm)
            return Typed(("cond", args[0].node, an, bn), dim, lit)
        if name in _PICK_FUNCTIONS:
            if len(args) < 2:
                raise ExpressionError(f"{name} needs at least 2 values.")
            dim = next((a.dim for a in args if a.dim != SCALAR), SCALAR)
            factor = _bare_factor(dim, design_mm)
            nodes = [scale_node(a.node, factor) if a.dim == SCALAR else a.node for a in args]
            return Typed(("call", name, nodes), dim, all(a.lit for a in args))
        if name == "random":
            raise ExpressionError("A random number cannot be copied.")
        raise ExpressionError(f"The function \"{name}\" cannot be copied.")

    return go(tree)


_NO_UNIT = ("", "unitless", "no units")


def _no_names(name):
    raise ExpressionError(f"\"{name}\" is not a unit.")


def unit_scale(unit):
    """(dim, mm or degrees in one of it) of a parameter unit: `mm`, `in`, `deg`, or one built from them such as
    `mm^2`. (SCALAR, 1) for no unit; None for a unit with other words (mass, time)."""
    text = (unit or "").strip()
    if text.lower() in _NO_UNIT:
        return SCALAR, 1.0
    found = unit_factor(text, loose=True)
    if found is not None:
        return found
    try:
        typed = translate_tree(parse(text), _no_names)
    except ExpressionError:
        return None
    value = _constant(typed.node)
    if value is None or value <= 0 or typed.lit or typed.dim == SCALAR:
        return None
    return typed.dim, value
