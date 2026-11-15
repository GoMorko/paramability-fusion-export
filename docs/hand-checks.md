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

6. AS1, steps after a stop. Extrude a box, split it with the curved face of a cylinder body and remove the outer
   piece, then add a coil joined to the box.
   Export: the box is saved as a fixed shape with the split as the reason, `after_stop` names the split and the
   coil, and the window says the coil was not copied either.

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
