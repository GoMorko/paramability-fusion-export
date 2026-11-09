# Paramability export for Fusion

An add-in for Autodesk Fusion that saves a body as a `.paramability` file. Paramability opens it as a part whose
sizes are your Fusion user parameters, ready on the form. Your Fusion licence still applies to what you export:
Personal is for non-commercial use, Education is for learning only.

Autodesk and Fusion are trademarks of Autodesk, Inc. Paramability is not affiliated with Autodesk. Rules for sharing
this add-in are in `docs/publishing.md`.

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
3. Look at the parameter table. Each row is one user parameter: a tick, its name, its value now, and what it becomes in
   Paramability. Parameters the picked body uses are ticked to start with (your favourites first); pick another body
   and the ticks follow that body. "Tick what the body uses" and "Untick all" set them again in one click. A ticked
   row has a Min and a Max: they start from the comment rule below, and you can type your own numbers (in the length
   unit of your design, in degrees, or whole numbers for a count; a typed unit such as `2 in` is read too). The
   current value must sit between them. An unticked row says "stays 3 mm". A parameter worked out by a formula says
   "formula" and follows the parameters it reads. A parameter that drives a sketch dimension, a construction plane or
   axis, or a joint cannot be a size for now: it is greyed out and its row says why. Click a row to read its comment,
   its formula or the full reason in the box under the table. You can tick up to 64 sizes. Each one gets a
   check, an extra STEP export, so many ticks make the export slower.
4. Pick the design up direction, click OK and choose where to save the file.
5. A window then lists each size with its range and its check ("matches Fusion", "not checked", "kept fixed"), what
   stays fixed and why, and how many parameters come along as variables. If this window cannot open, the same text is
   shown in a message box.
6. Open the file in Paramability. The sizes land on the form as variables, ready to configure.

Each ticked size has a range: you can type it in the table. It starts from a comment such as `Wall [1..6]` on the
parameter, otherwise from half to double the current value (a count goes from 1 to twice its value). A parameter that sets how many copies a pattern
makes is a whole number. The add-in first works out which sizes the copied steps really use, then checks each of
those once: it sets that size to the top of its range, writes a STEP file of the part, and puts it back. Paramability
builds the recipe at that value and compares it with the STEP file. A size that does not match is kept as a fixed
number.

A size stays a fixed number, with the reason in the message after the export and in the file, when Fusion cannot
build the part at the checked value, or when it moves a sketch (sketches that follow sizes come in a later version).
A ticked parameter that no copied step uses is not a size; the message after the export names it.
When a step cannot be copied, the file holds the plain part only, and the message names the first step that stopped
it. A copy of what the add-in read is saved inside the file as `report.json`.

Every plain part or recipe the add-in writes (also the one size case of Export size choices) also lists the design's user parameters
(up to 64, in Fusion order) with their current values, units and comments. A parameter worked out by a formula keeps
its formula when it can be copied, so Paramability gets the variables even when the shape stays fixed. This includes
helper parameters that only other formulas read. Parameters in other units than length, angle or no unit (a mass, a
time) are left out. In Export for Paramability, `report.json` says how many were
listed and which were left out and why.

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
- A body inside a component (at any depth) exports as a recipe with sizes, like a root body, and lands where Fusion
  shows it. If the part was moved by hand, capture its position first (Position, Capture Position); the export asks
  for it. A size that makes the part move in the assembly stays fixed, with the reason. A component used several
  times exports the copy you picked.
- These stay a fixed shape with a note: a part from a linked design, a place in the assembly that cannot be read, a
  step of another component that changes the body, a body made in another component and moved in, and a step that
  reaches into another component's faces, edges or bodies. A step that uses a sketch of another component is copied
  where Fusion shows it; the sizes that move that sketch stay fixed.
- A recipe covers the picked body only. Parameters made by steps or sketches of other bodies are left out where the
  add-in can match them by name; construction planes, axes and joints are read for the component and the ones above
  it. Sizes cannot move sketches yet.
  These stop the copy and leave a plain part:
  thin extrudes, face outlines, spline and other free curve outlines, extrudes that start or end on a tilted or curved
  surface, extrudes that make a new component, modeled threads, rounds with variable or chord length sizes or curvature
  continuity, shells that grow outward, close the body or round their corners, patterns of faces or bodies, patterns
  that spread to both sides of the start, mirrors of faces, a chamfer with two different sizes whose sides could not be
  measured, a press pull (offset
  faces) of a curved face, of a face with a leaning or rounded side, or of two faces that meet, a combine with a tool
  body that has more than one step, and every step type not listed above (sweep, loft, coil, move, draft, emboss).
- Some steps are copied with a note instead: setback corners, a cosmetic thread (cut as a plain hole), a round or
  chamfer with more than 32 edges (picked in groups), and a direction or size that Fusion stored two ways.
- To read the steps, the add-in moves the timeline marker through the design and puts it back at the end.
- In Export size choices, only plain number parameters can be columns. A parameter worked out by a formula cannot, and neither can one in a unit this export cannot convert (units other than mm, cm, m, in, ft, deg, rad or none).
- Paramability opens up to 256 MB per size and 1 GB per file. The export stops with a message above that.
- The design needs history (a parametric design).
- Made for the current Fusion release.
- This is version 0.3.2. The Fusion side has not been run by a tool: see `docs/hand-tests.md`.

## Tests

The package writer and the export logic (`lib/package/`, `lib/export_plan/`) do not need Fusion. The Fusion
reading code is tested with fakes. Anything that touches `adsk` stays in `lib/fusion_reader/`, `lib/fusion_ui/` and
`commands/`. From this folder:

```
python3 -m unittest discover -s tests -t .
```

Python 3.10 or newer, standard library only.
