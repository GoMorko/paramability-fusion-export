"""What the pipeline takes in and gives out: the port to Fusion, the request and the result."""
from dataclasses import dataclass, field
from typing import Optional, Protocol

from ..time_limit import DEFAULT_SECONDS


class ExportPort(Protocol):
    """What the pipeline needs from Fusion. The command passes the real one (`FusionPort`), tests pass a fake.

    store: the parameter store (`design_edit.store.ParameterStore`).
    units: {parameter name: Fusion unit string}.
    timing: the `timing.export_timing.ExportTiming` of this export, or None; the pipeline then makes its own. A port
      that reads the capture with a `CaptureTimer` hands its summary to it (`note_capture`).
    undo_steps: the `undo_steps.UndoSteps` the tries call, or None; `undo_steps.attach` sets it.
    read_timer: the `timing.timer.Timer` that `ProbeRun` lends the probe reader while it reads, else None.
    export_step(path): write the STEP of the picked body as the design is now.
    read_mesh(): `(vertices, triangles)` of the picked body as the design is now, in root coordinates and mm, for the
      Orca output; raises `StepExportError` when Fusion gives no mesh.
    read_capture(): the capture dict of the picked body, or the exception that stopped the read.
    read_reach(capture, gaps): the `reach` of the capture when the steps at the timeline indexes `gaps` are left out
      of the copy (`read_gap_reach.read_reach`); raises `MarkerError` when the timeline marker cannot go back.
    probe_reader(): a callable `read(request)` giving one probe state, or raising.
    sketch_keeper(tokens): an object that keeps the sketches `tokens` as they are now and whose `put_back()` moves
      their points back there (`fusion_reader.sketch_keep.SketchKeeper`, `ProbeRun`), or None when the port keeps none.
    progress(verb): a context manager whose value has `step(index, total, name, note)`; `note` is a line about the time
      the tries take (empty when there is none). The step returns False when the person cancelled.
    warn_unrestored(names): tell the person that these parameters could not be put back, when the export stops.
    warn_left_off(names, undo_dropped): tell the person that these timeline steps, turned off for the tries
      (`timeline_trim`), could not be turned back on; `undo_dropped` is True when Fusion forgot Undo data
      (`undo_dropped`), so Undo is not offered.
    warn_steps(lines): tell the person, when the export stops, the `health.health_lines` about steps that differ
      from the start of the export (`settle_steps`).
    log(text): a line for the log.
    """

    store: object
    units: dict
    timing: object
    undo_steps: object
    read_timer: object

    def export_step(self, path): ...

    def read_mesh(self): ...

    def read_capture(self): ...

    def read_reach(self, capture, gaps): ...

    def probe_reader(self): ...

    def sketch_keeper(self, tokens): ...

    def progress(self, verb): ...

    def warn_unrestored(self, names): ...

    def warn_left_off(self, names, undo_dropped=False): ...

    def warn_steps(self, lines): ...

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
    # Seconds the size tries may take before they stop (`time_limit`), None for no limit.
    probe_time_limit: Optional[float] = DEFAULT_SECONDS
    # The timeline steps before anything was read (`timeline_health.read_timeline`); None reads them when the export
    # starts.
    timeline_start: Optional[object] = None
    # What the export writes: "paramability" (a recipe package) or "orca" (an OrcaSlicer project,
    # `export_plan.orca_export`). The Orca output reads a mesh instead of a STEP and runs no size tries.
    output: str = "paramability"
    # The `rollback.ExportOutcome` the export fills in (`put_back.PutBack`), on every way it ends; None keeps no record.
    outcome: Optional[object] = None


@dataclass
class PipelineResult:
    """What `run_pipeline` made: the package parts, the report, and the size table the export ended with. The Orca
    output has no manifest and no files: `orca` holds its `orca_export.OrcaPackage`."""

    manifest: Optional[dict]
    files: dict
    report: dict
    table: object
    health: dict = field(default_factory=dict)
    orca: Optional[object] = None
