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
2. Click Export for Paramability and pick the body (or several bodies, see "Several bodies in one file").
3. Look at the parameter table. Each row is one user parameter: a tick, its name, its value now, and what it becomes in
   Paramability. Parameters the picked body uses are ticked to start with (your favourites first); pick another body
   and the ticks follow that body. "Tick what the body uses" and "Untick all" set them again in one click. A ticked
   row has a Min and a Max: they start from the comment rule below, and you can type your own numbers (in the length
   unit of your design, in degrees, or whole numbers for a count; a typed unit such as `2 in` is read too). The
   current value must sit between them. An unticked row says "stays 3 mm". A parameter worked out by a formula says
   "formula" and follows the parameters it reads. A parameter that changes another component that the body is drawn
   around (for example the diameter of a pipe whose outline a hole in the body follows) is ticked too, and its row
   says so. A parameter that drives a joint is not ticked to start with: the part does not follow it in the assembly.
   You can still tick it; its row then says "size, may be unexpected". Click a row to read its comment, its formula
   or the full reason in the box under the table. You can tick up to 64 sizes.
4. If a step of the body cannot be copied, a warning shows under the body picker as soon as you pick it: which
   step stops the copy (for example "Extrude9 (extrude)"), and that the part will be saved as a fixed shape while your
   parameters still come along as variables. Hover the warning for the full reason. "Show in timeline" selects that
   step in Fusion; the timeline marker does not move. A line "Copied with a note" lists steps that were copied with a
   remark.
5. Pick the design up direction, click OK and choose where to save the file.
6. A window then lists each size with its range and what it becomes in Paramability ("size", "may be unexpected",
   "kept fixed", "not followed" or "not used"), what stays fixed and why, which sizes may give unexpected results
   (loose sizes) and why, and how many parameters come along as variables. If this window cannot open, the same text
   is shown in a message box.
7. Open the file in Paramability. The sizes land on the form as variables, ready to configure.

### What the export does

The export reads the steps of the body, tries the sizes that move a sketch (see below), and writes the file. While it
works it sets parameters to other values for a moment, only to let Fusion rebuild and to measure the sketches (no STEP
file is made for these tries); every parameter is put back, whatever happens. Reading the steps may move the timeline
marker, and it is put back. Every ticked parameter that a copied step reads becomes a free
size with its current value and the range in the table. You set the final Min and Max in Paramability. The file has no
size checks (`checks` is empty). The only sizes that become fixed numbers are the ones
that would make the recipe invalid (for example a formula too long to write). A ticked parameter that no copied step
reads is not a size; it still comes along as a variable.

A sketch can also follow another component without a parameter of the body: a hole drawn around a pipe, with its
circle projected from the pipe or constrained to it. The add-in reads which components and bodies each sketch is tied
to this way. For each user parameter it follows where it acts: a sketch dimension acts on its sketch and on the steps
that use that sketch, and those steps shape bodies of their component. A parameter that shapes the pipe body the hole
is drawn around is ticked to start with and tried like a size behind a sketch dimension: if the sketch moves with it
and the tries can follow, it is a free size and the outline follows it; if the outline changes in a way the tries
cannot follow, it is "not followed" with the reason; if nothing in the part moves with it, it is "not used", with the
reason that it was tried and changes nothing in this part. Up to 8 more ticked parameters that nothing seems to tie
to the part are tried too, after the others, since you know your design.

A step can also use a plane, axis or point of another component directly (a mirror plane, a pattern axis, a face an
extrude reaches to, a hole point). The export reads where that place is at every size it tries and fits how far it
moves (a plane along its normal, an axis or point in space). A parameter that acts on the component that owns such a
place is ticked to start with and tried like a parameter behind a sketch. The copy then follows the place as a formula
of the sizes: a mirror plane, a pattern or revolve axis, the face or plane an extrude reaches to or starts from, and the
point or flat face a hole sits on move with the parameter, and the parameter stays a free size. A parameter that acts
on that component but does not move the place is not marked. A place that turns with a parameter, or moves in a way the
tries cannot follow, marks that parameter "may give unexpected results" with the step and the other component named;
so does a place the tries could not measure. The result is kept in `report.json` (`probe.motion.refs`).

When a sketch of the part is tied to another component, or a step uses a place of one, the export also tries up to 12
unticked parameters that act on other components, once each, in the rows left under the cap. These tries only look: a parameter that moves the
part is named in the result window ("These parameters also change this part"), and you tick it and export again to
get it as a size.

Some sizes the add-in cannot follow fully: a size that moves a sketch in a way the tries could not follow, a plane or
axis, a joint, a pick (an edge of a round or chamfer) that may move with it, a pick on a pattern copy whose count would
have to change, a step drawn on another component's sketch that could stop meeting the part, a taper that could reach
45 degrees. Such a size stays a free size. It is marked "may give unexpected results" with the reason, which starts
with the Fusion name of the parameter and, where the add-in can tell, the value past which the problem starts. Paramability
shows a warning mark next to it. The parts of the shape that cannot follow it keep their numbers, so the part looks
the same at the current values. The result window lists these loose sizes.

A size can also move a sketch: a rectangle width, a hole position, or a plane that a sketch sits on. The add-in then
sets the size to other values, lets Fusion rebuild, and reads the sketch each time. From these
readings it writes the sketch value as a formula of your parameters, such as `0.5 * FilterBox_width_mm`, so the
sketch follows the size in Paramability. This adds about one rebuild per size that moves a sketch, plus two. The
progress window says "Trying size ..." for these steps, and Cancel works there too. A try that Fusion cannot build is
dropped; no size is fixed for it. A size the readings still cannot follow is loose.

These cases cannot be copied in a sketch even with the tries: a point that moves along a curve (an angle or a
polar placement), an outline that changes shape (a line that only crosses the outline above some width, a sketch
pattern whose count follows a size), a sketch plane that turns, a sketch that a step uses in another way (a pattern
direction, a path), a construction plane or axis that a step reaches to directly, and a size that would shrink an
outline to nothing. Such a size is loose, as above.

Each size has a range: you can type it in the table. It starts from a comment such as `Wall [1..6]` on the parameter,
otherwise from half to double the current value (a count goes from 1 to twice its value). A parameter that sets how
many copies a pattern makes is a whole number.

A size is labelled with the name of its Fusion parameter; the Fusion comment goes into the variable list as the
description of the variable.

When a step cannot be copied, the file holds the plain part only. The message after the export starts with the
first step that stopped it, and the lower-right corner of the Fusion window shows a short line with the same step
(Fusion decides how long it stays). A copy of what the add-in read is saved inside the file as `report.json`; its `probe` record holds the tries
for the sketches, and its `health` record says whether the design came back to its start.

Every plain part or recipe the add-in writes (also the one size case of Export size choices) also lists the design's
user parameters (up to 64, in Fusion order) with their current values, units and comments. A parameter worked out by a formula keeps
its formula when it can be copied, so Paramability gets the variables even when the shape stays fixed. This includes
helper parameters that only other formulas read. Parameters in other units than length, angle or no unit (a mass, a
time) are left out. In Export for Paramability, `report.json` says how many were
listed and which were left out and why.

### Several bodies in one file

Pick two or more bodies (up to 32) in the body picker of Export for Paramability to save them in one file. Paramability
opens one object per body, each where Fusion shows it, with one set of sizes on the form: a parameter is one size for
every body that reads it, so changing `Wall` rebuilds every body that uses it. One body gives the file described above,
unchanged.

- The table ticks every parameter that any picked body uses. The warning under the picker names each body that stops
  the copy.
- A body that cannot be copied (or whose steps cannot be read) is saved as a fixed shape next to the editable bodies,
  with its own note. The other bodies keep their recipes and sizes.
- The sketches of all bodies are tried together over one set of rows (at most 64 in all, not per body), so the export
  takes about as long as for the body with the most sketches plus one read per body per row. A size left without a row
  is marked "may give unexpected results".
- A size that must stay a fixed number for one body is fixed for all. A size that may give unexpected results in one
  body is marked for the whole file; each reason starts with the bodies it was found for.
- Places are fixed: each body lands where Fusion shows it now. A size that moves a body in the assembly (a joint) is
  marked, as for one body. A component used several times is not expanded: one body is saved once per pick.
- The result window lists the sizes once and has a short line per body.
- The file is a package of kind `parts`: `manifest.json` (`parts`: name, step, optional recipe, note and loose sizes per
  part; shared `parameters`, `fixed` and `notes`), `parts/NN/part.step`, `parts/NN/recipe.json` and one `report.json`
  with a record per body (its capture, steps, sizes and probe).

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

Export for Paramability writes one STEP file of the picked body as it is, and sets parameters only for the sketch
tries. Export size choices sets the parameters for each size, lets Fusion rebuild, writes a STEP
file of the picked body, and moves on. All numbers in the file are in millimetres and degrees.

When the design holds more than the picked body, the add-in copies the picked body into a temporary component,
exports that, and deletes it. Fusion puts the copy at the timeline marker, and the add-in deletes only what the copy
added, so the steps after the marker stay as they are. This route is a choice,
not a proven fact: section 3 of `docs/hand-tests.md` decides it. To ask the designer to hide or move other bodies instead, set `MULTI_BODY_ROUTE`
in `ParamabilityExport/lib/fusion_reader/step_export.py` to `ROUTE_ASK_DESIGNER`.

## Limits

- Every size row and sketch try starts from the saved values: before each one after the first the add-in puts the
  parameters back and recomputes, so a sketch with two solutions cannot stay flipped from the row before. This costs
  one more recompute per row.
- One solid body per part. Several bodies go in one file as parts (see "Several bodies in one file").
- A body inside a component (at any depth) exports as a recipe with sizes, like a root body, and lands where Fusion
  shows it. If the part was moved by hand, capture its position first (Position, Capture Position); the export asks
  for it. A component used several times exports the copy you picked.
- These stay a fixed shape with a note: a part from a linked design, a place in the assembly that cannot be read, a
  step of another component that changes the body, a body made in another component and moved in, and a step that
  reaches into another component's edges, bodies or curved faces. A step that uses a sketch of another component is copied
  where Fusion shows it and follows the sizes the probe saw move it; where it could stop meeting the part (a slot that
  no longer reaches its wall, a rail that comes off), the size may give unexpected results, with the reason and the
  value past which it starts.
- A mirror plane, pattern or revolve axis, a flat face or plane an extrude starts from or reaches to, a hole on sketch
  points or on a flat face of another component, and a pattern direction taken from one, are copied and follow the
  sizes the tries measured (see above). Where the tries could not measure the place, or it turns, the size that may move
  it is marked "may give unexpected results" with the step named. An origin plane or axis of another component is treated the same way, since it moves with that component. A hole placed
  on an edge of another component, and an extrude that starts from or reaches to a curved face of one, stop the copy.
- A link to another component is found only through the sketch itself: a projected curve or point, a constraint to
  one, or a sketch drawn on that component's face. A sketch that follows another component in another way (through
  a construction plane or axis built on it, or a pattern reaching into it) is not linked; the tries of unticked
  parameters may still name it, and a parameter you tick by hand is tried.
- A recipe covers the picked body only. Parameters made by steps or sketches of other bodies are left out where the
  add-in can match them by name; construction planes, axes and joints are read for the component and the ones above
  it. A size that turns a sketch plane, moves a point along a curve, or changes the shape of an outline may give
  unexpected results.
  These stop the copy and leave a plain part:
  thin extrudes of an open line, of several outlines, of an outline with holes, that go two ways, reach to a face or
  have a taper, face outlines, a text or spline outline that is too big or too complex (see below), extrudes that start or end on
  a tilted or curved surface, an emboss on a curved face, an emboss that is moved or turned on its face, drawn on a
  plane tilted to its face or set to follow tangent faces that are rounded, extrudes that make a new component, modeled threads, rounds with variable or chord length
  sizes or curvature continuity, shells that grow outward, close the body or round their corners, patterns of faces or bodies, patterns
  that spread to both sides of the start, mirrors of faces, a chamfer with two different sizes whose sides could not be
  measured, a press pull (offset
  faces) of a curved face, of a face with a leaning or rounded side, or of two faces that meet, a combine whose
  tool body has any step that does not add material (a cut, a round, a chamfer, a shell, a hole, a pattern or mirror,
  a pasted body, a Move), a keep-only-the-shared-part combine whose tool has more than one step, and every
  step type not listed above (sweep, loft, coil, move, draft).
  A Remove of another body, a Split Face (the solid stays the same, so picks on its faces may not follow) and steps of
  other bodies that are never joined to the picked body do not stop the copy.
- A Combine is copied when its tool body is made by steps that only add material (a new body, then extrudes or
  revolves that join it). Each tool step is written with the Combine's operation: a cut removes the tool steps one
  after the other, a join adds them. A step of the tool that starts from or reaches to a face is refused when the tool
  has more than one step. A tool the Combine keeps can serve a second Combine. The message after the export names
  the step of the tool that stops it (for example "Fillet1 (fillet)"), so you know what to change in Fusion.
- The tool body may be made in another component. The add-in then reads the steps that made it in that component
  (up to 40 steps in all), and writes them where the tool component sits in the assembly, turned and moved as
  Fusion shows it. The sizes of those steps, including sketch dimensions of the tool, are sizes of the part like any
  other. A size that moves the tool's component is followed when the tries can measure it; one they cannot follow
  ("puts its tool at the place of Rod that turns with it") may give unexpected results. The message after the export
  names the step and the component of a tool that stops the copy. A tool made by Copy Paste Body, or moved with
  Move, is not copied yet and stops the copy, naming the step.
- Sketch outlines with a spline edge, an elliptical arc or another free curve are copied as spline segments. The add-in
  reads the Fusion curve as a fine chain of points and picks points for the app's own smooth curve so that it stays
  within 0.005 mm of that chain, also between its points (a long or tight curve is split into several segments). A size that moves a sketch
  holding such a curve cannot be followed: it stays loose with the reason, or is left out of the sizes, because the
  points of the curve are not a formula of the sizes. An outline of more than 1000 points is not copied.
- Sketch text (`Text` in a sketch) is read as outlines and copied by Extrude and Emboss like any other outline: each
  letter shape is one outline step, a hole in a letter (the inside of an "o") is kept. A text with more than 400
  outlines, 1000 points in one outline or 256 holes in one letter is not copied ("This text has too many outline
  points to copy"). A size that moves the sketch of a text, or sets the height of the text, cannot be followed: it stays loose
  or is left out of the sizes, with the reason. An emboss of text must grow or shrink the part by the text area
  times the depth, as for other outlines.
- An Emboss of sketch outlines on a flat face is copied as an extrude that starts on the face: it raises the outline
  when its depth is positive and sinks it when the depth is negative. The depth follows a parameter. The copy checks
  that the part grows or shrinks by the outline area times the depth, so an outline that runs past its face stops the
  copy.
- A thin extrude of one closed outline (a wall along a rectangle or circle, for lids and boxes) is copied with its wall
  thickness as a size. The side of the wall (inside, outside or both ways) is taken from the measured end face, since
  the API does not say which of Fusion's side one and side two is which. Where Fusion keeps the corners of the wall
  sharp, the copy rounds them and says so. A later pick on the wall's faces is placed on earlier steps or its
  sizes may give unexpected results.
- A formula that uses `%` is copied only when its left side stays at or above zero over the size ranges; the app and
  Fusion may disagree on negative values.
- Some steps are copied with a note instead: setback corners, a cosmetic thread (cut as a plain hole), a round or
  chamfer with more than 32 edges (picked in groups), a direction or size that Fusion stored two ways, and a step that
  Fusion shows a warning on.
- The export works on the design as it is at the timeline marker. If you drag the marker back, the steps after it
  are left out of the part, and the dialog says so ("Exporting the design as it is at the timeline marker (step 48
  of 120)"). To read the steps, the add-in moves the marker through the design and puts it back where it was.
- In Export size choices, only plain number parameters can be columns. A parameter worked out by a formula cannot, and neither can one in a unit this export cannot convert (units other than mm, cm, m, in, ft, deg, rad or none).
- Paramability opens up to 256 MB per size and 1 GB per file. The export stops with a message above that.
- The design needs history (a parametric design).
- Made for the current Fusion release.
- This is version 0.7.1. The Fusion side has not been run by a tool: see `docs/hand-tests.md`.

## Code layout

The add-in code is in `ParamabilityExport/lib/`, one package per job. A package imports only packages above it in this
list (lowest first); `tests/test_boundary.py` holds the exact table.

- `package`: the `.paramability` file: units, rows, manifest, caps, file names, zip writer.
- `params`: Fusion parameters as sizes: names, defaults, expression to formula, the size table.
- `sketch_values`: the motion file of sketch values and measured references that follow sizes, its keys and coverage.
- `design_edit`: setting parameter values row by row, restoring them, the timeline marker, the temporary copy.
- `translator`: a capture dict in, a recipe plus verdicts out (one handler per step kind).
- `probe`: measures sketches and the places of other components' planes, axes and points at other size values and fits the motion file.
- `export_plan`: the export itself: the pipeline, the recipe and its notes, the probe run, size offers.
- `dialog_model`: what the dialogs show, as plain data (rows, Sizes table, result view, stop warning).
- `fusion_reader`: reads the design with `adsk` into a capture (one of two packages that use `adsk`).
- `fusion_ui`: draws the dialogs and handles their events with `adsk`.
- `commands/`: the two buttons, their flows and the panel; the top of the tree.

## Tests

Everything under `lib/` except `fusion_reader/` and `fusion_ui/` is pure Python and runs without Fusion. The Fusion
reading code is tested with fakes. Anything that touches `adsk` stays in `lib/fusion_reader/`, `lib/fusion_ui/` and
`commands/`. `tests/test_boundary.py` checks that and which package may import which, so imports only go one way.
From this folder:

```
python3 -m unittest discover -s tests -t .
```

Python 3.10 or newer, standard library only.

To make the export copy one more kind of Fusion step, follow `docs/adding-a-step-type.md`.
