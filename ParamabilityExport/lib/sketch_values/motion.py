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

The keys are written by `sketch_values.keys`. `curves` lists the profiles (`<item>/p<profile>`) whose sketch curves were
measured.
`apart` lists the states (by number in `states`) where Fusion solved a sketch another way, so a different outline
there blames no size. A stuck value may carry `rest`: what it follows once its `stuck` sizes are fixed. `terms` keys
are Fusion parameter names; `const` plus the terms give the value at any size settings. A key that is not listed
did not move: the translator writes the captured number, unless its sketch is in `unmeasured` (sketch name to the
reason the probe could not measure it): then nothing is known about it, and the sizes behind that sketch cannot be
followed (`sketch_values.coverage`). A motion file without `unmeasured` says nothing about such sketches.

The translator reads this file; `probe.build` makes it.
"""
from ..package.numbers import round9

VERSION = 1

CURVE, SHAPE, TURNS, UNREAD, UNTRIED = "curve", "shape", "turns", "unread", "untried"
CAUSES = (CURVE, SHAPE, TURNS, UNREAD, UNTRIED)

_EPS = 1e-12


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
        out = {"const": round9(self.const), "terms": {k: round9(v) for k, v in self.terms.items()}}
        if self.sketch:
            out["sketch"] = self.sketch
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

