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
   "formula" and follows the parameters it reads. A parameter that drives a joint is not ticked to start with: the part
   does not follow it in the assembly. You can still tick it; its row then says "size, may be unexpected". Click a row
   to read its comment, its formula or the full reason in the box under the table. You can tick up to 64 sizes. Each
   one gets a check, an extra STEP export, so many ticks make the export slower. Tick "Keep doubtful sizes fixed" to
   keep every size the add-in cannot follow fully as a fixed number instead (see below).
4. If a step of the body cannot be copied, a warning shows under the body picker as soon as you pick it: which
   step stops the copy (for example "Extrude9 (extrude)"), and that the part will be saved as a fixed shape while your
   parameters still come along as variables. Hover the warning for the full reason. "Show in timeline" selects that
   step in Fusion; the timeline marker does not move. A line "Copied with a note" lists steps that were copied with a
   remark.
5. Pick the design up direction, click OK and choose where to save the file.
6. A window then lists each size with its range and its check ("matches Fusion", "not checked", "may be unexpected",
   "kept fixed"), what stays fixed and why, which sizes may give unexpected results and why, and how many parameters
   come along as variables. If this window cannot open, the same text is shown in a message box.
7. Open the file in Paramability. The sizes land on the form as variables, ready to configure.

Each ticked size has a range: you can type it in the table. It starts from a comment such as `Wall [1..6]` on the
parameter, otherwise from half to double the current value (a count goes from 1 to twice its value). A parameter that sets how many copies a pattern
makes is a whole number. The add-in first works out which sizes the copied steps really use, then checks each of
those once: it sets that size to the top of its range, writes a STEP file of the part, and puts it back. Paramability
builds the recipe at that value and compares it with the STEP file. A size that does not match is kept as a fixed
number.

The add-in also tries the other end of each range (the bottom, for a check at the top), with a rebuild only. When
Fusion cannot build the part at an end (for example a chamfer that no longer fits), the add-in does not fix the size.
It tries again half way toward the current value, then a quarter of the way, then an eighth of the way (at most three
more tries, each a rebuild). The value that builds becomes the new end of the range. When none builds, the current
value becomes that end, so the size can still move the other way, and a check at the top that could not stay moves
to the bottom. The message after the export says so, for example "Wall thickness: the range ends at 2 mm, since
Fusion cannot build the part at 2.5 mm (Chamfer1 fails)." If you typed that end yourself, the message says so. The
progress window says "Trying size ..." for these tries, and Cancel works there too. Only a size that builds at no
other value on either side stays a fixed number.

A size can also move a sketch: a rectangle width, a hole position, or a plane that a sketch sits on. The add-in then
sets the size to other values, only lets Fusion rebuild (no STEP file), and reads the sketch each time. From these
readings it writes the sketch value as a formula of your parameters, such as `0.5 * FilterBox_width_mm`, so the sketch
follows the size in Paramability. This adds about one rebuild per size that moves a sketch, plus two. The progress
window says "Trying size ..." for these steps, and Cancel works there too.

Some sizes the add-in cannot follow fully: a size that moves a joint, or the part in the assembly, or a sketch in a
way the add-in cannot copy, a pick (an edge of a round or chamfer) that may move with it, a pick on a pattern copy
whose count would have to change, or a step drawn on another component's sketch that would stop meeting the part.
These cases cannot be copied in a sketch: a point that moves along a curve (an angle or a polar placement), an outline
that changes shape (a line that only crosses the outline above some width, a sketch pattern whose count follows a
size), a sketch plane that turns, a sketch that a step uses in another way (a pattern direction, a path), a
construction plane or axis that a step reaches to directly, and a size that would shrink an outline to nothing.
Such a size stays a size, marked "may give unexpected results" with the reason: the parts of the shape that cannot
follow it keep their numbers, so the part looks the same at the current values, and everything else follows. Its
check still runs, and Paramability shows the warning next to the size. With "Keep doubtful sizes fixed" ticked, these
sizes stay fixed numbers instead. A size that no copied step can follow at all, or that Fusion cannot build at any
other value, always stays a fixed number, with the reason in the message after the export and in the file.
A ticked parameter that no copied step uses is not a size; the message after the export names it.
When a step cannot be copied, the file holds the plain part only. The message after the export starts with the
first step that stopped it, and the lower-right corner of the Fusion window shows a short line with the same step
(Fusion decides how long it stays). A copy of what the add-in read is saved inside the file as `report.json`.

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
exports that, and deletes it. Fusion puts the copy at the timeline marker, and the add-in deletes only what the copy
added, so the steps after the marker stay as they are. This route is a choice,
not a proven fact: section 3 of `docs/hand-tests.md` decides it. To ask the designer to hide or move other bodies instead, set `MULTI_BODY_ROUTE`
in `ParamabilityExport/lib/fusion_reader/step_export.py` to `ROUTE_ASK_DESIGNER`.

## Limits

- Every size check and probe row starts from the saved values: before each row after the first the add-in puts the
  parameters back and recomputes, so a sketch with two solutions cannot stay flipped from the row before. This costs
  one more recompute per row.
- One solid body per export.
- A body inside a component (at any depth) exports as a recipe with sizes, like a root body, and lands where Fusion
  shows it. If the part was moved by hand, capture its position first (Position, Capture Position); the export asks
  for it. A size that makes the part move in the assembly may give unexpected results, with the reason. A component
  used several
  times exports the copy you picked.
- These stay a fixed shape with a note: a part from a linked design, a place in the assembly that cannot be read, a
  step of another component that changes the body, a body made in another component and moved in, and a step that
  reaches into another component's faces, edges or bodies. A step that uses a sketch of another component is copied
  where Fusion shows it and follows the sizes the probe saw move it; where it would stop meeting the part (a slot that
  no longer reaches its wall, a rail that comes off), the size keeps the range Fusion builds and may give unexpected
  results past that value, with the reason. With "Keep doubtful sizes fixed" the range is shortened instead.
- A recipe covers the picked body only. Parameters made by steps or sketches of other bodies are left out where the
  add-in can match them by name; construction planes, axes and joints are read for the component and the ones above
  it. A size that turns a sketch plane, moves a point along a curve, or changes the shape of an outline may give
  unexpected results.
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
- The export works on the design as it is at the timeline marker. If you drag the marker back, the steps after it
  are left out of the part, and the dialog says so ("Exporting the design as it is at the timeline marker (step 48
  of 120)"). To read the steps, the add-in moves the marker through the design and puts it back where it was.
- In Export size choices, only plain number parameters can be columns. A parameter worked out by a formula cannot, and neither can one in a unit this export cannot convert (units other than mm, cm, m, in, ft, deg, rad or none).
- Paramability opens up to 256 MB per size and 1 GB per file. The export stops with a message above that.
- The design needs history (a parametric design).
- Made for the current Fusion release.
- This is version 0.4.4. The Fusion side has not been run by a tool: see `docs/hand-tests.md`.

## Tests

The package writer and the export logic (`lib/package/`, `lib/export_plan/`) do not need Fusion. The Fusion
reading code is tested with fakes. Anything that touches `adsk` stays in `lib/fusion_reader/`, `lib/fusion_ui/` and
`commands/`. From this folder:

```
python3 -m unittest discover -s tests -t .
```

Python 3.10 or newer, standard library only.
