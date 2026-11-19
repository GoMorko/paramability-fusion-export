# Development

This file tells how the code is laid out and how it is tested.
For how an export works from the click to the file, read `agent-docs/developer-guide.md`.
That guide has worked examples and debugging steps.

Contents:

- [Code layout](#code-layout)
- [Output difference check](#output-difference-check)
- [Tests](#tests)

## Code layout

The add-in code is in `ParamabilityExport/lib/`. There is one package for each job.

The table `ALLOWED_IMPORTS` in `tests/test_boundary.py` says which packages each package may import.
The list below follows its order, lowest first.
A package may import only packages above it in this list, not every one of them.
`commands/` sits on top.

### `package`

The `.paramability` file: units, rows, manifest, caps, file names and the zip writer.

### `geometry`

- Vector helpers.
- 2D helpers: distance to a segment, a point inside a ring, and an arc drawn as the app draws it (`plane2d.py`).
- The rigid map of a frame.
- Sketch outlines, and `closed_chain` (the curves of a loop in order).
- Open chains of curves (`chains.py`).
- The area that convex polygons cover together (`convex_union.py`).
- The app's spline and the fit of free curves to it (`spline_fit.py`).
- Volume checks.
- The tolerances for comparing two reads of the design (`tolerances.py`). The translator, the probe and the reader
  share them.

### `capture_model`

What a capture and a recipe step are made of:

- the step kind table;
- capture checks;
- body lineage;
- gap causes and hints.

### `timing`

- Stopwatch helpers.
- The `timing` block of `report.json`. It shows where an export spends its time.
- The export trail (`trail.py`). It is a file in the temp folder with one line for each thing that the export does in
  Fusion. It is kept for a crash.

### `orca_recipe`

The OrcaSlicer 2.5 Design tab recipe (`Metadata/orca_cad.bin`):

- the cereal binary values;
- the feature fields in Orca's order, with its defaults;
- the recipe reader and writer;
- a 3MF writer.

Export for Orca (experimental) writes the recipe through `orca_translate`. See `agent-docs/orca-output.md`.

### `params`

Fusion parameters as sizes:

- names;
- defaults;
- expression to formula;
- the size table;
- the geometry links. They say which parameters may reach a sketch or a place of the part through another component.

`params` does not read steps. The items that place an occurrence come from `design_model/step_links.py`.

### `sketch_values`

The motion file of sketch values and measured references that follow sizes, its keys and its coverage.

### `sketch_solve`

- It reads a sketch's dimensions and constraints from the capture into formulas for its points. It needs no Fusion.
- It says which projected entities no size moves (`constants.py`).
- Export for Orca uses its extended reading (`extended=True`). The recipe output does not use it.

### `design_edit`

- Setting parameter values row by row, and restoring them.
- Checking the timeline steps after a row.
- Bringing the design back the way a row took it away (`walk_back.py`).
- The timeline marker.
- The temporary copy.
- The declared interface of the parameter store (`store.py`).
- The store that counts the calls of the tries (`metered.py`).
- The saved state of the design at the start of an export (`saved_start.py`).

### `design_model`

`design_model` is the shared layer that both translators read.
It holds facts about the design that every output needs, and doubts about sizes. It never refuses.

#### Reading the design

- `design.py` reads the design as the walks read it (`read`). It gives one resolved step for each timeline item. A
  resolved step holds:
  - the role of the item;
  - what about the item cannot be read;
  - the step with the geometry of other components brought in, and the doubts that wait for the walk to replay;
  - the facts of its kind.
- A handler takes the resolved step and reads its step only through it: `brought`, `brought_data` and `facts`.
- An item that no walk resolves goes through `as_read`.
- `params_of` gives the model parameters behind the values of an item.
- `sketches_of` gives the sketches that an item names.
- `recorder.py` declares what the layer asks of a translation.
- `roles.py` says what each timeline item is for the body that a walk builds: a sketch, an assembly item, a step of
  another component, a step of the body or a step of another body. It also gives the body before and after the item,
  the measures of that body (`seen_on`) and the other pieces of a split.

#### Places, sizes and reach

- `refs.py` holds the planes, faces, axes and points of other components. It says which records a step can use, which
  sizes may move them, and the doubt when the copy keeps them in place.
- `borrowed.py` holds the outlines taken from another component's sketch.
- `step_links.py` holds the measured references of the steps and the items that may place an occurrence. It hands them
  as plain values to the geometry links of `params` (`reach`, `reference_links`, `outside`).
- `reach.py` says which sizes may move a sketch, a plane, a face or a joint. The sizes behind the model parameters are
  in `param_reach.py`, which `reach` names too.
- `edges.py` matches an edge or a face of the part to the straight extrude that made it. It tells which sizes may turn
  a pattern direction taken from it, and which may change the thickness that a hole goes through.
- `dimension_sizes.py` holds the sketch dimensions as formulas of the sizes, and the size settings that a sketch is
  tried at.
- `tried_ranges.py` holds the range cuts where the size probe saw one of these cases (`built_ranges`):
  - the design does not rebuild;
  - a step is in error now;
  - a followed outline changes;
  - the design comes apart.

#### Values, words and problems

- `values.py` holds the one value type, `Quantity` (a number and, when sizes move it, a formula). It holds `Sized`
  (the written form) and the helpers that work on them.
- `words.py` holds the sentences that both outputs give for the same fact: a problem of a reader, and a refusal that
  both outputs word alike.
- `problem.py` holds the answer of a reader that cannot read, place or build the design. This is `Problem`: a code,
  plain words and a gap cause. Each output turns it into its own refusal.
- `loops.py` is the loop writer: sketch curves to recipe loops, or a `Problem`. The translator writes with it, and the
  probe measures through it. So a measured value is the value that the translator writes.
- `tool_chains.py` holds the tool bodies of a Combine. It says:
  - which items build one, through splits and in another component;
  - where a tool of another component sits;
  - the frame of the component that a walk builds in.

#### `paths/`

The sweep path planner (`planner.plan`). It gives:

- the chain and its kind;
- the recipe path forms;
- the app's limits, as problems.

The output gives the caps and the spline fit in `PathOptions`.

#### `steps/`

`steps/` holds one reader for each kind of step.

- `steps/extrude.py`: where an extrude starts, how each side ends, its direction and its length.
- `steps/extrude_checks.py`: the checks against what Fusion measured (end face, side walls, volume).
- `steps/hole.py` and `steps/thread.py`: the kind, the direction, the measured sizes and the thread of a hole and of a
  ThreadFeature. They also give the end of a hole "To" a face, and the sizes that may end it on another face, for both
  outputs.
- `steps/repeat.py`:
  - the copies that a pattern kept, and their frames;
  - the grid index of a copy;
  - the reach of a symmetric direction;
  - the plane of a mirror;
  - the items that a pattern or a mirror repeats.
- `steps/pattern_places.py`: where the copies of a pattern sit. It covers circular copies by their ids, each place
  checked against the faces of its copy, and places that repeat or do not fill the count.
- `steps/path_pattern.py`: the plain pattern that a path pattern on one line, arc or circle equals, and the room that
  its copies have on the path.
- `steps/move.py`: the rigid move fitted from the corners of a body.
- `steps/offset_round.py`: a whole round face that a Press Pull moves.
- `steps/paste.py`: the source of a pasted body, and where the pasted body sits against it.
- `steps/body_pattern.py`: the copies of a pattern or mirror of bodies, and whether a Combine takes all of them.
- `steps/split.py`: which piece of a split lies inside the tool.
- `steps/finish.py`: the sets of a round or a chamfer: kinds, sizes, the face of the first distance of an uneven
  chamfer, and edges of one size. Each translator keeps its own picks of the edges.
- `steps/sweep.py`: the settings that are not plain, the outline points, and the volume and end face checks.
- `steps/pipe.py`: the section of a pipe as an outline, and where it sits on the path.
- `steps/emboss.py`: the volume check, and the face that an outline is trimmed to.
- `steps/loft.py`: the volumes of the corner pairings.
- `steps/revolve.py`: which side each angle of a revolve to two sides turns to.
- `steps/thin.py`: the wall of a thin extrude: its record, the open line, the shape of the wall and the side that it
  stands on.
- `steps/rib_web.py`: the walls of a rib or a web, as thin extrudes of open lines.
- `steps/rib_fill.py`: a rib To Next that Fusion fills up to the part, as the outline that Fusion made.

### `results`

The shape of a verdict, and of the record of a step left out. Both translators and the dialogs use them
(`verdicts.py`, `left_out.py`).
`results` holds shapes and the words of a verdict kind. It holds no facts about the design.

### `translator`

The translator takes a capture dict and gives a recipe plus verdicts.

- There is one handler for each step type. `handlers.py` maps them.
- Each handler takes the resolved step of `design_model.design`: `handler(ctx, step)`. It reads no step data from an
  item itself.
- The driver is `translate.py`, `walk.py`, `context.py`, `result.py`, `values.py` (the policy: ranges, pins, the
  audit) and `sizes.py`.
- The rest sits in folders by job:
  - `extrude/`: also emboss, the wall along an open line, rib and web.
  - `sweep/`: also pipe.
  - `paths/`: the recipe caps on a path, and the path that follows sizes.
  - `loft/`.
  - `revolve/`: also the ranges that keep an outline on its side of the axis.
  - `hole/`.
  - `repeat/`: patterns and mirrors.
  - `combine/`: also tool bodies.
  - `finishes/`: fillet, chamfer, shell, draft and offset faces.
  - `bodies/`: move, scale, paste and split.
  - `faces/`: the faces that steps make, and the picks that follow sizes.
  - `sketch/`: outlines and sketch values.
  - `ranges/`: formulas over the size ranges.
  - `gaps/`.

### `probe`

- It measures sketches, and the places of other components' planes, axes and points, at other size values. It fits
  the motion file.
- `same_shape.py` compares two reads of a sketch by their curves alone. A curve that Fusion only named or listed
  otherwise is no flip.
- It does not import the translator. What it reads of the recipe is in `design_model`: the loop writer and the range
  cuts of its tries.

### `orca_translate`

`orca_translate` takes a capture and gives an OrcaSlicer Design tab recipe (`orca_recipe`) plus a verdict for each step.
It serves Export for Orca (experimental).

- There is one handler module for each kind of step.
- It keeps the shape of the part built so far, for the checks of cuts.
- Each handler takes the resolved step of `design_model.design` (`handler(ctx, step)`). It reads no step data from an
  item itself.
- It imports neither the recipe translator nor the probe.
- The modules are listed in `agent-docs/orca-output.md`.

### `export_plan`

`export_plan` is the export itself.

- The pipeline: one body or several.
- The put back of the design at its end (`pipeline/put_back.py`).
- The recipe and its notes.
- The probe run.
- Size offers.
- The undo of an export that did not put the design back (`rollback.py`). It holds:
  - the verdict;
  - the gate of the execute event;
  - `reopen_offered`: whether the result window gives the steps to get the design back as it was saved;
  - `reopen_lines`: the steps.
- When a try leaves only steps outside what the tries need changed, `pipeline/outside_damage.py` says which sizes end
  with it. The try runner goes on with the others.
- The try runner (`pipeline/probe_run.py`) calls the probe through one declared interface (`probe_flow/interface.py`).
  The probe of one part (`probe_flow/size_probe.py`) and the group of several parts (`probe_flow/probe_group.py`) both
  have this interface.
- `probe_flow/body_routes.py` says which sizes change the part in their tries only through the values of its own steps
  (a size shared with another component). So the probe does not list them as changing the part in a way that the copy
  does not follow.

### `dialog_model`

What the dialogs show, as plain data:

- rows;
- the Sizes table;
- the result view;
- the stop warning;
- the result view and the left out preview of Export for Orca.

### `fusion_reader`

`fusion_reader` reads the design with `adsk` into a capture. It only reads.

- `read_solid.py` reads extrude, revolve and combine.
- `read_hole.py` reads holes.
- `read_extent.py` reads the start, the sides and the target face of an extrude. A hole reads its extent target there
  too.
- `saved_design.py` reads whether the design is saved in the cloud, and whether Fusion showed unsaved changes.

### `fusion_ui`

`fusion_ui` draws the dialogs and handles their events with `adsk`.

- `result_dialog.py` opens the result window when Fusion reports that the export command has ended
  (`UserInterface.commandTerminated`).
- No custom event and no background thread is used for it.
- The add-in never closes or opens a design. Fusion does not support that inside a command event.

### `commands/`

The three buttons, their flows and the panel. This package also uses `adsk`.

## Output difference check

A change that should not alter what the translators write must prove it.
Two scripts compare the output of both translators for every test capture, before and after a change.
The two outputs are the `.paramability` recipe and the Orca recipe.

```
python3 scripts/output_snapshot.py /tmp/before.json     # on the code before the change
python3 scripts/output_snapshot.py /tmp/after.json      # on the code after the change
python3 scripts/output_diff.py /tmp/before.json /tmp/after.json
```

### The snapshot

- Write a snapshot under `/tmp` or `tests/local` (git-ignored). Never write it into a tracked folder. The script
  refuses other places inside the repository.
- A snapshot takes about 30 to 45 seconds.
- It runs these captures:
  - each capture of `tests/fixtures/captures` without sizes (`plain`);
  - each capture of `tests/fixtures/captures` with every user parameter ticked (`sized`);
  - each capture that has a file in `tests/fixtures/motion`, with that motion (`motion`);
  - when `tests/local/captures.json` exists: the local packages replayed with their own probe states (`local`) and
    the local Orca reports (`orca`).
- You can name more capture or report files after the output path.
- A capture that raises is kept as its exception type and message.

### The diff

- The diff prints one line per change: `capture | mode | translator | what changed`.
- It lists these changes:
  - changed verdicts;
  - gaps;
  - fixed, loose, cut and dropped sizes;
  - left out steps;
  - parameter outcomes;
  - a changed recipe, by JSON path. At most 12 paths per output show. `--all` shows every one.
- For a changed formula, it works out the old and the new text at the current values and with each size 25% lower and
  higher. It says "same values" when they agree.
- The exit status is 1 when anything differs.

### The rule

Every line of the diff needs a reason in the commit message.
A line must be neutral or an improvement.
A line with no reason is a regression until shown otherwise.

## Tests

### Hand checks and test projects

- For a quick check of a release by hand, with your own projects and a few small test models, see
  `agent-docs/hand-checks.md`.
- To measure how many kinds of projects the copy covers, build the typical printing projects in
  `agent-docs/test-projects.md`. Export them. Open each one in the Paramability app to see how much of the design it
  keeps.

### What runs without Fusion

Everything under `lib/` except `fusion_reader/` and `fusion_ui/` is pure Python. It runs without Fusion.
The Fusion reading code is tested with fakes.
Anything that touches `adsk` stays in `lib/fusion_reader/`, `lib/fusion_ui/` and `commands/`.

### Boundary checks

`tests/test_boundary.py` checks these rules:

- Which package may import which. Imports go one way only.
- No module imports an underscore name from another module.
- The shared layer (`design_model`) uses no name of an output (`Refusal`, `Skip`, `Context`).
- The shared layer imports no output.
- No module outside the shared layer, the reader and the capture model takes the data of a step from the item itself.

The pattern instead:

- The handler gets the resolved step.
- Other items go in through `as_read`.
- Helpers get the data handed in.

This pattern is in `agent-docs/developer-guide.md` under `design.py` in 2.2.
`translator`, `orca_translate`, `probe` and `export_plan` follow it.

A module that reads every item of a capture (not a walk) reads each item's data through `as_read`.
`geometry` and `params` are below the shared layer. They get the data or plain values from their caller.
`design_model/step_links.py` reads the step facts that the geometry links need.

### Interface checks

`tests/test_interfaces.py` checks these points:

- The Fusion parameter store, the two Fusion ports and the shared fakes have every member declared for a store or a
  port. The declarations are in `design_edit/store.py` and `export_plan/pipeline/port.py`. The members have the
  declared parameters.
- Both probes have every member declared for a probe (in `export_plan/probe_flow/interface.py`).
- Both translation contexts have every member of the recorder (`design_model/recorder.py`).
- The code asks a store, a port, a probe or a recorder only for a declared member. This holds also through another
  name for it, or through `getattr`.

### Name checks

`tests/test_undefined_names.py` reads every module of the add-in with `symtable`.
It fails on a name that no scope binds (a missing import, for one).
It fails on a star import.

### Shared fakes

The shared fakes live in `tests/fakes/`, by domain:

- `store.py`: one parameter store, with options for the answers that a test needs. It has the stores that also hold
  the timeline marker.
- `port.py`: one port for one body and one for several bodies.
- `design.py`: Fusion objects for the reader tests.
- `dialog.py`: the dialog inputs.

A test that needs another answer passes an option: a recompute hook, a probe read, a sketch keeper or a reach read.
A test subclasses a fake store only to act out how Fusion behaves over several calls. Two examples are the order in
which it rebuilds items with the timeline marker held, and the health of timeline steps through an export
(`OrderStore`, `ParkStore`, `StepStore`, `BatchStore`).

### Run the tests

Python 3.10 or newer is needed. The code uses the standard library only.

From the repository root:

```
python3 -m unittest discover -s tests -t .
```

### Local capture checks

The local capture checks (`tests/test_local_captures.py`) read exported packages that stay outside the repository.

- They need a local `tests/local/captures.json` (git-ignored). Without it they skip.
- Set `PARAMABILITY_LOCAL_CAPTURES` to use another path.
- Set `PARAMABILITY_LOCAL_REPORTS` for the folder with the packages.

### OrcaSlicer sample recipes

The byte check over OrcaSlicer's own sample recipes (`tests/test_orca_recipe_files.py`) reads `cad_recipe_v3.bin`, `v4`
and `v5`.

- It reads them from the folder in `ORCA_RECIPE_SAMPLES`. This is the `tests/data` folder of the OrcaSlicer repo.
- Without it the check skips.
- The samples are not kept here.

## Related documents

- To make the export copy one more kind of Fusion step, follow `agent-docs/adding-a-step-type.md`.
- The file that lists the steps left out of a copy is described in `agent-docs/recipe-gaps.md`.
