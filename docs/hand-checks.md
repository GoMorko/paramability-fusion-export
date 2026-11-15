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
   Export: each copy leans the same way as in Fusion. A "Symmetric" draft that crosses the plane is left out with a
   reason.

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

5a. ST1, steps with their own reason. Model a 40 mm box and use Modify, Scale on it; on a second box add a Rib (a
   sketch line across a shell) and a Web; on a third use Replace Face with a surface, Pattern on Path with a sketch
   curve, and Boundary Fill between two bodies.
   Export: each part is left out or saved as a fixed shape with a step name and a plain reason (not "Steps of type
   ..."), and a tip in `gaps.json`. In `report.json` note the capture `type` of each step: the add-in expects
   ScaleFeature, ReplaceFaceFeature, RibFeature, WebFeature, PathPatternFeature, BoundaryFillFeature and (surface
   Offset) OffsetFeature; any other name gets the generic reason.

5b. CC5, a lid that follows a box not in the file. Make component Box with user parameter `Width`. In component Lid,
   sketch on the box top face, project the box outline, offset it 0.2 mm inwards and extrude 3 mm.
   Export: export the Lid alone, tick `Width`. The notes say the part follows the sizes of Box. Export Box and Lid
   together: that note is gone, and changing `Width` in Paramability changes both parts.

5c. CC1, a cut from the top level. Make components Box and Lid (a box 80 x 60 x 30 mm, a lid 80 x 60 x 3 mm on top).
   With the top level active, sketch two 3 mm circles on the lid top and cut them through both bodies.
   Export: export the Lid. The copy stops at the cut with "changes this part from another component" and a tip to
   move the step into the part's component or export both parts together.

6. AS1, steps after a stop. Extrude a box, split it with the curved face of a cylinder body and remove the outer
   piece, then add a thicken joined to the box.
   Export: the box is saved as a fixed shape with the split as the reason, `after_stop` names the split and the
   thicken, and the window says the thicken was not copied either.

7. SP1, marker roll. Make component Cup (60 mm square sketch from user parameter `Width`, extruded 40 mm), then
   component Rack with about 100 steps (a pattern of 200 holes, fillets, chamfers).
   Export: tick `Width` on the Cup. `probe.timeline` has `rolled: true` and fewer items than the whole design, and
   the time per try is about the time of the Cup alone.

8. SP2, one change per try. In the SP1 design add user parameter `Height` for the extrude and a 5 mm fillet on the
   top edges; give `Width` a range down to 8 mm so the fillet fails at the low end.
   Export: tick both. The failing tries are listed in `probe.dropped` with the fillet named, the `Width` range is cut,
   and the design shows its old values with no step in error afterwards.

9. SP4, memory and Undo. Use the SP2 design.
   Export: watch Fusion in Activity Monitor (Memory) before, during and after; then use Edit, Undo once. Note the
   peak, the value after the export and after Undo, and whether Undo lists the export as one step.

10. TH1 and TH5, steps after the export. TH1: a box from a 20 by 20 mm rectangle (user parameter `Width` = 20 mm)
    extruded 15 mm, the four vertical edges filleted with 9.9 mm. TH5 needs a second design: a 40 by 30 by 20 mm box,
    the vertical edges filleted with user parameter `Round` = 5 mm, then the top edges chamfered with `Bevel` = 4 mm,
    so the chamfer runs into the fillets.
    Export: TH1, tick `Width` with a range of 12 to 40. The low tries fail at the fillet and the range is cut; after
    the export the fillet has no warning and `health` has no `steps_changed` (`steps_recovered` and `end_actions` may
    show the add-in rebuilt the design). If `steps_changed` is there, note each `name`, `before`, `after` and
    `message`, then use Edit, Undo and count the steps that bring the fillet back. TH5: tick `Round` and `Bevel` (range 1 to 9) and
    cancel in the "Try 3 of ..." window; then, on the TH1 box, use Export size choices with a row `Width` = 12, which Fusion cannot build. In both, every step is
    as before; if not, a message box names the step and says to use Undo.

11. LP1, the list before the export. Extrude a 40 by 30 by 20 mm box. Round one vertical edge with a variable radius (a
    different radius at each end). Then round the top edges with 1 mm, which includes the edge between the top and
    the face the variable round made. Add a second body, a plain box with no such step.
    Export: pick the first box and do not click OK. Under the body picker a box lists the variable round with the
    reason and "Tip: Use a fillet with one radius.", and says "More may show after the export." (the 1 mm round picks
    faces that only the export can check). Pick the second box: the list is gone. Pick both: the list starts with
    the first box's name and says "More may show" once. The Text Commands window has a line "warning under the body
    picker: ... s; reading the steps of the picked bodies: ... s". Then click OK on the first box: the Saved window
    names the variable round with the same reason and tip, and any step of the 1 mm round it also lists is the one
    the "More may show" line was about. Note the seconds from the log line on a design with 100 or more steps: the
    warning itself should take well under a second.

11. LB1, size labels. Model a 40 x 30 x 10 mm box from three user parameters: `Wall_thickness_mm` (3 mm, comment
    `Wall thickness`), `BaseCup_midExtrude_offset__mm` (5 mm, no comment) and `Hole_diameter_mm` (6 mm, a comment of two
    long sentences describing the hole).
    Export: tick all three. In Paramability the form reads "Wall thickness", "Base cup mid extrude offset" and "Hole
    diameter". Each field has an info tip "Name in the original design: ..." with the Fusion name, the long comment is
    the text under the "Hole diameter" field, and the result window still lists the sizes by their Fusion names.

11. CO1, a coil on a block. Model a 40 x 20 x 10 mm block. Make a Coil with Insert > Coil (Fusion's Coil command) on a
    plane at the top of the block: diameter `CoilDia` = 10 mm, section size `Wire` = 2 mm, revolutions 3, height
    `CoilHeight` = 12 mm, round section, section position inside, clockwise, operation Join. Make a second design with
    a square section, counter clockwise and "Revolutions and Pitch" (pitch 4 mm).
    Export: tick `CoilDia`, `Wire` and `CoilHeight`. `report.json` has `items[].data` of the coil with `roles`,
    `params`, `volumes_before`, `made` and `faces` (two flat end faces and sampled edges); the copy has a `coil` step,
    and in Paramability the coil matches the Fusion one (same hand, same rise, joined to the block). Changing `Wire`
    or `CoilDia` moves the coil as in Fusion. The ranges stop before the wire reaches the axis or the turns touch.

12. CO2, coils the copy leaves out. In the CO1 design add a coil each with: a taper angle of 5 degrees; type Spiral;
    revolutions 2.5; a triangle section. Join each to the block.
    Export: the taper, the spiral and the 2.5 revolutions coils are left out with their own hint. The triangle coil is
    copied with its numbers (`Wire` and `CoilDia` are marked, not followed).

13. CO3, coil as a tool and the caps. Make a coil as a New Body, then Combine it (Join) with the block. Repeat to get
    more than 8 coils in one design (or 17 coils joined one by one).
    Export: the Combine of a lone coil body is copied as a plain coil step. From the ninth coil on, the coils are left
    out with the hint about 8 coils and 100 turns; the first eight stay. A coil body that also has a cut or a fillet
    in its tool is left out with the hint to join the coil before changing it.

11. TD1, modeled threads. Make a jar: a cylinder body of 30 mm diameter and 20 mm long (user parameter `Neck` for
    the length), and add a Thread (Create, Thread) on its side with "Modeled" ticked: an ISO Metric profile, M30x2,
    full length, right hand. Make a second design with a left hand M20x1.5 thread over only 10 mm of a 25 mm long
    cylinder, started from the lower end. Make a third with an ANSI Unified thread, and a fourth with an ACME thread.
    Export: tick `Neck`. In `report.json`, the item of the thread must hold `thread_type`, `pitch` (2.0), `major_diameter`
    (30.0), `minor_diameter`, `right_hand`, and a `faces` entry with `radius` 15, a `span` and `outward` true. If
    a number is missing or 10 times too big or too small, the units of the thread info differ from the reader's guess
    (cm). The thread copies as a `thread` step; the metric and Unified ones copy, the ACME one is left out with the
    hint about 60 degree threads. Changing `Neck` in Paramability changes the thread length. In the partial thread
    design, `made_span` must show where the made faces lie along the axis, and the copy must start at the same end.
    Compare the volume of the copy with Fusion: the threads differ a little in the crest and root shape, note by how
    much. In Fusion, also check what start angle the thread has: the copy always uses its own.

12. TD2, threaded and up to a face holes. Make a plate 40 x 40 x 12 mm with a tapped Hole (Hole tool, "Tapped",
    "Modeled" ticked, M6x1) 8 mm deep with full length thread, and a second one with a thread length of 5 mm. Make a
    through hole with a modeled M5 thread. Then make a Hole whose extent is "To" an inner floor (a second box body
    or a stepped pocket), and one up to a body.
    Export: each tapped hole copies as a hole at the minor diameter plus an internal `thread` step. In `report.json`
    the hole item must hold `thread` with `pitch`, `major_diameter`, `minor_diameter`, `right_hand`, `full_length`
    and for the 5 mm one `depth` 5.0. If those members are missing, note where Fusion keeps them (on `feature.thread`
    or on the hole). Check also what `sideFaces` holds for a modeled thread (the bore cylinder, or only the helical
    faces); the copy cuts the bore at the minor diameter from the thread info. The holes up to a face and a body copy
    as blind holes of the measured depth, and when the floor follows a parameter the hole depth follows it. A hole up to a
    face that ends in a drill point is left out with a reason.

11. FM2, a formula of numbers. Model a 40 x 40 x 20 mm box, shelled with the user parameter `Wall = 3 * 0.4 mm`.
    Export: `Wall` is a size and starts ticked. Changing it in Paramability changes the wall. After the export, the
    Parameters dialog in Fusion shows `3 * 0.4 mm` again.

12. FM3, a guarded count. On a 100 x 40 x 5 mm plate, cut one 5 mm hole and make a rectangular pattern of it with
    quantity `max(1; floor(Width / 20 mm))`, where the user parameter `Width = 100 mm` drives the plate.
    Export: tick `Width`. The hole count follows `Width` in Paramability, and `Width` has no warning mark. Repeat
    with the quantity `if(Width > 60 mm; 3; 2)`.

11. FP1, a fixed part in a parts package. Make component Box (an 80 x 60 x 30 mm box from user parameter `Width` =
    80 mm) and component Lid (80 x 60 x 3 mm on top of the box, sketch size from `Width` too). Add to the Lid a Split
    Body by the curved face of a cylinder body, so the Lid copy stops (see AS1).
    Export: pick Box and Lid together. The Lid is a fixed shape and the Box has a recipe. `Width` is marked "may give
    unexpected results" with "Lid stays a fixed shape in this file and does not change with this size." in the
    result window and in `report.json` `sizes.loose`. A size that only the Lid reads (add a second user parameter
    used by the Lid alone) is not offered at all.

11. PC1, a part that comes apart. Model a 80 by 20 by 5 mm plate whose length is user parameter `Width` = 80 mm,
    with the left end fixed at x = 0 and the right end at `Width`. On its top face draw a 4 mm circle at x = 70 and
    extrude it 5 mm up with Join. Second design: the same plate with a 2 mm wide slot cut across it at x = 40, 4 mm
    deep, its depth user parameter `Slot` = 4 mm.
    Export: in the first design tick `Width` with a range of 40 to 160; in the second tick `Slot` with a range of 2
    to 8. In `report.json`, the tries below 68 mm (first) and at 5 mm or more (second) have `pieces` 2 in
    `probe.states` and an entry in `probe.dropped`; each range is cut with "the part comes apart into 2 separate
    pieces in Fusion at ...". Note for each design whether the post or the second half shows as its own body in the
    browser at such a value or as part of Body1, and `timing.probe.read_parts.pieces` against `read_parts.box`.

12. HE1, a hole that reaches the edge of its face. Model a lid, 60 x 40 x 3 mm, whose length is user parameter `Width`
    = 60 mm (left end fixed at x = 0). Cut a round hole of 16 mm diameter through it at x = 30 mm, then use Emboss to
    raise a 10 mm triangle 0.5 mm on its top face, half over the hole.
    Export: tick `Width` with a range of 10 to 120. The range starts just above 38 mm (the hole ends at x = 38), with the reason
    "the outline of the face ... would cross itself, lose a corner or have a hole reach its edge". In Fusion, set
    `Width` to 40 mm and then to 36 mm: at 36 mm the hole breaks the edge of the lid and the face is a different
    shape, so Paramability must not offer that value. In Paramability, set `Width` to the smallest value: the
    triangle is trimmed to the lid and is not left floating.
