# User guide

This guide gives the full description of the three exports. It tells about the dialogs, what the export does, steps
that cannot be copied, several bodies in one file and the result window. The README has the short version
("How it works" and "Use").

## Export for Paramability

This export saves one body with its modeling steps, and your user parameters as sizes. Paramability opens the file
as an editable part. You do not type anything in Fusion.

### The dialog, step by step

1. Optional: in Fusion, mark as favourites the user parameters that you want to change in Paramability.
2. Click Export for Paramability and pick the body. To save several bodies in one file, see "Several bodies in one
   file".
3. Look at the parameter table. Each row is one user parameter: a tick, its name, its value now, and what it becomes
   in Paramability.
   - The parameters that the picked body uses are ticked to start with, your favourites first.
   - When you pick another body, the ticks follow that body.
   - "Tick what the body uses" and "Untick all" set the ticks again in one click.
   - A ticked row has a Min and a Max. They start from the comment rule (see "Size ranges" below).
   - You can type your own Min and Max: in the length unit of your design, in degrees, or whole numbers for a count.
     A typed unit such as `2 in` is read too.
   - The current value must be between Min and Max.
   - An unticked row says "stays 3 mm".
   - A parameter worked out by a formula says "formula". It follows the parameters that it reads.
   - A plain parameter that the body reads only through formulas is ticked too. Its row names the formula.
   - A parameter can change another component that the body is drawn around. An example is the diameter of a pipe,
     when a hole in the body follows the outline of the pipe. Such a parameter is ticked too, and its row says so.
   - A parameter that drives a joint is not ticked to start with, because the part does not follow it in the
     assembly. You can still tick it. Its row then says "size, may be unexpected".
   - Click a row to read its comment, its formula or the full reason in the box under the table.
   - You can tick up to 64 sizes.
4. Read the warning under the body picker, if one shows. It shows as soon as you pick the body.
   - When a step stops the copy altogether (see "When a step cannot be copied"), the warning names that step, for
     example "Extrude9 (extrude)".
   - It gives a "Tip" with what to change in Fusion, when there is one.
   - It says that the part will be saved as a fixed shape. Your parameters still come along as variables.
   - Hover the warning for the full reason.
   - "Show in timeline" selects that step in Fusion. The timeline marker does not move.
   - "Likely left out of the copy" lists the steps that the copy will only leave out. It shows the first three, each
     with its reason and Tip, then "and N more". The words are the same as in the result window after the export.
   - "More may show after the export" tells you that the list can grow. Some steps can only be checked during the
     export, for example a round on faces of a left out step.
   - "Copied with a note" lists steps that were copied with a remark.
   - Fix those steps first, or export anyway.
   - The list comes from the steps that the dialog already read for the body. The dialog does not read the design
     again and does not try sizes for it. The Text Commands window shows how long the list took.
5. Pick the design up direction and click OK. Choose where to save the file.
   - The file name offered is the name of the component that holds the body.
   - For a body that is not in a component, the file name offered is the name of the design.
6. Read the result window (see "The result window" below).
7. Open the file in Paramability. The sizes land on the form as variables, ready to configure.

The last line of the dialog shows the version of the add-in that runs ("Add-in version 0.14.6"). When you load
several copies of the add-in, check that line before you export.

### The result window

After the export, a window shows short sections. Each section is a group with its title.

- Sections with nothing to say are left out.
- The first sections are open: `Reopen the design` (when it applies), `Check your design` (when something is wrong)
  and `Result`.
- The other sections (`Sizes`, `Left out`, `More sizes`) are folded. Click a title to open it.
- A long list scrolls inside its box.
- When Fusion is slow to start the window, it opens a few seconds after the export ends. The status area says so
  while you wait.

The sections are these:

- `# Result`: the file, and what to do next. It says whether the file is an editable copy (or one with steps left
  out), and how many parameters come along as variables. A file with several bodies has one line per body.
- `# Sizes`: one line per size, with its range.
  - When it applies, the line then says "may be unexpected" (and from where), "kept fixed", "not followed" or "not
    used". The short reason follows in brackets.
  - Sizes that follow come first, then the marked ones, then the fixed ones.
  - A formula parameter that stayed a plain number is listed last as "kept as a number: name = formula (reason)".
- `# Left out`: each step that the copy left out, with the reason.
- `# More sizes`: parameters that you did not tick but that also change the part, or that could not be tried. Tick
  them and export again to get them as sizes.
- `# Check your design`: this section shows only when something is wrong.
  - It names a parameter that did not go back.
  - It names sketches that did not come back to their first shape, or came back on another outline.
  - It names a part whose volume or size is not as before.
  - It names timeline steps with a new warning or error, and sketches that could not be measured.
  - A try can leave a step changed that the add-in could not bring back. The section then says that the tries
    stopped early, after which try, and which step.
  - When that step belongs to another component and the part was not changed, only the tries of the sizes behind it
    end. The window names these sizes, the steps and their component. The other sizes are tried on.
  - The add-in then asks Fusion to undo the export.
  - With "Lighter on memory" ticked, all tries stop there instead, once Fusion forgot Undo data.
  - Use Undo in Fusion when this section says that your design is changed.
- `# Reopen the design`: this section shows first. It shows only when the export could not be undone ("Lighter on
  memory" was ticked) and your design was saved in the cloud.
  - It gives three steps to get the design back as it was saved. It names the project, the file name and the version
    to open (see "Get the design back as it was saved" below).
  - The add-in does not close or open the design. You do it.
  - Fusion can show unsaved changes when you open the export dialog. Then a line before the steps says that closing
    without saving loses every change since the last save.
  - Fusion counts the add-in's own marker moves as unsaved changes too: those of an earlier export, or of opening the
    export dialog. So the add-in cannot tell them from your own changes. Follow the steps only when you have no
    changes of your own to keep.

If this window cannot open, a message box shows a short summary. The summary gives the file name, how many sizes,
how many steps were left out, and what to check in your design. Fuller detail for debugging is in `report.json`.

## What the export does

The export reads the steps of the body, tries the sizes that move a sketch, and writes the file. Every parameter goes
back to its value at the end, whatever happens.

### Your parameters go back

While the export works, it sets parameters to other values for a short time.

- It does this only to let Fusion rebuild and to measure the sketches.
- No STEP file is made for these tries.
- Every parameter is put back, whatever happens.
- Reading the steps can move the timeline marker. The add-in puts the marker back.

### Which parameters become sizes

Every ticked parameter that a copied step reads becomes a free size. It gets its current value and the range from the
table.

- You set the final Min and Max in Paramability.
- The file has no size checks.
- A size becomes a fixed number only when it would make the recipe invalid, for example a formula too long to write.
- A ticked parameter that no copied step reads is not a size. It still comes along as a variable.

For developers: the `checks` list of the file is empty.

### Sketches drawn around another component

A sketch can follow another component without a parameter of the body. An example is a hole drawn around a pipe, with
its circle projected from the pipe or constrained to it.

- The add-in reads which components and bodies each sketch is tied to in this way.
- For each user parameter, the add-in follows where the parameter acts. A sketch dimension acts on its sketch and on
  the steps that use that sketch. Those steps shape bodies of their component.
- A parameter that shapes the pipe body (the body that the hole is drawn around) is ticked to start with. The add-in
  tries it like a size behind a sketch dimension.

The tries of such a parameter give one of these results:

- The sketch moves with the parameter and the tries can follow it. The parameter is a free size, and the outline
  follows it.
- The outline changes in a way the tries cannot follow. The parameter is "not followed", with the reason.
- Nothing in the part moves with the parameter. It is "not used", with the reason that it was tried and changes nothing
  in this part. The export says this only when the part itself stayed the same at each try of that parameter.
- The part changed, but no copied step follows the parameter. It is "not followed", with the reason that it changes
  this part in a way the copy does not follow. The copy keeps its value now.

A parameter can also be used in the part's own steps. An example is a wall thickness that is the length of an
extrude, and also the shell of the box that the lid is drawn around. Such a parameter is a normal size, and it is not
marked, when all of these are true:

- The sketches drawn around the other component stay where they are in its tries. The copy then follows the extrude.
- The tries follow every sketch of the part that is drawn around another component.
- The parameter moves no construction plane, axis or joint.

A parameter of a joint, or of a move that places a component, can move the pipe against the part. So it counts for
every such sketch too.

Up to 8 more ticked parameters that nothing seems to tie to the part are tried too, after the others, since you know
your design.

### Steps that use a place of another component

A step can use a plane, axis or point of another component directly. The copy follows that place as a formula of the
sizes, when the tries can measure how it moves.

- Examples of such places: a mirror plane, a pattern axis, a face that an extrude reaches to, a hole point.
- The export reads where the place is at every size it tries. It fits how far the place moves: a plane along its
  normal, an axis or point in space.
- A parameter that acts on the component that owns such a place is ticked to start with. It is tried like a
  parameter behind a sketch.
- These places then move with the parameter, and the parameter stays a free size: a mirror plane, a pattern or
  revolve axis, the face or plane that an extrude reaches to or starts from, and the point or flat face that a hole
  sits on.
- A parameter that acts on that component but does not move the place is not marked.
- A place can turn with a parameter, or move in a way the tries cannot follow. That parameter is then marked "may give
  unexpected results", with the step and the other component named.
- A place that the tries could not measure marks the parameter in the same way.

A parameter of a joint, or of a move that places a component, can move every other component.

- The dialog offers such a parameter as one that may move that component in the assembly.
- A joint parameter is not ticked to start with.
- The export tries such a parameter like a parameter behind a sketch.
- If the tries did not measure it, it is marked "may give unexpected results" for each such place. It is never marked
  "nothing in this part moved with it".

For developers: `report.json` keeps the result in `probe.motion.refs`.

### Planes and axes built on another component

A plane or axis of the part's own component can be built on another component. An example is a plane offset from the
XY plane of the main design while the part sits in an assembly.

- That plane belongs to the part, so the steps that use it are copied.
- The export cannot tell which parameters move what the plane is built on.
- When an extrude goes up to such a plane, or a sketch sits on it, the export tries it with every ticked parameter. A
  parameter that the tries could not measure is marked "may give unexpected results".
- A mirror plane or a pattern axis built in this way marks every ticked parameter.

### Extra tries of unticked parameters

When a sketch of the part is tied to another component, or a step uses a place of one, the export does more tries.
It tries up to 12 unticked parameters that act on other components, once each, in the rows left under the cap.

- These tries only look. They do not make sizes.
- A parameter that moves the part is named in the result window ("These parameters also change this part"). Tick it
  and export again to get it as a size.
- These tries are compared with the design as it reads just before them. So a sketch that Fusion left on its other
  solution after the earlier tries does not count as a change.
- A try that does not rebuild is listed as not tried.

### Sizes that may give unexpected results

Some sizes the add-in cannot follow fully. Such a size stays a free size, but it is marked "may give unexpected
results". These are the loose sizes.

A size is loose when it may move one of these in a way the copy cannot follow:

- a sketch, in a way the tries could not follow;
- a plane or axis;
- a joint;
- a pick (an edge of a round or chamfer) that may move with the size;
- a pick on a pattern copy whose count would have to change;
- a step drawn on another component's sketch, which could stop meeting the part.

What you see for a loose size:

- The reason starts with the Fusion name of the parameter.
- Where the add-in can tell, the reason gives the value past which the problem starts.
- Paramability shows a warning mark next to the size.
- The parts of the shape that cannot follow the size keep their numbers. So the part looks the same at the current
  values.
- The result window lists these loose sizes.

### How the sketch tries work

A size can move a sketch: a rectangle width, a hole position, or a plane that a sketch sits on. The add-in then tries
other values of the size and reads the sketch each time. From these readings it writes the sketch value as a formula.

- For each try, the add-in sets the size to other values and lets Fusion rebuild.
- The values of one try go in as one change, so Fusion rebuilds once per try. This is the same as when you edit the
  parameters yourself. (Export size choices also recomputes the whole design before it saves each size.)
- The formula uses your parameters, such as `0.5 * FilterBox_width_mm`. So the sketch follows the size in
  Paramability.
- The add-in first tries each such size a quarter below and a quarter above its value, inside its range.
- Then, while tries are left, it tries the ends of the range.
- A size that only feeds step values needs no try: an extrude distance, a fillet radius, a pattern count. Its formula
  is exact.
- The progress window tells you what happens and shows the try, for example "Try 5 of 31: HolderWidth at 32 mm".
  Cancel works there too.

To save time, Fusion rebuilds the timeline only up to the last step that the part needs while the tries run.

- The marker moves to that step, and goes back when the tries end.
- Steps of other components after that point are not rebuilt.
- This is also true when a sketch of the part is tied to another component, because a step only uses what comes
  before it in the timeline.

For developers: `report.json` says how many items each try rebuilt (`probe.timeline`).

### Points that move along a curve

A point can move along a curve. Examples are the end of a leg that turns with an angle, or a corner set back by a
wall along half the angle. The add-in then looks for a formula with the sine, cosine, tangent or cotangent of the
angle.

- The formula can use the angle or half of it, alone or times a length, and products of two lengths.
- A corner on a turned leg often needs two to four products of a length and the sine or cosine. The add-in tries these
  all at once. It also tries them with a length that moves the point only once the angle has turned.
- A formula is used only when the tries check it: every try must follow from the others.
- To have enough tries, the add-in sets each such size half way to its ends, and together with each other size of
  the same sketch. This is about 2 tries per curved size, plus 2 per other size that it shares a sketch with, inside
  the 64 tries.

When no such formula fits:

- Only that size is marked. The other sizes of the sketch still follow, and two more tries check them together.
- A size that the readings still cannot follow is loose.
- In the step with the point that cannot follow, the formulas with sines or products leave that size out. So the
  outline keeps its shape. Every other step still follows the size.

Some outlines would cross themselves only in a corner of the size ranges, for example a turned leg shorter than
another. The ranges are then cut there instead ("the outline of Sketch3 would cross itself, lose a corner or have a
hole reach its edge").

- The same cut applies to any outline whose corners follow sizes. An example is a corner that follows a size while the
  arc it meets is written as its number.
- The same cut applies to a hole that would leave its outline. This is also true for a flat face used as an outline,
  such as the face that an emboss is trimmed to.
- A round or chamfer that picks an end face of such an outline follows the outline corner nearest to its pick point.
  So its formula stays short.
- A line whose direction turns while both its ends follow leaves out nothing.

### Sketch changes that cannot be copied

Some sketch changes cannot be copied even with the tries. A size that causes one of them is loose, as above.

- a point that moves along a curve that no such formula follows;
- an outline that changes shape, for example a line that only crosses the outline above some width, or a sketch
  pattern whose count follows a size;
- a sketch plane that turns;
- a sketch that a step uses in another way, for example as a pattern direction or a path;
- a construction plane or axis that a step reaches to directly;
- a size that would shrink an outline to nothing.

### When a try does not build: range cuts

A try that Fusion cannot build is dropped, and no size is fixed for it. Instead, the range of the size stops at the
last value that built.

- A try also counts as failed when Fusion builds the part but a step of the part shows a new warning. Fusion may have
  built another shape there.
- After a failed try, the add-in tries that size nearer to its value now: half way, then a quarter, then a tenth of the
  way to the end of its range. It makes at most 24 such tries per export.
- When a nearer try builds, the size follows between the values that built.
- Where one value built and a farther one did not, the add-in also tries the values between them. It halves the gap up
  to four times, so it finds the last value that builds closely.
- A value past one that did not build is not tried at all, since the range stops before it anyway.
- On a side where Fusion did not rebuild, the range on the form stops at the last value that built. This does not
  apply when you typed that end in the dialog, or when the failing step belongs to another component than the part.
- On a side that the tries did not reach, the size says "it was followed between A and B".
- Steps in different components can have the same name. For example, two components can each have a "Chamfer1". The
  add-in tells them apart by their place in the timeline. So a failing step of the part still stops the range.
- A size that did not rebuild at any value tried is not a size. The reason names the values and the step where Fusion
  stopped.

How a cut range shows:

- Each cut range has one line in the result window: "range cut", with the value and the step where Fusion did not
  rebuild or showed a warning.
- The file keeps the same reason. Paramability shows it as a quiet note next to the size, not as a warning.
- In a file with several bodies, a size that more than one body reads gets the narrowest cut over the bodies that were
  probed. Its reason says so.

For developers: the reason is in `report.json` (`sizes.cut`) and in the file's `cuts` list.

### When the tries stop early

A try can leave the design broken: a step stays in error even with your values back. The tries then stop there,
because every later try would fail for that reason. The result window says so.

- When the broken step belongs to another component that the part does not need, and the part reads as before, only
  the tries of the sizes behind that step end. The other sizes are tried in full.
- A size that also changes steps of another component gets its range ends tried after the other sizes. Its tries are
  the most likely to break the design. Your favourite sizes still come first.

The tries can stop early like this, or run out of time, before the values between the last value that built and the
first one that did not were tried.

- The range then still stops at the last value that built.
- Its reason adds "no value between was tried", and why.
- It also adds a tip: untick the size that stopped the tries, or raise the time limit.
- The design may build at some of those values. A later export that tries them can give a longer range.

The tries can also end before the range ends of a size were tried at all.

- Its range then stops at the values that built in its first tries.
- Its reason says "no value below A or past B was tried", why, and the same tip.

An end that you typed keeps its value.

### Ranges of tapers and formula lengths

Some steps get the same kind of range cut without a failed try. The range stops where the step would stop making
sense.

- A taper that follows sizes: the range stops before the taper reaches 45 degrees, the steepest taper that
  Paramability builds.
- A tapered cut through all, whose walls would meet before the cut passes the part at some sizes: the add-in checks it
  over the ranges of the sizes behind its taper and its outline. Those ranges stop where the cut would close.
- A length or a count that is a formula of sizes, for example a join of `Tall - Low`: the ranges stop where the length
  would reach zero or the count would go under 1. The formula stays.

### Size ranges

Each size has a range, and you can type it in the table. It starts from a comment such as `Wall [1..6]` on the
parameter.

- Without such a comment, the range goes from half to double the current value.
- A count goes from 1 to twice its value.
- A parameter that sets how many copies a pattern makes is a whole number.
- A parameter that the pattern count reads only inside `round`, `floor` or `ceil` keeps its decimals.
- A parameter that the pattern count reads only in a test, such as `if(N > 2; 3; 5)`, keeps its decimals too.

### Size labels

A size is labelled in plain words.

- A short comment on the parameter is the label. The label is its first sentence, without a `[min..max]` hint.
- A longer comment is a description. The label is then the parameter name in words, with the unit word dropped. For
  example, `BaseCup_midExtrude_offset__mm` reads "Base cup mid extrude offset".
- Two sizes never share a label.
- The Fusion name stays the size name. So the form can show the name in a tip and the comment as the description.

For developers: the labels come from `lib/params/labels.py`. The package `parameters` list keeps the label as `label`,
next to the full comment.

### "Faster tries"

The box "Faster tries" under the body picker is on to start with. The tries then also turn off the timeline steps of
other components that the body does not use, so each try rebuilds less.

- Every step is turned back on when the tries end, also on cancel or an error.
- Steps that you had turned off yourself stay off.
- Before the tries, the add-in checks that the body reads the same with those steps off. If not, it turns nothing
  off.
- When the add-in is not sure which steps the body uses, for example when the design has joints, it turns nothing
  off.
- The discovery tries, which check whether a parameter of another component also changes the body, run with every
  step back on.
- Untick the box to keep every step on.

For developers: `report.json` says what happened and how long the tries took (`probe.timeline.suppressed`,
`try_seconds`).

### "Stop the size tries after"

The list "Stop the size tries after", in the same place, sets a time limit for the tries. The limit is 10 minutes to
start with. You can pick anything from 1 minute to 2 hours, or no limit.

- Small designs finish their tries in seconds. A big design can spend most of the export there.
- The progress window shows the time spent and about how long the tries still take.

When the limit is reached:

- The tries stop at the next try.
- Every value and step goes back exactly as after any end of the tries.
- The export goes on with what was measured.
- Sizes that move a sketch and were not tried in time are marked "may give unexpected results". When only a sketch
  reads them, they are "not a size".
- The reason says that the tries ran out of time. A tip says: pick a longer time, or untick sizes that do not need to
  change.
- The result window says that the tries stopped and how many sizes were left out.

The order of the tries makes the limit cut the sizes least likely to matter first.

- The tries start with the sizes that you marked as favourites in Fusion, then the others.
- The extra tries come after the near tries of every size. These are the far ends of the ranges, the sizes together,
  and the checks of other components.
- The far ends are tried one size after the other. Each size gets its tries for the last value that builds before
  the next size starts. So a later try that stops the tries does not cut the range of a size tried before it.
- A size whose near tries changed a step of another component gets its far ends last.

For developers: `report.json` keeps the limit, whether it was reached and the sizes left out (`probe.time_limit`,
`timing.probe.time_limit`).

### Flat faces used as an outline

Some steps use a flat face as their outline (see `agent-docs/limits.md`). A try that reads such a face leaves the
timeline marker before that step until the values are put back.

- So Fusion rebuilds the steps after it once per try instead of twice.
- The marker is always back where the tries hold it before the next read, and when the tries end.

### "Lighter on memory"

The box "Lighter on memory" is off to start with. It is an experiment. It keeps Fusion smaller during a long export,
but Undo may not step back through the export afterwards.

- A long export can make Fusion grow to many GB, because Fusion keeps Undo data for every try until the export ends.
- When you tick the box, the add-in asks Fusion to forget the tries as they run. It does this each time that all
  values are back where they were.
- The add-in puts every value back itself, so nothing should be lost.
- Save your design before you export. The dialog reminds you once the box is ticked.
- The Undo data of the last part of the export is dropped only when the check at the end confirms that the design is
  as it was. This means: every value back, no sketch moved, no step worse or left turned off, and every check could be
  made. On any doubt, the Undo data is kept.
- A step can still look changed after Undo data was dropped. The result window and the message box then do not send
  you to Undo. They tell you to close the design without saving and open the version you saved.
- When the design had no unsaved changes before the export, the result window gives the steps for this (see "Get the
  design back as it was saved").
- If your Fusion does not have the call or refuses it, the export runs as with the box off.

For developers: the call is Fusion's preview call `Command.beginStep`. `report.json` says what happened in
`timing.undo` (`on`, `applied`, `steps`) and `health.undo_dropped`.

### What the file keeps

The file keeps a copy of what the add-in read, as `report.json`.

- Its `probe` record holds the tries for the sketches.
- Its `health` record says whether the design came back to its start.

Every plain part or recipe that the add-in writes also lists the design's user parameters. This is also true for the
one size case of Export size choices. So Paramability gets the variables even when the shape stays fixed.

- The list holds up to 64 parameters, in Fusion order, with their current values, units and comments.
- A parameter worked out by a formula keeps its formula when the formula can be copied.
- This includes helper parameters that only other formulas read.
- Parameters in other units than length, angle or no unit (for example a mass or a time) are left out.
- In Export for Paramability, `report.json` says how many parameters were listed, which were left out and why.

## How the add-in puts the design back

At the end of every export, the add-in checks that the design is as before. When it cannot confirm this, it asks
Fusion to undo the whole export.

### The check at the end

Before the add-in reads the design, it notes the state of every timeline step: fine, warning or error, with Fusion's
message. It checks the states again at the end of every export, also a failed or cancelled one.

- When a step differs, the add-in turns back on any step that it turned off, and rebuilds the whole design once.
- When a step is still worse, it sets your values once more and rebuilds again.
- A step that still differs after that is named in the result window, with the advice to use Undo. When the export
  stopped, a message box names it.

The check at the end also measures the part itself: its volume, its size and place, the number of its pieces and the
other bodies of its component.

- A clear difference means that your design is changed.
- A very small difference with nothing else changed means that the add-in could not confirm the design is back.
- A difference that appears only after the add-in rebuilt the whole design at the end means the same.
- In both cases the export is undone.

For developers: `report.json` keeps a step that still differs under `health.steps_changed`.

### When the export is undone

When the check at the end cannot confirm that the design is back as it was, the add-in asks Fusion to undo the whole
export.

- The result window opens first and says that the add-in asked Fusion to do this.
- When the export ends, Fusion shows a message. The design returns to how it was when you clicked OK.
- Then look at the design once.
- The window and the message also say whether the file was saved. A file that was saved stays saved, and its sizes
  need a look.
- The lines about the copy stay in the window (for example tries that stopped early), because the undo does not change
  the file.

An export that stopped or was cancelled:

- It is undone too when the add-in could not confirm that every sketch came back.
- It is undone too when the timeline marker did not go back at the end.
- It is not undone when it put the design back.

With "Lighter on memory" ticked, the add-in never asks Fusion to undo. Fusion can undo only the last part of the
export, and that could make the design worse. The window then says that the export could not be undone. Close the
design without saving and open the version you saved.

### Get the design back as it was saved

When the export could not be undone, the result window gives the steps to get the design back as it was saved. It
does this when the design was saved in the cloud (it has a version in the Data Panel). The window shows these steps
under "Reopen the design", with the project, the file name and the version of your design:

1. In Fusion choose File > Close (or close the design's tab).
2. When Fusion asks to save, click Don't Save.
3. Open the design again from the Data Panel (the window names the project, the file and the version).

You do these steps yourself. The add-in does not close or open the design for you. Fusion does not support that while
a command runs, and Fusion closed suddenly when the add-in tried it.

What you lose:

- When the design had no unsaved changes when you opened the export dialog, the saved version is exactly the design as
  it was before the export. You lose only the changes of the export.
- When Fusion showed unsaved changes, a line before the steps says that closing without saving loses every change
  since the last save.
- These can be your own changes. They can also be the add-in's own marker moves, of an earlier export or of opening
  the export dialog, which Fusion also counts. Decide before you close the design.
- The view and the Undo history of this design are lost.
- A file that the export saved stays saved.

When the export stopped and saved no file, a small window with only these steps opens after the message.

## When a step cannot be copied

Some steps cannot be copied yet. Examples are a spiral or tapered coil, a sweep that twists and tapers, a pipe with a
square or triangle section, and an extrude with a taper on a face. `agent-docs/limits.md` gives the full list. What
the add-in does then depends on the step.

### A step that is left out

Most of the time the add-in leaves the step out. It goes on with the steps after it and writes the copy without the
missing step.

- The file keeps what the add-in knew about that step: its name and type, why it was left out, and where it belongs in
  the list of steps.
- The file also keeps how the step changed the size of the part, and the numbers that Fusion stores for it.
- Paramability opens such a part with the original shape (the STEP shape that Fusion made). It shows an unfinished copy
  of the steps beside it, and lists what is missing.
- You can switch between the original shape and the copy.
- The copy is not the part until the missing steps are added.
- If you connect an AI assistant to Paramability, it can add the missing steps for you. The add-in itself has no AI in
  it.

### A fillet or chamfer with several sets of edges

A fillet or chamfer with several sets of edges (rows in the Fusion dialog) can be copied in part.

- When the sets lie apart from each other and one set cannot be copied, the add-in copies the other sets. It leaves out
  only that set.
- The result window lists the step with "Set 2 of 3 of this step is left out" and the reason.
- In Paramability the missing step holds only that set.
- Sets that meet or come near each other are copied together, or left out together.

### Steps that depend on a left out step

A step that picks edges or faces of a left out step is left out too, since in the copy those faces do not exist. An
example is a round on the edges of a coil.

- The add-in asks Fusion which step made the faces that each later round, chamfer or shell picks. It leaves out only
  the ones that pick faces of a missing step.
- When Fusion does not answer, every later step that picks edges or faces is left out.
- A pattern or mirror of a left out step is left out too. A mirror of the whole body mirrors the part with the step
  missing instead.
- A Combine is left out when its tool body cannot be copied. It is also left out when its tool body misses a step
  other than a round, chamfer, draft or emboss. The Combine is one missing step, and the rest of the part is copied.
- An extrude that joins only material that a left out step made is left out too, with "It sits on a step that was left
  out". An example is a rib on a floor that a left out Combine made. That extrude would float apart from the copy, and
  Paramability could not build the copy at all.
- The add-in checks this against its own model of the copied part. It keeps the extrude whenever it cannot tell.
- The result window lists every step left out, with its reason.

For developers: in `report.json` each of these steps has the verdict `leftOut`.

### A step that Fusion shows in red

A step that Fusion shows in red (an error) is treated by what it did to the part.

- When the part is the same before and after the step, Fusion shows nothing of the step. So the copy leaves it out
  too, with a note, and copies the steps after it.
- When the part changed, the step is left out like any other step that cannot be copied. Fusion then keeps an older
  result of the step, for example a pattern with only some of its copies. The tip is "Fix the step that Fusion shows
  in red, then export again."
- A red step can build at other sizes. Fusion then makes a shape that the copy does not have. So where the add-in
  tried a size and the red step built, the range of that size stops before that value.
- A size that may make the red step build, and that the add-in did not try, stays fixed.

### Sizes that only a left out step reads

A size that only a left out step reads is still offered as a size. It is marked "may give unexpected results", with a
reason that says so: it changes nothing in the copy until the step is added. Sizes that other steps read too stay
plain sizes.

### When the part is saved as a fixed shape

In a few cases the whole part is saved as a fixed shape.

- Your parameters still come along as variables.
- The message after the export starts with the first step that stopped the copy.
- The lower-right corner of the Fusion window shows a short line with the same step. Fusion decides how long it stays.

These are the cases:

- A step that cannot be copied comes before the first step that the copy writes. The copy needs a body to add to.
- The body starts in a way that cannot be copied.
- More than 256 steps would be left out of one part.
- The place of the part in the assembly cannot be used.
- A step of another component, or an assembly step, changes the part.
- The body cannot be followed through the timeline, or a step cannot be read from Fusion.
- A step that Fusion shows as an error, when the add-in could not measure the part just before and just after it.
- A step that splits the part or makes another body. Some splits are copied:
  - A Split Body by a plane, a flat face or a solid body is copied when the part comes out of it as one piece, and no
    later step changes another piece together with it.
  - The copy then follows the body that it was split from and removes the other side. This is also true for a tool
    body that a Combine takes.
  - A split along a construction plane offset by a size follows that size.
  - A split along a curved surface still stops the copy.
- A recipe that is too large to open, or a list of left out steps that cannot be written.
- An error in the add-in while it copies a step. The message then says "This step could not be copied because of an
  error in the add-in. Please report it." This is a bug in the add-in, not a problem in your design.

## The export trail, for a bug report

While an export runs, the add-in writes a short line to the file `export-trail.log` for each thing that it does in
Fusion.

- The file is in the folder `ParamabilityExport` in the temporary folder of your computer.
- On Windows, type `%TEMP%\ParamabilityExport` in the address bar of File Explorer.
- On a Mac, the temporary folder is the one that the command `echo $TMPDIR` in Terminal shows.

What the file holds:

- The file holds only the last export.
- When you pick a body in the dialog, the read of its steps starts a new file too.
- Each line goes to the disk at once. So if Fusion closes suddenly during an export, the last lines show the last
  thing that the add-in did.
- The file then also holds the place in the add-in where Python stopped.

If an export stops with an error, or Fusion closes during an export, send this file with your bug report. Also send
the `report.json` from the saved file, when there is one. The trail holds the names of your timeline steps and the
values of the parameters that the tries set. It does not hold the shape of your design.

## Export for Orca (experimental)

This export saves one body as an OrcaSlicer 2.5 project (`.3mf`). The Design tab of OrcaSlicer rebuilds the part, and
your user parameters become its variables.

1. Click **Export for Orca (experimental)**. It is the third button of the add-in, next to Export for Paramability
   and Export size choices.
2. Pick the body and tick the parameters that you want as variables.
   - The parameter table says "In Orca".
   - A ticked row says that it becomes a variable in Orca's Design tab.
   - Min and Max are not used.
3. Save the file. Open it in OrcaSlicer 2.5.

This export is experimental.

- It copies fewer kinds of steps than Export for Paramability.
- A step that it cannot copy is left out, and the result window says why.
- The plate always shows the body as it is in Fusion.

A report is saved beside the `.3mf` file, named `<name>.report.json`. It lists the steps that were copied, the steps
that were left out and the reasons. `agent-docs/orca-output.md` gives the full description.

## Several bodies in one file

Pick two or more bodies (up to 32) in the body picker of Export for Paramability to save them in one file.
Paramability opens one object per body, each where Fusion shows it, with one set of sizes on the form.

A parameter is one size for every body that reads it. So changing `Wall` rebuilds every body that uses it. One body
gives the file described above, unchanged.

- The table ticks every parameter that any picked body uses.
- The warning under the picker names each body that stops the copy.
- A body that cannot be copied (or whose steps cannot be read) is saved as a fixed shape next to the editable bodies,
  with its own note. The other bodies keep their recipes and sizes.
- A body with left out steps keeps its recipe. It opens with the original shape and an unfinished copy, as for one
  body. The result window lists the left out steps of each part.
- A size that moves a body saved as a fixed shape is marked "may give unexpected results" for the file. The reason
  names the fixed body. The editable bodies follow the size and the fixed one does not, so they may no longer fit.
- The sketches of all bodies are tried together over one set of rows: at most 64 in all, not per body. So the export
  takes about as long as for the body with the most sketches, plus one read per body per row.
- A size left without a row is marked "may give unexpected results".
- A size that must stay a fixed number for one body is fixed for all.
- A size that may give unexpected results in one body is marked for the whole file. Each reason starts with the bodies
  it was found for.
- Places are fixed: each body lands where Fusion shows it now.
- A size that moves a body in the assembly (a joint) is marked, as for one body.
- A component used several times is not expanded: one body is saved once per pick.
- The result window lists the sizes once and has a short line per body.

For developers: the file is a package of kind `parts`. It holds `manifest.json` (`parts`: name, step, optional
recipe, note, loose sizes and cut sizes per part; shared `parameters`, `fixed` and `notes`), `parts/NN/part.step`,
`parts/NN/recipe.json` and one `report.json` with a record per body (its capture, steps, sizes and probe).

## Export size choices

This export saves ready-made sizes of one body as a dropdown. Paramability opens one shape per size.

1. Click Export size choices and pick the body.
2. Under "Parameters that change between sizes", tick the user parameters that differ from size to size.
   - Your favourites are ticked to start with.
   - The group can be collapsed.
   - A parameter worked out by a formula, or in a unit that this export cannot convert, is greyed out. Its tooltip
     says why.
3. Fill in the Sizes table. Each row is one size: a name, then a number for each ticked parameter, in that
   parameter's own unit.
   - The table starts with one row, "Default", at the current values.
   - "Add size" copies the selected row (or the last one) as "Size 2", "Size 3" and so on.
   - "Remove size" deletes the selected row.
   - Ticking or unticking a parameter changes the columns and keeps the numbers that you typed.
   - Problems show in a box under the table.
4. Name the dropdown ("Name of the dropdown in Paramability").
5. Pick the default size and the design up direction.
6. Click OK and choose where to save the file. Then open it in Paramability with Open.

One size saves a plain part. Two or more sizes save a part with a dropdown.

After an export, a cancel or a size that does not build, your parameters are set back to their old values.

## How the STEP file is made

Export for Paramability writes one STEP file of the picked body as it is. It sets parameters only for the sketch
tries. Export size choices sets the parameters for each size, lets Fusion rebuild, writes a STEP file of the picked
body, and moves on. All numbers in the file are in millimetres and degrees.

When the design holds more than the picked body, the add-in copies the picked body into a temporary component. It
exports that component, then deletes it.

- Fusion puts the copy at the timeline marker.
- The add-in deletes only what the copy added, so the steps after the marker stay as they are.

For developers: this route is a choice, not a proven fact. Section 3 of `agent-docs/hand-tests.md` decides it. To ask
the designer to hide or move other bodies instead, set `MULTI_BODY_ROUTE` in
`ParamabilityExport/lib/fusion_reader/step_export.py` to `ROUTE_ASK_DESIGNER`.
