"""Build the motion file from the states read at other size settings. Pure.

A state is `{ "values": { Fusion name: manifest number }, "built": bool, "read": READ, "e0": bool }`. `values` holds the
kept sizes that differ from the current settings (a size that is missing stays at its current value). `read` is the
probe state of `fusion_reader.probe_state` (sketches, points, lines, params in Fusion's own units, box). Exactly one
state has `"e0": true`: the read at the current settings, before any size is changed. A state that is not `built`
(Fusion could not build the part there) is left out of the fit; its `failed` names the first step that failed.

A sketch can have more than one solution, and Fusion may land on another one depending on the rows run before (a row
that did not build often leaves it there). A size is blamed for a different outline only by its own row (the row that
changes that size alone), when the row started from the right outline and the outline came back once the values were
put back. A state may carry `start`: the read of the design after the values were put back and before its row ran.
Without it, the row started where the row before it ended (E0 for the first row), and the next row (or `after`, the
read once all rows are done) tells whether the outline came back. A different outline that blames no size this way is
listed in `Motion.apart`. A sketch known to have stayed on its other outline across a restore (a `start` read shows it,
or it reads as the same other outline in rows of unrelated sizes) is named in `Motion.flipped`.
When a sketch reads as the same different outline in states that change different sizes, none of those sizes made it
either.
"""
from . import columns as cols
from . import match, plan, ref_fit
from .series import fit_series, moved as _moved
from ..sketch_values import coverage
from ..sketch_values.motion import SHAPE, UNREAD, Motion

_SAME = 1e-9


class StateRun:
    """The states of one export, lined up with E0 first."""

    def __init__(self, capture, states, current=None, after=None):
        self.current = current
        self.after = after
        self.found = plan.scan(capture)
        self.e0 = next((s for s in states if s.get("e0")), None)
        self.base = (self.e0 or {}).get("read")
        self.states = [self.e0 or {"values": {}, "e0": True}] + [s for s in states if not s.get("e0")]
        self.targets = []
        self.apart = set()
        self.apart_tokens = set()  # sketches that read as the same other outline in rows of unrelated sizes
        self._values = {}
        self.readable = set()
        if self.base:
            self.readable = match.readable(self.found, self.base)
            self.targets = [t for t in self.found.targets if t["sketch_token"] in self.readable
                            and (t["kind"] != "path" or match.matches_capture(t, self.base))]

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

    def mislabelled(self, at):
        """True when the read of state `at` shows a size at another value than its row set: the read belongs to
        another row, so it tells nothing about this one. Each parameter's read is scaled to the size's own units by
        its read and value at E0."""
        values = self.states[at].get("values") or {}
        read = (self.states[at].get("read") or {}).get("params") or {}
        first = (self.base or {}).get("params") or {}
        for name, value in values.items():
            now, before = read.get(name), first.get(name)
            if not all(isinstance(v, (int, float)) for v in (now, before)) or name not in (self.current or {}):
                continue
            if abs(before) <= _SAME:
                continue
            scale = self.current[name] / before
            if abs(now * scale - value) > 1e-6 * max(1.0, abs(value)):
                return True
        return False

    def values_at(self, target, at):
        """`(values, cause)` of a target in state `at`; (None, None) for a state that was not built."""
        key = (id(target), at)
        if key not in self._values:
            self._values[key] = self._read_values(target, at)
        return self._values[key]

    def _read_values(self, target, at):
        if not self.built(at) or self.mislabelled(at):
            return None, None
        read = self.states[at].get("read")
        values, cause = match.state_values(target, read, self.base) if read else (None, UNREAD)
        if values is not None and values.keys() != match.captured_values(target).keys():
            return None, SHAPE
        return values, cause

    def outline_right(self, token, read):
        """True when every followed record of the sketch `token` reads as the captured outline in `read`. A sweep
        path is not an outline."""
        if not isinstance(read, dict):
            return False
        for target in self.targets:
            if target["sketch_token"] == token and target["kind"] != "path":
                values, _ = match.state_values(target, read, self.base)
                if values is None or values.keys() != match.captured_values(target).keys():
                    return False
        return True

    def started_right(self, token, at):
        """True when the row of state `at` is known to have started on the captured outline of the sketch."""
        start = self.states[at].get("start")
        if isinstance(start, dict):
            return self.outline_right(token, start)
        before = at - 1
        if before == 0:
            return True
        return self.built(before) and self.outline_right(token, self.states[before].get("read"))

    def came_back(self, token, at):
        """True when the sketch is known to read as captured again once the values of state `at` were put back."""
        after = at + 1
        if after >= len(self.states):
            return self.after is not None and self.outline_right(token, self.after)
        start = self.states[after].get("start")
        if isinstance(start, dict):
            return self.outline_right(token, start)
        return self.built(after) and self.outline_right(token, self.states[after].get("read"))

    def shape_blames(self, token, at):
        """True when the different outline of the sketch in state `at` blames the size of that row: its own row,
        started on the right outline, and the outline came back after it."""
        return (len(self.varied(at, self.current)) == 1 and self.started_right(token, at)
                and self.came_back(token, at))

    def find_flips(self):
        """Adds to `apart` the states whose different outline blames no size, and returns the names of the sketches
        known to have stayed on another outline across a restore: a `start` read on another outline, or the same
        different read in rows of unrelated sizes (`find_apart`)."""
        flipped = []
        for token in dict.fromkeys(t["sketch_token"] for t in self.targets):
            name = next(t["sketch"] for t in self.targets if t["sketch_token"] == token)
            if token in self.apart_tokens:
                flipped.append(name)
            for at in range(1, len(self.states)):
                start = self.states[at].get("start")
                if isinstance(start, dict) and not self.outline_right(token, start):
                    flipped.append(name)
                if (not self.built(at) or self.mislabelled(at)
                        or self.outline_right(token, self.states[at].get("read"))):
                    continue
                if not self.shape_blames(token, at):
                    self.apart.add(at)
        return list(dict.fromkeys(flipped))

    def find_apart(self, current=None):
        """The states where a sketch reads as the same different outline as in another state that changes other
        sizes, or the same sizes to other values. A sketch that reads exactly alike at two values of a size does not
        follow that size there: it landed on another solution."""
        for token in dict.fromkeys(t["sketch_token"] for t in self.targets):
            shaped = [at for at in range(1, len(self.states))
                      if any(self.values_at(t, at)[1] == SHAPE for t in self.targets if t["sketch_token"] == token)]
            reads = {at: self.states[at]["read"]["sketches"].get(token) for at in shaped}
            for i, a in enumerate(shaped):
                for b in shaped[i + 1:]:
                    if (self._unrelated(a, b, current) and isinstance(reads[a], dict) and isinstance(reads[b], dict)
                            and match.same_read(reads[a], reads[b])):
                        self.apart.update((a, b))
                        self.apart_tokens.add(token)

    def _unrelated(self, a, b, current):
        """True when states `a` and `b` change no size to the same value: other sizes, or the same ones elsewhere."""
        sizes_a, sizes_b = self.varied(a, current), self.varied(b, current)
        if not sizes_a or not sizes_b:
            return False
        values_a, values_b = self.states[a].get("values") or {}, self.states[b].get("values") or {}
        return all(abs(values_a[n] - values_b[n]) > _SAME for n in sizes_a & sizes_b)


def moved_sizes(capture, states, current=None):
    """Fusion names of the sizes whose state (the only size that differs) moved a covered sketch value.

    `current` gives the size values of E0 for a size its `values` does not list (`plan.state_values`)."""
    run = StateRun(capture, states)
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


def _state_record(state):
    out = {"values": state.get("values") or {}, "built": state.get("built") is not False}
    if state.get("failed"):
        out["failed"] = state["failed"]
    return out


def spans(states, current):
    """`Motion.spans`: per size a state sets to another value than `current` has, the lowest and highest value of the
    states that built (the current value included), and `[value, step]` for each state that set it alone and did not
    build."""
    out = {}
    for state in states:
        values = state.get("values") or {}
        moved = {n: v for n, v in values.items() if n in current and abs(v - current[n]) > _SAME}
        for name, value in moved.items():
            span = out.setdefault(name, {"low": current[name], "high": current[name], "failed": []})
            if state.get("built") is not False:
                span["low"], span["high"] = min(span["low"], value), max(span["high"], value)
            elif len(moved) == 1:
                span["failed"].append([value, state.get("failed") or ""])
    return out


def build(capture, table, states, after=None):
    """The `Motion` of a capture. See the module text for `states` and `after`."""
    current = {e.name: e.value for e in table.entries}
    run = StateRun(capture, states, current, after)
    out = Motion(box_max=_box_max(states), states=[_state_record(s) for s in run.states[1:]],
                 unmeasured=coverage.unmeasured(run.found, run.readable, bool(run.base)),
                 spans=spans(run.states[1:], current))
    refs = ref_fit.measurable(plan.refs(capture), run.base)
    out.refs = refs.notes
    if not run.targets and not refs.usable:
        return out
    overrides = [s.get("values") or {} for s in run.states]
    reads = [s.get("read") for s in run.states]
    envs = [cols.size_env(table, o) for o in overrides]
    dropped = []
    shared = cols.user_columns(table, overrides, envs, reads, dropped)
    models = cols.model_columns(table, envs, reads, dropped)
    out.dropped = dropped
    run.find_apart(current)
    out.flipped = run.find_flips()
    out.apart = sorted(at - 1 for at in run.apart)
    for target in run.targets:
        _fit_target(out, run, target, shared, models, current)
    out.curves = {match.prefix(t) for t in run.targets if t["kind"] in ("profile", "path")}
    for ref in refs.usable:
        ref_fit.fit_ref(out, ref, [s.get("read") for s in run.states], [run.built(at) for at in range(len(run.states))],
                        shared, models, lambda at: run.varied(at, current))
    return out


def _fit_target(out, run, target, shared, models, current):
    want = match.captured_values(target)
    series = {key: [value] for key, value in want.items()}
    problems = []
    for at in range(1, len(run.states)):
        values, cause = run.values_at(target, at)
        for key in want:
            series[key].append(None if values is None else values[key])
        if values is None and cause and not (cause == SHAPE and (at in run.apart
                                                                 or not run.shape_blames(target["sketch_token"], at))):
            problems.append((cause, run.varied(at, current)))
    sketch = target["sketch"]
    plane = (target.get("reference") or {}).get("token") or ""
    candidates = shared + [m.ranked(sketch, plane) for m in models]
    fit_series(out.values, series, problems, candidates, lambda at: run.varied(at, current), sketch)
