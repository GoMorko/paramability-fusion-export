"""Fusion expression text to a formula in the app grammar (`@packages/expressions`).

Fusion writes `;` between function arguments, `^` for powers, `%` for the remainder, `<>` for not equal, the words
`and`, `or`, `not`, and `if(test; a; b)`. The app formula writes `,`, `pow`, `mod`, `!=`, `&& || !` and
`test ? a : b`. A formula is a number over size names with lengths in mm and angles in degrees, so every unit is
converted away: `2 mm` becomes `2`, `1 in` becomes `25.4` and `w / mm` becomes `w`. Units are tracked as a pair of
powers (length, angle) only to convert numbers: Fusion already refuses expressions whose units do not fit, so a mix
of units is written as it stands. docs/expressions.md has the full table.

Unverified in Fusion: a number without a unit added to a length is read in the design's default length unit, a value
without a unit in an angle position is read in degrees, and `-a ^ b` binds as `-(a ^ b)`. The value check compares
the written formula with the number Fusion reports, so a wrong guess is caught instead of writing a wrong formula.
"""
import math
import re
from collections import namedtuple

from ..package.units import unit_kind

# One operand while translating: the output node, its unit powers (length, angle) and whether it is a bare
# literal (a number typed without a unit, whose unit is read from the other side of a sum).
Typed = namedtuple("Typed", "node dim lit")

# Parameter units, and the design's default length unit, in mm.
LENGTH_MM = {"mm": 1.0, "cm": 10.0, "m": 1000.0, "in": 25.4, "ft": 304.8, "um": 0.001}
DEG_PER_RAD = 180.0 / math.pi

# Unit words Fusion reads in an expression, in mm or degrees.
_LENGTH_WORDS = dict(LENGTH_MM, **{
    "millimeter": 1.0, "centimeter": 10.0, "meter": 1000.0, "hm": 100000.0, "micron": 0.001, "µ": 0.001,
    "inch": 25.4, '"': 25.4, "foot": 304.8, "yd": 914.4, "yard": 914.4, "mi": 1609344.0, "mile": 1609344.0,
    "mil": 0.0254, "nauticalMile": 1852000.0,
})
_ANGLE_WORDS = {
    "deg": 1.0, "degree": 1.0, "degrees": 1.0, "°": 1.0, "˚": 1.0, "grad": 0.9,
    "rad": DEG_PER_RAD, "radian": DEG_PER_RAD, "radians": DEG_PER_RAD,
}
_LOOSE_WORDS = {w.lower(): w for w in list(_LENGTH_WORDS) + list(_ANGLE_WORDS)}

# Longest formula text the app accepts in a recipe.
MAX_FORMULA_LENGTH = 300

SCALAR = (0, 0)
LENGTH = (1, 0)
ANGLE = (0, 1)

_NUMBER = re.compile(r"(\d+\.?\d*|\.\d+)([eE][-+]?\d+)?")


def _ident_char(c):
    """Letters, digits and the symbols Fusion allows in names and unit words (`$ " ° µ`)."""
    return c.isalnum() or c in "_$\"°˚"


_TWO_CHAR_OPS = ("<=", ">=", "==", "<>", "!=")
_ONE_CHAR_OPS = "+-*/^%(),;<>"
_COMPARE = {"<": "<", "<=": "<=", ">": ">", ">=": ">=", "==": "==", "<>": "!=", "!=": "!="}
_LOGIC_WORDS = ("and", "or", "not")
_CONSTANTS = ("PI", "π", "E")

# Fusion function names by how they translate. Names are matched without case.
_SAME_UNIT_FUNCTIONS = ("abs", "ceil", "floor", "round")
_TRIG = ("sin", "cos", "tan")
_INVERSE_TRIG = ("asin", "acos", "atan")
_HYPERBOLIC = ("sinh", "cosh", "tanh")
_INVERSE_HYPERBOLIC = ("asinh", "acosh", "atanh")
_PLAIN = ("exp", "ln", "log")
_PICK_FUNCTIONS = ("min", "max")


class ExpressionError(Exception):
    """The expression cannot be written as an app formula; the message is plain words for the person."""


def unit_factor(word, loose=False):
    """(dim, factor to mm or degrees) for a unit word, or None when it is not a length or angle unit.

    `loose` also matches other letter cases; it is safe only where a unit is expected (after a value).
    """
    if loose and word not in _LENGTH_WORDS and word not in _ANGLE_WORDS:
        word = _LOOSE_WORDS.get(word.lower(), word)
    if word in _LENGTH_WORDS:
        return LENGTH, _LENGTH_WORDS[word]
    if word in _ANGLE_WORDS:
        return ANGLE, _ANGLE_WORDS[word]
    return None


# Tokens: ("num", value), ("id", name), ("op", text), ("end",)

def tokenize(text):
    tokens = []
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c.isspace():
            i += 1
        elif c.isdigit() or c == ".":
            m = _NUMBER.match(text, i)
            if not m:
                raise ExpressionError("A number could not be read.")
            tokens.append(("num", float(m.group(0))))
            i = m.end()
        elif _ident_char(c):
            k = i
            while k < n and _ident_char(text[k]):
                k += 1
            tokens.append(("id", text[i:k]))
            i = k
        elif text[i:i + 2] in _TWO_CHAR_OPS:
            tokens.append(("op", text[i:i + 2]))
            i += 2
        elif c in _ONE_CHAR_OPS:
            tokens.append(("op", c))
            i += 1
        else:
            raise ExpressionError(f"The character \"{c}\" is not supported.")
    tokens.append(("end",))
    return tokens


# Parse tree: ("num", v), ("name", s), ("unitword", w), ("unit", a, w), ("const", s), ("neg", a), ("not", a),
# ("bin", op, a, b) for + - * / % ^, ("cmp", op, a, b), ("logic", op, a, b), ("call", f, args)

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

    def is_op(self, *ops):
        tok = self.peek()
        return tok[0] == "op" and tok[1] in ops

    def is_word(self, *words):
        tok = self.peek()
        return tok[0] == "id" and (tok[1] in words or tok[1].lower() in words and tok[1].isupper())

    def close(self):
        if not self.is_op(")"):
            raise ExpressionError("A bracket is not closed.")
        self.take()

    def parse(self):
        node = self.disjunction()
        if self.peek()[0] != "end":
            raise ExpressionError("The expression has something extra at the end.")
        return node

    def disjunction(self):
        node = self.conjunction()
        while self.is_word("or"):
            self.take()
            node = ("logic", "||", node, self.conjunction())
        return node

    def conjunction(self):
        node = self.negation()
        while self.is_word("and"):
            self.take()
            node = ("logic", "&&", node, self.negation())
        return node

    def negation(self):
        if self.is_word("not"):
            self.take()
            return ("not", self.negation())
        return self.comparison()

    def comparison(self):
        node = self.sum()
        if self.is_op(*_COMPARE):
            op = _COMPARE[self.take()[1]]
            node = ("cmp", op, node, self.sum())
            if self.is_op(*_COMPARE):
                raise ExpressionError("Comparisons cannot be chained. Join them with \"and\".")
        return node

    def sum(self):
        node = self.term()
        while self.is_op("+", "-"):
            op = self.take()[1]
            node = ("bin", op, node, self.term())
        return node

    def term(self):
        node = self.unary()
        while self.is_op("*", "/", "%"):
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
        base = self.postfix()
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

    def postfix(self):
        """An operand and the unit words after it (`2 mm`, `(a + b) mm`)."""
        node = self.atom()
        while self.peek()[0] == "id" and not self.is_word(*_LOGIC_WORDS):
            word = self.take()[1]
            if unit_factor(word, loose=True) is None:
                raise ExpressionError(f"The unit \"{word}\" is not a length or an angle.")
            node = ("unit", node, word)
        return node

    def atom(self):
        tok = self.take()
        if tok[0] == "num":
            return ("num", tok[1])
        if tok[0] == "id":
            name = tok[1]
            if self.is_op("("):
                self.take()
                args = []
                if not self.is_op(")"):
                    args.append(self.disjunction())
                    while self.is_op(";", ","):
                        self.take()
                        args.append(self.disjunction())
                self.close()
                if name.lower() == "not" and len(args) == 1:
                    return ("not", args[0])
                return ("call", name.lower(), args)
            if name in _CONSTANTS:
                return ("const", name)
            if unit_factor(name) is not None:
                return ("unitword", name)
            return ("name", name)
        if tok == ("op", "("):
            node = self.disjunction()
            self.close()
            return node
        raise ExpressionError("The expression is not complete.")


def parse(text):
    return _Parser(tokenize(text)).parse()


def _children(node):
    for part in node[1:]:
        if isinstance(part, tuple):
            yield part
        elif isinstance(part, list):
            yield from part


def referenced_names(text):
    """Parameter names an expression reads, in order of first use. An unreadable expression gives an empty list."""
    try:
        tree = parse(text)
    except ExpressionError:
        return []
    out = []
    stack = [tree]
    while stack:
        node = stack.pop()
        if node[0] == "name":
            if node[1] not in out:
                out.append(node[1])
        else:
            stack.extend(reversed(list(_children(node))))
    return out


def scanned_names(text):
    """The words of an expression that may name a parameter, in order of first use, also when the parser refuses the
    text: identifiers that do not start with a digit and are not followed by `(` (a function). Unit words and
    constants are kept, so callers compare the result with the names they know."""
    out = []
    i, n = 0, len(text or "")
    while i < n:
        c = text[i]
        if c.isdigit() or c == ".":
            m = _NUMBER.match(text, i)
            i = m.end() if m else i + 1
            while i < n and _ident_char(text[i]):
                i += 1  # a unit written against its number: `2mm`
        elif _ident_char(c):
            k = i
            while k < n and _ident_char(text[k]):
                k += 1
            word, i = text[i:k], k
            while k < n and text[k].isspace():
                k += 1
            if (k >= n or text[k] != "(") and word not in out:
                out.append(word)
        else:
            i += 1
    return out


# Output nodes: ("num", v), ("name", s), ("neg", a), ("not", a), ("bin", op, a, b) for + - * /,
# ("cmp", op, a, b), ("logic", op, a, b), ("cond", test, a, b), ("call", f, args)

def format_number(value):
    """Number text with at most 9 decimals and no exponent."""
    if value == int(value) and abs(value) < 1e15:
        return str(int(value))
    text = ("%.9f" % value).rstrip("0").rstrip(".")
    return "0" if text in ("", "-0") else text


_PLAIN_NUMBER = re.compile(r"^\s*[-+]?(\d+\.?\d*|\.\d+)([eE][-+]?\d+)?\s*([A-Za-z]+)?\s*$")


def is_plain_number(expression):
    """True for "20", "20 mm" or "1.5e2 deg"; false for formulas such as "d1 * 2" or "20 mm + 1 mm"."""
    return bool(_PLAIN_NUMBER.match(expression or ""))


def format_expression(value, unit):
    """Expression text to write into a parameter, for example "40 mm"."""
    number = format_number(value)
    unit = (unit or "").strip()
    if unit_kind(unit) == "count":
        return number
    return f"{number} {unit}"


# Binding strength, as in the app grammar: choice, ||, &&, comparison, + -, * /, unary, atom.
_PREC = {"||": 1, "&&": 2, "<": 3, "<=": 3, ">": 3, ">=": 3, "==": 3, "!=": 3, "+": 4, "-": 4, "*": 5, "/": 5}
_UNARY = 6
_ATOM = 7


def _prec(node):
    kind = node[0]
    if kind == "cond":
        return 0
    if kind in ("bin", "cmp", "logic"):
        return _PREC[node[1]]
    if kind in ("neg", "not"):
        return _UNARY
    return _ATOM


def render(node):
    kind = node[0]
    if kind == "num":
        return format_number(node[1])
    if kind == "name":
        return node[1]
    if kind in ("neg", "not"):
        inner = render(node[1])
        return ("-" if kind == "neg" else "!") + (inner if _prec(node[1]) == _ATOM else "(" + inner + ")")
    if kind == "call":
        return node[1] + "(" + ", ".join(render(a) for a in node[2]) + ")"
    if kind == "cond":
        test = render(node[1])
        if _prec(node[1]) == 0:
            test = "(" + test + ")"
        return f"{test} ? {render(node[2])} : {render(node[3])}"
    op, left, right = node[1], node[2], node[3]
    p = _PREC[op]
    ltext = render(left)
    rtext = render(right)
    # A comparison does not chain, so a comparison on either side needs brackets.
    if _prec(left) < p or (kind == "cmp" and _prec(left) == p):
        ltext = "(" + ltext + ")"
    if _prec(right) <= p:
        rtext = "(" + rtext + ")"
    return f"{ltext} {op} {rtext}"


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


def internal_factor(dim):
    """Factor from Fusion's internal numbers (cm, radians) to mm and degrees, for a value of `dim`."""
    return 10.0 ** dim[0] * DEG_PER_RAD ** dim[1]


# Evaluation of written formulas with the app's function semantics, to check them against the number Fusion reports.

def _quarter_turns(x):
    """x degrees as a whole number of quarter turns (0 to 3), or None."""
    q = x / 90.0
    return int(q) % 4 if q == int(q) else None


def _sin(x):
    q = _quarter_turns(x)
    return (0.0, 1.0, 0.0, -1.0)[q] if q is not None else math.sin(math.radians(x))


def _cos(x):
    q = _quarter_turns(x)
    return (1.0, 0.0, -1.0, 0.0)[q] if q is not None else math.cos(math.radians(x))


def _tan(x):
    q = _quarter_turns(x)
    if q is None:
        return math.tan(math.radians(x))
    if q % 2:
        raise ValueError("tan of a quarter turn has no value")
    return 0.0


def _mod(a, b):
    if b == 0:
        raise ValueError("mod by zero")
    return a - b * math.floor(a / b)


# App function name -> (argument count, None for 2 or more; function over the argument list)
_APP_FUNCTIONS = {
    "abs": (1, lambda a: abs(a[0])),
    "acos": (1, lambda a: math.degrees(math.acos(a[0]))),
    "asin": (1, lambda a: math.degrees(math.asin(a[0]))),
    "atan": (1, lambda a: math.degrees(math.atan(a[0]))),
    "atan2": (2, lambda a: math.degrees(math.atan2(a[0], a[1]))),
    "ceil": (1, lambda a: math.ceil(a[0])),
    "clamp": (3, lambda a: min(max(a[0], a[1]), a[2])),
    "cos": (1, lambda a: _cos(a[0])),
    "exp": (1, lambda a: math.exp(a[0])),
    "floor": (1, lambda a: math.floor(a[0])),
    "ln": (1, lambda a: math.log(a[0])),
    "log": (1, lambda a: math.log10(a[0])),
    "max": (None, max),
    "min": (None, min),
    "mod": (2, lambda a: _mod(a[0], a[1])),
    "pi": (0, lambda a: math.pi),
    "pow": (2, lambda a: math.pow(a[0], a[1])),
    "round": (1, lambda a: math.floor(a[0] + 0.5)),
    "sign": (1, lambda a: (a[0] > 0) - (a[0] < 0)),
    "sin": (1, lambda a: _sin(a[0])),
    "sqrt": (1, lambda a: math.sqrt(a[0])),
    "tan": (1, lambda a: _tan(a[0])),
}


def parse_formula(formula):
    """Output node tree of an app formula in the forms `render` writes (a choice as `?:`, no `if` keyword)."""
    tokens = tokenize_formula(formula)
    pos = [0]

    def peek():
        return tokens[pos[0]]

    def take():
        pos[0] += 1
        return tokens[pos[0] - 1]

    def op(*texts):
        tok = peek()
        return tok[0] == "op" and tok[1] in texts

    def expect(text, message):
        if not op(text):
            raise ExpressionError(message)
        take()

    def choice():
        test = either()
        if op("?"):
            take()
            a = choice()
            expect(":", "A choice has no \":\".")
            return ("cond", test, a, choice())
        return test

    def either():
        node = both()
        while op("||"):
            take()
            node = ("logic", "||", node, both())
        return node

    def both():
        node = compare()
        while op("&&"):
            take()
            node = ("logic", "&&", node, compare())
        return node

    def compare():
        node = sum_()
        if op(*_PREC_COMPARE):
            node = ("cmp", take()[1], node, sum_())
        return node

    def sum_():
        node = term()
        while op("+", "-"):
            node = ("bin", take()[1], node, term())
        return node

    def term():
        node = unary()
        while op("*", "/"):
            node = ("bin", take()[1], node, unary())
        return node

    def unary():
        if op("-", "!"):
            return ("neg" if take()[1] == "-" else "not", unary())
        return atom()

    def atom():
        tok = take()
        if tok[0] == "num":
            return ("num", tok[1])
        if tok[0] == "id":
            if op("("):
                take()
                args = []
                if not op(")"):
                    args.append(choice())
                    while op(","):
                        take()
                        args.append(choice())
                expect(")", "A bracket is not closed.")
                return ("call", tok[1], args)
            return ("name", tok[1])
        if tok == ("op", "("):
            node = choice()
            expect(")", "A bracket is not closed.")
            return node
        raise ExpressionError("The formula is not complete.")

    node = choice()
    if peek()[0] != "end":
        raise ExpressionError("The formula has something extra at the end.")
    return node


_PREC_COMPARE = ("<", "<=", ">", ">=", "==", "!=")
_COMPARISONS = {
    "<": lambda a, b: a < b, "<=": lambda a, b: a <= b, ">": lambda a, b: a > b, ">=": lambda a, b: a >= b,
    "==": lambda a, b: a == b, "!=": lambda a, b: a != b,
}


def _truth(value):
    return 1.0 if value else 0.0


def _eval(node, env):
    kind = node[0]
    if kind == "num":
        return node[1]
    if kind == "name":
        if node[1] not in env:
            raise ExpressionError(f"Unknown name {node[1]}.")
        return float(env[node[1]])
    if kind == "neg":
        return -_eval(node[1], env)
    if kind == "not":
        return _truth(_eval(node[1], env) == 0)
    if kind == "cond":
        return _eval(node[2] if _eval(node[1], env) != 0 else node[3], env)
    if kind == "logic":
        left = _eval(node[2], env) != 0
        if left == (node[1] == "||"):
            return _truth(left)
        return _truth(_eval(node[3], env) != 0)
    if kind == "cmp":
        return _truth(_COMPARISONS[node[1]](_eval(node[2], env), _eval(node[3], env)))
    if kind == "call":
        entry = _APP_FUNCTIONS.get(node[1])
        if entry is None:
            raise ExpressionError(f"Unknown function {node[1]}.")
        count, fn = entry
        args = [_eval(a, env) for a in node[2]]
        if len(args) < 2 if count is None else len(args) != count:
            raise ExpressionError(f"{node[1]} has the wrong number of values.")
        try:
            return float(fn(args))
        except (ValueError, OverflowError) as exc:
            raise ExpressionError(str(exc))
    a, b = _eval(node[2], env), _eval(node[3], env)
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
    value = _eval(parse_formula(formula), env)
    if math.isnan(value) or math.isinf(value):
        raise ExpressionError("The formula does not give a number.")
    return value


_FORMULA_TOKEN = re.compile(r"\s*(?:(\d+\.?\d*|\.\d+)([eE][-+]?\d+)?|([A-Za-z_][A-Za-z0-9_]*)|(<=|>=|==|!=|&&|\|\||.))")


def tokenize_formula(formula):
    """Tokens of an app formula: ("num", v), ("id", name), ("op", text), ("end",)."""
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
