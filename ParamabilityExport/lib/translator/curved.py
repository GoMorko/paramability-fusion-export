"""Sketch values that move along a curve with the sizes: products, quotients and square roots of affine values.

Where a sketch line crosses a circle, or two circles cross, the crossing point moves with a square root of the sizes,
so it is not an `Affine`. `Curved` keeps such a value as a small formula over Fusion parameter names: a polynomial
part plus square roots, products and quotients of other values. `render` writes an `Affine` or a `Curved` as a
`Quantity` over the sizes.
"""
import math

from ..package.numbers import round9
from ..sketch_values.motion import UNREAD, Affine, Stuck, Terms
from .values import Quantity, wrapped

_EPS = 1e-12


def _monomial(names):
    return tuple(sorted(names))


class Poly:
    """`sum(coef * product of parameters)`, keyed by the sorted names of each product (`()` is the constant)."""

    def __init__(self, terms=None):
        self.terms = {m: float(c) for m, c in (terms or {}).items() if abs(c) > _EPS}

    @classmethod
    def of(cls, value):
        if isinstance(value, Poly):
            return value
        if isinstance(value, Affine):
            out = {(name,): a for name, a in value.terms.items()}
            out[()] = value.const
            return cls(out)
        return cls({(): float(value)})

    def plus(self, other):
        terms = dict(self.terms)
        for m, c in Poly.of(other).terms.items():
            terms[m] = terms.get(m, 0.0) + c
        return Poly(terms)

    def scaled(self, factor):
        return Poly({m: c * factor for m, c in self.terms.items()})

    def times(self, other):
        terms = {}
        for m1, c1 in self.terms.items():
            for m2, c2 in Poly.of(other).terms.items():
                m = _monomial(m1 + m2)
                terms[m] = terms.get(m, 0.0) + c1 * c2
        return Poly(terms)

    def names(self):
        return tuple(dict.fromkeys(n for m in self.terms for n in m))

    def key(self):
        return tuple(sorted((m, round(c, 9)) for m, c in self.terms.items()))

    def render(self, table):
        """A Quantity over the sizes, or a Stuck ("unread") when a parameter cannot be written as a formula."""
        total = Quantity(0.0)
        for m, coef in sorted(self.terms.items(), key=lambda t: (len(t[0]) == 0, t[0])):
            number, value, texts, reads = coef, 1.0, [], []
            for name in m:
                tr = table.translate(name)
                if not tr.ok:
                    return Stuck(table.depends(name) or tr.reads, UNREAD)
                if tr.reads:
                    texts.append(wrapped(tr.formula))
                    reads.extend(tr.reads)
                    value *= tr.value
                else:
                    number *= tr.value
            if texts:
                total = total.plus(Quantity(value, " * ".join(texts), tuple(dict.fromkeys(reads))).scaled(number))
            else:
                total = total.plus(number)
        return total


def _coefficient(value):
    value = round9(value)
    return str(int(value)) if value == int(value) else repr(value)


def _sum_formula(parts, constant):
    """`parts` are (coefficient, formula) pairs, written as a sum: `0.5 * w - offset + 2`."""
    out = ""
    for at, (a, text) in enumerate(parts):
        if abs(a) == 1:
            body = text if a > 0 else wrapped(text)
        else:
            body = "%s * %s" % (_coefficient(abs(a)), wrapped(text))
        if at == 0:
            out = ("-" if a < 0 else "") + body
        else:
            out += (" - " if a < 0 else " + ") + body
    if abs(constant) > _EPS:
        out += (" - " if constant < 0 else " + ") + _coefficient(abs(constant))
    return out


def _render_affine(value, table):
    constant = total = value.const
    parts, reads = [], []
    for name, a in value.terms.items():
        tr = table.translate(name)
        if not tr.ok:
            return Stuck(table.depends(name) or tr.reads, UNREAD, value.sketch)
        total += a * tr.value
        if tr.reads:
            parts.append((a, tr.formula))
            reads.extend(tr.reads)
        else:
            constant += a * tr.value
    if not parts:
        return Quantity(round9(constant))
    return Quantity(total, _sum_formula(parts, constant), tuple(dict.fromkeys(reads)))


def render(value, table):
    """`value` (an `Affine` or a `Curved`) as a `Quantity` over the sizes of `table`, or a `Stuck` ("unread") when a
    parameter cannot be written as a formula. A fixed or constant parameter becomes its number and joins the
    constant; a formula reads the free sizes it depends on."""
    if isinstance(value, Affine):
        return _render_affine(value, table)
    return value.render(table)


def _as_curved(value):
    if isinstance(value, Curved):
        return value
    return Curved(Poly.of(value), (), getattr(value, "sketch", ""))


class Curved:
    """`poly + sum(coef * node)`; a node is `("sqrt", x)`, `("mul", x, y)`, `("div", x, y)`, or `("sin", x)`,
    `("cos", x)`, `("tan", x)` of an angle `x` in degrees, all of Curved values."""

    def __init__(self, poly, nodes=(), sketch=""):
        self.poly = Poly.of(poly)
        self.nodes = tuple((c, node) for c, node in nodes if abs(c) > _EPS)
        self.sketch = sketch

    @property
    def is_constant(self):
        return not self.names()

    def names(self):
        out = list(self.poly.names())
        for _, node in self.nodes:
            for arg in node[1:]:
                out.extend(arg.names())
        return tuple(dict.fromkeys(out))

    def key(self):
        return (self.poly.key(), tuple((round(c, 9), node[0]) + tuple(a.key() for a in node[1:])
                                       for c, node in self.nodes))

    def scaled(self, factor):
        return Curved(self.poly.scaled(factor), [(c * factor, n) for c, n in self.nodes], self.sketch)

    def plus(self, other):
        other = _as_curved(other)
        nodes = list(self.nodes)
        for c, node in other.nodes:
            key = (node[0],) + tuple(a.key() for a in node[1:])
            at = next((i for i, (_, n) in enumerate(nodes) if (n[0],) + tuple(a.key() for a in n[1:]) == key), None)
            if at is None:
                nodes.append((c, node))
            else:
                nodes[at] = (nodes[at][0] + c, nodes[at][1])
        return Curved(self.poly.plus(other.poly), nodes, self.sketch or other.sketch)

    def times(self, other):
        other = _as_curved(other)
        if not self.nodes and not other.nodes:
            return Curved(self.poly.times(other.poly), (), self.sketch or other.sketch)
        return Curved(Poly(), [(1.0, ("mul", self, other))], self.sketch or other.sketch)

    def divided(self, other):
        return Curved(Poly(), [(1.0, ("div", self, _as_curved(other)))], self.sketch)

    def sqrt(self):
        return Curved(Poly(), [(1.0, ("sqrt", self))], self.sketch)

    def trig(self, function):
        """`sin`, `cos` or `tan` of this value as an angle in degrees."""
        return Curved(Poly(), [(1.0, (function, self))], self.sketch)

    def render(self, table):
        """A Quantity over the sizes, or a Stuck ("unread") when a parameter cannot be written as a formula."""
        total = self.poly.render(table)
        if isinstance(total, Stuck):
            return Stuck(total.movers, UNREAD, self.sketch)
        for coef, node in self.nodes:
            args = [render(a, table) for a in node[1:]]
            stuck = next((a for a in args if isinstance(a, Stuck)), None)
            if stuck is not None:
                return Stuck(stuck.movers, UNREAD, self.sketch)
            total = total.plus(_apply(node[0], args).scaled(coef))
        return total


_TRIG = {"sin": math.sin, "cos": math.cos, "tan": math.tan}


def _apply(op, args):
    reads = tuple(dict.fromkeys(r for a in args for r in a.reads))
    if op in _TRIG:
        (a,) = args
        n = _TRIG[op](math.radians(a.n))
        return Quantity(n, "%s(%s)" % (op, a.text), reads) if a.sized else Quantity(n)
    if op == "sqrt":
        (a,) = args
        n = math.sqrt(max(a.n, 0.0))
        return Quantity(n, "sqrt(%s)" % a.text, reads) if a.sized else Quantity(n)
    a, b = args
    return a.divided_by(b) if op == "div" else a.times(b)


def combine(parts, sketch=""):
    """`sum(coef * value)` over (coef, Affine, Curved, Stuck or number) pairs. A Stuck part makes the sum stuck; a
    Curved part makes it Curved; else it is an Affine."""
    total, stuck = Affine(0.0, sketch=sketch), []
    for coef, value in parts:
        if not coef:
            continue
        if isinstance(value, Stuck):
            stuck.append(value)
        elif isinstance(value, Curved):
            total = _as_curved(total).plus(value.scaled(coef))
        elif isinstance(value, Affine):
            total = total.plus(value.scaled(coef))
        else:
            total = total.plus(coef * value)
    if stuck:
        names = [name for s in stuck for name in s.movers]
        return Stuck(dict.fromkeys(names), stuck[0].cause, stuck[0].sketch or sketch)
    if isinstance(total, Curved) and not total.sketch:
        total.sketch = sketch
    return total


def _factor(factor, sketch):
    """One factor of a `Terms` part as a Curved: a size, or a function of a share of an angle size (`cot` is
    cos / sin)."""
    function, name, scale = factor
    angle = Curved(Poly({(name,): scale}), (), sketch)
    if not function:
        return angle
    if function == "cot":
        return angle.trig("cos").divided(angle.trig("sin"))
    return angle.trig(function)


def from_terms(value):
    """A motion `Terms` value as a Curved over the same Fusion names."""
    total = Curved(Poly({(): value.const}), (), value.sketch)
    for coef, factors in value.parts:
        part = Curved(Poly({(): coef}), (), value.sketch)
        for factor in factors:
            part = part.times(_factor(factor, value.sketch))
        total = total.plus(part)
    total.sketch = value.sketch
    return total


def names_of(value):
    """The Fusion names that move a raw value (Affine, Curved or Stuck)."""
    if isinstance(value, Stuck):
        return value.movers
    if isinstance(value, Curved):
        return value.names()
    if isinstance(value, Terms):
        return value.names()
    return tuple(value.terms)


def times(a, b):
    """The product of two raw values (Affine, Curved or numbers) as a Curved."""
    return _as_curved(a).times(b)
