"""Shadow mode of reading sketches directly: what the solver (`sketch_solve`) says about each sketch of an export, set
against what the probe measured in Fusion. Pure, no Fusion calls, and it changes nothing the export writes.

`shadow` solves each sketch graph record of the capture (`capture.sketch_graphs`) at size settings made from the
user parameters, puts the solved values under the probe's keys (`derived_keys`) and expresses each over the recipe's
size names. Then, for every state the probe read, it works out the same values at that state's sizes and compares them
with the numbers read there, and with the formulas the measured fit found (`Motion`). The result is the `derived`
block of `report.json`:

    { "version": 1,
      "summary": { "sketches": 4, "derived": 3, "partly": 1, "not_derived": 0, "values": 21, "agree": 21,
                   "disagree": 0, "skipped": 0, "errors": 0 },
      "sketches": [ { "sketch", "token", "outcome", "solver_outcome", "reason"?, "values", "reasons", "formulas",
                      "leaves", "constants", "assumptions", "compare", "keys", "solver" } ] }

`outcome` is `derived` when every key of the sketch's profiles, hole points and axis lines has a formula or numbers,
`partly` when some do, `not_derived` when none do (or the solver gave up); `solver_outcome` is the solver's own
verdict on points and radii. A sketch that no step reads has no keys, so `outcome` is the solver's. `reasons` counts
the keys with no values by code. A sketch past `MAX_ENTITIES`, or one whose solving stopped on an error, is recorded
as not derived with `skipped` or `error`.
"""
from collections import Counter

from ..package.numbers import round9
from ..params import geometry_links
from ..params.size_table import DERIVED, FREE
from ..sketch_solve.outcome import DERIVED as SOLVED, NOT_DERIVED, PARTLY
from ..sketch_solve.solve import solve_sketch
from ..sketch_values.motion import Affine, Stuck, Terms
from . import derived_keys as dk
from . import derived_sizes as sizes
from . import match
from .build import StateRun
from .fit import TOLERANCE

VERSION = 1
# The most points and curves of a sketch that are worked out; a larger sketch is skipped.
MAX_ENTITIES = 400
MAX_SKETCHES = 60
# Measured inputs (projected values) a sketch's formulas are fitted over; each costs two settings.
MAX_INPUTS = 40
# Keys listed in a sketch record, and disagreements listed in its comparison.
MAX_KEYS = 300
MAX_LISTED = 12


def _origin_axis(record, curve):
    """True for a projected line through the sketch origin that the sketch's lists did not hold: an axis of the
    component's origin, which no size moves."""
    origin = next((p for p in record.get("points") or [] if p.get("origin")), None)
    if curve.get("kind") != "line" or not curve.get("implicit") or origin is None:
        return False
    points = {p["id"]: p["xy"] for p in record.get("points") or [] if "id" in p and p.get("xy")}
    try:
        (ax, ay), (bx, by) = points[curve["points"][0]], points[curve["points"][1]]
    except (KeyError, TypeError, ValueError):
        return False
    length = ((bx - ax) ** 2 + (by - ay) ** 2) ** 0.5
    ox, oy = origin["xy"]
    return length > 0 and abs((bx - ax) * (oy - ay) - (by - ay) * (ox - ax)) / length < 1e-6


def constants_of(record, linked):
    """The refs of the projected entities that no size moves, for `solve_sketch`: a projection of another component
    when no parameter reaches the sketch through that component (`linked` false), and the origin's axes. Other
    projections stay measured inputs: a size can move the body edge or sketch they come from."""
    points = {p["id"]: p for p in record.get("points") or [] if isinstance(p, dict) and "id" in p}
    out = []
    for curve in record.get("curves") or []:
        reference = curve.get("reference")
        if not isinstance(reference, dict):
            continue
        if (reference.get("source") == "other" and not linked) or _origin_axis(record, curve):
            out.append(("curve", curve["id"]))
            out.extend(("point", p) for p in list(curve.get("points") or []) + [curve.get("center")]
                       if isinstance(p, int) and p in points)
    for pid, point in points.items():
        reference = point.get("reference")
        if isinstance(reference, dict) and reference.get("source") == "other" and not linked:
            out.append(("point", pid))
    return out


class _Key:
    """One key with values: its formula over size names (`expr`, None when it has numbers only), `kind` ("const",
    "affine", "curved" or "numeric"), the sizes it reads (Fusion names) and what else it reads."""

    def __init__(self, key, expr, why, leaves, table):
        self.key, self.expr, self.why = key, expr, why
        names = expr.names() if expr is not None else ()
        self.inputs = [n for n in names if n.startswith("@")]
        self.unread = [n for n in names if n in leaves and not n.startswith("@")]
        self.sizes = _free_sizes(table, names)
        self.kind = ("numeric" if expr is None else "const" if expr.is_constant
                     else "affine" if expr.as_affine() is not None else "curved")

    def json(self):
        if self.expr is None:
            return {"numbers": True, "why": self.why}
        out = {"formula": self.expr.text(), "kind": self.kind}
        if self.inputs:
            out["inputs"] = self.inputs
        if self.unread:
            out["unread_dimensions"] = self.unread
        return out


def _free_sizes(table, names):
    """Fusion names of the free sizes that the recipe size names (or Fusion names) in `names` follow."""
    by_name = {}
    for e in table.entries:
        if e.state == FREE:
            by_name[e.size_name] = {e.name}
        elif e.state == DERIVED and e.size_name:
            by_name[e.size_name] = set(e.reads)
    out = set()
    for name in names:
        out |= by_name.get(name, set())
    return out


def _round(value):
    return round9(value) if isinstance(value, (int, float)) and abs(value) < 1e15 else None


class _Context:
    """What one `shadow` call works over: the capture, the size table, the probe states lined up (`StateRun`) and
    the measured motion."""

    def __init__(self, capture, table, states, motion):
        self.capture, self.table, self.motion = capture, table, motion
        self.run = StateRun(capture, states, {e.name: e.value for e in table.entries})
        try:
            self.linked = {link["sketch"] for link in geometry_links.reach(capture)}
        except Exception:
            self.linked = set()
        self._envs = {}

    def size_env(self, at):
        """Size values by recipe name at probe state `at`."""
        if at not in self._envs:
            self._envs[at] = sizes.size_env(self.table, self.run.states[at].get("values") or {})
        return self._envs[at]

    def frame_of(self, token):
        """The frame of a sketch in the first read, or None."""
        return (((self.run.base or {}).get("sketches") or {}).get(token) or {}).get("frame")


def shadow(capture, table, states, motion=None):
    """The `derived` block for a capture, its size table, the probe states (`SizeProbe.states`) and the measured
    `Motion` (None when it could not be built). None when the capture has no sketch graphs."""
    graphs = capture.get("sketch_graphs") if isinstance(capture, dict) else None
    if not isinstance(graphs, list) or not graphs:
        return None
    ctx = _Context(capture, table, states, motion)
    out = []
    for number, record in enumerate(graphs):
        named = record if isinstance(record, dict) else {}
        head = {"sketch": named.get("sketch") or "", "token": named.get("token") or ""}
        if number >= MAX_SKETCHES:
            out.append(dict(head, outcome=NOT_DERIVED,
                            skipped="only the first %d sketches are worked out" % MAX_SKETCHES))
            continue
        if not isinstance(record, dict):
            out.append(dict(head, outcome=NOT_DERIVED, reason="the sketch record is missing"))
            continue
        try:
            out.append(_Sketch(ctx, named, head).record())
        except Exception as exc:  # one sketch never stops the export
            out.append(dict(head, outcome=NOT_DERIVED, error=("%s: %s" % (type(exc).__name__, exc))[:300]))
    return {"version": VERSION, "summary": _summary(out), "sketches": out}


def _summary(records):
    outcomes = Counter(r["outcome"] for r in records)
    compare = [r["compare"] for r in records if "compare" in r]
    return {"sketches": len(records), SOLVED: outcomes[SOLVED], PARTLY: outcomes[PARTLY],
            NOT_DERIVED: outcomes[NOT_DERIVED],
            "values": sum(r.get("values", {}).get("derived", 0) for r in records),
            "agree": sum(c["agree"] for c in compare), "disagree": sum(c["disagree"] for c in compare),
            "skipped": sum(1 for r in records if "skipped" in r), "errors": sum(1 for r in records if "error" in r)}


def log_line(block):
    """One line for the add-in log about a `derived` block."""
    s = block["summary"]
    return ("sketch reading, shadow: %d sketches, %d derived, %d partly, %d not; %d values derived, %d agree with the "
            "read, %d disagree, %d skipped, %d errors"
            % (s["sketches"], s[SOLVED], s[PARTLY], s[NOT_DERIVED], s["values"], s["agree"], s["disagree"],
               s["skipped"], s["errors"]))


class _Sketch:
    """One sketch of the capture: its solution, the key values drawn from it and the comparison with the probe."""

    def __init__(self, ctx, record, head):
        self.ctx, self.record_in, self.head = ctx, record, head
        self.table = ctx.table
        self.formulas = sizes.dimension_formulas(self.table, record)
        self.overrides = sizes.override_sets(sizes.moving_sizes(self.table, self.formulas))
        self.linked = head["sketch"] in ctx.linked
        self.constants = constants_of(record, self.linked)
        self.solution = None
        self.results = []  # (derivation, { key: _Key })
        self.open = {}  # key -> (code, reason)

    # ---- the solution and the keys drawn from it ------------------------------------------------------------

    def leaf_env(self, overrides):
        """Leaf name to number at the size `overrides` (Fusion name to number): the dimensions that can be worked out
        there, and the measured inputs as they are. At the current sizes every leaf has its value."""
        leaves = self.solution.leaves
        if not overrides:
            return {n: leaf.value for n, leaf in leaves.items()}
        inputs = {n: leaf.value for n, leaf in leaves.items() if leaf.kind == "input"}
        return dict(inputs, **sizes.leaf_values(self.formulas, sizes.size_env(self.table, overrides)))

    def _solve(self):
        settings = [sizes.leaf_values(self.formulas, sizes.size_env(self.table, o)) for o in self.overrides]
        self.solution = solve_sketch(self.record_in, settings or None, self.constants)

    def _derive(self):
        """The keys of each probe target of the sketch that have values, with their formulas over size names."""
        solution, token = self.solution, self.head["token"]
        drawing = dk.Drawing(self.record_in, solution)
        envs = [self.leaf_env(o) for o in [{}] + self.overrides]
        unvaried = self._vary_inputs(envs)
        substitute = {n: f.expr for n, f in self.formulas.items() if f.expr is not None and n in solution.leaves}
        for target in (t for t in self.ctx.run.found.targets if t["sketch_token"] == token and t["kind"] != "path"):
            derivation = dk.derivation(target, drawing, self.ctx.frame_of(token))
            keys, open_ = _keys(target, derivation, envs[0])
            self.open.update(open_)
            found = derivation.formulas(keys, envs) if keys else {}
            made = {}
            for key in keys:
                expr, why = found.get(key, (None, "it has no formula"))
                if expr is not None and unvaried.intersection(expr.names()):
                    expr, why = None, "it reads projected values that were not varied"
                made[key] = _Key(key, expr.substitute(substitute) if expr is not None else None, why, solution.leaves,
                                 self.table)
            self.results.append((derivation, made))

    def _vary_inputs(self, envs):
        """Adds to `envs` a setting for each measured input moved up and one moved down by a quarter of its value (at
        least 1), so a formula that reads an input can be fitted. The solver never moves inputs, since how a
        projection moves is not known; the formulas it gives hold for any values of them. Returns the inputs left
        unvaried because there are more than `MAX_INPUTS`."""
        names = [n for n, leaf in self.solution.leaves.items() if leaf.kind == "input"]
        for name in names[:MAX_INPUTS]:
            value = self.solution.leaves[name].value
            step = max(0.25 * abs(value), 1.0)
            envs.extend(dict(envs[0], **{name: value + sign * step}) for sign in (1.0, -1.0))
        return set(names[MAX_INPUTS:])

    def record(self):
        count = len(self.record_in.get("points") or []) + len(self.record_in.get("curves") or [])
        if count > MAX_ENTITIES:
            return dict(self.head, outcome=NOT_DERIVED,
                        skipped="the sketch has %d points and curves, more than the %d that are worked out"
                        % (count, MAX_ENTITIES))
        self._solve()
        self._derive()
        solution = self.solution
        infos = {k: i for _, made in self.results for k, i in made.items()}
        out = dict(self.head, outcome=solution.outcome, solver_outcome=solution.outcome)
        if solution.reason:
            out["reason"] = solution.reason
        out["values"] = {"derived": len(infos), "not_derived": len(self.open)}
        out["reasons"] = dict(Counter(code for code, _ in self.open.values()))
        out["formulas"] = dict(Counter(i.kind for i in infos.values()))
        out["leaves"] = _leaves(solution, self.formulas)
        if self.constants:
            out["constants"] = ["%s%d" % ("p" if kind == "point" else "c", i) for kind, i in self.constants]
        if solution.assumptions:
            out["assumptions"] = [{"text": a.text, "flips": list(a.flips)} for a in solution.assumptions]
        out["solver_open"] = dict(Counter(v.code for pair in solution.points.values() for v in pair if not v.derived)
                                  + Counter(v.code for v in solution.radii.values() if not v.derived))
        if infos or self.open:
            out["outcome"] = SOLVED if infos and not self.open else PARTLY if infos else NOT_DERIVED
            out["keys"] = _listed(infos, self.open)
        out["compare"] = _Compare(self).summary()
        out["solver"] = solution.json()
        return out


def _keys(target, derivation, env):
    """`(derived keys, { key: (code, reason) } of the keys with no values)` of a probe target. The sketch plane is
    not counted: it is no value of the sketch's own."""
    open_, keys = {}, []
    now = derivation.direct(env)
    for key in match.captured_values(target):
        found = derivation.code_of(key)
        if found is None and (now is None or key not in now):
            found = (dk.NO_MATCH, "the outline drawn from the solution is not the captured outline")
        if found is None:
            keys.append(key)
        elif found[0] != dk.PLANE:
            open_[key] = found
    return keys, open_


def _listed(infos, open_):
    out = {key: info.json() for key, info in list(infos.items())[:MAX_KEYS]}
    for key, (code, reason) in list(open_.items())[:max(0, MAX_KEYS - len(out))]:
        out[key] = {"open": code, "reason": reason}
    return out


def _leaves(solution, formulas):
    out = {}
    for name, leaf in solution.leaves.items():
        record = leaf.json()
        found = formulas.get(name)
        if leaf.kind == "dimension" and found is not None:
            record["formula"] = found.text if found.usable else None
            if not found.usable:
                record["why"] = found.reason
        out[name] = record
    return out


# ---- comparison with what was read -----------------------------------------------------------------------------

def _kind_of(measured):
    """The measured fit of a key as one of "const" (it did not move), "affine", "curved" or "stuck"."""
    if measured is None:
        return "const"
    if isinstance(measured, Affine):
        return "affine" if measured.terms else "const"
    if isinstance(measured, Terms):
        return "affine" if measured.as_affine() is not None else "curved"
    return "stuck"


def _measured_sizes(table, measured):
    """Fusion names of the free sizes a measured fit follows."""
    names = (measured.terms if isinstance(measured, Affine) else measured.names() if isinstance(measured, Terms)
             else measured.movers if isinstance(measured, Stuck) else ())
    out = set()
    for name in names:
        out |= set(table.depends(name))
    return out


class _Compare:
    """The derived values of a sketch at every state the probe read, against the numbers read there and the formulas
    the measured fit found."""

    def __init__(self, sketch):
        self.sketch, self.ctx = sketch, sketch.ctx
        self.stat = {}  # key -> [times compared, worst difference, first disagreement]
        self.off = []  # formula against the numbers drawn from the solution
        self.skipped = 0
        self.states = set()
        self.fit = Counter()
        self.fit_listed = []
        total = sum(len(made) for _, made in sketch.results)
        self.total = total
        for derivation, made in sketch.results:
            if any(derivation.target is t for t in self.ctx.run.targets):
                self._states(derivation, made)
                self._against_fit(derivation, made)
            else:
                self.skipped += len(made)

    def _states(self, derivation, made):
        run, solution = self.ctx.run, self.sketch.solution
        for at in range(len(run.states)):
            measured, _ = run.values_at(derivation.target, at)
            if measured is None:
                continue
            overrides = run.states[at].get("values") or {}
            direct = derivation.direct(self.sketch.leaf_env(overrides))
            env = dict(self.ctx.size_env(at), **{n: l.value for n, l in solution.leaves.items()
                                                  if l.kind == "input" or not overrides})
            for key, info in made.items():
                if key in measured:
                    self._one(at, overrides, key, info, measured[key], direct, env)

    def _one(self, at, overrides, key, info, read, direct, env):
        got = self._number(info, key, direct, env, overrides)
        if got is None:
            return
        self.states.add(at)
        diff = abs(got - read)
        entry = self.stat.setdefault(key, [0, 0.0, None])
        entry[0] += 1
        entry[1] = max(entry[1], diff)
        if diff > TOLERANCE and entry[2] is None:
            entry[2] = {"key": key, "state": at, "derived": _round(got), "read": _round(read), "sizes": dict(overrides)}
            if info.inputs:
                entry[2]["reads_inputs"] = True
        if (info.expr is not None and direct is not None and key in direct and abs(got - direct[key]) > TOLERANCE
                and len(self.off) < MAX_LISTED):
            self.off.append({"key": key, "state": at, "formula": _round(got), "numbers": _round(direct[key])})

    @staticmethod
    def _number(info, key, direct, env, overrides):
        """The number a key has at a state: its formula over the state's sizes, else the numbers drawn from the
        solution; None when it has none there (a dimension that could not be written reads only at the first state)."""
        if info.expr is None:
            return None if direct is None else direct.get(key)
        if info.unread and overrides:
            return None
        try:
            return info.expr.value(env)
        except dk.EVAL_ERRORS:
            return None

    def _against_fit(self, derivation, made):
        motion = self.ctx.motion
        if motion is None:
            return
        table = self.ctx.table
        unmeasured = derivation.target["sketch"] in (getattr(motion, "unmeasured", None) or {})
        for key, info in made.items():
            measured = motion.get(key)
            if info.expr is None:
                verdict = "numbers_only"
            elif unmeasured or _kind_of(measured) == "stuck":
                verdict = "derived_only"
            else:
                same_kind = (_kind_of(measured) in ("const", "affine")) == (info.kind in ("const", "affine"))
                verdict = "same" if same_kind and _measured_sizes(table, measured) == info.sizes else "differs"
            self.fit[verdict] += 1
            if verdict == "differs" and len(self.fit_listed) < MAX_LISTED:
                self.fit_listed.append({"key": key, "derived": info.kind, "derived_sizes": sorted(info.sizes),
                                        "measured": _kind_of(measured),
                                        "measured_sizes": sorted(_measured_sizes(table, measured))})

    def summary(self):
        bad = [e[2] for e in self.stat.values() if e[2] is not None]
        out = {"states": len(self.states), "values": self.total, "compared": len(self.stat),
               "agree": len(self.stat) - len(bad), "disagree": len(bad),
               "never_compared": self.total - len(self.stat) - self.skipped,
               "max_diff": _round(max([e[1] for e in self.stat.values()] or [0.0])), "listed": bad[:MAX_LISTED]}
        if self.skipped:
            out["target_not_read"] = self.skipped
        if self.off:
            out["formula_off"] = self.off
        if self.fit:
            out["measured_fit"] = dict(self.fit)
            if self.fit_listed:
                out["measured_fit_listed"] = self.fit_listed
        return out
