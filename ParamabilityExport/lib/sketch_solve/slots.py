"""The scalar unknowns of a sketch and the relations between them.

A slot is one scalar: `("x", point)`, `("y", point)`, `("o", line)` (the line's offset along its normal, see
`solve.Directions`), `("r", curve)` (a radius) or `("len", line)` (a line's length along its direction). Slots that a
relation with constant factors ties together (`y1 = y2`, `x2 = x1 + d16`, `2 * xm = xa + xb` once two of them share a
group) are joined: every slot is `m * root + k` of its group's root, with `m` a number and `k` an `Expr`. Knowing the
root gives every slot of the group.

A `Lin` is `sum(coef * slot) + const` with `Expr` factors; a linear relation says a `Lin` is zero. A `Dist` says two
points lie a known distance apart (a point on a circle, a centre at a distance).
"""
from ..sketch_values.expr import Expr, num


def x(p):
    return ("x", p)


def y(p):
    return ("y", p)


def offset(line):
    return ("o", line)


def radius(curve):
    return ("r", curve)


def length(line):
    return ("len", line)


class Lin:
    """`sum(coef * slot) + const`; coefficients and the constant are `Expr` values."""

    def __init__(self, terms=None, const=0.0):
        self.terms = {}
        for slot, coef in (terms or {}).items():
            self.add(slot, coef)
        self.const = num(const) if not isinstance(const, Expr) else const

    def add(self, slot, coef):
        coef = num(coef) if not isinstance(coef, Expr) else coef
        self.terms[slot] = self.terms.get(slot, num(0.0)) + coef
        return self

    def plus(self, other, factor=1.0):
        """This plus `factor` times another `Lin`, an `Expr` or a number."""
        out = Lin(self.terms, self.const)
        if isinstance(other, Lin):
            for slot, coef in other.terms.items():
                out.add(slot, coef * factor)
            out.const = out.const + other.const * factor
        else:
            out.const = out.const + (other if isinstance(other, Expr) else num(other)) * factor
        return out

    def scaled(self, factor):
        return Lin({s: c * factor for s, c in self.terms.items()}, self.const * factor)

    def base(self, base_of, env_value):
        """The number on the solved drawing: `base_of(slot)` gives a slot's solved number, `env_value(expr)` the
        number of an `Expr` at the current sizes."""
        return sum(env_value(c) * base_of(s) for s, c in self.terms.items()) + env_value(self.const)


def point(p):
    """The point's coordinates as two `Lin`."""
    return Lin({x(p): 1.0}), Lin({y(p): 1.0})


class Rel:
    """A linear relation `lin == 0`, with the rule that made it (for reasons and conflicts)."""

    def __init__(self, lin, source):
        self.lin = lin
        self.source = source


class Dist:
    """Points `a` and `b` lie `rho` apart (`rho` a `Lin`, known once its slots are)."""

    def __init__(self, a, b, rho, source):
        self.a, self.b, self.rho, self.source = a, b, rho, source


class Slots:
    """The groups of slots, the known roots and the solved number of every slot."""

    def __init__(self, base):
        self.base = dict(base)  # slot -> solved number
        self.parent = {}  # slot -> (parent slot, m, k): slot = m * parent + k
        self.value = {}  # root -> Expr
        self.members = {}  # root -> [slot, ...] (every slot of the group, the root too)
        self.source = {}  # root -> the rule that gave its value

    def find(self, slot):
        """(root, m, k) with slot = m * root + k."""
        path = []
        current, m, k = slot, 1.0, num(0.0)
        while current in self.parent:
            path.append(current)
            parent, pm, pk = self.parent[current]
            # current = pm * parent + pk, and slot = m * current + k
            k = k + pk.scaled(m)
            m = m * pm
            current = parent
        if len(path) > 1:
            self._compress(path, current)
        return current, m, k

    def _compress(self, path, root):
        for slot in path:
            m, k, node = 1.0, num(0.0), slot
            while node != root:
                parent, pm, pk = self.parent[node]
                k = k + pk.scaled(m)
                m = m * pm
                node = parent
            self.parent[slot] = (root, m, k)

    def group(self, root):
        return self.members.get(root, [root])

    def known(self, slot):
        """The slot's value as an Expr, or None."""
        root, m, k = self.find(slot)
        if root not in self.value:
            return None
        return self.value[root].scaled(m) + k

    def reduce(self, lin):
        """`lin` over the unknown roots: ({root: coef}, const). Known roots fold into the constant."""
        unknown, const = {}, lin.const
        for slot, coef in lin.terms.items():
            root, m, k = self.find(slot)
            const = const + coef * k
            if root in self.value:
                const = const + coef * self.value[root].scaled(m)
            else:
                unknown[root] = unknown.get(root, num(0.0)) + coef.scaled(m)
        return {r: c for r, c in unknown.items() if not (c.is_constant and abs(c.const) < 1e-12)}, const

    def join(self, keep, other, m, k):
        """Puts root `other` into the group of root `keep`: other = m * keep + k."""
        self.parent[other] = (keep, m, k)
        self.members[keep] = self.group(keep) + self.group(other)
        self.members.pop(other, None)

    def assign(self, root, value, source):
        self.value[root] = value
        self.source[root] = source
