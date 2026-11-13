"""The fake export ports: Fusion as the single body pipeline sees it (`pipeline.ExportPort`) and as the several body
pipeline sees it (`pipeline.PartsPort`). Both have every declared member; the options give the answers a test needs."""
import contextlib
import copy

from tests.fakes.store import FakeStore
from tests.translator_helpers import load_capture

# The design a port shows when a test names none: a box with a centred sketch.
BOX = load_capture("sketch_rect_centred")


def first_read(capture):
    """The probe state a design reads at its start: the sketches of the capture's profiles as captured (a profile
    without a sketch token has none to read)."""
    e0 = {"sketches": {}, "points": {}, "lines": {}, "params": {}}
    for item in capture["items"] if isinstance(capture, dict) else []:
        for profile in (item.get("data") or {}).get("profiles") or []:
            if "sketch_token" not in profile:
                continue
            e0["sketches"][profile["sketch_token"]] = {
                "frame": profile["frame"], "profiles": [{"loops": profile["loops"]}]}
    return e0


def shifted(read, dx):
    """The read with every sketch point moved `dx` along x."""
    out = copy.deepcopy(read)

    def move(node):
        if isinstance(node, dict):
            for key in ("start", "end", "center"):
                if isinstance(node.get(key), list):
                    node[key][0] += dx
            for value in node.values():
                move(value)
        elif isinstance(node, list):
            for value in node:
                move(value)

    move(out["sketches"])
    return out


def _user(capture):
    return (capture if isinstance(capture, dict) else BOX)["parameters"]["user"]


class _Ported:
    """What both fake ports share: the store, the units, the counters, the progress window, the sketch keeper, the
    warnings and the log. Each warning is kept: `warned` (parameters not put back), `left_off` (timeline steps not
    turned back on, with `undo_dropped`) and `warned_steps`; `shown` keeps every progress step and `verb` the last
    window's verb."""

    timing = None
    undo_steps = None
    read_timer = None

    def __init__(self, user, store, units, bad_when, fail_read_from, fail_step_at, cancel_at, keeper, reach, reader):
        self.store = store or FakeStore({p["name"]: p["expression"] for p in user}, bad_when=bad_when)
        self.units = units if units is not None else {p["name"]: p["unit"] for p in user}
        self.reads, self.steps, self.progressed = 0, 0, 0
        self.logs, self.warned, self.left_off, self.warned_steps, self.shown = [], [], [], [], []
        self.undo_dropped, self.verb = None, None
        self.fail_read_from, self.fail_step_at, self.cancel_at = fail_read_from, fail_step_at, cancel_at
        self.keeper, self.reach, self.reader = keeper, reach, reader

    def _count_read(self):
        self.reads += 1
        if self.fail_read_from is not None and self.reads >= self.fail_read_from:
            raise RuntimeError("Fusion would not answer")

    def _write_step(self, path, text):
        self.steps += 1
        if self.fail_step_at == self.steps:
            from lib.design_edit.errors import StepExportError
            raise StepExportError("Fusion did not write the STEP file.")
        with open(path, "wb") as f:
            f.write(text)

    def sketch_keeper(self, tokens):
        return self.keeper(tokens) if self.keeper is not None else None

    def progress(self, verb):
        outer = self
        self.verb = verb

        class Step:
            @staticmethod
            def step(*args):
                outer.progressed += 1
                if len(args) == 3:
                    outer.shown.append(tuple(args))
                return outer.cancel_at != outer.progressed

        return contextlib.nullcontext(Step())

    def warn_unrestored(self, names):
        self.warned.append(list(names))

    def warn_left_off(self, names, undo_dropped=False):
        self.left_off.append(list(names))
        self.undo_dropped = undo_dropped

    def warn_steps(self, lines):
        self.warned_steps.append(list(lines))

    def log(self, text):
        self.logs.append(text)


class FakePort(_Ported):
    """Fusion for one body: its `capture` (or the exception that stopped the read), a store over the capture's user
    parameters unless `store` is given, and a probe read that gives the capture's sketches as captured.

    reader(request): the read to give in place of that one; `e0` is the read as captured.
    fail_read_from: that read and every later one raise. drift: every read at the start values after the first comes
    back moved that far. fail_step_at: that STEP export fails. cancel_at: that progress step is cancelled.
    keeper(tokens): the sketch keeper to give (else none). reach(capture, gaps): the reach answer (else it raises).
    """

    def __init__(self, capture=BOX, store=None, units=None, bad_when=None, fail_read_from=None, drift=0.0,
                 fail_step_at=None, cancel_at=None, keeper=None, reach=None, reader=None):
        super().__init__(_user(capture), store, units, bad_when, fail_read_from, fail_step_at, cancel_at, keeper,
                         reach, reader)
        self.capture, self.drift = capture, drift
        self.start = dict(self.store.exprs)
        self.e0 = first_read(capture)

    def read_reach(self, capture, gaps):
        if self.reach is None:
            raise AssertionError("this fake port reads no reach")
        return self.reach(capture, gaps)

    def export_step(self, path):
        self._write_step(path, b"ISO-10303-21;")

    def read_capture(self):
        return self.capture

    def probe_reader(self):
        def read(request):
            self._count_read()
            if self.reader is not None:
                return self.reader(request)
            if self.drift and self.reads > 1 and self.store.exprs == self.start:
                return shifted(self.e0, self.drift)
            return self.e0
        return read


class FakePartsPort(_Ported):
    """Fusion for several bodies of one design: one capture per body (or the exception that stopped its read), one
    store over the user parameters of the first capture unless `store` is given, and probe reads that give each
    body's sketches as captured. The options are those of `FakePort`; `reach(index, capture, gaps)` answers for the
    body `index`, and `fail_read_from` counts the reads of every body."""

    def __init__(self, captures, store=None, units=None, bad_when=None, fail_read_from=None, fail_step_at=None,
                 cancel_at=None, keeper=None, reach=None, reader=None):
        first = next((c for c in captures if isinstance(c, dict)), BOX)
        super().__init__(_user(first), store, units, bad_when, fail_read_from, fail_step_at, cancel_at, keeper,
                         reach, reader)
        self.captures = captures
        self.count = len(captures)

    def body_names(self):
        return [c["target"]["name"] if isinstance(c, dict) else "Broken" for c in self.captures]

    def read_reach(self, index, capture, gaps):
        if self.reach is None:
            raise AssertionError("this fake port reads no reach")
        return self.reach(index, capture, gaps)

    def export_step(self, index, path):
        self._write_step(path, b"ISO-10303-21;%d" % index)

    def read_capture(self, index):
        return self.captures[index]

    def probe_reader(self, index):
        e0 = first_read(self.captures[index])

        def read(request):
            self._count_read()
            return self.reader(index, request) if self.reader is not None else e0
        return read
