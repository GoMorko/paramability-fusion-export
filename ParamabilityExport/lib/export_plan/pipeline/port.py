"""What the pipeline takes in and gives out: the port to Fusion, the request and the result."""
from dataclasses import dataclass, field
from typing import Optional, Protocol


class ExportPort(Protocol):
    """What the pipeline needs from Fusion. The command passes the real one, tests pass a fake.

    store: the parameter store (`apply.apply_row_values` and `restore.restore_parameters` list what it needs, plus
      `saved_expressions`).
    units: {parameter name: Fusion unit string}.
    export_step(path): write the STEP of the picked body as the design is now.
    read_capture(): the capture dict of the picked body, or the exception that stopped the read.
    read_reach(capture, gaps): the `reach` of the capture when the steps at the timeline indexes `gaps` are left out
      of the copy (`read_gap_reach.read_reach`); raises `MarkerError` when the timeline marker cannot go back.
    probe_reader(): a callable `read(request)` giving one probe state, or raising.
    sketch_keeper(tokens): optional; an object that keeps the sketches `tokens` as they are now and whose
      `put_back()` moves their points back there (`fusion_reader.sketch_keep.SketchKeeper`, `ProbeRun`).
    timing: optional; the `timing.export_timing.ExportTiming` of this export. The pipeline makes its own when the port
      has none; a port that reads the capture with a `CaptureTimer` hands its summary to it (`note_capture`).
    progress(verb): a context manager whose value has `step(index, total, name)`; the step returns False when the
      person cancelled.
    warn_unrestored(names): tell the person that these parameters could not be put back, when the export stops.
    warn_left_off(names, undo_dropped): optional; tell the person that these timeline steps, turned off for the tries
      (`timeline_trim`), could not be turned back on; `undo_dropped` is True when Fusion forgot Undo data
      (`undo_dropped`), so Undo is not offered.
    warn_steps(lines): optional; tell the person, when the export stops, the `health.health_lines` about steps that
      differ from the start of the export (`settle_steps`).
    log(text): a line for the log.
    """

    store: object
    units: dict

    def export_step(self, path): ...

    def read_capture(self): ...

    def read_reach(self, capture, gaps): ...

    def probe_reader(self): ...

    def progress(self, verb): ...

    def warn_unrestored(self, names): ...

    def log(self, text): ...


@dataclass
class ExportRequest:
    """The person's choices and the design's parameters for one export."""

    title: str
    writer: str
    up_axis: str
    parameters: list
    model_params: list
    design_unit: str
    ticked: list
    ranges: dict
    marker: Optional[dict] = None
    faster_tries: bool = True  # suppress the timeline items the tries do not use (`timeline_trim`)
    # The timeline steps before anything was read (`timeline_health.read_timeline`); None reads them when the export
    # starts.
    timeline_start: Optional[object] = None


@dataclass
class PipelineResult:
    """What `run_pipeline` made: the package parts, the report, and the size table the export ended with."""

    manifest: dict
    files: dict
    report: dict
    table: object
    health: dict = field(default_factory=dict)
