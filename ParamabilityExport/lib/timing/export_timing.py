"""The timing of one export: the phases of the export flow, the capture read and the size probe. `report()` is the
`timing` block of `report.json` (agent-docs/capture-format.md).

Phases are spans of the pipeline (`export_plan.pipeline`); one that runs more than once (a
translation per body, the probe's start and its tries) adds up. `after_stop` is the time of the second walk after a
stop (`translator.translate`), and it is inside the translate phases, as is `outline_check`, the time the translator
spends checking that written outlines do not cross themselves. The write of the package file comes after
`report.json` is made, so it is not in it (the add-in logs it).
"""
from .timer import Timer, rounded

PHASES = (
    "step_export",  # the STEP of the part as it is
    "capture",  # reading the timeline
    "size_table",  # the table of sizes from the dialog's parameters
    "translate_first",  # the first translation, and the one after the reach is known
    "reach",  # asking Fusion which step made the faces later steps pick
    "probe",  # the size probe: its start, its tries and its close
    "translate_final",  # the translation with the motion the probe found
    "restore",  # parameters, suppressed steps and the timeline marker put back
    "package",  # manifest, recipe and report assembled
    "after_stop",  # of which: the second walk after a stop, inside the translate phases
    "outline_check",  # of which: checking that written outlines do not cross themselves, inside the translate phases
)


class ExportTiming(Timer):
    """The `Timer` of one export. `note_capture` and `note_probe` keep the records of the readers' own timers."""

    def __init__(self, clock=None):
        super().__init__(*([clock] if clock else []))
        self.started = self._now()
        self.captures = []  # (part name or None, summary)
        self.probe = None
        self.undo = None  # `export_plan.undo_steps` record: whether the tries were kept out of Undo

    def _now(self):
        try:
            return self.clock()
        except Exception:
            return None

    def note_capture(self, summary, part=None, cached=False):
        """The `CaptureTimer.summary` of one capture read; `part` names the body of a several-body export, `cached`
        marks a read made earlier by the dialog (it is not part of this export's own time)."""
        try:
            if isinstance(summary, dict):
                self.captures.append((part, dict(summary, cached=True) if cached else summary))
        except Exception:
            pass

    def note_probe(self, summary):
        self.probe = summary if isinstance(summary, dict) else self.probe

    def report(self, parts=False):
        """The `timing` record, or None when it could not be made. Never raises."""
        try:
            return self._report(parts)
        except Exception:
            return None

    def _report(self, parts):
        out = {"total": rounded(self.clock() - self.started),
               "phases": {name: rounded(self.seconds(name)) for name in PHASES}}
        if parts:
            out["captures"] = [dict(summary, part=name) for name, summary in self.captures]
        elif self.captures:
            out["capture"] = self.captures[0][1]
        if self.probe is not None:
            out["probe"] = self.probe
        if self.undo is not None:
            out["undo"] = dict(self.undo)
        return out


def stamp(timing):
    """The clock reading at the start of the package assembly, or None when there is no timing or it fails."""
    try:
        return timing.clock() if timing is not None else None
    except Exception:
        return None


def attach(report, timing, started, parts=False):
    """Add the `timing` block to `report`, with the time since `started` (`stamp`) counted as the package phase. The
    report is written right after this, so the block ends here. Never raises: a failure leaves the field out."""
    try:
        if timing is None or started is None:
            return
        timing.add("package", timing.clock() - started)
        record = timing.report(parts)
        if record is not None:
            report["timing"] = record
    except Exception:
        pass
