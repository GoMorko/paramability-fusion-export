"""The motion file: how each written sketch value moves with the parameters. The translator reads it.

    { "version": 1,
      "values": {
        "4/p0/l0/width": { "const": 0, "terms": { "FilterBox_width_mm": 1 } },
        "9/p0/plane": { "const": 0, "terms": { "FilterBox_height_mm": 1 } },
        "12/p0/l0/points.2.1": { "stuck": ["angle_deg"], "cause": "curve", "sketch": "Sketch5" } },
      "box_max": { "min": [..], "max": [..] },
      "states": [ { "values": { "width": 2.0 }, "built": true } ],
      "apart": [ 3 ],
      "unmeasured": { "Sketch7": "its first read did not match the capture" },
      "untried": [ "FilterBox_width_mm" ],
      "refs": { "57.plane": "", "60.axis": "its first read did not match the capture" },
      "spans": { "width": { "low": 1.8, "high": 3.6, "failed": [ [0.9, "Chamfer3"] ] } } }

The keys are written by `sketch_values.keys`. `curves` lists the profiles (`<item>/p<profile>`) whose sketch curves were
measured.
`apart` lists the states (by number in `states`) where Fusion solved a sketch another way, so a different outline
there blames no size. `flipped` names the sketches that stayed on another outline after the values were put back. A stuck value may carry `rest`: what it follows once its `stuck` sizes are fixed. `terms` keys
are Fusion parameter names; `const` plus the terms give the value at any size settings. A key that is not listed
did not move: the translator writes the captured number, unless its sketch is in `unmeasured` (sketch name to the
reason the probe could not measure it): then nothing is known about it, and the sizes behind that sketch cannot be
followed (`sketch_values.coverage`). A motion file without `unmeasured` says nothing about such sketches.
`untried` lists the Fusion names of sizes that move a sketch but were left without probe rows: for them every sketch
answers `NOT_MEASURED`.

`refs` has one entry per measured reference the probe looked at (`<item>.<slot>`, `params.geometry_links.ref_key`):
an empty text when it was measured, else why it could not be. Its values are keyed `<item>/r/<slot>/...`: how far the
plane, axis or point moved from where the capture has it (zero at the current sizes), as an `Affine` of the sizes, or
a `Stuck` when it turned or the move does not fit. A measured reference without keys stayed where it is. A reference
that is not in `refs` was not looked at (a motion file written without references, or the first translation
of an export): nothing is known about it.

`spans` says, per size the probe set to other values, between which values it was really measured: `low` and `high`
are the lowest and highest values of the states that built (the value now included), `failed` lists each value tried
alone that Fusion could not rebuild, with the first step that failed there. A size whose `low` and `high` are its
value now and that has `failed` entries was not measured at all.

A value that follows its sizes along a curve the copy can write is a sum of products instead:
`{ "const": 2, "sum": [ { "k": 1, "of": [["", "wall", 1], ["cot", "angle", 0.5]] } ] }` is
`2 + wall * cot(angle / 2)` (`Terms`).

The translator reads this file; `probe.build` makes it.
"""
import math

from ..package.numbers import round9

VERSION = 1

CURVE, SHAPE, TURNS, UNREAD, UNTRIED = "curve", "shape", "turns", "unread", "untried"
CAUSES = (CURVE, SHAPE, TURNS, UNREAD, UNTRIED)

_EPS = 1e-12
# A term whose factor rounds to zero at the 9 decimals the files keep (the sum of two parts that cancel) is no term.
_TERM_EPS = 5e-10


class Stuck:
    """A value that cannot follow its sizes: the Fusion names of the sizes that move it, why, and its sketch.

    `rest` is the Affine the value follows once those sizes are fixed (the other sizes still move it), or None."""

    def __init__(self, movers, cause, sketch="", rest=None):
        self.movers = tuple(movers)
        self.cause = cause
        self.sketch = sketch
        self.rest = rest

    def json(self):
        out = {"stuck": list(self.movers), "cause": self.cause}
        if self.sketch:
            out["sketch"] = self.sketch
        if self.rest is not None:
            out["rest"] = self.rest.json()
        return out

    def __eq__(self, other):
        return isinstance(other, Stuck) and self.json() == other.json()

    def __repr__(self):
        return "Stuck(%r, %r, %r)" % (self.movers, self.cause, self.sketch)


class Affine:
    """`const + sum(a * parameter)` over Fusion parameter names (user parameters and model parameters)."""

    def __init__(self, const=0.0, terms=None, sketch=""):
        self.const = float(const)
        self.terms = {k: float(v) for k, v in (terms or {}).items() if abs(v) >= _TERM_EPS}
        self.sketch = sketch

    @property
    def is_constant(self):
        return not self.terms

    def scaled(self, factor):
        return Affine(self.const * factor, {k: v * factor for k, v in self.terms.items()}, self.sketch)

    def plus(self, other):
        """The sum with a number or another Affine."""
        if not isinstance(other, Affine):
            return Affine(self.const + other, self.terms, self.sketch)
        terms = dict(self.terms)
        for name, a in other.terms.items():
            terms[name] = terms.get(name, 0.0) + a
        return Affine(self.const + other.const, terms, self.sketch or other.sketch)

    def value(self, env):
        """The value over parameter values `env` (Fusion name to number)."""
        return self.const + sum(a * env[name] for name, a in self.terms.items())

    def json(self):
        out = {"const": round9(self.const), "terms": {k: round9(v) for k, v in self.terms.items()}}
        if self.sketch:
            out["sketch"] = self.sketch
        return out


# Functions of an angle size (in degrees) a `Terms` value may use; `cot` is cos / sin.
FUNCTIONS = ("sin", "cos", "tan", "cot")


def factor_value(factor, env):
    """The number of one factor `(function, name, scale)` over `env` (Fusion name to value): the size itself when the
    function is empty, else the function of `scale` times the angle size in degrees."""
    function, name, scale = factor
    value = env[name]
    if not function:
        return value
    angle = math.radians(scale * value)
    if function == "sin":
        return math.sin(angle)
    if function == "cos":
        return math.cos(angle)
    if function == "tan":
        return math.tan(angle)
    return math.cos(angle) / math.sin(angle)


class Terms:
    """`const + sum(coef * product of factors)`: a value that follows its sizes along a curve the copy can write. A
    factor is `(function, name, scale)`: a size (`function` empty, `scale` 1) or `sin`, `cos`, `tan` or `cot` of
    `scale` times an angle size in degrees (scale 1 or 0.5). `parts` are `(coef, factors)`."""

    def __init__(self, const=0.0, parts=(), sketch=""):
        self.const = float(const)
        self.parts = tuple((float(c), tuple(tuple(f) for f in factors)) for c, factors in parts if abs(c) > _EPS)
        self.sketch = sketch

    @property
    def is_constant(self):
        return not self.parts

    def names(self):
        """The Fusion names of the sizes the value reads, in order."""
        return tuple(dict.fromkeys(f[1] for _, factors in self.parts for f in factors))

    def value(self, env):
        total = self.const
        for coef, factors in self.parts:
            term = coef
            for factor in factors:
                term *= factor_value(factor, env)
            total += term
        return total

    def as_affine(self):
        """The same value as an `Affine` when every part is one size alone, else None."""
        terms = {}
        for coef, factors in self.parts:
            if len(factors) != 1 or factors[0][0] or factors[0][2] != 1.0:
                return None
            terms[factors[0][1]] = terms.get(factors[0][1], 0.0) + coef
        return Affine(self.const, terms, self.sketch)

    def held(self, values):
        """This value with the sizes in `values` (Fusion name to value) held there: their factors become numbers."""
        const, parts = self.const, []
        for coef, factors in self.parts:
            kept = []
            for factor in factors:
                if factor[1] in values:
                    coef *= factor_value(factor, values)
                else:
                    kept.append(factor)
            if kept:
                parts.append((coef, kept))
            else:
                const += coef
        return Terms(const, parts, self.sketch)

    def json(self):
        out = {"const": round9(self.const),
               "sum": [{"k": round9(c), "of": [[f[0], f[1], f[2]] for f in factors]} for c, factors in self.parts]}
        if self.sketch:
            out["sketch"] = self.sketch
        return out

    @classmethod
    def from_json(cls, raw):
        parts = [(p.get("k", 0.0), [(f[0], f[1], float(f[2])) for f in p.get("of") or []]) for p in raw.get("sum") or []]
        return cls(raw.get("const", 0.0), parts, raw.get("sketch", ""))

    def __repr__(self):
        return "Terms(%r, %r)" % (self.const, self.parts)


class Motion:
    """What the probe found: a value per key (Affine or Stuck), the union of the target boxes and the states tried."""
    optimistic = False

    def __init__(self, values=None, box_max=None, states=None, dropped=None, curves=None, apart=None,
                 unmeasured=None, untried=None, refs=None, body_moved=None, spans=None, flipped=None):
        self.values = dict(values or {})
        self.box_max = box_max
        self.states = list(states or [])
        self.dropped = list(dropped or [])  # columns left out of the fit, `{ name, reason }`
        self.curves = set(curves or ())  # profiles whose sketch curves were measured, `<item>/p<profile>`
        self.apart = list(apart or [])  # numbers in `states` where Fusion solved a sketch another way
        # names of the sketches that stayed on another outline after the values were put back
        self.flipped = list(flipped or [])
        self.unmeasured = dict(unmeasured or {})  # sketch name to why the probe could not measure it
        self.untried = list(untried or [])  # Fusion names of sizes that moved a sketch and were not tried
        self.refs = dict(refs or {})  # reference key to "" (measured) or why it could not be measured
        # Fusion names of sizes that changed the body (its box) in a try but moved no followed sketch or reference
        self.body_moved = list(body_moved or [])
        # Fusion name to { low, high, failed }: the values a size was measured between, and the ones that did not build
        self.spans = dict(spans or {})

    def get(self, key):
        """`Affine`, `Terms`, `Stuck`, or None when the value did not move."""
        return self.values.get(key)

    def json(self):
        out = {"version": VERSION, "values": {k: v.json() for k, v in self.values.items()}}
        if self.box_max is not None:
            out["box_max"] = self.box_max
        out["states"] = self.states
        if self.dropped:
            out["dropped"] = self.dropped
        if self.curves:
            out["curves"] = sorted(self.curves)
        if self.apart:
            out["apart"] = list(self.apart)
        if self.flipped:
            out["flipped"] = list(self.flipped)
        if self.unmeasured:
            out["unmeasured"] = dict(self.unmeasured)
        if self.untried:
            out["untried"] = list(self.untried)
        if self.refs:
            out["refs"] = dict(self.refs)
        if self.body_moved:
            out["body_moved"] = list(self.body_moved)
        if self.spans:
            out["spans"] = {name: dict(span) for name, span in self.spans.items()}
        return out

    @classmethod
    def from_json(cls, data):
        values = {}
        for key, raw in (data.get("values") or {}).items():
            if "sum" in raw:
                values[key] = Terms.from_json(raw)
                continue
            if "stuck" in raw:
                rest = raw.get("rest")
                values[key] = Stuck(raw["stuck"], raw.get("cause", UNREAD), raw.get("sketch", ""),
                                    Affine(rest.get("const", 0.0), rest.get("terms"), raw.get("sketch", ""))
                                    if isinstance(rest, dict) else None)
            else:
                values[key] = Affine(raw.get("const", 0.0), raw.get("terms"), raw.get("sketch", ""))
        return cls(values, data.get("box_max"), data.get("states"), data.get("dropped"), data.get("curves"),
                   data.get("apart"), data.get("unmeasured"), data.get("untried"), data.get("refs"),
                   data.get("body_moved"), data.get("spans"), data.get("flipped"))


class _Optimistic(Motion):
    """The first translation of an export: sketch values are written as numbers and nothing is fixed for them."""
    optimistic = True


OPTIMISTIC = _Optimistic()

