"""The export of one body, or of several bodies in one file, into a recipe package, from the capture to the manifest.
Pure: no Fusion imports.

The sequence asks Fusion for the capture, the STEP of the part as it is and the sketch measuring. A size that a value
cannot follow is left free with a warning, and the ranges are the ones in the dialog table.

Steps, in order: read the capture, translate once to learn which sizes the recipe keeps, run the sketch probe (it
only recomputes), translate again with the motion it found, and assemble the package. The probe runs whenever a
sketch can be followed. When the first translation leaves steps out, or stops because the part holds too many gaps,
Fusion is asked which step made the faces each later step picks (`reach_pass`) before anything else, and the part is
translated again with the answer.

Fusion is reached only through the port the caller hands in (see `ExportPort`), so tests run the whole sequence with
fakes. Parameters are changed by the probe and put back on every way out: when a step fails, when the person
cancels, and before the probe's last read. What is left over (a parameter that would not go back, sketches that did
not return to their start, a probe that could not measure) goes into the `health` record of the result. Timeline items
suppressed for the tries (`timeline_trim`, unless the person turns it off) are turned back on in the same places,
before the timeline marker goes back, and before the discovery tries. Last, on every way out, the health of every
timeline step is compared with the start of the export and the design rebuilt when a step differs
(`design_edit.timeline_health`).

Several bodies follow the same sequence with one size table and one probe scan for all of them (`parts`).

The modules: `port` (`ExportPort`, `ExportRequest`, `PipelineResult`), `run` (`run_pipeline` and the stages of one
export), `parts` (`run_parts_pipeline`, `PartsPort`: the same for several bodies), `probe_run` (`ProbeRun`, the try
runner), `settle` (the end check of the design after the tries) and `warn` (the messages for what could not be put
back). This package re-exports what the rest of the add-in reads as
`pipeline.<name>`.
"""
from .parts import PartsPort, PartsResult, run_parts_pipeline
from .port import ExportPort, ExportRequest, PipelineResult
from .probe_run import MarkerNotHeld, ProbeRun
from .run import run_pipeline

__all__ = [
    "ExportPort", "ExportRequest", "MarkerNotHeld", "PartsPort", "PartsResult", "PipelineResult", "ProbeRun",
    "run_parts_pipeline", "run_pipeline"]
