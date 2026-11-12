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
   "formula" and follows the parameters it reads. A plain parameter the body reads only through formulas is ticked
   too, and its row names the formula. A parameter that changes another component that the body is drawn
   around (for example the diameter of a pipe whose outline a hole in the body follows) is ticked too, and its row
   says so. A parameter that drives a joint is not ticked to start with: the part does not follow it in the assembly.
   You can still tick it; its row then says "size, may be unexpected". Click a row to read its comment, its formula
   or the full reason in the box under the table. You can tick up to 64 sizes.
4. If a step of the body stops the copy altogether (see "When a step cannot be copied"), a warning shows under the
   body picker as soon as you pick it: which step stops the copy (for example "Extrude9 (extrude)"), and that the part
   will be saved as a fixed shape while your parameters still come along as variables. Hover the warning for the full
   reason. "Show in timeline" selects that step in Fusion; the timeline marker does not move. A line "Copied with a
   note" lists steps that were copied with a remark. A step that is only left out of the copy is not in this warning:
   the result window names it after the export.
5. Pick the design up direction, click OK and choose where to save the file.
6. A window then shows short sections, each starting with a `# Title` line. Sections with nothing to say are left out:
   - `# Result`: the file, what to do next, whether it is an editable copy (or one with steps left out) and how many
     parameters come along as variables. A file with several bodies has one line per body.
   - `# Sizes`: one line per size, with its range, then "may be unexpected" (and from where) or "kept fixed" or "not
     followed" or "not used" when that applies, and the short reason in brackets. Sizes that follow come first, then
     the marked ones, then the fixed ones.
     A formula parameter that stayed a plain number is listed last as "kept as a number: name = formula (reason)".
   - `# Left out`: each step the copy left out, with the reason.
   - `# More sizes`: parameters you did not tick that also change the part, or that could not be tried. Tick them and
     export again to get them as sizes.
   - `# Check your design`: shown first, and only when something is wrong: a parameter that did not go back, sketches
     that did not come back to their first shape, or sketches that could not be measured.

   Fuller detail for debugging is in `report.json`. If this window cannot open, the same text is shown in a message
   box.
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
get it as a size. These tries are compared with the design as it reads just before them, so a sketch that Fusion
left on its other solution after the earlier tries does not count as a change. A try that does not rebuild is listed
as not tried.

Some sizes the add-in cannot follow fully: a size that moves a sketch in a way the tries could not follow, a plane or
axis, a joint, a pick (an edge of a round or chamfer) that may move with it, a pick on a pattern copy whose count would
have to change, a step drawn on another component's sketch that could stop meeting the part. Such a size stays a free size. It is marked "may give unexpected results" with the reason, which starts
with the Fusion name of the parameter and, where the add-in can tell, the value past which the problem starts. Paramability
shows a warning mark next to it. The parts of the shape that cannot follow it keep their numbers, so the part looks
the same at the current values. The result window lists these loose sizes.

A size can also move a sketch: a rectangle width, a hole position, or a plane that a sketch sits on. The add-in then
sets the size to other values, lets Fusion rebuild, and reads the sketch each time. From these
readings it writes the sketch value as a formula of your parameters, such as `0.5 * FilterBox_width_mm`, so the
sketch follows the size in Paramability. Each size that moves a sketch is first tried a quarter below and a quarter
above its value (inside its range), then, while tries are left, at the ends of its range. A size that only feeds step
values (an extrude distance, a fillet radius, a pattern count) needs no try: its formula is exact. The progress window
explains what happens and shows the try ("Try 5 of 31: HolderWidth at 32 mm"), and Cancel works there too. To save
time, Fusion rebuilds only the timeline up to the last step the part needs while the tries run (the marker moves
there, and goes back when they end; `report.json` says how many items each try rebuilt, `probe.timeline`). A try that
Fusion cannot build is dropped; no size is fixed for it. The add-in then tries that size nearer to its value now (half
way, then a quarter, then a tenth of the way to the end of its range; at most 24 such tries per export). When a nearer
try builds, the size follows between the values that built. Where one value built and a farther one did not, the add-in
also tries the values between them, halving up to four times, so the last value that builds is found closely. On a
side where Fusion did not rebuild, the range on the form stops at the last value that built, unless you typed that end
in the dialog or the failing step belongs to another component than the part; on a side the tries did not reach, the
size says "it was followed between A and B". Each cut range has one line in the result window ("range cut" with the
value and the step where Fusion did not rebuild), a reason in `report.json` (`sizes.cut`) and the same reason in the
file's `cuts` list, where Paramability shows it as a quiet note next to the size, not as a warning. In a file with several bodies a size that more than one body
reads has the narrowest cut over the bodies that were probed, and its reason says so. A size that did not rebuild at
any value tried is not a size, and the reason names the values and the step Fusion stopped at. A taper that follows
sizes gets the same kind of range: it stops before the taper reaches 45 degrees, the steepest Paramability builds.

The box "Faster tries" under the body picker is off to start with. When you tick it, the tries also turn off the
timeline steps of other components that the body does not use, so each try rebuilds less. Every step is turned back
on when the tries end, also on cancel or an error, and steps you had turned off yourself stay off. Before the tries,
the add-in checks that the body reads the same with those steps off; if not, or if it is not sure which steps the body
uses (for example when the design has joints), it turns nothing off. This is an experiment: `report.json` says what
happened and how long the tries took (`probe.timeline.suppressed`, `try_seconds`), so you can compare an export with
the box on and off.

A point can also move along a curve: the end of a leg that turns with an angle, or a corner set back by a wall along
half the angle. The add-in then looks for a formula with the angle's sine, cosine, tangent or cotangent (of the angle
or of half of it), alone or times a length, and with products of two lengths. A formula is used only when the tries
check it: every try must follow from the others. To have enough tries, the add-in sets each such size half way to its
ends and together with each other size of the same sketch (about 2 tries per curved size, plus 2 per other size it
shares a sketch with, inside the 64 tries). When no such formula fits, only that size is marked; the other sizes of
the sketch still follow, and two more tries check them together. A size the readings still cannot follow is loose.
In the step with the point that cannot follow, the formulas with sines or products leave that size out, so the
outline keeps its shape; every other step still follows it. A line whose direction turns while both its ends follow
leaves out nothing.

These cases cannot be copied in a sketch even with the tries: a point that moves along a curve no such formula
follows, an outline that changes shape (a line that only crosses the outline above some width, a sketch
pattern whose count follows a size), a sketch plane that turns, a sketch that a step uses in another way (a pattern
direction, a path), a construction plane or axis that a step reaches to directly, and a size that would shrink an
outline to nothing. Such a size is loose, as above.

Each size has a range: you can type it in the table. It starts from a comment such as `Wall [1..6]` on the parameter,
otherwise from half to double the current value (a count goes from 1 to twice its value). A parameter that sets how
many copies a pattern makes is a whole number.

A size is labelled with the name of its Fusion parameter; the Fusion comment goes into the variable list as the
description of the variable.

A copy of what the add-in read is saved inside the file as `report.json`; its `probe` record holds the tries
for the sketches, and its `health` record says whether the design came back to its start.

### When a step cannot be copied

Some steps cannot be copied yet: a coil, a sweep that twists and tapers, an extrude with a taper on a face, and others (the limits
below say which). What the add-in does then depends on the step.

Most of the time the step is left out. The add-in goes on with the steps after it, writes the copy without the
missing step, and keeps what it knew about that step in the file: its name and type, why it was left out, where it
belongs in the list of steps, how it changed the size of the part and the numbers Fusion stores for it. Paramability
opens such a part with the original shape (the STEP shape Fusion made) and an unfinished copy of its steps beside it,
and lists what is missing. You can switch between the original shape and the copy. The copy is not the part until
the missing steps are added. If you connect an AI assistant to Paramability, it can add the missing steps for you.
The add-in itself has no AI in it.

A step that picks edges or faces of a left out step is left out too, since in the copy those faces do not exist (a
round on the edges of a coil, for example). The add-in asks Fusion which step made the faces each later round,
chamfer or shell picks, and leaves out only the ones that pick faces of a missing step. When Fusion does not
answer, every later step that picks edges or faces is left out. A pattern or mirror of a left out step is left out
too (a mirror of the whole body mirrors the part with the step missing instead), and so is a Combine whose tool body cannot be copied (the Combine is one missing step; the rest of the part is
copied). The result window lists every step left out with its reason. In `report.json` each of them has the verdict
`leftOut`.

A size that only a left out step reads is still offered as a size, marked "may give unexpected results" with a reason
that says so: it changes nothing in the copy until the step is added. Sizes that other steps read too stay plain
sizes.

A part is saved as a fixed shape only in these cases. Your parameters still come along as variables, the message
after the export starts with the first step that stopped the copy, and the lower-right corner of the Fusion window
shows a short line with the same step (Fusion decides how long it stays):

- a step that cannot be copied comes before the first step the copy writes (the copy needs a body to add to), or the
  body starts in a way that cannot be copied;
- more than 16 steps would be left out of one part;
- the place of the part in the assembly cannot be used, or a step of another component or an assembly step changes
  the part;
- the body cannot be followed through the timeline, or a step cannot be read from Fusion;
- a step that Fusion shows as an error;
- a step that splits the part or makes another body. A Split Body by a plane, a flat face or a solid body is copied
  when the part comes out of it as one piece and no later step changes another piece together with it: the copy
  follows the body it was split from and removes the other side. A split along a curved surface still stops the copy;
- a recipe that is too large to open, or a list of left out steps that cannot be written.

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
  with its own note. The other bodies keep their recipes and sizes. A body with left out steps keeps its recipe and
  opens with the original shape and an unfinished copy, as for one body; the result window lists the left out steps
  of each part.
- The sketches of all bodies are tried together over one set of rows (at most 64 in all, not per body), so the export
  takes about as long as for the body with the most sketches plus one read per body per row. A size left without a row
  is marked "may give unexpected results".
- A size that must stay a fixed number for one body is fixed for all. A size that may give unexpected results in one
  body is marked for the whole file; each reason starts with the bodies it was found for.
- Places are fixed: each body lands where Fusion shows it now. A size that moves a body in the assembly (a joint) is
  marked, as for one body. A component used several times is not expanded: one body is saved once per pick.
- The result window lists the sizes once and has a short line per body.
- The file is a package of kind `parts`: `manifest.json` (`parts`: name, step, optional recipe, note, loose sizes and cut sizes per
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

- A part with left out steps is exported the same way as any other, so it takes as long as a full export. At most 16
  steps can be left out of one part; a longer list stops the copy.
- Every size row and sketch try starts from the saved values: before each one after the first the add-in puts the
  parameters back and recomputes. A sketch with two solutions can still land on its other one after a try that did
  not rebuild, and stay there. After such a try the add-in reads the design again before the next one. A size is
  blamed for a sketch that "makes a different outline" only when its own try started from the right outline and the
  outline came back after it. Such a size keeps its range up to the last value tried that kept the outline (the
  add-in halves toward it, as for a value that does not rebuild); only when no other value works is it not a size,
  and the reason says why. The tries made while a sketch stayed on its other solution count against no size, and
  the result window says so in one line. When the sketch still reads another outline after the export, the result
  window names it so you can look at it in Fusion. Fusion sometimes gives a projected curve a new name when it
  recomputes; the add-in then knows it by its place in the outline.
- A round on the four side edges of a rectangle (a slot cut, a block) whose radius is half the short side at every
  size makes round ends: the copy draws that outline as a slot and writes no round, which builds the same part.
- The rounds and chamfers on the copies of a rectangular pattern follow its count: the copy writes them for every
  count the size range allows, each kept only while the count makes its copy. Paramability cannot repeat a round
  itself yet. A round that is wider than the face next to it, or a chamfer as big as a whole face (Fusion rolls over
  such edges), may still be left out by Paramability on some copies.
- A sketch value that one size moves along a curve is copied only with the sine, cosine, tangent or cotangent of an
  angle size (or of half of it), alone or times a length, and products of two lengths, up to 3 such terms per value.
  Other curves (a square root, a power, an angle divided by a length) leave that size loose or not a size.
- A cut through all to one side cuts on the side of its sketch where it meets the part. When Fusion's stored
  direction points to a side without material there, the other side is used, with a note.
- A round or chamfer that picks an edge inside one flat side wall of an extrude (where a round meets the wall) follows
  that wall.
- A revolve axis the copy cannot use (an edge that is not straight, a face that is not round, an axis that cannot be
  read) leaves the revolve out of the copy; the reason says which of these it is.
- One solid body per part. Several bodies go in one file as parts (see "Several bodies in one file").
- A body inside a component (at any depth) exports as a recipe with sizes, like a root body, and lands where Fusion
  shows it. If the part was moved by hand, capture its position first (Position, Capture Position); the export asks
  for it. A component used several times exports the copy you picked.
- These stay a fixed shape with a note: a part from a linked design, a place in the assembly that cannot be read, a
  step of another component that changes the body, and a body made in another component and moved in. A step of the
  body that reaches into another component's edges, bodies or curved faces is left out of the copy. A step that uses a sketch of another component is copied
  where Fusion shows it and follows the sizes the probe saw move it; where it could stop meeting the part (a slot that
  no longer reaches its wall, a rail that comes off), the size may give unexpected results, with the reason and the
  value past which it starts.
- A rectangular or circular pattern that spreads copies to both sides of the original is copied as a forward and a
  backward pattern from the original, at the places Fusion measured. Its count and spacing can follow sizes. A count that
  was measured odd and can become even inside its size range may give unexpected results, since the places Fusion
  uses for an even count were not checked for it.
- A mirror plane, pattern or revolve axis, a flat face or plane an extrude starts from or reaches to, a hole on sketch
  points or on a flat face of another component, and a pattern direction taken from one, are copied and follow the
  sizes the tries measured (see above). Where the tries could not measure the place, or it turns, the size that may move
  it is marked "may give unexpected results" with the step named. An origin plane or axis of another component is treated the same way, since it moves with that component. A hole placed
  on an edge of another component, and an extrude that starts from or reaches to a curved face of one, are left out of
  the copy.
- A link to another component is found only through the sketch itself: a projected curve or point, a constraint to
  one, or a sketch drawn on that component's face. A sketch that follows another component in another way (through
  a construction plane or axis built on it, or a pattern reaching into it) is not linked; the tries of unticked
  parameters may still name it, and a parameter you tick by hand is tried.
- A recipe covers the picked body only. Parameters made by steps or sketches of other bodies are left out where the
  add-in can match them by name; construction planes, axes and joints are read for the component and the ones above
  it. A size that turns a sketch plane, moves a point along a curve, or changes the shape of an outline may give
  unexpected results.
  These steps are left out of the copy (see "When a step cannot be copied"):
  thin extrudes of an open line, of several outlines, of an outline with holes, that go two ways, reach to a face or
  have a taper, an extrude of a curved face, of several faces or of a face together with sketch outlines on another plane, a text or spline outline that is too big or too complex (see below), extrudes that start or end on
  a tilted or curved surface, an emboss on a curved face, an emboss that is moved or turned on its face, drawn on a
  plane tilted to its face or set to follow tangent faces that are rounded, extrudes that make a new component, modeled threads, rounds with variable or chord length
  sizes or curvature continuity, shells that grow outward, close the body or round their corners, patterns of faces, patterns
  that spread to both sides of the start when the original sits between two copies or the copies do not follow the
  usual places, mirrors of faces, a chamfer with two different sizes whose sides could not be
  measured, a press pull (offset
  faces) of a curved face, of a face with a leaning or rounded side, or of two faces that meet, and every
  step type not listed above (coil). A draft is copied when its faces all lie on one side of its plane, with one angle
  under 30 degrees (or the same on both sides; it follows a size only when both sides use the same formula, and the
  size range stops before 30 degrees), and the part's volume changes (it tells which way the faces lean);
  other drafts are left out. A step of that kind in a tool body leaves the Combine that
  takes the tool out of the copy, as one missing step. A Remove of another body, a Split Face (the solid stays the same, so picks on its faces may not follow) and steps of
  other bodies that are never joined to the picked body do not stop the copy.
- A sweep is copied when its outline is one closed sketch outline (holes allowed; several outlines become one sweep
  each, along the same path) and its path starts at the outline,
  square to it, and runs one way. A straight path becomes an extrude, one arc or a full circle becomes a revolve, and
  a chain of lines, arcs and spline curves in one plane, or of lines joined by tangent arcs in 3D, becomes a sweep
  step. A path of body edges is copied as measured, and such a step cannot be repeated by a pattern. The outline
  follows sizes like an extrude outline. So does a path of sketch lines and arcs that the size probe measured: a size
  behind a line length, an arc radius or a corner position becomes a formula (the extrude's distance, the revolve's axis
  point and angle, or the points of the flat path, or both corner points of a straight path that twists), the path's rules are tested over the size ranges, and the ranges
  are cut where they stop holding (past that value the path would cross itself, bend tighter than the outline, or turn
  sharply). The path start must stay on the outline's plane: a size that moves one without the other is marked "may
  give unexpected results". A path that stays as measured, with the sizes behind its sketch (or the plane, face or
  projected edges it sits on) marked: one with a spline curve, a full circle, 3D corner points, body edges or a taper,
  and a closed path cut open inside an arc. A twist, a taper, or a parallel orientation on a path that keeps moving away from the
  outline's plane becomes a sweep step too (recipe version 16); a twist or taper is copied with a note to check the
  shape, since Fusion does not document how it measures them. A closed chain of lines, arcs and spline curves in one
  plane becomes a sweep step along a closed flat path (version 16), cut open where the path meets the outline's plane;
  a full circle stays a revolve unless a twist needs the sweep step. A twist along a closed path must be whole turns
  and is copied as a number, not as a size. These sweeps are left out of the copy: a twist together
  with a taper or parallel orientation, a taper along spline curves or along a scaled outline, a taper that would close part of the outline
  or a hole, a taper of 45 degrees
  or more, a twist over 3600 degrees, a guide rail, parallel orientation on a path that turns back (the path's direction
  must keep a rise of 0.05 along the outline's normal at every point, ends and arc points included), several outlines at once that intersect the part, an outline that is a face of the part, a path of
  sketch curves mixed with edges, a closed path that bends in 3D, that is cut at a sharp corner, or that tapers or keeps
  the outline in one direction, a twist along a closed path that is not whole turns, a sharp corner in the path, a path that
  crosses itself or bends tighter than the outline allows, a path in 3D with splines or arcs that are not tangent, an
  outline in the middle of the path or not square to it, a sweep along only part of the path, a surface sweep and a
  sweep that makes a new component. A new body must have the volume the outline and path give (a parallel outline: its area times the rise of the
  path), or the sweep is left out; so is a tapered one whose volume fits neither an offset nor a scaled outline. A
  twist or taper that follows a size marks the size past the values where it would reach the limits. A twist along a
  closed path turns as Fusion walks the path. A later round or chamfer on all edges of a sweep's start or end cap names
  the step and follows its sizes, as on an extrude. The end cap is placed on a path in one plane, or for an outline
  kept in one direction. After a twist, a taper or a path that leaves one plane only the start cap is placed; a closed
  path or an outline with holes has no cap placed. A pick on part of a cap, or on a side edge at a corner of the
  outline along a path of lines and arcs, keeps its points and marks only the sizes the sweep reads. Any other pick on
  a sweep marks every size written before it.
- A loft is copied when it joins two closed sketch outlines with free ends and no rails or centre line. It is written
  with straight faces between the outlines. Both outlines need the same number of holes, and their planes must not
  cross. Outlines of different shapes are copied with a note, since Fusion may pair the corners differently. These
  lofts are left out: three or more outlines, a point end, an outline that is a face of the part, tangent or direction
  ends, rails, a centre line, a closed loft, a surface loft and a loft that makes a new component. A round or chamfer
  on all edges of an outline of a loft (no holes) names the loft and follows its sizes; a pick on part of an outline
  keeps its points and marks the sizes the loft reads, and a pick on its side marks every size before it.
- A Combine (join, cut or keep only the shared part) is copied with its tool bodies. A tool made only by steps that add
  material (a new body, then extrudes or revolves that join it) is written step by step, each with the Combine's
  operation. Any other tool becomes one tool step that holds all the steps that made the tool: its cuts, rounds,
  chamfers, holes, shells, a Combine of its own, a pasted body, a Move and a pattern of bodies. Sizes and sketches of
  those steps are sizes of the part like any other, and a later round or chamfer on the result follows them. A tool the
  Combine keeps can serve a later Combine, which gets the tool with the steps added since. Tools made from tools are
  followed 3 levels deep. The export reads up to 120 steps and 32 tool bodies in all (a pattern of many copies counts
  as one body). The message after the export names the step that stops a tool (for example "Coil1 (coil)" or "the
  tool body Body3 cannot be copied"), so you know what to change in Fusion. A tool step that starts from or reaches to a
  face of the part follows that face where the add-in can place it, and marks the sizes it cannot follow.
- Copy Paste Body is copied by writing the steps of the source again, as the source stood at the paste. The pasted
  body must be a new body: a paste that lands on a body that already has steps is left out of the copy. A copy that sits where
  its source sits keeps the sizes; a copy that sits elsewhere gets a plain-number Move, and the sizes that could change
  its place are marked "may give unexpected results". A paste of several bodies is copied when each pasted body can
  be matched to its source by its corners.
- Move of bodies is copied when the body moves as one solid. A Move along X, Y and Z, a Rotate and a free Move follow
  their distances and angles as sizes. The other kinds (point to point, to a position, along an entity) are written
  as the numbers Fusion measured. What they follow can move with any size, so every ticked size is marked or left
  out with the reason. A Move of faces, and a Move that mirrors or
  scales, are left out of the copy.
- A rectangular, circular or mirror pattern of bodies is copied when a Combine takes the copies. When the Combine takes
  the whole pattern (the original and every copy), the pattern is written as a pattern, so its count and spacing follow
  sizes. For a join the original may be the part itself. When the Combine takes only some of the copies, or the layout
  is uneven, or it keeps only the shared part, each copy is written as a tool with its place as numbers, and the sizes
  behind the layout are marked. A count that follows a size is written as if the Combine also takes the new copies.
  Since it is not known whether Fusion does this (hand test B6), that size is marked "may give unexpected results". A mirror of bodies is copied only in a Combine, together
  with its source. A body that is a copy in a pattern is copied by writing its source's steps and a Move.
- A pattern or mirror of features whose sources hold a Combine of the part, together with every step that built its tool
  bodies, repeats the Combine as it was copied, so its count, spacing and skipped copies follow sizes as for any
  pattern. A pattern that holds only some of those steps, the steps of a tool without its Combine, or a Combine that
  keeps only the shared part is left out of the copy.
- Fusion does not say what a keep-only-the-shared-part Combine with several tools keeps (the part and every tool, or
  the part and any tool). The export tries it on temporary copies, which are never added to your design, compares
  the volumes with the result Fusion made, and copies it that way. When the volumes fit neither way, or a tool lives
  in another component, the Combine is left out with "This combine keeps a shared part that the copy could not work out".
  When both ways give the same volume, the export cannot tell which one Fusion used, so the sizes of the tools are
  marked "may give unexpected results".
  A Combine whose result is more than its tool bodies can give (a cut that removes more than the tools hold) is left out too.
- The tool body may be made in another component. The add-in then reads the steps that made it in that component
  (they count in the 120), and writes them where the tool component sits in the assembly, turned and moved as
  Fusion shows it. The sizes of those steps, including sketch dimensions of the tool, are sizes of the part like any
  other. A size that moves the tool's component is followed when the tries can measure it; one they cannot follow
  ("puts its tool at the place of Rod that turns with it") may give unexpected results. The message after the export
  names the step and the component of a tool that cannot be copied. A tool from another component that reaches to a
  face becomes a tool step. A Combine inside such a tool that takes a body from yet another component makes the Combine that takes the tool a left out step.
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
  that the part grows or shrinks by the outline area times the depth. An outline that runs past its face (over a hole
  or off an edge) is trimmed to the face by Fusion: the copy then checks the end face area times the depth and limits
  the extrude to the outline of that face, holes included (`within`). That works for one flat face with no flat
  neighbour following it; the face's edges are exact when it is an untapered end of an earlier extrude, else measured
  with the sizes marked loose. Older exports lack the edges and stop the copy. An emboss whose outline is a flat face of the part is copied like an extrude from that face (below).
- An extrude whose outline is a flat face of the part is copied. When the face is the top or bottom face of an earlier
  extrude without a taper, and no round, cut or join changed that face, the copy draws that extrude's outline again
  on the face. The outline and the face then follow the sizes of the earlier extrude (its length, its start and its
  sketch). Any other flat face (the top of a tapered extrude, a face after a round) is copied as Fusion measured it,
  and the sizes of the steps before it are marked "may give unexpected results", since they may change that face. The
  length, taper and operation of the face extrude follow its own parameters in both cases. Sketch outlines on the
  face's plane may come with the face; the face is then copied as measured. Exports made with
  version 0.8.0 or older did not read the face, so export again.
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
- This is version 0.10.4. It writes recipe version 16 when a sweep needs it, which needs a Paramability build that opens version 16. The Fusion side has not been run by a tool: see `docs/hand-tests.md`.

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
The file that lists the steps left out of a copy is described in `docs/recipe-gaps.md`.
