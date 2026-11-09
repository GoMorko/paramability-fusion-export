"""Feature values that follow Fusion parameters.

A reader gives each value that Fusion keeps as a model parameter in the item's `data.params` (capture field path to
`{ name, expression, value }`). `quantity` turns such a value into a `Quantity`: the measured number plus, when the
parameter's expression reads a size of the size table, the formula to write instead. `num` is the same for a field
written as a number or `{ "expr": ... }`.

When a value cannot follow its sizes (the formula does not translate, its unit or sign breaks inside the size range,
or the step writes it as a plain number), it is written as its number and the sizes it reads are recorded as a doubt
(`Context.doubt`). The driver then keeps them free with a warning (`translate`); a value that depends on a size never
stays a number while that size stays free without one. A formula the
parser cannot read still marks the sizes on Fusion's own list of what its parameter depends on.
"""
import re

from ..params.expressions import MAX_FORMULA_LENGTH, tokenize_formula
from . import range_check
from .range_check import size_env as _env  # noqa: F401  (the size values at a setting; tests read it from here)

TOLERANCE = 1e-6
_ATOM = re.compile(r"^(?:[A-Za-z_][A-Za-z0-9_]*|\d+(?:\.\d+)?)$")


def _n(value):
    return round(value, 9) + 0.0


def _text(number):
    """A number as a formula writes it: no exponent, at most 9 decimals."""
    value = _n(number)
    return str(int(value)) if value == int(value) else format(value, ".9f").rstrip("0").rstrip(".")


def _whole_group(text):
    """True when `text` is one bracket group: it opens with "(" and that bracket closes at its end."""
    if not text.startswith("("):
        return False
    level = 0
    for at, char in enumerate(text):
        level += {"(": 1, ")": -1}.get(char, 0)
        if level == 0:
            return at == len(text) - 1
    return False


def _negated(text):
    """`text` negated: a leading minus on a plain name, a number or a bracket group is taken off instead of stacked."""
    if text.startswith("-") and _ATOM.match(text[1:]):
        return text[1:]
    if text.startswith("-") and _whole_group(text[1:]):
        return text[2:-1]
    return "-" + _wrapped(text)


def _subtracted(text):
    """The text after a minus sign for a negated term, or None when `text` is not a negated name, number or group."""
    if text.startswith("-") and (_ATOM.match(text[1:]) or _whole_group(text[1:])):
        return text[1:]
    return None


def _wrapped(text):
    return text if _ATOM.match(text) else "(" + text + ")"


class Sized(dict):
    """`{ "expr": formula }` that also remembers the number the formula stood for when it was written, and the Fusion
    names of the sizes it reads.

    It is a plain dict for JSON and copying; handlers that read written steps back (`number`) use the number.
    """
    n = 0.0
    reads = ()


def negated(value):
    """A written number or formula, negated."""
    if not isinstance(value, Sized):
        return 0.0 - value
    out = Sized(expr=_negated(value["expr"]))
    out.n, out.reads = -value.n, value.reads
    return out


def reads_in(node, found=None):
    """The Fusion names read by every formula in a written value, step or list of steps, in order."""
    found = {} if found is None else found
    if isinstance(node, Sized):
        found.update(dict.fromkeys(node.reads))
    if isinstance(node, dict):
        for value in node.values():
            reads_in(value, found)
    elif isinstance(node, list):
        for value in node:
            reads_in(value, found)
    return tuple(found)


def numbers_of(node):
    """A written value, step or list with every formula replaced by the number it stood for."""
    if isinstance(node, Sized):
        return node.n
    if isinstance(node, dict):
        return {k: numbers_of(v) for k, v in node.items()}
    if isinstance(node, list):
        return [numbers_of(v) for v in node]
    return node


def number(value):
    """The number of a written value: its measured number for a formula, else the value itself."""
    return value.n if isinstance(value, Sized) else value


class Quantity:
    """A measured number with an optional formula over the sizes. `reads` are the Fusion names of the sizes it reads.

    A formula that ends in a number keeps the two apart (`core`, `const`), so adding numbers later folds them into one.
    """

    def __init__(self, n, text=None, reads=(), core=None, const=0.0):
        self.n = n
        self.text = text
        self.reads = tuple(reads)
        self.core = text if core is None else core
        self.const = const if core is not None else 0.0

    @property
    def sized(self):
        return self.text is not None

    def json(self):
        """The value as the recipe writes it: a number, or { "expr": formula }."""
        if not self.sized:
            return _n(self.n)
        out = Sized(expr=self.text)
        out.n, out.reads = self.n, self.reads
        return out

    def same_as(self, other):
        if self.sized or other.sized:
            return self.text == other.text
        return abs(self.n - other.n) <= 1e-9

    def scaled(self, factor):
        if not self.sized:
            return Quantity(self.n * factor)
        if factor == 1:
            return self
        if factor == -1:
            return Quantity(-self.n, _negated(self.text), self.reads)
        return Quantity(self.n * factor, "%s * %s" % (_text(factor), _wrapped(self.text)), self.reads)

    def _with_const(self, const):
        """This formula's core plus the number `const`."""
        n = self.n - self.const + const
        if abs(const) <= 1e-12:
            return Quantity(n, self.core, self.reads)
        sign, right = ("-", _text(-const)) if const < 0 else ("+", _text(const))
        return Quantity(n, "%s %s %s" % (self.core, sign, right), self.reads, self.core, const)

    def plus(self, other):
        """The sum with a number or another Quantity."""
        if not isinstance(other, Quantity):
            other = Quantity(other)
        if not self.sized and not other.sized:
            return Quantity(self.n + other.n)
        reads = tuple(dict.fromkeys(self.reads + other.reads))
        if not self.sized and self.n == 0:
            return Quantity(self.n + other.n, other.text, reads, other.core, other.const)
        if not other.sized:
            return self if other.n == 0 else self._with_const(self.const + other.n)
        left = self.text if self.sized else _text(self.n)
        rest = _subtracted(other.text)
        sign, right = ("-", rest) if rest is not None else ("+", _wrapped(other.text))
        return Quantity(self.n + other.n, "%s %s %s" % (left, sign, right), reads)

    def times(self, other):
        """The product with a number or another Quantity."""
        if not isinstance(other, Quantity):
            return self.scaled(other)
        if not self.sized:
            return other.scaled(self.n)
        if not other.sized:
            return self.scaled(other.n)
        reads = tuple(dict.fromkeys(self.reads + other.reads))
        return Quantity(self.n * other.n, "%s * %s" % (_wrapped(self.text), _wrapped(other.text)), reads)

    def divided_by(self, other):
        if not isinstance(other, Quantity):
            other = Quantity(other)
        if not self.sized and not other.sized:
            return Quantity(self.n / other.n)
        reads = tuple(dict.fromkeys(self.reads + other.reads))
        left = _wrapped(self.text) if self.sized else _text(self.n)
        right = _wrapped(other.text) if other.sized else _text(other.n)
        return Quantity(self.n / other.n, "%s / %s" % (left, right), reads)


def _data(item):
    data = item.get("data") if isinstance(item, dict) else None
    return data if isinstance(data, dict) else item


def _param(item, path):
    params = _data(item).get("params")
    found = params.get(path) if isinstance(params, dict) else None
    return found if isinstance(found, dict) and found.get("expression") else None


def _unread(ctx, ref, tr):
    """Fusion names of the sizes behind a parameter whose expression the parser could not read: Fusion's own list of
    the parameters it depends on. Empty when the parser read the expression."""
    if tr.ok or tr.reads:
        return ()
    return tuple(sorted(ctx.table.depends(ref.get("name") or "")))


def _reads_of(ctx, ref):
    """Fusion names of the sizes a parameter reads."""
    if ctx.table is None:
        return ()
    tr = ctx.table.translate(ref["expression"])
    return tuple(tr.reads) or _unread(ctx, ref, tr)


def pin(ctx, item, path, why):
    """The value at `path` stays a number here: the sizes its parameter reads become fixed numbers."""
    ref = _param(item, path)
    if ref is not None:
        ctx.doubt(_reads_of(ctx, ref), why)


def _stays_in_range(table, formula, reads, sign, low):
    """True when sign * formula stays at or above `low` over the size range, mixed corners included."""
    span = range_check.sweep(table, formula, reads)
    return span.at_least(low) if sign > 0 else span.at_most(-low)


_ROUNDING = ("round", "floor", "ceil")


def _without_rounding(tokens):
    """The tokens with each rounding call (`ceil(...)` and the like) left out: such a call is a whole number."""
    out, at = [], 0
    while at < len(tokens):
        token = tokens[at]
        if token[0] == "id" and token[1] in _ROUNDING and at + 1 < len(tokens) and tokens[at + 1] == ("op", "("):
            level, at = 0, at + 1
            while at < len(tokens):
                level += {("op", "("): 1, ("op", ")"): -1}.get(tokens[at], 0)
                at += 1
                if level == 0:
                    break
            out.append(("num", 1))
            continue
        out.append(token)
        at += 1
    return out


def _gives_whole_numbers(table, formula, depth=0):
    """True when a formula gives a whole number at every size value: it adds, subtracts and multiplies whole
    numbers, rounding calls and count sizes (and derived sizes that do the same)."""
    tokens = _without_rounding(tokenize_formula(formula)[:-1])
    for token in tokens:
        if token[0] == "num" and token[1] != int(token[1]):
            return False
        if token[0] == "op" and token[1] not in "+-*()":
            return False
        if token[0] == "id":
            size = table.sizes.get(token[1])
            if size is None or depth > 8:
                return False
            if "expr" in size:
                if not _gives_whole_numbers(table, size["expr"], depth + 1):
                    return False
            elif size.get("kind") != "count":
                return False
    return True


def stays_below(ctx, item, q, limit, why):
    """`q` when it stays under `limit` over the size range; else its number, with its sizes fixed for `why`."""
    if not q.sized or _stays_in_range(ctx.table, q.text, q.reads, -1, -limit + 1e-9):
        return q
    ctx.doubt(q.reads, why)
    return Quantity(q.n)


def stays_positive(table, q):
    """True when a sized Quantity stays above zero over the size range."""
    return _stays_in_range(table, q.text, q.reads, 1, 1e-9)


def quantity(ctx, item, path, literal, dim="length", sign=1, absolute=False, whole=False):
    """The value at `path` as a Quantity.

    `literal` is the number the step writes (what Fusion measured, mm or degrees). `dim` is length, angle or scalar.
    `sign` is 1 or -1 when the step writes the absolute value of a negative parameter. `absolute` asks the value to
    stay above zero over the size range; `whole` asks it to stay at least 1 (counts).
    """
    plain = Quantity(literal)
    ref = _param(item, path)
    if ref is None or ctx.table is None:
        return plain
    tr = ctx.table.translate(ref["expression"], expected=ref["value"], dim=dim, unit=ctx.table.unit_of(ref.get("name")))
    if not tr.reads:
        behind = _unread(ctx, ref, tr)
        if behind:
            ctx.doubt(behind, "a value of %s cannot be copied: %s"
                      % (item.get("name", "a step"), tr.reason.rstrip(".")))
        return plain
    if not tr.ok:
        ctx.doubt(tr.reads, "a value of %s cannot be copied: %s"
                  % (item.get("name", "a step"), tr.reason.rstrip(".")))
        return plain
    if abs(sign * tr.value - literal) > TOLERANCE + 1e-9 * abs(literal):
        ctx.doubt(tr.reads, "its formula in %s does not match what Fusion measured" % item.get("name", "a step"))
        return plain
    if len(tr.formula) > MAX_FORMULA_LENGTH:
        ctx.doubt(tr.reads, "its formula in %s is too long to copy" % item.get("name", "a step"))
        return plain
    if whole and not _gives_whole_numbers(ctx.table, tr.formula):
        ctx.doubt(tr.reads, "%s needs a whole number of copies, and its formula can give a part number"
                  % item.get("name", "a step"))
        return plain
    if absolute or whole:
        if not _stays_in_range(ctx.table, tr.formula, tr.reads, sign, 1.0 if whole else 1e-9):
            ctx.doubt(tr.reads, "%s would leave its working range (a length reaching zero or a count under 1)"
                      % item.get("name", "a step"))
            return plain
    text = tr.formula if sign > 0 else _negated(tr.formula)
    return Quantity(literal, text, tr.reads)


def num(ctx, item, path, literal, **kwargs):
    """`quantity(...).json()`: a number, or { "expr": formula } when the value follows sizes."""
    return quantity(ctx, item, path, literal, **kwargs).json()
