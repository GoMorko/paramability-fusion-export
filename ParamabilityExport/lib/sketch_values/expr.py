"""A symbolic value over Fusion parameter names: numbers, sums, products, quotients, square roots and `sin`, `cos`,
`tan` of angles in degrees.

An `Expr` is kept in one normal form: a constant plus a sum of terms, each a number times a product of factors. A
factor is a parameter name, or a function of another `Expr`: `sqrt`, `sin`, `cos`, `tan`, or `inv` (one divided by
it). The normal form folds numbers, merges equal terms, cancels `x * inv(x)` and `sqrt(x) * sqrt(x)`, turns
`cos(u)^2 + sin(u)^2` into 1 and moves whole quarter turns out of a trig argument (`cos(a + 90)` is `-sin(a)`). That
keeps formulas short and makes a linear value visible as one (`as_affine`).

Values are evaluated over an env (Fusion name to number, lengths in mm and angles in degrees, as for `Affine` and
`Terms`). `text` writes the formula as the translator writes formulas; `json` and `from_json` keep it in a file.
"""
import math
import re

from ..package.numbers import round9
from .motion import Affine

_EPS = 1e-12
_FUNCTIONS = ("sqrt", "sin", "cos", "tan", "inv")
_TRIG = ("sin", "cos", "tan")
_ATOM = re.compile(r"^(?:[A-Za-z_][A-Za-z0-9_]*|\d+(?:\.\d+)?)$")


class ExprDomainError(ValueError):
    """A value has no number at an env: a square root of a negative value or a division by zero."""


def _fkey(factor):
    return (0, factor) if isinstance(factor, str) else (1, factor[0], factor[1].key())


def _round_key(value):
    return round(value, 12) + 0.0


class Expr:
    """`const + sum(coef * product of factors)`. Build values with `num`, `name`, the operators `+ - * /` and the
    functions `sqrt`, `sin`, `cos`, `tan` of this module; the constructor takes an already normal form."""

    __slots__ = ("const", "terms", "_key")

    def __init__(self, const=0.0, terms=None):
        self.const = float(const)
        # monomial key (tuple of factor keys) -> (coef, factors)
        self.terms = dict(terms or {})
        self._key = None

    # --- reading -------------------------------------------------------------------------------------------------

    @property
    def is_constant(self):
        return not self.terms

    def key(self):
        """A hashable key; equal keys mean the same normal form."""
        if self._key is None:
            self._key = (_round_key(self.const),
                         tuple(sorted((mk, _round_key(c)) for mk, (c, _) in self.terms.items())))
        return self._key

    def same(self, other):
        return self.key() == of(other).key()

    def parts(self):
        """The terms in a fixed order: `(coef, factors)`, a factor `("name", text)` or `(function, Expr)`."""
        out = []
        for mk in sorted(self.terms):
            coef, factors = self.terms[mk]
            out.append((coef, tuple(("name", f) if isinstance(f, str) else f for f in factors)))
        return out

    def names(self):
        """The Fusion names the value reads, in order."""
        found = {}
        for _, factors in self.parts():
            for op, arg in factors:
                if op == "name":
                    found[arg] = None
                else:
                    found.update(dict.fromkeys(arg.names()))
        return tuple(found)

    def value(self, env):
        """The number over `env`; raises `ExprDomainError` for a square root of a negative value or a division by
        zero, KeyError for a name `env` does not hold."""
        total = self.const
        for coef, factors in self.terms.values():
            term = coef
            for factor in factors:
                term *= _factor_value(factor, env)
            total += term
        return total

    def as_affine(self, sketch=""):
        """The same value as an `Affine` when it is linear in its names, else None."""
        terms = {}
        for coef, factors in self.terms.values():
            if len(factors) != 1 or not isinstance(factors[0], str):
                return None
            terms[factors[0]] = terms.get(factors[0], 0.0) + coef
        return Affine(self.const, terms, sketch)

    def single_factor(self):
        """The factor when the value is exactly one factor (coefficient 1, no constant), else None."""
        if self.const or len(self.terms) != 1:
            return None
        coef, factors = next(iter(self.terms.values()))
        return factors[0] if coef == 1.0 and len(factors) == 1 else None

    def split_constant(self):
        """(constant part, the rest)."""
        return self.const, Expr(0.0, self.terms)

    # --- arithmetic ----------------------------------------------------------------------------------------------

    def __add__(self, other):
        other = of(other)
        acc = _Acc(self.const + other.const)
        acc.add_terms(self.terms.values())
        acc.add_terms(other.terms.values())
        return acc.done()

    __radd__ = __add__

    def __neg__(self):
        return self.scaled(-1.0)

    def __sub__(self, other):
        return self + of(other).scaled(-1.0)

    def __rsub__(self, other):
        return of(other) - self

    def scaled(self, factor):
        factor = float(factor)
        if factor == 0.0:
            return Expr()
        return Expr(self.const * factor, {mk: (c * factor, f) for mk, (c, f) in self.terms.items()})

    def __mul__(self, other):
        other = of(other)
        if other.is_constant:
            return self.scaled(other.const)
        if self.is_constant:
            return other.scaled(self.const)
        acc = _Acc(self.const * other.const)
        for coef, factors in self.terms.values():
            acc.add_terms([(coef * other.const, factors)])
        for coef, factors in other.terms.values():
            acc.add_terms([(coef * self.const, factors)])
        for c1, f1 in self.terms.values():
            for c2, f2 in other.terms.values():
                acc.add(_monomial(c1 * c2, f1 + f2))
        return acc.done()

    __rmul__ = __mul__

    def __truediv__(self, other):
        return _divide(self, of(other))

    def __rtruediv__(self, other):
        return _divide(of(other), self)

    # --- substitution and files ----------------------------------------------------------------------------------

    def substitute(self, mapping):
        """The value with each name in `mapping` replaced by its `Expr` or number."""
        total = Expr(self.const)
        for coef, factors in self.parts():
            term = num(coef)
            for op, arg in factors:
                if op == "name":
                    term = term * (of(mapping[arg]) if arg in mapping else name(arg))
                else:
                    term = term * _apply(op, arg.substitute(mapping))
            total = total + term
        return total

    def json(self):
        """`{ "const": 2, "sum": [ { "k": 0.5, "of": ["d1", { "sin": {...} }] } ] }`."""
        return {"const": round9(self.const),
                "sum": [{"k": round9(c), "of": [arg if op == "name" else {op: arg.json()} for op, arg in factors]}
                        for c, factors in self.parts()]}

    @classmethod
    def from_json(cls, raw):
        total = num(raw.get("const", 0.0))
        for part in raw.get("sum") or []:
            term = num(part.get("k", 0.0))
            for factor in part.get("of") or []:
                if isinstance(factor, str):
                    term = term * name(factor)
                else:
                    (op, arg), = factor.items()
                    if op not in _FUNCTIONS:
                        raise ValueError("unknown function %r" % op)
                    term = term * _apply(op, cls.from_json(arg))
            total = total + term
        return total

    def text(self, name_text=None):
        """The formula as text, e.g. `d2 * cos(d3) + 4`. `name_text(name)` gives the text written for a name (the
        name itself by default); a text that is not a plain name or number is put in brackets."""
        writer = name_text or (lambda n: n)
        pieces = []
        for coef, factors in self.parts():
            top, bottom = [], []
            for op, arg in factors:
                if op == "name":
                    top.append(_wrapped(writer(arg)))
                elif op == "inv":
                    bottom.append(_wrapped(arg.text(writer)))
                else:
                    top.append("%s(%s)" % (op, arg.text(writer)))
            magnitude = abs(round9(coef))
            if magnitude == 0.0:
                continue
            if magnitude != 1.0 or not top:
                top.insert(0, _number_text(magnitude))
            body = " * ".join(top) + "".join(" / " + b for b in bottom)
            pieces.append((coef < 0, body))
        const = round9(self.const)
        if const or not pieces:
            pieces.append((const < 0, _number_text(abs(const))))
        out = ""
        for at, (negative, body) in enumerate(pieces):
            if at == 0:
                out = ("-" if negative else "") + body
            else:
                out += (" - " if negative else " + ") + body
        return out

    def __repr__(self):
        return "Expr(%s)" % self.text()


# --- building --------------------------------------------------------------------------------------------------------


def num(value):
    return Expr(float(value))


def name(text):
    """The value of one Fusion parameter (or input) name."""
    return Expr(0.0, {((0, text),): (1.0, (text,))})


def of(value):
    """An `Expr` from an `Expr` or a number."""
    if isinstance(value, Expr):
        return value
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError("not a number or Expr: %r" % (value,))
    return num(value)


def sqrt(value):
    """The square root; a constant is folded, a positive constant factor is moved out."""
    value = of(value)
    if value.is_constant:
        if value.const < 0:
            if value.const > -1e-12:
                return num(0.0)
            raise ExprDomainError("square root of a negative value")
        return num(math.sqrt(value.const))
    scale = _lead(value)
    if scale < 0:
        return _function("sqrt", value)
    inner = value.scaled(1.0 / scale)
    return _function("sqrt", inner).scaled(math.sqrt(scale))


def sin(value):
    return _trig("sin", of(value))


def cos(value):
    return _trig("cos", of(value))


def tan(value):
    return _trig("tan", of(value))


def _function(op, arg):
    factor = (op, arg)
    return Expr(0.0, {(_fkey(factor),): (1.0, (factor,))})


def _apply(op, arg):
    if op == "sqrt":
        return sqrt(arg)
    if op == "inv":
        return _divide(num(1.0), arg)
    return _trig(op, arg)


def _lead(value):
    """The coefficient of the first term in key order (the value's sign and scale for normalising)."""
    first = min(value.terms)
    return value.terms[first][0]


# Exact values at whole quarter turns, so `cos(90)` is 0 and not 6e-17.
_QUARTER = {"sin": (0.0, 1.0, 0.0, -1.0), "cos": (1.0, 0.0, -1.0, 0.0)}


def _trig(op, arg):
    """`sin`, `cos` or `tan` of `arg` in degrees. A constant is folded; a negative leading term is turned around
    (`sin(-u)` is `-sin(u)`) and whole quarter turns of the constant part are moved out."""
    if arg.is_constant:
        angle = arg.const % 360.0
        quarter = angle / 90.0
        if abs(quarter - round(quarter)) < 1e-12:
            q = int(round(quarter)) % 4
            if op == "tan":
                if q % 2:
                    raise ExprDomainError("tangent of a quarter turn")
                return num(0.0)
            return num(_QUARTER[op][q])
        return num({"sin": math.sin, "cos": math.cos, "tan": math.tan}[op](math.radians(angle)))
    sign = 1.0
    if _lead(arg) < 0:
        arg = -arg
        if op in ("sin", "tan"):
            sign = -1.0
    const, rest = arg.split_constant()
    turns = const / 90.0
    if abs(turns - round(turns)) < 1e-12:
        q = int(round(turns)) % 4
        if op == "tan":
            base = _function("tan", rest)
            return (base if q % 2 == 0 else -_divide(num(1.0), base)).scaled(sign)
        # sin(u + q*90) and cos(u + q*90) as +-sin(u) or +-cos(u)
        table = {"sin": (("sin", 1), ("cos", 1), ("sin", -1), ("cos", -1)),
                 "cos": (("cos", 1), ("sin", -1), ("cos", -1), ("sin", 1))}
        fn, s = table[op][q]
        return _function(fn, rest).scaled(sign * s)
    const = (const + 180.0) % 360.0 - 180.0
    return _function(op, rest + const).scaled(sign)


# --- normal form helpers ---------------------------------------------------------------------------------------------


def _factor_value(factor, env):
    if isinstance(factor, str):
        return float(env[factor])
    op, arg = factor
    value = arg.value(env)
    if op == "sqrt":
        if value < 0:
            if value > -1e-9 * (1.0 + abs(value)):
                return 0.0
            raise ExprDomainError("square root of a negative value")
        return math.sqrt(value)
    if op == "inv":
        if value == 0.0:
            raise ExprDomainError("division by zero")
        return 1.0 / value
    return {"sin": math.sin, "cos": math.cos, "tan": math.tan}[op](math.radians(value))


def _monomial(coef, factors):
    """`coef` times the product of `factors` as an Expr, with `x * inv(x)` cancelled and `sqrt(x) * sqrt(x)` turned
    into `x`."""
    factors = sorted(factors, key=_fkey)
    keys = [_fkey(f) for f in factors]
    for at, factor in enumerate(factors):
        if isinstance(factor, tuple) and factor[0] == "inv":
            inner = factor[1].single_factor()
            if inner is not None and _fkey(inner) in keys:
                other = keys.index(_fkey(inner))
                rest = [f for i, f in enumerate(factors) if i not in (at, other)]
                return _monomial(coef, rest)
        if isinstance(factor, tuple) and factor[0] == "sqrt" and keys.count(keys[at]) >= 2:
            other = keys.index(keys[at], at + 1)
            rest = [f for i, f in enumerate(factors) if i not in (at, other)]
            return _monomial(coef, rest) * factor[1]
    mk = tuple(keys)
    return Expr(0.0, {mk: (coef, tuple(factors))})


class _Acc:
    """Collects terms into a normal form."""

    def __init__(self, const=0.0):
        self.const = const
        self.terms = {}

    def add_terms(self, terms):
        for coef, factors in terms:
            if not factors:
                self.const += coef
                continue
            mk = tuple(_fkey(f) for f in factors)
            old = self.terms.get(mk)
            self.terms[mk] = ((old[0] if old else 0.0) + coef, factors)

    def add(self, expr):
        self.const += expr.const
        self.add_terms(expr.terms.values())

    def done(self):
        terms = {mk: t for mk, t in self.terms.items() if abs(t[0]) > _EPS}
        terms = _pythagoras(terms)
        const = self.const
        if isinstance(terms, tuple):
            terms, extra = terms
            const += extra.const
            acc = _Acc(const)
            acc.add_terms(terms.values())
            acc.add_terms(extra.terms.values())
            return acc.done()
        return Expr(0.0 if abs(const) < _EPS else const, terms)


def _pythagoras(terms):
    """`c * R * cos(u)^2 + c * R * sin(u)^2` becomes `c * R`. Returns the terms unchanged, or (terms, the Expr to
    add back) after one replacement."""
    for mk, (coef, factors) in terms.items():
        for at in range(len(factors) - 1):
            f = factors[at]
            if not (isinstance(f, tuple) and f[0] == "cos") or _fkey(factors[at + 1]) != _fkey(f):
                continue
            rest = factors[:at] + factors[at + 2:]
            partner = _monomial(1.0, rest + (("sin", f[1]), ("sin", f[1])))
            (pk, (_, pf)), = partner.terms.items()
            if pk in terms and abs(terms[pk][0] - coef) <= _EPS * max(1.0, abs(coef)):
                kept = {k: t for k, t in terms.items() if k not in (mk, pk)}
                return kept, _monomial(coef, rest)
    return terms


def _common_factors(value):
    """The factors every term of `value` holds (with repeats), or () when it has a constant or no terms."""
    if value.const or not value.terms:
        return ()
    common = None
    for _, factors in value.terms.values():
        keys = [_fkey(f) for f in factors]
        if common is None:
            common = list(zip(keys, factors))
            continue
        kept = []
        for key, factor in common:
            if key in keys:
                keys.remove(key)
                kept.append((key, factor))
        common = kept
    return tuple(common or ())


def _without(value, factors):
    """`value` with each of `factors` taken out of every term (they must be common)."""
    out = {}
    for _, (coef, own) in value.terms.items():
        rest = list(own)
        for key, _ in factors:
            at = [_fkey(f) for f in rest].index(key)
            rest.pop(at)
        mk = tuple(_fkey(f) for f in rest)
        out[mk] = (coef, tuple(rest))
    acc = _Acc(0.0)
    acc.add_terms(out.values())
    return acc.done()


def _divide(a, b):
    if b.is_constant:
        if b.const == 0.0:
            raise ExprDomainError("division by zero")
        return a.scaled(1.0 / b.const)
    if a.is_constant and a.const == 0.0:
        return Expr()
    common_b = _common_factors(b)
    if common_b and not a.const:
        a_keys = [k for k, _ in _common_factors(a)]
        shared = []
        for key, factor in common_b:
            if key in a_keys:
                a_keys.remove(key)
                shared.append((key, factor))
        if shared:
            a, b = _without(a, shared), _without(b, shared)
            if b.is_constant:
                return _divide(a, b)
    if not a.is_constant:
        ratio = _lead(a) / _lead(b)
        if a.scaled(1.0 / ratio).same(b):
            return num(ratio)
    if not b.const and len(b.terms) == 1:
        coef, factors = next(iter(b.terms.values()))
        out = a.scaled(1.0 / coef)
        for factor in factors:
            if isinstance(factor, tuple) and factor[0] == "inv":
                out = out * factor[1]
            else:
                inner = Expr(0.0, {(_fkey(factor),): (1.0, (factor,))})
                out = out * _function("inv", inner)
        return out
    lead = _lead(b)
    return a.scaled(1.0 / lead) * _function("inv", b.scaled(1.0 / lead))


def _number_text(value):
    value = round9(value)
    return str(int(value)) if value == int(value) else format(value, ".9f").rstrip("0").rstrip(".")


def _wrapped(text):
    return text if _ATOM.match(text) else "(" + text + ")"
