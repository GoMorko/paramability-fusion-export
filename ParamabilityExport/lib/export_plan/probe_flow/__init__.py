"""The size probe of one export: which sketch states to read, and how the answers become a motion. Pure: no Fusion.

The export reads the sketches of the part, the measured references of other components its steps use (a plane,
axis, direction or point) and the flat faces its steps use as outlines, at its current settings (E0) and at extra
settings that only recompute: the range ends of the sizes that move a sketch or such a reference, and all sizes low or
high (`probe_rows`). `SizeProbe` keeps that
record and hands the states to `probe.build`. Fusion is reached through the `read` callable given to `start`:
`read(request)` returns one probe state (`fusion_reader.probe_state.read_state`).

A step of the target can use a sketch of another component (a borrowed sketch). The probe reads it like the
target's own sketches: its frame is brought into the target's coordinates at every state, so the fit sees its
outline move with the sizes. The probe works on a view of the capture where such profiles are written as own ones.
A borrowed sketch that the fit cannot follow (it did not read back as captured) is watched instead: a size that
changes it, or leaves it unreadable, is loose. A reference that did not read back as captured is not read again; the
motion file says so (`Motion.refs`).

The modules: `size_probe` (`SizeProbe`: the states of one part, the rows it plans, the discovery rows and the motion),
`probe_group` (`ProbeGroup`: several parts over shared rows), `interface` (`Probe`: what the try runner and the
pipelines call; both classes have every member), `row_schedule` (the row phases), `borrowed_view` (the borrowed
sketches and the view of the capture), `shared_reads`, `states` (comparing states), `sizes` (`sizes_to_try`: which
sizes to probe), `reasons` (the texts of untried sizes) and `shadow` (the `derived` block).
This package re-exports what the rest of the add-in reads as `probe_flow.<name>`.
"""
from .borrowed_view import borrowed_sketches, covers_a_sketch, probe_view
from .interface import Probe
from .probe_group import ProbeGroup
from .shadow import shadow_of
from .size_probe import SizeProbe
from .sizes import sizes_to_try

__all__ = ["Probe", "ProbeGroup", "SizeProbe", "borrowed_sketches", "covers_a_sketch", "probe_view", "shadow_of",
           "sizes_to_try"]
