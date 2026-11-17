# User guide

The full description of both exports: the dialogs, what the export does, steps that cannot be copied, several
bodies in one file and the result window. The README has the short version.

## Export for Paramability

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
   body picker as soon as you pick it: which step stops the copy (for example "Extrude9 (extrude)"), a "Tip" with what
   to change in Fusion when there is one, and that the part will be saved as a fixed shape while your parameters still
   come along as variables. Hover the warning for the full reason. "Show in timeline" selects that step in Fusion; the
   timeline marker does not move. Steps that the copy will only leave out are listed there too, under "Likely left
   out of the copy": the first three, each with its reason and Tip (the same words the result window uses after the
   export), then "and N more". "More may show after the export" says that some steps can only be checked during the
   export (for example a round on faces of a left out step), so the list can grow. Fix those steps first, or export
   anyway. A line "Copied with a note" lists steps that were copied with a remark. The list comes from the steps the
   dialog already read for the body, with no extra read of the design and no size tries; the Text Commands window
   shows how long it took.
5. Pick the design up direction, click OK and choose where to save the file. The file name offered is the name of the
   component that holds the body, or the name of the design for a body that is not in a component.
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

## What the export does

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
reason that it was tried and changes nothing in this part. The export says that only when the part itself stayed the
same at each try of that parameter. When the part changed but no copied step follows the parameter, it is "not
followed", with the reason that it changes this part in a way the copy does not follow; the copy keeps its value now. A parameter of a joint, or of a move that places a
component, may move the pipe against the part, so it counts for every such sketch too. Up to 8 more ticked parameters that nothing seems to tie
to the part are tried too, after the others, since you know your design.

A step can also use a plane, axis or point of another component directly (a mirror plane, a pattern axis, a face an
extrude reaches to, a hole point). The export reads where that place is at every size it tries and fits how far it
moves (a plane along its normal, an axis or point in space). A parameter that acts on the component that owns such a
place is ticked to start with and tried like a parameter behind a sketch. The copy then follows the place as a formula
of the sizes: a mirror plane, a pattern or revolve axis, the face or plane an extrude reaches to or starts from, and the
point or flat face a hole sits on move with the parameter, and the parameter stays a free size. A parameter that acts
on that component but does not move the place is not marked. A place that turns with a parameter, or moves in a way the
tries cannot follow, marks that parameter "may give unexpected results" with the step and the other component named;
so does a place the tries could not measure. The result is kept in `report.json` (`probe.motion.refs`). A parameter of
a joint, or of a move that places a component, can move every other component. The dialog offers such a parameter
as one that may move that component in the assembly, and the export tries it like a parameter behind a sketch (a
joint parameter is not ticked to start with). If the tries did not measure it, it is marked "may give unexpected results"
for each such place, and never "nothing in this part moved with it".

A plane or axis of the part's own component can be built on another component, for example a plane offset from the
XY plane of the main design while the part sits in an assembly. That plane belongs to the part, so the steps that
use it are copied. The export cannot tell which parameters move what the plane is built on. When an extrude goes up
to such a plane or a sketch sits on it, the export tries it with every ticked parameter, and a parameter that the
tries could not measure is marked "may give unexpected results". A mirror plane or a pattern axis built so marks
every ticked parameter.

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
sets the size to other values, lets Fusion rebuild, and reads the sketch each time. The values of one try go in as
one change, so Fusion rebuilds once per try, as when you edit the parameters yourself (Export size choices also
recomputes the whole design before it saves each size). From these
readings it writes the sketch value as a formula of your parameters, such as `0.5 * FilterBox_width_mm`, so the
sketch follows the size in Paramability. Each size that moves a sketch is first tried a quarter below and a quarter
above its value (inside its range), then, while tries are left, at the ends of its range. A size that only feeds step
values (an extrude distance, a fillet radius, a pattern count) needs no try: its formula is exact. The progress window
explains what happens and shows the try ("Try 5 of 31: HolderWidth at 32 mm"), and Cancel works there too. To save
time, Fusion rebuilds only the timeline up to the last step the part needs while the tries run (the marker moves
there, and goes back when they end; `report.json` says how many items each try rebuilt, `probe.timeline`). Steps of
other components that come after that point are not rebuilt, also when a sketch of the part is tied to another
component: a step only uses what comes before it in the timeline. A try that
Fusion cannot build is dropped; no size is fixed for it. A try where Fusion builds the part but a step of the part shows
a warning that it did not show before the tries counts the same way, since Fusion may have built another shape there. The add-in then tries that size nearer to its value now (half
way, then a quarter, then a tenth of the way to the end of its range; at most 24 such tries per export). When a nearer
try builds, the size follows between the values that built. Where one value built and a farther one did not, the add-in
also tries the values between them, halving up to four times, so the last value that builds is found closely. A
value past one that did not build is not tried at all, since the range stops before it anyway. On a
side where Fusion did not rebuild, the range on the form stops at the last value that built, unless you typed that end
in the dialog or the failing step belongs to another component than the part; on a side the tries did not reach, the
size says "it was followed between A and B". Each cut range has one line in the result window ("range cut" with the
value and the step where Fusion did not rebuild or showed a warning), a reason in `report.json` (`sizes.cut`) and the same reason in the
file's `cuts` list, where Paramability shows it as a quiet note next to the size, not as a warning. In a file with several bodies a size that more than one body
reads has the narrowest cut over the bodies that were probed, and its reason says so. A size that did not rebuild at
any value tried is not a size, and the reason names the values and the step Fusion stopped at. When a try leaves the
design broken (a step stays in error even with your values back), the tries stop there, since every later try would
fail for that reason; the result window says so. A taper that follows
sizes gets the same kind of range: it stops before the taper reaches 45 degrees, the steepest Paramability builds. A
tapered cut through all whose walls would meet before it passes the part at some sizes is checked over the ranges of
the sizes behind its taper and its outline, and those ranges stop where the cut would close. A length or a count
that is a formula of sizes (for example a join of `Tall - Low`) gets the same kind of range: the ranges stop where the
length would reach zero or the count would go under 1, and the formula stays.

The box "Faster tries" under the body picker is on to start with. The tries then also turn off the timeline steps of
other components that the body does not use, so each try rebuilds less. Every step is turned back on when the tries
end, also on cancel or an error, and steps you had turned off yourself stay off. Before the tries, the add-in checks
that the body reads the same with those steps off; if not, or if it is not sure which steps the body uses (for example
when the design has joints), it turns nothing off. The discovery tries, which check whether a parameter of another
component also changes the body, run with every step back on. Untick the box to keep every step on; `report.json`
says what happened and how long the tries took (`probe.timeline.suppressed`, `try_seconds`).

The list "Stop the size tries after" in the same place sets a time limit for the tries: 10 minutes to start with, or
anything from 1 minute to 2 hours, or no limit. Small designs finish their tries in seconds; a big design can spend most
of the export there. The progress window shows the time spent and about how long the tries still take. When the limit is
reached, the tries stop at the next try, every value and step goes back exactly as after any end of the tries, and the
export goes on with what was measured. Sizes that move a sketch and were not tried in time are marked "may give
unexpected results" (or "not a size", when only a sketch reads them), with the reason that the tries ran out of time and
a tip: pick a longer time, or untick sizes that do not need to change. The result window says that the tries stopped
and how many sizes were left out. The tries start with the sizes you marked as favourites in Fusion, then the others, so
a limit cuts the sizes least likely to matter first; the extra tries (the far ends of the ranges, the sizes together,
the checks of other components) come after the near tries of every size. `report.json` keeps the limit, whether it was
reached and the sizes left out (`probe.time_limit`, `timing.probe.time_limit`).

A try that reads a flat face a step uses as its outline (see `docs/limits.md`) leaves the timeline marker before that step
until the values are put back, so Fusion rebuilds the steps after it once per try instead of twice. The marker
is always back where the tries hold it before the next read and when the tries end.

The box "Lighter on memory" is off to start with, and it is an experiment too. A long export can make Fusion grow to
many GB, because Fusion keeps Undo data for every try until the export ends. When you tick the box, the add-in asks
Fusion to forget the tries as they run, each time all values are back where they were (Fusion's preview call
`Command.beginStep`). The add-in puts every value back itself, so nothing should be lost, but Undo may not step back
through the export afterwards: save your design before you export (the dialog reminds you once the box is ticked).
The Undo data of the last part of the export is dropped only when the check at the end confirms the design is as it
was: every value back, no sketch moved, no step worse or left turned off, and every check could be made. On any doubt
it is kept. When a step still looks changed after Undo data was dropped, the result window and the message box do not
send you to Undo: they say to close the design without saving and open the version you saved. If your Fusion does
not have the call or refuses it, the export runs as with the box off. `report.json` says what happened in
`timing.undo` (`on`, `applied`, `steps`) and `health.undo_dropped`.

A point can also move along a curve: the end of a leg that turns with an angle, or a corner set back by a wall along
half the angle. The add-in then looks for a formula with the angle's sine, cosine, tangent or cotangent (of the angle
or of half of it), alone or times a length, and with products of two lengths. A corner on a turned leg often needs two
to four products of a length and the sine or cosine; these are tried all at once, also with a length that moves the
point only once the angle has turned. A formula is used only when the tries check it: every try must follow from the
others. To have enough tries, the add-in sets each such size half way to its ends and together with each other size of
the same sketch (about 2 tries per curved size, plus 2 per other size it shares a sketch with, inside the 64 tries).
When no such formula fits, only that size is marked; the other sizes of the sketch still follow, and two more tries
check them together. A size the readings still cannot follow is loose. In the step with the point that cannot follow,
the formulas with sines or products leave that size out, so the outline keeps its shape; every other step still
follows it. When the outline would cross itself only in a corner of the size ranges (a turned leg shorter than
another), the ranges are cut there instead ("the outline of Sketch3 would cross itself, lose a corner or have a hole reach its edge"). The same
cut applies to any outline whose corners follow sizes, for example a corner that follows a size while the arc it
meets is written as its number, and to a hole that would leave its outline (also for a flat face used as an
outline, such as the face an emboss is trimmed to). A round or
chamfer that picks an end face of such an outline follows the outline corner nearest to its pick point, so its formula
stays short. A line whose direction turns while both its ends follow leaves out nothing.

These cases cannot be copied in a sketch even with the tries: a point that moves along a curve no such formula
follows, an outline that changes shape (a line that only crosses the outline above some width, a sketch
pattern whose count follows a size), a sketch plane that turns, a sketch that a step uses in another way (a pattern
direction, a path), a construction plane or axis that a step reaches to directly, and a size that would shrink an
outline to nothing. Such a size is loose, as above.

Each size has a range: you can type it in the table. It starts from a comment such as `Wall [1..6]` on the parameter,
otherwise from half to double the current value (a count goes from 1 to twice its value). A parameter that sets how
many copies a pattern makes is a whole number. A parameter that the pattern count reads only inside `round`,
`floor` or `ceil`, or only in a test such as `if(N > 2; 3; 5)`, keeps its decimals.

A size is labelled in plain words (`lib/params/labels.py`). A short comment on the parameter is the label (its first
sentence, without a `[min..max]` hint); a longer comment is a description, and the label is then the parameter name
in words: `BaseCup_midExtrude_offset__mm` reads "Base cup mid extrude offset", with the unit word dropped. Two sizes
never share a label. The Fusion name stays the size name, and the package `parameters` list keeps it as `label`
next to the full comment, so the form can show the name in a tip and the comment as the description.

A copy of what the add-in read is saved inside the file as `report.json`; its `probe` record holds the tries
for the sketches, and its `health` record says whether the design came back to its start.

The add-in notes the state of every timeline step (fine, warning or error, with Fusion's message) before it reads
the design, and checks it again at the end of every export, also a failed or cancelled one. When a step differs, it
turns back on any step it turned off and rebuilds the whole design once; when a step is still worse, it sets your
values once more and rebuilds again. A step that still differs after that is named in the result window (and in a
message box when the export stopped), with the advice to use Undo, and `report.json` keeps it under
`health.steps_changed`.

## When a step cannot be copied

Some steps cannot be copied yet: a spiral or tapered coil, a sweep that twists and tapers, a pipe with a square or triangle section, an extrude with a taper on a face, and others (`docs/limits.md` says
which). What the add-in does then depends on the step.

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
too (a mirror of the whole body mirrors the part with the step missing instead), and so is a Combine whose tool body cannot be copied or misses a step other than a round, chamfer, draft or emboss (the Combine is one missing step; the rest of the part is
copied). An extrude that joins only material a left out step made (a rib on a floor that a left out Combine made)
would float apart from the copy, and Paramability could not build the copy at all; so it is left out too, with "It
sits on a step that was left out". The add-in checks this against its own model of the copied part and keeps the
extrude whenever it cannot tell. The result window lists every step left out with its reason. In `report.json` each
of them has the verdict `leftOut`.

A size that only a left out step reads is still offered as a size, marked "may give unexpected results" with a reason
that says so: it changes nothing in the copy until the step is added. Sizes that other steps read too stay plain
sizes.

A part is saved as a fixed shape only in these cases. Your parameters still come along as variables, the message
after the export starts with the first step that stopped the copy, and the lower-right corner of the Fusion window
shows a short line with the same step (Fusion decides how long it stays):

- a step that cannot be copied comes before the first step the copy writes (the copy needs a body to add to), or the
  body starts in a way that cannot be copied;
- more than 256 steps would be left out of one part;
- the place of the part in the assembly cannot be used, or a step of another component or an assembly step changes
  the part;
- the body cannot be followed through the timeline, or a step cannot be read from Fusion;
- a step that Fusion shows as an error;
- a step that splits the part or makes another body. A Split Body by a plane, a flat face or a solid body is copied
  when the part comes out of it as one piece and no later step changes another piece together with it: the copy
  follows the body it was split from and removes the other side, also for a tool body that a Combine takes. A split
  along a construction plane offset by a size follows that size. A split along a curved surface still stops the copy;
- a recipe that is too large to open, or a list of left out steps that cannot be written;
- an error in the add-in while it copies a step. The message then says "This step could not be copied because of an
  error in the add-in. Please report it." This is a bug in the add-in, not a problem in your design.

## The export trail, for a bug report

While an export runs, the add-in writes a short line for each thing it does in Fusion to the file
`export-trail.log`. The file is in the folder `ParamabilityExport` in the temporary folder of your computer. On
Windows, type `%TEMP%\ParamabilityExport` in the address bar of File Explorer. On a Mac, the temporary folder is
the one that the command `echo $TMPDIR` in Terminal shows.

The file holds only the last export. When you pick a body in the dialog, the read of its steps starts a new file
too. Each line goes to the disk at once. Thus, if Fusion closes suddenly during an export, the last lines show the last thing the add-in did,
and the file also holds the place in the add-in where Python stopped.

If an export stops with an error, or Fusion closes during an export, send this file with your bug report, together
with the `report.json` from the saved file when there is one. The file holds the names of your timeline steps and the
values of the parameters that the tries set. It does not hold the shape of your design.

Every plain part or recipe the add-in writes (also the one size case of Export size choices) also lists the design's
user parameters (up to 64, in Fusion order) with their current values, units and comments. A parameter worked out by a formula keeps
its formula when it can be copied, so Paramability gets the variables even when the shape stays fixed. This includes
helper parameters that only other formulas read. Parameters in other units than length, angle or no unit (a mass, a
time) are left out. In Export for Paramability, `report.json` says how many were
listed and which were left out and why.

## Export for Orca (experimental)

Saves one body as an OrcaSlicer 2.5 project (`.3mf`). The Design tab of OrcaSlicer rebuilds the part, and your user
parameters become its variables.

1. Click **Export for Orca (experimental)**. It is the third button of the add-in, next to Export for Paramability
   and Export size choices.
2. Pick the body and tick the parameters you want as variables. The parameter table says "In Orca", and a ticked
   row says it becomes a variable in Orca's Design tab. Min and Max are not used.
3. Save the file. Open it in OrcaSlicer 2.5.

This export is experimental. It copies fewer kinds of steps than Export for Paramability. A step it cannot copy is
left out, and the result window says why. The plate always shows the body as it is in Fusion.

A report is saved beside the `.3mf` file, named `<name>.report.json`. It lists the steps that were copied, the steps
that were left out and the reasons. `docs/orca-output.md` gives the full description.

## Several bodies in one file

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
- A size that moves a body saved as a fixed shape is marked "may give unexpected results" for the file, with the
  fixed body named in the reason: the editable bodies follow it and the fixed one does not, so they may no longer fit.
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

## Export size choices

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
