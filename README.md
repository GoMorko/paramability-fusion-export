# Paramability export for Fusion

A Fusion add-in that saves a design as a `.paramability` file. Paramability opens it with a size dropdown, so one
file holds several sizes of the same part.

## Install

1. Get the folder: clone this repository, or download the release zip and unzip it.
2. In Fusion, click the Utilities tab, then Scripts and Add-Ins.
3. In the dialog, click the plus icon near the top of the list and choose "Script or add-in from device".
4. Pick the `ParamabilityExport` folder (the folder itself, not a file in it). Fusion remembers the location.
5. Find it in the list and click Run. Turn on "Run on Startup" to load it each time.

Two buttons show in the Utilities tab, in the panel "Paramability": "Export for Paramability" and "Export size choices".

## Use

### Export for Paramability

Saves one body with its modeling steps and your user parameters as sizes. Paramability opens it as an editable part.
Nothing is typed in Fusion.

1. In Fusion, mark the user parameters you want to change in Paramability as favourites (optional).
2. Click Export for Paramability and pick the body.
3. Under "Sizes you can change in Paramability", check the list. Parameters the body uses are ticked to start with
   (your favourites first). A parameter worked out by a formula shows "(formula)" and follows the parameters it
   reads. Unticked parameters stay fixed numbers. A parameter that cannot be a size is greyed out, and its tooltip
   says why.
4. Pick the design up direction, click OK and choose where to save the file.
5. Open the file in Paramability. The sizes are ready for the "Put on the form" button.

Each ticked size has a range: a comment such as `Wall [1..6]` on the parameter sets it, otherwise it is half to
double the current value (a count goes from 1 to twice its value). The add-in checks every size once: it sets that
size to the top of its range, writes a STEP file of the part, and puts it back. Paramability builds the recipe at that
value and compares it with the STEP file. A size that does not match is kept as a fixed number. Up to 16 sizes are
checked, favourites first; the rest are saved as sizes without a check.

A size stays a fixed number, with the reason in the message after the export and in the file, when Fusion cannot
build the part at the checked value, or when it moves a sketch (sketches that follow sizes come in a later version).
When a step cannot be copied, the file holds the plain part only, and the message names the first step that stopped
it. A copy of what the add-in read is saved inside the file as `report.json`.

### Export size choices

Saves ready-made sizes of one body as a dropdown. Paramability opens one shape per size.

1. Click Export size choices and pick the body. Under "Parameters that change between sizes", tick the user
   parameters that differ from size to size (your favourites are ticked to start with; the group can be collapsed).
   A parameter worked out by a formula, or in a unit this export cannot convert, is greyed out, and its tooltip says
   why.
2. In the Sizes table each row is one size: a name, then a number for each ticked parameter, in that parameter's own
   unit. The table starts with one row, "Default", at the current values. "Add size" copies the selected row (or the
   last one) as "Size 2", "Size 3" and so on. "Remove size" deletes the selected row. Ticking or unticking a
   parameter changes the columns and keeps the numbers you typed. Problems show in a box under the table.
   Name the dropdown ("Name of the dropdown in Paramability").
3. Pick the default size and the design up direction.
4. Click OK and choose where to save the file, then open it in Paramability with Open.

One size saves a plain part. Two or more sizes save a part with a dropdown.

After an export, a cancel or a size that does not build, your parameters are set back to their old values.

## How it works

For each size (or each check) the add-in sets the parameters, lets Fusion rebuild, writes a STEP file of the picked
body, and moves on. All numbers in the file are in millimetres and degrees.

When the design holds more than the picked body, the add-in copies the picked body into a temporary component,
exports that, and deletes it. The export stops if the timeline marker is not at the end. This route is a choice,
not a proven fact: section 3 of `docs/hand-tests.md` decides it. To ask the designer to hide or move other bodies instead, set `MULTI_BODY_ROUTE`
in `ParamabilityExport/lib/fusion_reader/step_export.py` to `ROUTE_ASK_DESIGNER`.

## Limits

- One solid body per export.
- A body inside a component can be picked, and rows of values work for it. A recipe needs the body in the root
  component for now; a body in a component is saved as a fixed shape with a note.
- A recipe covers the picked body only, built from the root component. Sizes cannot move sketches yet.
  These stop the copy and leave a plain part:
  thin extrudes, face outlines, spline and other free curve outlines, extrudes that start or end on a tilted or curved
  surface, extrudes that make a new component, modeled threads, rounds with variable or chord length sizes or curvature
  continuity, shells that grow outward, close the body or round their corners, patterns of faces or bodies, patterns
  that spread to both sides of the start, mirrors of faces, a combine with a tool
  body that has more than one step, and every step type not listed above (sweep, loft, coil, move, draft, emboss).
- Some steps are copied with a note instead: setback corners, a cosmetic thread (cut as a plain hole), a round or
  chamfer with more than 32 edges (picked in groups), and a direction or size that Fusion stored two ways.
- To read the steps, the add-in moves the timeline marker through the design and puts it back at the end.
- In Export size choices, only plain number parameters can be columns. A parameter worked out by a formula cannot, and neither can one in a unit this export cannot convert (units other than mm, cm, m, in, ft, deg, rad or none).
- Paramability opens up to 256 MB per size and 1 GB per file. The export stops with a message above that.
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
