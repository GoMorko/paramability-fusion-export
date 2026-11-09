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
- [ ] Watch these calls: expressions are written as text such as `40 mm`. If your Fusion uses a comma as the decimal
      mark, check that `12.5` rows still set the right number.
- [ ] A user parameter in an unusual unit (for example mm/s) is listed greyed out as "not supported" with the reason
      in its tooltip, and cannot be ticked.
- [ ] A formula parameter (for example `depth = width / 2`) is greyed out with "(formula)" and a tooltip.

## 3. Several bodies in the root

The add-in exports the picked body alone. The choice is the constant `MULTI_BODY_ROUTE` in
`ParamabilityExport/lib/fusion_reader/step_export.py`.

- [ ] A root with three bodies, pick one: each STEP in the file holds only that body.
- [ ] The design timeline has no leftover items after the export (the temporary copy is removed).
- [ ] If the copy route adds items to the timeline, fails, or the STEP holds more than the picked body, set
      `MULTI_BODY_ROUTE = ROUTE_ASK_DESIGNER`. The dialog then asks the designer to hide or move the other bodies.
- [ ] A body inside a child component or occurrence can be picked in the viewport, OK turns active, and the STEP
      holds the body where it sits in the assembly (not moved to the component origin).
- [ ] With Export size choices, a body in a component exports as usual. With Export for Paramability it is a recipe
      with sizes (section 8).
- [ ] A body picked after its parameter changed (second row) still lands in the right place (the token lookup keeps
      the occurrence proxy).
- [ ] Roll the timeline marker back and click OK: the export stops with "Move the timeline marker to the end", and no
      feature of the design is deleted.

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

- the saved message in Fusion says how many steps were copied and how many sizes are ready, or names the step that
  stopped the copy;
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
- [ ] **Marker and document**: after each export the timeline marker is at the end, the design is unchanged, and
      Fusion's undo list and "unsaved changes" mark are as before (or, if moving the marker marks the document
      changed, note it). Cancel, and a forced error during the read, leave the marker at the end and the parameters
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

- [ ] The dialog lists the user parameters in a table, the ones the body reads ticked (favourites first), the formula
      one greyed with "formula" in the last column. OK is on once a body is picked.
- [ ] **Greyed when it opens.** A parameter that drives a sketch dimension is unticked and greyed out as soon as the
      dialog opens, with "fixed, changes a sketch" in its row and the full reason in the box under the table when the
      row is clicked. It stays that way for parameters that are not ticked by default.
- [ ] **Another body.** In a design with two bodies built from different parameters, pick the other body: the ticks
      and greyed lines change to that body's parameters. A parameter only the other body reads is not ticked. Note
      how long the dialog takes to open and to follow the pick (the add-in reads the steps of the body each time).
- [ ] **Limit.** Tick a 65th size: the box unticks itself and the line under the details box says "You can tick up
      to 64 sizes". Unticking one brings back the count line.
- [ ] **Counts.** A parameter that drives a pattern quantity is a whole number size (the form steps by 1), also when
      its role text does not say "quantity". Set it to 2.5 in the app: the recipe still builds.
- [ ] **Long name.** A user parameter with a name over 64 characters that drives a sketch dimension: the export
      saves, and the message names the fixed size without stopping.
- [ ] **Not used.** Tick a parameter no step reads: the message after the export names it as "not used by any copied
      step".
- [ ] With only one body in the design it is picked already. With no user parameters the dialog says so (no table)
      and the export still works.
- [ ] Export, open in Paramability: the part is a recipe, the sizes are the ticked parameters, and the message after
      the export says how many sizes are ready. `manifest.json` inside the file lists one check per size
      (`checks/01.step` and up), each with a single size in `values`. The recipe in `recipe.json` lists no size
      that has no check, unless the message said some were not checked.
- [ ] Untick a parameter and export: that name is not a size and its number is plain in `recipe.json`.
- [ ] **Fixed by a sketch.** Drive a sketch dimension by a ticked parameter. The export does not stop: the message
      after it lists that parameter with "it changes Sketch1" (the sketch name), the manifest `fixed` list holds it,
      and it is not a size. A parameter that only drives an extrude distance stays a size.
- [ ] **Fixed by a failed build.** Give a ticked parameter a range comment such as `[1..400]` that Fusion cannot
      build at the top (a fillet larger than the part). The export saves, the parameter is listed as fixed with
      "Fusion cannot build the part when it is ...", and the other sizes are unaffected.
- [ ] **Restore.** After each export, a cancel in the "Checking size 2 of 4" window, and a forced failure (full disk
      or a read only folder), every parameter shows its old expression, formulas included, the timeline marker is
      at the end and the design has no unsaved change beyond Fusion's own.
- [ ] **Expressions** (the translator writes `+ - * /`, `^` as `pow`, and numbers with units as mm or degrees; the
      value check refuses a formula that does not give Fusion's number, so a wrong reading shows as a fixed size).
      Try `1 in + 5 mm`, `wall + 5` in a mm design and in an inch design, `wall ^ 2` and `-wall ^ 2`. Try `floor(wall)`,
      `round(wall)` and `ceil(wall)` on a length (Fusion may apply them in cm, the app in mm): with `wall = 25 mm`,
      note the value Fusion shows for `floor(wall)`. Helper parameters: a unitless `count`, `step = count * 1 mm`,
      `wall = layers * 0.4` in mm, and a formula reading them: all export with formulas, ticked or not.
- [ ] The marker is rolled back: the export stops with "Move the timeline marker to the end".
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
- [ ] Add a boss extruded "from" the top face: the message after the export lists the count and the cube width as
      fixed, with "starts from a face" in the reason.
- [ ] Round the inside edges of the shell: the message lists the sizes written before the round as fixed, with the
      round's name in the reason.
- [ ] Turn the design to Y up and repeat the first check.
- [ ] Mirror the rounded corners of one side: the height sizes are listed as fixed ("placed one by one").

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
- [ ] Click OK: the progress window shows as before, then the result window "Saved for Paramability" opens with the
      saved line, a table of sizes (name, range, "matches Fusion", "not checked", "kept fixed" or "not used"), a
      "Stays fixed" group with each reason, and the line "All N parameters come along as variables ...". Only a Close
      button shows. Pull a size to fail its check (a range that breaks a fillet): its row says "kept fixed".
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
- [ ] **C4 Joints.** `Tray` joined to `Box` with an offset `gap_mm`: `gap_mm` is greyed with a joint reason. Then join
      it to a face whose place depends on `FilterBox_height_mm`: after the checks that size is fixed with "moves Tray
      in the assembly".
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
- [ ] **C10 Many components.** A design with several components made one after the other (each with sketches,
      construction planes and extrudes), the picked one in the middle, and one moved away from the origin. Export:
      the occurrences and construction planes of the other components are "skipped" in the report, never the refusal.
      The report items of the picked component's own extrudes, chamfers and mirrors carry no `foreign`, and its
      outlines on a standing sketch (on a side plane, not the ground) have real 2D points, not all `y` = 0.
- [ ] **C11 Offset faces.** In a component: a box, then Press Pull its top face up by `gap_mm`, then a second box
      whose side face is pulled in by 1 mm. Export: two recipes whose offsets became extrudes (join and cut), and a
      changed `gap_mm` moves the top. The report shows `faces_after` and `sides: "square"`. A pulled face with a
      fillet next to it, or a curved face, gives a fixed shape that names the offset.

## Fusion calls to watch

These were written from the API reference and never run:

- `BRepBody.copyToComponent` into a new occurrence (hand test 3).
- Deleting the temporary occurrence and the timeline items the copy adds: only the items after the first `count`
  items, and only entities that are not equal (`==`) to one of the entities read before the copy (hand test 3). Check
  that `==` between two wrappers of one Fusion entity is true, here and in the capture (`parentComponent == ctx.
  component`, `same_entity` in `lib/fusion_reader/read_geometry.py`). If it is false, the capture marks every item
  as outside the target's component and the placement of a nested body is refused.
- `Timeline.markerPosition` equal to `Timeline.count` when the marker is at the end.
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
- The component export flow (`commands/ExportForParamability/export_flow.py`): `Design.snapshots` and
  `Snapshots.hasPendingSnapshot` (asked when the dialog opens, before the capture moves the marker, and again at OK;
  an unreadable answer counts as "nothing pending"); `BRepBody.parentComponent` of a
  proxy giving the native component whose sketches are read at every check; `Occurrence.transform2` and the occurrence
  path read again after each parameter change (`placement.read_frame`); the capture members of "Bodies inside
  components" in `docs/capture-format.md`.
- `Design.fusionUnitsManager.defaultLengthUnits` as the unit of a bare number in a length formula (falls back to mm).
- `Component.modelParameters` read by `list_model_parameters`; `Sketch.transform.asArray()`, `Sketch.sketchPoints`
  with `worldGeometry`, `Sketch.sketchCurves` with `worldGeometry` (`radius`, `center`, `startPoint`, `endPoint`)
  read in `lib/fusion_reader/sketches.py`, and `Component.sketches` with `Sketch.name`. A missing member only
  leaves a gap in the numbers: a sketch that moves on a missing member is then not seen, so check hand test 7.1.
- Scoping to the picked body: `SketchDimension.parentSketch` with `Sketch.name` (read as `created_by.sketch`), and
  the name of a feature (`created_by.name`) equal to its timeline item name. A name that does not match leaves the
  parameter in, so a mismatch shows as a parameter that other bodies' steps make ticked.
- Reading the capture while the dialog is open (`lib/fusion_ui/` and `commands/ExportForParamability/entry.py`): the
  timeline marker moves in the `commandCreated` and `inputChanged` events and comes back to the end. Also
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
- `HoleFeature.thread.isModeled`, `holePositionDefinition.sketchPoints[i].worldGeometry`, `position`, `direction`
  (into the material or out), `tipAngle` for a flat drill point, `participantBodies`, `sideFaces`, `endFaces`.
- `CombineFeature.targetBody`, `toolBodies`, `isKeepToolBodies`; `ThreadFeature.isModeled`.
- `participantBodies` on extrude and revolve (may be unreadable; then the list is empty).
- `Design.findEntityByToken` for the picked body at each marker position, with a name fallback in the root component.
- `TimelineObject.isGroup`: group objects are skipped; check that grouped features still appear as items.
- Moving `Timeline.markerPosition` once per item: the marker ends at the end, the document is not marked changed and
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
