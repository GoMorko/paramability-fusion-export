# Hand tests

No tool can run Fusion, so these checks are done by hand after each change to the Fusion side. Tick each one and
note the Fusion version and system.

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
      item) still gets its sizes checked: the sizes are offered and kept, and only a size that breaks a new item is
      fixed, with that item named in its reason and in `report.json` (sizes, build_failures).
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
- [ ] **Fixed shape**: a part with an emboss, and one with a variable radius fillet. Each saves as a fixed shape
      (plain CAD part) and the message after the export names that feature.
- [ ] **Y up**: a design made with the Y up preference, exported with "Y up". The plain part stands upright in
      Paramability, and the positions in `recipe.json` are Z up (a plate drawn on the ground plane has its sketch
      normal along z).
- [ ] **Speed**: a design with about 100 timeline items exports in under a minute.
- [ ] **Size choices**: a two row export in Export size choices still lands as size choices (one shape per size).


### 7.1 Sizes from parameters, checks and restore

Use a design with one body in the root and three plain user parameters read by its features (for example `wall` in
mm, `corner` in mm, `holes` as a count), one favourite and one formula parameter.

Unless a line says otherwise, the lines in this section and in sections 8 and 9 that speak of checks, probe rows,
"Trying size", shortened or raised ranges or "Keep doubtful sizes fixed" need the box "Check sizes in Fusion
(slower)" ticked. The default export (box off) is the plain one below.

- [ ] **Plain export (box off, the default).** The dialog shows the box "Check sizes in Fusion (slower)" off and no
      "Keep doubtful sizes fixed" box; ticking the first shows the second, unticking hides it. The hint under the table
      says that nothing is changed in the design. Export: no progress window shows, the timeline shows no parameter
      change and Undo has nothing new beyond what Fusion itself records. Every ticked size that a copied step reads is
      in `recipe.json` with the range of the table and its current value. `manifest.json` has `"checks": []` and the
      package holds no `checks/` folder. `report.json` has `"check_sizes": false` and no `probe`, `raised` or
      `narrowed`.
- [ ] **Plain export, loose sizes.** Tick a parameter that drives a sketch dimension or a joint. The size stays in
      `recipe.json`, the manifest `loose` list holds it with a reason that starts with the Fusion name, the result
      window shows "may be unexpected" in its "In Paramability" column, and Paramability shows a warning mark. A
      ticked parameter that no copied step reads is not a size: the message names it, and it is in the manifest
      `parameters` list.
- [ ] **Labels.** Open the plain file in Paramability: each size shows the Fusion parameter name as its label, and
      the Fusion comment as the variable's description (from the manifest `parameters` list), not as the name.

- [ ] The dialog lists the user parameters in a table, the ones the body reads ticked (favourites first), the formula
      one greyed with "formula" in the last column. OK is on once a body is picked.
- [ ] **Doubtful when it opens.** A parameter that drives a joint is unticked as soon as the dialog opens, but it can
      be ticked: its row then says "size, may be unexpected", and the box under the table gives the reason ("may give
      unexpected results: it moves a joint") when the row is clicked. Tick "Keep doubtful sizes fixed": the row says
      "fixed, moves a joint"; untick it again. A parameter that drives a sketch dimension is not marked: section 9
      covers it.
- [ ] **Doubtful sizes in the file.** Export with such a size ticked and the box off: the size is in `recipe.json`,
      the manifest `loose` list names it with the reason, the result window has a "May give unexpected results" group
      and its row says "may be unexpected", and Paramability marks the size with a warning. Export again with "Keep
      doubtful sizes fixed" ticked: the size is in the manifest `fixed` list instead and not in `recipe.json`.
- [ ] **Another body.** In a design with two bodies built from different parameters, pick the other body: the ticks
      and greyed lines change to that body's parameters. A parameter only the other body reads is not ticked. Note
      how long the dialog takes to open and to follow the pick (the add-in reads the steps of the body each time).
- [ ] **Limit.** Tick a 65th size: the box unticks itself and the line under the details box says "You can tick up
      to 64 sizes". Unticking one brings back the count line.
- [ ] **Counts.** A parameter that drives a pattern quantity is a whole number size (the form steps by 1), also when
      its role text does not say "quantity". Set it to 2.5 in the app: the recipe still builds.
- [ ] **Long name.** A user parameter with a name over 64 characters that drives a joint: the export saves, and the
      message names the size that may give unexpected results without stopping.
- [ ] **Not used.** Tick a parameter no step reads: the message after the export names it as "not used by any copied
      step".
- [ ] With only one body in the design it is picked already. With no user parameters the dialog says so (no table)
      and the export still works.
- [ ] With the box ticked: export, open in Paramability: the part is a recipe, the sizes are the ticked parameters, and
      the message after the export says how many sizes are ready. `manifest.json` inside the file lists one check per size
      (`checks/01.step` and up), each with a single size in `values`. The recipe in `recipe.json` lists no size
      that has no check, unless the message said some were not checked.
- [ ] Untick a parameter and export: that name is not a size and its number is plain in `recipe.json`.
- [ ] **Doubtful by a sketch.** Drive a sketch dimension by a ticked parameter through an angle (a point placed by
      an angle on a circle) and also an extrude distance. The export does not stop: the message after it lists that
      parameter with its reason (it moves Sketch1 along a curve), the manifest `loose` list holds it, and it stays a
      size whose extrude follows while the point keeps its place. With "Keep doubtful sizes fixed" it is in `fixed`.
- [ ] **Fixed by a failed build.** Give a ticked parameter a range that Fusion cannot build at either end or at any
      smaller step toward the current value (a fillet that only fits at the current value). The export saves, the
      parameter is listed as fixed with "Fusion cannot build the part when it is ... or ..., or any value closer to
      the current one", and the other sizes are unaffected. `report.json` (sizes, build_failures) lists the failed
      value and the values tried (`tries`).
- [ ] **One side only.** Give a ticked parameter a range comment such as `[1..400]` that Fusion cannot build above
      the current value at all, but can build below it. The parameter stays a size whose range ends at its current
      value; the check in `manifest.json` is at the bottom of the range and matches in Paramability.
- [ ] **Range shortened by a failed build.** Give a ticked parameter a range that Fusion cannot build at the top but
      can build part of the way (for example a wall thickness of 1.25 mm with the default range up to 2.5 mm, where
      a chamfer fails at 2.5). A progress window "Trying size 1 of 3: ..." shows. The parameter stays a size; the
      message after the export has a line such as "Wall thickness: the range ends at 1.87 mm, since Fusion cannot
      build the part at 2.5 mm (Chamfer1 fails).", the result window has a "Range shortened" group and its Range
      column shows the shorter range, the recipe size max is the same number, and `report.json` (sizes, narrowed)
      lists it. Open the file in Paramability: the check at the new top matches. Type a Max of 2.5 yourself and
      export again: the line says "you typed a Max of 2.5 mm". Repeat at the bottom of a range (a Min that Fusion
      cannot build): the bottom is tried for every checked size, with a rebuild only, and the range starts at the
      value that builds. Cancel during a try: nothing is saved and every parameter is back, with one message at most
      about parameters that could not be put back.
- [ ] **Rows start from the saved values.** On a design with a sketch that has two solutions (a lid sketch whose
      outline can flip), run an export with several checked sizes and the probe: the check rows and probe rows match
      what the same sizes give when set by hand from the saved values, and no row stays on the flipped solution.
      The export takes one more recompute per row (the parameters are put back before each row after the first), so a
      long run is a little slower.
- [ ] **Restore.** After each export, a cancel in the "Checking size 2 of 4" window, and a forced failure (full disk
      or a read only folder), every parameter shows its old expression, formulas included, the timeline marker is
      where it was and the design has no unsaved change beyond Fusion's own.
- [ ] **Expressions** (the translator writes `+ - * /`, `^` as `pow`, and numbers with units as mm or degrees; the
      value check refuses a formula that does not give Fusion's number, so a wrong reading shows as a fixed size).
      Try `1 in + 5 mm`, `wall + 5` in a mm design and in an inch design, `wall ^ 2` and `-wall ^ 2`. Try `floor(wall)`,
      `round(wall)` and `ceil(wall)` on a length (Fusion may apply them in cm, the app in mm): with `wall = 25 mm`,
      note the value Fusion shows for `floor(wall)`. Helper parameters: a unitless `count`, `step = count * 1 mm`,
      `wall = layers * 0.4` in mm, and a formula reading them: all export with formulas, ticked or not.
- [ ] **Marker rolled back, with sizes.** Put the marker before the last few steps (one of them uses a ticked size)
      and export. The dialog shows the marker line. The recipe holds only the steps before the marker, every size
      check matches Fusion at the marker, `report.json` has `marker` (position and count) and the capture has only
      the items before the marker. A step after the marker that would fail at a check size does not fix that size.
      After the export the marker is at the same step, parameters are back and the later steps compute as before
      when you drag the marker to the end.
- [ ] Time: note how long a design with 5 sizes and 100 timeline items takes.
- [ ] **Extra rebuilds.** With sizes that move sketches, the progress window shows "Checking size n of m" and then
      "Trying size n of m". Cancel in the second window: the message says the export is cancelled, parameters are back
      and the marker is at the end.

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
- [ ] Round the inside edges of the shell: the message lists the sizes written before the round as fixed, with the
      round's name in the reason.
- [ ] Turn the design to Y up and repeat the first check.
- [ ] Mirror the rounded corners of one side: the mirrored corners stay round at every height, and no height size
      is fixed.
- [ ] Add a row of three posts (a rectangular pattern of an extrude, spacing `hole_pitch_mm`), then round the top
      edge of the last post: the round stays on that post when the spacing changes. Make the count a formula of a
      ticked size: that size is fixed, with "picks a copy made by" in the reason.
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
- [ ] **Long names.** A name over about 26 characters is broken after an underscore into two lines inside its cell and
      stays readable. If a break looks wrong at the real column width, note the width (the break is made by the add-in
      with `<br>` in `formattedText`).
- [ ] **Row click.** Click a row (not its tick): the box under the table shows the name, the comment, and for a
      formula the formula with "Now ...", for a greyed row the reason. If the box does not follow the click, note
      it: it then only follows ticks and typed ranges.
- [ ] Tick or untick a row: its Min and Max open or grey out, "In Paramability" says "size" or "stays 3 mm", and the
      count line says "N of 64 sizes ticked. Every parameter also comes along as a variable."
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
- [ ] The Design up direction menu is under the count line.
- [ ] **Early warning.** Pick a body whose steps hold one the add-in cannot copy (for example a sweep, a loft or an
      emboss). Right under the body picker a box shows "Copy stops at Sweep1 (sweep)." in bold, the reason in short,
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
      saved line, a table of sizes (name, range, "matches Fusion", "not checked", "may be unexpected", "kept fixed"
      or "not used"; a plain export says "size" instead of "matches Fusion" and heads the column "In Paramability"), a "Stays fixed" group and a "May give unexpected results" group with each reason, and the line
      "All N parameters come along as variables ...". Only a Close button shows. Pull a size so that Fusion cannot
      build it at any other value (a fillet that only fits now): its row says "kept fixed".
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
      may give unexpected results when ticked. Then join it to a face whose place depends on `FilterBox_height_mm`:
      after the checks that size may give unexpected results with "moves Tray in the assembly" (fixed with "Keep
      doubtful sizes fixed").
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
      of `Box`. The first exports (a `Box` parameter that moves it is fixed with the sketch reason); the second is a
      fixed shape naming the extrude.
- [ ] For a component body, the dialog table follows the component's own parameters, and "Tick what the body uses"
      ticks only what the component reads.
- [ ] **C9b Sketch of another component.** An extrude in `Tray` that uses a sketch of `Box` (moved and turned), and a
      mirror in `Tray` across a plane of the root. Export: the extrude is copied where Fusion shows it, with a note
      that names the sketch, and the mirror is copied. A ticked size that drives a dimension of that `Box` sketch is
      fixed with "changes the sketch". The report shows `native_frame`, `placement.checked_points` 3 and
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
      Note the export time against an export of the same design before this stage.
- [ ] **K2 Pipe offset.** A circle placed by `pipe_offset_mm` from the box edge, diameter `pipe_d_mm` as a sketch
      dimension, cut through. Then a hole feature on a sketch point at `pipe_offset_mm`. Both follow both sizes and
      the box width.
- [ ] **K3 Offset plane.** A sketch on a construction plane offset by `FilterBox_height_mm`, a boss extruded from it.
      The boss moves with the height. Then make an extrude reach "to" that plane: the height is fixed with the
      construction plane reason.
- [ ] **K4 Sketch on a face.** A sketch on the top face of the base, a lid lip extruded from it with projected edges.
      The lip follows the height and the width.
- [ ] **K5 What stays fixed.** A point placed by an angle parameter on a circle (reason: along a curve); a line that
      crosses the outline only above some width (reason: a different outline); a plane at an angle driven by a
      parameter (reason: turns the plane). Each is fixed with its reason; the other sizes work.
- [ ] **K6 Constraints.** A slot with equal and symmetric constraints, a rectangle with sketch fillets of radius
      `corner_mm`, a hole diameter `sqrt(area_mm2)`. All follow; the fillet arcs keep their radius.
- [ ] **K7 Restore and cancel.** Cancel during "Trying size 2 of 6": parameters are back and the marker is at the
      end. A range comment that Fusion cannot build at the bottom of the range: the report `probe.dropped` lists the
      state, the size stays a size and the other sizes work.
- [ ] **K8 In a component.** K1 built inside a turned component `Tray`: the box lands where Fusion shows it and
      resizes in place.
- [ ] **K9 Report.** Send the K1 report. It pins token stability (the curves are found again in every state), the
      first read against the capture (a sketch that differs is left to the measured check), `restore_gap_mm` (should
      be 0 or tiny) and the column checks (`motion.dropped`).

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
  - `commandInputs.addTableCommandInput(id, "", 6, "1:6:2:2:2:4")` with cells added by `addCommandInput(input, row,
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
  an unreadable answer counts as "nothing pending"); `BRepBody.parentComponent` of a
  proxy giving the native component whose sketches are read at every check; `Occurrence.transform2` and the occurrence
  path read again after each parameter change (`placement.read_frame`); the capture members of "Bodies inside
  components" in `docs/capture-format.md`.
- The size probe (`lib/fusion_reader/probe_state.py`, `lib/probe/`, `lib/export_plan/probe_flow.py`), none of it run
  yet. Each member below is read at every state; a missing one only leaves that sketch unread (the measured check of
  hand test 7.1 then decides) and shows in `probe.states` of `report.json`:
  - `Sketch.entityToken`, `Sketch.profiles` per state (the profiles at the timeline end must equal the ones the
    steps used: the first read is compared with the capture within 1e-4 mm), `Sketch.referencePlane` with
    `.entityToken` and `objectType`.
  - `ProfileCurve.sketchEntity.entityToken`: the same curve must give the same token after every recompute (K9).
  - `SketchPoint` and `SketchLine` `.entityToken`, `.parentSketch`, `.worldGeometry`; the hole point tokens
    (`SketchPointsHolePositionDefinition.sketchPoints` items) and the revolve axis line token.
  - `ConstructionPlane.entityToken` and `ConstructionAxis.entityToken` (a step that reaches one fixes the sizes behind
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
    capture for each dimension (before this check, a real design gave `other` with a role like "Linear Dimension-2").
- `Design.fusionUnitsManager.defaultLengthUnits` as the unit of a bare number in a length formula (falls back to mm).
- `Component.modelParameters` read by `list_model_parameters`; `Sketch.transform.asArray()`, `Sketch.sketchPoints`
  with `worldGeometry`, `Sketch.sketchCurves` with `worldGeometry` (`radius`, `center`, `startPoint`, `endPoint`)
  read in `lib/fusion_reader/sketches.py`, and `Component.sketches` with `Sketch.name`. A missing member only
  leaves a gap in the numbers: a sketch that moves on a missing member is then not seen, so check hand test 7.1.
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
- `CurveEvaluator3D.getParameterExtents` and `getPointAtParameter` (arc middle point, 200 samples of free curves, edge
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
