"""What one translation keeps while it walks: the recipe so far, the formulas it bound, and what each size did.

A value that follows sizes is written as a formula over Orca variables (`bind`); the variables are the sizes of the
size table those formulas read, written at the end. A value that some size moves but that Orca cannot follow keeps
its number, and the sizes are recorded with the reason (`doubt`), so the result can say why a parameter stayed fixed.
"""
import re

from ..orca_recipe.enums import BooleanMode, FeatureType
from ..params.expressions.text import format_number
from ..params.size_table import DERIVED, FREE
from .formulas import OrcaFormulaError, to_orca, variable_names
from .solid import Solid


class Value:
    """A number to write and, when sizes move it, the app formula over size names and the Fusion names it reads."""

    def __init__(self, number, formula=None, reads=()):
        self.number = float(number)
        self.formula = formula
        self.reads = tuple(reads)

    def scaled(self, factor):
        """The value times a number; the formula keeps up."""
        if self.formula is None or factor == 1:
            return Value(self.number * factor, self.formula, self.reads)
        if factor == -1:
            return Value(-self.number, "-(%s)" % self.formula, self.reads)
        return Value(self.number * factor, "%r * (%s)" % (float(factor), self.formula), self.reads)

    def magnitude(self):
        return self.scaled(-1) if self.number < 0 else self


class Context:
    """The state of one translation. `table` is the export's size table (None: no sizes, every value a number)."""

    def __init__(self, capture, table, place):
        self.capture, self.table, self.place = capture, table, place
        self.features = []
        self.items = []
        self.left_out = []
        self.notes = []
        self.bound = []  # {feature, field, formula, reads}
        self.follows = {}  # Fusion name -> [where]
        self.doubts = {}  # Fusion name -> [reason]
        # The bodies: the exported part, and tool bodies while a step builds them (`push`). The handlers work on the
        # innermost one (`solid`, `has_body`, `target`). `bodies` is Orca's list of bodies at this point of the recipe.
        self.part = Body(capture.get("target"), "part")
        self.scopes = [self.part]
        self.bodies = []
        self.written = {}  # timeline index -> the features its step wrote
        self.shapes = {}  # timeline index -> [(mode, shape)] its step added to the body it built
        # A step may change what an earlier step wrote (a round drawn into an earlier outline, `outline_rounds`):
        # `undo` holds a function per change that puts it back (`rollback` runs them), and `reshaped` the steps whose
        # features no longer stand for that step alone (timeline index -> why a copy of them would be wrong).
        self.undo = []
        self.reshaped = {}
        # Rounds and chamfers left out whose edges the copy could measure (`outline_rounds.note_left_out`): timeline
        # index -> where each may have changed the part.
        self.left_corners = {}
        # Outlines built from plane cuts (`outline_cuts`): timeline index -> the `outline_cuts.Built` records of its
        # step, so a pattern can write them again into its tool body.
        self.cut_built = {}
        # Outlines that rounds of side edges cut corner tools from (`corner_hosts`): timeline index of the extrude ->
        # a `corner_hosts.Host` for each time the extrude was written (a tool body may be written more than once);
        # and timeline index of each such round -> the Hosts it changed.
        self.corner_hosts = {}
        self.corner_steps = {}
        # The solved sketches (`sketch_sizes.sketch_formulas`): id of the sketch graph record -> `SketchFormulas` or None.
        self.sketch_formulas = {}
        sizes = list(table.sizes) if table is not None else []
        self.names = variable_names(sizes)
        self._orca_sizes = self._writable_sizes()

    # ---- the sizes Orca can hold ------------------------------------------------------------------------------

    def _writable_sizes(self):
        """`{size name: Orca formula or None}`: a free size is its number, a derived size its formula when Orca can
        hold it and every size it reads can be held too, else None."""
        out = {}
        if self.table is None:
            return out
        entries = {e.size_name: e for e in self.table.entries if e.size_name in self.table.sizes}
        pending = dict(entries)
        while pending:
            done = []
            for size, e in pending.items():
                if e.state == FREE:
                    out[size] = format_number(e.value)
                elif e.state != DERIVED:
                    out[size] = None
                else:
                    reads = [n for n in _names_in(e.formula) if n in entries and n != size]
                    if any(n in pending for n in reads):
                        continue
                    try:
                        out[size] = to_orca(e.formula, {n: self.names[n] for n in reads if out.get(n) is not None})
                    except OrcaFormulaError:
                        out[size] = None
                done.append(size)
            if not done:
                out.update(dict.fromkeys(pending))
                break
            for size in done:
                del pending[size]
        return out

    def variables(self):
        """The Orca variables the bound formulas read, with every variable those read: `{name: formula}`."""
        wanted, out = [], {}
        reverse = {v: k for k, v in self.names.items()}
        todo = [n for b in self.bound for n in _names_in(b["formula"]) if n in reverse]
        while todo:
            name = todo.pop()
            if name in out:
                continue
            text = self._orca_sizes.get(reverse[name])
            out[name] = text
            wanted.append(name)
            todo.extend(n for n in _names_in(text) if n in reverse and n not in out)
        return {name: out[name] for name in sorted(wanted, key=lambda n: list(self.names.values()).index(n))}

    def size_entry(self, size_name):
        return next((e for e in self.table.entries if e.size_name == size_name), None)

    # ---- values ------------------------------------------------------------------------------------------------

    def quantity(self, item, path, number, dim="length"):
        """The `Value` of a feature value that Fusion keeps as a model parameter (`data.params[path]`). A value whose
        expression reads no size is its number; one whose formula cannot be written is its number with a doubt."""
        if self.table is None:
            return Value(number)
        found = ((item.get("data") or {}).get("params") or {}).get(path)
        if not isinstance(found, dict) or not isinstance(found.get("expression"), str):
            return Value(number)
        unit = self.table.unit_of(found.get("name") or "")
        tr = self.table.translate(found["expression"], expected=float(found.get("value", number)), dim=dim,
                                  unit=unit)
        if not tr.reads:
            return Value(number)
        if not tr.ok:
            self.doubt(tr.reads, "%s: %s" % (item.get("name") or "a step", tr.reason))
            return Value(number)
        return Value(number, tr.formula, tr.reads)

    def bind(self, feature, field, value, where):
        """Write `value` into the feature's field and, when it follows sizes and Orca can hold its formula, bind the
        field to it. Otherwise the number stays and the sizes get the reason."""
        setattr(feature, field, value.number)
        if value.formula is None:
            return False
        try:
            text = self.orca_formula(value.formula)
        except OrcaFormulaError as exc:
            self.doubt(value.reads, "%s stays a number in Orca: %s" % (where, exc))
            return False
        feature.bind(field, text)
        self.bound.append({"feature": feature.name, "field": field, "formula": text, "reads": list(value.reads)})
        for name in value.reads:
            self.follows.setdefault(name, [])
            if where not in self.follows[name]:
                self.follows[name].append(where)
        return True

    def orca_formula(self, formula):
        """The Orca formula of an app formula over size names; raises `OrcaFormulaError` when Orca cannot hold it."""
        held = {n: self.names[n] for n, text in self._orca_sizes.items() if text is not None}
        return to_orca(formula, held)

    def doubt(self, names, reason):
        """These Fusion sizes move something that keeps its number in Orca, for `reason`."""
        for name in names:
            found = self.doubts.setdefault(name, [])
            if reason not in found:
                found.append(reason)

    def depends(self, param_names):
        """Fusion names of the free sizes behind parameters (user or model)."""
        if self.table is None:
            return ()
        out = {}
        for name in param_names:
            out.update(dict.fromkeys(sorted(self.table.depends(name))))
        return tuple(out)

    def add(self, feature):
        """Append a feature; returns its index. A feature that starts a body gives the innermost body its place in
        Orca's list; one that works on a body names it when it is not the last one (Orca's default)."""
        scope = self.scope
        if _starts_body(feature, self.bodies):
            scope.index = len(self.bodies)
            self.bodies.append(scope)
        elif feature.type not in _NO_BODY and feature.target_body == -1 and scope.index is not None \
                and scope.index != len(self.bodies) - 1:
            feature.target_body = scope.index
        self.features.append(feature)
        return len(self.features) - 1

    # ---- bodies ------------------------------------------------------------------------------------------------

    @property
    def scope(self):
        return self.scopes[-1]

    @property
    def solid(self):
        """The shape of the body the handlers work on, to check cuts before they are written."""
        return self.scope.solid

    @property
    def has_body(self):
        return self.scope.has_body

    @has_body.setter
    def has_body(self, value):
        self.scope.has_body = value

    @property
    def target(self):
        """The capture record of the body the handlers work on."""
        return self.scope.target

    def push(self, body):
        """Work on another body (a tool) until `pop`."""
        self.scopes.append(body)
        return body

    def pop(self):
        return self.scopes.pop()

    def consume(self, body):
        """A body Orca takes away (a Combine's tool): it leaves the list, and the bodies after it move up."""
        if body in self.bodies:
            self.bodies.remove(body)
        body.index = None
        for n, other in enumerate(self.bodies):
            other.index = n

    def checkpoint(self):
        """The state to go back to when a step that writes several features turns out not to copy."""
        return (len(self.features), len(self.bound), len(self.notes), {k: list(v) for k, v in self.follows.items()},
                {k: list(v) for k, v in self.doubts.items()}, list(self.bodies),
                [(b, b.index, b.has_body, list(b.solid.pieces)) for b in set(self.bodies) | set(self.scopes)],
                list(self.scopes), [(v, dict(v)) for v in self.items], len(self.undo))

    def rollback(self, mark):
        features, bound, notes, follows, doubts, bodies, states, scopes, verdicts, undo = mark
        while len(self.undo) > undo:
            self.undo.pop()()
        for verdict, was in verdicts:
            verdict.clear()
            verdict.update(was)
        del self.features[features:]
        del self.bound[bound:]
        del self.notes[notes:]
        self.follows, self.doubts = follows, doubts
        self.bodies[:] = bodies
        for body, index, has_body, pieces in states:
            body.index, body.has_body, body.solid.pieces = index, has_body, pieces
        self.scopes[:] = scopes


def _names_in(text):
    return re.findall(r"[A-Za-z_][A-Za-z0-9_]*", text or "")


class Body:
    """One body of the copy: the capture record it stands for (`target`), its shape so far (`solid`), whether a step
    has made it yet, and its place in Orca's list of bodies (`index`, None until a step makes it)."""

    def __init__(self, target, label=""):
        self.target = target
        self.label = label
        self.solid = Solid()
        self.has_body = False
        self.index = None
        # The steps that changed the body's edges in ways `solid` does not show (rounds, chamfers, threads), as
        # `finish_body` records them.
        self.finishes = []


# Features that build no body, and those that start a new one (Orca's `produces_body` and `route_feature`).
_NO_BODY = frozenset((FeatureType.SKETCH, FeatureType.HELIX, FeatureType.PLANE, FeatureType.AXIS,
                      FeatureType.COORD_SYS, FeatureType.PROJECT))
_MAY_START = frozenset((FeatureType.EXTRUDE, FeatureType.REVOLVE, FeatureType.SWEEP, FeatureType.LOFT))


def _starts_body(feature, bodies):
    if feature.type in _NO_BODY:
        return False
    if not bodies or feature.type == FeatureType.IMPORT:
        return True
    return feature.type in _MAY_START and feature.mode == BooleanMode.NEW
