"""Build the motion file from the states read at other size settings. Pure.

A state is `{ "values": { Fusion name: manifest number }, "built": bool, "read": READ, "e0": bool }`. `values` holds the
kept sizes that differ from the current settings (a size that is missing stays at its current value). `read` is the
probe state of `fusion_reader.probe_state` (sketches, points, lines, params in Fusion's own units, box). Exactly one
state has `"e0": true`: the read at the current settings, before any size is changed. A state that is not `built`
(Fusion could not build the part there) is left out of the fit.

A sketch can have more than one solution, and Fusion may land on another one depending on the rows run before. When
a sketch reads as the same different outline in states that change different sizes, none of those sizes made it:
those states blame no size for that outline (`Motion.apart`).
"""
from . import columns as cols
from . import fit, match, plan
from ..sketch_values import coverage
from ..sketch_values.motion import CURVE, SHAPE, TURNS, UNREAD, Affine, Motion, Stuck

_SAME = 1e-9
_PRIORITY = (TURNS, SHAPE, UNREAD)


class _Run:
    """The states of one export, lined up with E0 first."""

    def __init__(self, capture, states):
        self.found = plan.scan(capture)
        self.e0 = next((s for s in states if s.get("e0")), None)
        self.base = (self.e0 or {}).get("read")
        self.states = [self.e0 or {"values": {}, "e0": True}] + [s for s in states if not s.get("e0")]
        self.targets = []
        self.apart = set()
        self._values = {}
        self.readable = set()
        if self.base:
            self.readable = match.readable(self.found, self.base)
            self.targets = [t for t in self.found.targets if t["sketch_token"] in self.readable]

    def varied(self, at, current=None):
        """Fusion names of the sizes that state `at` sets to other values than E0 has."""
        base = self.states[0].get("values") or {}
        out = set()
        for name, value in (self.states[at].get("values") or {}).items():
            before = base.get(name, (current or {}).get(name, value))
            if abs(value - before) > _SAME:
                out.add(name)
        return out

    def built(self, at):
        return self.states[at].get("built") is not False

    def values_at(self, target, at):
        """`(values, cause)` of a target in state `at`; (None, None) for a state that was not built."""
        key = (id(target), at)
        if key not in self._values:
            self._values[key] = self._read_values(target, at)
        return self._values[key]

    def _read_values(self, target, at):
        if not self.built(at):
            return None, None
        read = self.states[at].get("read")
        values, cause = match.state_values(target, read, self.base) if read else (None, UNREAD)
        if values is not None and values.keys() != match.captured_values(target).keys():
            return None, SHAPE
        return values, cause

    def find_apart(self, current=None):
        """The states where a sketch reads as the same different outline as in a state that changes other sizes."""
        for token in dict.fromkeys(t["sketch_token"] for t in self.targets):
            shaped = [at for at in range(1, len(self.states))
                      if any(self.values_at(t, at)[1] == SHAPE for t in self.targets if t["sketch_token"] == token)]
            reads = {at: self.states[at]["read"]["sketches"].get(token) for at in shaped}
            for i, a in enumerate(shaped):
                for b in shaped[i + 1:]:
                    sizes_a, sizes_b = self.varied(a, current), self.varied(b, current)
                    if (sizes_a and sizes_b and not sizes_a & sizes_b and isinstance(reads[a], dict)
                            and isinstance(reads[b], dict) and match.same_read(reads[a], reads[b])):
                        self.apart.update((a, b))


def _moved(a, b):
    return abs(a - b) > fit.TOLERANCE


def moved_sizes(capture, states, current=None):
    """Fusion names of the sizes whose state (the only size that differs) moved a covered sketch value.

    `current` gives the size values of E0 for a size its `values` does not list (`plan.state_values`)."""
    run = _Run(capture, states)
    moved = []
    for at in range(1, len(run.states)):
        names = run.varied(at, current)
        if len(names) != 1 or names <= set(moved):
            continue
        for target in run.targets:
            values, _ = run.values_at(target, at)
            want = match.captured_values(target)
            if values and any(_moved(values[k], v) for k, v in want.items()):
                moved.extend(names)
                break
    return moved


def _box_max(states):
    boxes = [s["read"]["box"] for s in states
             if s.get("built") is not False and isinstance((s.get("read") or {}).get("box"), dict)
             and len(s["read"]["box"].get("min") or ()) == 3 and len(s["read"]["box"].get("max") or ()) == 3]
    if not boxes:
        return None
    return {"min": [min(b["min"][i] for b in boxes) for i in range(3)],
            "max": [max(b["max"][i] for b in boxes) for i in range(3)]}


def _movers(run, series, current):
    """Sizes whose own state moved the value; when only a state of several sizes moved it, all of those."""
    single, several = [], []
    for at in range(1, len(series)):
        if series[at] is None or not _moved(series[at], series[0]):
            continue
        names = run.varied(at, current)
        (single if len(names) == 1 else several).extend(sorted(names))
    return list(dict.fromkeys(single or several))


def _blocked(problems):
    """The sizes behind the states that could not be read. A state of several sizes adds nothing when a size of it
    already fails alone, since that size stays fixed and the state cannot happen."""
    alone = set().union(*[p[1] for p in problems if len(p[1]) == 1])
    several = [p[1] for p in problems if len(p[1]) != 1 and not p[1] & alone]
    return sorted(alone.union(*several))


def build(capture, table, states):
    """The `Motion` of a capture. See the module text for `states`."""
    run = _Run(capture, states)
    current = {e.name: e.value for e in table.entries}
    out = Motion(box_max=_box_max(states),
                 states=[{"values": s.get("values") or {}, "built": s.get("built") is not False}
                         for s in run.states[1:]],
                 unmeasured=coverage.unmeasured(run.found, run.readable, bool(run.base)))
    if not run.targets:
        return out
    overrides = [s.get("values") or {} for s in run.states]
    reads = [s.get("read") for s in run.states]
    envs = [cols.size_env(table, o) for o in overrides]
    dropped = []
    shared = cols.user_columns(table, overrides, envs, reads, dropped)
    models = cols.model_columns(table, envs, reads, dropped)
    out.dropped = dropped
    run.find_apart(current)
    out.apart = sorted(at - 1 for at in run.apart)
    for target in run.targets:
        _fit_target(out, run, target, shared, models, current)
    out.curves = {match.prefix(t) for t in run.targets if t["kind"] == "profile"}
    return out


def _fit_target(out, run, target, shared, models, current):
    want = match.captured_values(target)
    series = {key: [value] for key, value in want.items()}
    problems = []
    for at in range(1, len(run.states)):
        values, cause = run.values_at(target, at)
        for key in want:
            series[key].append(None if values is None else values[key])
        if values is None and cause and not (cause == SHAPE and at in run.apart):
            problems.append((cause, run.varied(at, current)))
    sketch = target["sketch"]
    plane = (target.get("reference") or {}).get("token") or ""
    candidates = shared + [m.ranked(sketch, plane) for m in models]
    stuck_causes = [c for c in _PRIORITY if any(p[0] == c for p in problems)]
    blocked = _blocked(problems)
    for key, x in series.items():
        movers = _movers(run, x, current)
        if problems:
            # The states that failed are left out: the value may still follow the other sizes.
            rest = fit.fit_value(x, candidates)
            if rest.kind == "affine":
                out.values[key] = Stuck(blocked, stuck_causes[0], sketch, Affine(rest.const, rest.terms, sketch))
            elif rest.kind == "const":
                out.values[key] = Stuck(blocked, stuck_causes[0], sketch)
            else:
                out.values[key] = Stuck(dict.fromkeys(blocked + movers), stuck_causes[0], sketch)
            continue
        result = fit.fit_value(x, candidates)
        if result.kind == "affine":
            out.values[key] = Affine(result.const, result.terms, sketch)
        elif result.kind == "stuck":
            out.values[key] = Stuck(movers, result.cause or CURVE, sketch)
