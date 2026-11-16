# Development

How the code is laid out and how it is tested. For how an export works from the click to the file, with worked
examples and debugging steps, read `docs/developer-guide.md`.

## Code layout

The add-in code is in `ParamabilityExport/lib/`, one package per job. The table `ALLOWED_IMPORTS` in
`tests/test_boundary.py` says which packages each one may import; the list below follows its order, lowest first, and a
package may import only packages above it in this list (not every one of them). `commands/` sits on top.

- `package`: the `.paramability` file: units, rows, manifest, caps, file names, zip writer.
- `geometry`: vector helpers, 2D helpers (distance to a segment, a point inside a ring, an arc drawn as the app draws it, `plane2d.py`), the rigid map of a frame, sketch outlines (and `closed_chain`, the curves of a loop in order), the app's spline and the fit of free curves to it (`spline_fit.py`), volume checks and the tolerances for comparing two reads of the design (`tolerances.py`) that the translator, the probe and the reader share.
- `capture_model`: what a capture and a recipe step are made of: the step kind table, capture checks, body lineage, gap causes and hints.
- `timing`: stopwatch helpers and the `timing` block of `report.json` (where an export spends its time).
- `orca_recipe`: the OrcaSlicer 2.5 Design tab recipe (`Metadata/orca_cad.bin`): the cereal binary values, the
  feature fields in Orca's order with its defaults, the recipe reader and writer, and a 3MF writer. Export for Orca
  (experimental) writes it through `orca_translate`; see `docs/orca-output.md`.
- `params`: Fusion parameters as sizes: names, defaults, expression to formula, the size table.
- `sketch_values`: the motion file of sketch values and measured references that follow sizes, its keys and coverage.
- `sketch_solve`: reads a sketch's dimensions and constraints from the capture into formulas for its points, without Fusion, and says which projected entities no size moves (`constants.py`). Export for Orca uses its extended reading (`extended=True`), which the recipe output does not use.
- `design_edit`: setting parameter values row by row, restoring them, the timeline marker, the temporary copy, and the declared interface of the parameter store (`store.py`).
- `design_model`: the shared layer both translators read: facts about the design that every output needs and doubts
  about sizes, never a refusal. `design.py` reads the design as the walks read it (`read`: one resolved step per
  timeline item with its role, what about it cannot be read, the step with the geometry of other components brought
  in and the doubts that waits for the walk to replay, and the facts of its kind; a handler takes the resolved step and
  reads its step only through it, `brought`, `brought_data` and `facts`, and an item that no walk resolves through
  `as_read`; `params_of` gives the model parameters behind the values of an item); `recorder.py` declares what it asks
  of a translation; `refs.py` holds the planes,
  faces, axes and points of other components (which records a step can use, which sizes may move them, the doubt when
  the copy keeps them in place); `borrowed.py` the outlines taken from another component's sketch; `roles.py` what
  each timeline item is for the body a walk builds (a sketch, an assembly item, a step of another component, a step of
  the body or of another body), the body before and after it, the measures of that body (`seen_on`) and the other
  pieces of a split; `words.py` the sentences both outputs give for the same fact (a problem of a reader, a refusal
  both outputs word alike); `reach.py` which sizes may move a sketch, a plane, a face or
  a joint; `dimension_sizes.py` the sketch dimensions as formulas of the sizes and the size settings a sketch is tried
  at; `problem.py` the answer of a reader that cannot read, place or build the design (`Problem`: a code, plain words
  and a gap cause; each output turns it into its own refusal); `values.py` the one value type, `Quantity` (a number
  and, when sizes move it, a formula), with `Sized` (the written form) and the helpers that work on them; `tool_chains.py` the tool bodies of a Combine (which items build one, through splits and in another component, where a tool of another component sits, and the frame of the
  component a walk builds in); `paths/` the
  sweep path planner (`planner.plan`: the chain, its kind, the recipe path forms and the app's limits as problems; the
  caps and the spline fit come from the output in `PathOptions`); `steps/` holds one reader per kind of step:
  `steps/extrude.py` (where an extrude starts, how each side ends, its direction
  and length, and the checks against what Fusion measured: end face, side walls, volume), `steps/hole.py` and
  `steps/thread.py` (the kind, the direction, the measured sizes and the thread of a hole and of a
  ThreadFeature), `steps/repeat.py` (the copies a pattern kept and their frames, the grid index of a copy, the reach of
  a symmetric direction, the plane of a mirror), `steps/move.py` (the rigid move fitted from the corners of a body),
  `steps/split.py` (which piece of a split lies inside the tool), `steps/finish.py` (the sets of a round or a chamfer:
  kinds, sizes, the face of the first distance of an uneven chamfer, edges of one size; each translator keeps its own
  picks of the edges), `steps/sweep.py` (the settings that are not plain, the outline points, the volume and end face
  checks), `steps/emboss.py` (the volume check and the face an outline is trimmed to) and `steps/loft.py` (the volumes of
  the corner pairings).
- `results`: the shape of a verdict and of the record of a step left out, for both translators and the dialogs (`verdicts.py`, `left_out.py`). It holds shapes and the words of a verdict kind, not facts about the design.
- `translator`: a capture dict in, a recipe plus verdicts out (one handler per step type, mapped in `handlers.py`). `translate.py`, `walk.py`, `context.py`, `result.py`, `values.py` (the policy: ranges, pins, the audit) and `sizes.py` are the driver; the rest sits in folders by job: `extrude/` (also emboss), `sweep/` and `paths/` (the recipe caps on a path, the path that follows sizes), `loft/`, `revolve/`, `hole/`, `repeat/` (patterns and mirrors), `combine/` (also tool bodies), `finishes/` (fillet, chamfer, shell, draft, offset faces), `bodies/` (move, paste, split), `faces/` (the faces steps make and the picks that follow sizes), `sketch/` (outlines and sketch values), `ranges/` (formulas over the size ranges) and `gaps/`.
- `probe`: measures sketches and the places of other components' planes, axes and points at other size values and fits the motion file. It still reads the translator for what the recipe writes (`sketch/loops.profile_loops` and its `Refusal`, and `ranges.kept_ranges`); everything else it reads is in `design_model`.
- `orca_translate`: a capture in, an OrcaSlicer Design tab recipe (`orca_recipe`) plus a verdict per step out, for Export for Orca (experimental): one handler module per kind of step, and the shape of the part built so far for the checks of cuts. Each handler takes the resolved step of `design_model.design` (`handler(ctx, step)`) and reads no step data from an item itself. It imports neither the recipe translator nor the probe. The modules are listed in `docs/orca-output.md`.
- `export_plan`: the export itself: the pipeline (one body or several), the put back of the design at its end (`pipeline/put_back.py`), the recipe and its notes, the probe run, size offers. The try runner (`pipeline/probe_run.py`) calls the probe through one declared interface (`probe_flow/interface.py`) that the probe of one part (`probe_flow/size_probe.py`) and the group of several parts (`probe_flow/probe_group.py`) both have.
- `dialog_model`: what the dialogs show, as plain data (rows, Sizes table, result view, stop warning, and the result view and the left out preview of Export for Orca).
- `fusion_reader`: reads the design with `adsk` into a capture.
- `fusion_ui`: draws the dialogs and handles their events with `adsk`.
- `commands/`: the three buttons, their flows and the panel; also uses `adsk`.

## Output difference check

A change that should not alter what the translators write must prove it. Two scripts compare the output of both
translators (the `.paramability` recipe and the Orca recipe) for every test capture, before and after a change.

```
python3 scripts/output_snapshot.py /tmp/before.json     # on the code before the change
python3 scripts/output_snapshot.py /tmp/after.json      # on the code after the change
python3 scripts/output_diff.py /tmp/before.json /tmp/after.json
```

Write a snapshot under `/tmp` or `tests/local` (git-ignored), never into a tracked folder; the script refuses other
places inside the repository. A snapshot takes about 30 to 45 seconds. It runs each capture of `tests/fixtures/captures`
without sizes (`plain`) and with every user parameter ticked (`sized`), each capture that has a file in
`tests/fixtures/motion` with that motion (`motion`), and, when `tests/local/captures.json` exists, the local packages
replayed with their own probe states (`local`) and the local Orca reports (`orca`). More capture or report files can be
named after the output path. A capture that raises is kept as its exception type and message.

The diff prints one line per change: `capture | mode | translator | what changed`. It lists changed verdicts, gaps,
fixed, loose, cut and dropped sizes, left out steps and parameter outcomes, and a changed recipe by JSON path (at most
12 paths per output, `--all` shows every one). For a changed formula it works out the old and the new text at the
current values and with each size 25% lower and higher, and says "same values" when they agree. The exit status is 1
when anything differs.

Rule: every line of the diff needs a reason in the commit message, and a line must be neutral or an improvement. A line
with no reason is a regression until shown otherwise.

## Tests

For a quick check of a release by hand, with your own projects and a few small test models, see `docs/hand-checks.md`.
To measure how many kinds of projects the copy covers, build the typical printing projects in `docs/test-projects.md`,
export them and open each one in the Paramability app to see how much of the design it keeps.

Everything under `lib/` except `fusion_reader/` and `fusion_ui/` is pure Python and runs without Fusion. The Fusion
reading code is tested with fakes. Anything that touches `adsk` stays in `lib/fusion_reader/`, `lib/fusion_ui/` and
`commands/`. `tests/test_boundary.py` checks that, which package may import which (so imports only go one way),
that no module imports an underscore name from another module, that the shared layer (`design_model`) uses no name
of an output (`Refusal`, `Skip`, `Context`) and imports no output, and which modules above the shared layer still
take the data of a step from the item itself (`RAW_STEP_DATA`). That list may only shrink: a module that reads the
facts of `design_model` instead leaves it, and a new module must not join it. The pattern that takes a module off
the list (the handler gets the resolved step, other items go in through `as_read`) is in `docs/developer-guide.md`
under `design.py` in 2.2; `orca_translate` follows it. `tests/test_interfaces.py` checks that the Fusion
parameter store, the two Fusion ports and the shared fakes have every member declared for a store or a port (in
`design_edit/store.py` and `export_plan/pipeline/port.py`) with the declared parameters, that both probes have every
member declared for a probe (in `export_plan/probe_flow/interface.py`), that both translation contexts have every member
of the recorder (`design_model/recorder.py`), and that the code asks a store, a port, a probe or a recorder only for a
declared member, also through another name for it or `getattr`.

The shared fakes live in `tests/fakes/`, by domain: one parameter store with options for the answers a test needs
(`store.py`, with the stores that also hold the timeline marker), one port for one body and one for several bodies
(`port.py`), Fusion objects for the reader tests (`design.py`) and the dialog inputs (`dialog.py`). A test that needs
another answer passes an option (a recompute hook, a probe read, a sketch keeper, a reach read). A test subclasses a
fake store only to act out how Fusion behaves over several calls, such as the order it rebuilds items in with the
timeline marker held or the health of timeline steps through an export (`OrderStore`, `ParkStore`, `StepStore`,
`BatchStore`).

From this folder:

```
python3 -m unittest discover -s tests -t .
```

Python 3.10 or newer, standard library only.

The local capture checks (`tests/test_local_captures.py`) read exported packages that stay outside the repository. They need a local `tests/local/captures.json` (git-ignored); without it they skip.
Set `PARAMABILITY_LOCAL_CAPTURES` to use another path and `PARAMABILITY_LOCAL_REPORTS` for the folder with the packages.

The byte check over OrcaSlicer's own sample recipes (`tests/test_orca_recipe_files.py`) reads `cad_recipe_v3.bin`,
`v4` and `v5` from the folder in `ORCA_RECIPE_SAMPLES` (the OrcaSlicer repo's `tests/data`); without it they skip.
The samples are not kept here.

To make the export copy one more kind of Fusion step, follow `docs/adding-a-step-type.md`.
The file that lists the steps left out of a copy is described in `docs/recipe-gaps.md`.
