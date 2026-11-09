# Paramability export for Fusion

A Fusion add-in that saves a design as a `.paramability` file. Paramability opens it with a size dropdown, so one
file holds several sizes of the same part.

## Install

1. Get the folder: clone this repository, or download the release zip and unzip it.
2. In Fusion, click the Utilities tab, then Scripts and Add-Ins.
3. In the dialog, click the plus icon near the top of the list and choose "Script or add-in from device".
4. Pick the `ParamabilityExport` folder (the folder itself, not a file in it). Fusion remembers the location.
5. Find it in the list and click Run. Turn on "Run on Startup" to load it each time.

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

With one size, "Export as a recipe" (on by default) also saves the modeling steps of the picked body: sketches
with extrudes and revolves, holes, rounds, chamfers, shells, rectangular and circular patterns, mirrors and combines.
The current Paramability opens such a file as a plain part and says the steps are kept for a later version. When a
step cannot be copied, the file holds the plain part only, and the message after the export names the first step that
stopped it. A copy of what the add-in read from Fusion is saved inside the file as `report.json`.

After the export, a cancel or a size that does not build, your parameters are set back to their old values.

## How it works

For each size the add-in sets the parameters, lets Fusion rebuild, writes a STEP file of the picked body, and moves
on. All numbers in the file are in millimetres and degrees.

When the design holds more than the picked body, the add-in copies the picked body into a temporary component,
exports that, and deletes it. The export stops if the timeline marker is not at the end. This route is a choice,
not a proven fact: section 3 of `docs/hand-tests.md` decides it. To ask the designer to hide or move other bodies instead, set `MULTI_BODY_ROUTE`
in `ParamabilityExport/lib/fusion_reader/step_export.py` to `ROUTE_ASK_DESIGNER`.

## Limits

- One solid body per export.
- A recipe covers the picked body only, built from the root component. These stop the copy and leave a plain part:
  thin extrudes, face outlines, spline and other free curve outlines, extrudes that start or end on a tilted or curved
  surface, extrudes that make a new component, modeled threads, rounds with variable or chord length sizes or curvature
  continuity, shells that grow outward, close the body or round their corners, patterns of faces or bodies, patterns
  that spread to both sides of the start, mirrors of faces, a combine with a tool
  body that has more than one step, and every step type not listed above (sweep, loft, coil, move, draft, emboss).
- Some steps are copied with a note instead: setback corners, a cosmetic thread (cut as a plain hole), a round or
  chamfer with more than 32 edges (picked in groups), and a direction or size that Fusion stored two ways.
- To read the steps, the add-in moves the timeline marker through the design and puts it back at the end.
- Only plain number parameters can be columns. A parameter worked out by a formula cannot, and neither can one in a unit this export cannot convert (units other than mm, cm, m, in, ft, deg, rad or none).
- Paramability opens up to 256 MB per size and 1 GB per file. The export stops with a message above that.
- Only bodies of the top level of the design can be picked, not bodies inside a component.
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
