"""The value type both translators write: a measured number with, when sizes move it, the formula over those sizes.

`Quantity` is the number (`n`), the formula text (`text`, None when no size moves it) and the Fusion names of the
sizes the formula reads (`reads`). It has no destination in it: the Paramability translator writes `Quantity.json()`
into its recipe, and the Orca translator turns the formula into an Orca one when it binds a feature field. `Sized` is
the written form, `{ "expr": formula }` that remembers its number and reads, for recipes that hold written steps.
"""
import re

from ..package.numbers import round9

_ATOM = re.compile(r"^(?:[A-Za-z_][A-Za-z0-9_]*|\d+(?:\.\d+)?)$")


def _text(number):
    """A number as a formula writes it: no exponent, at most 9 decimals."""
    value = round9(number)
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


def negated_text(text):
    """`text` negated: a leading minus on a plain name, a number or a bracket group is taken off instead of stacked."""
    if text.startswith("-") and _ATOM.match(text[1:]):
        return text[1:]
    if text.startswith("-") and _whole_group(text[1:]):
        return text[2:-1]
    return "-" + wrapped(text)


def _subtracted(text):
    """The text after a minus sign for a negated term, or None when `text` is not a negated name, number or group."""
    if text.startswith("-") and (_ATOM.match(text[1:]) or _whole_group(text[1:])):
        return text[1:]
    return None


def wrapped(text):
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
    out = Sized(expr=negated_text(value["expr"]))
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
            return round9(self.n)
        out = Sized(expr=self.text)
        out.n, out.reads = self.n, self.reads
        return out

    def magnitude(self):
        """The value with its sign dropped: itself when it is not below zero, else negated."""
        return self.scaled(-1) if self.n < 0 else self

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
            return Quantity(-self.n, negated_text(self.text), self.reads)
        return Quantity(self.n * factor, "%s * %s" % (_text(factor), wrapped(self.text)), self.reads)

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
        sign, right = ("-", rest) if rest is not None else ("+", wrapped(other.text))
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
        return Quantity(self.n * other.n, "%s * %s" % (wrapped(self.text), wrapped(other.text)), reads)

    def divided_by(self, other):
        if not isinstance(other, Quantity):
            other = Quantity(other)
        if not self.sized and not other.sized:
            return Quantity(self.n / other.n)
        reads = tuple(dict.fromkeys(self.reads + other.reads))
        left = wrapped(self.text) if self.sized else _text(self.n)
        right = wrapped(other.text) if other.sized else _text(other.n)
        return Quantity(self.n / other.n, "%s / %s" % (left, right), reads)
