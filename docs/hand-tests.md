# Hand tests

No tool can run Fusion, so these checks are done by hand after each change to the Fusion side. Tick each one and
note the Fusion version and system.

## Check first in this version

In this order. Each id is described in the section named.

- [ ] K10 Hole drawn around another component's pipe: section 9. Export the box, the pipe diameter parameter is
      ticked to start with, and the hole follows it in Paramability.
- [ ] K11 Parameters found by trying: section 9. Untick the pipe diameter and export: the result window says it
      also changes this part.
- [ ] Compact export window: section 7.2, "The export window has no empty gaps", then "Early warning" and "Show in
      timeline".
- [ ] Result window with its warnings: section 7.2, "Click OK: ... the result window", and the export pipeline entry
      under "Fusion calls to watch" ("These parameters could not be set back").
- [ ] E1 to E6, Emboss on a flat face: section 10.
- [ ] T1 to T5, thin walled extrudes of one closed outline: section "Thin extrudes".
- [ ] S1 to S5 and X1 onward, spline outlines and sketch text: section 11.
- [ ] Mirror plane and pattern axis reference reads: "Fusion calls to watch", the entry about `read_reference.py`.
- [ ] `%` with a negative left side: T5.

## 1. Install

- [ ] Follow the README install steps on macOS (and Windows if you have it). Confirm each step matches the current
      Fusion dialog: Utilities tab, Scripts and Add-Ins, plus icon, "Script or add-in from device", Run, "Run on
      Startup". The steps came from Autodesk's help pages, not from a Fusion window. Fix the README if a label differs.
- [ ] The buttons "Export for Paramability" and "Export size choices" show in the Utilities tab, in the panel
      "Paramability", each with an icon. The first is promoted.
- [ ] Stop the add-in in the Add-Ins dialog: both buttons go away and the panel is removed. Run it again: no
      duplicate button.

## 2. Sizes and parameter restore (Export size choices)

Click "Export size choices". Use a design with two favourite user parameters (for example `width` in mm and `angle` in deg).

- [ ] The dialog opens with the group "Parameters that change between sizes" (all user parameters listed, `width` and
      `angle` ticked) and a Sizes table with the header `Name | width (mm) | angle (deg)` and one `Default` row at
      the current values. The line "Each row becomes one size in Paramability's dropdown." shows above the table.
- [ ] Collapse and expand the parameter group with a design that has 30 or more user parameters: it stays usable.
- [ ] Untick `angle`: the column goes and the other numbers stay as typed. Tick it again: the column comes back with
      the number typed before. Tick a unitless count parameter: its column shows a plain number.
- [ ] Select a row and click "Add size": the new row is named "Size 2" and holds the values of the selected row. With
      no row selected, it copies the last row. Click "Remove size": the selected row goes; the last row cannot be removed.
- [ ] Type a duplicate name or an empty name: the status box under the table names the problem at once and OK is off.
- [ ] A parameter in inches or radians shows the number in that unit, and the exported value is the same number.
- [ ] Fallback: if the table or the parameter list cannot be built, or its first change fails, the dialog shows
      "The table could not be shown in this Fusion version, so sizes are typed as text.", a one line help, and one
      text box with every settable parameter in the header and a Default row. Edit it, click OK: the file is written
      as before. Note the failing call in the Fusion text commands log ("sizes table failed") and report it.
- [ ] Add two more rows, set the default size, click OK, pick a place to save. The file is written.
- [ ] After the export, both parameters show their original values in the parameters table.
- [ ] Click Cancel in the progress window part way: nothing is saved and the parameters are back.
- [ ] Add a row whose numbers break the part (a fillet that cannot fit): Fusion shows the row name and the failing
      item, nothing is saved and the parameters are back.
- [ ] A design that already has warnings or errors elsewhere (for example a component with a yellow or red timeline
      item) still gets its sizes built: only a size that breaks a new item stops the export, with that item named in
      the message.
- [ ] Watch these calls: expressions are written as text such as `40 mm`. If your Fusion uses a comma as the decimal
      mark, check that `12.5` rows still set the right number.
- [ ] A user parameter in an unusual unit (for example mm/s) is listed greyed out as "not supported" with the reason
      in its tooltip, and cannot be ticked.
- [ ] A formula parameter (for example `depth = width / 2`) is greyed out with "(formula)" and a tooltip.

## 3. Several bodies in the root

The add-in exports the picked body alone. The choice is the constant `MULTI_BODY_ROUTE` in
`ParamabilityExport/lib/fusion_reader/step_export.py`.

- [ ] A root with three bodies, pick one: each STEP in the file holds only that body.
- [ ] The design timeline has no leftover items after the export (the temporary copy is removed). If the cleanup
      ever leaves an item, the export stops with "The temporary copy of the part left N steps in the timeline" and a
      marker that was at the end is at the end again, after those items.
- [ ] If the copy route adds items to the timeline, fails, or the STEP holds more than the picked body, set
      `MULTI_BODY_ROUTE = ROUTE_ASK_DESIGNER`. The dialog then asks the designer to hide or move the other bodies.
- [ ] A body inside a child component or occurrence can be picked in the viewport, OK turns active, and the STEP
      holds the body where it sits in the assembly (not moved to the component origin).
- [ ] With Export size choices, a body in a component exports as usual. With Export for Paramability it is a recipe
      with sizes (section 8).
- [ ] A body picked after its parameter changed (second row) still lands in the right place (the token lookup keeps
      the occurrence proxy).
- [ ] **Marker rolled back.** A root with three bodies and 10 or more steps. Drag the timeline marker back to the
      middle, with steps after it that change the picked body (a fillet, a hole) and one that adds a body. Open the
      dialog: a line says "Exporting the design as it is at the timeline marker (step n of m)". Click OK: the STEP
      holds the body as Fusion shows it at the marker (without the later fillet and hole). After the export the
      timeline has the same number of items in the same order, every step after the marker is still there, and the
      marker sits at the same step. Watch the timeline during the export: the temporary component appears at the
      marker (not at the end) and is gone afterwards. Repeat with Export size choices and with a cancel part way.
- [ ] **Marker inside a group.** Expand a timeline group and put the marker inside it. Export: the temporary
      component may join the group for a moment; afterwards the group holds the same items as before.

## 4. Y up design

- [ ] The "Design up direction" menu starts on the orientation of the design. If it starts wrong, note it: the
      detection reads the modeling orientation preference, which may not match the open design.
- [ ] A design drawn Y up, exported with "Y up": the part stands upright when opened in Paramability.
- [ ] The same design exported with "Z up" lies on its side, so the menu does what it says.

## 5. Personal use licence

- [ ] On a personal use account, the export runs: parameters change and the STEP files are written.
- [ ] Note any message about editable documents or exports.

## 6. Open in Paramability

- [ ] Open the `.paramability` file with Open: one file, one object per size.
- [ ] A dropdown with the chosen name (default "Size") shows on the Form preview and on `/configure`.
- [ ] Picking a size swaps the body in place.
- [ ] The numbers of the picked size show in the Variables panel.
- [ ] A one size export opens as a plain part.

## 7. Recipe export (Export for Paramability)

Paramability rebuilds the steps, compares them with the Fusion part and lands the file as an editable part with its
sizes. The file itself can also be checked without the app:

- the saved message in Fusion says how many steps were copied and how many sizes are ready, or (for a fixed shape)
  starts with the step that stopped the copy, written as in the dialog warning ("Extrude9 (extrude)");
- in the app repo, `npm run recipe:check -- <file>.paramability` prints `ok` for a recipe package;
- the steps listed in `recipe.json` (a zip entry) match the design, and `report.json` holds the capture;
- after any export of a recipe or a plain part (also one size from Export size choices), the manifest lists the user parameters under `parameters`, with
  value, unit and, for a formula parameter, `expr`; a body in a component and a part the translator cannot copy list
  them too, and `report.json` shows how many were listed and which were left out.

When a design surprises you, send `report.json`: its `capture` becomes a test fixture. The calls and enum names these
tests pin are in the "Capture reader calls to watch" parts below. "Matches" below means the part Paramability
builds agrees with the Fusion part.

- [ ] **Plate**: a sketched rectangle with a pocket, two through holes and an L shaped boss. Saves as a recipe and
      matches. Put two features in a timeline group to check that groups are walked.
- [ ] **Tilted sketch**: a boss on a sketch on an angled construction plane, offset from the origin. Matches.
- [ ] **Turned knob**: a full revolve, a 90 degree revolve cut, a symmetric 120 degree revolve. Matches.
- [ ] **Extrude directions**: a flipped one sided extrude, a two sided extrude, a symmetric extrude with "full
      length" on and off, a 5 degree taper, a cut "through all" one way, a join "to" a parallel face. Matches.
- [ ] **Holes**: a blind hole with a 118 degree tip, the same with a flat drill point, a through counterbore, a
      through countersink, a hole on three sketch points. Matches; the step list shows a revolve for the tipped hole.
- [ ] **Bin**: a box shelled with the top open (2 mm), outer vertical edges filleted, a 3 by 2 pattern of magnet
      holes with one copy suppressed, a circular pattern of slots over 90 degrees, a mirrored boss. Matches; the
      pattern has one copy left out.
- [ ] **Combine**: a separate cylinder body cut from the main body with Combine. Matches.
- [ ] **Marker and document**: after each export the timeline marker is where it was (at the end, or the step it was
      rolled back to), the design is unchanged, and
      Fusion's undo list and "unsaved changes" mark are as before (or, if moving the marker marks the document
      changed, note it). Cancel, and a forced error during the read, leave the marker where it was and the parameters
      as they were.
- [ ] **Fixed shape**: a part with a sweep, and one with a variable radius fillet. Each saves as a fixed shape
      (plain CAD part) and the message after the export names that feature.
- [ ] **Y up**: a design made with the Y up preference, exported with "Y up". The plain part stands upright in
      Paramability, and the positions in `recipe.json` are Z up (a plate drawn on the ground plane has its sketch
      normal along z).
- [ ] **Speed**: a design with about 100 timeline items exports in under a minute.
- [ ] **Size choices**: a two row export in Export size choices still lands as size choices (one shape per size).


### 7.1 Sizes from parameters, the sketch tries and restore

Use a design with one body in the root and three plain user parameters read by its features (for example `wall` in
mm, `corner` in mm, `holes` as a count), one favourite and one formula parameter.

- [ ] **Export.** The hint under the table says the design is changed for a moment to measure the sketches. Export:
      a "Trying" progress window shows when a ticked size moves a sketch, parameters change for a moment and are all back at the end (check the values), and no STEP is made for
      the tries. Every ticked size that a copied step reads is in `recipe.json` with the range of the table and its
      current value. `manifest.json` has `"checks": []` and the package holds no `checks/` folder. `report.json` has
      a `probe` record when a sketch could be followed (its `restore_gap_mm` is about 0). A try that Fusion cannot
      build is listed in `probe.dropped` and no size is fixed for it.
- [ ] **Sketch sizes follow.** Tick a parameter that drives a sketch dimension. Open the file in
      Paramability: changing the size moves the sketch, and the size is not marked "may be unexpected" unless the
      probe could not follow it.
- [ ] **Loose sizes.** Tick a parameter that drives a joint, or a sketch the tries cannot follow. The size stays in
      `recipe.json`, the manifest `loose` list holds it with a reason that starts with the Fusion name, the result
      window has a "May give unexpected results" group and its row says "may be unexpected", and Paramability shows a
      warning mark. A ticked parameter that no copied step reads is not a size: the message names it, and it is in
      the manifest `parameters` list.
- [ ] **Labels.** Open the file in Paramability: each size shows the Fusion parameter name as its label, and
      the Fusion comment as the variable's description (from the manifest `parameters` list), not as the name.

- [ ] The dialog lists the user parameters in a table, the ones the body reads ticked (favourites first), the formula
      one greyed with "formula" in the last column. OK is on once a body is picked.
- [ ] **Doubtful when it opens.** A parameter that drives a joint is unticked as soon as the dialog opens, but it can
      be ticked: its row then says "size, may be unexpected", and the box under the table gives the reason ("may give
      unexpected results: it moves a joint") when the row is clicked. A parameter that drives a sketch dimension is
      not marked: section 9 covers it.
- [ ] **Another body.** In a design with two bodies built from different parameters, pick the other body: the ticks
      and greyed lines change to that body's parameters. A parameter only the other body reads is not ticked. Note
      how long the dialog takes to open and to follow the pick (the add-in reads the steps of the body each time).
- [ ] **Limit.** Tick a 65th size: the box unticks itself and the line under the details box says "You can tick up
      to 64 sizes". Unticking one brings back the count line.
- [ ] **Counts.** A parameter that drives a pattern quantity is a whole number size (the form steps by 1), also when
      its role text does not say "quantity". Set it to 2.5 in the app: the recipe still builds.
- [ ] **Long name.** A user parameter with a name over 64 characters that drives a joint: the export saves, and the
      message names the size that may give unexpected results without stopping.
- [ ] **Not used.** Tick a parameter no step reads: in the result window its row says "not used", and the message
      after the export lists it after "Not used by any copied step, so not sizes:". Tick a parameter a step reads
      that the copy cannot follow (a size left out with a reason): its row says "not followed", and the group "Not
      followed" gives the reason, which starts with the parameter name.
- [ ] With only one body in the design it is picked already. With no user parameters the dialog says so (no table)
      and the export still works.
- [ ] Export, open in Paramability: the part is a recipe, the sizes are the ticked parameters that the steps read, and
      the message after the export says how many sizes are ready.
- [ ] Untick a parameter and export: that name is not a size and its number is plain in `recipe.json`.
- [ ] **Doubtful by a sketch.** Drive a sketch dimension by a ticked parameter through an angle (a point placed by
      an angle on a circle) and also an extrude distance. The export does not stop: the message after it lists that
      parameter with its reason (it moves Sketch1 along a curve), the manifest `loose` list holds it, and it stays a
      size whose extrude follows while the point keeps its place.
- [ ] **Rows start from the saved values.** On a design with a sketch that has two solutions (a lid sketch whose
      outline can flip), run an export with several sizes that move sketches: the probe rows match what the same sizes give
      when set by hand from the saved values, and no row stays on the flipped solution.
      The export takes one more recompute per row (the parameters are put back before each row after the first), so a
      long run is a little slower.
- [ ] **Restore.** With sizes that move sketches the progress window shows "Trying size n of m". After each export, a
      cancel in the "Trying size 2 of 4" window (the message says the export is cancelled), and a forced failure (full disk
      or a read only folder), every parameter shows its old expression, formulas included, the timeline marker is
      where it was and the design has no unsaved change beyond Fusion's own.
- [ ] **Expressions** (the translator writes `+ - * /`, `^` as `pow`, and numbers with units as mm or degrees; the
      value check refuses a formula that does not give Fusion's number, so a wrong reading is written as a number and its sizes may give unexpected results).
      Try `1 in + 5 mm`, `wall + 5` in a mm design and in an inch design, `wall ^ 2` and `-wall ^ 2`. Try `floor(wall)`,
      `round(wall)` and `ceil(wall)` on a length (Fusion may apply them in cm, the app in mm): with `wall = 25 mm`,
      note the value Fusion shows for `floor(wall)`. Helper parameters: a unitless `count`, `step = count * 1 mm`,
      `wall = layers * 0.4` in mm, and a formula reading them: all export with formulas, ticked or not.
- [ ] **Marker rolled back, with sizes.** Put the marker before the last few steps (one of them uses a ticked size)
      and export. The dialog shows the marker line. The recipe holds only the steps before the marker, `report.json`
      has `marker` (position and count) and the capture has only the items before the marker. After the export the
      marker is at the same step, parameters are back and the later steps compute as before when you drag the marker
      to the end.
- [ ] Time: note how long a design with 5 sizes and 100 timeline items takes.

### Pick points that follow sizes

Use the filter tray: an 80 by 60 base extruded to `count * cube + 2 mm`, a shell that opens the top, rounded vertical
corners, and a pipe hole in a row of three. Tick the count and the cube width.

- [ ] Export and open in Paramability. Set the count to 2.5 and the cube width to 30 (the box grows to 77 mm): the top
      stays open and all four corners stay round. Do the same at both ends of each range and with every size at its
      smallest and at its largest.
- [ ] Round only three of the four corners and export again: the same three corners stay round at every height.
- [ ] Shell the top and one side face: both stay open when the height changes.
- [ ] Add a tab beside the box, extruded "to" the top face. In the app the tab grows with the box.
- [ ] Add a boss extruded "from" the top face: in the app the boss rides on the top when the height changes, and
      no size is fixed for it.
- [ ] Add a boss whose sketch sits on an offset plane, with the start offset of the extrude set to `wall_mm * 2`: in the
      app the boss moves with `wall_mm`.
- [ ] Round the inside edges of the shell: the message lists the sizes written before the round as "may give
      unexpected results", with the round's name in the reason.
- [ ] Turn the design to Y up and repeat the first check.
- [ ] Mirror the rounded corners of one side: the mirrored corners stay round at every height, and no height size
      is fixed.
- [ ] Add a row of three posts (a rectangular pattern of an extrude, spacing `hole_pitch_mm`), then round the top
      edge of the last post: the round stays on that post when the spacing changes. Make the count a formula of a
      ticked size: that size may give unexpected results, with "picks a copy made by" in the reason.
- [ ] Chamfer the four top edges with two distances (1 mm and 2 mm), then flip the chamfer and export again: in the
      app the 1 mm side is on the top in the first file and on the walls in the second. The report shows `sides` and
      `cut_normals` on each edge. Do the same with a distance and an angle (30 degrees).
- [ ] Taper a join extrude of two separate outlines by 3 degrees, with its end face meeting the top of the box: it
      is copied, and the report shows `side_leans` for every wall. Flip the taper sign: still copied with the other
      sign. A tapered cut of two outlines is copied too.

### 7.2 The parameter table dialog

Use the filter box design (names such as `FilterBox_$_depth__contains_CeramicMedium`, a comment `Wall [1..4]` on `wall_mm`).

- [ ] Columns: tick, Parameter (the Fusion name), Now (value and unit), Min, Max, In Paramability. The header row has
      no tick. Min and Max name the design's length unit ("Min (in)" in an inch design), and Now shows lengths in it
      too. An angle row shows "deg" in its cells and a count row shows plain numbers. The table scrolls when there are
      many rows.
- [ ] **Long names.** A name over about 36 characters is cut in the middle with "..." and stays on one line, so
      every row has the same height. Hover the name: the tooltip holds the full name; the box under the table shows
      it in full after a click. If names that fit still wrap, or the cut is too early, note the column width.
- [ ] **Row click.** Click a row (not its tick): the box under the table shows the name, the comment, and for a
      formula the formula with "Now ...", for a greyed row the reason. If the box does not follow the click, note
      it: it then only follows ticks and typed ranges.
- [ ] Tick or untick a row: its Min and Max open or grey out, "In Paramability" says "size" or "stays 3 mm", and the
      last line of the box under the table says "N of 64 sizes ticked."
- [ ] **Range.** Min and Max of a ticked row start from the comment (`Wall [1..4]` gives 1 and 4), else half to double
      the value. Type 1.5 and 6: after the export the size in Paramability goes from 1.5 to 6. Type a Min above the
      value, a Min above the Max, or text: the count line names the parameter and OK turns off. A count row refuses
      1.5 and 0. Type a comma (`1,5`) or a unit (`2 mm`, `0.1 in`): all are read. `1,000` is refused, since it
      could mean one or a thousand. In an inch design, type 2 for Max: the size goes up to 2 inches.
- [ ] Does a typed Min or Max fire `inputChanged` when you leave the field (not only at Enter)? If the count line
      updates late, note when.
- [ ] "Tick what the body uses" returns the ticks to what the body reads; "Untick all" clears them. Both keep typed
      ranges. A greyed row is never ticked by either.
- [ ] Pick another body: ticks, greyed rows and texts follow; typed ranges go back to the defaults.
- [ ] The Design up direction menu is under the box with the count.
- [ ] **The export window has no empty gaps.** Open the dialog on the filter box design, then look at:
      - Under "Copied with a note: ..." (or the stop warning) no blank lines before the table; nothing shows when
        the body copies fully. A long warning shows all its lines, none cut off.
      - Under the table one box holds the hint, then the count line, with no blank lines between or after. Hover
        it: the tooltip says the design is changed for a moment and that every parameter also comes along.
      - Click a row with a long comment: the box grows to show it all and shrinks back on the next row.
      - Table rows are one line each, the name column is the widest and the last column ("stays 12 mm", "fixed,
        changes a sketch") is not cut off. About ten rows show before the table scrolls; the table spans the width.
      - The Saved window (result dialog) has no blank lines under its notes and fixed lists either.
      If a box is still too tall or too short, note the text it holds and the dialog width.
- [ ] **Early warning.** Pick a body whose steps hold one the add-in cannot copy (for example a sweep, a loft or a
      coil). Right under the body picker a box shows "Copy stops at Sweep1 (sweep)." in bold, the reason in short,
      and "The part will be saved as a fixed shape; your parameters still come along as variables." Hover the box:
      the tooltip holds the full reason. If no tooltip shows, note it (the reason is then only in the box when short,
      and in the message after the export). Pick a body that copies fully: the box and the button go away. A step
      copied with a note (for example a round with setback corners, or an extrude that uses a sketch of another
      component) adds one line "Copied with a note: ...".
- [ ] **Show in timeline.** With a stop shown, click "Show in timeline". The stopping step's feature is selected in
      the canvas and the timeline marker does not move; the design is not changed. The body picker still holds the
      body. If Fusion refuses the selection a message says so. Note whether the step also shows as selected in the
      timeline bar. No button shows when the stop has no step (a linked part, an unreadable place, a read that failed).
- [ ] **Message and status line.** Click OK on such a body. The message box starts with "Saved <file>. Copy stopped
      at Sweep1 (sweep)." then the reason and "The part is saved as a fixed shape." After you close the box, the
      lower-right corner of the Fusion window shows "Paramability: saved as a fixed shape. Copy stopped at ...". Note
      whether the line stays or Fusion replaces it at once (its lifetime is not fixed by the API).
- [ ] Click OK: the progress window shows as before, then the result window "Saved for Paramability" opens with the
      saved line, a table of sizes (name, range, and under "In Paramability": "size", "may be unexpected", "kept fixed",
      "not followed" or "not used"), a "Stays fixed" group, a "May give unexpected results" group and a "Not followed"
      group with each reason (a group with nothing in it is left out),
      and the line "All N parameters come along as variables ...". Only a Close button shows.
- [ ] The result window opens right after the export ends, not while the progress window is still up. If it does not
      open, the same text shows in a message box. Note which: the log line "result dialog failed" gives the reason.

## 8. Bodies inside components

Send `report.json` from any export that surprises; its capture becomes a test fixture. These tests check that a body
inside a component, also a nested or turned one, lands where Fusion shows it.

- [ ] **C1 Moved component.** A model with sizes (the filter box) built inside a component `Tray`, its occurrence
      moved to (100, 50, 0) and its position captured. Export: a recipe with sizes that lands where Fusion shows it.
      Put on the form and change a size. The report shows `entity_context` and `placement.source`. The timeline
      marker is at the end, no temporary component is left, parameters are back.
- [ ] **C2 Nested and turned.** `Tray` inside a component `Box`; `Box` turned 90 degrees about Z, `Tray` turned 90
      degrees about X inside it. Same checks as C1, plus a hole on a sketch point: it lands in the right place.
- [ ] **C3 Used twice.** Two occurrences of `Tray` at different places. Pick the second: it lands at the second
      place, and the note says the part is used 2 times.
- [ ] **C4 Joints.** `Tray` joined to `Box` with an offset `gap_mm`: `gap_mm` is unticked with a joint reason and
      may give unexpected results when ticked.
- [ ] **C5 Cut from the assembly.** With the root active, cut a hole through the body of `Tray`. Export: a fixed shape
      whose note names the cut.
- [ ] **C6 Components from bodies.** Model a body in the root, then "Create Components from Bodies". Export it and
      note what happens (a recipe or the "made in another component" note); send the report.
- [ ] **C7 Uncaptured move.** Drag `Tray` without capturing its position and open Export for Paramability: the dialog
      itself says "Capture the position of moved parts first (Position, Capture Position), then export again." and
      has no OK button. Check that the message shows at once, before any table is built. Capture the
      position and export again: it works.
- [ ] **C8 Linked component.** Insert a design as a linked component and pick its body: the file is a fixed shape with
      the linked design note.
- [ ] **C9 Reach into another component.** A sketch in `Tray` on a face of `Box`, and an extrude in `Tray` "to" a face
      of `Box`. The first exports (a `Box` parameter that moves it may give unexpected results, with the sketch reason); the second is a
      fixed shape naming the extrude.
- [ ] For a component body, the dialog table follows the component's own parameters, and "Tick what the body uses"
      ticks only what the component reads.
- [ ] **C9b Sketch of another component.** An extrude in `Tray` that uses a sketch of `Box` (moved and turned), and a
      mirror in `Tray` across a plane of the root. Export: the extrude is copied where Fusion shows it, with a note
      that names the sketch, and the mirror is copied. A ticked size that drives a dimension of that `Box` sketch
      may give unexpected results, with "changes the sketch". The report shows `native_frame`, `placement.checked_points` 3 and
      `sketch_params` on the profile, and `"assembly": true` on the mirror plane.
- [ ] **C10 Many components.** A design with several components made one after the other (each with sketches,
      construction planes and extrudes), the picked one in the middle, and one moved away from the origin. Export:
      the occurrences and construction planes of the other components are "skipped" in the report, never the refusal.
      The report items of the picked component's own extrudes, chamfers and mirrors carry no `foreign`, and its
      outlines on a standing sketch (on a side plane, not the ground) have real 2D points, not all `y` = 0.
- [ ] **C11 Offset faces.** In a component: a box, then Press Pull its top face up by `gap_mm`, then a second box
      whose side face is pulled in by 1 mm. Export: two recipes whose offsets became extrudes (join and cut), and a
      changed `gap_mm` moves the top. The report shows `faces_after` and `sides: "square"`. A pulled face with a
      fillet next to it, or a curved face, gives a fixed shape that names the offset. The offset item in the report
      has no `read_error`.

## 9. Sketches that follow sizes

Send `report.json` from any export that surprises; its `probe` record (the states read, the motion and
`restore_gap_mm`) and its capture become test fixtures. In every test, the package is checked in Paramability: change
the sizes on the form and compare the part with Fusion at the same values.

- [ ] **K1 Filter box base.** The filter box of the parameters plan with the base rectangle `FilterBox_width_mm` by
      `FilterBox_depth_mm` (both `count * cube + 2 mm`), centred on the origin by a midpoint constraint. Tick the
      counts and the cube width. Export: no parameter is greyed; the result window shows all as sizes; `recipe.json`
      has `"width": { "expr": "FilterBox_width_mm" }`. In Paramability, changing a count or the cube width resizes the
      base, the shell stays open and the corners stay round. Repeat with the rectangle drawn from the origin corner.
      Note the export time.
- [ ] **K2 Pipe offset.** A circle placed by `pipe_offset_mm` from the box edge, diameter `pipe_d_mm` as a sketch
      dimension, cut through. Then a hole feature on a sketch point at `pipe_offset_mm`. Both follow both sizes and
      the box width.
- [ ] **K3 Offset plane.** A sketch on a construction plane offset by `FilterBox_height_mm`, a boss extruded from it.
      The boss moves with the height. Then make an extrude reach "to" that plane: the height may give unexpected
      results, with the construction plane reason.
- [ ] **K4 Sketch on a face.** A sketch on the top face of the base, a lid lip extruded from it with projected edges.
      The lip follows the height and the width.
- [ ] **K5 What may give unexpected results.** A point placed by an angle parameter on a circle (reason: along a curve); a line that
      crosses the outline only above some width (reason: a different outline); a plane at an angle driven by a
      parameter (reason: turns the plane). Each may give unexpected results, with its reason; the other sizes work.
- [ ] **K6 Constraints.** A slot with equal and symmetric constraints, a rectangle with sketch fillets of radius
      `corner_mm`, a hole diameter `sqrt(area_mm2)`. All follow; the fillet arcs keep their radius.
- [ ] **K7 Restore and cancel.** Cancel during "Trying size 2 of 6": parameters are back and the marker is at the
      end. A range comment that Fusion cannot build at the bottom of the range: the report `probe.dropped` lists the
      state, the size stays a size and the other sizes work.
- [ ] **K8 In a component.** K1 built inside a turned component `Tray`: the box lands where Fusion shows it and
      resizes in place.
- [ ] **K9 Report.** Send the K1 report. It pins token stability (the curves are found again in every state), the
      first read against the capture (a sketch that differs is not followed), `restore_gap_mm` (should
      be 0 or tiny) and the column checks (`motion.dropped`).
- [ ] **K10 Drawn around another component.** A box body in its own component with a hole whose circle (or two
      arcs) is projected from a pipe in another component, or constrained to such a projection; the pipe diameter is
      a user parameter used only in the pipe's component (the filter box with `MainPipe__Top_diameter_mm` is one).
      Open Export for Paramability and pick the box: the pipe diameter row is ticked, and clicking it says it changes
      the pipe component that the hole sketch is drawn around. Export: the progress window tries the pipe diameter;
      the result window shows it as "size"; `report.json` has `links` with outcome `size` and `capture.sketch_links`
      names the pipe component. In Paramability, change the diameter: the hole grows and shrinks with it and matches
      Fusion at the same value. Then break the link (delete the projection and give the hole its own diameter): the
      row is not ticked to start with; tick it by hand and export: the progress window still tries it, and the result
      says "not used" with the reason that it was tried and changes nothing in this part (never "not used by any
      copied step"). In `report.json`, `capture.parameters.user` lists the pipe diameter's `dependents`: its sketch
      dimension names the pipe's sketch, and `capture.items` gives the pipe's extrude `sketch_inputs` with that sketch.
- [ ] **K11 Found by trying.** The K10 design with the pipe diameter unticked. Export: the progress window tries it
      once ("(try)"); the result window has the group "Also change this part" with the line "These parameters also
      change this part: ... Tick them and export again to get them as sizes."; `report.json` has `also_changes` with
      the pipe diameter and `probe.discovery` with `moved: true`. The pipe diameter is not a size in that file. Tick
      it, export again: it is a size.

## 10. Emboss

An Emboss of sketch outlines on a flat face is copied as an extrude that starts on the face. Send `report.json` from
any emboss that surprises; its capture becomes a test fixture. "Matches" means the part Paramability builds agrees with
the Fusion part. The calls behind these tests are listed under "Capture reader calls to watch (emboss)".

- [ ] **E1 Raised outline.** The BoxLid design: `Emboss1` on the sketch `DirectionEmboss` (a raised outline on the lid).
      The export copies it and the part matches. In `report.json` the emboss item shows `faces[0].surface` `Plane`, a
      positive `depth`, `volume_after` minus `volume_before` equal to the sum of `areas` times `depth`, and `end_offset`
      equal to the distance of the top of the outline from the sketch plane. Tick the parameter behind the lid
      thickness and the one behind the emboss depth: both resize the part in Paramability.
- [ ] **E2 Sunk outline.** The same outline as a deboss (a negative depth, or the Deboss option of the dialog). `depth`
      reads negative, the recipe step is a cut and the part matches. Note whether the dialog needs a negative number
      or an option: if the sign of `depth` does not follow what the dialog says, the sign rule is wrong; send the
      report.
- [ ] **E3 Moved or turned outline.** An emboss with a horizontal distance, a vertical distance and a rotation set in
      the dialog. The copy stops with "moved or turned on its face" and the part saves as a fixed shape. Note in which
      frame each setting moves the outline (the sketch axes, the face axes, or the model axes) and around which point
      the rotation turns, so the copy can follow them later. With all three at zero but one of them set by a
      parameter, a ticked size behind it stays free with the reason "it sets how far <emboss> moves its outline".
- [ ] **E4 Text.** An emboss of sketch text on the top face is copied (see section 11, X1). An emboss of text on a
      side face or a curved face is refused for its face, not for the text.
- [ ] **E5 Older Fusion.** In a Fusion build from before September 2025, open a design that has an emboss. The export
      does not crash: the step is named in the stop message and the part saves as a fixed shape.
- [ ] **E6 Tangent Chain.** Emboss an outline near the edge of a face that has a fillet along that edge, with Tangent
      Chain on. The copy stops with "Tangent Chain" and the part saves as a fixed shape. With Tangent Chain off, or on
      a face with no rounded edge, it is copied.

## 11. Spline outlines and sketch text

An outline with a spline edge (fit point or control point), an elliptical arc or another free curve is copied as spline
segments, and the outlines of sketch text are copied by Extrude and Emboss. Send `report.json` from any of these that
surprises; its capture becomes a test fixture. "Matches" means the part Paramability builds agrees with the Fusion part.
The calls behind these tests are listed under "Capture reader calls to watch (spline outlines and sketch text)".

- [ ] **S1 Spline edge.** Draw a closed outline of three lines and one fit point spline with five or six points
      (a bump on one side) and extrude it. The export copies it and the part matches: lay the Paramability part over
      the Fusion part and look at the curved wall; it must stay within about 0.005 mm. In `report.json` the curve shows
      `kind` `other`, `type` `NurbsCurve3D`, a `samples` list of 20 or more
      points, a `mid` that is one of them, `tangent_start` and `tangent_end` (unit directions that point along the
      curve), and no `truncated`.
- [ ] **S2 Curves of other kinds.** An outline with an elliptical arc (a slice of an ellipse), one with a control
      point spline, one made only of one closed spline (a blob), and one with a conic curve. Each copies and
      matches. Note the `type` each curve shows in `report.json`; a curve type that is refused tells which one.
- [ ] **S3 Spline on a tilted or turned sketch.** The S1 outline on a sketch on an angled construction plane, and on
      a sketch on the bottom face of a body (a sketch that is flipped in z). The export copies it, the item shows
      `space` `sketch` or `model` (not `ambiguous`) and the part matches. A spline-only outline is the case where
      the space is decided from the points of the curve and its sketch curve.
- [ ] **S4 Size that moves a spline.** Tick a parameter that drives a sketch dimension of the S1 sketch (the width).
      The size does not follow in Paramability: it is either left out of the sizes, with "it changes Sketch1 and could
      not be tried at other values", or, when another step reads it too, it stays free with the same reason as a
      warning. The shape at the current value is right.
- [ ] **S5 Long or tight curve.** A spline 150 mm long with ten bends, and a tight curve (a hook of 1 mm radius).
      The part matches. In `report.json` read the number of `samples` and whether the curve shows `truncated`; a
      truncated curve is refused with "could not be read closely enough". In Paramability open the sketch and
      check that the curve is smooth where one spline was split in two.
- [ ] **X1 Text, emboss.** Write a short text ("Hello 3D") on a sketch on the top face and Emboss it 1 mm. The export
      copies it, each letter shape is a step of its own and the inside of "e", "o" and "D" stays open. The part
      matches. In `report.json` the emboss item shows one profile record per letter shape, each with `text` true,
      `space` and `loops`, and `areas` that add up to about the text area; `volume_after` minus `volume_before` is that
      area times the depth.
- [ ] **X2 Text, extrude and space.** The same text as an Extrude (new body, 2 mm). It copies and matches. Then put
      the text on a sketch that is not the identity (a sketch on a side face, one on the bottom face, and one on an
      angled plane). The item shows `space` `sketch` or `model` and the part matches; a text refused with "could not
      be told with certainty" shows the bounding box rule could not decide, and the points of
      `SketchText.asCurves()` in the Fusion console against `SketchText.boundingBox` say which space they are in. Set
      `GEOMETRY_SPACE` in `read_sketch.py` once this is known.
- [ ] **X3 Text stays text.** After an export the text in the sketch is still one text (not exploded), the timeline
      has no new item and the design is not marked changed by the read. `SketchText.asCurves()` is documented as not
      changing the text; this is the check.
- [ ] **X4 Shapes with holes, and big text.** "ABOQ8%" in a bold font: every hole is kept. A line of about 60
      characters in a fine script font: it copies or stops with "This text has too many outline points to copy",
      and the export does not take more than a minute longer than without it.
- [ ] **X4b Overlapping strokes.** A variable font whose letters are drawn from overlapping strokes (for example a
      heavy weight of a variable font with "k" or "x"). If `SketchText.asCurves()` returns crossing loops the copy stops
      with "This text has overlapping outlines, so it is not copied yet". Note which fonts do, and whether the loops
      of one glyph keep the winding of the font (this could replace the even and odd rule later).
- [ ] **X4c Extrude of overlapping strokes.** The text of X4b as an Extrude (new body, 2 mm). The export stops with
      the same overlap reason, not with a part. If the strokes come through as separate outlines instead (no crossing
      loops), the extrude volume check stops it: the volume of the Fusion part is smaller than the outline areas times
      the length, and the item says so. Check that no part is exported in either case.
- [ ] **X5 Text and sizes.** Tick a parameter that drives a sketch dimension of the text's sketch (its position).
      The size stays loose or is left out with "could not be tried at other values". An emboss depth ticked as a size
      follows. A size that drives the text height (`Height` in the text dialog) is left out of the sizes with the
      reason "it changes the size of the text in <sketch>", also when the same size drives the emboss depth; the text
      keeps its current height.
- [ ] **X6 Text of another component.** A text in a sketch of another component used by an extrude of this one: the
      part saves as a fixed shape.

## Thin extrudes

A thin extrude of one closed outline is copied as an extrude with a wall. Send `report.json` from any thin extrude
that surprises; its capture becomes a test fixture. The calls behind these tests are listed under "Capture reader
calls to watch (thin extrude)".

- [ ] **T1 Which side is which.** Draw a 40 x 30 rectangle and make a thin extrude, 10 mm tall, wall 2 mm, once with
      each wall location in the dialog (Side 1, Side 2, Center). Note for each which way the wall grows (into the
      rectangle, out of it, or both) and whether the corners on the outside are sharp or round. In `report.json`
      the item shows `thin_wall.location` (`side1`, `side2` or `center`) and `end_area`: 264 for a wall inside, about
      296 for a wall outside with sharp corners (292.6 with round corners), about 280 for a centered one. The copy
      takes the side from `end_area`, not from the location name, and the part must match each time. Where Fusion
      keeps the outside corners sharp, the copy rounds them and the item shows the note "Fusion keeps the corners of
      this wall sharp"; check that the difference is the size of the corner only.
- [ ] **T2 Open line.** Draw one open line (or a few joined lines that do not close) and make a thin extrude of it,
      the way a rib or a fence is made. The copy stops with "A thin extrude of an open line is not copied yet" and the
      part saves as a fixed shape. In `report.json` read what Fusion gave as the profile: `thin_wall.profile_type`
      (the type of `ExtrudeFeature.profile`) and the entries of `profiles` (`{ "kind": "other", "type": ... }` shows
      the type of each). Note whether the end of the wall is square or round in Fusion; the app draws round ends.
      This is what a later copy of open lines needs.
- [ ] **T3 Wall as a size.** Tick the parameter behind the wall thickness and the one behind the height, export, and
      change both in Paramability: the wall and the height follow. Set the range of the wall so it can reach zero:
      the wall is then not a size, with the reason in the result window.
- [ ] **T4 Cases that stop the copy.** A thin extrude of an outline with a hole, of two outlines, that goes two ways,
      that reaches to a face, and with a taper (if the dialog lets you). Each stops with its own plain reason.
- [ ] **T5 Remainder.** A parameter `a % b` whose left side stays positive over its range is copied. When the left
      side can go negative (for example `(width - 120 mm) % 7 mm` with width from 65 to 260), the sizes it reads are
      loose with the reason. Also note what Fusion shows for a negative left side, such as `-20 mm % 7 mm`: the app
      gives 1 (the result takes the sign of the right side). If Fusion gives 1 as well, the check can be dropped.

## Fusion calls to watch

These were written from the API reference and never run:

- `BRepBody.copyToComponent` into a new occurrence (hand test 3).
- Deleting the temporary occurrence and the timeline items the copy adds: only entities that are not equal (`==`) to
  one of the entities read before the copy, wherever they sit; nothing when more items look new than the timeline
  grew by (hand test 3). Check
  that `==` between two wrappers of one Fusion entity is true, here and in the capture (`parentComponent == ctx.
  component`, `same_entity` in `lib/fusion_reader/read_geometry.py`). If it is false, the capture marks every item
  as outside the target's component and the placement of a nested body is refused.
- `Timeline.markerPosition` equal to `Timeline.count` when the marker is at the end, and equal to the number of steps
  before the marker when it is rolled back (the dialog line counts steps this way).
- With the marker rolled back (hand test 3, "Marker rolled back"), none of these run yet:
  - `Occurrences.addNewComponent` and `BRepBody.copyToComponent` put their timeline items at the marker and move the
    marker past them, and the copied body exists (the export refuses an empty copy). If Fusion puts them at the end
    instead, the copy is rolled back and the export stops with "The copy of the part could not be made".
  - `Occurrence.deleteMe` removes the items of the temporary component and moves the marker back by as many; the
    add-in then sets `markerPosition` to the start position if it is not there.
  - `Design.computeAll` and setting `UserParameter.expression` leave the marker where it is. The add-in puts it back
    after every recompute in any case, and once more at the end of the export.
  - `TimelineObject.healthState` of the items before the marker after a recompute; items after the marker are not
    read for health.
  - `ExportManager.createSTEPExportOptions` with the root component writes the body as it is at the marker.
  - Timeline groups that span the marker: only their children before the marker are checked.
- The `preSelect` event and `isSelectable` for the body picker.
- `Design.findEntityByToken` to find the body again after each recompute.
- `ExportManager.createSTEPExportOptions` with a component, and `execute`.
- The sizes table (`lib/fusion_ui/sizes_table_ui.py`), none of it run yet; the API reference pages could not be read
  while writing it, so every member below is from memory of the reference and Autodesk samples:
  - `CommandInputs.addGroupCommandInput`, `GroupCommandInput.children`, `isExpanded`, and `itemById` on the command
    inputs finding the group; inputs created through `group.children`.
  - `children.addTableCommandInput(id, name, columns, "2:1:1")` (column ratio text), `TableCommandInput.addCommandInput(input,
    row, column)`, `getInputAtPosition`, `rowCount`, `selectedRow` (-1 when none), `deleteRow`, `minimumVisibleRows`,
    `maximumVisibleRows`.
  - `TableCommandInput.addToolbarCommandInput` with a `BoolValueCommandInput` created with `isCheckBox=False` and an
    empty resource folder: the button should show its name as text. If it shows nothing, add an icon folder.
  - `CommandInput.deleteMe` on a table, then a new table added in the same group (the columns of a table are fixed
    when it is created). Cells are created through the same `children` as the table. If the group order or the
    stale cells cause trouble, build the table once and hide it instead.
  - `inputChanged` firing for cell inputs, the toolbar buttons and the check boxes inside a group; `selectedRow`
    reading while the header row (row 0) is selected.
  - `addValueInput` with unit text `mm`, `deg` or an empty string (counts), and `ValueCommandInput.value` returning
    internal units (cm, rad).
  - `CommandInput.isEnabled` and `tooltip` on a check box.
  - `BoolValueCommandInput.text` must not be set on a check box: Fusion raises `InternalValidationError : button` (the
    text is for button style only). The label is the parameter name, fixed at creation.
- The main dialog (`lib/fusion_ui/recipe_dialog.py`), none of it run yet:
  - `commandInputs.addTableCommandInput(id, "", 6, "1:9:2:2:2:4")` with cells added by `addCommandInput(input, row,
    column)`: check boxes (`addBoolValueInput` with empty text), read-only text boxes, and `addStringValueInput` for
    Min and Max. Cells are created through the command's own inputs, not a group. Row 0 holds the header text boxes.
  - `TableCommandInput.minimumVisibleRows`, `maximumVisibleRows`, `isFullWidth`, `addToolbarCommandInput` with two
    `isCheckBox=False` buttons (their text must show; the same call as Export size choices), and `Command.
    setDialogInitialSize(700, 700)` to make room for six columns. Each is set in a guarded call, so a refusal is
    logged ("Table width failed") and the dialog still opens.
  - **A row click firing `inputChanged`** with the table (or a cell) as the changed input, and `TableCommandInput.
    selectedRow` giving the clicked row (row 0 is the header). The details box also follows the row of a touched tick
    or Min or Max field, so a missing row click only leaves the box on the last touched row.
  - **A long name in a text box cell:** `TextBoxCommandInput.formattedText` with `<br>` and the row count given at
    creation; whether the row grows to fit the lines.
  - `isEnabled` and `value` set on cells in `inputChanged` and when another body is picked; `StringValueCommandInput.
    value` read from a cell, and `inputChanged` firing when a typed Min or Max is committed.
  - `TextBoxCommandInput.formattedText` set after creation for the details box and the count line (`<b>` and `<br>`).
  - Cell ids are made from the row number (`pm_tick_3`), not from the parameter name.
  - **Layout without gaps** (hand test "the export window has no empty gaps"), none of it run yet:
    - `TextBoxCommandInput.numRows` set after creation (warning box, details box, export status box): whether it is
      writable and the box resizes. If it raises it is logged ("Warning rows failed", "Details rows failed") and the
      box keeps its first height (1 row for the warning, 2 for the details).
    - Whether a text box with `isVisible = False` leaves no gap, and `tooltipDescription` on text boxes (details box,
      warning box, name cells).
    - Read only text boxes show html: `&lt;`, `&gt;` and `&amp;` must display as `<`, `>` and `&`, while quotes
      are sent as plain `"` (the entity `&quot;` showed as typed). A parameter name with `<` or `&` shows the
      character, not the entity.
    - Row height of a one line text box cell; the column ratio `1:9:2:2:2:4` and the width of the name column
      (36 characters); `minimumVisibleRows` 6, `maximumVisibleRows` 14 and `isFullWidth` with a dialog of
      700 x 700; whether 14 rows fit the dialog height. The result dialog uses ratio `8:3:3`.
- The result dialog (`lib/fusion_ui/result_dialog.py`), none of it run yet:
  - **Starting a command after the export command:** `Application.registerCustomEvent(id)` in `start()`,
    `CustomEvent.add` with a `CustomEventHandler`, `Application.fireCustomEvent(id)` at the end of the export, and
    `unregisterCustomEvent` in `stop()`. The handler runs `CommandDefinitions.addButtonDefinition(id, name, tooltip,
    "")` (a definition that is in no panel), `commandCreated` and `CommandDefinition.execute()`. Check that the
    window opens once the export command has ended. The fallback is the message box when firing or starting raises;
    if nothing raises but nothing opens, look for the window at the end of the export and note it.
  - `Command.isOKButtonVisible = False` and `Command.cancelButtonText = "Close"`; a group with a table whose cells
    come from the group's `children`; text boxes with `<br>` lines.
- The early warning (`lib/fusion_ui/timeline_select.py`, `lib/fusion_ui/notice.py`, `commands/ExportForParamability/
  entry.py`), none of it run yet:
  - `Timeline.item(index).entity` giving the feature of a timeline item (`None` for a group or an unsupported type),
    without touching `markerPosition`.
  - `UserInterface.activeSelections.clear()` and `.add(feature)` with a feature (the reference says `add` takes any
    entity; it does not name features). While the dialog's body picker is active the selection may go to the picker:
    after the call the add-in puts the body back with `SelectionCommandInput.clearSelection` and `addSelection`.
    Check that the body stays picked, that no `inputChanged` loop starts, and that the selection survives until the
    dialog closes.
  - A button style `BoolValueCommandInput` ("Show in timeline", `isCheckBox=False`) whose `value` is set back to
    False in `inputChanged`; `CommandInput.isVisible` on it and on the warning text box; `TextBoxCommandInput.
    tooltipDescription` and `CommandInput.tooltip` on a read-only text box.
  - `UserInterface.statusMessage` (the lower-right corner) followed by `adsk.doEvents()`, set at the end of the
    export command. The reference says its lifetime is not fixed.
- The component export flow (`commands/ExportForParamability/export_flow.py`): `Design.snapshots` and
  `Snapshots.hasPendingSnapshot` (asked when the dialog opens, before the capture moves the marker, and again at OK;
  an unreadable answer counts as "nothing pending"); the capture members of "Bodies inside
  components" in `docs/capture-format.md`.
- The size probe (`lib/fusion_reader/probe_state.py`, `lib/probe/`, `lib/export_plan/probe_flow.py`), none of it run
  yet. Each member below is read at every state; a missing one only leaves that sketch unread, so its sizes may give
  unexpected results, and it shows in `probe.states` of `report.json`:
  - `Sketch.entityToken`, `Sketch.profiles` per state (the profiles at the timeline end must equal the ones the
    steps used: the first read is compared with the capture within 1e-4 mm), `Sketch.referencePlane` with
    `.entityToken` and `objectType`.
  - `ProfileCurve.sketchEntity.entityToken`: the same curve must give the same token after every recompute (K9).
  - `SketchPoint` and `SketchLine` `.entityToken`, `.parentSketch`, `.worldGeometry`; the hole point tokens
    (`SketchPointsHolePositionDefinition.sketchPoints` items) and the revolve axis line token.
  - `ConstructionPlane.entityToken` and `ConstructionAxis.entityToken` (a step that reaches one marks the sizes behind
    it); `RectangularPatternFeature.directionOneEntity` and `directionTwoEntity` with `.parentSketch`.
  - `Design.findEntityByToken` for sketches, points and lines of a component (K8): the native object or an
    occurrence proxy, the add-in keeps the one without `assemblyContext`.
  - Another component's sketch used by a step (borrowed): `Design.findEntityByToken` for its native `Sketch`,
    `Sketch.parentComponent`, `Component.allOccurrencesByComponent` on the root with `Occurrence.fullPathName` (the
    occurrence is picked by the path the capture recorded) and `SketchPoint.createForAssemblyContext(occurrence)` read
    again at every state, since a size can move that component. Check in `probe.states[*].read.sketches` that the
    sketch has `native_frame` and `placement`, and that `unread` is absent. Test: the filter box with a lid in a
    second component whose sketches project the box edges; shrink and grow the box on the form and compare the lid
    rails with Fusion at the same sizes.
  - `UserParameters.itemByName` and `Component.modelParameters.itemByName` for the value of each column per state.
  - `ModelParameter.createdBy` of a sketch dimension: recognised by the type name, a `SketchDimension` cast, the
    members `parentSketch` and `parameter`, or else the sketch dimension whose own `parameter` is this one
    (`Sketch.sketchDimensions`). Check that `created_by.kind` is `sketchDimension` with the sketch name in the report
    capture for each dimension.
- `Design.fusionUnitsManager.defaultLengthUnits` as the unit of a bare number in a length formula (falls back to mm).
- `Component.modelParameters` read by `list_model_parameters`.
- Scoping to the picked body: `SketchDimension.parentSketch` with `Sketch.name` (read as `created_by.sketch`), and
  the name of a feature (`created_by.name`) equal to its timeline item name. A name that does not match leaves the
  parameter in, so a mismatch shows as a parameter that other bodies' steps make ticked.
- Reading the capture while the dialog is open (`lib/fusion_ui/` and `commands/ExportForParamability/entry.py`): the
  timeline marker moves in the `commandCreated` and `inputChanged` events and comes back to where it was. Also
  `BoolValueCommandInput.value`, `isEnabled` and `StringValueCommandInput.value` assigned in `inputChanged`.
- Two buttons in one panel (`ControlsCommand` added twice, `isPromoted` on the first only).
- `ProgressDialog` (`show`, `progressValue`, `wasCancelled`) and `FileDialog` filter text.
- `FeatureHealthStates.ErrorFeatureHealthState` on timeline items after `computeAll`.
- The modeling orientation preference as the up direction.
- Toolbar tab id `ToolsTab` for the Utilities tab.
- What a mirror plane or a circular pattern axis is (`lib/fusion_reader/read_reference.py`; check the `plane` and `axis`
  records in `report.json` of a mirror across a body face, across a construction plane offset from a face, across an
  origin plane, and a pattern about an edge, a cylinder face, a construction axis and an origin axis):
  - `Component.xYConstructionPlane`, `xZConstructionPlane`, `yZConstructionPlane`, `xConstructionAxis`,
    `yConstructionAxis`, `zConstructionAxis` equal (`==`) to the plane or axis the feature uses: the record then says
    `origin: true` and nothing more. If the comparison is false, an origin plane is read as construction geometry with
    no `built_on`, which the translator treats as parameters only, so it still stays where it is.
  - `ConstructionPlane.timelineObject.index` (`made_by`) and `ConstructionPlane.definition` (type name:
    `ConstructionPlaneOffsetDefinition`, `...MidplaneDefinition` and so on; the translator follows only names that
    hold `offset` or `midplane`). The same two members on `ConstructionAxis`.
  - The members of those definitions that name what they are built on, tried one by one and each guarded:
    `planarEntity`, `planarEntityOne`, `planarEntityTwo`, `linearEntity`, `tangentFace`, `referencePlane`, `edgeOne`,
    `edgeTwo`, `pointOne`, `pointTwo`, `pointThree`, `point`, `path`, `circularFace`, `edge`, `face`, `planeOne`,
    `planeTwo`, `entity`. Written from memory of the reference: print `built_on` of an offset plane (one face) and a
    midplane (two faces); a plane whose definition members are not found has no `built_on` and is treated as
    parameters only.
  - `BRepFace.pointOnFace` and `BRepFace.geometry` (type name `Plane` or `Cylinder`) of the mirror face or the pattern
    axis face; `BRepEdge` points through `edge_record`.
- Geometry links (`lib/fusion_reader/read_links.py`, `dependents` in `parameters.py`), K10 and K11. Read in the
  API reference: `Sketch.sketchCurves`, `sketchPoints`, `geometricConstraints`, `referencePlane`;
  `SketchEntity.isReference` and `referencedEntity`; `CoincidentConstraint.point` and `entity`,
  `ConcentricConstraint.entityOne` and `entityTwo`, `EqualConstraint` and `TangentConstraint` `curveOne` and
  `curveTwo`; `ModelParameter.createdBy`, `component` and `dependentParameters`; `ExtrudeFeature.profile`,
  `SweepFeature.profile`, `path` and `guideRail`, `PathEntity.entity`, `LoftSection.entity`. A real export confirmed
  that `referencedEntity` names the other component through `assemblyContext.component`, and showed that
  `ModelParameter.component` answers the root component for every dependent, so it is used only as a last fallback.
  Not confirmed yet: that `createdBy` of a parameter from `dependentParameters` names its sketch or feature (print
  the pipe diameter's `dependents` from `report.json`: a sketch dimension must name the pipe's sketch and the pipe
  component); that `sketch_inputs` of the pipe's own steps name that sketch; that the `body` of a referenced edge
  has the token `bodies_after` gives (compare `sketch_links[].links[].bodies` with the pipe steps' `bodies_after`);
  that `lineOne`, `lineTwo`, `line` and `curve` are members of the other line constraints; that reading `profile` and
  `path` on steps of other components with the marker before them is quick on a large design (note the export time).
- The export pipeline (`lib/export_plan/pipeline.py`, wired in `commands/ExportForParamability/export_flow.py`):
  the export measures the sketches, and the probe reads the sketches once more after the last restore, so
  `report.json` `probe.restore_gap_mm` and `health` describe the design as the person gets it back. Check that the
  extra read after a restore does not move the timeline marker, that `health.sketch_drift` stays false on a design
  that returns to its start, and that a restore the add-in cannot finish (a parameter locked by hand during the
  export) shows "These parameters could not be set back" in the result window and in a message box.

## Capture reader calls to watch (extrude, revolve, hole, combine, thread, sketch profiles)

These members and values were written from the API reference and never run. A member that cannot be read gives
`null` or `other`, which the translator refuses, so a wrong guess shows up in `report.json` rather than as a wrong
part. The few members that fall back to a default (the fillet, chamfer and shell ones) are listed in the next part.
Run the plate, tilted sketch, turned knob, extrude directions, holes and combine designs of section 7 and
read the capture in `report.json`.

- Enum names are matched by text: `FeatureOperations`, `FeatureExtentTypes`, `HoleTypes`, `HoleTapTypes`,
  `FeatureHealthStates`. Unknown names fall back to `other`.
- `ProfileCurve.geometry` space. The reader treats geometry with every point at z near 0 as sketch space, else maps it
  with `Sketch.modelToSketchSpace`. A sketch lying in a model plane with turned axes cannot be told apart this way;
  `GEOMETRY_SPACE` in `read_sketch.py` can be set to `"sketch"` or `"model"`.
- `ProfileCurve.sketchEntity` and `SketchCurve.geometry` (sketch space), used to decide the curve space of a sketch
  in the plane z = 0 with a turned frame (for example a sketch on a bottom face). A profile marked `"space":
  "ambiguous"` is refused.
- `Timeline.timelineGroups`, `TimelineGroup.startIndex` and `endIndex`: a design with a collapsed group must export;
  a group whose children `Timeline.item` does not list makes the capture fail and the export a fixed shape.
- `BRepFace.geometry` type of the hole end faces (`plane` flat, `cone` tipped; anything else gives null), compared with `tipAngle`.
- `HoleFeature.holeType` names that do not match fall to `other`; the same for `FeatureExtentTypes` on extrudes.
- `Matrix3D.getAsCoordinateSystem()` returning `(origin, xAxis, yAxis, zAxis)` in Python.
- `CurveEvaluator3D.getParameterExtents` and `getPointAtParameter` (arc middle point, the adaptive samples of free curves, edge
  points); `SurfaceEvaluator.getNormalAtPoint` (revolve start face normal).
- Model parameters read through `.value` (distances, taper angles, angles, hole sizes, offsets). A plain number is
  also accepted.
- `ExtrudeFeature.symmetricExtent` with `distance`, `isFullLength`, `taperAngle`; `taperAngleOne`, `taperAngleTwo`.
- `ExtrudeFeature.startExtent`: `OffsetStartDefinition.offset`; the entity member name of the from-entity start
  definition (`entity` is assumed); `ToEntityExtentDefinition.entity` and `.offset`.
- `ThroughAllExtentDefinition.isPositiveDirection`, and the type name of the "all" extent (`AllExtentDefinition`).
- A flipped one sided extrude storing a negative distance: compare `side_one.distance` with `end_offset`.
- `RevolveFeature.axis` (sketch line, construction axis, linear edge, cylindrical face), `isProjectAxis`,
  `extentDefinition` (`AngleExtentDefinition.angle`, `isSymmetric`; `TwoSidesAngleExtentDefinition.angleOne`,
  `angleTwo`), `startFaces` and the sign of `start_face_normal`.
- `Profile.areaProperties().area` and `BRepFace.area` (cm2, read as `profile_area` and `end_area`), and
  `Component.bRepBodies` of the root at each marker position (`bodies_before`).
- `ExtrudeFeature.sideFaces` with the marker after the item, and `SurfaceEvaluator.getNormalAtPoint` at
  `pointOnFace` pointing out of the body (`side_leans`); a merged or split side face is still one of the listed faces.
- Another component's sketch used by a feature: `Profile.assemblyContext` and `Profile.nativeObject` of the proxy,
  `Sketch.parentComponent`, `Sketch.sketchPoints`, `SketchPoint.worldGeometry` of the native point (component
  coordinates) and of `SketchPoint.createForAssemblyContext(occurrence)` (root coordinates), `Occurrence.transform2`
  of that occurrence, `Sketch.sketchDimensions`, `SketchDimension.parameter`, `Parameter.dependencyParameters`.
- A construction plane or axis of the root (or of another component, seen through its occurrence) used as a mirror
  plane or turning axis gives `geometry` in root coordinates (`from_assembly`).
- `HoleFeature.thread.isModeled`, `holePositionDefinition.sketchPoints[i].worldGeometry`, `position`, `direction`
  (into the material or out), `tipAngle` for a flat drill point, `participantBodies`, `sideFaces`, `endFaces`.
- `CombineFeature.targetBody`, `toolBodies`, `isKeepToolBodies`; `ThreadFeature.isModeled`.
- `participantBodies` on extrude and revolve (may be unreadable; then the list is empty).
- `Design.findEntityByToken` for the picked body at each marker position, with a name fallback in the root component.
- `OffsetFacesFeature.inputFaces` with the marker just before the item: a Python list of `BRepFace` in newer Fusion
  versions (a collection in older ones). When it gives no faces, `OffsetFacesFeature.faces` with the marker after the
  item is read instead: check that it lists only the moved faces (not their side walls), since each listed flat face
  is moved back by `distance` and copied.
- `TimelineObject.isGroup`: group objects are skipped; check that grouped features still appear as items.
- Moving `Timeline.markerPosition` once per item: the marker ends where it was, the document is not marked changed and
  the undo list is as before.
- `Profile.areaProperties().area` of every profile of an extrude whose outlines hold text or a spline, and `BRepBody.volume`
  of the target before and after the item (of the bodies in `ExtrudeFeature.bodies` for a new body). The translator
  compares the change with the outline area times the length; when a value cannot be read it refuses (extrude of text,
  X1; overlapping strokes, X4).

## Capture reader calls to watch (fillet, chamfer, shell, patterns, mirror)

These members and values were written from the API reference and never run. Run the fillet (edges, face and
tangent chain inputs, two radii), chamfer (equal, two distances, distance and angle), shell (open top, body input),
rectangular pattern (row, grid, flipped direction, suppressed copy), circular pattern and mirror designs, and read the
capture in `report.json`.

- Enum names are matched by text: `SurfaceContinuityTypes` (fillet continuity), `ChamferCornerTypes`, `ShellTypes`,
  `PatternEntityTypes`, `PatternDistanceType` (also tried as `PatternDistanceTypes`). An unreadable member gives `other` for fillet continuity and pattern
  distance type, `chamfer` for the corner type and `sharp` for the shell type; an unknown name gives `other`.
- Edge set type names are matched by text: `ConstantRadius`, `VariableRadius`, `ChordLength`, `Asymmetric` or
  `DoubleRadius` (fillet); `EqualDistance`, `TwoDistances`, `DistanceAndAngle` (chamfer). The member names
  `ChamferEdgeSet.distanceOne`, `distanceTwo`, `angle`, `isFlipped`.
- Uneven chamfers: `BRepEdge.faces` (two faces) and `SurfaceEvaluator.getNormalAtPoint` before the item (`sides`);
  with the marker after it `ChamferFeature.faces` (the chamfer faces), `adsk.core.Point3D.create`,
  `SurfaceEvaluator.getParameterAtPoint`, `getPointAtParameter`, `isParameterOnFace` and `getNormalAtParameter`
  (`cut_normals`). An edge without `cut_normals` makes the chamfer a fixed shape; check that a chamfer on a closed
  edge (a hole rim) gets two of each.
- `FilletEdgeSet.isTangentChain` (default true when unreadable) and `FilletFeature.isRollingBallCorner`.
- `BRepEdge.tangentiallyConnectedEdges` and `BRepFace.tangentiallyConnectedFaces`: whether the list includes the edge
  or face itself (the reader adds it first and drops repeats, so both work). `BRepFace.edges`.
- `ShellFeature.inputEntities` holding faces or a body, `isTangentChain`, `outsideThickness`.
- `RectangularPatternFeature.directionOne` and `directionTwo` as vectors; when absent the reader falls back to
  `directionOneEntity` and `directionTwoEntity` (sketch line, construction axis, linear edge, planar face). Check which
  one the capture used: a null `direction_one` means neither was readable. The pattern direction sign for a flipped
  pattern.
- `quantityOne`, `quantityTwo`, `quantity` as unitless model parameters; `distanceOne`, `distanceTwo` as lengths;
  `totalAngle` as an angle; `isSymmetricInDirectionOne`, `isSymmetricInDirectionTwo`, `isSymmetric`.
- `patternElements` read with the marker just after the item: `PatternElement.id`, `isSuppressed`, `transform`. The
  first element is the identity; compare each origin with the lattice step. Whether suppressed copies are listed.
- `suppressedElementsIds` as a list of integers.
- `CircularPatternFeature.axis` (construction axis, sketch line, linear edge, cylindrical face).
- `Feature.timelineObject.index` of each pattern or mirror input feature matches the item `index` in the capture.
- `MirrorFeature.patternEntityType`, `mirrorPlane` (construction plane or planar face), `isCombine`.

## Capture reader calls to watch (emboss)

These members and values were written from the API reference and never run. A member that cannot be read gives
`null`, which the translator refuses, so a wrong guess shows up in `report.json` rather than as a wrong part. Run the
Emboss tests of section 10 and read the capture in `report.json`.

- `adsk.fusion.EmbossFeature` itself: it came with the September 2025 release and the API reference marks it as
  preview, so members may change. A Fusion build without it cannot hold the step (E5).
- `EmbossFeature.profiles` with the marker just before the item: a collection of `Profile` and `SketchText` items on
  one plane. A text item is read as outlines (X1).
- `EmbossFeature.inputFaces` with the marker just before the item: a list or a collection of `BRepFace`. The reader
  accepts both and raises when it cannot list them.
- `EmbossFeature.faces` with the marker just after the item: the faces the feature made. The reader takes the flat
  face parallel to the input face that lies farthest from the sketch plane (`end_offset`, `end_area`); check that it
  is the top of a raised outline and the floor of a sunk one.
- `EmbossFeature.depth` as a `ModelParameter`, and its sign: assumed positive raises and negative sinks. The API has no
  emboss or deboss flag and `Feature.operation` is not listed for it, so the sign is the only signal. The translator
  checks the sign against the measured change of the volume and refuses when they disagree (E1, E2).
- `EmbossFeature.horizontalDistance`, `verticalDistance` and `rotationAngle` as `ModelParameter`s: the reference does
  not say in which frame they move the outline or around which point they turn. The copy needs all three to be zero
  (E3).
- `EmbossFeature.isTangentChain` and `BRepFace.tangentiallyConnectedFaces` of each input face (read as
  `tangent_faces`; whether it includes the face itself does not matter). `EmbossFeature.faces` surface kinds are read
  as `made_surfaces`. With Tangent Chain on and a fillet next to the face the copy must stop (E6).
- `BRepFace.geometry` type names `Plane`, `Cylinder` and `Cone` for the input faces, `BRepFace.body`, `BRepFace.area`
  (cm2, read as `end_area`), `SurfaceEvaluator.getNormalAtPoint` at `pointOnFace` pointing out of the body.
- `Profile.areaProperties().area` for each emboss profile (cm2, read as `areas`), and `BRepBody.volume` of the target
  at the marker before and after the item.
- `SketchText.parentSketch` for the sketch of a text item (X1).

## Capture reader calls to watch (thin extrude)

These members and values were written from the API reference and never run. A member that cannot be read gives
`null`, which the translator refuses, so a wrong guess shows up in `report.json` rather than as a wrong part. Run the
thin extrude tests above and read the capture in `report.json`.

- `ExtrudeFeature.isThinExtrude` (already read), then `ExtrudeFeature.thinExtrudeWallLocationOne` and
  `thinExtrudeWallLocationTwo`: the enum `ThinExtrudeWallLocation` (`Side1`, `Side2`, `Center`). The reader matches
  the value name; a value that matches none reads as `other` and stops the copy.
- `ExtrudeFeature.thinExtrudeWallThicknessOne` and `thinExtrudeWallThicknessTwo`: `ModelParameter`s (cm, read as mm).
  Check that the first one gives the wall in `thin_wall.thickness` and that `params["thin.thickness"]` names the
  parameter. The second only counts for an extrude that goes two ways, which is refused.
- The side of the wall is not taken from the location name (the API does not say which of side one and side two is
  the inside). `endFaces[0].area` (read as `end_area`) decides it, so check that for a thin extrude it is the face at
  the far end of the wall and has the area of the wall's cross section (T1).
- `ExtrudeFeature.profile` of an open line, and `type_name` of what it returns (`thin_wall.profile_type`): not known
  (T2).

## Capture reader calls to watch (spline outlines and sketch text)

Written from the API reference and never run. A member that cannot be read leaves the curve without samples or the text
as a marker, which the translator refuses, so a wrong guess shows up as a refusal and not as a wrong part.

- `CurveEvaluator3D.getParameterExtents` and `getPointAtParameter(parameter)` of `ProfileCurve.geometry` for a
  `NurbsCurve3D` or `EllipticalArc3D`: `(ok, low, high)` and `(ok, Point3D)`. The reader starts with 16 equal
  parameter spans (4 per knot span for a curve with many control points) and splits each until five points inside it
  are within 0.0005 mm of the chord (S1, S5).
- `NurbsCurve3D.controlPointCount` and `degree`: read only to choose how many spans to start with. A curve that does
  not give them starts with 16.
- `CurveEvaluator3D.getLengthAtParameter(from, to)` over the whole parameter range, in cm (the reader accepts a plain
  number or `(ok, length)`). The chords of the samples must add up to it within 0.1 % (or 0.01 mm); if not, the
  curve is marked `truncated` and refused. Check on a spline with a tight S bend that the length is the real curve
  length and that a normal spline is not refused by it (S1, S2).
- `CurveEvaluator3D.getTangent(parameter)`: `(ok, Vector3D)` at the first and last parameter. A failure leaves out
  `tangent_start` or `tangent_end` (S1).
- `ProfileCurve.geometry` of a free curve has no `startPoint` or `endPoint` (a `NurbsCurve3D` does not): the points
  that decide the space come from the evaluator at 0, 0.5 and 1 (S3).
- `SketchText.asCurves()`: a list of `Curve3D` (`Line3D`, `Arc3D`, `NurbsCurve3D`, ...) that trace the outlines. Called
  once per text read, no argument. Expected to leave the text and the design alone (X3).
- `SketchText.boundingBox`: a `BoundingBox3D` in sketch space (`minPoint`, `maxPoint`, cm). The reader keeps the
  reading of the curve points (sketch or model space) under which every point lies inside it (X2).
- `SketchText.parentSketch`, `Sketch.modelToSketchSpace`, `Sketch.transform` as for profiles.
- `SketchText.heightParameter` (a `ModelParameter`): its `name` is kept as `text_params` on each text record, so a size
  that drives the text height is not followed (X5). Also `Sketch.sketchTexts` and the `createdBy` of that parameter:
  `created_by.kind` should read `sketchText` with the sketch name in the report. When the name cannot be read the
  record says `text_params_unknown` and every size that reaches a parameter with an unknown maker is treated as
  reaching the text.
