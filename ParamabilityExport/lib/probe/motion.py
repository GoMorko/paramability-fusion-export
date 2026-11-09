"""The motion file: how each written sketch value moves with the parameters. The translator reads it.

    { "version": 1,
      "values": {
        "4/p0/l0/width": { "const": 0, "terms": { "FilterBox_width_mm": 1 } },
        "9/p0/plane": { "const": 0, "terms": { "FilterBox_height_mm": 1 } },
        "12/p0/l0/points.2.1": { "stuck": ["angle_deg"], "cause": "curve", "sketch": "Sketch5" } },
      "box_max": { "min": [..], "max": [..] },
      "states": [ { "values": { "width": 2.0 }, "built": true } ],
      "apart": [ 3 ],
      "unmeasured": { "Sketch7": "its first read did not match the capture" } }

The keys are written by `probe.keys`. `curves` lists the profiles (`<item>/p<profile>`) whose sketch curves were
measured.
`apart` lists the states (by number in `states`) where Fusion solved a sketch another way, so a different outline
there blames no size. A stuck value may carry `rest`: what it follows once its `stuck` sizes are fixed. `terms` keys
are Fusion parameter names; `const` plus the terms give the value at any size settings. A key that is not listed
did not move: the translator writes the captured number, unless its sketch is in `unmeasured` (sketch name to the
reason the probe could not measure it): then nothing is known about it, and the sizes behind that sketch cannot be
followed (`probe.coverage`). A motion file without `unmeasured` says nothing about such sketches.

Imports nothing from the translator at module level, since the translator imports this module.
"""
import re

VERSION = 1

CURVE, SHAPE, TURNS, UNREAD, UNTRIED = "curve", "shape", "turns", "unread", "untried"
CAUSES = (CURVE, SHAPE, TURNS, UNREAD, UNTRIED)

_EPS = 1e-12


def _n(value):
    return round(value, 9) + 0.0


def _text(value):
    value = _n(value)
    return str(int(value)) if value == int(value) else repr(value)


_ATOM = re.compile(r"^(?:[A-Za-z_][A-Za-z0-9_]*|\d+(?:\.\d+)?)$")


def _wrapped(text):
    return text if _ATOM.match(text) else "(" + text + ")"


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
        self.terms = {k: float(v) for k, v in (terms or {}).items() if abs(v) > _EPS}
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
        out = {"const": _n(self.const), "terms": {k: _n(v) for k, v in self.terms.items()}}
        if self.sketch:
            out["sketch"] = self.sketch
        return out

    def render(self, table):
        """The value as a `Quantity` over the sizes of `table`, or a `Stuck` ("unread") when a parameter cannot be
        written as a formula. A fixed or constant parameter becomes its number and joins the constant; a formula
        reads the free sizes it depends on."""
        from ..translator.values import Quantity
        constant = total = self.const
        parts, reads = [], []
        for name, a in self.terms.items():
            tr = table.translate(name)
            if not tr.ok:
                return Stuck(table.depends(name) or tr.reads, UNREAD, self.sketch)
            total += a * tr.value
            if tr.reads:
                parts.append((a, tr.formula))
                reads.extend(tr.reads)
            else:
                constant += a * tr.value
        if not parts:
            return Quantity(_n(constant))
        return Quantity(total, _formula(parts, constant), tuple(dict.fromkeys(reads)))


def _formula(parts, constant):
    """`parts` are (coefficient, formula) pairs, written as a sum: `0.5 * w - offset + 2`."""
    out = ""
    for at, (a, text) in enumerate(parts):
        if abs(a) == 1:
            body = text if a > 0 else _wrapped(text)
        else:
            body = "%s * %s" % (_text(abs(a)), _wrapped(text))
        if at == 0:
            out = ("-" if a < 0 else "") + body
        else:
            out += (" - " if a < 0 else " + ") + body
    if abs(constant) > _EPS:
        out += (" - " if constant < 0 else " + ") + _text(abs(constant))
    return out


class Motion:
    """What the probe found: a value per key (Affine or Stuck), the union of the target boxes and the states tried."""
    optimistic = False

    def __init__(self, values=None, box_max=None, states=None, dropped=None, curves=None, apart=None,
                 unmeasured=None):
        self.values = dict(values or {})
        self.box_max = box_max
        self.states = list(states or [])
        self.dropped = list(dropped or [])  # columns left out of the fit, `{ name, reason }`
        self.curves = set(curves or ())  # profiles whose sketch curves were measured, `<item>/p<profile>`
        self.apart = list(apart or [])  # numbers in `states` where Fusion solved a sketch another way
        self.unmeasured = dict(unmeasured or {})  # sketch name to why the probe could not measure it

    def get(self, key):
        """`Affine`, `Stuck`, or None when the value did not move."""
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
        if self.unmeasured:
            out["unmeasured"] = dict(self.unmeasured)
        return out

    @classmethod
    def from_json(cls, data):
        values = {}
        for key, raw in (data.get("values") or {}).items():
            if "stuck" in raw:
                rest = raw.get("rest")
                values[key] = Stuck(raw["stuck"], raw.get("cause", UNREAD), raw.get("sketch", ""),
                                    Affine(rest.get("const", 0.0), rest.get("terms"), raw.get("sketch", ""))
                                    if isinstance(rest, dict) else None)
            else:
                values[key] = Affine(raw.get("const", 0.0), raw.get("terms"), raw.get("sketch", ""))
        return cls(values, data.get("box_max"), data.get("states"), data.get("dropped"), data.get("curves"),
                   data.get("apart"), data.get("unmeasured"))


class _Optimistic(Motion):
    """The first translation of an export: sketch values are written as numbers and nothing is fixed for them."""
    optimistic = True


OPTIMISTIC = _Optimistic()


def build(capture, table, states):
    """The `Motion` of a capture from the states read at other size settings. See `probe.build.build`."""
    from . import build as builder
    return builder.build(capture, table, states)
