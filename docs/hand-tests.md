# Hand tests

No tool can run Fusion, so these checks are done by hand after each change to the Fusion side. Tick each one and
note the Fusion version and system.

## 1. Install

- [ ] Follow the README install steps on macOS (and Windows if you have it). Confirm each step matches the current
      Fusion dialog: Utilities tab, Scripts and Add-Ins, plus icon, "Script or add-in from device", Run, "Run on
      Startup". The steps came from Autodesk's help pages, not from a Fusion window. Fix the README if a label differs.
- [ ] The button "Export for Paramability" shows in the Utilities tab, in the panel "Paramability", with an icon.
- [ ] Stop the add-in in the Add-Ins dialog: the button goes away and the panel is removed.

## 2. Sizes and parameter restore

Use a design with two favourite user parameters (for example `width` in mm and `angle` in deg).

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
- [ ] With rows of values, a body in a component exports as usual. With one row and "Export as a recipe" on, the
      file is a plain part with the note "This part sits inside a component, so it was exported as a fixed shape."
      A recipe needs the body in the root component for now.
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

## 7. Recipe export (one size, "Export as a recipe" on)

The current Paramability opens a recipe package as a plain part and shows "This package has editable steps that this
version cannot use yet." It does not rebuild the steps or compare them with the Fusion part yet. So today each test
checks the file, not the rebuilt part:

- the saved message in Fusion says how many steps were copied, or names the step that stopped the copy;
- in the app repo, `npm run recipe:check -- <file>.paramability` prints `ok` for a recipe package;
- the steps listed in `recipe.json` (a zip entry) match the design, and `report.json` holds the capture.

When a design surprises you, send `report.json`: its `capture` becomes a test fixture. The calls and enum names these
tests pin are in the "Capture reader calls to watch" parts below. Once Paramability rebuilds recipes, "Matches" below
means the part it builds agrees with the Fusion part.

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
- [ ] **Several sizes**: a two row export still lands as size choices (one shape per size), and the "Export as a
      recipe" box is hidden while the sizes box holds two or more rows.
- [ ] **Single size with values**: one row that changes a parameter. The recipe and the STEP both hold the changed
      value, and the parameter is back to its old value after the export.

## Fusion calls to watch

These were written from the API reference and never run:

- `BRepBody.copyToComponent` into a new occurrence (hand test 3).
- Deleting the temporary occurrence and the timeline items the copy adds, by entity token (hand test 3).
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
  `PatternEntityTypes`, `PatternDistanceTypes`. An unreadable member gives `other` for fillet continuity and pattern
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
