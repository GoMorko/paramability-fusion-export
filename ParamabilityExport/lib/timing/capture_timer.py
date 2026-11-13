"""Where the time of one capture read goes. The read moves the timeline marker to every step, and Fusion rebuilds the
design at each move, so the time of a step is the marker move that built it plus what is read from it.

The reader notes, by span name:
- `total`: the whole read.
- `marker_moves` (the walk) and `marker_moves_helper` (the pass over the tool bodies): the marker assignments, one
  count each. Fusion rebuilds the design inside the assignment.
- `target_state`: the volume and box of the target at a marker position.
- `readers`: the feature readers of the steps, before and after the step.
- `helper_pass`: the whole pass over the tool bodies; `body_states` is the measuring of bodies inside it.
- `faces`: reads of a face outline; `split`: reads of Split Body steps. Both are inside `readers`.
- `restore_marker`: the move back to the person's marker; `tail`: what is read after the walk.
`step(index)` adds the time of one timeline step: the marker move that built it, its measures and its reads.
"""
from .timer import Timer, rounded

TOP = 10


class CaptureTimer(Timer):
    """The `Timer` of one capture read, plus the time of each timeline step."""

    def __init__(self, clock=None):
        super().__init__(*([clock] if clock else []))
        self.steps = {}  # timeline index -> seconds
        self.info = {}  # timeline index -> (name, type, component token)
        self.components = {}  # component token -> name

    def step(self, index):
        """`with timer.step(i):` adds the block's time to timeline step `i` (a negative index counts nothing)."""
        return _StepSpan(self, index)

    def describe(self, index, name, type_name, component):
        try:
            self.info[index] = (name, type_name, component or "")
        except Exception:
            pass

    def note_component(self, token, name):
        try:
            if token and name:
                self.components.setdefault(token, name)
        except Exception:
            pass

    def _labels(self):
        """{ component token: unique readable label }."""
        labels, used = {}, {}
        for token in {info[2] for info in self.info.values()}:
            name = self.components.get(token) or token or "unknown"
            if name in used and used[name] != token:
                name = "%s (%s)" % (name, token[-6:])
            used[name] = token
            labels[token] = name
        return labels

    def summary(self, top=TOP):
        """The compact record for `report.json` (`timing.capture`). Never raises: a failure gives None."""
        try:
            return self._summary(top)
        except Exception:
            return None

    def _summary(self, top):
        labels = self._labels()
        by_type, by_component = {}, {}
        for index, seconds in self.steps.items():
            name, type_name, component = self.info.get(index, ("", "unknown", ""))
            for table, key in ((by_type, type_name or "unknown"), (by_component, labels.get(component, "unknown"))):
                row = table.setdefault(key, [0, 0.0])
                row[0] += 1
                row[1] += seconds

        def table(rows):
            ordered = sorted(rows.items(), key=lambda pair: -pair[1][1])
            return {key: {"steps": count, "seconds": rounded(seconds)} for key, (count, seconds) in ordered}

        slowest = sorted(self.steps.items(), key=lambda pair: -pair[1])[:top]
        walk, helper = self.entry("marker_moves"), self.entry("marker_moves_helper")
        return {
            "seconds": rounded(self.seconds("total")),
            "steps": len(self.steps),
            "marker_moves": {"count": walk["count"] + helper["count"],
                             "seconds": rounded(self.seconds("marker_moves") + self.seconds("marker_moves_helper")),
                             "walk": walk["count"], "helper": helper["count"]},
            "measure": {"target_state": rounded(self.seconds("target_state")),
                        "body_states": rounded(self.seconds("body_states"))},
            "readers": self.entry("readers"),
            "faces": self.entry("faces"),
            "split": self.entry("split"),
            "helper_pass": rounded(self.seconds("helper_pass")),
            "restore_marker": rounded(self.seconds("restore_marker")),
            "tail": rounded(self.seconds("tail")),
            "by_type": table(by_type),
            "by_component": table(by_component),
            "slowest": [{"index": index, "name": self.info.get(index, ("",))[0],
                         "type": self.info.get(index, ("", ""))[1],
                         "component": labels.get(self.info.get(index, ("", "", ""))[2], "unknown"),
                         "seconds": rounded(seconds)} for index, seconds in slowest],
        }


class _StepSpan:
    def __init__(self, timer, index):
        self.timer, self.index, self.started = timer, index, None

    def __enter__(self):
        try:
            if self.index >= 0:
                self.started = self.timer.clock()
        except Exception:
            self.started = None
        return self

    def __exit__(self, *exc):
        if self.started is not None:
            try:
                steps = self.timer.steps
                steps[self.index] = steps.get(self.index, 0.0) + (self.timer.clock() - self.started)
            except Exception:
                pass
        return False
