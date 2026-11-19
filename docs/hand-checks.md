# Hand checks

The short way to check a release by hand. Export your usual projects, compare with the last release, then look at
the 10-second check in Fusion. The long list of single checks is `docs/hand-tests.md`; use it only when a section
here points to it.

## After every release

Export the same projects as last time. Keep the old result window text and `report.json` to compare. In each case
"same or better" means: not fewer steps copied, not more steps left out, no new size marked "may give unexpected
results", no narrower cut range, and the copy in Paramability still matches the Fusion part.

### A box with a lid (shell, fillets, emboss on a flat face)

- Steps copied: the shell, the fillets and the emboss are in the copy, none newly left out.
- Marked sizes: wall thickness and fillet radius move the part, and the cut range stops before the fillet or shell
  fails, not much earlier than last time.
- In Paramability: change the wall size and the lid still fits the box; the emboss stays on its face.

### A part with angled extrudes and patterns (reach to a face, symmetric pattern)

- Steps copied: extrudes that reach to a face or plane, and patterns (also symmetric ones), are copied.
- Marked sizes: an angle size moves the points the way Fusion does; the pattern count and spacing follow.
- In Paramability: a "to face" extrude still ends on that face at other sizes; the pattern keeps its copies.

### A messy part (sweeps, lofts, splits, combines)

- Steps copied: this part usually has left-out steps. The number should go down or stay. A step that was left out
  before and is copied now must match the STEP.
- Left-out steps: each one has a reason in the window. A new reason, or a step left out that was copied before, is a
  regression.
- Cut ranges and match: ranges are not narrower; the copy matches the STEP at the default size.

### The put back, one body and several bodies

When a release changes how an export ends (the put back of values, steps, sketches and the timeline marker), export
one single body and one design with several bodies picked, each with sizes that move a sketch. Compare `report.json`
with the last release: `health` and `probe.timeline` hold the same keys and values (times aside). Then do the
10-second check below on both designs.

### The 10-second check in Fusion after each export

- The timeline marker is back at the end (or where you left it).
- No step is newly in warning or error (yellow or red).
- The sketches look the same: same outline, not flipped, not moved.
- Open the parameters table: the user parameters show their formulas, not plain numbers, and the same values as
  before the export.
- If something is off, use Edit, Undo once and see "When something looks wrong". With "Lighter on memory" ticked, Undo may not step back through the export: close the design without saving and open the version you saved before.

### The export trail

Model any small part with two user parameters that a sketch uses, for example a plate `Width` by `Depth`, 3 mm high.
    Export: export it with both parameters ticked. While the result window is open, open
    `%TEMP%\ParamabilityExport\export-trail.log`. It starts with "start: export" and ends with "end: export". It
    lists "start item" and "finish item" for each timeline step, the marker moves, a "try" line for each size try with
    its values, "recompute: start" and "recompute: end" pairs, and the "STEP file" lines. Pick another body in a new
    dialog: the file then starts again with "start: read the steps". The export takes about as long as before.

### A pattern that repeats a Combine

Model a 60 x 40 x 5 mm plate. Extrude a 6 mm square post 8 mm up from its top face as a new body, combine (join) it
with the plate, then cut a 3 mm hole through the post with a one-sided extrude cut. Make a rectangular pattern of
features of the post extrude, the Combine and the cut: 3 copies 15 mm apart along X.
    Export: export the plate with no parameters ticked. Fusion does not close. In `report.json` the pattern item has
    `faces_skipped: "unsafe inputs"` and its elements have no `faces`. Afterwards the design is as before.

## When something looks wrong

Open `report.json` from the export. The field layout is in `docs/capture-format.md`, section 6 ("Report and
capture file"). Open these first:

1. `health`: whether the design was put back (`restore_unverified`, `flipped`, `broken`, `tries_stopped`) and how
   far sketches drifted (`sketch_gap_mm`, `sketch_drift`). Any `broken` entry means the design changed: use Undo, or reopen the saved version when `undo_dropped` is true.
2. `timing`: where the time went (section 6, "Timing"). A slow export shows up as one large entry, often the tries.
3. `refusal` (on a body saved as a fixed shape): the step that stopped the copy and why.
4. `after_stop`: what a walk past that stop finds, so you see which later steps were not copied either.
5. `gaps`: each left-out step with its reason. Their meaning and the gaps file are in `docs/recipe-gaps.md`.

Also read `probe.dropped` (sizes that did not work, with the failing step), `probe.cut` (ranges that were cut) and
`probe.timeline` (how many items each try rebuilt).

## Small test models

Only the checks your own projects do not cover. Each says what to model and, under it, what to do and watch.
Longer wording and past results are in `docs/hand-tests.md` under the same id.

1. SB2, split by a body core. Model a 100 x 100 x 20 mm plate and a cylinder body (kept) of 30 mm diameter through
   it. Split Body the plate with the cylinder, and remove the piece inside the cylinder. Second design: keep the
   inside piece instead.
   Export: export the plate, then the inside piece. Expect a cut by the cylinder for the plate and an intersect for
   the core, and both copies match the STEP. A split by a curved face of a body stops with "curved surface".
   Also check the fallback: when Fusion's point containment gives no answer for a face of a piece, the add-in
   intersects temporary copies of the piece and the tool. Note in `report.json` whether every piece of the split has
   `inside` set, and compare an export from this version of the plate split with the old one: both copy.

2. SB1, split by an offset plane. Model a box with a shell and a fillet. Add a construction plane offset from the
   top face by a user parameter `Cut`, Split Body with it and Remove the upper piece.
   Export: tick `Cut`. Changing `Cut` in Paramability moves the cut. Give `Cut` a range above the box: the export
   must say the tries stopped early and name the Remove step, and Undo brings the design back.

3. DR1, draft directions. Extrude a box from a sketch on the XY plane. Draft two side faces by 3 degrees from a user
   parameter, with the XY plane as the fixed plane. Make a second copy with the direction flipped and a third with a
   negative angle.
   Export: each copy leans the same way as in Fusion. (A "Symmetric" draft that crosses the plane is copied: see DR2.)

4. TH2, a sketch with two solutions. Sketch a triangle: one corner on the origin, one 40 mm along X, the third
   placed only by two distances (`Arm` = 30 mm from the origin, 35 mm from the second corner), no other constraint,
   so it can flip below the X axis. Extrude 10 mm and fillet one top edge with 2 mm.
   Export: tick `Arm` with a range of 5 to 80. `health.flipped` may name the sketch. Afterwards the triangle is on
   the same side as before, the fillet has no warning, and `health` has no `steps_changed` and no `deferred_left`.

5. SW9 and LF3, sweep and loft inputs. Sweep a small closed profile along the closed edge loop of a box top face,
   once as Single path and once as Path + Guide Surface. Then loft from a closed loop of a body's edges (picked as
   edges) to a sketch profile above it.
   Export: the single path sweep copies; the guide surface sweep is left out and names the settings Fusion did not
   give; the edge loft names what Fusion gave for the section.

6. ST1, steps with their own reason. Model a 40 mm box and use Modify, Scale on it together with a sketch; on a
   second box add a Rib (a sketch line across a shell) and a Web; on a third use Replace Face with a surface, Pattern
   on Path along a sketch spline, and Boundary Fill between two bodies.
   Export: each part is left out or saved as a fixed shape with a step name and a plain reason (not "Steps of type
   ..."), and a tip in `gaps.json`. In `report.json` note the capture `type` of each step: the add-in expects
   ScaleFeature, ReplaceFaceFeature, RibFeature, WebFeature, PathPatternFeature, BoundaryFillFeature and (surface
   Offset) OffsetFeature; any other name gets the generic reason.

7. CC5, a lid that follows a box not in the file. Make component Box with user parameter `Width`. In component Lid,
   sketch on the box top face, project the box outline, offset it 0.2 mm inwards and extrude 3 mm.
   Export: export the Lid alone, tick `Width`. The notes say the part follows the sizes of Box. Export Box and Lid
   together: that note is gone, and changing `Width` in Paramability changes both parts.

8. CC1, a cut from the top level. Make components Box and Lid (a box 80 x 60 x 30 mm, a lid 80 x 60 x 3 mm on top).
   With the top level active, sketch two 3 mm circles on the lid top and cut them through both bodies.
   Export: export the Lid. The copy stops at the cut with "changes this part from another component" and a tip to
   move the step into the part's component or export both parts together.

9. AS1, steps after a stop. Extrude a box, split it with the curved face of a cylinder body and remove the outer
   piece, then add a thicken joined to the box.
   Export: the box is saved as a fixed shape with the split as the reason, `after_stop` names the split and the
   thicken, and the window says the thicken was not copied either.

10. SP1, marker roll. Make component Cup (60 mm square sketch from user parameter `Width`, extruded 40 mm), then
   component Rack with about 100 steps (a pattern of 200 holes, fillets, chamfers).
   Export: tick `Width` on the Cup. `probe.timeline` has `rolled: true` and fewer items than the whole design, and
   the time per try is about the time of the Cup alone.

11. SP2, one change per try. In the SP1 design add user parameter `Height` for the extrude and a 5 mm fillet on the
   top edges; give `Width` a range down to 8 mm so the fillet fails at the low end.
   Export: tick both. The failing tries are listed in `probe.dropped` with the fillet named, the `Width` range is cut,
   and the design shows its old values with no step in error afterwards.

12. SP4, memory and Undo. Use the SP2 design.
   Export: watch Fusion in Activity Monitor (Memory) before, during and after; then use Edit, Undo once. Note the
   peak, the value after the export and after Undo, and whether Undo lists the export as one step.

13. TH1 and TH5, steps after the export. TH1: a box from a 20 by 20 mm rectangle (user parameter `Width` = 20 mm)
    extruded 15 mm, the four vertical edges filleted with 9.9 mm. TH5 needs a second design: a 40 by 30 by 20 mm box,
    the vertical edges filleted with user parameter `Round` = 5 mm, then the top edges chamfered with `Bevel` = 4 mm,
    so the chamfer runs into the fillets.
    Export: TH1, tick `Width` with a range of 12 to 40. The low tries fail at the fillet and the range is cut; after
    the export the fillet has no warning and `health` has no `steps_changed` (`steps_recovered` and `end_actions` may
    show the add-in rebuilt the design). If `steps_changed` is there, note each `name`, `before`, `after` and
    `message`, then use Edit, Undo and count the steps that bring the fillet back. TH5: tick `Round` and `Bevel` (range 1 to 9) and
    cancel in the "Try 3 of ..." window; then, on the TH1 box, use Export size choices with a row `Width` = 12, which Fusion cannot build. In both, every step is
    as before; if not, a message box names the step and says to use Undo.

14. LP1, the list before the export. Extrude a 40 by 30 by 20 mm box. Round one vertical edge with a variable radius (a
    different radius at each end and a third radius at its middle). Then round the top edges with 1 mm, which includes
    the edge between the top and the face the variable round made. Add a second body, a plain box with no such step.
    Export: pick the first box and do not click OK. Under the body picker a box lists the variable round with the
    reason and "Tip: Give the changing radius a fillet of its own with one edge and no radii between the ends.", and
    says "More may show after the export." (the 1 mm round picks
    faces that only the export can check). Pick the second box: the list is gone. Pick both: the list starts with
    the first box's name and says "More may show" once. The Text Commands window has a line "warning under the body
    picker: ... s; reading the steps of the picked bodies: ... s". Then click OK on the first box: the Saved window
    names the variable round with the same reason and tip, and any step of the 1 mm round it also lists is the one
    the "More may show" line was about. Note the seconds from the log line on a design with 100 or more steps: the
    warning itself should take well under a second.

15. LB1, size labels. Model a 40 x 30 x 10 mm box from three user parameters: `Wall_thickness_mm` (3 mm, comment
    `Wall thickness`), `BaseCup_midExtrude_offset__mm` (5 mm, no comment) and `Hole_diameter_mm` (6 mm, a comment of two
    long sentences describing the hole).
    Export: tick all three. In Paramability the form reads "Wall thickness", "Base cup mid extrude offset" and "Hole
    diameter". Each field has an info tip "Name in the original design: ..." with the Fusion name, the long comment is
    the text under the "Hole diameter" field, and the result window still lists the sizes by their Fusion names.

16. CO1, a coil on a block. Model a 40 x 20 x 10 mm block. Make a Coil with Insert > Coil (Fusion's Coil command) on a
    plane at the top of the block: diameter `CoilDia` = 10 mm, section size `Wire` = 2 mm, revolutions 3, height
    `CoilHeight` = 12 mm, round section, section position inside, clockwise, operation Join. Make a second design with
    a square section, counter clockwise and "Revolutions and Pitch" (pitch 4 mm).
    Export: tick `CoilDia`, `Wire` and `CoilHeight`. `report.json` has `items[].data` of the coil with `roles`,
    `params`, `volumes_before`, `made` and `faces` (two flat end faces and sampled edges); the copy has a `coil` step,
    and in Paramability the coil matches the Fusion one (same hand, same rise, joined to the block). Changing `Wire`
    or `CoilDia` moves the coil as in Fusion. The ranges stop before the wire reaches the axis or the turns touch.

17. CO2, coils the copy leaves out. In the CO1 design add a coil each with: a taper angle of 5 degrees; type Spiral;
    revolutions 2.5; a triangle section. Join each to the block.
    Export: the taper, the spiral and the 2.5 revolutions coils are left out with their own hint. The triangle coil is
    copied with its numbers (`Wire` and `CoilDia` are marked, not followed).

18. CO3, coil as a tool and the caps. Make a coil as a New Body, then Combine it (Join) with the block. Repeat to get
    more than 8 coils in one design (or 17 coils joined one by one).
    Export: the Combine of a lone coil body is copied as a plain coil step. From the ninth coil on, the coils are left
    out with the hint about 8 coils and 100 turns of coils and threads; the first eight stay. A coil body that also has a cut or a fillet
    in its tool is left out with the hint to join the coil before changing it.

19. TD1, modeled threads. Make a jar: a cylinder body of 30 mm diameter and 20 mm long (user parameter `Neck` for
    the length), and add a Thread (Create, Thread) on its side with "Modeled" ticked: an ISO Metric profile, M30x2,
    full length, right hand. Make a second design with a left hand M20x1.5 thread over only 10 mm of a 25 mm long
    cylinder, started from the lower end. Make a third with an ANSI Unified thread, and a fourth with an ACME thread.
    Export: tick `Neck`. In `report.json`, the item of the thread must hold `thread_type`, `pitch` (2.0, from
    `threadPitch`), `angle_deg` (60, or null), `major_diameter`
    (30.0), `minor_diameter`, `pitch_diameter` (between the minor and the major diameter, from `pitchDiameter`),
    `right_hand`, and a `faces` entry with `radius` 15, a `span` and `outward` true. If
    a number is missing or 10 times too big or too small, the units of the thread info differ from the reader's guess
    (cm). The thread copies as a `thread` step; the metric and Unified ones copy, the ACME one is left out with the
    hint about 60 degree threads. Changing `Neck` in Paramability changes the thread length. In the partial thread
    design, `made_span` must show where the made faces lie along the axis, and the copy must start at the same end.
    Compare the volume of the copy with Fusion: the threads differ a little in the crest and root shape, note by how
    much. In Fusion, also check what start angle the thread has: the copy always uses its own.

20. TD2, threaded and up to a face holes. Make a plate 40 x 40 x 12 mm with a tapped Hole (Hole tool, "Tapped",
    "Modeled" ticked, M6x1) 8 mm deep with full length thread, and a second one with a thread length of 5 mm. Make a
    through hole with a modeled M5 thread. Then make a Hole whose extent is "To" an inner floor (a second box body
    or a stepped pocket), and one up to a body.
    Export: each tapped hole copies as a hole at the minor diameter plus an internal `thread` step. In `report.json`
    the hole item must hold `thread` (read from `HoleFeature.tappedHoleInfo` and the hidden thread feature
    `HoleFeature.thread`, Fusion September 2025 and later) with `pitch`, `major_diameter`, `minor_diameter`,
    `right_hand`, `full_length`, for the 5 mm one `depth` 5.0 and `offset` 0, and `made_span` starting near 0 and
    ending near the thread length. Fusion 2706 gave `full_length` false for tapped holes made with the default
    settings, also through all: note the thread length Fusion shows in the Hole dialog, and check that `depth` is that
    length and that the copy's thread is as long. Check also what `sideFaces` holds for a modeled thread (the bore cylinder, or only the helical
    faces); the copy cuts the bore at the minor diameter from the thread info. The holes up to a face and a body copy
    as blind holes of the measured depth, and when the floor follows a parameter the hole depth follows it. A hole up to a
    face that ends in a drill point is left out with a reason.

21. FM2, a formula of numbers. Model a 40 x 40 x 20 mm box, shelled with the user parameter `Wall = 3 * 0.4 mm`.
    Export: `Wall` is a size and starts ticked. Changing it in Paramability changes the wall. After the export, the
    Parameters dialog in Fusion shows `3 * 0.4 mm` again.

22. FM3, a guarded count. On a 100 x 40 x 5 mm plate, cut one 5 mm hole and make a rectangular pattern of it with
    quantity `max(1; floor(Width / 20 mm))`, where the user parameter `Width = 100 mm` drives the plate.
    Export: tick `Width`. The hole count follows `Width` in Paramability, and `Width` has no warning mark. Repeat
    with the quantity `if(Width > 60 mm; 3; 2)`.

23. FP1, a fixed part in a parts package. Make component Box (an 80 x 60 x 30 mm box from user parameter `Width` =
    80 mm) and component Lid (80 x 60 x 3 mm on top of the box, sketch size from `Width` too). Add to the Lid a Split
    Body by the curved face of a cylinder body, so the Lid copy stops (see AS1).
    Export: pick Box and Lid together. The Lid is a fixed shape and the Box has a recipe. `Width` is marked "may give
    unexpected results" with "Lid stays a fixed shape in this file and does not change with this size." in the
    result window and in `report.json` `sizes.loose`. A size that only the Lid reads (add a second user parameter
    used by the Lid alone) is not offered at all.

24. PC1, a part that comes apart. Model a 80 by 20 by 5 mm plate whose length is user parameter `Width` = 80 mm,
    with the left end fixed at x = 0 and the right end at `Width`. On its top face draw a 4 mm circle at x = 70 and
    extrude it 5 mm up with Join. Second design: the same plate with a 2 mm wide slot cut across it at x = 40, 4 mm
    deep, its depth user parameter `Slot` = 4 mm.
    Export: in the first design tick `Width` with a range of 40 to 160; in the second tick `Slot` with a range of 2
    to 8. In `report.json`, the tries below 68 mm (first) and at 5 mm or more (second) have `pieces` 2 in
    `probe.states` and an entry in `probe.dropped`; each range is cut with "the part comes apart into 2 separate
    pieces in Fusion at ...". Note for each design whether the post or the second half shows as its own body in the
    browser at such a value or as part of Body1, and `timing.probe.read_parts.pieces` against `read_parts.box`.

25. TL1, the time limit of the size tries. Model a part that is slow to rebuild: a 60 x 40 x 20 mm box with a shell
    and a rectangular pattern of 300 small holes (all in one component), and user parameters `Length` = 60 mm and
    `Width` = 40 mm for the box sketch, `Wall` = 2 mm for the shell, and `Count` = 300 for the pattern. Mark `Length`
    as a favourite in Fusion.
    Export: open the dialog, set "Stop the size tries after" to 1 minute, tick `Length`, `Width`, `Wall` and `Count`. In
    the "Trying" window the third line shows "Time spent" and "About ... left (limit: 1 min)"; the estimate does not
    go past the limit. At the limit the window closes, and the result window says "The size tries stopped at the time
    limit (1 min)" and how many sizes were not tried. `Length` (the favourite) is tried first, so it is not among them.
    Each size left out is "may give unexpected results" (or "not a size") with "the tries ran out of time before this
    size was tried" and "Tip: raise the time limit in the export dialog, or untick sizes that need no change". In
    `report.json`, `probe.time_limit` is `{ limit_seconds: 60, hit: true, left_out: [...] }`, `timing.probe.time_limit`
    has the same, and `health` has no `tries_stopped`. Afterwards the 10-second check passes: the marker is at the end,
    no step has a warning, the parameters show their formulas, and Undo has no extra step. Export again with 30 minutes
    (or "No limit"): `hit` is false and every size has its tries. If the rebuild is fast on your machine, add more
    holes to the pattern until a try takes a few seconds.

26. HE1, a hole that reaches the edge of its face. Model a lid, 60 x 40 x 3 mm, whose length is user parameter `Width`
    = 60 mm (left end fixed at x = 0). Cut a round hole of 16 mm diameter through it at x = 30 mm, then use Emboss to
    raise a 10 mm triangle 0.5 mm on its top face, half over the hole.
    Export: tick `Width` with a range of 10 to 120. The range starts just above 38 mm (the hole ends at x = 38), with the reason
    "the outline of the face ... would cross itself, lose a corner or have a hole reach its edge". In Fusion, set
    `Width` to 40 mm and then to 36 mm: at 36 mm the hole breaks the edge of the lid and the face is a different
    shape, so Paramability must not offer that value. In Paramability, set `Width` to the smallest value: the
    triangle is trimmed to the lid and is not left floating.

27. OC1, a tool made by an intersect, for Export for Orca. Model a 60 x 40 x 10 mm plate (Body1) with its corner at
    the origin. Make three bodies that overlap near the middle of the plate, each 10 mm high from the plate's base: a
    20 x 20 mm box (Body2) from x = 20, y = 10, a 20 mm cylinder (Body3) centred at x = 30, y = 20, and a 10 x 20 mm
    box (Body4) from x = 25, y = 10. Combine Body2 with Body3 and Body4 as tools, Intersect, without "Keep Tools".
    Then Combine Body1 with Body2 as Cut.
    Export: Export for Orca with Body1. In `report.json` the first Combine has `body_states` for Body2 with
    `volume_before` and `volume_after` (its own `intersect_model` is read on Body1 and does not count). The Orca copy
    cuts the shape that Fusion cuts (compare it with the Fusion part from above), and the result lists no step left
    out. If `body_states` is missing, the Cut is left out with the reason that the intersect rule is not known.

28. OC2, one chamfer step with two sizes, for Export for Orca. Model a 40 x 20 x 10 mm plate with its corner at the
    origin. In one Chamfer step, pick the four top edges as one set with 1 mm and the four bottom edges as a second set
    with 2 mm (Fusion shows two edge sets, each with its own distance).
    Export: Export for Orca with the plate. The result lists the step as copied as 2 Orca features: a chamfer of the top
    edges of 1 mm and a chamfer of the bottom edges of 2 mm, and a note that the copy makes one chamfer for each size.
    In Orca the part has the volume of the Fusion part (7712 mm3). Pick one top edge with 1 mm and the other three with
    2 mm instead: the step is left out with the reason of the different sizes.

29. EX1, extrude sides that the measured end face checks. Model a 40 x 40 x 20 mm box with its base on the XY plane.
    On a sketch on the XZ plane at the box's middle (y = 20) draw a 10 mm circle at x = 20, z = 10 and cut it with
    Extrude, Two Sides: side one 30 mm (past the box), side two 10 mm (it ends inside the box). Add a second box with
    a construction plane offset 30 mm above the XY plane, and extrude a 10 mm square up to that plane with a taper of
    5 degrees. Add a third extrude that starts From the top face of the first box with an offset of 2 mm.
    Export: tick no size. In `report.json`, note `end_offset` of the two sided cut (a face of side two at 10 mm or
    one at another place), and note `params["side_one.taper_deg"]` of the extrude to the plane. The two sided cut is
    copied with side one along the stored direction. The tapered extrude to the plane is copied with its taper and
    ends on the plane. The extrude from the face with an offset is copied 2 mm from the face, on the side where
    Fusion put it; its `start_offset` in `report.json` is the measured start face (EX4 checks both signs).

30. OC3, the left out steps under the body picker of Export for Orca. Model a 40 x 20 x 10 mm plate with its corner at the
    origin, then add a Thicken step on one of its faces (a type that the copy does not make), and a Coil step.
    Export: open Export for Orca and pick the plate. Under the body picker the dialog lists "Likely left out of the
    copy:" with one line for each of the two steps: "name: reason", and "Tip: ..." for the Thicken step (build the
    solid with an extrude, sweep, loft or shell) but no tip for the Coil step (the coil tip is about Paramability).
    Pick no body: the list goes. Export: the result window lists the same two steps with the same words. Then remove
    both steps and pick the body again: no list shows.
31. OR24, places that Export for Orca writes as numbers. Model a 40 x 20 x 10 mm plate with its corner at the origin.
    Add a construction plane offset from the YZ plane by a user parameter `cut_at` (25 mm), and Split Body the plate
    with it. Add a user parameter `mirror_at` (5 mm), a construction plane offset from the XZ plane by it, and a
    small boss (5 x 5 x 5 mm) on the top face that you mirror across that plane.
    Export: Export for Orca with the piece from x 0 to 25, `cut_at` and `mirror_at` ticked (OR24 in
    `docs/hand-tests.md` adds a circular pattern). The result window shows
    both as kept as fixed numbers, with the reasons "Split1 cuts along a plane that may move with it" and "Mirror1
    mirrors across a plane that may move with it", never as not used. The copy matches the Fusion part at the values
    of the export.
32. EX2, a two sided cut through ribs: which end face Fusion lists. Model a 40 x 40 x 20 mm box with its base on the
    XY plane, shell it 2 mm with the top face removed, and extrude four ribs 0.6 x 2 mm up the full height on the
    inside of each wall. Sketch a 3 mm tall slot on the YZ plane across the whole width at the bottom, and cut it
    with two sides: side one 30 mm (out through the +X wall), side two 18.5 mm (ending inside the -X wall).
    Export: in `report.json`, note `end_offset`, `end_area` and `end_normal` of the cut. Expect a face whose
    `end_normal` is parallel to X when Fusion lists one (an end cap at -18.5 mm, `end_area` about the slot area
    inside the wall), else a rib wall with a normal across X and a small area. Either way the cut is copied in both
    outputs; write down which face Fusion listed first and whether `endFaces` held a cap at all.
33. OC4, a rectangle centred by its diagonals, for Export for Orca. Add user parameters `Width` 40 mm and `Depth`
    30 mm. On the XY plane draw a 2 point rectangle, two construction lines from corner to opposite corner, and a
    sketch point; make the point coincident with both construction lines (no midpoint constraint) and with the
    origin. Give the sides the dimensions `Width` and `Depth`, and extrude it 10 mm.
    Export: Export for Orca with `Width` and `Depth` ticked. Both follow their Orca variable ("Extrude1 sketch width"
    and "Extrude1 sketch height"), with no "keeps its numbers" reason. In Orca set Width to 60: the box stays centred
    on the origin and is 60 mm wide, as in Fusion.
34. JT1, a size of a joint that moves a face the part reaches to. Make component Base: a 60 x 40 x 5 mm plate.
    Make component Post: a 10 x 10 mm square sketch on its XY plane. Make component Cap: a 30 x 30 x 3 mm plate. In
    the top level, ground Base, join Post to the top face of Base with a rigid joint, and join the bottom face of Cap
    to the top face of Base with a slider joint along Z whose offset is user parameter `Lift` = 40 mm, so Cap floats
    40 mm above Base. Activate Post and extrude its square "To object" up to the bottom face of Cap.
    Export: export the Post body and tick only `Lift`. In `report.json`, `probe.motion.refs` lists the reach of the
    extrude with an empty reason, and `probe.motion.values` has a `.../r/side_one/offset` key with a term of `Lift`.
    In Paramability the post grows as `Lift` grows; `Lift` is a loose size with "it moves a joint". Afterwards Cap
    sits 40 mm above Base as before, `Lift` is 40 mm, and no step or joint is in warning.
35. OR26, a pattern along an edge of the part and a tapped hole through all. Add user parameters `Tilt` = 20 deg and
    `Plate` = 10 mm. On the XY plane draw a triangle with corners (0, 0), (60, 0) and (0, 40): fix the bottom side
    60 mm long on the X axis and the left side on the Y axis, and give the angle at (60, 0) between the bottom side
    and the slanted side the dimension `14 deg + Tilt`. Extrude it `Plate` up. On the top face draw a 3 by 3 mm
    square centred at (20, 5) and extrude it 3 mm up (join). Make a rectangular pattern of that boss along the
    bottom edge on the X axis: 2 copies, 10 mm apart. Make a second rectangular pattern of the same boss along the
    slanted top edge: 3 copies, 8 mm apart, towards the Y axis. Then sketch a point at (8, 20) on the top face and
    add a tapped M5 hole there, through all, with "Modeled" on. Last, on a copy of the design, delete the two
    patterns and the boss.
    Export: Export for Orca with `Tilt` and `Plate` ticked. `Tilt` stays a number, with the reason "RectangularPattern2
    spreads copies along an edge that may move with it, and the copy cannot follow that". `Plate` follows partly,
    with the reason "Hole1: its thread runs through the part as thick as it is now, and Orca keeps that length". In
    `report.json` the pattern's data has `direction_one_place` with `own: true` and `entity_type` `BRepEdge`. The
    first pattern gives no reason to any size: its edge lies on the horizontal bottom line of the triangle, and only
    straight extrudes come before it. The thread reason names `Plate` and `Tilt`: the boss and its copies make the
    part thicker at some places, and `Tilt` moves the copies. On the copy without the boss, the thread reason names
    `Plate` only. Export the same body to Paramability with `Tilt` ticked: `Tilt` is a loose size with the same
    pattern reason. Afterwards the design is as before.
36. NC1, extrude, revolve and loft with the operation "New Component". Units mm, Z up. Use a new design with Direct
    Modeling off (timeline on) and no user parameters. Build three cases, each on the top level, in one design.
    (a) On the XY plane draw a 30 x 20 mm rectangle (2 point rectangle, corner at the origin). Use Create > Extrude,
    distance 10 mm, Operation "New Component". (b) On the XZ plane draw a 10 x 20 mm rectangle at X from 50 to 60
    and Z from 0 to 20. Use Create > Revolve around the Z axis, 360 deg, Operation "New Component". (c)
    On the XY plane draw a 20 x 20 mm square centred at (100, 0); make a plane 15 mm above the XY plane (Construct >
    Offset Plane); draw a 10 x 10 mm square centred at (100, 0) on it. Use Create > Loft with both squares,
    Operation "New Component". Do not activate any component and do not move any occurrence.
    Export: Export for Paramability once for the body of each of the three new components (pick the body), then
    open `report.json`. Per case read the item of the extrude, of the revolve and of the loft: `type`, `name`,
    `component` (a token), `in_target_component`, `data.operation` (extrude and revolve; the loft too if the
    field exists) and `bodies_after`. Then read the sketch item of the same case: its `component`. Send back, per
    case: the item `type`, `data.operation`, whether the feature `component` equals the `component` of the
    sketch, whether it differs from the top level component `capture.component` (name and token), and the name
    of the component that holds the new body. In Fusion look at the browser tree: write down the name of the new
    component ("Component1" and so on), which node holds the sketch (the top level or the new component), which
    holds the body, and in the timeline whether the feature shows a component icon. Open Inspect > Properties
    on the new component and write down its origin offset from the top level (should be 0, 0, 0 for all three).
37. AL1, what an Align step reads as. Units mm, Z up. Make two components: Part A with a 20 x 20 x 20 mm box on
    the XY plane (corner at the origin) and Part B with a 10 x 10 x 10 mm box on the XY plane (corner at the origin
    of its own component). On the top level, use Modify > Align on Part B: From face = the bottom face of Part B,
    To face = the top face of Part A, with "Flip" off and "Align" mode (faces touch and are aligned), so that Part B
    rests on top of Part A. Do the same once in a second design with Modify > Move/Copy (type Free Move, 0 0 0,
    Z 20 mm) as a comparison.
    Export: in the Align design export the body of Part A and of Part B (two exports), tick no parameters. In
    `report.json` read the `items` list: for the Align step write down `type` (the timeline item type, such as
    `MoveFeature` or another name), `name`, `health`, `message`, the verdict of the item (`verdict`, with `gap`,
    `note` and `cause` when it is left out), and `component`. The current add-in does not read an Align step as a
    move; note whether it appears in `items` at all. In Fusion, right-click the timeline item and read its name
    and icon (the tooltip names the feature kind). Send back the same fields for the Move comparison.
38. TA1, where a Join extrude with extent "All" ends. Units mm, Z up. On the XY plane make two bodies in one
    component: body 1 a 20 x 20 mm square at (0, 0) to (20, 20) extruded 10 mm up (new body), and body 2 a 20 x 20
    mm square at (40, 0) to (60, 20) extruded 30 mm up (new body). They do not touch. Draw a 10 x 10 mm square on
    the XY plane at (5, 5) to (15, 15). Use Create > Extrude on it, Direction One, Extent "All", Direction
    Positive (up), Operation Join, with only body 1 as the target (not "All bodies" if the dialog offers a choice
    of bodies, pick body 1). Make this a copy of the design. In a second copy do the same but start from a sketch
    on a plane at Z 5 mm (Offset Plane) with the same square, so the sketch starts inside body 1.
    Export: Export for Paramability of body 1 in each copy, with no parameters ticked. In `report.json` read the
    item of the extrude: `data.side_one.kind` (it reads `throughAll` or `all`), `data.end_offset` (the distance from the
    sketch plane to the measured end face), `data.end_area`, `data.end_normal` and `data.target_box_before`. Send
    back those fields. In Fusion measure (Inspect > Measure) the top of body 1 after the step and write down its
    Z height: 10 mm means the extrude ends at the far side of the target body; 30 mm means it ends at the far
    side of all bodies in the component; another value gets written down too. Write down also whether body 2
    changed.
39. PI1, Pipe: start plane, section placement, hollow section. Units mm, Z up. Make a path on the XZ plane: a line
    from (0, 0) to (0, 40) mm (so it runs along Z), then a tangent arc, 90 deg, radius 15 mm, ending at
    (15, 55) pointing along +X (one sketch, two curves joined). Make five pipes from the same path, each as a
    new body (use Undo or copies of the design between them). Use Create > Pipe, path = the sketch, and: (a)
    Section Circle, Section Size (outside diameter) 10 mm, Hollow off. (b) Circle 10 mm, Hollow on, Section
    Thickness 2 mm. (c) Section Square, size 10 mm, Hollow off. (d) Section Triangle, size 10 mm, Hollow off.
    (e) Circle 10 mm, with Distance One 0 and Distance Two 1 as default (a repeat of (a) to check the defaults).
    Export: the Export dialog does not read Pipe yet, so it leaves the pipe out or stops. Read the item of the
    pipe in `report.json` (`items`: `type` should be `PipeFeature`, `health`, verdict, `note`). Send back
    the `type` and note. In Fusion, per pipe, write down: where the section starts (use Inspect > Section
    Analysis or hide the pipe and look at the end face) as a position and the plane normal at the start of the
    path: is the end face at Z 0 and square to Z; the outer diameter of the end face (Inspect > Measure); for (b)
    the inner diameter; for (c) and (d) which way the corners point (a corner toward +X, +Y or another way) and
    the side length; the body volume (Inspect > Properties); and in the timeline dialog (double click the feature)
    the values of Distance One and Distance Two. Say whether the section is centred on the path.
40. T2-open, a wall along an open line with a corner. Units mm, Z up. Add user parameters `Leg` = 30 mm, `Height` =
    15 mm and `Wall` = 2 mm. On the XY plane draw two joined lines, the second from the end of the first: (0, 0) to
    (30, 0) to (30, 20), not closed. Make the start point coincident with the origin, the first line horizontal with
    a length dimension `Leg`, the second line vertical with a length dimension of 20 mm. Use Create > Extrude with the
    open line as the profile: Thin Extrude on, Wall Location "Side 1", Thickness `Wall`, distance `Height`, Operation
    New Body. Make two more designs the same with Wall Location "Side 2" and "Center". A fourth design: a 60 x 40 x
    3 mm plate on the XY plane, and on its top face the same two lines starting at (10, 10), extruded up as a Join
    with Side 1. A fifth design: the same plate and join, with the lines starting at the corner (0, 0) of the plate,
    so the wall is flush with the plate's front and left edges. A sixth design: a new body as the first, but the
    second line turns 135 degrees, from (30, 0) to (15.86, 14.14) (20 mm long), Side 2 so the wall is on the outer
    side of the sharp corner.
    Export: tick `Leg`, `Height` and `Wall` and export each body. Expect the extrude copied, not left out, and the
    copy to match the Fusion body: Side 1 inside the corner (1440 mm3 at the start sizes), Side 2 outside it (1560
    mm3), Center half on each side (1500 mm3), the ends square and the outer corner sharp. In Paramability set `Leg`
    to 50 and `Wall` to 4: the wall follows as in Fusion. In `report.json` the extrude item has `data.path` with two
    lines (`opposed` false) and `data.wall_faces` with 8 flat faces for a new body. The flush wall is copied too (8640
    mm3 with the plate): its `data.wall_faces` lists a face with its point on the plate, and
    `data.target_faces_before` lists the plate's 6 faces. The 135 degree corner is copied too: Fusion keeps one sharp
    tip at (34.83, -2) (8 flat faces, box x 0 to 34.83, y -2 to 15.56), and the copy matches its 1644.85 mm3. If a
    copy leaves the step out, send `report.json` and the reason.
41. RV6, a revolve to two sides with two angles. Add user parameters `Ahead` = 30 deg and `Back` = 50 deg. On the XZ
    plane draw a 5 by 20 mm rectangle from 10 to 15 mm away from the Z axis, its bottom on the XY plane. Revolve it
    about the Z axis as a new body, Extent Two Sides: angle one `Ahead`, angle two `Back`. Second design: the same with
    angle one 90 deg (the start face then fits both sides). Third design: a 60 x 60 x 30 mm box centred on the Z axis,
    then the same sketch with a second rectangle 25 to 28 mm away from the Z axis, both revolved Two Sides with
    `Ahead` and `Back` as an intersect.
    Export: export the first body with `Ahead` and `Back` ticked. Both are sizes. In Paramability the ring segment
    matches the Fusion body; set `Back` to 80: the body grows only on the side of angle two, as in Fusion. The second
    design leaves the revolve out with the tip "Make two revolves, one to each side of the sketch." The third copy
    matches the Fusion body (the box keeps both ring segments). Export the first body for Orca: it matches, and
    `Ahead` and `Back` keep their numbers with the reason "turns to two sides". Afterwards the design is as before.

42. RC1, revolves whose start face is gone, and a symmetric revolve. On the XY plane make a 40 x 20 x 10 mm box with
    its corner at the origin. Sketch on its front face (y = 0) a 5 by 8 mm rectangle from x = 10 to 15 whose top side
    lies on the top front edge (z = 2 to 10). Revolve it about that top front edge by 90 degrees away from the box
    (toward -Y), Join. In a second design, sketch on the XZ plane a 10 by 15 mm rectangle from x = 20 to 30, z = 0 to
    15, and revolve it about the Z axis, Direction Symmetric, angle 60 degrees (user parameter `Sweep`). Make a third
    design like the second with 200 degrees.
    Export: Export for Orca and for Paramability each body. In `report.json` the first revolve has `start_face_normal`
    null and `end_face_normal` [0, 0, 1]. Its `made_box` can be x 0 to 40, y -8 to 20, z 2 to 10, because Fusion
    merged the start cap with the front face of the box. It is copied in both outputs, turned toward -Y (the body
    boxes before and after the step decide), and the volume equals Fusion's (8251.3 mm3). In the Paramability copy the
    second is a turn of 120 degrees (Fusion's angle is the turn to each side); the volume equals Fusion's (7853.98
    mm3). In the Orca copy it is two revolves of `min(Sweep, 180)` from the sketch, one flipped, and `Sweep` is a
    variable; set it to 90 in Orca and expect 11780.97 mm3. The third is a closed ring (23561.94 mm3).
    Then measure how loose Fusion's boxes are: in the text commands window run a script that prints
    `boundingBox` of the body and of each face of the first revolve, and compare it with the shape (the body is 0 to
    40, -8 to 20, 0 to 10; the quarter round face is x 10 to 15, y -8 to 0, z 2 to 10). Expect each side to be within
    0.5 mm plus 2 percent of the largest side of the box (`BOX_LOOSE_MM`, `BOX_LOOSE_SHARE` in
    `design_model/steps/revolve.py`). If a box is looser, raise those numbers.

43. CP1, where Fusion says the copies of a circular pattern are. On the XY plane make a disc of 60 mm diameter, 5 mm
    high. Sketch a point at (20, 0) on its top face and drill a simple 5 mm hole there, through all. Make a circular
    pattern of the hole about the Z axis: Type Full, quantity 6. In a second design: Type Angle, total angle 120
    degrees, quantity 3.
    Export: Export for Orca. In `report.json` note `elements` of the pattern: each `id` and the turn of its `frame`
    about Z (atan2 of x[1] and x[0]). Fusion 2706 gave ids 0 to 5 with turns 0, 120, 180, 240, 300 and 0 (no copy
    at 60), and 0, 120 and 180 for the second, while the holes sat at 0, 60, 120 and so on. The add-in now places
    the copies by their ids and checks them against their `faces`: both patterns are copied, 6 holes round the full
    circle and 3 holes over 120 degrees, and they match the STEP. Note the turns Fusion gives: when they agree with the
    faces, Fusion has fixed the transforms.

44. SK1, what a sketch on a face says it sits on. Make a 30 x 20 x 10 mm box (user parameter `Height` for the 10 mm).
    Sketch a 6 mm circle on its top face and extrude it 5 mm up (Join). Sketch a point on the top face and drill a
    simple 3 mm hole there from that one point.
    Export: Export for Orca with `Height` ticked. In `report.json` note whether the boss profile has `reference`
    (Fusion 2706 gave none, `Sketch.referencePlane` was null) and whether the hole has `sketch`, `point_tokens` and
    `reference`. `Height` follows partly with the reason that the boss sketch sits on a plane or face that moves with
    it. If Fusion gives the face, `reference` is `{ "kind": "face" }`.
45. EX3, extrudes up to a tilted face and up to a curved face. Add a user parameter `Height` = 10 mm. On the XY
    plane draw a 60 x 40 mm rectangle from the origin and extrude it up by `Height`. Chamfer the top edge along
    y = 40 by 8 mm (equal distance). Add a construction plane 30 mm above the XY plane, sketch a 6 mm circle on it at
    (30, 36) and extrude it down "To object" up to the chamfer face as a join, with Chain Faces off. Make the same
    post at (20, 36) with Chain Faces on. On the YZ plane draw a 10 mm radius circle centred at y = 20, z = 10, and
    extrude it 60 mm along +X as a join (a round roof on the box). Sketch a 6 mm circle on the plane
    30 mm up at (30, 25) and extrude it down "To object" up to the round face as a join, with Chain Faces off. Make
    the same roof post at (45, 25) with Chain Faces on, and one at (57, 25) with Chain Faces off, whose circle
    reaches past the end of the roof at x = 60.
    Export: tick no size. In `report.json`, note `side_one.chained` of the two chamfer posts and `end_offset` of the
    roof posts. Expect `chained` false and true. The roof posts have `side_one.surface` "Cylinder". The first roof
    post has `outline_hits_face` true, the one at (57, 25) false, and the one with Chain Faces on has none. The two
    chamfer posts and the first roof post are copied with `extent: { upTo: { near } }` and match the STEP: the posts
    land on their faces alone. The roof post with Chain Faces on is left out with "a face and the faces next to it",
    and the one at (57, 25) with "reaches past that face". Then move the chamfer post with
    Chain Faces on to (20, 33), so it reaches past the chamfer onto the top face, and export again: Fusion ends it on
    both faces, and the post is left out with "its outline may reach past that face". Move it back. Export again with
    `Height` ticked: the first roof post is still copied (the extrude that made the roof places its point; Fusion
    gives no end face for this join, and the box after the step, which lies wholly below the plane 30 mm up, shows
    that it goes down), and
    `Height` is marked with "ends on a curved face"; the chamfer post is left out with "may move when the sizes
    change". Afterwards the design is as before.
46. EX4, an extrude that starts at a distance from a face, both ways. Add user parameters `Height` = 10 mm and
    `Lift` = 3 mm. On the XY plane draw a 40 x 40 mm rectangle from the origin and extrude it up by `Height`. On the
    XY plane draw a 10 mm square centred at (20, 20) and extrude it 5 mm up as a new body, with Start set to "From
    object", the top face of the box, and the offset `Lift`. Make a second new body the same way at (10, 10) with
    the offset `-Lift`. Make a third extrude like the first as a join with the offset -2 mm, so it starts inside
    the box.
    Export: export each new body with both sizes ticked. In `report.json` note `start_offset` of each extrude and
    which way Fusion moved the start. Expect the first body to start at `Height + Lift` and the second at
    `Height - Lift`, both following the sizes in Paramability. Export the box: `start_offset` of the join is null
    (no start face inside material) and `end_offset` is 13. The join is copied: it starts 2 mm below the top face
    (z = 8) and goes 5 mm up, and the shape matches the STEP.
47. EX5, an intersect to two sides. On the XY plane draw a 40 x 40 mm rectangle from the origin and extrude it
    20 mm up. Add a construction plane 10 mm above the XY plane. On it draw a 20 mm circle centred at (20, 20) and
    extrude it as an intersect with Two Sides: side one 4 mm up, side two 6 mm down.
    Export: tick no size. The intersect is copied as one tool body that the part intersects (recipe version 15),
    and the copy is a disc 20 mm across from z 4 to z 14 that matches the STEP.
48. EX6, an extrude up to a face square to it, with Chain Faces on. On the XY plane draw a 40 x 40 mm rectangle from
    the origin and extrude it up 20 mm. Shell it 2 mm with the top face removed. Make a shelf: on a plane 15 mm up
    draw a rectangle from (0, 0) to (40, 20) and extrude it 2 mm up as a join, then chamfer the lower edge of the
    shelf at y = 20 by 3 mm. On the XY plane draw a 6 mm circle at (20, 10) and extrude it up "To object" up to the
    bottom face of the shelf as a join, with Chain Faces on. Make a second post the same way at (20, 16), so that it
    reaches past the bottom face onto the chamfer.
    Export: tick no size. In `report.json`, `side_one.chained` is true and `side_one.face_outline` holds the bottom
    face of the shelf. The first post is copied and matches the STEP. The second post is left out with "its outline
    may reach past that face"; note where Fusion ended it. Turn Chain Faces off on the second post: it is copied and
    ends on the plane of the shelf bottom, as Fusion then makes it. Then delete the second post, and cut a 2 mm wide
    slot through the shelf from (19, 0) to (21, 18), across the first post: no corner of the slot lies in the post.
    Export again: the first post is left out with "its outline may reach past that face".
49. CR1, a round set by chord length. Model a 40 x 20 x 10 mm box with its corner at the origin, and add user
    parameter `Chord` = 3 mm. Round the four top edges with a fillet whose type is Chord Length, chord length `Chord`.
    On a second box, draw a triangle on the XZ plane with corners (0, 0), (30, 0) and (0, 20), extrude it 40 mm, and
    round its slanted top edge the same way.
    Export: export the first box with `Chord` ticked. In `report.json` each edge of the fillet set has five `samples`,
    each with a `radius` of 2.121 mm (3 divided by the square root of 2). The recipe has one round of
    `0.707106781 * Chord`, and `Chord` is a size. Change `Chord` to 5 in Paramability: the round grows like Fusion's.
    Export the second box: the radius is 3 / (2 sin(a / 2)), where a is the angle between the slanted face and the
    face beside it, and matches the measured `radius`. If the measured radius differs, note both numbers.
    On a third part, extrude a circle of diameter 30 mm up 10 mm and round its top edge with a Chord Length fillet of
    `Chord`; on a fourth, round the top edge of a 40 x 20 x 10 mm box whose top was cut by a sphere of radius 60 mm.
    Export the third part with `Chord` ticked: in `report.json` the cylinder in `side_faces` has an `axis` along Z and
    the round follows `Chord`. Export the fourth: the radius is a number, `Chord` is not a size, and the reason says
    the round sits on a face that curves across the edge.
50. VR1, a variable radius: is Fusion's change even? Model a 60 x 20 x 20 mm box with its corner at the origin.
    Round the front top edge (along X) with a fillet whose type is Variable Radius: 1 mm at the start, 5 mm at the
    end, no radii between them. On a copy, round the same edge with 5 mm at the start and 1 mm at the end.
    Export: export each box. In `report.json` the fillet set has `start_radius`, `end_radius` and `mid_count` 0, and
    the edge has five `samples` with a `radius`. Note the five radii. When they are 1, 2, 3, 4 and 5 (or the other
    way round) within 0.01 mm, Fusion's change is even: the recipe has a round with `size` at the end with the lower
    x and `sizeEnd` at the other, and the round in Paramability looks like Fusion's. When the middle radii are off
    the straight line (for example 1.6 and 4.4 at a quarter and three quarters), Fusion blends in a curve: the round
    is left out with the reason that the radius does not change evenly. Note the measured radii in both cases.
51. PP1, a path pattern along a line, an arc and a circle. Add user parameters `Count` = 3 and `Pitch` = 15 mm.
    Model a 80 x 40 x 10 mm plate with its corner at the origin. On the top face draw a sketch line from (5, 10) to
    (35, 10), a circle of radius 2 mm at (5, 10), and in a second sketch on the top face an arc of radius 10 mm
    centred at (60, 20) from (70, 20) counter clockwise to (50, 20) with a circle of radius 2 mm at (70, 20). Cut each
    small circle 4 mm deep. Make a Pattern on Path of the first cut along the line: quantity `Count`, distance `Pitch`,
    spacing, orientation Path Direction, start point at the line's start. Make a second Pattern on Path of the second
    cut along the arc: quantity 3, distance 5 mm, spacing, orientation Path Direction. On a copy of the design, set
    the second pattern's orientation to Identical; on another copy, make it along a full circle of radius 10 mm.
    Export: export the plate with `Count` and `Pitch` ticked. Both path patterns are copied: in Paramability the holes
    sit where Fusion has them. The first pattern follows `Count` and `Pitch`, and the cut ranges stop where the last
    hole would pass x = 35 (a count of 3 and a pitch of 15 mm). The copy with orientation Identical leaves the second
    pattern out with a reason and a tip. The full circle copy turns the holes evenly round the circle. In
    `report.json` the path pattern data has `start_point` 0, `flip` false and `along_path` true, and `elements` hold
    the moves of the copies from the original. Then set `Count` to 4 in Fusion: note whether Fusion puts the fourth
    hole past the end of the line, leaves it out, or fails (the copy keeps the copies on the path). Afterwards the
    design is as before. On another copy, set the arc pattern's start point to 0.75 and pick the arc so that the path
    runs from (50, 20) to (70, 20), against the arc. In `report.json` the path curve has `opposed` true. The copy
    counts the start point from the start of the path: 7.9 mm of arc lie ahead of it and the copies reach 10 mm, so
    the pattern is left out as running past the end. Note where Fusion puts the copies (`elements`). Fusion 2706 put
    them off the arc, with transforms that do not agree with their faces: an arc pattern with a start point other
    than 0 or the flip is left out with the reason that Fusion can put the copies off the path.
52. TD3, a tapped hole with a counterbore and one with a countersink. Make a plate 40 x 40 x 12 mm. Add a Hole at
    (10, 20) on the top face: Counterbore, counterbore 10 mm across and 3 mm deep, "Tapped", "Modeled" ticked,
    M6x1, 10 mm deep, full length thread. Add a Hole at (30, 20): Countersink, 12 mm across at 90 degrees, tapped
    and modeled M6x1, through all. Add a user parameter `Bore` = 3 mm and set the counterbore depth to `Bore`.
    Export: tick `Bore`. In `report.json` note `thread.made_span` of each hole: expect it to start near 3 mm for the
    counterbore hole and near 3.5 mm for the countersink hole (where the cone narrows to the 5 mm bore). Both holes
    are copied with a `thread` step that starts at the bottom of the recess and match the STEP. In the Orca copy the
    counterbore hole has a thread from the counterbore floor and `Bore` is followed in part; the countersink hole is
    left out. In Paramability,
    change `Bore` to 5 mm: the thread of the counterbore hole starts 5 mm down and ends at the bottom of the hole.
    When `made_span` starts at 0 instead, Fusion starts its thread at the top: the holes are left out with "does not
    start at the top of the hole (or below its counterbore or countersink)". Afterwards the design is as before.
53. RP1, one fillet with two tangent chains of different radii. Add a user parameter `Width` = 40 mm.
    Sketch a 40 x 20 mm rectangle with its corner at the origin and width `Width`, and round two of its corners in
    the sketch with arcs of 5 mm, so each long side runs on into an arc without a corner. Extrude it 10 mm. Make one
    Fillet with two sets, both with Tangent Chain on: the first set picks the top front edge (radius 1 mm), the second
    set picks the bottom back edge (radius 2 mm).
    Export: tick `Width`. The recipe has one round with `chain: tangent`, two points and `edgeSizes` [1, 2], and
    `Width` stays a size with no "may give unexpected results" for the fillet. In Paramability, change `Width` to 60
    mm: each chain keeps its radius, as in Fusion. Then add a third set picked by the top face (radius 1 mm): the
    fillet is written with a point per edge and `Width` is marked "may give unexpected results". Afterwards the design
    is as before.
54. SC1, scale of a body. Add a user parameter `Grow` = 1.5 (no unit) and `Height` = 10 mm. Sketch a 40 x 20 mm
    rectangle on the XY plane with one corner at the origin and extrude it by `Height`. Use Modify, Scale on the body
    with the origin point as the point, uniform, factor `Grow`. Fillet one top edge by 2 mm after the scale. Make a
    second design with the same box scaled Non Uniform by X 1, Y 2, Z 0.5 about the far top corner of the box (a
    vertex), and a third with the box in a component that is turned 30 degrees about Z in the assembly, scaled Non
    Uniform about the component's origin.
    Export: tick `Grow` and `Height`. The first copy has a `scale` step with factor `Grow` after the extrude and
    matches the STEP; in Paramability, change `Grow` to 2: the part grows to 80 x 40 x 20 mm, and the fillet
    stays on its edge (the fillet may mark sizes "may give unexpected results"). The second copy
    writes the factors [1, 2, 0.5] and the corner as the point, and `Height` is marked "may give unexpected results".
    The third leaves the scale out with "turned at an angle". Export for Orca leaves the scale out with the tip
    "Change the sizes in the sketches". In `report.json` note `input_kind`, `point` and `factors` of each scale.
    Afterwards the design is as before.
55. SH1, a shell that grows outward. Add a user parameter `Wall` = 2 mm. Sketch a 40 x 20 mm rectangle with its corner
    at the origin on the XY plane and extrude it 10 mm. Make a Shell: pick the top face, direction Outside, thickness
    `Wall`, type Sharp. Fusion keeps the box as the hollow and adds the wall outside it, with the top open.
    Export: tick `Wall`. The recipe has a `shell` step with `outside: true`, `thickness` `{ "expr": "Wall" }` and
    `openFaces`, and the recipe version is 17. In `report.json` the shell data has `inside` 0, `outside` 2 and
    `shell_type` `sharp`, and `volume_before` is more than `volume_after`. In Paramability: the part is 44 mm by 24
    mm by 12 mm over all, open at the top, and the hollow is the 40 x 20 x 10 mm box. Change `Wall` to 3 mm: the
    outside grows to 46 x 26 mm, as in Fusion. Then add a Join extrude of a 4 x 4 mm square that starts 11 mm above
    the base plane (inside the wall height) at the corner of the part: the join stays in the copy. Afterwards the
    design is as before. On another copy set the Shell direction to Both Sides: the shell is left out with a reason
    and the tip "Shell one way only, inward or outward, with sharp or rounded corners."
56. SH2, a closed hollow. Sketch a 40 x 20 mm rectangle with its corner at the origin and extrude it 10 mm. Make a
    Shell: pick the body (not a face), direction Inside, thickness 2 mm, type Sharp. The body becomes a closed hollow
    with a 36 x 16 x 6 mm cavity.
    Export: the recipe has a `shell` step with no `openFaces` and no `outside`, and the recipe version is 17. In
    `report.json` the shell data has `bodies_input` true, no faces, and `volume_after` below `volume_before`. In
    Paramability: the part is a closed hollow; cut it with a section view and see the cavity. Add a Fillet on the
    four vertical outer edges after the shell: the fillet is copied. Afterwards the design is as before.
57. SH3, a shell with rounded corners. Sketch a 40 x 20 mm rectangle with its corner at the origin and extrude it 10
    mm. Make a Shell: pick the top face, direction Outside, thickness 2 mm, type Rounded. Fusion rounds the outside
    corners and edges of the wall with a radius of 2 mm. On another copy use direction Inside and type Rounded.
    Export: the recipe has a `shell` step with `corners: "round"` (and `outside: true` on the first copy), and the
    recipe version is 17. In `report.json` the shell data has `shell_type` `rounded`. In Paramability: the outer
    corners of the wall are round as in Fusion, and the volumes of the copy and the STEP agree within 1 percent. When
    they do not agree, note which of the two types differs and by how much: the rounded type of Fusion and of the
    app may round different edges. On the inside copy the shape that Fusion makes is the one to match.
58. DR2, a Symmetric draft and a Two Sides draft across the plane. Add a user parameter `Lean` = 3 deg. Extrude a
    40 x 20 mm rectangle 10 mm up from the XY plane. Add a construction plane parallel to the XY plane, offset 5 mm,
    and use it as the fixed plane. Make three copies of the design. Copy one: Draft the four side faces, Draft Type
    "Symmetric", angle `Lean`. Copy two: the same, with the angle -3 deg. Copy three: Draft Type "Two Sides" with Angle 1
    = 3 deg and Angle 2 = 6 deg. In each copy, measure how wide the top face (z = 10), the middle (z = 5) and the bottom
    face (z = 0) are along X, and write the numbers down. On a fourth copy use Two Sides with 3 deg and 3 deg.
    Export: tick `Lean` for copy one. Expect copy one to be widest in the middle (note it if not: the copy relies on
    both sides leaning alike), so material comes off on both sides; the draft is copied as one step with two equal angles of 3 degrees (recipe version 17), and in Paramability
    the top and bottom faces are narrower than the middle exactly as in Fusion. Changing `Lean` changes both sides. In
    copy two the box is narrowest in the middle, and both angles are -3. Copy three is left out with the reason that
    each side has its own angle; note which angle (3 or 6) Fusion applied to the half above the plane (z 5 to 10)
    and whether `isDirectionFlipped` changes it: the answer decides whether this case can be copied later. On the fourth
    copy note whether the shape equals the Symmetric draft of copy one (the same widths); it is left out now. Afterwards
    the design is as before.
59. PF1, Press Pull on a whole round face (a press fit). Add user parameters `Fit` = 0.2 mm and `HoleSize` = 5 mm.
    On the XY plane draw a 40 x 20 mm rectangle with its corner at the origin and extrude it 10 mm. On the top face
    draw a circle of diameter `HoleSize` with its centre at (12, 10) and cut it through all. On the XY plane draw a
    circle of 6 mm diameter with its centre at (30, 10) and extrude it 15 mm as a Join, so a pin stands 5 mm above
    the plate. Use Press Pull (Offset Faces) on the wall of the hole with the distance `-Fit`. Use Press Pull on the
    round side of the pin with the distance -0.1 mm.
    Export: tick `Fit` and `HoleSize`. In `report.json`, each Offset Faces item has a face of `kind` "round" with two
    `ends` of `kind` "circle", each with a flat `face`; `outward` is false for the hole and true for the pin;
    `rounds_after` holds a radius of 2.7 for the hole and 2.9 for the pin. The recipe is version 17 with two
    `offsetFaces` steps; the distance of the hole follows `Fit`. In Paramability, set `Fit` to 0.4 mm: the hole is
    5.8 mm across, and the pin stays 5.8 mm across. When `rounds_after` is empty, Fusion does not list the moved face
    after the step and both steps are left out with "could not be measured": report this. Afterwards the design is as
    before.
60. TD4, tapped holes through all and a cosmetic one. Add a user parameter `Plate` = 30 mm. Make a box 80 x 60 mm,
    `Plate` high. On the top face add three Holes, "Tapped", M6x1: at (-20, 0) Simple, "Modeled" ticked, through all;
    at (0, 0) Counterbore 10 mm across and 3 mm deep, "Modeled" ticked, through all; at (20, 0) Simple, cosmetic
    (Modeled off), 15 mm deep.
    Export: tick `Plate`, once to Paramability and once to Orca. In `report.json` each hole lists no thread faces in
    `end_points` (the through holes have none), and each `side_cylinders` entry has a `span` that covers the bore:
    30 mm long for the simple through hole, 27 mm for the counterbore one. The through holes copy as a hole at the
    minor diameter plus a thread from the top (simple) or from the counterbore floor (3 mm down) to the bottom face;
    the cosmetic hole copies as a plain hole 5.035 mm across. In Paramability, change `Plate` to 40 mm: both threads
    still reach the bottom face. In Orca, the counterbore hole has a lead-in at the counterbore floor and at the
    bottom face. When a `span` is null or covers only part of the bore, note what `vertices` the side face of the
    hole has. Then add a user parameter `HoleX` = -20 mm for the x of the simple through hole, and a box 10 mm high
    on the top face over x -14..-6 and y -10..10, clear of the holes. Export again with `Plate` and `HoleX` ticked: the
    thread of that hole is 30 mm long as a number, and `Plate` and `HoleX` are marked "may give unexpected results"
    (the hole can move under the box, where Fusion's thread is 40 mm). Afterwards the design is as before.
61. MV1, a sphere moved into a box and kept where both meet. Make a box 40 x 20 x 10 mm with its corner at the
    origin. Make a second body: sketch a half circle of radius 60 mm on a plane through the middle of the box (y = 10),
    centre at (20, 10, 0), with its straight side on a vertical line, and revolve it 360 degrees about that line as a
    new body. Move the sphere with a Move along X, Y and Z by z = -52 mm. Combine the box with the sphere: Intersect,
    the box as target.
    Export: pick the box. The recipe has a `toolBody` with the revolve and a `move` of -52 mm along z, and the copy is
    a dome 8 mm high that matches the STEP. In `report.json` the Move data has `boxes_before` and `boxes_after` 52 mm
    apart along z. Then add a Rotate Move of the sphere (10 degrees about the z axis through (0, 0, 0)) before the
    Combine and export again: the Combine is left out with a reason that names the sphere and the Rotate Move, and no
    flat box is written. Afterwards the design is as before.
62. HB1, an extrude that starts from a face of a helper body. Add user parameters `Height` = 10 mm and `Lift` = 3 mm.
    Body1: a 40 x 40 mm rectangle at the origin extruded `Height` as a new body. Body2: a 10 x 10 mm rectangle
    centred at (20, 20) on the XY plane, extruded 5 mm as a new body, with the start "From object" on the top face of
    Body1 and an offset of `Lift`. Body3: the same with the centre at (10, 10) and an offset of `-Lift`.
    Export: pick Body2 and tick both sizes. Both stay sizes, and the start of the extrude in `recipe.json` reads
    `Height + Lift` (Body3: `Height - Lift`). No size is "not used" with "changes nothing". In Paramability, change
    `Height` to 15 mm: Body2 starts at 18 mm, as in Fusion. Afterwards the design is as before.
63. PE1, where Fusion says the copies of a rectangular pattern are. Make a 100 x 60 x 5 mm plate with its corner at
    the origin. Drill a simple 5 mm hole through all at (10, 10). Make a rectangular pattern of the hole: direction
    one along X, quantity 4, distance 20 mm, spacing; direction two along Y, quantity 3, distance 15 mm. On a copy of
    the design, tick Symmetric in direction one and set its quantity to 5, with the hole at (50, 10). On another copy,
    suppress the copy at (50, 25). On a last copy, make the plate in a new component and move that component 100 mm
    along Y and turn it 90 degrees about Z, then make a circular pattern of the hole about the Z axis of the
    component: Full, quantity 4.
    Export: Export for Paramability and Export for Orca. In `report.json`, for each element compare the shift of its
    `frame` (`origin`) with the move from the original's `source_faces` to the element's `faces`. Expect them to
    agree, and the holes at x 10, 30, 50, 70 and y 10, 25, 40. Each pattern is copied (the suppressed copy as a
    skip in the recipe; Orca leaves that one out) and matches the STEP. If a pattern is left out with "Fusion gives a
    place for a copy of this pattern that is not where the faces of that copy are", note the ids, frames and face
    centres: the transforms of rectangular patterns are wrong too. In the moved component, the frames are in
    assembly space and the face centres in the component's space (the original hole near (10, 10), not near (-10, 110)); both patterns
    are copied. If they are left out with that reason, note the frames and face centres: the spaces differ from
    what the reader expects.
64. PE2, where Fusion says the copies of a path pattern round a whole circle are. Make a 60 x 60 x 5 mm plate with
    its corner at the origin. Sketch a circle of radius 20 mm centred at (30, 30) on the top face, and a circle of
    radius 2 mm at (50, 30); cut the small circle through all. Make a Pattern on Path of the cut along the large
    circle: quantity 6, extent, distance the whole circle (125.664 mm), orientation Path Direction.
    Export: Export for Paramability. In `report.json` note each element's `id`, the turn of its `frame` about the
    circle's centre and the centre of its `faces`. Expect 6 different places 60 degrees apart and transforms that
    agree with the faces. The pattern is copied as a full turn of 6 and matches the STEP. If two elements share a
    place, or a transform does not agree with its faces, the pattern is left out with that reason: note the values.
65. PE3, where Fusion says the copies of a pattern of bodies are. Make a 10 x 10 x 10 mm box at (20, -5, 0) to
    (30, 5, 10) as its own body, and a disc of 80 mm diameter, 5 mm high, centred on the origin as a second body. Make
    a circular pattern of the box body (Pattern Type Bodies) about the Z axis: Full, quantity 6. On a copy of the
    design, make it Angle, total 120 degrees, quantity 3. On another copy, make a rectangular pattern of the box body
    instead: along X, quantity 3, distance 15 mm. Then Combine Join the disc with every box.
    Export: Export for Paramability the disc. In `report.json` compare each element's `frame` with the move from
    `source_faces` to its `faces`, and with the place of its body in `result_bodies`. The Combine writes one pattern
    of the box tool: 6 copies round the circle, 3 over 120 degrees, and 3 along X. Each copy matches the STEP. If
    a pattern is left out with "The copies of this pattern could not be matched to the bodies it made", note the
    frames and the body points.
66. NC1, steps that make a new component. Add a user parameter `Len` = 30 mm. With the top level active, sketch a
    30 x 20 mm rectangle on the XY plane, width `Len`, and extrude it 10 mm with the operation New Component. In the
    same way revolve a 10 x 20 mm rectangle on the XZ plane (50 to 60 mm from the Z axis) a full turn about the Z axis,
    and loft a 20 mm square on the XY plane to a 10 mm square on a plane 15 mm up, each with New Component.
    Export: export the body of each new component, tick `Len` for the extrude. Each copy is written as a recipe and
    matches the STEP, with no "older version of the add-in" reason. In Paramability, change `Len` to 40 mm: the
    extrude grows like in Fusion. Then move the first new component 20 mm along X (Position, Capture Position) and
    export it again: the copy still matches. Afterwards the design is as before.
67. HO1, a hole placed from the projected origin. Add user parameters `Width` = 80 mm, `Depth` = 60 mm, `Height` = 30
    mm and `HoleX` = 20 mm. Sketch a centred rectangle `Width` x `Depth` on the XY plane and extrude it `Height` up.
    Sketch on the top face, project the origin point (Project, then the origin in the browser), add a sketch point
    and dimension it `HoleX` along X from the projected origin, on the same line in Y. Add a simple 6 mm hole on
    that point, 10 mm deep.
    Export: Export for Orca, tick all four. `HoleX` is a variable of the hole place, not fixed, and no size has the
    reason "placed by geometry projected into Sketch2". In Orca, change `HoleX` to 30 mm: the hole moves like in
    Fusion. Afterwards the design is as before.

68. RV7, a revolve about an axis that a size moves past the outline. Add a user parameter `Height` = 10 mm. On the XY
    plane make a 40 x 20 mm box with its corner at the origin, extruded `Height` up. Sketch on its top face a line on
    the top front edge (y = 0, from x = 0 to 40), coincident with that edge. On the XZ plane draw a rectangle from
    x = 0 to 10, z = 12 to 15. Revolve it 90 degrees about the line, Join, toward +Y (the ends lie on the top face).
    Export: tick `Height`. The range of `Height` stops at 11.99 or lower, and the revolve is copied. The reason is
    "the outline of Revolve1 would reach its axis", or "Fusion shows a warning on Revolve1 at ..." when a try near
    12 mm made Revolve1 show a warning (`probe.states` has `warned: true` there). In Paramability set `Height` to 11.99: the copy matches Fusion at that
    value. In Fusion set `Height` to 15 and to 20: the revolve turns into the box, which is why the range stops. Then
    export again with the range of `Height` typed as 4 to 20 mm: the revolve is left out with the tip "Type size
    ranges that keep the outline on one side of the axis, or leave the ranges to the add-in." Afterwards the design
    is as before.

69. TA2, a join through all onto a body with a step. Add user parameters `Low` = 10 mm and `Tall` = 30 mm. On the XY
    plane draw a rectangle from (0, 0) to (60, 20) and extrude it `Low` up as a new body (Body1). On the XY plane draw
    a rectangle from (40, 0) to (60, 20) and extrude it Join, distance `Tall`, so Body1 has a low part and a tall part.
    On the XY plane draw a rectangle from (80, 0) to (100, 20) and extrude it 50 mm up as a new body (Body2). On the
    XY plane draw three squares: A from (10, 5) to (20, 15) under the low part, B from (35, 5) to (45, 15) across the
    step, C from (45, 5) to (55, 15) under the tall part. Extrude each square alone, Join, extent All, direction up,
    with Body1 as the only body it joins (three extrudes, in the order B, C, A).
    Export: pick Body1, tick `Low` and `Tall`. In `report.json` all three end at 30 (`end_offset`), the top of the
    whole body; `end_area` is 450 for B and C and 100 for A. A, B and C are copied as extrudes to the far side of the
    part (`"extent": "through"`, no distance, recipe version 17), and `Low` and `Tall` are marked "may give unexpected
    results" with an extrude named. In Paramability set `Tall` to 40 and `Low` to 15: A, B and C end at the top of
    the tall part, as in Fusion with the same values. Then add Body2 to the bodies that B joins and export again:
    Fusion still ends B at 30, and B is left out with the tip "Let the extrude join only this body, or give it a
    distance." Afterwards the design is as before.
    A curved far side: make a cylinder of radius 10 mm along X as its own body, a 10 x 10 mm square on a plane
    through its axis tilted 20 degrees, Join, extent All, the cylinder the only body it joins. Fusion adds nothing
    and lists no end face (`end_offset` null). The export never copies that join as `"extent": "through"`.

70. PI2, pipes copied as sweeps. Add user parameters `PipeD` = 10 mm, `Wall` = 2 mm and `Run` = 40 mm. On the XZ
    plane draw a line from (0, 0) to (0, `Run`) mm (so it runs up Z), then a tangent arc of 90 degrees and radius
    15 mm that ends pointing along +X. The arc must start on the end point of the line (draw it from that point):
    an arc that only has a coincident constraint to the line makes the pipe follow the line alone. Make two copies
    of the design. In the first use Create > Pipe on the path: Section Circle, Section Size `PipeD`, Hollow off, new
    body. In the second the same with Hollow on and Section Thickness `Wall`. In the third draw a second sketch on
    the XY plane with an L of two lines that meet at a sharp corner, (0, 0) to (30, 0) to (30, 20), and pipe it
    with Section Circle 6 mm.
    Export: export the pipe body of each design and tick all parameters. Each copies as one sweep of a circle (a
    ring for the hollow pipe, its hole radius `0.5 * PipeD - Wall`). `PipeD` and `Wall` are sizes and are not marked
    "may give unexpected results"; for the hollow pipe the range of `PipeD` starts and the range of `Wall` stops
    where the wall would close the hole. The volume in Paramability matches Fusion's (Inspect > Properties) at the
    values now and with `PipeD` at 12 mm, `Wall` at 3 mm and `Run` at 50 mm. The corner of the third pipe is mitred
    (1413.717 mm3, as in Fusion). Afterwards each design is as before.

71. CC9, a plane of the part built on the top level. Add user parameter `Width` = 40 mm. Make component Tray and
    activate it. Sketch a `Width` x 30 mm rectangle on the XY plane of Tray and extrude it 10 mm. Activate the top
    level. Move the Tray occurrence 20 mm up along Z (Move, then Position, Capture Position). Activate Tray. Make a
    construction plane offset 45 mm from the XY plane of the top level (pick it under the Origin of the top level in
    the browser, not under Tray). Sketch a 10 x 10 mm square on the top face and extrude it up to the new plane
    (extent To Object), Join.
    Export: pick the Tray body, tick `Width`. In `report.json` the plane of the second extrude (`side_one`) has no
    `foreign`, and its `built_on` entry is `{ "foreign": true }` with `component` of the top level and `root: true`.
    The second extrude is copied, not left out with "reaches into another component". `Width` is not marked
    "may give unexpected results". In Paramability the post is 15 mm tall and ends 25 mm above the base of the tray,
    as in Fusion. Afterwards the design is as before.

72. RB1, the undo of an export that left a step worse. Model a part where a try flips a sketch. Add user parameters
    `Base` = 40 mm and `Lift` = 10 mm. Sketch 1 on the XY plane: a triangle with one corner on the origin, one corner
    `Base` along X on the X axis, and the third corner set by two dimensions (a 30 mm side and a 50 mm side), so
    the sketch has two solutions and a change of `Base` can flip it to the other one. Extrude it 5 mm. Sketch 2 on
    the top face of that extrude: project one edge of the extrude and draw a rectangle that uses the projected edge
    as a side. Extrude sketch 2 up by `Lift`. Save the design.
    Export: pick the body, tick `Base` and `Lift`, leave "Lighter on memory" off, then click OK. Expect the result
    window to say that the add-in asked Fusion to undo everything the export did, and that the file is saved. When the
    window is closed and the export ends, expect Fusion to show a message that the add-in asked it to undo the export
    and that the file is saved. Then expect the timeline to show no new warning (yellow) or error (red) that it did not
    have before, and the export's steps gone from Edit, Undo (Undo goes back to your own last edit, not to a step of
    the export). When the tries stopped early, the window still says so. The `.paramability` file is saved and opens
    in Paramability. Note the message Fusion shows and how long the undo takes after the tries end. Repeat, and click
    Cancel in the progress window during the tries: when the triangle stays flipped, Fusion undoes the export too, and
    the window and the message say that no file was saved. Repeat with "Lighter on memory" ticked: Fusion shows no undo message, the
    design stays as the put back left it, and the window says that the export could not be undone because Lighter on
    memory was on, and advises to close the design without saving. If your design does
    not leave a step worse (it comes back clean), the export must not be undone: Fusion shows no message and the
    result window has no undo lines.
73. FD1, a try that flips a sketch with steps built on it. Add a user parameter `Arm` = 30 mm. On the XY plane sketch
    a triangle: one corner on the origin, one corner 40 mm along X, the third corner placed only by two distances
    (`Arm` from the origin, 35 mm from the second corner), with no other constraint, so the third corner can flip below
    the X axis. Extrude it 10 mm as a new body. On the XZ plane start a second sketch, project the slanted top edge of
    the extrude from the origin to the third corner (Create > Project), and draw a 4 mm circle centred on the end
    point of the projected line. Cut through all with that circle.
    Export: tick `Arm` with a range of 5 to 80. When a try flips the triangle, the result window either has no line
    about it (the flip was brought back) or says "The tries stopped early: after trying Arm at ..., these steps stayed
    changed even with your values back" and names the second sketch. Only the tries before it are used. Afterwards
    the triangle is on the same side as before, the second sketch and the cut have no warning, and `health` in
    `report.json` has no `steps_changed`, no `outlines_changed` and no `body_changed`. Undo is still offered when the
    tries stopped, unless the end check found the design changed or could not confirm it; then the export is undone
    (see RB1). `body_changed` must not show for a design that came back: a difference with no other change is at most
    `body_unconfirmed`. When a flip was brought back, `probe.recovery.attempts` in `report.json` lists each attempt
    with the row and the values set, and the attempt that brought the triangle back has `back: true`.
74. CH5, two components with steps of the same name. Add a user parameter `Width` = 12 mm. Make component Box and
    activate it. Sketch a rectangle of `Width` x 20 mm on the XY plane, extrude it 10 mm up as a new body, and chamfer
    the four top edges by 4 mm in one Chamfer step (Fusion names it Chamfer1). Activate the top level, make component
    Other and activate it. Sketch a 30 x 30 mm rectangle from (50, 0) on the XY plane, extrude it 10 mm up as a new
    body, and chamfer its four top edges by 1 mm (Fusion also names it Chamfer1, in its own component). Fusion cannot
    build the chamfer of Box when `Width` is below 8 mm.
    Export: pick the Box body and tick `Width`; leave its range as the add-in gives it (6 to 24 mm). Expect the range
    of `Width` to start at a value from 8 to 12 mm, with the reason "Fusion did not rebuild the design at ...
    (Chamfer1)". In `report.json`, each entry of `probe.motion.spans.Width.failed` has a third number: the timeline
    position of the chamfer of Box (the `index` of that item in `capture.items`, not of the chamfer of Other). The
    state of that try in `probe.states` has `failed_at` with the same number. Afterwards the design is as before.
75. AX1, a cone or a torus face as the turning axis. Add a user parameter `PotH` = 40 mm. On the XZ plane sketch a
    tapered pot as one closed outline: bottom 30 mm wide, top 50 mm wide, `PotH` high, with the centre line on the Z
    axis (the outer side line is slanted). Revolve it 360 degrees about the Z axis as a new body, so the outer wall
    is a cone. Add a 3 mm hole 6 mm deep in the top face, 10 mm from the centre, and a Circular Pattern of it with 6
    copies whose axis is the conical outer wall (pick the face, not the Z axis). Then, on the XZ plane, sketch a 6 x
    6 mm square 8 mm outside the wall at the top, and Revolve it 90 degrees as a Join with the conical wall as the
    axis. For the torus, revolve a circle of 6 mm diameter, centred 25 mm from the Z axis, about the Z axis, and make
    a Circular Pattern of a 2 mm hole in the top face with the toroidal face as its axis.
    Export: tick `PotH` with a range of 30 to 60. Expect the revolve and both patterns to copy, with no gap "a face
    that is not round". In `report.json` the `axis` of these steps holds `entity_type: "BRepFace"`, `surface` `Cone`
    (or `Torus`), a `point` and a `dir` along Z. `PotH` is marked "may give unexpected results" with those steps
    named. The copy matches the Fusion part at the values the add-in tried. A Circular Pattern whose axis is the face
    of a sphere is still left out with "a face that is not round".
76. RS1, a red step that builds at other sizes. Add a user parameter `Side` = 60 mm. On the XY plane sketch a
    centred square of `Side` x `Side` and extrude it 5 mm up as a new body. Fillet its four vertical edges with 25 mm
    in one Fillet step. Then set `Side` to 40 mm: Fusion cannot build the fillet now, and it is red in the timeline.
    On the top face sketch a 6 mm circle on the centre and cut it through all.
    Export: pick the body and tick `Side` with a range of 20 to 80 mm. Expect a recipe, not a fixed shape: a note says
    the fillet "is in error in Fusion and changes nothing on the part, so the copy leaves it out too", the cut is
    copied, and no step is left out. The range of `Side` stops at a value from 40 to 50 mm, with the reason
    "Fillet1, in error in Fusion now, builds at ...". In `report.json` that try has `cleared: true` in
    `probe.states`, and `probe.motion.spans.Side.cleared` lists it. Afterwards the fillet is red again, `Side` is
    40 mm, and `health` has no `steps_changed`.
77. RV8, picks on the faces of a revolve. Add user parameters `Height` = 40 mm and `Diameter` = 60 mm. On the XZ
    plane draw a rectangle from x = 0 to `Diameter` / 2 and from z = 0 to `Height`, with its left side on the z axis.
    Revolve it a full turn about the z axis as a new body (a cup). Shell it 2 mm inside, with the top face open.
    Fillet the outer rim (the circle where the outside wall meets the top of the wall) by 1 mm.
    Export: tick `Height` and `Diameter`. Expect no size marked "may give unexpected results", and the shell and the
    fillet copied. In `recipe.json` the `openFaces` and `edges` of the two steps hold `near` points with formulas of
    `Diameter` and `Height`. In Paramability set `Height` to 50 and `Diameter` to 80, then to 30 and 40: the cup stays
    open at the top, and the round stays on the outer rim, as in Fusion at the same values. Afterwards the design is
    as before.
78. FS1, far tries one size after the other. Add user parameters `Round` = 2 mm and `Cut` = 5 mm and star `Round` as
    a favourite. On the XY plane sketch a 40 x 30 mm rectangle and extrude it 10 mm up as a new body. Fillet its four
    vertical edges with `Round`. Add a construction plane offset from the bottom face by `Cut`, Split Body with it and
    Remove the upper piece.
    Export: tick `Round` with a range of 1 to 20 mm and `Cut` with a range of 2 to 20 mm. Expect the result window to
    say that the tries stopped early after a try of `Cut`, and name the Remove step. The range of `Round` stops less
    than 2 mm below the largest round Fusion builds on the 30 mm side (about 15 mm), not at 2.5 mm. In `report.json`,
    `probe.states` has the tries of `Round` near 15 mm before the far tries of `Cut`. Afterwards the design is as
    before.
79. OC1, a lasting change in another component. Add user parameters `Width` = 40 mm (star it as a favourite) and
    `Depth` = 30 mm. Make two components, `Box` and `Holder`. In `Box`, sketch a `Width` x `Depth` rectangle on the XY
    plane from the origin and extrude it 10 mm up as a new body. In `Holder`, sketch an 80 x 50 mm rectangle on the XY
    plane from (0, -60) mm and extrude it 15 mm up as a new body. Fillet the top edge of its right end (x = 80 mm) with
    2 mm. Then, on the top face of the holder, sketch a pocket rectangle from x = 5 mm to a line projected from the
    right side edge of the box, 20 mm wide in the middle of the holder, and cut it 5 mm deep. At `Width` = 90 mm the
    pocket cuts through the filleted edge.
    Export: pick the body of `Box`, tick `Width` with a range of 20 to 90 mm and `Depth` with a range of 15 to 60 mm.
    Expect the result window to say that the tries of `Width` ended early after the try at 90 mm, name the fillet of
    the holder (now a warning or an error), and say that the add-in undoes the export. `Depth` keeps its range of 15 to
    60 mm. In `report.json`, `probe.ended` names `Width` and the fillet, and `probe.states` has `Depth` at 15 and 60 mm
    after the try of `Width` at 90 mm. After Fusion undid the export, the design is as before. When the fillet comes
    back by itself with the values back, the export ends as usual and nothing is undone.
80. TO1, steps turned on with a step in error after them. Make two components, `Box` and `Holder`. Add a user
    parameter `Width` = 40 mm. In `Box`, sketch a `Width` x 30 mm rectangle on the XY plane and extrude it 10 mm up as
    a new body. In `Holder`, sketch a 50 x 50 mm rectangle on the XY plane and extrude it 15 mm up as a new body, then
    add a second sketch and extrude on it (these steps are the ones the export turns off). After them, in `Holder`,
    fillet an edge with a radius that is too large for the part, so that the fillet is in error from the start. Keep
    the marker at the end of the timeline.
    Export: pick the body of `Box`, tick `Width`, and leave "Faster tries" on. Expect the export to finish with no
    step of `Holder` turned off, no step in `steps_changed` that is off, and the marker at the end of the timeline.
    The fillet is in error again, as at the start. In `export-trail.log` a line says that steps were turned on with the
    marker held. Afterwards the design is as before.
81. RO1, the steps to get back a design that the export could not undo. Build the model of OC1 (two components, `Box`
    and `Holder`, and the pocket that cuts through the filleted edge at `Width` = 90 mm). Save the design, and make no
    change after the save.
    Export: pick the body of `Box`, tick `Width` with a range of 20 to 90 mm, tick "Lighter on memory", then click OK.
    Expect the result window to say that the add-in could not undo the export, and to show the part "Reopen the
    design" first and open, with three steps: close the design, click Don't Save, open it again from the Data Panel
    with the project, the file name and the version. Expect no button in that part, and no unsaved changes line.
    Fusion must not close or open the design by itself, and must stay stable after you close the window. Follow the
    steps: the fillet of the holder is as it was before the export, and the timeline marker is where it was. The
    `.paramability` file stays saved. Repeat with one change after the save (for example move the timeline marker one
    step and back): the part shows one more line before the steps, which says that every change since the last save is
    lost. Repeat with a design that was never saved to the cloud: expect no "Reopen the design" part.
82. SZ1, a box and a lid that share sizes. Add user parameters `Width` = 60 mm, `Depth` = 40 mm, `Height` = 30 mm
    and `Wall` = 2 mm. Make two components, `Box` and `Lid`. In `Box`, sketch a `Width` x `Depth` rectangle on the XY
    plane from the origin, extrude it `Height` up as a new body, and shell it with the top face open and a thickness
    of `Wall`. Make the lid in three versions, one at a time:
    A. In `Lid`, sketch its own `Width` x `Depth` rectangle on the XY plane from the origin and extrude it `Wall` up as
       a new body.
    B. In `Lid`, sketch on the XY plane, project the four outer bottom edges of the box, and extrude the projected
       rectangle `Wall` up as a new body.
    C. As B, but replace the projected left edge by a fit point spline through three points that bulges 5 mm out.
    Export: pick the body of `Lid` and tick `Width`, `Depth` and `Wall`. In A and B, expect all three as sizes with
    no "may give unexpected results", and `probe.motion.body_moved` empty in `report.json`. In B, `probe.states` has
    tries of `Wall`, and the lid outline follows `Width` and `Depth` in Paramability. In C, expect `Width` and `Depth`
    as "not a size" (they change `Box`, which the lid sketch is drawn around, and the tries do not follow a sketch
    with a spline), and `Wall` as a size, since only the lid's own extrude reads it. Afterwards the design is as
    before. Checked in Fusion 2706 with 0.14.3 plus this change: A, B and C as written here.
83. RV9, picks on the inner walls a shell leaves on a revolve. Add user parameters `Height` = 40 mm, `Diameter` =
    60 mm and `Wall` = 2 mm. On the XZ plane draw a rectangle from x = 0 to `Diameter` / 2 and from z = 0 to `Height`,
    with its left side on the z axis. Revolve it a full turn about the z axis as a new body (a cup). Shell it `Wall`
    inside, with the top face open. Fillet the inner rim (the circle where the inside wall meets the top of the wall)
    by 0.5 mm, and the inner bottom edge (the circle where the inside wall meets the floor inside) by 1 mm. Chamfer
    the bottom face outside by 0.3 mm, picking the face. Make a design the same without the round on the inner bottom
    edge and with the chamfer on the floor inside, picking the face (Fusion cannot chamfer the floor inside after the
    round, since the floor then has only the edge of the round, tangent to it). Make a second design the same, with a second outline on the sketch, a
    5 x 20 mm rectangle from x = `Diameter` / 2 to `Diameter` / 2 + 5 and z = 0 to 20, revolved in the same Revolve.
    Export: tick the three sizes. In the first design expect no size marked "may give unexpected results", and the
    fillet and the chamfer copied with `near` points that hold formulas of `Diameter`, `Height` and `Wall`. In
    Paramability set `Height` to 50, `Diameter` to 80 and `Wall` to 3, then to 30, 40 and 1.5: the rounds stay on the
    inner rim and the inner bottom edge, and the chamfer on the floor inside, as in Fusion at the same values. In the
    second design the two outlines share the side line from z = 0 to 20, so they make one body and the shell hollows
    the ring too: the inner bottom edge lies at x = `Diameter` / 2 + 3. The add-in places the picks on the outline of
    the two outlines together (RV11): expect no size marked, the rounds on the inner rim and on that inner bottom edge
    with formulas of the sizes, and in Paramability the rounds on the same edges as in Fusion at the same values.
    Afterwards each design is as before. Checked in Fusion 2706 with 0.14.3: the first design's picks hold formulas
    of the sizes; the size changes in Paramability and the second design with the joined outline are still to
    check.

84. RV10, picks on the end faces of a half turn. Add user parameters `Height` = 40 mm and `Diameter` = 60 mm. On the
    XZ plane draw a rectangle from x = 0 to `Diameter` / 2 and from z = 0 to `Height`, with its left side on the z
    axis. Revolve it 180 degrees about the z axis as a new body (half a cylinder). Fusion makes the two flat ends of a
    half turn one flat face. Fillet by 1 mm the straight edge at x = `Diameter` / 2 where the flat face meets the
    round side, and chamfer by 0.5 mm the flat face, picking the face.
    Make a second design the same with the angle of the revolve a user parameter `Turn` = 180 deg.
    Export: tick `Height` and `Diameter` (and `Turn` in the second design). In the first design expect no size marked
    "may give unexpected results"; in Paramability set `Height` to 50 and `Diameter` to 80: the round stays on its
    edge and the chamfer on the flat face, as in Fusion. In the second design the round still follows the sizes, and
    the chamfer on the flat face that `Turn` turns keeps its place with the sizes marked. Afterwards each design is as
    before. Checked in Fusion 2706 with 0.14.3 plus this change, except the size changes in Paramability.
85. MP1, one fillet with sets picked in different ways. Add user parameters `Height` = 20 mm and `Round` = 2 mm. On
    the XY plane sketch an 80 x 40 mm rectangle from the origin and extrude it `Height` up as a new body. On its top
    face sketch a 20 x 20 mm square from (10, 10) mm and extrude it 10 mm up as a join (the boss). On the plate top
    face sketch a slot 30 mm long and 10 mm wide with round ends, centred at (55, 20) mm along X, and cut it 5 mm deep.
    Make one Fillet with three sets (rows): set 1 picks the top face of the boss with Tangent Chain off, radius
    `Round` (with Tangent Chain on, Fusion 2706 cannot list the edges of this set and rounds nothing for it: see
    UF1); set 2 picks one
    straight edge of the slot rim with Tangent Chain on, radius 1 mm; set 3 picks the vertical edge of the plate at
    (80, 40) mm with Tangent Chain off, radius 3 mm.
    Second design: the same, but set 3 picks the vertical edge of the boss at (30, 30) mm, which meets the top face of
    the boss at a corner.
    Third design: the first one, but set 3 is a variable radius on the same plate edge, 1 mm at the bottom and 3 mm at
    the top. Make it a second time with one more radius of 2 mm in the middle.
    Fourth design: the first one with a Chamfer of 1 mm on the same three sets instead of the Fillet.
    Fifth design: an 80 x 40 x 10 mm plate with a hole of 10 mm diameter through it, its centre at (10, 7) mm, so its
    rim is 2 mm from the front edge. One Fillet: set 1 picks the top rim of the hole with Tangent Chain on, radius
    1 mm; set 2 picks the top front edge of the plate (y = 0) with Tangent Chain off, radius 1 mm.
    Sixth design: a 60 x 40 x 20 mm block from the origin with a V groove cut along X across its top: its two faces 30
    degrees apart, 10 mm deep, the bottom edge at y = 12 mm. One Fillet: set 1 picks the bottom edge of the groove with
    Tangent Chain on, radius 2 mm; set 2 picks the top front edge of the block (y = 0) with Tangent Chain off, radius
    2 mm.
    Export: tick `Height` (10 to 40 mm) and `Round` (1 to 4 mm) where they exist.
    First design: the fillet is three round steps, one per set, with the note that the sets are copied one after the
    other; `Height` is marked "may give unexpected results" (the tries cannot show that it keeps the sets apart); in
    `report.json` every edge of the fillet sets has `box`, and `turn_deg` near 90. In Paramability the copy matches
    the STEP, and at other `Height` and `Round` values the rounds stay on the boss top, around the whole slot rim and on
    the plate corner.
    Second design: the fillet is one round step with its edges picked one by one, as before this change; the corner
    where the boss edge meets the boss top matches Fusion.
    Third design: sets 1 and 2 are copied, the result window lists the fillet once, as left out with "Set 3 of 3 of
    this step is left out", and the tip about a changing radius; `gaps.json` has a gap for the fillet whose data holds
    one set. With the middle radius the reach of set 3 is not known, so the whole fillet is left out as before.
    Fourth design: three bevel steps.
    Fifth design: one round step (the hole rim comes 2 mm from the plate edge, nearer than twice the two radii).
    Sixth design: one round step (`turn_deg` of the groove edge near 150, so its round reaches 3.7 times its radius).
    Afterwards each design is as before. Checked in Fusion 2706 with 0.14.3 plus this change, except the views in
    Paramability.
86. UF1, a fillet set picked by a face with Tangent Chain on. Add a user parameter `Width` = 40 mm.
    First design: on the XY plane sketch a centre rectangle `Width` x 30 mm on the origin and extrude it 10 mm up as a
    new body. Fillet the four vertical edges, radius 3 mm. Add a second Fillet: pick the front face (the flat side at
    y = -15 mm) with Tangent Chain on, radius 1 mm. Fusion rounds the whole top rim and the whole bottom rim.
    Second design: the same box without the rounded corners. On its top face sketch a centre rectangle 16 x 10 mm on
    the origin and extrude it 6 mm up as a join (the boss). Make one Fillet with two sets: set 1 picks the top face of
    the boss with Tangent Chain on, radius 1 mm; set 2 picks the top front edge of the box (y = -15 mm, z = 10 mm),
    radius 2 mm. Then make one Chamfer with two sets: set 1 picks the bottom face of the box with Tangent Chain on,
    0.5 mm; set 2 picks the vertical edge at (20, 15) mm with Tangent Chain off, 1 mm. Then on the XY plane sketch a
    circle of 4 mm diameter at (-12, 0) mm and cut it 10 mm up.
    Export: tick `Width` (20 to 80 mm).
    First design: the second fillet is one round step with `faceEdges`; `Width` is marked "may give unexpected
    results". In Paramability the copy matches Fusion at every `Width`.
    Second design: Fusion rounds only the front edge (set 1 rounds nothing) and chamfers only the vertical edge
    (the chamfer lists one set). In `report.json` set 1 of the fillet has `read_error` and no edges, and set 2 has
    its edge. The fillet is left out with "Fusion did not give the edges of a set of this round" and the tip "Pick
    the edges of that set, or turn Tangent Chain off for its face, or remove the set if it changes nothing." The
    extrudes, the chamfer and the cut are copied, and the export writes a recipe. The copy differs from Fusion only
    by the round on the front edge. Afterwards each design is as before. Checked in Fusion 2706 with 0.14.3 plus
    this change, through the API, except the views in Paramability.
87. RW1, the result window after an export with "Lighter on memory". Save a design in the cloud with no unsaved
    changes. Add user parameters `Width` = 40 mm and `Wall` = 3 mm. On the XY plane sketch a centre rectangle `Width`
    x 30 mm and extrude it 20 mm up as a new body. Shell the top face inward by `Wall`. Fillet the four vertical
    outside edges, radius 8 mm, so that a small `Width` makes the fillet fail.
    Export: tick `Width` (12 to 80 mm) and `Lighter on memory`.
    The export ends. While the export runs, a line in the status area says the result window opens when the export
    has ended. Right after the export command ends, the window "Saved for Paramability" opens once, with no long
    message box after it. The Text Commands window says "the result window opens when ParamabilityExportCommand has
    ended"; when it says "opening the result window now" instead, note the command it names. The first section "Reopen the design" is open and
    shows its three steps without scrolling, and has no button. "Check your design" and "Result" are open too; "Sizes", "Left out" and
    "More sizes" are folded and open when their title is clicked. A long list scrolls inside its box. Close and
    open the window again from a second export: it still opens. Afterwards the design is as it was.
88. PW1, one progress window. Use a design with several sizes that move sketches, so that the tries run in many batches.
    Export: tick all sizes.
    One window "Measuring how your sketches follow each size ..." shows from the first try to the end. It does not
    open again between tries, and the try number only goes up. It is gone before the result window or a message box
    opens, also after Cancel. Click Cancel part way once: the export stops and no window stays open.
89. TS1, the lighter checks after a try. Add user parameters `Width` = 40 mm and `Wall` = 3 mm. On the XY plane sketch a
    centre rectangle `Width` x 30 mm and extrude it 20 mm up as a new body. Shell the top face inward by `Wall`. Fillet
    the four vertical outside edges, radius 8 mm, so that a small `Width` makes the fillet fail. Add a second
    component with a sketch and an extrude that Fusion shows in a warning before any change (for example an extrude
    that cuts nothing), and leave it unrelated to the first body.
    Export: tick `Width` (12 to 80 mm) and leave `Faster tries` on. Export the same design with the release build
    first and keep its `report.json`.
    The states, the ranges and the reasons for `Width` are the same as in the release build, and the warning that
    the step had at the start is not reported as a new one. `timing.probe.calls` is filled: `computes` has `baseline`
    and no `confirm_new_errors` (a failing try makes no extra rebuild); `health_passes` is about one per try; `timeline_reads` is small;
    `calls.after_tries` has `end_check`. `timing.probe.tries_seconds` per failing try is lower than with the release
    build. Afterwards the design is as it was.
90. RV11, picks where the outlines of one revolve meet. Add user parameters `Radius` = 20 mm, `Height` = 10 mm and
    `Wall` = 1.5 mm. On the XZ plane draw two closed outlines that share a line. The body: a rectangle from x = 0 to
    `Radius` and from z = 0 to `Height`, with its left side on the z axis. The flange below it: the points (0, -1),
    (`Radius` + 0.5, -1), (`Radius`, 0) and (0, 0), so that its outer edge leans out by 0.5 mm and its top is the
    bottom of the body. Revolve both outlines in one Revolve, a full turn about the z axis, as a new body. Shell it
    `Wall` inside, with the bottom face (z = -1) open. Chamfer by 0.5 mm the flat ceiling inside (z = `Height` -
    `Wall`), picking the face, and in the same Chamfer, by 0.3 mm, the inner rim edge where the inside wall meets the
    open bottom (at z = -1, about 18.8 mm from the axis). Make a second design the same with a third outline in the
    same Revolve: a lip on the side, the triangle (`Radius`, 2), (`Radius` + 1, 2), (`Radius`, `Lip`), with a user
    parameter `Lip` = 4 mm.
    Export: tick `Radius`, `Height` and `Wall` (and `Lip` in the second design, with the range 2 to 12 mm typed).
    In the first design expect no size marked "may give unexpected results", the range of `Wall` stopping at about
    2.23 ("the inside wall of Revolve1 that Chamfer1 picks would shrink to nothing"), and both chamfers copied with
    `near` points that hold formulas of the sizes. In Paramability set `Radius` to 25, `Height` to 12 and `Wall` to 2,
    then to 15, 8 and 1: the chamfers stay on the ceiling inside and on the inner rim, as in Fusion at the same
    values. In the second design (past `Lip` = 10 the tip of the lip leaves the side) expect `Lip` as "not a size"
    (the outline changes at other values), `Wall` marked "may give unexpected results", and the chamfers on the
    same faces as in Fusion at other `Radius` and `Height` values. Checked in Fusion 2706 with 0.14.4 plus this
    change: in both designs the chamfer points were on the chamfered faces of Fusion at four other sets of sizes. Afterwards each design is as
    before.
91. RV12, a revolve with a hole and several outlines (Export for Orca). On the XZ plane sketch a rectangle from x = 10
    to 20, z = 0 to 10, with a circle of radius 2 at (15, 5) inside it, and revolve the rectangle (its region with the
    hole) a full turn about the Z axis as a new body. In a second design, first extrude a circle of radius 12 on the XY
    plane by 30 mm, then sketch on the XZ plane two separate rectangles, x = 10 to 20, z = 0 to 5 and x = 10 to 16,
    z = 20 to 25, and revolve both in one Revolve, a full turn about the Z axis, Join.
    Export: Export for Orca each body. In `report.json` the first revolve has one profile with two loops (the circle
    with `outer` false), and the second has two profiles with one loop each and lists one body after it. Both are
    copied with nothing left out: the first as a revolve of the rectangle and a revolve cut of the circle (8240.43
    mm3), the second as two revolves joined to the rod (19352.21 mm3). Afterwards each design is as before.

92. OT1, a name tag with text, for both exports. Add a user parameter `Depth` = 1 mm. Model a 60 x 20 x 2 mm
    plate with its corner at the origin. On its top face make a sketch with the text "AB8" (Arial, 8 mm high), placed
    by its corner at (5, 5). Extrude the text by `Depth` up from the top as a join. Make a second design the same with
    the text cut `Depth` down, and a third with an Emboss of the text on the top face, depth `Depth`. Make a fourth
    design with a 60 x 20 x 10 mm plate and the text on its front face (the face at y = 0), extruded out by `Depth` as
    a join. In the API, the extrude takes the SketchText itself in an ObjectCollection (the sketch has no profile of
    the text, and the feature's `profile` reads back as the SketchText), and `embossFeatures.createInput` takes
    Python lists of the text and of the face. Fusion gives the text of "AB8" as 20 lines and 59 NURBS curves in
    sketch space, and the text adds 64.898 mm3 per 1 mm of depth.
    Export: Export for Orca, then Export for Paramability, with the plate and `Depth` ticked. In both, the text step
    is copied with nothing left out; in Orca it is 2 features (a sketch named "... text" and an Extrude). `Depth`
    follows its variable; the text height and place are listed as kept numbers. In Orca the Design body has the
    volume of the Fusion part within 0.5 percent at `Depth` 1 and 2 (1.5 for the cut, since 2 cuts through the
    plate), and the holes of "A", "B" and "8" stay open. Afterwards each design is as before.

93. OR27, a hole up to a plane and extrudes that start at a distance from a face, for Export for Orca. Add user
    parameters `Lift` = 8 mm and `Inset` = 2 mm. Model a 40 x 40 x 20 mm block centred on the origin with its base on the
    XY plane. Add a construction plane offset from the XY plane by `Lift`. Add a Hole of 5 mm diameter at the middle of
    the top face, with Extent "To" that plane and a flat drill point. Make a second design with a 40 x 40 x 10 mm plate,
    and a 10 x 10 mm square on the XY plane extruded 5 mm up as a join with Start "From object", the top face of the
    plate, and the offset `-Inset` (it starts 2 mm inside the plate). Make a third design the same with the offset
    `Inset` and the extrude 4 mm down (it starts 2 mm above the plate and goes into it).
    Export: Export for Orca each design with its parameters ticked. In `report.json` the hole `extent` is
    `toEntity` of a `ConstructionPlane` with `match_shape` as made, `chained` null and no `offset` (Fusion 2706 gives a
    hole made through the API a `OneSideToExtentDefinition`), and the hole has `end_face_types` `["plane"]` and an `end_points` entry at
    z = 8, and the extrudes have `start_offset` (12 for the third design, null for the second). Export for Paramability
    of the first design copies the hole too. The hole is copied 12 mm deep with its depth following `Lift` (12 - (Lift - 8)); the volume in Orca is
    31764.4 mm3, and with `Lift` = 5 the hole is 15 deep. The second design is copied with its sketch at z = 8 and
    the volume 16300 mm3, the third with its sketch at z = 12 and the volume 16200 mm3; `Inset` is listed as a fixed
    number with the reason that Orca cannot move a sketch plane with a variable. Afterwards each design is as before.
    Open, what `matchShape` means on a face: add a user parameter `Plate` = 10 mm. Model a 40 x 40 mm plate `Plate`
    thick, centred on the origin with its base on the XY plane, and on its top face a 10 x 10 x 5 mm block centred at
    (10, 0) as a join. On the top of the block sketch a point at (10, 0). Make a Hole of 3 mm diameter at that point
    with Extent "To" the top face of the plate, made through the API with `setOneSideToExtent(face, True)`, and a
    second design the same with `False`. Under the hole the plate top face is missing (the block stands there), so
    Fusion must either extend the face or use the faces next to it.
    Export: Export for Orca and Export for Paramability each design with `Plate` ticked. In `report.json` note
    `match_shape` and the `end_points` of the hole, and in Fusion where the hole ends: on the extended plane of the
    plate top (z = 10) or on another face (or the hole fails). With true and with false the extent has `chained` null,
    and `Plate` is marked in both exports. Record which value extends the face; then the reader may give `chained`
    from `matchShape`. Afterwards each design is as before.

94. PP2, path patterns for Export for Orca. Add user parameters `Count` = 4 and `Pitch` = 10 mm. Model a 40 x 20 x 4 mm
    plate with its corner at the origin. On the top face sketch a 6 x 6 mm square centred at (5, 10) and extrude it
    6 mm up as a join. On the top face sketch a line from (5, 10) to (45, 10). Make a Pattern on Path of the square
    extrude along the line: quantity `Count`, distance `Pitch`, spacing, orientation Path Direction. In a second
    design, add `Count` = 5 and `Pitch` = 12 mm, model a 50 x 40 x 4 mm plate, a 6 x 6 mm square centred at (40, 5)
    extruded 6 mm up as a join, and on the top face an arc of radius 35 mm centred at (5, 5) from (40, 5) counter
    clockwise to (5, 40). Make a Pattern on Path of the square extrude along the arc: quantity `Count`, distance
    `Pitch`, spacing, orientation Path Direction. On a copy of the second design, set `Pitch` to 48 mm, the
    orientation to Identical and the distance type to Extent.
    Export: Export for Orca each design with `Count` and `Pitch` ticked. Each path pattern is copied with nothing
    left out: a linear Pattern (4064 mm3), a circular Pattern (9080 mm3) and a Pattern along a sketch arc (9080 mm3,
    `Pitch` kept as a number). In `report.json` the `elements` of the third pattern are moves without a turn. The
    parameter lines say: keep
    `Count` under 5 and `Pitch` under 13.3 mm for the line, `Count` under 5.58 and `Pitch` under 13.7 mm for the arc.
    In OrcaSlicer set the count to 3: each Design body has the volume that Fusion has at `Count` 3 (3848, 8648 and
    8648 mm3). Afterwards each design is as before.

95. PI3, round pipes exported to Orca. Add user parameters `PipeD` = 8 mm and `Wall` = 1 mm. On the XY plane draw a
    path: a line from (0, 0) to (20, 0) mm, then from its end point a tangent arc of 90 degrees and radius 20 mm that
    ends pointing along +Y, then from the end of the arc a line 30 mm along +Y. Use Create > Pipe on the path: Section
    Circle, Section Size `PipeD`, Hollow on, Section Thickness `Wall`, new body. Make a second design: a block from
    (-10, -10, 0) to (50, 30, 20) mm, and on a plane 10 mm above the XY plane a path of a line from (-15, 0) to
    (20, 0), a tangent arc of radius 15 mm to (35, 15) and a line to (35, 40); pipe it with Section Circle 6 mm, Cut.
    Make a third design: a circle of radius 20 mm on the XY plane, piped with Section Circle 4 mm, new body.
    Export: Export for Orca each body with all parameters ticked. Each pipe is copied with nothing left out: a sketch
    of a circle, a sketch of the path and a Sweep, and for the hollow pipe also a sketch of the hole and a Sweep Cut.
    `PipeD` and `Wall` follow variables, and their lines give the limits (`PipeD` from 2 to 39.9 mm, `Wall` up to
    4 mm). In OrcaSlicer the Design body has the volume of Fusion (Inspect > Properties) within 0.5 percent: 1790.43
    mm3, 46061.46 mm3 and 1579.14 mm3. The ends of the first pipe are flat and square to the path, as in Fusion. With
    `PipeD` set to 10 in OrcaSlicer, the first body is 2301.98 mm3. Afterwards each design is as before.

96. OR28, a Press Pull of a whole round face, for Export for Orca. Add user parameters `Grow` = 1 mm and `Fit` =
    0.5 mm. Model a 40 x 40 x 5 mm plate centred on the origin with its base on the XY plane, and on its top face a
    circle of radius 5 at the origin extruded 10 mm up as a join (a pin). Press Pull (Offset Faces) the round face of
    the pin by `Grow`. Make a second design with a 40 x 40 x 10 mm block and a circle of radius 4 at the origin cut
    through it (a bore), then Press Pull the wall of the bore by `-Fit`. Make a third design as the first with the
    pin Press Pulled by `-Grow`.
    Export: Export for Orca each design with its parameter ticked. In `report.json` the Press Pull has one face of
    `kind` `round` with two `ends` of kind `circle`, each with its flat end face, and `rounds_after` holds the
    cylinder of the new radius. Each Press Pull is copied with nothing left out, as 5 features (two sketches, two
    extrudes and a Boolean: Add for the first design, Cut for the others). The volume in Orca is 9130.97 mm3
    (9539.38 with `Grow` = 2), 15363.83 mm3 (15214.60 with `Fit` = 1) and 8502.65 mm3 (8282.74 with `Grow` = 2).
    The line of the parameter tells how far it may go (under 14.9, 15.9 and 4.99 mm). Afterwards each design is as
    before.

97. BP1, patterns of bodies that a Combine joins or cuts, for Export for Orca. Add user parameters `Count` = 4,
    `Pitch` = 14 mm and `PegH` = 6 mm. Model a 60 x 20 x 4 mm plate with its corner at the origin (Body1). On the top
    face sketch a 6 x 6 mm square centred at (8, 10) and extrude it `PegH` up as a new body (Body2). Make a
    Rectangular Pattern of Bodies of Body2 along X: quantity `Count`, distance `Pitch`, spacing. Then Combine Join
    with Body1 as the target and Body2 and its three copies as the tools. In a second design make a 60 x 60 x 4 mm
    plate centred on the origin, a 6 x 6 mm peg centred at (20, 0) as a new body, a Circular Pattern of Bodies of the
    peg about the Z axis, quantity 6, full circle, and a Combine Join of all six pegs into the plate. In a third
    design make a 40 x 20 x 4 mm plate centred on the origin, a peg centred at (-12, 0) as a new body, a Mirror of
    the peg body across the YZ plane, and a Combine Join of the peg and its mirror image into the plate. In a fourth
    design make a 60 x 20 x 10 mm block with its corner at the origin, a 6 x 6 mm square centred at (8, 10) on a
    plane 4 mm above the XY plane extruded 10 mm up as a new body, a Rectangular Pattern of Bodies of it (quantity
    `Count`, distance `Pitch`), and a Combine Cut of the four bodies from the block.
    Export: Export for Orca each design with all parameters ticked. Each Combine is copied with nothing left out, as
    one tool body, a Pattern or a Mirror of it and one Boolean (Add, or Cut for the fourth design); the pattern says
    "Copied with Combine1". `Count` is fixed with the reason that Fusion may not change what its Combine takes,
    `Pitch` and `PegH` follow. The volume in Orca is 5664, 15696, 3632 and 11136 mm3, as in Fusion (Inspect >
    Properties). In OrcaSlicer set `Pitch` to 18: the first body reaches x = 65 with 5664 mm3, the fourth has
    11316 mm3. Set `PegH` to 10: the first three are 6240, 16560 and 3920 mm3. In Fusion set `Count` to 5 and look
    whether the Combine takes the new copy: note what it does. Afterwards each design is as before.

98. CO4, a coil spring for Export for Orca. Add user parameters `Pitch` = 5 mm and `Wire` = 2 mm. Make a Coil with
    Insert > Coil on the XY plane, centred on the origin: type "Revolutions and Pitch", diameter 20 mm, revolutions 4,
    pitch `Pitch`, round section, section size `Wire`, section position "On center", right hand, new body. Make a
    second design with a cylinder of radius 10.5 mm and 30 mm high on the XY plane, and the same coil on the XY plane
    as a Cut (a groove round the cylinder).
    Export: Export for Orca each design with both parameters ticked. The coil is left out with the reason that Orca
    keeps the wire square to its turns, and `orca.left_out[]` has the cause `coilShape`; the cylinder of the second
    design is copied. In `report.json` the coil's two `faces.flat` frames have a `z` (the face normal) square to the
    Z axis, so Fusion's end faces lie on planes through the axis. Fusion gives the first body 789.57 mm3 (Inspect >
    Properties; a round tube along the helix would be 792.06). Afterwards each design is as before.
