# Hand tests

No tool can run Fusion, so these checks are done by hand after each change to the Fusion side. Tick each one and
note the Fusion version and system.

## Check first in this version

What 0.6.0 to 0.8.0 added, and what this version adds, in this order. Each id is described in the section named,
except U1, L1 to L15, F1, F2 and SP1 to SP4, which are described here.

- [ ] SP1, the marker roll past other components. Make component Cup: a sketch with a 60 mm square whose side is the
      user parameter `Width`, extruded 40 mm. In that sketch project an edge of a body of an earlier component (once
      with the projection link on, once with it off, so the sketch may hold a reference Fusion gives no source for). After the Cup steps,
      add component Rack with about 100 steps (a pattern of 200 holes, fillets and chamfers on its own body). Tick
      `Width` and export the Cup. Expect: `probe.timeline` has `rolled: true` and `items` equal to the last Cup step
      plus one, not the full count; `timing.probe.tries_seconds` per try is about the time of the Cup steps alone.
- [ ] SP2, one change per try. In SP1, add a second user parameter `Height` for the extrude and a fillet on the top
      edges whose radius is 5 mm; give `Width` a range down to 8 mm, so the fillet fails at the low end. Export with
      both ticked. Expect: the tries that fail are still listed in `probe.dropped` with the fillet as the failing
      step and the range of `Width` is cut, as with 0.10.8; `timing.probe.rebuild` is about half of the 0.10.8 value
      or less; after the export the design shows the values it had, with no step in error.
- [ ] SP3, a try that breaks the design. Split a box body with an offset construction plane (offset from the top face
      by the user parameter `Cut`) and Remove the upper piece. Give `Cut` a range that moves the plane above the box,
      so the split makes one piece and the Remove step loses its input. Export the box with `Cut` ticked. Expect: when
      the Remove step stays in error with the values back, `probe.stopped` names the try and `Remove`, no try runs
      after it, the result window says the tries stopped early, and if the step is still in error at the end it says
      the design is changed and to use Undo. Edit, Undo then brings the design back.
- [ ] SP4, memory and Undo. On the SP1 design with SP2's sizes, watch Fusion in Activity Monitor (Memory column)
      before, during and after the export, then use Edit, Undo once. Note the peak, the value after the export and
      after Undo, and whether Undo lists the export as one step. Repeat with 0.10.8 for comparison.
- [ ] SB1, Split Body by a plane. Model a cup or a box with a shell and a fillet, then Split Body with the YZ origin
      plane and Remove the other half (a second Split Body with the XZ plane of the half gives a quarter). Export the
      piece that the split made (a new body, not the one that kept its name), and once more the piece that kept its
      name. Expect: the steps before the split are copied, the split is a tool step (`toolBody`, combine `cut`) with
      one extrude of a large square on the plane, facing away from the piece, and in Paramability the copy matches
      the STEP. The capture item has `data.tool` with `kind: "plane"`, `data.bodies` with one body and `data.pieces`
      with both pieces, their boxes and volumes adding up to the body's; the steps before the split have
      `body_states` for the body they build. Repeat with a split by a construction plane
      offset from a face by a user parameter: changing the parameter in Paramability moves the cut. A fillet after the
      split on the other half as well (the fillet lists both bodies) stops the copy at the split and names the fillet.
      Seen with 0.10.5 (Fusion 2706.1.17, 2026-11-12): both pieces of the origin plane split copy and match. The width
      range starts at 26.56, not 25, and that is real: the sketch keeps its right edge fixed, so at 25 the box lies
      on one side of the plane and Fusion does not split it. The offset plane split marked its offset size; later
      versions follow it (Fusion gives that plane a second parameter, `ExtraOffset`, at 0 mm). The fillet across both
      halves stopped the copy as expected.
- [ ] SB2, Split Body by another body. Split a plate with a cylinder body (kept), remove the piece inside the
      cylinder, and export the plate; then export the inside piece of a second split. Expect: `data.tool` has
      `kind: "body"` and `solid: true`, each piece has `inside` (false for the plate, true for the core; check it
      against the model), and the copy is a cut by the cylinder for the plate and an intersect for the core. A split
      along a curved face of a body (a cylinder side, not extended) stops with "curved surface".
      Seen with 0.10.5 (Fusion 2706.1.17, 2026-11-12): `inside` was missing, so the plate stopped; later versions read
      it. The "core" export held the cylinder tool body, not the piece inside it: export the inside piece again.
- [ ] DR1, Draft. On a box extruded from a sketch on the XY plane, draft two side faces by 3 degrees with the XY
      plane as the fixed plane, the angle from a user parameter. Export. Expect: a `draft` step with two `near` points
      on the faces, `neutral` on the plane, and an angle that follows the parameter; in Paramability the walls lean
      the same way as in Fusion (narrower at the top when the volume went down). Repeat with the direction flipped
      and with a negative angle: the copy still leans like Fusion. A draft with "Symmetric" whose faces cross the
      plane, or with two different angles, is left out with its reason.
      Seen with 0.10.5 (Fusion 2706.1.17, 2026-11-12): both directions copy and match, but the angle size was marked
      (its default range starts at 0 degrees); later versions follow it with the range cut to 0.01 to 29.98. A draft
      of 35 degrees is left out with "Drafts of 30 degrees or more are not copied." Negative and two angle drafts are
      still to check.
- [ ] SB3, a split part inside a component. Put the cup of SB1 in a component inside another component, join a
      second body to it with a Combine before the splits (a sweep or an extrude with a draft), split it with the root's
      YZ and XZ origin planes, and after the splits add a symmetric cut "through all" and a mirror of the body across
      a root origin plane. Export the quarter. Expect: the split planes and the mirror plane have `assembly: true` and
      a `ref` (not `foreign`), the symmetric cut has `symmetric` null and `side_one` with `kind: "throughAll"`, and
      the steps that made the Combine's tool body have `body_states` for that body. Repeat with a cut "through all"
      to one side with a taper of -5 degrees: it is copied as a tapered cut.
- [ ] SW9, a sweep whose settings Fusion does not give. Sweep a small closed sketch profile along the closed loop of
      edges of a box's top face, once as "Single path" and once as "Path + Guide Surface" with the top face as the
      guide. Export each. Expect: the single path sweep has `orientation`, `taper_deg` and `twist_deg`; for the other,
      the ones that are null are listed in `data.unread` with Fusion's answer, and the gap reason names them.
- [ ] LF3, a loft section of edges. Loft from a closed loop of a body's edges (picked as edges, not a face) to a sketch
      profile above it. Export. Expect: the section shows `kind: "other"` with `items` naming what Fusion gave
      (`BRepEdge` or another type) and `count`.
- [ ] AS1, the steps after a stop. Extrude a box, split it with the curved face of a cylinder body (not extended)
      and remove the outer piece (this stops the copy), then add a coil joined to the box. Export the box. Expect: a
      fixed shape with the split in `refusal`, `report.json` `after_stop` with `steps` naming the split and the coil,
      and a second note "Not copied either: Coil1".
- [ ] U1, faster tries (0.9.1, experimental). Use a design with a body in one component and two or more other
      components the body does not use (no joints), with a ticked size that moves a sketch. Suppress one step of an
      unused component by hand first. Export for Paramability twice, once with "Faster tries" off and once with it
      on, to two files. Expect: the two files hold the same recipe and sizes (compare `recipe.json` and `manifest.json`);
      with the box on, the steps of the unused components show as suppressed in the timeline while the tries run, and
      `report.json` has `probe.timeline.suppressed` with `on: true` and the number of steps; with it off, `on: false`
      and `asked: false`. Compare `try_seconds` of the two files. After each export the timeline looks as before: the
      same steps in the same order, none suppressed that were not before, the step you suppressed by hand still
      suppressed, the marker where it was, parameters back. Export again with the box on and press Cancel during the
      tries: every step is back on (the hand suppressed one still off), the marker and parameters are back. Note
      whether Undo or the "unsaved changes" mark show anything new. A design with a joint gives `on: false` with a
      reason and suppresses nothing.
- [ ] L1, a step in the middle of the timeline that cannot be copied. In a part, add a coil in the middle
      of the timeline (a join, between two extrudes). Export for Paramability. Expect: the export finishes with a
      recipe; the result window has a "Left out" list with the coil and a reason, and a line that says
      Paramability keeps the original shape and an unfinished copy; the package holds `gaps.json` and a
      `manifest.json` of `version` 2 with `gaps`; `report.json` has `gaps`, and the item has the verdict `leftOut`
      with `gap` (the gap id). In `gaps.json` the gap has `after` (the step written before it), `before`, `list`
      null, `bodyBefore` and `bodyAfter` (the box and volume of the part around the step, in the coordinates of the
      recipe: compare the box with the part in Paramability), a `data` record with the step's Fusion data (empty
      for a coil: the reader has none) and `toRecipe` (the identity, or the move of the part in the
      assembly). The same design without the coil gives a `manifest.json` of `version` 1 and no `gaps.json`.
- [ ] L2, a round on the edges of the left out step. After the coil of L1, add a fillet on edges that the coil
      made. Export. Expect: the fillet is left out too, its reason names the coil ("It picks faces of Coil1, which
      is missing from the copy."), its gap has `dependsOn` with the coil's gap id, and `report.json` has `reach` with
      `read: true`, the coil's index in `gaps` (the fillet's is not there) and the fillet's index in `makers` with the
      coil's index in its list.
- [ ] L3, a round on other edges after the left out step. After the coil of L1, add a fillet on edges of an earlier
      extrude that the coil did not touch. Export. Expect: the fillet is copied (not left out), `reach.makers` lists
      only the extrude for it, and in Paramability the copy has the round on the same edges. This test and
      L2 decide whether `Feature.faces` gives the faces a step made for each feature type ("Reach" in the not
      verified table of `docs/capture-format.md`). Where `reach.read` is false, `reach.error` says why; every later step that picks edges or faces is then left out.
- [ ] L4, a first body that cannot be copied. Make a part whose first body comes from a step the add-in cannot copy
      (a coil as the first step). Export. Expect: the export stops as before: a fixed shape, the message
      names the step, no `gaps.json`, a `manifest.json` of `version` 1.
- [ ] L5, a Combine whose tool has a coil. Make a Combine (cut) whose tool body was made with a coil. Export.
      Expect: the Combine is one left out step ("The tool body Body2 cannot be copied: Coil1 (coil) ..."), the rest
      of the part is copied, and the gap's `after` and `before` are the steps around the Combine. Then add a fillet
      on an edge the cut made (an edge of a face of the tool) and export again: the fillet is left out too and
      `reach.makers` lists the Combine's index for it.
- [ ] L6, a size used only by the left out step. Give the coil of L1 a size from a user parameter that no
      other step reads, tick it and export. Expect: the result window lists it as "may give unexpected results" with a
      reason that says Fusion uses it only in that step and it changes nothing in the copy yet; the gap lists it in
      `sizes` and `looseSizes`. A parameter that an extrude reads too stays a plain size and is in `sizes` of the gap
      only. In Paramability, change that size on the form: the copy does not change.
- [ ] L7, a file with several bodies, one of them with a left out step. Export two bodies, one as in L1. Expect: a
      `manifest.json` of `version` 2 where only that part has `gaps` (`parts/01/gaps.json`), the other part is as
      before, and the result window lists the left out step with the part name first.
- [ ] L8, more than 16 steps left out. A design with 17 steps of a type that cannot be copied after its first body
      stops the copy with the reason "More than 16 steps of this part cannot be copied."
- [ ] L9 to L13, in Paramability (a build that reads version 2 packages), with the files of L1, L2 and L5. L9: the
      original shape shows, the card says how many steps are missing, the tip names the steps and reasons, and
      Editable copy shows the unfinished copy. L10: with assistant mode off there is no assistant text in the
      message or the card; with it on, a second message says an AI assistant can add the missing steps. L11: ask the
      assistant to fill the gaps: it reads them, adds the steps, the line goes away when the copy matches, then
      switch to Editable copy and change a size on the form. L12: Undo the assistant's last edit and the old copy and
      line come back; save, close and reopen and the line, the tip and the assistant's read still work. L13: open the
      file in a build without version 2 support: it says the file needs a newer Paramability.
- [ ] L14, a moved body before a round. After the first extrude, add a Move of the body that the add-in cannot copy
      (a free move with a turn about a tilted axis), then a fillet on an edge of that extrude. Export. Expect: the
      Move and the fillet are both left out, and in `report.json` the fillet's entry in `reach.makers` lists the
      Move's index. Note in the result whether `Feature.faces` of the Move was empty. Do the same with a draft in place
      of the Move.
- [ ] L15, a split of the part in the middle of the timeline. After the first extrude, split the body in two (Split
      Body) and add a fillet after it. Export. Expect: the export stops with a fixed shape and a message that names
      the split; no `gaps.json`.

- [ ] F1, an extrude of a flat face. Sketch a circle of 10 mm on the XY plane and extrude it 20 mm as a new body, with
      the distance set by a user parameter `post_mm`. Extrude its top face 2 mm (join) with a taper of -25 degrees,
      and its bottom face the same way. Make a box around it and Combine (cut) the post body from the box. Tick
      `post_mm` and export. Expect: the Combine is translated, `post_mm` is a free size without a warning, and in
      Paramability both face extrudes move with the post when `post_mm` changes, staying tapered. Then add a round
      on the top edge of the post before the top face extrude and export again: that face is copied as measured and
      `post_mm` is marked "may give unexpected results". In `report.json`, each face extrude has a profile with
      `"face": true`, a `frame` whose `z` points out of the post, closed `loops`, and `made_by` naming the post
      extrude with `which` `start` or `end` (the stub says the start faces of a symmetric extrude are on its positive
      side). Watch the calls listed under "Face outlines" in "Capture reader calls to watch (extrude, revolve, hole,
      combine, thread, sketch profiles)".
- [ ] F2, a pattern of a Combine with its tool steps. In the F1 design (without the round), add a rectangular pattern
      of features whose sources are the post extrude, both face extrudes and the Combine: count from a user parameter
      `posts` (5), set to both sides, distance type extent from `row_mm / 2`. Tick `posts`, `row_mm` and `post_mm` and
      export. Expect: a recipe, the pattern written as two patterns that repeat the Combine's tool step, and in
      Paramability the row of holes follows `posts` and `row_mm`. Then take one face extrude out of the sources and
      export again: the pattern stops the copy with a reason that names the Combine and the tool body.
- [ ] B1 to B12, tool bodies: a Combine whose tool has rounds, chamfers or cuts, Copy Paste Body, Move, patterns and
      mirrors of bodies, and an intersect of several tools: section "Tool bodies". B6 (does the Combine take the new
      copies when a count changes) and B7 (what an intersect of several tools keeps) answer questions only Fusion can.
- [ ] Export the bracket and the box once with this version and send the two `.paramability` files. Nothing needs
      checking by eye: each file holds a `derived` record in its `report.json` that says how well reading the sketch
      dimensions agrees with what the tries measured ("Derived values" in `docs/capture-format.md`, section 6).
- [ ] D1 and D5 to D13, the sketch graph in the capture, the marker held early during the tries, the new first tries
      near the value, the progress window text and sketch dimensions in `dependents`: section 12 (the calls are under
      "Sketch graph, marker roll and progress window" in "Fusion calls to watch").
- [ ] K27, a flat face used as an outline (an extrude from a face, an emboss kept to its face) is read before its
      step at every try: section 9 (the calls are under "Sketch graph, marker roll and progress window").
- [ ] K26, a sketch that flips to its other solution during the tries is put back before the next try: section 9
      (the calls are under "Sketch graph, marker roll and progress window").
- [ ] K25, an extrude that reaches to a face or plane no earlier extrude places (a cut's side wall, a plane on it):
      section 9.
- [ ] K24, sketches and extrude reaches on construction planes built on the part (offset from a face, a chain of
      planes, an offset that is a size): section 9.
- [ ] K23, a size whose own try changes a sketch outline keeps the range below that value: section 9.
- [ ] K18 to K21, a sketch left on its other solution after a try that does not rebuild, a projected curve that
      Fusion names again, slot ends rounded by half the slot width, and rounds and chamfers on pattern copies that
      follow the count: section 9.
- [ ] Symmetric patterns: section "Symmetric patterns" under "Capture reader calls to watch (fillet, chamfer, shell,
      patterns, mirror)".
- [ ] K16 and K17, an angle size that moves a bracket's points with sines and cosines, and a slot cut through all
      whose rounds follow: section 9.
- [ ] K12 to K15, a size whose far values do not rebuild is measured nearer, a curved size marks only itself, the
      tries of other parameters compare with the design as it is before them, and a revolve axis that cannot be
      copied says what it is: section 9.
- [ ] Compact export window and result window: section 7.2 ("The export window has no empty gaps", "Early warning",
      "Show in timeline", the result window) and the export pipeline entry under "Fusion calls to watch".
- [ ] SW1 to SW20 and LF1 to LF6, sweeps and lofts (0.9.2; SW15 to SW20 and LF6 0.10.0): section 13 (the calls are under "Capture reader calls to watch
      (sweep and loft)").
- [ ] V1, a body that reads a parameter only through formulas: section 7.2.
- [ ] E1 to E7, Emboss on a flat face: section 10.
- [ ] T1 to T5, thin walled extrudes of one closed outline (T5 is `%` with a negative left side): section "Thin
      extrudes".
- [ ] S1 to S5 and X1 onward, spline outlines and sketch text: section 11.
- [ ] K10 and K11, a parameter that reaches the part through another component, and the "Also change this part"
      list: section 9.
- [ ] R1 to R7, references to places of another component: section 8.1 (the reads are under "Fusion calls to watch").
- [ ] M1 to M6, measuring those places at other sizes: section 8.2.
- [ ] Combine with a tool of several steps: section 7, "Combine with a tool of several steps".
- [ ] P1 to P4, several bodies in one file: section 8.3.
- [ ] G1 to G7, a Combine whose tool body is made in another component: section 8.4 (the reads are under "Capture
      reader calls to watch", the last entry of the combine list).

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
  value, unit and, for a formula parameter, `expr` (or `expression` and `untranslated` when it was not translated); a body in a component and a part the translator cannot copy list
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
- [ ] **Combine with a tool of several steps**: a separate body made by an extrude (new body) and two more extrudes
      that join it (overlapping cylinders). Combine it as a cut from the main body, then undo and join it instead.
      Both match. Make one of the joined steps read a user parameter that nothing else reads: it shows as a size.
      Then add a fillet to the tool body: the Combine is written as a tool step and the fillet follows the tool's
      sizes ("Tool bodies", B1). Try a join whose first tool step lies apart from the main body and is bridged by a later step:
      if Paramability refuses the step "does not touch the part built so far", note it.
- [ ] **Marker and document**: after each export the timeline marker is where it was (at the end, or the step it was
      rolled back to), the design is unchanged, and
      Fusion's undo list and "unsaved changes" mark are as before (or, if moving the marker marks the document
      changed, note it). Cancel, and a forced error during the read, leave the marker where it was and the parameters
      as they were.
- [ ] **Fixed shape**: a part with a coil, and one with a variable radius fillet. Each saves as a fixed shape
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
- [ ] **V1 Used only through a formula.** A design with plain user parameters `cells` (a count), `pitch` (6 mm) and
      `wall` (1.5 mm), a formula `inner = cells * pitch` and a formula `outer = inner + 2 * wall`. Draw a body whose
      sketch and extrude read only `outer` (for example a square of side `outer` extruded `outer / 2`), with no
      favourites. Open the export dialog on it. Expect: `cells`, `pitch` and `wall` are ticked; `inner` and `outer` say
      "formula". Click `cells`: the box under the table says "This part uses it through the formula outer." and so does
      the tooltip of its name. Export: the progress window tries only `cells`, `pitch` and `wall`, never `inner` or
      `outer`; in Paramability `outer` is a formula over the three sizes and the body follows a change of each. Then
      mark `outer` as a favourite and a plain parameter the body does not read as another favourite, and open the
      dialog again: `cells`, `pitch` and `wall` are still ticked. Note any base parameter left unticked.
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
- [ ] **Early warning.** Pick a body whose steps hold one the add-in cannot copy (for example a coil). Right under the body picker a box shows "Copy stops at Coil1 (coil)." in bold, the reason in short,
      and "The part will be saved as a fixed shape; your parameters still come along as variables." Hover the box:
      the tooltip holds the full reason. If no tooltip shows, note it (the reason is then only in the box when short,
      and in the message after the export). Pick a body that copies fully: the box and the button go away. A step
      copied with a note (for example a round with setback corners, or an extrude that uses a sketch of another
      component) adds one line "Copied with a note: ...".
      A body whose steps hold one the copy leaves out but can go on without (for example a coil after the first
      extrude) shows "Likely left out of the copy:", then one line per step with the reason (at most three, then
      "and N more."). It is a guess made without the size tries, so after the export compare it with "N steps left out"
      in the Saved window: it should name the same steps, except rounds or shells that pick faces of a left out step
      (only the export can tell those). Note any step the box named that the Saved window did not, or the reverse
      for a step the box could have known.
- [ ] **Show in timeline.** With a stop shown, click "Show in timeline". The stopping step's feature is selected in
      the canvas and the timeline marker does not move; the design is not changed. The body picker still holds the
      body. If Fusion refuses the selection a message says so. Note whether the step also shows as selected in the
      timeline bar. No button shows when the stop has no step (a linked part, an unreadable place, a read that failed).
- [ ] **Message and status line.** Click OK on such a body. The message box starts with "Saved <file>. Copy stopped
      at Coil1 (coil)." then the reason and "The part is saved as a fixed shape." After you close the box, the
      lower-right corner of the Fusion window shows "Paramability: saved as a fixed shape. Copy stopped at ...". Note
      whether the line stays or Fusion replaces it at once (its lifetime is not fixed by the API).
- [ ] Click OK: the progress window shows as before, then the result window "Saved for Paramability" opens with
      sections that start with a "# Title" line: "# Result" (the file, what to do next, the kind of copy, the variables
      count), "# Sizes" (one line per size: name, range, "may be unexpected", "kept fixed", "not followed" or "not used" and the reason in brackets),
      and "# Left out", "# More sizes" or "# Check your design" when
      they apply (a section with nothing in it is left out). Only a Close button shows.
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

### 8.1 Places of another component (R tests)

These check the steps that use a face, plane, axis, direction or point of another component. The copy follows such a
place when the export measured how it moves with the sizes (section 8.2); a size it cannot follow is loose, and the
reason names the step and the other component. Read `report.json` for the `ref` records, and the recipe for the
formulas.

- [ ] **R1 Extrude to a face of another component.** `Base` holds a block of height `base_h`; in `Top`, an extrude "to" the
      top face of `Base`. Export `Top` with `base_h` ticked: the extrude is copied, its length is a formula of
      `base_h`, and `base_h` is a free size with no warning. The report shows a `ref` with `type` `BRepFace`, the `Base`
      component and body, `point`, `normal` and `face_point` in the coordinates of `Top`: move `Top` by (100, 50, 0)
      and turn it 90 degrees first, and check the numbers follow. Change `base_h` in Paramability: the extrude
      reaches the new top. Then an extrude that starts from the face (not reaches to it): its sketch moves with
      `base_h`. A round face of `Base` stops the copy ("reaches to a curved face of another component").
- [ ] **R2 Mirror across a plane of another component.** In `Cover`, an offset plane driven by `gap`; in `Tray`, a
      mirror across it. Export `Tray` with `gap` ticked: the mirror plane is a formula of `gap` and the mirrored half
      follows `gap` in Paramability. Then add an angle parameter that tilts the plane and tick it: that parameter is
      loose with "turns" and the mirror and `Cover` named. A size that only acts in `Tray` stays a free size.
- [ ] **R3 Pattern around an axis of another component.** Same with a circular pattern around a construction axis of
      `Cover` that moves with `gap`: the axis point is a formula of `gap` and the pattern centre follows it. A revolve
      about such an axis behaves the same; an axis that leaves the plane of the revolve's sketch makes that size
      loose ("moves out of the plane of its sketch"). A sketch line of `Cover` as the axis: the `axis` record has no
      `sketch_token`.
- [ ] **R4 Hole on a face of another component.** A hole placed by a point on a flat face of `Cover` whose offset follows
      `gap`: copied, the hole centre moves along the face normal with `gap` (check that Fusion moves the hole with the
      face; if the hole stays put while the face moves, the copy is wrong and this test fails). A hole placed by "plane and offsets"
      from an edge of `Cover` is marked foreign with `position_refs`. A hole on an edge of
      `Cover`: the copy stops ("placed on an edge or point of another component") and `position_refs` names the
      entity.
- [ ] **R5 Hole on sketch points of another component.** In `Cover`, a sketch with points; in `Tray`, a hole on them.
      Move the `Cover` occurrence by (100, 50, 0) and turn it 90 degrees first. Export: the hole sits where Fusion
      shows it (the right centres and the right direction into the material), the report has `position_refs` and no
      `sketch_token`. A size that moves that sketch moves the hole in Paramability.
- [ ] **R6 Origin plane and no measuring.** A mirror across an origin plane of the root: copied with no
      warning. Across an origin plane of `Cover`, with a ticked parameter that moves the `Cover` occurrence:
      `ref.origin` is true and the mirror follows the move (or the parameter is loose with a reason). Then a mirror across a plane of `Cover` driven by a
      ticked parameter, in an export where the sketch scan did not run (a motion file without references, or the scan failed): the
      parameter is loose with a reason, never silently fixed.
- [ ] **R7 Pattern direction from another component.** A rectangular pattern whose direction is an axis or edge of `Cover`:
      copied with the direction as read. A parameter that turns that axis is loose ("turns").

### 8.2 Measuring places of another component (M tests)

The export reads each plane, axis, direction or point of another component that a step uses again at every size it
tries, and fits how far it moves. The copy writes the result as formulas (R tests); check it in `report.json`: `probe.request.refs`
lists the references, `probe.motion.refs` says which were measured (empty text) or why not, `probe.motion.values` has
the keys `<item>/r/<slot>/...`, and each state's `read.refs` has the places in the part's coordinates.

- [ ] **M1 Plane that follows a size.** R2's design: in `Cover`, an offset plane driven by `gap`; in `Tray`, a mirror
      across it. Export `Tray` with `gap` ticked. `motion.refs` has `<item>.plane` with empty text; the key
      `<item>/r/plane/offset` is a formula of `gap` (slope 1 for a plane offset by `gap`, 0.5 for a plane halfway), and
      its number at the current `gap` is 0. Every state's `read.refs` `point` moves along `normal` by the same amount.
- [ ] **M2 Plane that turns.** Add an angle parameter that tilts the `Cover` plane and tick it. The key is stuck with
      cause `turns` and names the angle parameter; `gap` is not named. Untick the angle: the stuck key is gone.
- [ ] **M3 The part's own component moves.** Move `Tray` with a parameter (a joint or an offset plane under it), keep
      `Cover` fixed. The plane's `offset` follows that parameter with the opposite sign, and a parameter that moves
      both by the same amount gives no key.
- [ ] **M4 Occurrence moved and turned.** Move `Cover` by (100, 50, 0) and turn it 90 degrees in the assembly first.
      `read.refs` of the first state equals the capture's `ref.point` and `ref.normal` (`motion.refs` empty text); if
      not, `motion.refs` says "its first read did not match the capture" and nothing is fitted.
- [ ] **M5 Pattern direction from another component.** A rectangular pattern whose direction is an axis or edge of
      `Cover`. The capture has `direction_one_place` with `ref`; a size that tilts that axis gives a stuck
      `<item>/r/direction_one/dir`. A direction the add-in cannot bring in stops the copy ("reaches into another
      component").
- [ ] **M6 Restore and time.** After the export every parameter is back (the window lists none that would not go
      back) and `health.restore_gap_mm` is 0. A size that acts only on a referenced component is ticked to start with
      (its row says it changes that component) and has probe rows; unticked, it is listed under "These parameters also
      change this part" when it moves the plane. Note the export time with and without the references.

### 8.3 Several bodies in one file (P tests)

Pick two or more bodies in the body picker of Export for Paramability. Open the file in Paramability and look at
`report.json` (one record per body under `parts`, shared `sizes`).

- [ ] **P1 Shared size.** Two bodies in two components that both read `Wall`. Pick both (hold Ctrl or Shift). The
      table ticks `Wall` and what either body uses. One file, two objects at the places Fusion shows, and one `Wall`
      field on the form that rebuilds both. Parameters are back, no temporary component is left, the timeline marker
      is where it was.
- [ ] **P2 Time.** Export 2, 4 and 8 bodies of a real design with sketches. Note the time and the number of probe
      rows in `report.json` (`parts[].probe.states`). The export reads each body's steps once (N captures) and tries
      the sketches over one set of rows of at most 64.
- [ ] **P3 Fixed shape.** One picked body starts with a Coil (a step before the first copied one stops the copy), the other copies. The
      warning under the picker names the first body. The file holds an editable part and a fixed shape with a note;
      the editable part keeps its sizes.
- [ ] **P4 Moves in the assembly.** A size that drives a joint offset moving one of the bodies. Tick it: it is marked
      "may give unexpected results" with the joint reason, the bodies stay where Fusion shows them now.
- [ ] Pick one body again: the file is the usual single body file (`kind: recipe`).
- [ ] After picking a body, "Show in timeline" selects the step and the picker still holds all picked bodies.

### 8.4 Tool bodies made in another component (G tests)

A Combine in the exported body's component can take a tool body made in another component. The add-in reads the steps
that made the tool a second time (in the tool component's own frame), carries them to the Combine's place with the
tool component's place in the assembly, and writes them with the Combine's operation. Look in `report.json` at the
Combine's `data.tools[]` (`component`, `path`, `place` with `frame`, `target_frame` and the three plane `ref`s) and at
the items of the tool component (`helper_of`, `data`). A tool step that cannot be copied leaves the Combine out as a gap, and the
reason names the step and the component. The tool is written as a tool step, like a tool of the same component
("Tool bodies").

- [ ] **G1 Cut with a tool from another component.** Component `Rod` holds a body made by two join extrudes (two
      cylinders, one sketch each). `Rod` is moved by (30, 10, 0) and turned 90 degrees about Z. In the root (or in
      `Tray`, moved too) a box, then a Combine "cut" with the Rod body as the tool. Export the box: copied; the recipe
      has the box and two cut extrudes at the places Fusion shows (the cylinders cut where the tool sits, not at the
      Rod's origin), and the part in Paramability matches the STEP. The report shows `place.frame` equal to the
      occurrence, `checked_points` 3, and `helper_of` on the two Rod extrudes. Then a "join" Combine with the same
      tool, and a tool kept (`isKeepToolBodies`) that serves a second Combine.
- [ ] **G2 A size in the tool.** The tool extrude height is a model parameter of `Rod` that reads a user parameter
      `tool_len`; a cylinder radius is a sketch dimension of `Rod` driven by `tool_r`. Tick both: each is a free size,
      and changing it in Paramability changes the cut. The probe request lists the `Rod` sketches under `native`, and
      `probe.motion.values` has keys for the extrude items of `Rod`. A size that acts on `Rod` without moving
      anything (a joint it is not part of) is dropped as "tried, changes nothing".
- [ ] **G3 Pasted body.** A body in `Rod` made by Copy Paste Body of another body of `Rod`, used as the tool. The
      Combine is copied: the tool step holds the steps of the source, at the place of `Rod`. Same check as B8, with
      the paste inside the other component.
- [ ] **G4 Moved tool.** A body in `Rod` moved by Move/Copy (free move) before the Combine: the tool step holds the
      steps and a `move` for it, and the cut sits where Fusion shows it.
- [ ] **G5 Time.** Export a body whose tool chain has about 20 steps in other components; note the export time with
      and without the tool (the second pass moves the marker at most twice per tool step, and not for other steps).
      More than 120 tool steps stop the copy ("reads at most 120 steps").
- [ ] **G6 Tool with a fillet.** Round the edges of the `Rod` body before the Combine: the tool step holds the round
      and it follows the sizes of `Rod`. A tool with a coil leaves the Combine out and the reason names the coil and `Rod`.
- [ ] **G7 Tool component moved by a size.** Move `Rod` with a ticked parameter (an offset on a joint or a move
      driven by `rod_x`). The probe request lists three `refs` per tool (`<Combine index>.tool0.xy|xz|yz`) and
      `probe.motion.refs` marks them measured. The cut follows the move in Paramability (the recipe positions are
      formulas of `rod_x`). Turn `Rod` with an angle parameter: that parameter is loose with "puts its tool at the
      place of Rod that turns with it". Run once with the references unmeasured (scan failed): every size that acts on
      `Rod` is loose, never silently fixed.

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
      The boss moves with the height. Then make an extrude reach "to" that plane: its length follows the height
      (`recipe.json` writes the distance as a formula) and nothing is marked.
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
- [ ] **K12 Measured nearer.** A size whose range ends do not rebuild in Fusion (a pipe diameter with a range of half
      to double, where a chamfer or round fails at both ends). Export: the progress window shows tries named
      "(min, nearer)" and "(max, nearer)" after the first ones. `report.json`: `probe.states` has `failed` with the
      step on each state that did not build, and `probe.motion.spans` gives, for that size, `low` and `high` (the
      values that built) and `failed` (the values that did not, with the step). When a nearer try built, the size is a
      size (or "not used"), its range in `recipe.json` stops at the values that built on the sides that failed (a
      range typed in the dialog keeps its ends), and it is not marked for those sides; in Paramability it matches
      Fusion over that range. Where a near value built and the range end did not, extra tries "(max, nearer)" split
      the gap (up to four per side), so the range stops close to the real limit. The result window has a "range cut"
      line for the size with the value and step where Fusion did not rebuild, `report.json` has `sizes.cut`, and
      Paramability shows the same reason as a quiet info mark next to the size (the file's `cuts` list), not a warning. A failure in a step of another
      component leaves the range alone. Export two bodies that read that size in one file: both recipes have the same
      range and the reason says it holds in every part that uses the size. When no try built, the result window shows it as not followed, and the reason names the nearest values
      tried and the step that failed there; it never says "changes nothing". Note how many extra tries ran (at most 24)
      and the export time.
- [ ] **K13 Only the curved size is marked.** A bracket with two legs at an angle parameter, a wall thickness and leg
      lengths. Export: the angle is marked ("along a curve"), the wall thickness and the leg lengths stay sizes, and
      the progress window shows "all low but curved" and "all high but curved". In Paramability, change the wall and
      a leg length (not the angle): the part matches Fusion.
- [ ] **K14 Tries of other parameters after a flipped sketch.** In a design where a sketch can land on its other
      solution (the filter box lid), export with parameters of another component unticked. `probe.after_rows` names
      what reads differently from the first read once the parameters are back; `probe.discovery` entries have
      `changed` and `unread`; a parameter that does not touch the part has `moved: false`, and "Also change this part"
      lists only parameters whose `changed` is not empty. A try that does not rebuild has `tried: false` and counts as
      not tried. If `health.restore_unverified` is true, `health.unchecked` names the sketch and the result window
      says which sketch to look at: check in Fusion that it is back as before.
- [ ] **K15 Revolve axis.** A revolve whose axis is the pipe component's own axis (origin Z axis), then one about a
      straight edge, then one about a round edge (if Fusion lets you pick it). `capture.items[...].data.axis` has
      `point` and `dir` for the first two; when the copy refuses, the axis record has `type` (and `geometry` or
      `error`), and the message says which kind of axis it is. Send the report of the pipe of the two body filter
      file: its axis could not be told apart before.
- [ ] **K16 Angle size.** A bracket of two legs at an angle size (for example 120 degrees), a wall thickness and leg
      lengths, drawn in one sketch. Tick all sizes and export. The progress window shows "(half way)" tries for the
      angle and "<angle> and <size> (low/high)" tries. `report.json`: `probe.motion.values` has entries with `sum`
      (a formula with `cos`, `sin` or `cot` of the angle); the result window shows the angle as a size. In
      Paramability, set the angle to two other values inside its range (for example 100 and 140): the bracket matches
      Fusion at the same values (measure a leg end and the inner corner). When the angle is still marked, note the
      reason and send `report.json`.
- [ ] **K17 Slot through a wall.** A slot cut "through all" from a sketch on a plane at the face of a wall, with its
      corners rounded afterwards. Export: the rounds follow the wall and slot sizes (no "picks may move" warning). If
      the cut direction was stored the other way, the step list says so in a note; in Paramability the slot is cut
      through the wall.
- [ ] **K18 Sketch on its other solution.** A design with a sketch that has two solutions (a thin strip offset to one
      side of a line) and a size whose far value does not rebuild. Export with that size
      ticked. `report.json`: the state after the failed try has a `start` read; `probe.motion.flipped` names the
      sketch when it stayed on its other solution; the sizes of the later tries are not loose with "makes a different
      outline". The result window has one line that names the sketch. Check in Fusion that the sketch is back on its
      first solution after the export.
- [ ] **K19 Projected curve named again.** A sketch on a face with a projected or intersection line between two
      profiles that one extrude uses. Export: the sizes that only move that line are not loose with "<sketch> makes a
      different outline", and `health.unchecked` does not name the sketch.
- [ ] **K20 Slot with round ends.** A rectangular slot cut with its four corner edges rounded by `SlotHeight / 2`.
      Export: `recipe.json` has the cut with `"kind": "slot"` and no round for that fillet; the step list notes that
      the rounded ends are drawn into the cut. In Paramability change `SlotHeight`: the ends stay half circles.
- [ ] **K21 Pattern with its round and chamfer.** A symmetric rectangular pattern of a groove cut with its round and
      chamfer, the count from a parameter. Export: `recipe.json` has one round and one chamfer step per possible copy,
      each with a `when` that reads the count. In Paramability set the count lower and higher: each groove copy keeps
      its round and chamfer and no step picks an edge where no copy is. Note copies where Paramability leaves a round
      out (the step list says so).
- [ ] **K22 A curved point holds only its own step.** A box with ribs whose corners a wall thickness moves along a
      curve (marked "along a curve"), and a lid rail in another sketch that sits on the walls and follows the wall
      thickness and the box width (a count times a cube width). Export, then in Paramability set the wall thickness
      and the cube width to their ends: the rail still meets the wall and the part matches Fusion; only the ribs may
      differ.
- [ ] **K23 A different outline stops the range.** The lid of the filter box, with the wall thickness and the box
      depth ticked (the lid rail is drawn around the box, and a lid chamfer fails when the box gets small). Export.
      The progress window shows "(max, nearer)" tries of the wall thickness between its value and the first value
      where the rail took another outline. Expect: the wall thickness is a size (or "not used" with the values it
      was followed between and the value where the outline changes), never "not a size" only because of the
      outline; its range stops at the last value that kept the rail outline and the result window has a "range cut"
      line that names the rail sketch and that value. `report.json`: `probe.motion.spans` has `kept` and `changed`
      for it, and `sizes.cut` the same reason. The box depth, when nothing below its value rebuilds, starts at its
      value and is not dropped for the wall's outline. In Paramability, set the wall thickness inside the cut range:
      the lid matches Fusion. A size that changes the outline on both sides is "not a size" with "no value other
      than ... could be copied" and names the nearest failure or outline on each side. Note the number of tries and
      the export time.
- [ ] **K24 Plane offset from a face.** A plate whose thickness `plate_mm` is the extrude distance (not a sketch
      dimension). Add Plane1 offset 2 mm below its top face and Plane2 offset 1 mm from Plane1. Draw a circle on Plane1
      and cut it 4 mm down; extrude a post from the base sketch "to" Plane2. Tick only `plate_mm` and export. Expect:
      the progress window tries `plate_mm`; in `report.json` the pocket profile's `reference` has `definition` and
      `built_on` (the top face), and the post's `side_one` has the chain (Plane2 built on Plane1 built on the face);
      `recipe.json` writes the pocket's `sketch.on.origin` and the post's distance as formulas of `plate_mm`, and
      nothing is marked. In Paramability change `plate_mm`: the pocket stays 2 mm under the top face and the post ends
      1 mm under it, as in Fusion. Then set Plane1's offset to a user parameter `gap_mm`, tick it and export again:
      both follow `gap_mm` too. Then replace Plane1 by a plane at an angle to the top face: the pocket follows (or is
      marked "turns" when the angle is a size), and the post's reach is marked with "a plane built on part geometry".
- [ ] **K25 Reach to a face the steps cannot place.** A plate 40 x 20 with its thickness `plate_mm` and a second
      size `width_mm` (the plate's width in the base sketch). Draw a rectangle on a side sketch and cut a slot into
      the plate whose top wall sits `slot_mm` under the top face (a sketch dimension). Add a plane offset 1 mm from
      the slot's top wall, then extrude a peg from the base sketch "to" that plane, as a new body that a Combine cuts
      from the plate. Tick all three sizes and export. Expect: `report.json` has `token` on the face under the plane,
      `probe.request.refs` holds the peg's `side_one` with `"own": true`, and `probe.motion.refs` gives it `""`;
      `recipe.json` writes the peg's distance as a formula of `plate_mm` and `slot_mm`, and `width_mm` is not marked.
      In Paramability change `plate_mm` and `slot_mm`: the peg still ends 1 mm under the slot's top wall. Then reach
      "to" the slot's top wall itself instead of the plane: the same holds (Fusion finds the face again by its token
      at every try; when it does not, `motion.refs` names why and the sizes stay marked as before).
- [ ] **K26 Sketch that flips during the tries.** A lid sketch drawn around a projected point of another component,
      with a distance dimension from a sketch point to that projected point (a distance has no side), and sizes that
      make the box shallower. Export with those sizes ticked. `report.json`: `probe.recovery` counts the put backs;
      every state with a `start` on the other outline has a `put_back` read on the first one; the rows after it do not
      fail in steps of another component; a row listed again carries `again`. `probe.motion.flipped` is empty, and
      the result window has no line about a sketch that stayed on its other outline. Check in Fusion that the sketch
      is on its first solution after the export, and note the export time (each put back is one more rebuild).
- [ ] **K27 Outline face read before its step.** A plate whose width `width_mm` and thickness `plate_mm` are sizes,
      with a tapered join extruded from its top face (the face itself as the outline), then a fillet on a plate edge.
      Tick both and export. Expect: `probe.request.faces` holds the join's key with the face `token` and `before`, the
      states have `faces` with that key, `probe.motion.faces` names it, and neither size is marked; in Paramability
      change both and the join stays on the top face with its outline. Repeat with an emboss whose outline runs over
      a hole of its face (E8): the `within` outline follows the sizes. Then make the face take another outline at a
      large width (a hole that appears there): the width's range stops before it, "the face ... starts on makes a
      different outline". Then let an earlier two sided extrude reach past its start at a low size value, so the face
      faces the other way there: that size's range stops before the value with the same reason, and it is not marked
      "turns the plane". Check in Fusion that the marker is back where it was after the export, and note the export
      time (each read moves the marker before the step and back).
      Seen with 0.10.5 (Fusion 2706.1.17, 2026-11-12): a tapered join from the plate's top face copies, matches, and
      follows width and thickness with neither marked (no fillet in that test).

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
- [ ] **E7 Face as the outline.** If the Emboss dialog takes a flat face as its profile, emboss the top face of a small
      pad onto the face around it. The emboss item's `profiles` holds a record with `face` true and, when an extrude
      made that face, `made_by`. The copy matches; with `made_by` the pad's sizes stay free, without it they are
      marked loose. If the dialog takes no faces, note that here.
- [ ] **E8 Outline past its face.** Emboss a raised outline that reaches over a hole or a chamfered edge in its face.
      Fusion raises only the part on the face. `end_area` times `depth` equals `volume_after` minus `volume_before`, and
      `faces[0].outline` holds the edges of the face, holes included. The copy writes the extrude with a `within`
      outline of that face and matches. Repeat with a sunk outline (a deboss) and with an outline that runs off the
      face's edge. An older export without `outline` stops with "the edges of the face could not be read".

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

## 12. Sketches read directly, the marker during the tries, progress text

Send `report.json` after each of these; the capture and `probe` are what is checked.

- [ ] **D1 Rectangle from the origin.** A sketch with a rectangle from the origin, a width and a height dimension, used
      by an extrude. In `report.json`, `capture.sketch_graphs` has an entry for it: 4 lines, 4 corner points (two
      lines share each corner point id in their `points`), 2 dimensions with their `param` names and `driving` true,
      the geometric constraints (horizontal, vertical, coincident) and `fully_constrained` true. Nothing in the export
      changes because of it.
- [ ] **D5 Marker held early.** An export of a part in a design with many later steps that the part does not need (the
      FilterBox, or a second component with a few extrudes after it). Note the export time. Watch the timeline while the
      tries run: the marker sits just after the last step the part needs and not at the end. After the export the marker
      is back where it was, the timeline is unchanged and Undo shows no new entries. In `report.json`, `probe.timeline`
      is `{ rolled: true, items: N, of: M }` with N below M. A design where the part needs every step shows
      `rolled: false` with a reason, and the marker never moves.
- [ ] **D6 Progress window.** While the tries run the window shows the explanation ("Measuring how your sketches follow
      each size. Fusion rebuilds the design for every try; all values go back at the end.") and, under it, a line
      such as "Try 5 of 31: HolderWidth at 32 mm". The value has the unit you typed (inches in an inch design, degrees
      for an angle). A try on several sizes says "several sizes together"; a discovery try says "checking if X changes
      this part"; a try nearer after one that did not rebuild ends with "The last value did not rebuild, so this one is
      nearer." If Fusion shows only one line, note which one; the explanation then moves to the window title.
- [ ] **D7 Rectangle with no position dimension.** The rectangle floats (no dimension from the origin). Its entry in
      `sketch_graphs` has `fully_constrained` false and its points and lines `free` true. The export gives the same
      part as before.
- [ ] **D8 Driven dimension.** A reference (driven) dimension in a sketch. It is listed with `driving` false and its
      value; the export is unchanged.
- [ ] **D9 Design in inches.** A design whose default unit is inches. `sketch_graphs` lengths are mm (a 1 in dimension
      reads 25.4) and angles are degrees; `xy` of points is in mm.
- [ ] **D10 Reads to check.** In one sketch graph, check: `xy` of a point is in the sketch's own frame (the same frame as
      the profile curves of the extrude); two connected lines share one sketch point id; exactly one point has
      `origin: true` and it is the sketch origin; `fixed` of the origin; an angular dimension gives its `value` in
      degrees (note which of the four angles it is); a linear dimension's `orientation` reads horizontal, vertical or
      aligned the way it is drawn.
- [ ] **D11 Sketch dimension in `dependents`.** In `report.json`, a user parameter that sets a sketch dimension (the pipe
      diameter of the K10 design) has a `dependents` record with `kind: "sketchDimension"`, the sketch name, its token
      and the component, and not `kind: "other"` with the sketch name in `feature`. The parameter of a sketch text height
      reads `kind: "sketchText"`. The offer text of a linked parameter (K10) is the same as before.
- [ ] **D12 First tries near the value.** In `probe.states` the first single size tries are about a quarter below and
      above the current value (inside the range), the far range ends follow only after them (and the retries of near
      tries that did not build), and a size that only feeds an extrude distance or a fillet radius has no try. Compare
      the number of tries and the export time with the last version.
- [ ] **D13 Cancel and failure with the marker held.** Cancel during the tries on a design where D5 shows `rolled: true`:
      the marker is back where it was, the parameters are back, no entries were added to Undo and the later steps have
      their normal look (they are rebuilt once at the end). Then pull the marker back by hand before exporting and check
      the same.

## 13. Sweeps and lofts

A sweep along a straight path is copied as an extrude, a sweep along one arc or a full circle as a revolve, and a sweep
along a flat chain of lines, arcs and spline curves (or a 3D chain of lines and tangent arcs) as a sweep step. A loft
between two closed outlines with free ends is copied as a loft with straight faces. Everything else is left out with a
reason. "Matches" means the part Paramability builds agrees with the Fusion part. The calls behind these tests are
listed under "Capture reader calls to watch (sweep and loft)". Send `report.json` from any sweep or loft that
surprises.

- [ ] **SW1 Straight sweep.** A rectangle swept along one sketch line, profile at the line start. The recipe holds an
      `extrude`, the part matches, and a size behind the profile resizes it in Paramability. A size behind the length
      of the line is the extrude's distance and resizes the part the same way (see SW19).
- [ ] **SW2 Pipe with bends.** A circle swept along a flat path of lines joined by tangent arcs. The recipe holds a
      `sweep` step with a flat path, the part matches, and `volume_after` minus `volume_before` is the circle area
      times the path length. Sizes behind the path sketch follow in the path (see SW19).
      `faces_after.end` holds a point on the end cap and its normal; both lie at the far end of the path, square to
      it. Then draw the same path from the far end, or use Join and Cut: the cap must still be at the far end, or the
      sweep is left out as not matching.
- [ ] **SW3 Ring.** A triangle swept along a full sketch circle. The recipe holds a full turn `revolve` and the part
      matches. `path.closed` is true. With a twist of 360 degrees the same ring becomes a `sweep` step along a closed
      flat path of two half arcs (see SW18).
      A triangle drawn on the outer side of a small arc (an arc of radius 3 mm, the triangle 4 mm wide beside it) is
      copied too; one that reaches across the arc's axis is left out.
- [ ] **SW4 Profile at the far end.** Draw the path from the far end towards the profile. Note the order of
      `path.curves` and the `opposed` flags. The copy turns the path round and the part matches.
- [ ] **SW5 Profile in the middle.** Put the profile plane through the middle of the path. Note `distance_one` and
      `distance_two` and what Fusion builds. The sweep is left out with "This sweep runs to both sides of its
      outline".
- [ ] **SW6 Sharp corner.** Two sketch lines at 90 degrees, no arc between them. The sweep is left out with "The path
      of this sweep has a sharp corner". Note what Fusion builds (a mitre, a rounded corner or an error) and measure
      the outer corner, so a later version can copy it.
- [ ] **SW7 Taper and twist.** On a straight path, a 20 by 10 mm rectangle with taper 5 degrees, then with twist 90
      degrees. Each is copied as a `sweep` step with `taperDeg` or `twistDeg` (recipe version 16) and a note "check the
      shape"; the sizes behind the angle and the outline are marked. Note `taper_deg` and `twist_deg` in degrees with
      the dialog's sign; whether the far end of the rectangle is offset (both sides shrink by the same mm) or scaled
      (both shrink by the same share, then the taper is left out as "scales its outline"); which way the taper leans
      for a positive angle; and which way the twist turns, seen along the path. A taper steep enough to close the
      rectangle (more than 5.7 degrees on 20 mm) is left out. Then set `TAPER_MEANING_CONFIRMED`,
      `TWIST_SIGN_CONFIRMED` and the two signs in `lib/translator/sweep.py` and drop the note.
- [ ] **SW8 Parallel orientation.** The SW2 path with orientation parallel is left out ("The outline keeps one
      direction along a path that turns back past its plane"). Along a path that keeps moving away from the outline's
      plane (one arc of 60 degrees) it is copied as a `sweep` step with `orientation: "fixed"`, and the part matches.
      On a straight path it is copied as an extrude. An arc turning 88 degrees is left out (the path must keep rising). A twist or taper together with parallel is left out, and so is
      parallel along a closed path ("along a closed path").
- [ ] **SW9 Guide rail.** A sweep with a guide rail is left out ("Sweeps with a guide rail"). `rail` holds the rail
      curves and `scaling` holds the dialog's choice. If a build cannot read the rail, `rail` is `{ "kind": "unread" }`
      and the reason says the rail could not be read.
- [ ] **SW10 Path of edges.** Sweep a small circle along two edges of an extruded box. It is copied as measured, the
      sizes behind the box are marked "may give unexpected results", and `path.edges` lists the two edges with
      tokens and `body`. A pattern of that sweep is left out. Then do the same on an edge of another component: the
      sweep is left out as a step in another component. Edges of a second body of the same component mark every
      ticked size.
- [ ] **SW11 Tilted profile.** A profile at 30 degrees to the path at its start. The sweep is left out ("The outline is
      not square to the path at its start"). Note what Fusion builds.
- [ ] **SW12 3D path.** A 3D sketch of three lines with sketch fillets at the two corners. The recipe holds a sweep
      step with a 3D path with two bends and the part matches. With a spline or an arc that is not tangent to its
      neighbours the sweep is left out ("bends in 3D in a way that is not copied yet").
- [ ] **SW13 Space of the path curves.** In a design where the sweep's component is moved in the assembly, check that
      `path.curves` and `check` (read from `PathEntity.curve`) agree in the component's frame, not the root frame.
- [ ] **SW15 Twist on a bent path.** The SW2 path with twist 90 degrees. Copied as a `sweep` step with `twistDeg`
      and a note; the end of the part is turned the same way as in Fusion. With a taper too it is left out
      ("both twist and taper").
- [ ] **SW16 Taper on an arc.** A rectangle along one arc with taper 3 degrees. Copied with the note. Compare the sizes
      at the far end with Fusion. A taper along a path with a spline curve is left out ("along curves").
- [ ] **SW17 Closed rim.** A 2 by 2 mm rectangle swept once round a rounded rectangle sketch (40 by 20 mm, corner
      radius 5 mm), the rectangle inside the loop at the middle of a long side. The recipe holds a `sweep` step with a
      flat path that has `closed: true`, starts at the profile plane and ends on its start (version 16), and the part
      matches. `volume_after` is the area times the length the centre travels: the path length minus 2 pi times how
      far the centre sits inside the loop. Then put the rectangle on a corner of a rectangle sketch with sharp
      corners: the sweep is left out ("sits on a sharp corner of its closed path"). A closed sketch with a spline side
      is copied when the profile sits on the spline too; note whether the two halves of the spline meet smoothly in
      the recipe.
- [ ] **SW18 Twist along a closed path.** The SW17 path with a bar centred on it and a twist of 360 degrees. Copied
      with the note; whether the end of the part meets its start, and the handedness of the twist, are the same as
      in Fusion. Draw the same loop from the other end (or flip its direction) and repeat: the twist must turn the same
      way as Fusion's, so the copy mirrors the first one. A twist of 90 degrees is left out ("not whole turns"). A taper
      on a closed path is left out ("Tapered sweeps along a closed path").
- [ ] **SW19 Path sizes on the form.** The SW2 pipe with a user parameter behind each of the first line's length, the
      arc's radius and the last line's length, and the profile's plane tied to the start of the path with a sketch
      dimension. Tick the three sizes and export. The flat path holds formulas for them (such as `bend_mm + 20`), the
      sizes are not marked "may give unexpected results", and in Paramability each one moves the pipe the way the same
      change moves it in Fusion (compare the end point and `volume_after`). Make the circle wider than the smallest
      arc radius the form allows: the range of the size behind the circle stops before the value where the circle
      would reach the centre of the bend, and the note says so ("past ..."). Then move the profile plane with a size
      that does not move the start of the path (a plane on an offset plane): that size is marked "starts its path on
      the plane of its outline". Repeat on the SW17 rim with a size behind its width: it follows, and its range
      stops where the long side would end before the profile plane. A path with a spline curve, a full circle, 3D
      corner points, or a taper keeps its sizes marked, as before. Give the profile a rounded corner or a slot shape
      (arcs): the range of the size behind it stops where the arc, not only its corners, would reach the centre of
      the bend. Add a twist to a straight path with a size behind its length: the path follows the size like the
      untwisted one. A sweep with many sizes behind its path (seven or more) and a long path may not be checked at every
      value: then its sizes are marked ("too many settings to check them all in a reasonable time") and no range is
      cut; the export must not stay busy for more than about twenty seconds on it. Send `report.json` from a sweep
      whose path sizes do not follow or whose range stops too early.
- [ ] **SW14 Round on a sweep end.** After SW2 (a circle of a user parameter `wire_mm` swept along a bent path), add
      a fillet on the whole edge of the end cap and tick `wire_mm`. The `round` step picks `featureEdges` of the sweep
      with `which: "end"`, `wire_mm` is not marked "may give unexpected results", and in Paramability the round
      follows the end of the pipe when `wire_mm` changes. Do the same on the edge of the start cap (`which: "start"`).
      After SW1 (the extrude form) the fillet follows sizes like a round on an extrude.
- [ ] **SW20 Faces of a sweep that stay as measured.** On the SW14 part, pick one edge of the end cap of a square
      wire instead of all four: the round holds a point, `wire_mm` is marked, and a size of an earlier step (a plate
      the wire sits on) is not. A fillet on an edge along the wire at a corner of the square does the same. A fillet on
      a round wire's side edge, or on the end of a twisted, tapered or hollow wire, or of a closed path, marks every
      size written before it. A twisted sweep names its start cap but not its end cap. Send `report.json` when
      Paramability picks another edge than Fusion after a size changes.
- [ ] **SW21 Chamfer where three edges meet.** Make a 20 mm cube. Chamfer the three edges that meet at one corner
      with the same distance (2 mm), in one Chamfer feature, and export. The app kernel and its wedge fallback give
      different shapes at such a corner, and the app refuses the wedge there, so we need to learn which shape Fusion
      makes. Send a photo of the corner (from outside, close up) or the `report.json`, and say whether the corner is a
      small triangle where the three chamfer faces meet, a flat patch with more sides, or something else.
- [ ] **LF1 Two squares.** A loft from a 20 mm square to a 10 mm square, 30 mm apart, free ends. The recipe holds a
      loft with `ruled` set and `volume_after` is the frustum volume (7000 mm3). Note whether Fusion builds straight
      faces between the two outlines (a curved side would show in the volume).
      Then turn the top square 45 degrees (turn its sketch, not its outline) and export: the copy is accepted when
      the part's volume is 6414 mm3, and left out ("joins the corners ... another way") when it is 3586 mm3. Note which
      volume Fusion gives; with a Join or Cut instead of a new body the copy carries a note that the outlines are
      turned against each other.
- [ ] **LF2 Circle to square.** A loft from a circle to a square. It is copied with a note that the outlines have
      different shapes. Compare the part's volume in Paramability with Fusion's, and note how the corners are
      paired.
- [ ] **LF3 Three sections.** Left out with "Lofts through more than two outlines".
- [ ] **LF4 Loft options.** One loft each with a tangent end, a point end, two rails, a centre line and Closed on.
      Each is left out with its own reason, and `sections[].end`, `rails`, `centerline` and `closed` read as set.
- [ ] **LF5 Tube loft.** Two rings (circle with a circle hole) of different sizes. The recipe holds a loft with one
      hole key and the part matches. A ring and a plain circle are left out ("different numbers of openings").
- [ ] **LF6 Round on a loft end.** After LF1 with its sizes on the form, add a fillet on all four edges of the top
      outline and tick the sizes. The round picks `featureEdges` of the loft with `which: "end"` and no size is marked;
      the bottom outline gives `which: "start"`. A fillet on one edge of an outline marks the sizes the loft reads, and
      one on the loft's side marks every size before it. A tube loft (LF5) has no end faces to name.

Members of the running Fusion build to note in the same exports: whether `SweepFeature.extent`, the guide surface
sweep type and the loft end condition classes exist (an absent one reads as null or `other` and the step is left
out).

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

## Tool bodies

A Combine takes its tool bodies as they stand at the Combine. A tool made only by steps that add material is written
step by step. Any other tool is written as one tool step that holds the steps that made it (cuts, rounds, chamfers,
holes, shells, a Combine of its own, Copy Paste Body, Move, patterns and mirrors of bodies). Look in `report.json` at
the Combine's verdict: `tool_steps` holds the verdicts of the items inside the tools, and the recipe shows a `toolBody`
step with its own `features`. A step that cannot be copied is left out as a gap (inside the tool, or the whole Combine when the tool cannot be built) and the reason names it, for example "The
tool body Body3 cannot be copied: Coil1 (coil)". The calls behind these tests are listed under "Capture reader calls
to watch (tool bodies)". Use a design with a user parameter behind a tool's size, and check each result in
Paramability against the STEP, at the current sizes and at one other size.

- [ ] **B1 Tool with a chamfer.** A separate body (an extrude with a chamfer on one edge), cut from the main body with
      Combine. Export: the Combine is one tool step that holds the extrude and the chamfer, and the pocket has the
      chamfer. Change the tool's size (a parameter behind the extrude or the chamfer) in Paramability: the pocket
      follows. Do the same with a cut and a hole made in the tool before the Combine.
- [ ] **B2 Copy Paste Body.** Paste a copy of a body (a bracket) and Combine it into another body. Export: copied.
      The capture item has `data.sources` (the source body, with `points`) and `data.result_bodies`; the tool step
      holds the steps of the source, written again with their own ids, and the verdict is "translated". A paste that
      sits on its source has no `move`; a paste moved afterwards has one. Change a size of the source: both the
      source and the pasted tool follow. A paste onto a body that already has steps stops with "lands on a body that
      already has steps". Fusion documents `sourceBody` as a collection: check that `data.sources` is filled. Also
      paste two bodies at once: `data.sources` has both, and each pasted body gets the steps of its own source.
- [ ] **B3 Free Move.** Move a tool body by hand (Move/Copy, Free Move, a turn and a shift) before the Combine. The cut
      sits where Fusion shows it. The capture item has `data.move_type` `free`, `points_before` and `points_after`
      (up to 8 corner points of the body each); the recipe has a `move` step with numbers. Also try Point to Point,
      Point to Position and Translate Along Entity: the same result, and every ticked size is marked "may give
      unexpected results" ("follows a point or an edge that may move with it") or left out with that reason. A Move of
      faces stops with "moves faces of the
      body".
- [ ] **B4 Move by X, Y, Z.** Move a tool by distances that read user parameters, in a component that is not at the
      origin and is turned. Do it once with the Move in component space and once in design space (the option in the
      Move dialog). The `move` step reads the sizes: change one, and the tool moves in Paramability the way it moves
      in Fusion. Note any sign or space that comes out wrong (`data.is_design_space`).
- [ ] **B5 Move by Rotate.** Rotate a tool about a sketch line with an angle parameter. The tool turns the same way as
      in Fusion, and follows the angle. Rotate about a construction axis and an edge too. If the corners of the body
      cannot tell the turn from its opposite, the angle stays a fixed number with the reason "the corners of the body
      do not tell which way ... turns"; note which axis kind gave that.
- [ ] **B6 Pattern of bodies.** Make a circular pattern of bodies (a tool with a count parameter), then Combine join
      all copies with the part. Export: one `pattern` step that repeats the tool steps, not one tool per copy, and the
      verdict of the pattern item is "translated". The size behind the count is marked "may give unexpected results";
      spacing and angle are not. Change the count in Paramability. Then answer this in Fusion: change the count there
      and edit the Combine. Does the Combine take the new copies? The recipe repeats the tools for any count. Once
      Fusion is confirmed to take the new copies, the mark can go. If Fusion leaves them out, say so: the app and
      Fusion then differ for a changed count. Copies are matched on their first 8 vertices: on a body with more than 8,
      a copy that lists its vertices in another order is not matched, and the pattern stops with "could not be matched
      to the bodies it made" or falls back to one tool per copy; note if that happens on a real pattern. Also try a
      rectangular pattern, a mirror of bodies (with "Combine" off), a Combine that takes only some of the copies (each
      copy becomes a tool with its place in numbers, and the sizes behind the layout are marked), and a cut instead of
      a join.
- [ ] **B7 Intersect of several tools.** Two tool bodies that overlap each other only partly and both overlap the part,
      then Combine intersect with both. In the capture item read `data.intersect_volumes` (`every` and `any`, mm3) and
      `data.intersect_model`. Compare with the shape Fusion made: `every` means the part keeps only what lies in the
      part and in all tools; `any` means what lies in the part and in at least one tool. Write down which one Fusion
      made, and whether `intersect_model` says the same. With `every` the recipe has one tool step per tool, each
      with `combine` intersect. With `any` it has one intersect step that holds the tools. When the two volumes are
      equal the sizes the tools read are marked "may give unexpected results"; once the rule is known, that mark can
      go. Also try two tools that do not overlap each other at all: `every` should be 0. An intersect of one tool
      with several steps is a tool step too. An intersect with a tool from another component, or where the two
      volumes fit neither way, stops with "keeps a shared part that the copy could not work out".
- [ ] **B8 The whole chain.** In component `Rod`, paste a body from another component, Move it, Offset Faces on it,
      make a pattern of it, then Combine the copies into the part. Export: copied, the cut sits where Fusion shows it,
      and a size of the source follows through every step.
- [ ] **B9 Kept tool.** A Combine with "Keep tools" on, then a fillet and two extrudes on the kept tool, then a second
      Combine that uses it. Export the part: the second Combine gets the tool with the later steps, and a note says
      Fusion kept the first tool. A tool the first Combine used up (no "Keep tools") cannot serve a second one: it
      stops with "was used up by an earlier combine".
- [ ] **B10 Export the kept tool.** Export the kept tool body itself. The Combine that kept it is skipped (its target
      is another body) and the tool is copied with its own steps.
- [ ] **B11 Coil in a tool.** A tool made by a coil. The Combine is left out as a gap, naming the coil and the tool body.
      Nothing is guessed.
- [ ] **B12 Time and a real design.** A design with about 20 tool steps: note the export time with and without the
      tools (a tool is walked once per pass of the sizes). Then export the body of the real design that has Combines
      and send `report.json`: it is the first real input for all of the above.

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

### Sketch graph, marker roll and progress window

Written from the API reference and never run (sections: "Sketch graphs" in `docs/capture-format.md`, hand tests D1 and
D5 to D13). Every read is guarded: a member that raises is listed in the record's `unread` or leaves the old behaviour.

- Outline faces at each state (`lib/fusion_reader/read_face.py` `read_faces`, hand test K27): `Timeline.markerPosition`
  set to the step's index, `Design.findEntityByToken` of the face with the marker there (one face, not a split one),
  its loops read as at the capture, and the marker set back, which rebuilds the steps after it with the values tried.
- Sketch put back (`lib/fusion_reader/sketch_keep.py`, hand test K26): `SketchPoint.geometry` in sketch space,
  `isReference`, `isFixed`, `SketchPoint.move(Vector3D)` while `Sketch.isComputeDeferred` is true, and whether
  Fusion solves the sketch from the moved points (back on its first solution) once compute is turned on again and
  the design is recomputed. If it solves to the other solution again, the put back counts as a miss and the probe
  stops after two.
- Sketch graph (`lib/fusion_reader/read_constraints.py`): `Sketch.sketchPoints`, `sketchCurves`, `sketchDimensions`,
  `geometricConstraints`, `isFullyConstrained`, `originPoint`; `SketchEntity.isFixed`, `isFullyConstrained`, `isLinked`,
  `isReference`, `referencedEntity`, `entityToken`; `SketchPoint.geometry` (sketch space, cm); `SketchLine.startSketchPoint`,
  `endSketchPoint`, `isCenterLine`; `SketchArc` and `SketchCircle.centerSketchPoint`, `radius`; `SketchCurve.isConstruction`;
  `SketchDimension.parameter`, `value`, `isDriving`, `textPosition` and each dimension class's members (`entityOne`,
  `entityTwo`, `lineOne`, `lineTwo`, `entity`, `circleOne`, `circleTwo`, ...); `SketchLinearDimension.orientation`; the
  members of each geometric constraint class (`point`, `entity`, `pointOne`, `lineOne`, `curveOne`, `symmetryLine`,
  `midPointCurve`, `parentCurves`, `childCurves`, ...); `OffsetConstraint.dimension` and
  `SketchOffsetCurvesDimension.offsetConstraint`. Check that a collection item can be fetched by index, that the wrappers
  of one entity compare equal with `same_entity`, that one sketch point is shared by connected lines and that the origin
  point is the same object as the one in `sketchPoints`.
- `Sketch.sketchDimensions` with `SketchDimension.parameter.name` and `Sketch.sketchTexts` with
  `SketchText.heightParameter.name`, used to tell what a parameter made by a sketch is (`parameters.dependent_record`). The
  premise is that `ModelParameter.createdBy` of a sketch dimension's parameter answers the Sketch, not the dimension; D11
  shows which it is.
- Marker held early (`fusion_reader/rows.py` `roll_marker`, `unroll_marker`; `export_plan/marker_roll.py`): setting
  `Timeline.markerPosition` to a position before the end while parameters change; `Design.computeAll` then rebuilds only
  the items before the marker and leaves the marker in place (the store sets it back after each recompute anyway); a
  read of sketches, points, lines, references and the body box at that marker equals the read at the full marker (the
  export checks this once and does not roll when it differs); moving the marker forward again and calling
  `computeAll` builds the later items with the restored parameter values and leaves no entry in Undo.
- One change per try (`fusion_reader/rows.py` `set_expressions`, hand tests SP2 and SP4): `Design.modifyParameters`
  with `ValueInput.createByString` sets every expression or none and rebuilds once; `TimelineObject.healthState` is
  up to date after it without `computeAll`; the marker stays where it was.
- Faster tries (`fusion_reader/rows.py` `suppress_items`, `unsuppress_items`; `export_plan/timeline_trim.py`, hand
  test U1): `Timeline.item(index)`, `TimelineObject.name`, `isGroup`, and `isSuppressed` get and set on items before
  the rolled marker; `computeAll` then rebuilds without them and leaves the marker in place; setting `isSuppressed`
  back to false restores the items exactly.
- Progress window (`fusion_ui/progress.py`): `ProgressDialog.message` with a line break (`\n`) shows two lines, and
  `show` with the text "Try %v of %m" accepts the placeholders as "Size %v of %m" did. If it shows one line only, move
  the explanation (`export_plan/messages.TRY_INTRO`) to the title passed to `show`.

### Several bodies in the picker

Never run in Fusion (section 8.3):

- `SelectionCommandInput.setSelectionLimits(1, 32)`, `selectionCount`, `selection(i).entity` for several bodies, and
  `clearSelection` then `addSelection` per body to put them back (`restore_bodies`).
- `Component.entityToken`, `Component.name` and `bRepBodies.count` of a body's parent component, for the part name
  (`body_label`; any failure falls back to the body name).
- One `ReadContext` and one probe reader per body, over the same rows: each body's `read_state` finds the user
  parameters by name and its own component's model parameters; the model parameters of the other bodies read as
  missing, which only means they are not used as columns for that body.

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
- Face outlines (`read_face.py`, hand test F1): `ExtrudeFeature.profile` gives a `BRepFace` with the marker before
  the step; `BRepFace.geometry` (a `Plane`: `origin`, `uDirection`), `BRepFace.evaluator.getNormalAtPoint` at
  `pointOnFace` points out of the body, `BRepFace.loops`, `BRepLoop.isOuter`, `BRepLoop.edges`, `BRepEdge.geometry`
  (`Line3D`, `Arc3D`, `Circle3D`, `Ellipse3D`, else sampled through `BRepEdge.evaluator`, which must cover only the
  edge), `BRepFace.area`, `BRepFace.body`, `BRepFace.entityToken`; `Component.features.extrudeFeatures`,
  `Feature.timelineObject.index`, and `startFaces`, `endFaces`, `sideFaces` of the earlier extrudes holding the same
  face. A positive distance must go along the outward normal: `end_offset` of the face extrude is positive.
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
- What the translator assumes about references of other components (no new `adsk` call; R1 to R7 pin it): a face
  or plane of another component read through its occurrence has `point`, `normal` and `face_point` that, brought into
  the part's coordinates, equal the read at the current sizes; a hole placed by a point on a flat face keeps its
  place on the face while the face moves along its normal (the copy moves the hole centre by the face's offset); the
  extrude length to a face of another component is the face's distance from the sketch plane, so it follows the
  face's offset one to one.
- `HoleFeature.thread.isModeled`, `holePositionDefinition.sketchPoints[i].worldGeometry`, `position`, `direction`
  (into the material or out), `tipAngle` for a flat drill point, `participantBodies`, `sideFaces`, `endFaces`.
- `CombineFeature.targetBody`, `toolBodies`, `isKeepToolBodies`; `ThreadFeature.isModeled`.
- `CombineFeature.toolBodies` of a body in another component, in the capture of the exported body's component
  (`tool_identity`, `place.py`): the proxy's `assemblyContext.fullPathName`, `nativeObject.entityToken` (must equal the
  token that `bodies_after` of the tool's steps give) and `parentComponent`. The second reading pass
  (`fusion_reader/helper_pass.py`, G1 to G7) moves the marker to the Combine (`Timeline.markerPosition`), finds the
  native tool body with `Design.findEntityByToken` there, and reads the tool's place: `Component.xYConstructionPlane`,
  `xZConstructionPlane`, `yZConstructionPlane`, `ConstructionPlane.createForAssemblyContext(occurrence)` (in the API
  reference), `ConstructionPlane.geometry` (`Plane.origin`, `normal`) of the native and the shown plane,
  `Component.allOccurrencesByComponent` with `Occurrence.fullPathName` and `transform2`. It then rolls to each step
  that made the tool and reads it with the feature readers of its type. Check that the tool's token matches, that
  `place.frame` equals the occurrence's transform with `checked_points` 3, and that every guarded read that fails
  leaves a `place.error`, a `read_error` or a `helper_unread` in the report rather than stopping the export.
- `BRepBody.volume` of the target with the marker before and after a Combine (`volume_before`, `volume_after`): a cut
  must show a smaller volume. A null means the body could not be measured there; the volume check is skipped.
- Measuring references at each state (`lib/fusion_reader/probe_refs.py`, M1 to M6): `Design.findEntityByToken` of a
  native construction plane, axis, face or sketch point of another component after a recompute;
  `Component.allOccurrencesByComponent` and `fullPathName` to find the occurrence again;
  `ConstructionPlane`, `ConstructionAxis`, `BRepFace`, `SketchPoint.createForAssemblyContext(occurrence)` and the
  geometry of the proxy it gives (`geometry`, `worldGeometry`) in the assembly's coordinates at the state's own
  occurrence place, equal to the capture's at the first state; `BRepBody.createForAssemblyContext(occurrence)` of the
  target, to read the target's own place again at each state (`read_placement`). Every one is guarded: a failure
  leaves that reference unread with a reason (`probe.states[].read.unread`), never stops the probe.
- The direction of a rectangular pattern taken from an entity of another component
  (`directionOneEntity` / `directionTwoEntity`, `read_repeat._foreign_direction`): its `geometry` or `worldGeometry`
  in the assembly's coordinates, turned into the target's frame (M5).
- Entities of another component (`ref_record` in `placement.py`): `entity.assemblyContext.component` and `.fullPathName`
  of a proxy plane, axis, face, sketch line or sketch point; `entity.nativeObject.entityToken`; `BRepFace.body` and
  `SketchPoint.parentSketch` of the native entity; the origin members of the owning component
  (`xYConstructionPlane`, `xConstructionAxis`, ...). Check in `report.json` that `ref.component` is the component that
  owns the entity, `ref.token` finds it again, and that the geometry of a proxy (`geometry` of a plane or face,
  `worldGeometry` of a sketch point or line) is in the assembly's coordinates, as the move into the target's
  coordinates assumes (R1, R2, R5).
- `HoleFeature.holePositionDefinition` of a hole on a face, plane or edge: the members are read by definition type
  (`PointHolePositionDefinition`: `planarEntity`, `point`; `PlaneAndOffsetsHolePositionDefinition`: `planarEntity`,
  `edgeOne`, `edgeTwo`; `AtCenterHolePositionDefinition`: `planarEntity`, `centerEdge`); any other type, the edge
  placement among them, is tried through every name (`edge`, `edges`, `face`, `plane` and the like) and may not all exist.
  The member names are from memory of the API reference and not confirmed on a live Fusion: check each. A hole on a face of another component that is
  not marked `foreign` means none of them answered (R4). `HoleFeature.direction` of a hole on sketch points of another
  component is taken as given: check it points into the material in R5.
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

### Symmetric patterns

Written from the API reference and the owner's 0.7.2 export, never run on the new code.

- [ ] A rectangular pattern of an extrude with its round and chamfer, **Symmetric** on, an odd count taken from a
      count parameter and an `Extent` distance written as a formula of a length parameter. Export. The copies sit at
      `step` apart from the original (in the middle), `step = 2 * extent / (count - 1)`. In Paramability, change the
      length parameter: the copies follow. The count parameter is marked, since the rounds of the copies are placed one
      by one and an odd count may become even. Without the round and chamfer, an odd count follows the parameter.
- [ ] Same with an even count (4 or 6) and **Spacing** as the distance. Look at where the copies really are:
      `report.json` `elements` shows each origin. The export expects the original to be one of the two middle copies.
      If the original is not among the elements, the export stops with "sits between two copies"; note which Fusion
      version did that.
- [ ] Symmetric in both directions (3 by 3). The copies fill the grid once.
- [ ] A circular pattern over 90 degrees with **Symmetric** on and 5 copies: the copies sit at -45, -22.5, 0, 22.5, 45
      degrees from the original.
- [ ] Members read: `RectangularPatternFeature.isSymmetricInDirectionOne` and `isSymmetricInDirectionTwo`,
      `CircularPatternFeature.isSymmetric` (a flag that fails reads as not symmetric, then the measured copies are
      refused). Which element is the identity (not always the first).

## Capture reader calls to watch (tool bodies)

These members were written from the API reference and never run. A member that cannot be read gives `null` or `other`,
and the translator refuses the item, so a wrong guess shows up in `report.json` as a refusal. Run B1 to B12.

- `CopyPasteBody.sourceBody` (a collection in the API stubs) with the marker before the item (empty or shorter when a source was consumed), `CopyPasteBody.bodies`
  after it, also for a source in another component (`read_paste.py`).
- `MoveFeature.inputEntities` (bodies, or faces: a mix is `other`), `MoveFeature.definition` and the class it names
  (`TranslateXYZ`, `Rotate`, `FreeMove`, `PointToPoint`, `PointToPosition`, `TranslateAlongEntity`),
  `xDistance`, `yDistance`, `zDistance`, `isDesignSpace`, `angle`, `axisEntity`, `distance` (along an entity) and
  `transform` of the free move definition (when it cannot be read, the fit against the points decides alone)
  (`read_move.py`).
- The first 8 vertices of a body (`BRepBody.vertices`, `BRepVertex.geometry`) in a stable order: with the marker before
  a Paste, a Move or a pattern, and again after it for the same body found by its token. A gap in the list gives an
  empty list, which refuses the fit.
- `inputEntities` of a rectangular, circular or mirror pattern of bodies (`entity_type` `bodies`) with the marker before
  the item, and `bodies` after it: all the copies, not the sources. `PatternElement` has no bodies, so copies are matched
  to elements by their corner points (`body_copies.match`).
- `BRepBody.volume` of each tool with the marker before the Combine, and of the bodies the second pass finds by token
  (`body_states`).
- `TemporaryBRepManager.get()`, `copy`, `booleanOperation` and `BooleanTypes` (`IntersectionBooleanType`,
  `UnionBooleanType`), and the `volume` of a temporary body, for an intersect of several tools
  (`read_intersect.py`). Nothing is added to the design: check that the timeline and the bodies are the same after.

## Capture reader calls to watch (emboss)

These members and values were written from the API reference and never run. A member that cannot be read gives
`null`, which the translator refuses, so a wrong guess shows up in `report.json` rather than as a wrong part. Run the
Emboss tests of section 10 and read the capture in `report.json`.

- `adsk.fusion.EmbossFeature` itself: it came with the September 2025 release and the API reference marks it as
  preview, so members may change. A Fusion build without it cannot hold the step (E5).
- `EmbossFeature.profiles` with the marker just before the item: `Profile` and `SketchText` items on one plane (a
  flat face, if the dialog takes one: E7). Fusion 2706 gives them without `count` and `item` (a list or a vector);
  the reader takes lists, collections and vectors. A text item is read as outlines (X1).
- `EmbossFeature.inputFaces` with the marker just before the item: Fusion 2706 gives a `BRepFaceVector`, which has
  only len and indexing, no `count` or `item`. Every collection reader accepts lists, collections and such vectors,
  and raises when it cannot list them. A lone input face also gets its loops read as for an extrude face (`outline`).
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

## Capture reader calls to watch (sweep and loft)

These members were written from the API reference and never run. A member that cannot be read, or that the running
Fusion build does not have, gives `null` in the capture of the step, so a wrong guess shows up in `report.json` and
the step is left out as a gap. Export a design with a sweep (straight path, a path of lines and arcs, a closed circle, a path
of body edges, a guide rail) and one with a loft (two outlines, a point end, a tangent end, rails, a centre line,
Closed on), and read the `data` of each step.

- `SweepFeature.path` and `guideRail` as `Path` objects: `Path.count`, `Path.item(i)` and `Path.isClosed`. Note the
  order of `curves` and the `opposed` flags for a path drawn from the far end towards the outline.
- `PathEntity.entity` is a sketch curve or a `BRepEdge`. The reader maps `SketchCurve.geometry` (assumed to be in
  sketch space) with the sketch's `transform` into the component frame. `PathEntity.curve` is read only as `check`
  (its start and end). In a design where the component is moved in the assembly, `check` and `curves[].start` and `end`
  must agree in the component's frame. A 3D sketch path must keep `flat` null for curves off the plane.
- `BRepEdge.geometry` (native object, component frame) for path edges, and the edge records in `path.edges`. An edge
  of another component must be marked `foreign`.
- `SweepFeature.orientation` (`SweepOrientationTypes`, read as `perpendicular` or `parallel`), `profileScaling`
  (`SweepProfileScalingOptions`, read as `scale`, `stretch` or `none`) and `extent`. Check which of these exist in the
  running Fusion build: `extent` in particular may be missing and then reads as null.
- `distanceOne`, `distanceTwo`, `taperAngle` and `twistAngle` as `ModelParameter`s: `distance_one` and `distance_two`
  are assumed to be the share of the path (1 and 0 for a full sweep). Note the values for an outline at one end and in
  the middle of the path, and the sign of the taper and the twist.
- `SweepFeature.startFaces` and `endFaces`, and `LoftFeature.startFace` and `endFace`, with the marker after the item
  (`faces_after`): a point on each made end cap and its outward normal.
- `LoftFeature.loftSections` and `LoftSection.entity`: the entity type decides the section kind (`Profile`, a sketch
  or construction point, `BRepVertex`, `BRepFace`, a `Path`). Note which type a point end gives.
- `LoftSection.endCondition` type names (`LoftFreeEndCondition`, `LoftDirectionEndCondition`,
  `LoftTangentEndCondition`, `LoftSmoothEndCondition`, `LoftPointSharpEndCondition`,
  `LoftPointTangentEndCondition`) and their `angle` and `weight` members (read as model parameters when they are).
  A name that does not match reads as `other`.
- `LoftFeature.centerLineOrRails` (`count`, `isCenterLine`, `item(i)`): what it returns when the loft has neither
  (assumed null or an empty collection, read as no rails), and `isClosed`, `isTangentEdgesMerged`.

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

## Capture reader calls to watch (reach)

Written from the API reference and never run (`lib/fusion_reader/read_gap_reach.py`, used only when the first
translation left steps out). A read that fails gives `reach: { read: false, error }` and the translator leaves out
every later step that picks geometry, so a wrong guess shows up as too many left out steps and not as a wrong part
(L2, L3).

- `Timeline.item(index).entity.faces` (`Feature.faces`) with the marker just before a later step: the faces that step
  created, as `BRepFace` objects. A feature type that has no `faces`, or whose faces cannot be read, counts as a
  maker of every pick. Check it for an extrude, a revolve, a sweep, a loft, a fillet, a chamfer, a shell, a pattern,
  a combine and a move, and that the faces of an earlier feature that a later round cut into are still found.
- `BRepEdge.faces`: the faces an edge joins (a picked edge is traced to the faces it touches).
- `Design.findEntityByToken(token)` for a picked edge or face: a list of entities (a split face gives several); the
  reader takes the native object of each. A face is also found with `Component.findBRepUsingPoint(point,
  BRepEntityTypes.BRepFaceEntityType)` at the recorded point.
- Two entities are the same face when `entityToken` matches or `geo.same_entity` says so.
- `Timeline.markerPosition = index` for each tested step, and back to the start marker at the end: after a read the
  marker must be where it was (`MarkerError` stops the export otherwise). The marker visits each position once, so
  the read moves it about once per tested step. Measure it on L2 and on a part with a run of rounds after the coil:
  `reach.moves` in `report.json` is the number of moves (the move back is not counted); note it with the
  seconds the export waits before the result window. A move that takes long in Fusion (a design that rebuilds
  slowly) is the number to report.
