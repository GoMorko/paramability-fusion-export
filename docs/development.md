# Development

How the code is laid out and how it is tested.

## Code layout

The add-in code is in `ParamabilityExport/lib/`, one package per job. The table `ALLOWED_IMPORTS` in
`tests/test_boundary.py` says which packages each one may import; the list below follows its order, lowest first, and a
package may import only packages above it in this list (not every one of them). `commands/` sits on top.

- `package`: the `.paramability` file: units, rows, manifest, caps, file names, zip writer.
- `geometry`: vector helpers, 2D helpers (distance to a segment, a point inside a ring, an arc drawn as the app draws it, `plane2d.py`), the rigid map of a frame, sketch outlines, volume checks and the tolerances for comparing two reads of the design (`tolerances.py`) that the translator, the probe and the reader share.
- `capture_model`: what a capture and a recipe step are made of: the step kind table, capture checks, body lineage, gap causes and hints.
- `timing`: stopwatch helpers and the `timing` block of `report.json` (where an export spends its time).
- `params`: Fusion parameters as sizes: names, defaults, expression to formula, the size table.
- `sketch_values`: the motion file of sketch values and measured references that follow sizes, its keys and coverage.
- `sketch_solve`: reads a sketch's dimensions and constraints from the capture into formulas for its points, without Fusion.
- `design_edit`: setting parameter values row by row, restoring them, the timeline marker, the temporary copy, and the declared interface of the parameter store (`store.py`).
- `translator`: a capture dict in, a recipe plus verdicts out (one handler per step type, mapped in `handlers.py`). `translate.py`, `walk.py`, `context.py`, `result.py`, `values.py` and `sizes.py` are the driver; the rest sits in folders by job: `extrude/` (also emboss), `sweep/` and `paths/`, `loft/`, `revolve/`, `hole/`, `repeat/` (patterns and mirrors), `combine/` (also tool bodies), `finishes/` (fillet, chamfer, shell, draft, offset faces), `bodies/` (move, paste, split), `faces/` (the faces steps make and the picks that follow sizes), `sketch/` (outlines and sketch values), `ranges/` (formulas over the size ranges) and `gaps/`.
- `probe`: measures sketches and the places of other components' planes, axes and points at other size values and fits the motion file.
- `export_plan`: the export itself: the pipeline (one body or several), the put back of the design at its end (`pipeline/put_back.py`), the recipe and its notes, the probe run, size offers. The try runner (`pipeline/probe_run.py`) calls the probe through one declared interface (`probe_flow/interface.py`) that the probe of one part (`probe_flow/size_probe.py`) and the group of several parts (`probe_flow/probe_group.py`) both have.
- `dialog_model`: what the dialogs show, as plain data (rows, Sizes table, result view, stop warning).
- `fusion_reader`: reads the design with `adsk` into a capture.
- `fusion_ui`: draws the dialogs and handles their events with `adsk`.
- `commands/`: the two buttons, their flows and the panel; also uses `adsk`.

## Tests

For a quick check of a release by hand, with your own projects and a few small test models, see `docs/hand-checks.md`.
To measure how many kinds of projects the copy covers, build the typical printing projects in `docs/test-projects.md`,
export them and score them with the app's scoreboard.

Everything under `lib/` except `fusion_reader/` and `fusion_ui/` is pure Python and runs without Fusion. The Fusion
reading code is tested with fakes. Anything that touches `adsk` stays in `lib/fusion_reader/`, `lib/fusion_ui/` and
`commands/`. `tests/test_boundary.py` checks that, which package may import which (so imports only go one way), and
that no module imports an underscore name from another module. `tests/test_interfaces.py` checks that the Fusion
parameter store, the two Fusion ports and the shared fakes have every member declared for a store or a port (in
`design_edit/store.py` and `export_plan/pipeline/port.py`) with the declared parameters, that both probes have every
member declared for a probe (in `export_plan/probe_flow/interface.py`), and that the code asks a store, a port or a probe
only for a declared member, also through another name for it or `getattr`.

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

The owner-capture checks (`tests/test_owner_captures.py`) need a local `tests/local/owner_captures.json` (git-ignored); without it they skip.
Set `PARAMABILITY_OWNER_CAPTURES` to use another path and `PARAMABILITY_OWNER_REPORTS` for the folder with the packages.

To make the export copy one more kind of Fusion step, follow `docs/adding-a-step-type.md`.
The file that lists the steps left out of a copy is described in `docs/recipe-gaps.md`.
