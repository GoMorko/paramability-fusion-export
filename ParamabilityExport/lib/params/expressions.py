"""Fusion expression text to a formula in the app grammar (`@packages/expressions`).

The app grammar has `+ - * /`, calls of `abs ceil floor round sqrt min max pow` (and a few more) and no `^`.
A formula is written over size names with lengths in mm and angles in degrees, so `2 mm` becomes `2` and
`1 in` becomes `25.4`. Units are tracked as a pair of powers (length, angle) so that sums of unlike things refuse.

Unverified in Fusion: a bare number added to a length is read in the design's default length unit, and
`-a ^ b` binds as `-(a ^ b)`. Both are pinned by the value check, which compares the written formula with
the number Fusion reports.
"""
import math
import re
from collections import namedtuple

from ..package.units import ANGLE_UNITS, LENGTH_UNITS

# One operand while translating: the output node, its unit powers (length, angle) and whether it is a bare
# literal (a number typed without a unit, whose unit is read from the other side of a sum).
Typed = namedtuple("Typed", "node dim lit")

LENGTH_MM = {"mm": 1.0, "cm": 10.0, "m": 1000.0, "in": 25.4, "ft": 304.8, "um": 0.001}
ANGLE_DEG = {"deg": 1.0, "rad": 180.0 / math.pi}
_ANGLE_ALIAS = {"degree": "deg", "degrees": "deg", "radian": "rad", "radians": "rad"}

SCALAR = (0, 0)
LENGTH = (1, 0)
ANGLE = (0, 1)

_NUMBER = re.compile(r"(\d+\.?\d*|\.\d+)([eE][-+]?\d+)?")
_IDENT_CHAR = lambda c: c.isalnum() or c in "_$"  # noqa: E731

# Fusion function name -> (minimum args, maximum args or None)
_SAME_UNIT_FUNCTIONS = {"abs": (1, 1), "ceil": (1, 1), "floor": (1, 1), "round": (1, 1)}
_PICK_FUNCTIONS = {"min": (2, None), "max": (2, None)}


class ExpressionError(Exception):
    """The expression cannot be written as an app formula; the message is plain words for the person."""


def unit_factor(unit):
    """(dim, factor to mm or degrees) for a unit word, or None when it is not a length or angle unit."""
    u = unit.lower()
    u = _ANGLE_ALIAS.get(u, u)
    if u in LENGTH_MM and u in LENGTH_UNITS:
        return LENGTH, LENGTH_MM[u]
    if u in ANGLE_DEG and (u in ANGLE_UNITS or u in _ANGLE_ALIAS):
        return ANGLE, ANGLE_DEG[u]
    return None


# Tokens: ("num", value, unit or None), ("id", name), ("op", char), ("end",)

def tokenize(text):
    tokens = []
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c.isspace():
            i += 1
            continue
        if c.isdigit() or c == ".":
            m = _NUMBER.match(text, i)
            if not m:
                raise ExpressionError("A number could not be read.")
            value = float(m.group(0))
            i = m.end()
            j = i
            while j < n and text[j].isspace():
                j += 1
            k = j
            while k < n and _IDENT_CHAR(text[k]):
                k += 1
            word = text[j:k]
            unit = None
            if word:
                if unit_factor(word) is None:
                    raise ExpressionError(f"The unit \"{word}\" is not supported.")
                unit = word
                i = k
            tokens.append(("num", value, unit))
        elif c.isalpha() or c in "_$":
            k = i
            while k < n and _IDENT_CHAR(text[k]):
                k += 1
            tokens.append(("id", text[i:k]))
            i = k
        elif c in "+-*/^(),":
            tokens.append(("op", c))
            i += 1
        else:
            raise ExpressionError(f"The character \"{c}\" is not supported.")
    tokens.append(("end",))
    return tokens


# Parse tree: ("num", v, unit), ("name", s), ("neg", a), ("bin", op, a, b), ("call", f, args)

class _Parser:
    def __init__(self, tokens):
        self.t = tokens
        self.i = 0

    def peek(self):
        return self.t[self.i]

    def take(self):
        tok = self.t[self.i]
        self.i += 1
        return tok

    def is_op(self, ch):
        tok = self.peek()
        return tok[0] == "op" and tok[1] == ch

    def parse(self):
        node = self.sum()
        if self.peek()[0] != "end":
            raise ExpressionError("The expression has something extra at the end.")
        return node

    def sum(self):
        node = self.term()
        while self.is_op("+") or self.is_op("-"):
            op = self.take()[1]
            node = ("bin", op, node, self.term())
        return node

    def term(self):
        node = self.unary()
        while self.is_op("*") or self.is_op("/"):
            op = self.take()[1]
            node = ("bin", op, node, self.unary())
        return node

    def unary(self):
        if self.is_op("-"):
            self.take()
            return ("neg", self.unary())
        if self.is_op("+"):
            self.take()
            return self.unary()
        return self.power()

    def power(self):
        base = self.atom()
        if self.is_op("^"):
            self.take()
            return ("bin", "^", base, self.exponent())
        return base

    def exponent(self):
        if self.is_op("-"):
            self.take()
            return ("neg", self.exponent())
        if self.is_op("+"):
            self.take()
            return self.exponent()
        return self.power()

    def atom(self):
        tok = self.take()
        if tok[0] == "num":
            return ("num", tok[1], tok[2])
        if tok[0] == "id":
            if self.is_op("("):
                self.take()
                args = []
                if not self.is_op(")"):
                    args.append(self.sum())
                    while self.is_op(","):
                        self.take()
                        args.append(self.sum())
                if not self.is_op(")"):
                    raise ExpressionError("A bracket is not closed.")
                self.take()
                return ("call", tok[1], args)
            return ("name", tok[1])
        if tok == ("op", "("):
            node = self.sum()
            if not self.is_op(")"):
                raise ExpressionError("A bracket is not closed.")
            self.take()
            return node
        raise ExpressionError("The expression is not complete.")


def parse(text):
    return _Parser(tokenize(text)).parse()


def referenced_names(text):
    """Parameter names an expression reads, in order of first use. An unreadable expression gives an empty list."""
    try:
        tree = parse(text)
    except ExpressionError:
        return []
    out = []

    def walk(node):
        kind = node[0]
        if kind == "name":
            if node[1] not in out:
                out.append(node[1])
        elif kind == "neg":
            walk(node[1])
        elif kind == "bin":
            walk(node[2])
            walk(node[3])
        elif kind == "call":
            for a in node[2]:
                walk(a)

    walk(tree)
    return out


# Output nodes: ("num", v), ("name", s), ("neg", a), ("bin", op, a, b), ("call", f, args)

def format_number(value):
    """Number text with at most 9 decimals and no exponent."""
    if value == int(value) and abs(value) < 1e15:
        return str(int(value))
    text = ("%.9f" % value).rstrip("0").rstrip(".")
    return "0" if text in ("", "-0") else text


_PREC = {"+": 1, "-": 1, "*": 2, "/": 2}


def _prec(node):
    if node[0] == "bin":
        return _PREC[node[1]]
    if node[0] == "neg":
        return 3
    return 4


def render(node):
    kind = node[0]
    if kind == "num":
        return format_number(node[1])
    if kind == "name":
        return node[1]
    if kind == "neg":
        inner = render(node[1])
        return "-" + (inner if _prec(node[1]) == 4 else "(" + inner + ")")
    if kind == "call":
        return node[1] + "(" + ", ".join(render(a) for a in node[2]) + ")"
    op, left, right = node[1], node[2], node[3]
    p = _PREC[op]
    ltext = render(left)
    rtext = render(right)
    if _prec(left) < p:
        ltext = "(" + ltext + ")"
    if _prec(right) <= p and right[0] != "neg":
        rtext = "(" + rtext + ")"
    elif right[0] == "neg" and _prec(right) < p:
        rtext = "(" + rtext + ")"
    return f"{ltext} {op} {rtext}"


def _scale(node, factor):
    if factor == 1.0:
        return node
    if node[0] == "num":
        return ("num", node[1] * factor)
    return ("bin", "*", node, ("num", factor))


def _dim_add(a, b):
    return (a[0] + b[0], a[1] + b[1])


def _dim_sub(a, b):
    return (a[0] - b[0], a[1] - b[1])


def _align(a, b, design_mm):
    """Bring both operands of a sum or a min to one unit. Returns (node a, node b, dim, lit)."""
    if a.dim == b.dim:
        return a.node, b.node, a.dim, a.lit and b.lit
    for lit, other, flip in ((a, b, False), (b, a, True)):
        if lit.lit and lit.dim == SCALAR and other.dim in (LENGTH, ANGLE):
            factor = design_mm if other.dim == LENGTH else 1.0
            scaled = _scale(lit.node, factor)
            return (scaled, other.node, other.dim, False) if not flip else (other.node, scaled, other.dim, False)
    raise ExpressionError("A sum mixes values with different units.")


def _constant(node):
    """Value of an output node that holds numbers only, else None."""
    try:
        return evaluate(render(node), {})
    except ExpressionError:
        return None


def translate_tree(tree, resolve, design_mm=1.0):
    """Typed result for a parse tree. `resolve(name)` gives a Typed for a parameter or raises ExpressionError."""

    def go(node):
        kind = node[0]
        if kind == "num":
            if node[2] is None:
                return Typed(("num", node[1]), SCALAR, True)
            dim, factor = unit_factor(node[2])
            return Typed(("num", node[1] * factor), dim, False)
        if kind == "name":
            return resolve(node[1])
        if kind == "neg":
            a = go(node[1])
            return Typed(("neg", a.node), a.dim, a.lit)
        if kind == "call":
            return call(node[1], [go(a) for a in node[2]])
        op = node[1]
        a, b = go(node[2]), go(node[3])
        if op in "+-":
            an, bn, dim, lit = _align(a, b, design_mm)
            return Typed(("bin", op, an, bn), dim, lit)
        if op == "*":
            return Typed(("bin", "*", a.node, b.node), _dim_add(a.dim, b.dim), a.lit and b.lit)
        if op == "/":
            return Typed(("bin", "/", a.node, b.node), _dim_sub(a.dim, b.dim), a.lit and b.lit)
        return power(a, b)

    def power(a, b):
        if b.dim != SCALAR:
            raise ExpressionError("An exponent cannot have a unit.")
        if a.dim == SCALAR:
            return Typed(("call", "pow", [a.node, b.node]), SCALAR, a.lit and b.lit)
        n = _constant(b.node)
        if n is None or n != int(n):
            raise ExpressionError("A value with a unit can only be raised to a whole number.")
        n = int(n)
        return Typed(("call", "pow", [a.node, b.node]), (a.dim[0] * n, a.dim[1] * n), False)

    def call(name, args):
        if name in _SAME_UNIT_FUNCTIONS:
            lo, hi = _SAME_UNIT_FUNCTIONS[name]
            if not lo <= len(args) <= hi:
                raise ExpressionError(f"{name} needs {lo} value.")
            a = args[0]
            return Typed(("call", name, [a.node]), a.dim, a.lit)
        if name == "sqrt":
            if len(args) != 1:
                raise ExpressionError("sqrt needs 1 value.")
            a = args[0]
            if a.dim[0] % 2 or a.dim[1] % 2:
                raise ExpressionError("sqrt needs a value whose unit can be halved.")
            return Typed(("call", "sqrt", [a.node]), (a.dim[0] // 2, a.dim[1] // 2), a.lit)
        if name == "pow":
            if len(args) != 2:
                raise ExpressionError("pow needs 2 values.")
            return power(args[0], args[1])
        if name in _PICK_FUNCTIONS:
            if len(args) < 2:
                raise ExpressionError(f"{name} needs at least 2 values.")
            dims = {a.dim for a in args if not (a.lit and a.dim == SCALAR)}
            if len(dims) > 1:
                raise ExpressionError(f"{name} mixes values with different units.")
            dim = dims.pop() if dims else SCALAR
            factor = design_mm if dim == LENGTH else 1.0
            nodes = [_scale(a.node, factor) if (a.lit and a.dim == SCALAR and dim != SCALAR) else a.node for a in args]
            return Typed(("call", name, nodes), dim, all(a.lit for a in args))
        raise ExpressionError(f"The function \"{name}\" cannot be copied.")

    return go(tree)


# Evaluation of written formulas, to check them against the number Fusion reports.

_APP_FUNCTIONS = {
    "abs": abs,
    "ceil": math.ceil,
    "floor": math.floor,
    "round": lambda x: math.floor(x + 0.5),
    "sqrt": math.sqrt,
    "pow": math.pow,
    "min": min,
    "max": max,
}


def evaluate(formula, env):
    """Value of a written formula over `env` (name to number), with the app's function semantics.

    Reads only what `translate_tree` writes: numbers, names, `+ - * /`, unary minus and the calls above.
    """
    tokens = tokenize_formula(formula)
    pos = [0]

    def peek():
        return tokens[pos[0]]

    def take():
        pos[0] += 1
        return tokens[pos[0] - 1]

    def op(ch):
        return peek() == ("op", ch)

    def sum_():
        v = term()
        while op("+") or op("-"):
            o = take()[1]
            r = term()
            v = v + r if o == "+" else v - r
        return v

    def term():
        v = unary()
        while op("*") or op("/"):
            o = take()[1]
            r = unary()
            if o == "/":
                if r == 0:
                    raise ExpressionError("Division by zero.")
                v = v / r
            else:
                v = v * r
        return v

    def unary():
        if op("-"):
            take()
            return -unary()
        return atom()

    def atom():
        tok = take()
        if tok[0] == "num":
            return tok[1]
        if tok[0] == "id":
            if op("("):
                take()
                args = [sum_()]
                while op(","):
                    take()
                    args.append(sum_())
                if not op(")"):
                    raise ExpressionError("A bracket is not closed.")
                take()
                fn = _APP_FUNCTIONS.get(tok[1])
                if fn is None:
                    raise ExpressionError(f"Unknown function {tok[1]}.")
                try:
                    return float(fn(*args)) if tok[1] not in ("min", "max") else float(fn(args))
                except (ValueError, OverflowError, TypeError) as exc:
                    raise ExpressionError(str(exc))
            if tok[1] not in env:
                raise ExpressionError(f"Unknown name {tok[1]}.")
            return float(env[tok[1]])
        if tok == ("op", "("):
            v = sum_()
            if not op(")"):
                raise ExpressionError("A bracket is not closed.")
            take()
            return v
        raise ExpressionError("The formula is not complete.")

    value = sum_()
    if peek()[0] != "end":
        raise ExpressionError("The formula has something extra at the end.")
    return value


_FORMULA_TOKEN = re.compile(r"\s*(?:(\d+\.?\d*|\.\d+)([eE][-+]?\d+)?|([A-Za-z_][A-Za-z0-9_]*)|(.))")


def tokenize_formula(formula):
    """Tokens of an app formula: ("num", v), ("id", name), ("op", ch), ("end",)."""
    out = []
    pos = 0
    text = formula.rstrip()
    while pos < len(text):
        m = _FORMULA_TOKEN.match(text, pos)
        if not m:
            break
        pos = m.end()
        if m.group(1) is not None:
            out.append(("num", float(m.group(1) + (m.group(2) or ""))))
        elif m.group(3) is not None:
            out.append(("id", m.group(3)))
        else:
            out.append(("op", m.group(4)))
    out.append(("end",))
    return out
