"""What to read from Fusion and which size settings to try. Pure: no Fusion imports.

`scan` finds the sketches whose numbers the probe can follow ("covered" ones): every capture record that names them
is a profile, a hole point set, a revolve axis line or a sweep path of lines and arcs that the reader gave tokens
for. Which records a step type carries comes from the step kind table (`translator/step_kinds.py`, `sketches`).
`refs` finds the measured references (a plane, axis, direction or point of another component that a step uses, and
a face or plane of the part that an extrude starts from or reaches to) that the probe reads again at every state. A
flat face a step uses as its outline (`outline_face`) is a target of its own (`kind` "face"): the reader reads its
loops again at every state with the timeline marker before that step, since the step itself changes the face.
`request` is what the reader reads per state, `kept_sizes` the sizes worth probing, `probe_rows` the size settings to
try.

Sizes are dicts as in `export_plan.size_offers.probe_sizes`: param (Fusion name), size (recipe name), unit, value,
min, max (manifest numbers).

Row order, each step only while rows are left under `MAX_PROBE_ROWS` (64):
1. Near rows (`probe_rows`): every size that moves a sketch, then the sizes tried on a guess, gets one row
   `NEAR_SHARE` (25 percent) of its value below and one above, kept inside its range (a count is a whole number, at
   least one step away).
2. Near pair rows (`pair_rows`, run after the near rows): when two or more sizes are tried, one row with all of them at
   their lower near value and one at the higher. A size whose own near row on that side did not build stays at its
   value: the pair would fail for it alone.
3. Far rows (`far_rows`, run after the nearer tries of step 1 and 2): the range ends that differ from the value and
   from the near values, so the measured span grows. An end past a value of the size that did not build on its own is
   not tried: the range stops before that value anyway.
4. Far pair rows (`far_pair_rows`, after the nearer tries of step 3): when two or more sizes are tried, all sizes at
   their minimum, then all at their maximum, a tried size at the farthest value it built at on its own on that side.
A row that does not build is tried again nearer (`nearer_rows`, `NEARER_STEPS`: 50, 25 and 10 percent of the way to
the range end, the first one nearer than the value tried). On a side where some value built and a farther one did
not, the values between them are halved (`BISECT_STEPS` times at most) so the last value that builds is found closely.
A row where the size alone made a followed sketch take a different outline (a state marked `changed`) counts as one
that did not build: the range stops before it, so the same tries find the farthest value that keeps the outline.
A size that only feeds step values is exact from its
formula and gets no row: rows go to the sizes that move a sketch or a measured reference (`moved`) and to the
guessed ones, and only a size left without a near row because of the limit is reported as untried.

The modules: `covered` (`scan`), `references` (`refs`), `request` (`request`), `sizes` (which sizes to probe), `rows`
(one row), `history` (what earlier states show), `near_far`, `nearer` and `extra_rows` (the row kinds). This package
re-exports what the rest of the add-in reads as `plan.<name>`.
"""
from .covered import FACE, Scan, _SCANNERS, outline_face, scan
from .extra_rows import MAX_DISCOVERY, check_rows, discovery_left, discovery_rows
from .near_far import far_pair_rows, far_rows, near_values, pair_rows, probe_rows
from .nearer import BISECT_STEPS, MAX_NEARER_ROWS, NEARER_STEPS, nearer_rows
from .references import NO_PLACE, NO_TOKEN, SHAPE_AXIS, SHAPE_DIRECTION, SHAPE_PLANE, SHAPE_POINT, is_vector, refs
from .request import request, symmetric_patterns
from .rows import MAX_PROBE_ROWS, RETRY_NOTE, state_values
from .sizes import MAX_EXTRA_SIZES, extra_sizes, kept_sizes, sketch_driven

__all__ = [
    "BISECT_STEPS", "FACE", "MAX_DISCOVERY", "MAX_EXTRA_SIZES", "MAX_NEARER_ROWS", "MAX_PROBE_ROWS", "NEARER_STEPS",
    "NO_PLACE", "NO_TOKEN", "RETRY_NOTE", "SHAPE_AXIS", "SHAPE_DIRECTION", "SHAPE_PLANE", "SHAPE_POINT", "Scan",
    "_SCANNERS", "check_rows", "discovery_left", "discovery_rows", "extra_sizes", "far_pair_rows", "far_rows",
    "is_vector", "kept_sizes", "near_values", "nearer_rows", "outline_face", "pair_rows", "probe_rows", "refs",
    "request", "scan", "sketch_driven", "state_values", "symmetric_patterns"]
