# Paramability export for Fusion

An add-in for Autodesk Fusion. It exports a body from your Fusion design to Paramability. Paramability opens the
body as a part that you can change. The sizes of the part are your Fusion user parameters.

Autodesk and Fusion are trademarks of Autodesk, Inc. Paramability is not affiliated with Autodesk.

## What it does

The add-in adds three buttons to Fusion:

- **Export for Paramability** saves one or more bodies with their modeling steps and your user parameters. In
  Paramability, you change a parameter and the part rebuilds.
- **Export size choices** saves fixed sizes of one body, for example S, M and L. In Paramability, you select a size
  from a list.
- **Export for Orca (experimental)** saves one body as an OrcaSlicer 2.5 project. The Design tab of OrcaSlicer
  rebuilds the part, and your user parameters become its variables (`docs/orca-output.md`). A revolve copies with
  holes in its outline and with several outlines. When the angle of a symmetric revolve follows a parameter, the
  copy makes two turns, one to each side, so the angle follows in OrcaSlicer too. A pattern on a path of one line,
  arc or circle copies too, and its count and distance follow. A pipe with a round section copies as a sweep of
  its circle, solid or hollow, and its diameter and wall follow your parameters. A pattern or mirror of bodies
  whose copies one Combine joins to the part or cuts from it copies too; its spacing and angle follow, and its
  count keeps its number. A hole "To" a face or plane copies to the depth Fusion made, in both exports, and its end
  must lie on that face or plane. A body made by Copy and Paste copies as its source was at the paste, also when
  you move it and join it to the part or cut it from the part; the sizes of the source follow. A coil is left out:
  Orca's sweep along a helix keeps the wire square to its turns, so the ends and the thickness of the wire would not
  be as in Fusion.

Your Fusion licence applies to the files that you export. Personal is for non-commercial use. Education is for
learning only.

## How it works

1. The add-in reads the steps of the body in the Fusion timeline: sketches, extrudes, holes, fillets and more.
2. It changes your parameters for a short time and lets Fusion rebuild. This shows which sketches each parameter
   moves, and how much. Where a step of the body does not rebuild, or shows a new warning, the range of that
   parameter stops before that value. A step that is red in the timeline now is left out of the copy; where it builds
   at a value tried, the range stops before that value too. The add-in finds the step by its place in the timeline, so a step of another
   component with the same name (two components can each have a "Chamfer1") does not hide it. The add-in tries the
   range ends one size at a time, and finds the last value that builds for that size before it goes to the next size.
   A size that also changes steps of another component gets its range ends after the other sizes (your favourites
   still come first), since its tries are the most likely to break the design. Such a size (a width or a wall that a
   box and its lid share) is a normal size of the part when it changes the part only through the part's own steps,
   for example the length of an extrude, and the sketches drawn around the other component stay where they are in
   its tries.
   When the tries end early, the range stops at the last value that built, and its note says that the values after it
   were not tried. This is also true for a size whose range ends were not tried yet: its range stops at the values
   that built in its first tries. A range end that you typed is kept.
3. It sets all parameters back to their values. Your design does not change. When the check at the end cannot
   confirm this, the add-in asks Fusion to undo the whole export, and the result window says so. This also happens
   for an export that you cancel or that stops, when the add-in cannot confirm that your design came back. A file
   that was saved stays saved (with "Lighter on memory" ticked the add-in cannot undo, and the window says so; when the
   design was saved in the cloud, the window gives the steps to get the design back as it was saved: close it without
   saving and open it again from the Data Panel; the add-in does not close the design itself; when Fusion showed
   unsaved changes before the export, the window says that they are lost too).
   A parameter that no copied step uses
   is reported as "changes nothing" only when the body stayed the same each time the add-in changed it.
   When a change leaves a step in a new warning or error, or a sketch on its other solution, also with the values
   back, the add-in tries to bring the design back: it sets the sizes of the recent changes a little past their
   values from the other side and back, one change or one size at a time. If it cannot, it stops the changes there and
   tells you which step. When only steps of another component stay changed and the part is as before, it stops only the
   changes of the sizes behind it and tries the other sizes in full. Your design is changed then, so the add-in asks
   Fusion to undo the export at its end. At the end it compares the sketches and the volume and size of the body with
   the start, and tells you when they differ. A very small difference with nothing else changed counts as "not
   confirmed", not as a change.
4. It writes the steps and the parameters to a `.paramability` file. The file also holds a STEP file of the body as
   Fusion made it.
5. Paramability builds the part from the steps and compares it with the STEP shape.

The add-in cannot copy all Fusion steps. If it cannot copy a step, it leaves the step out and tells you why.
For some steps the add-in measures the shape that Fusion made, for example the radius of a round set by chord
length, or of a round whose radius changes along its edge. It copies such a step only when the measure agrees.
A shell that grows outward or has rounded corners is copied only when the volume of the part changed as the shell says.
A thin extrude of an open line (a fence or a divider) is copied only when the faces that Fusion made show on which
side of the line the wall stands. Export for Orca copies a thin wall along one rectangle, one circle or one line of
straight lines; the side of the wall comes from what Fusion measured, as for the other export.
Fusion does not record which way some steps go, for example a join whose end merges into the part. The add-in then
tells the way from where the body grew. When that does not show it, the add-in leaves the step out.
For example, a Pattern on Path is copied only when its path is one straight line, one arc or one circle, and a
Scale of a body is copied only when the body measured after it has the size and volume that its factors give. A Press
Pull on the wall of a hole or of a pin (to tune a fit) is copied only when the new radius that Fusion made agrees.
Export for Orca copies such a Press Pull of one round face as a ring that it adds to the part or cuts from it, and
the distance follows its parameter.
A Pipe with a round section is copied as a sweep of a circle. A pipe with a square or triangle section is left out.
The add-in checks where Fusion says each copy of a pattern is against the faces of that copy, and leaves the
pattern out when the two do not agree.
A join "through all" is copied only when it joins this body alone and Fusion ended it on the far side of this body.
The add-in marks the sizes that change the body before it "may give unexpected results" (`docs/limits.md`).
A revolve turns toward one side of its sketch in Fusion. When a parameter moves its axis past the outline, the
range of that parameter stops before the outline reaches the axis.
A shell, round or chamfer on the faces or edges of a revolve follows the sizes of the revolve, for example the open
top and the rounded outer rim of a cup. A round or chamfer inside a shelled cup (its inner rim, its inner bottom edge)
follows the sizes and the thickness of the shell, and one on a flat end face of a part turn follows the outline.
Outlines that share a line and are revolved together (a lid and its rim) count as one outline, so a round or chamfer
where they meet follows the sizes too. Where the add-in cannot be sure (the end face turns with a size, the outlines
overlap, a size moves one outline so that they meet in another way), the sizes are marked.
Some places stay where they are in the copy, for example an axis or a plane that a step turns about or mirrors
across. The add-in marks each size that may move such a place "may give unexpected results". When it cannot tell
what a place is, it marks every size that the steps before it use (`docs/limits.md`).
The same holds when Fusion picked the edges of a round or chamfer from faces or chains of edges and the copy has to
pick the edges one by one: at other sizes those faces or chains may hold other edges.
One fillet or chamfer can hold several sets of edges, each picked in its own way and with its own size. When the sets
lie apart from each other, the copy makes one step for each way of picking, one after the other. Then each set keeps
the pick that Fusion used. When one set cannot be copied, only that set is left out, and the copy keeps the others.
The sizes used before such a step are still marked, since the add-in cannot see whether they move the sets nearer.
A set that Fusion cannot list (a face picked with Tangent Chain on, where no other face meets it smoothly) leaves its
whole step out, with a tip. A step that cannot be read from Fusion is left out when the part changed around it, so
the rest of the part is still copied.
Paramability then shows the original shape and a list of the missing steps.

## Install

1. Get the add-in: clone this repository, or download the release zip and unzip it.
2. In Fusion, click the **Utilities** tab, then **Scripts and Add-Ins**.
3. In the dialog, click the plus icon near the top of the list. Select **Script or add-in from device**.
4. Select the `ParamabilityExport` folder. Select the folder itself, not a file in it.
5. Find the add-in in the list and click **Run**. To load it each time Fusion starts, turn on **Run on Startup**.

The three buttons are in the **Utilities** tab, in the **Paramability** panel.

## Use

### Export for Paramability

1. Optional: in Fusion, mark the user parameters that you want to change in Paramability as favourites.
2. Click **Export for Paramability**.
3. Select the body. (*Upon initial selection there's a timeline rewind which can take its time.*) To put more bodies in one file, select up to 32 bodies.
4. Look at the parameter table. The add-in ticks the parameters that the body uses. Tick or untick parameters as
   necessary. Each ticked parameter becomes a size in Paramability. You can type a Min and a Max for it.
5. If a warning shows below the body picker, read it. It tells you which steps the copy cannot use and how to change
   them in Fusion.
6. Select the up direction of the design. Click **OK**.
7. Select where to save the file.
8. Read the result window. It shows which parameters are sizes and which steps the copy left out.
9. Open the file in Paramability.

### Export size choices

1. Click **Export size choices** and select the body.
2. Below "Parameters that change between sizes", tick the parameters that change from size to size.
3. In the Sizes table, add one row for each size. Type a name and a value for each parameter.
4. Type a name for the list of sizes ("Name of the dropdown in Paramability").
5. Select the default size and the up direction of the design.
6. Click **OK** and select where to save the file.
7. Open the file in Paramability.

After each export, the add-in sets your parameters back to their values. This also occurs if you cancel the export
or if an error occurs.

### When something goes wrong

Each export writes a short trail of what it does in Fusion to the file `export-trail.log`, in the folder
`ParamabilityExport` of your temporary folder (`%TEMP%\ParamabilityExport` on Windows). The file is kept when
Fusion closes suddenly. Send it with your bug report (`docs/user-guide.md`, "The export trail, for a bug report").

## Main limits

- The design must have history (a parametric design).
- The add-in cannot copy all Fusion steps. `docs/limits.md` gives the full list.
- Paramability opens up to 256 MB for each size and 1 GB for each file.
- This is version 0.14.5. It needs Paramability 1.7.0 or newer to open its files.

## More information

| Document | Contents |
| --- | --- |
| `docs/user-guide.md` | All dialogs, the result window, several bodies, steps that the copy leaves out |
| `docs/orca-output.md` | Export for Orca: what it copies, what it leaves out, the report |
| `docs/limits.md` | What the copy can and cannot do, step by step |
| `docs/feature-support.md` | Which Fusion actions each export copies, and what could be copied later |
| `docs/development.md` | Code layout and tests |
| `docs/developer-guide.md` | How an export works step by step, the code map, worked examples, how to debug with `report.json` |
| `docs/capture-format.md`, `docs/expressions.md`, `docs/recipe-gaps.md` | File formats and how formulas are copied |
| `docs/adding-a-step-type.md` | How to copy one more kind of Fusion step |
| `docs/hand-checks.md`, `docs/hand-tests.md`, `docs/test-projects.md` | Checks by hand in Fusion |
| `docs/publishing.md`, `docs/create-remote.md` | Rules for sharing the add-in, releases |

## Licence

This add-in is free software under the GNU General Public License, version 3 (`LICENSE.txt`). You can share and
change it under the terms of that licence. It comes with no warranty: it is provided "as is". The licence covers this
add-in only, not the Paramability app. It applies to every version of the add-in, including the commits made before
`LICENSE.txt` held the licence text.
