# Paramability export for Fusion

A Fusion add-in that saves a design as a `.paramability` file. Paramability opens it with a size dropdown, so one
file holds several sizes of the same part.

## Install

1. Get the folder: clone this repository, or download the release zip and unzip it.
2. In Fusion, open Utilities, then Add-Ins (or press Shift+S).
3. On the Add-Ins tab, click the green plus.
4. Pick the `ParamabilityExport` folder.
5. Select it in the list, click Run. Tick "Run on startup" to load it each time.

The button "Export for Paramability" shows in the Utilities tab.

## Use

1. In Fusion, mark the user parameters you want to vary as favourites.
2. Click Export for Paramability.
3. Pick the body, list your sizes (one per line), and name the dropdown. The sizes box starts with a header and a
   Default line made from your favourites. Add one line per size: the name first, then a number for each column.
   Leave a cell empty to keep the current value.
4. Pick the default size and the design up direction.
5. Click OK and choose where to save the file.
6. Open the file in Paramability with Open.

One size saves a plain part. Two or more sizes save a part with a dropdown.
After the export, a cancel or a size that does not build, your parameters are set back to their old values.

## How it works

For each size the add-in sets the parameters, lets Fusion rebuild, writes a STEP file of the picked body, and moves
on. All numbers in the file are in millimetres and degrees.

When the design holds more than the picked body, the add-in copies the picked body into a temporary component,
exports that, and deletes it. This route is a choice, not a proven fact: owner hand test 3 in
`docs/hand-tests.md` decides it. To ask the designer to hide or move other bodies instead, set `MULTI_BODY_ROUTE`
in `ParamabilityExport/lib/fusion_reader/step_export.py` to `ROUTE_ASK_DESIGNER`.

## Limits

- One solid body per export.
- Only plain number parameters can be columns. A parameter worked out by a formula cannot.
- The design needs history (a parametric design).
- Made for the current Fusion release.
- This is version 0.1.0. The Fusion side has not been run by a tool: see `docs/hand-tests.md`.

## Tests

The package writer and the export logic (`lib/package/`, `lib/export_plan/`) do not need Fusion. The Fusion
reading code is tested with fakes. Anything that touches `adsk` stays in `lib/fusion_reader/`, `lib/fusion_ui/` and
`commands/`. From this folder:

```
python3 -m unittest discover -s tests -t .
```

Python 3.10 or newer, standard library only.
