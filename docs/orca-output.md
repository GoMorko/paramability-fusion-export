# The Orca output (experimental)

"Export for Orca (experimental)" saves one body as an OrcaSlicer 2.5 project (`.3mf`). The plate shows the body as
a mesh, and Orca's Design tab holds a recipe of its steps, so the person can change the variables there and the part
follows. The `.paramability` output does not change.

## What the person does

1. In OrcaSlicer 2.5, turn on Preferences > General > Features > "CAD feature (experimental)", then restart Orca.
2. Open the file. The file is marked as a shared ("published") project, so Orca keeps the person's own printer,
   process and filament presets, and opens it without a file name (Save asks where to save).
3. Change the variables in the Design tab. The Design body follows.
4. Commit adds the changed body to the plate as a new object; the mesh from Fusion stays. Delete the old object.

## How it is made

The command (`commands/ExportForOrca/`) reuses the dialog of Export for Paramability (`recipe_dialog.build(...,
orca=True)`: one body, the parameter table, the up direction) and the export pipeline with
`ExportRequest.output = "orca"` (`export_plan/pipeline/run.py`, `_run_orca`):

- the mesh of the body (`port.read_mesh`, `fusion_reader/body_mesh.py`: Fusion's mesh calculator, in root
  coordinates and mm, an STL export as the fallback) instead of the STEP;
- the capture and the size table, as for a recipe;
- one translation, switched at `recipe_export.translate_capture(..., output="orca")` to `orca_translate`;
- no size tries. Min and Max, Faster tries, the time limit and Lighter on memory are not used, and a bad Min or Max
  does not block OK;
- the design is put back and checked as for a recipe (`PutBack`), and the result window has the same `# Title`
  sections (`dialog_model/orca_result.py`): Check your design, Result, Variables, Left out, Next in OrcaSlicer;
- the dialog shows a warning under the body picker, as the dialog of a recipe does: the steps that the Orca copy will
  probably leave out, one line each with its reason and tip (`orca_result.preview`, which reads one Orca translation
  with no sizes ticked, and `left_out_preview.find_orca`). The list is whole for the sizes that are not ticked, because
  the Orca translation decides every step it leaves out by itself;
- the file (`export_plan/orca_export.py`): the mesh, `Metadata/orca_cad.bin` (`orca_recipe`) and
  `Metadata/paramability_report.json`, the report with the capture and an `orca` block (features with their bound
  fields, variables, what each ticked parameter became, the steps left out, the plate move) and `mesh_check` (the
  mesh's box against the part's box on the plate). When the steps cannot be read or translated, the file holds the
  mesh and an empty recipe (`outcome: meshOnly`). The same report is written beside the file as
  `<name>.report.json`, since Orca drops the entry inside when the person saves the project from Orca.

The modules of `lib/orca_translate/`:

- `translate.py`: the walk over the timeline. It passes by the steps that do not build the body, gives every other
  step to the handler of its kind (`HANDLERS`, gathered from the handler modules) and keeps the verdict of each step.
  It reads the design from the shared layer (`design_model.design.read`), the same resolved steps the recipe walk
  reads: what each step is for the body (a sketch, an assembly item, a step of another component, a step of the body
  or of another body) and the body before and after it (`design_model.roles`), what about it cannot be read (the
  step, its bodies, or a step in error in Fusion), and the step with the geometry of other components brought in. A
  left out round or chamfer is measured from the sets in the resolved step (`facts`). Each handler gets the resolved
  step (`handler(ctx, step)`) and reads its step only through it (see "Handlers read the resolved step" in
  `docs/developer-guide.md`).
- `context.py`: what one translation keeps while it walks: the recipe so far, the formulas it bound, the sizes that
  keep their numbers and why, and the part built so far. Its `Context` is a `design_model.recorder.Recorder`
  (`cache`, `motion` always None, `doubt`, `note`, `follow_component`), so the shared layer can record on it. A value
  that follows sizes is a `design_model.values.Quantity`, the same type the recipe translator uses: `Context.quantity`
  reads it from the model parameters of the step (`design_model.design.params_of`), and `Context.bind` turns its formula into an Orca formula (`formulas.to_orca`) and
  writes it into the field.
- `other_components.py`: geometry of other components (see "Other components" below).
- `kept_refs.py`: planes, axes and faces of the part's own component that a step writes as numbers (see "Which
  parameters follow").
- Handler modules, one per kind of step: `steps.py` (extrude; `thin.py` builds a thin extrude, see "Thin extrudes"), `holes.py` (hole), `revolve.py` (with
  `revolve_parts.py`, which writes its sketches, revolves and tool bodies), `sweeps.py`, `pipes.py` (a round
  pipe as a sweep of its circle, see "Pipes"), `lofts.py`, `repeat.py` (patterns and mirrors; `repeat_path.py` patterns along a path), `combine.py` (with `body_pattern.py`, the
  copies of a pattern or mirror of bodies that a Combine takes), `paste.py` (a pasted body, built as its source stood
  at the paste), `bodies.py` (split and move), `finishes.py` (fillet
  and chamfer), `threads.py`, `emboss.py` (an emboss on a flat face, written by the extrude handler), `rib_web.py` (a rib or a web, each wall
  written by the thin extrude, see "Ribs and webs") and
  `press_round.py` (a Press Pull of one whole round face, see "Press Pull of a round face"), and `coils.py`, which
  leaves every coil out (see "Coils"). `holes.py` and `threads.py` read the hole and the thread through the shared readers
  `design_model/steps/hole.py` and `thread.py` (the kind, the direction, the measured sizes, the thread numbers and
  the cylinder of a thread), and turn a `Problem` into a `Skip`. A handler gives the features it wrote or a `Skip` (`skip.py`) with the reason and a
  cause (`causes.py`).
- Helpers of the handlers: `extents.py` (To, From and taper of an extrude, as values that follow sizes), `text_regions.py` (sketch text
  as Orca's imported regions), `hole_place.py` (where holes sit), `hole_reach.py` (the depth of a hole up to a face or plane),
  `drilled.py` (circle holes of the first outline drilled as Orca holes), `sketch_sizes.py` (the sizes an outline
  sketch follows or keeps),
  `sketches.py` and `splines.py` (outlines as Orca sketches), `sweep_splines.py` (splines of a sweep path, exactly), `outline_cuts.py` and `halfplanes.py` (outlines of
  straight lines whose corners follow sizes, built from plane cuts), `tools.py` (tool bodies for Combine, patterns and
  mirrors, also of other components), `finish_body.py`, `outline_rounds.py` and `left_corners.py` (the edges rounds and chamfers pick, and the
  measuring of left out rounds), `corner_tools.py` and `corner_hosts.py` (rounds and chamfers of side edges on
  outlines whose sizes follow variables, cut as corner tools), `limits.py` (how far a
  variable may go), `formulas.py` (formulas Orca can write) and `place.py` (where the part sits on the plate).
- `solid.py`: the part the copy has built so far, as simple shapes, for the checks of cuts and the copy's own box.

Which sizes may move a sketch, a plane or a face is not decided in `orca_translate`: it is in the shared layer
(`design_model/reach.py`). The Orca output reads those sizes and decides what to do: it keeps the number and marks the
sizes. `sketch_sizes.profile_sizes` and `translate._item_sizes` call `reach.profile_sizes` and `reach.step_sizes`.

`sketch_sizes.py` gives the helpers that the handlers of outlines share: `sketch_formulas` (each sketch solved once
per translation) and `sketch_doubts` (the sizes an outline sketch follows or keeps), and `projection_doubts` (the
sizes that may move geometry projected into a sketch). `steps.py` also gives `misses_reason` (the reason for a cut
that meets nothing), and for holes `toward_material` and `behind` (the side of a one way cut or hole through all).

## What is copied

`lib/orca_translate/` turns a capture into an Orca recipe:

| Fusion | Orca | Follows variables |
| --- | --- | --- |
| User parameters ticked in the dialog | `variables` in mm and degrees; a formula parameter keeps its formula when Orca can write it | |
| An outline that is one rectangle that keeps its place and direction | simple rectangle, its plane at the rectangle's centre | `width`, `height` |
| An outline of straight lines (one loop, no holes) whose corners follow sizes, of an extrude without taper: also a rectangle that moves or turns (see "Outlines built from plane cuts") | a square block on the sketch plane, extruded as the extrude, a Cut per side (between two Transforms for a side that turns), tool bodies cut away at inward corners, a Boolean into the part | every corner: `cut_offset`, `xf_angle_deg` |
| An outline that is one circle | simple circle | `radius` |
| Any other outline of lines, arcs, circles, full ellipses (centre, major and minor radius, major axis direction) and splines (a spline whose exact shape Fusion gives, see "Sweeps, lofts and splines"), and an outline the cuts cannot build | sketch entities at their current values | no |
| The first body's outline with holes | the outer outline, then a cut through all per hole, so each stays a simple rectangle or circle where it is one; a circle hole whose centre moves, in a one sided extrude without taper, is an Orca Hole through all instead (see "Outlines built from plane cuts") | as above; the drilled hole: `hole_x`, `hole_y`, `hole_diameter` |
| Extrude: one side, symmetric, two sides; new body, join, cut, intersect; a distance, or through all for a cut or intersect; a start offset | Extrude | `distance`, `distance2` |
| Extrude side "To" a flat face or plane square to the extrude, with an offset | the measured distance (Blind, or a side of Two sides) | `distance` when the plane follows: an offset plane, or an end face of a copied extrude (see "Extents") |
| Extrude "From" a flat face or plane square to the extrude, at an offset from it or not | the sketch plane moved to that plane, and by the offset (the way the measured start face shows) | no |
| Thin extrude of one rectangle or one circle, one way or symmetric, no taper (see "Thin extrudes") | the outer outline as a new body less the inner outline cut through all; on a part, as a tool body and a Boolean with the step's operation | `width`, `height`, `radius` (the drawn size plus or minus the thickness), `distance` |
| Thin extrude of one straight line, the wall centred on it | simple rectangle centred on the line | `width` (the length of the line), `height` (the thickness), `distance` |
| Thin extrude of any other open line of straight lines | the outline of the wall as sketch lines | `distance`; the line and the thickness keep their numbers |
| Rib or web along straight lines, no draft, no fillet (see "Ribs and webs") | one thin extrude of an open line per line | as the thin extrude: `distance`, and `height` for a straight line with the wall centred on it |
| Extrude of a flat face of the body (the face as the outline) | sketch entities of the face where it is now | no |
| Extrude of sketch text: one side, symmetric, or a cut through all; no taper (see "Sketch text and embosses") | a sketch of its own with each letter as an imported region (polygons within 0.005 mm of the letter), Extrude | `distance` (the text keeps its size and place) |
| Emboss on a flat face: raised or sunk, text or other outlines (see "Sketch text and embosses") | the extrude from the face it stands for | `distance` (the depth) |
| Tapered extrude: one side, symmetric or two sides, of an outline that Orca tapers the same way (see "Extents") | Extrude with `taper_deg` (Blind; two Blind halves for symmetric and two sides) | `taper_deg` for a smooth outline |
| Hole: simple, counterbore, countersink; a depth or through all; one Orca hole per point | Hole | diameter, depth, counterbore and countersink sizes |
| Hole "To" a flat face or plane square to the hole, with a flat end (see "Extents") | Hole of the measured depth | `hole_depth` when the plane follows: an offset plane, or an end face of a copied extrude |
| Hole on sketch points, with the sketch's frame (`sketch_frame`) and graph in the capture | Hole on the sketch plane, at `hole_x`, `hole_y` | `hole_x`, `hole_y` |
| Tapped hole with a cosmetic thread | Hole at the drill size | as Hole |
| Tapped hole with a modeled thread (metric or Unified, right hand), simple or counterbore | Hole at the minor diameter, then an inside Thread per point from the counterbore floor or the top, half a pitch inside each end, and a lead-in Hole at each open end | as Hole; `thread_height` with the depth (the thread start under a counterbore keeps its number) |
| Thread, modeled, on one cylinder (a rod or a hole wall) | Thread, half a pitch inside each end, and a lead-in at each open end (a Hole in a hole, a ring cut on a rod) | `thread_height` (a set length) |
| Thread, cosmetic | nothing (it changes no shape) | |
| Press Pull (Offset Faces) of one whole round face: a pin, a boss or a bore whose face goes all the way round between two flat ends square to its axis (see "Press Pull of a round face") | a tool body of two circles on the axis, the outer one extruded between the end planes and the inner one cut through it, then a Boolean: Add for a pin or boss that grows or a bore that shrinks, Cut for a bore that grows or a pin that shrinks | `radius` of the circle of the new radius (the distance) |
| Fillet or chamfer (an even chamfer) whose edges are exactly one of Orca's edge groups of the copied part, or, with sets of different sizes, a top group and a bottom group | Fillet or Chamfer of that face group: all, top, bottom or side edges; one for each size | `dressup_size` |
| Fillet or even chamfer whose edges all run along copied straight extrudes, at corners of two lines of their outlines (each set may have its own size) | the extrude's sketch drawn again: an arc tangent to both lines, or a line across the corner | no: the round keeps its number |
| The same, on an outline whose sizes follow variables (built from plane cuts, or a rectangle whose width or height follows) | a corner tool per corner, cut from the outline's body before it goes into the part: a through all block cut by four planes (three for a chamfer), between two Transforms for a line that turns, less an Orca Hole at the arc centre, and a Boolean (see "Corner tools") | every corner and the round's size: `cut_offset`, `xf_angle_deg`, `hole_x`, `hole_y`, `hole_diameter` |
| Rectangular pattern of features, one or two directions, to one side or both | the repeated steps as a tool body, one Pattern per direction (two tool bodies for a direction to both sides), a Boolean into the part | `pattern_count`, `pattern_spacing` |
| Circular pattern of features | the repeated steps as a tool body, a circular Pattern about the axis, a Boolean | `pattern_count`, `pattern_angle` |
| Path pattern of features along one straight line | the repeated steps as a tool body, a linear Pattern along the line (as a rectangular pattern of one direction), a Boolean | `pattern_count`, `pattern_spacing` |
| Path pattern along one arc or a full circle, the copies turning with the path | a circular Pattern about the arc's axis; the angle is the distance x 180 / (pi x radius) | `pattern_count`, `pattern_angle` (only the count round a whole circle) |
| Path pattern along one arc, the copies keeping their direction | a sketch arc from the start of the path to the last copy, Orca's pattern along that curve | `pattern_count` for a distance over the whole extent; the distance keeps its number |
| Mirror of features | the repeated steps as a tool body joined with its Mirror, a Boolean | no |
| Mirror of the body joined to it | Mirror of the part (Add) | no |
| Rectangular or circular pattern, or mirror, of bodies whose copies one Combine joins to the part or cuts from it | the sources as one tool body, as they are just before the pattern, one Pattern per direction or a circular Pattern or a Mirror of that tool, a Boolean with the Combine's operation; copies of the part joined to it: a Pattern or Mirror of the part | `pattern_spacing`, `pattern_angle`; the count keeps its number |
| Combine: join, cut, intersect | each tool body from the steps that made it, then a Boolean (Add, Cut, Intersect) | as the tool's steps |
| Copy and paste of a body, in place: the part itself, or a body that a Combine takes, moved first or not | the steps of the source before the paste written again as a body of its own (later steps of the source do not reach it), then the later steps of the pasted body (a Move as a Transform, a Combine as a Boolean) | as the source's steps |
| Combine with a tool body of another component | the tool from its steps in its component's coordinates, a Transform to its place, then the Boolean (see "Other components") | as the tool's steps, never only that: the sizes acting on that component are marked |
| Split Face that leaves the solid as it was (the reader saw the part unchanged) | nothing: the step is skipped, as in the other export. A Split Face that may have changed the solid is left out | no |
| Split Body by a plane or a flat face | Cut by that plane, keeping the part's side | no |
| Split Body by a solid body | that body as a tool, then a Boolean (Intersect inside it, Cut outside it) | as the tool's steps |
| Move of the body: a turn about an axis (a negative angle turns about the reversed axis) | Transform about that axis | `xf_angle_deg` |
| Move of the body: any other move | Transform by the measured turn and shift | no |
| Revolve of one or more outlines, with or without holes, the axis in their sketch plane: a full turn, an angle, an angle to both sides, two sides with two angles | per loop a sketch with a construction line on the axis (`revolve_axis_entity`), a Revolve of each outer loop, a Revolve Cut of each hole; on a part that holds material an outline with holes is a tool body and a Boolean, as is an intersect of several outlines. An angle to both sides that follows a size is two Revolves from the sketch, one with `flip` | `revolve_angle` (to both sides as `min(angle, 180)` on each half; not for an intersect or two sides) |
| Sweep along a straight path | Extrude of the outline, as long as the path | the outline's sizes |
| Sweep along one arc or a full circle | Revolve of the outline about the arc's axis | no |
| Sweep along lines, arcs and splines in one plane that meet smoothly, open or closed (a closed path without splines), one outline without holes | the outline's sketch, a sketch of the path from the outline (splines as exact B-spline pieces), Sweep | the outline's sizes (`width`, `height`, `radius`) |
| Pipe with a round section, solid or hollow, along the whole path: a line, an arc, a full circle, or lines, arcs and splines in one plane that meet smoothly (see "Pipes") | a circle sketch square to the path at its start, a sketch of the path from there, Sweep; a hollow pipe also the circle of its hole and a Sweep Cut, on a part that holds material as a tool body and a Boolean | `radius`: half the size; the hole's radius less the wall |
| Loft between two circles, or two outlines of straight lines whose corners pair up clearly, in parallel planes, free ends | a sketch per outline, Loft with `loft_ruled` | the outlines' sizes |

Left out, with the reason in the result window and the report: every other step type (shell, draft,
scale (Orca has no step that scales a body)...), the pastes in "Patterns, mirrors, Combine, split, move and revolve", the Press Pulls in "Press Pull of a round
face" (flat faces, several faces, round faces that are not whole), the sweeps and lofts in "Sweeps, lofts and splines", the pipes in "Pipes", every coil (see "Coils"), the cases in "Patterns, mirrors, Combine, split, move and revolve" (path patterns, and Combines that take copies of
a pattern of bodies in a way that is not copied, among them), fillets and chamfers on hand-picked edges that do not all run along straight extrudes, the thin extrudes in "Thin extrudes", the tapers and faces in "Extents", join and new body extrudes through all (Fusion
ends them where the part ends, which no Orca length follows), the sketch text and embosses in "Sketch text and
embosses", outlines of another component's sketch that cannot be placed (the capture lacks the frame of the outline, the frame of its sketch or the place of its component in the assembly, so the outline stays marked foreign), elliptical arcs, splines Fusion does not give exactly, cuts that split
the part, tapered tapped holes, tapped holes with a countersink and a modeled thread, left hand threads,
threads whose ends the copy cannot judge, holes up to a tilted or curved face, one of another component or one whose end is not flat or not on the face, a split whose other piece a later step changes together
with the part (cause `pieceUsedLater`), a step that lists another body with the part's name (cause `bodyLost`: the
part may have a new token, so the copy cannot tell whether the step changes it). A left out step changes the shape Orca builds; later steps are still
copied. A cut or intersect while no body is in the copy yet is left out too. A step that is left out keeps nothing
that its handler wrote before it found the reason: the walk (`translate._walk`) takes a `Context.checkpoint` before
each handler and goes back to it (`Context.rollback`) on a Skip, so its features, notes, bound fields, followed
variables and reasons for parameters go away. Only the reason for the left out step stays.

The result lists each copied step with the number of Orca features it wrote. A round or chamfer drawn into the
outline of an extrude writes no feature of its own: it changes the sketch feature of that extrude, and its line in
the result names that feature and the step that wrote it ("Copied by changing Extrude1 sketch (from Extrude1).").

A handler that stops on an error the copy did not expect leaves only its step out (cause `internalError`, the
error in `orca.left_out[].error`), goes back to the state before the step as for any step left out, and the copy
goes on with the next step.

Each step left out has a record in the report (`orca.left_out[]`) with the shape that the recipe gaps share
(`results/left_out.left_out`): `name` (the type in words when the item has no name), `type`, `reason`, and the Orca
keys `index` and `cause` (and `error` for a step that failed). The cause is a cause of `capture_model/gap_hints.py`
when the recipe translator gives the same one, else one of `orca_translate/causes.py` for a rule of the Orca copy
only (a cut that misses the part, copies Orca cannot repeat, a revolve axis off the sketch plane...). The Orca output
writes no gap file. A record has a `hint` (the tip of `gap_hints.py`, shown as "Tip: ...") only when the cause is one
whose tip fits Orca too (`orca_translate/causes.tip`). The tips about the Paramability app (a coil that an AI
assistant adds, the size limits of a thread, exporting parts together) and the causes of the Orca copy only have no
tip. The result window lists up to five steps in full lines ("name: reason Tip: hint") and points to the report for
the rest.

A pipe with a round section is copied as a sweep of its circle (see "Pipes"). A pipe with a square or triangle
section is left out (cause `pipe`), with the tip to draw the section on a sketch and sweep it. Every coil is left out
(cause `coilShape`, no tip, see "Coils"). A Box, Cylinder, Sphere or Torus step is left out as in the recipe
(cause `primitive`), with the tip to draw the shape in a sketch and extrude or revolve it, since the Fusion API gives
no place, direction or operation of these steps (`docs/feature-support.md`).

When a shared reader finds a problem in the design (`design_model.problem.Problem`), the Orca copy shows the sentence of
the problem as it is (`Skip.of`). An extrude that starts from or reaches to a face or plane of another component that
cannot be placed gives the sentence of the resolved step (`ResolvedStep.why_foreign`, through `extents.reader_skip`):
a curved face, or a face or plane whose place could not be read. The sentence comes from `design_model/words.py` and names no output, so the recipe
and the Orca copy give the same words for the same fact: "This extrude starts in a way that is not copied." A refusal
that comes from a limit of Orca only is worded in `orca_translate` ("... which is not copied to Orca yet."). A
sentence of `orca_translate` that names no output ("This extrude makes a new component, which is not copied.") does not
say "yet", as in the shared layer.

Orca stops the whole rebuild on a cut or hole that removes nothing, so the copy checks each cut, intersect and hole
against the part it has built so far (`orca_translate/solid.py`: every copied extrude and hole as an outline swept
along its normal, tested along lines through the tool's outline). A cut or intersect that meets no material is left
out ("does not meet the part as the Orca copy builds it", often after a left out step); of a step with several
outlines or hole points, only those that miss are left out, with a note. The shape also holds revolves (an outline
turned about its axis, sampled along each line), tapered extrudes (the outline moved in or out with the height, read
along each line in steps no longer than the distance to the nearest wall, so a thin slot or a thin wall is not
stepped over; only a part of a line shorter than 1/4096 of its reach through the shape, next to a wall, can be
missed), the copies of patterns and mirrors (the tool body moved), tool bodies joined, cut or intersected, a
plane cut (half of space), a Move (the body moved), sweeps (the outline carried along each line, turned about the
centre of each arc and carried along short chords of each spline of the path) and lofts (the section at each height, `lofts.Lofted`), so a cut after any of them
is checked against what Orca builds. A loft is read along each line in steps no longer than the distance to its
nearest wall, as a tapered extrude is. That distance is the distance to the section at that height: for two circles,
the distance to the centre less the radius; for two outlines of straight lines, the distance to the edges of the
section. Its rate of change along the line has a limit: the move across the section plane, plus the move along the
normal times how far the walls move from one end to the other (the move of the centre and the change of the radius,
or the largest move of a corner) over the height. So a thin part of a loft is not stepped over, and a later cut is
not judged to meet material where Orca removes nothing.

### Extents: To, From and taper

`orca_translate/extents.py`, called by the extrude handler (`steps.extrude`), checked against Orca 2.5.1
(`CadDocument::apply_feature` Extrude, `SketchEngine::make_extrude_taper`) and live.

- The shared reader (`design_model/steps/extrude.py`) reads where the extrude starts, and for each side how it ends,
  its direction and its length; the recipe translator reads the same sides. The Orca copy keeps to what Orca can
  build (see below). A problem of the reader (a tilted or curved face, a value that cannot be read, two sides that
  end on one side of the sketch) gets the Orca wording in `extents.skip_of`. The direction of a side is the reader's:
  the measured end face wins over the stored direction; a side to a face or plane goes toward it; for two sides, a
  face or plane of either side sets the direction, else the measured end face turns the stored one only when it fits
  the turned sides and not the stored ones. A one way cut or intersect through all whose end Fusion did not measure
  then goes toward material (`steps.toward_material`).
- Orca's "up to face" end names a face by Orca's own numbering of the body it rebuilt, which the copy cannot know. So
  a side "To" a face or plane is a distance: the measured distance from where the extrude starts to the plane, plus
  Fusion's offset from it (that offset may follow a size). The face or plane must be flat and square to the extrude;
  a tilted or curved one, a curved one of another component or one whose place is not known, and a two sided extrude whose sides both end on one side of the
  sketch are left out.
- The measured end face (`steps._end_gap`, from `design_model.steps.extrude_checks.end_check`) must lie at the end of the
  side whose way it lies on, for every kind of side: one side, symmetric (at half the length either way) and two
  sides. Else the step is left out. For a two sided extrude the face is checked against the side on its own side of
  the sketch, never against the other side. A cut may end before that distance only where it leaves the part: a cut
  that goes out of the part makes no end face of its own, and Fusion then measures a wall that the cut went through.
  The copy accepts this nearer face only when no material can lie inside the cut's outlines between the measured
  face and the end of the side that the face lies on. No material lies there when that side ends past the whole
  Fusion part (`target_box_before`, `design_model.steps.extrude_checks.passes_box`), or when the part that the copy built
  has no material there (rounds and chamfers count as material) and no earlier step of the body was left out. The
  other side of a two sided cut does not make the face acceptable. A cut that ends inside material must end at the
  measured face. A face behind the start, or past the end, is not accepted. A measured face that is not an end cap
  (`design_model.steps.extrude.end_is_cap`: its normal, or else its area) is no measure at all: the stored direction
  and lengths stand, as for the recipe.
- An extrude of spline outlines must make the volume of its outlines times its length
  (`design_model.steps.extrude_checks.volume_problem`, as for a recipe).
- The distance follows the sizes that move the plane, where the copy can tell how: an origin plane stays; an offset
  plane moves with its own distance when one size sets it (`design_model.reach.offset_param`, its sign from the
  measured place) and with what it is built on; a face follows the end of a copied extrude it lies on
  (`solid.Prism.ends`: the end's length `Quantity`), when no later shape of that body touches the measured point. The
  length is then the measured length plus the plane's move, so the end stays where Fusion puts it. A plane or face
  that sizes may move in any other way keeps its length, and every size that may move it is marked
  (`design_model.reach.reach_sizes`: the sizes read before the step, and those behind the planes of the chain).
- "From" a face or plane: the sketch plane is moved to that plane. Orca cannot move a sketch plane with a variable, so
  the shift is a number and the sizes that move the face are marked. A start at a distance from the face (a
  `start.offset` that is not zero) moves the sketch plane by that distance as well, as a number: no Orca field carries
  it, and the sizes that set the offset are marked (the Orca datum plane feature is not used). Which way Fusion
  measures the offset is not read, so the way is the one that puts the start on the face Fusion measured
  (`start_offset`), or else the one that puts the end on the measured end cap, as for a recipe
  (`dm.start_of(..., offsets=True)`); where it is not sure, the step is left out (cause `extrudeStartOffset`). The sizes
  that move the start (its face and its offset) also go to the end faces of this extrude (`extents.Shift.reads`,
  `solid.Prism.plane_sizes`), so a later face that follows an end of it is marked with them.
- A hole "To" a face or plane (`hole_reach.py`): a Hole of the measured depth, from each position to its flat end.
  The checks are shared with the Paramability copy (`design_model/steps/hole.py`, `to_face_depth`): the face or plane
  must be flat and square to the hole, and each measured end must lie on its plane, else the hole is left out (Fusion
  ended it on another face, for example a face next to the picked one). A face of another component, a body or a
  point as the end, a tilted or curved face, a drill point at the end and an end that was not measured are left out;
  a tilted or curved face and one of another component give the causes of an extrude up to a face, the others
  `refused`. The depth follows the plane as the length of an extrude does (`extents.plane_move`: an offset plane
  with its own distance and its base, an end face of a copied extrude): Orca keeps the plane the hole sits on as a
  number, so the depth is the measured one plus how far the face moves along the drilling direction (an offset plane
  `lift` above the origin and a hole drilled down gives `depth - (lift - number)`). A face that sizes may move in any
  other way keeps the measured depth and its sizes are marked. Fusion may also end the hole on the faces next to the
  face (Chain Faces). The capture gives this as `chained`, which is null for a hole up to a face made with
  `setOneSideToExtent` (the meaning of `matchShape` is not checked yet), so for a face with `chained` true or null the
  sizes that may move the face are marked (`hole_facts.end_face_sizes`, the same in both exports). The variables
  behind the depth are walked down to where the depth reaches zero (`hole_reach.guard`: "keep lift_mm under 20 mm").
  A tapped hole goes up to a plane with the thread length from that depth. Orca limits of the hole stay: a flat end,
  the counterbore and the countersink as for a depth.
- The depth of a hole with a counterbore or countersink, "To" a face or of a given depth, must stay deeper than the
  counterbore or the countersink cone (`hole_reach.guard`). Past that Orca drills only the recess, without an error.
  The limit goes on the parameter's line ("keep lift_mm under 14.9 mm (above that, the hole gets no deeper than its
  counterbore or countersink)"). Where the limit cannot be told, the depth and the recess keep their numbers and the
  sizes are marked.
- A flat face of the body as the outline: its loops and plane as they are now, as sketch entities. Every size read
  before the step is marked, since the face may move or change with it.
- The plane a sketch sits on: Orca cannot move it with a variable, so the sizes that may move it
  (`design_model.reach.placement_sizes`: those behind its construction plane, and for a plane on the part every size
  read before the sketch) are marked for every extrude, and for the outlines of revolves, sweeps and lofts
  (`design_model.reach.sketch_plane_sizes`). Fusion 2706 gives no `Sketch.referencePlane` for some sketches on a face
  (a boss sketched on the top of a plate), so a sketch without a reference counts as one on a face of the part,
  unless its frame lies on an origin plane. The recipe output uses the same rule.
- Taper. Orca tapers a Blind extrude only (and its "up to face"); symmetric and two sided extrudes ignore
  `taper_deg`. It moves the outline in its plane by the signed length times the tangent of `taper_deg` (a positive
  angle grows the outline along the extrude; with Flip the same angle shrinks it) and lofts the two outlines. A
  tapered symmetric or two sided extrude is therefore two Blind extrudes of the same sketch, one flipped, each with
  its side's angle; Fusion's positive taper grows the outline going away from the sketch, so `taper_deg` is Fusion's
  angle, negated on a flipped side. The taper's sign is checked against the measured walls as for a recipe
  (`design_model.steps.extrude_checks.taper_problem`). A side that ends on a face keeps its taper in its parameter only;
  without one, its measured walls (or, without walls, its end face area) must show no taper.
- Orca's outline move rounds every corner it pushes outward, and its loft between two arcs that meet at a sharp
  corner twists the wall (the corner slides along the arcs). So a taper is copied only for a full circle, or an
  outline of lines and arcs whose sharp corners are all between two lines and point away from the move: convex
  corners when the outline shrinks, inward corners when it grows (a growing polygon is always left out). Arcs must
  meet their neighbours smoothly (a slot, a rounded rectangle). Every line and arc must keep at least 0.05 mm at the
  far end. Holes in the outline (Orca stops on them), a taper of 80 degrees or more, a taper on a through all
  extrude and a tapered intersect to both sides are left out. Causes: `taperShape`, `taperExtent`.
- A taper angle follows its size only for an outline without sharp corners: at the other sign Orca would round them.
  Otherwise it keeps its number and the size is marked.
- Limits (`extents.guard`, `limits.guard`): Orca variables have no ranges, and past some values Orca builds these
  extrudes wrong without an error. A "To" length below zero extrudes the other way, and a taper that shrinks a side
  of its outline to nothing builds a straight extrude. So for each variable a bound length, taper or outline size
  reads, the copy walks the variable down and up (the others kept) to where the length stays above zero and
  `taper_gap` still holds, and the parameter's line says how far it may go ("keep lift_mm over 5 mm", "keep
  draft_deg between -44.8 and 79.9"). Every limit found is told, also one far from the current value, since past it
  Orca gives no error (the walk goes up to about 16000 times the value). A lower limit at zero or below is told only
  for a value below zero (a taper angle): a size stays above zero anyway. A field that sizes a shape (a sketch
  `width`, `height` or `radius`, a round or chamfer size, a hole size, a thickness, a thread size: `limits.POSITIVE`)
  never fits at zero or below, whatever the step's own check says, so the walk of a variable that drives one stops
  where that field reaches zero, and that lower limit is told even when it is small ("keep wire between 0.01 and
  18.5 mm" for the diameter of a swept circle, never a limit below zero). When a limit cannot be worked out (the check
  fails at the current values, or the variable has no parameter line), the field keeps its number and its sizes get
  the reason. The told limit is a `limits.Limit`: the words, with the variable and the low and high numbers.
- Why a limit stops. A check that knows why a value does not fit returns `limits.Stop(kind)` (it counts as False)
  instead of False. The walk (`limits.bounds`) keeps the answer of the first value it tested past each limit
  (`limits.Range.why`), and `limits.words` adds the cause in plain words (`limits.CAUSES`, kept in `Limit.why`):
  "keep lift_mm over 5 mm (below that, the end of the extrude passes its start)", "keep wall between 3 and 28 mm
  (outside that, a rounded corner reaches another side of the outline)", "keep ang between 45.1 and 178.7 degrees
  (below 45.1 degrees, two sides of the outline meet or cross; above 178.7 degrees, the outline grows too large for
  the copy)". The causes: a size of the shape reaches zero (`POSITIVE`); for an outline built from cuts
  (`Planned.fits`), two sides meet or cross, the outline grows past the block, a side turns around, a choice of the
  sketch solver flips, or the cuts no longer give the outline; for corner tools (`corner_tools.holds`), a corner
  gets flat or turns the other way, an angled chamfer loses its square corner, a round or chamfer gets too small,
  the rounds and chamfers need more than a whole side, or a corner tool reaches another side; for a sweep, the
  outline grows past the tightest bend or reaches another part of the path; for an extrude, the "To" end passes the
  start or the taper closes the outline; the rounds or chamfers no longer fit on the part; the thread no longer
  fits. A check that cannot be worked out at a value (an error) gives no cause, and the limit is told without one.
  The cause changes only the words: where a limit is found does not change.
- The end faces of a copied extrude (`solid.Prism.ends`, which a later "To" follows) are set once its fields are
  bound and checked: a length that Orca does not hold as a formula (it cannot write it, or the limit check unbinds
  it) is a number there too, so a later "To" on that face keeps its number as the earlier extrude does.
- Live with OrcaSlicer 2.5.1 (raw recipes): a shrinking 40 by 20 rectangle (7485.27 mm3, the exact frustum) and
  triangle, and a circle growing and shrinking, gave the exact volumes, also with Flip; a growing rectangle (8531.4
  against 8535.1) and two arcs of radius 5 meeting at two corners, 3 long at 10 degrees in (53.27 against 53.32),
  did not.

### Rounds, chamfers and threads

`orca_translate/finishes.py`, `finish_body.py`, `outline_rounds.py` and `threads.py`, checked against Orca 2.5.1
(`CadDocument::apply_feature`, `GeometryEngine::collect_edges`) and live.

- Orca names single edges and faces by its own numbering of the body it rebuilt, which the copy cannot know. A round
  or chamfer can also take every edge of a face group: Top takes each edge of a flat face whose outward normal points
  up (its Z above 0.7), Bottom each edge of a flat face that points down, Lateral each edge of any other face (curved
  faces count as Lateral), All every edge. Z is the design's up direction. On a box, side edges and all edges are the
  same edges.
- So a fillet or chamfer is copied only when its picked edges are exactly one group of the part as the copy builds
  it. The copy knows the edges of a simple part only (`finish_body.body_of`): one straight extrude of lines, arcs
  and circles (an outline with a spline is not one), with cuts and holes straight through it along the same direction that touch nothing else. Its edges are the outlines at both
  ends, one edge along the extrude at each outline corner, and the seam of a full circle. The seam, and the edge where
  two side faces meet smoothly (a slot), are not rounded by Orca and not shown by Fusion, so they may be picked or
  not. Each Fusion edge is matched to an edge of the copy by its measured points (`edges[].points`); an edge that
  matches none, or several, leaves the step out. A part that Orca builds from revolves joined together (see
  "Revolve" below) has faces split where they meet, so a round of a face group on it is left out with the cause
  `revolveSeam` before its edges are looked at.
- Orca stops the whole rebuild on a round it cannot make. Rule (`finish_body.room`): every face must stay larger
  than 1.1 times what the rounds take from it: each outline line longer than the size times the corner cut at its
  ends, each convex arc larger than the size, outline curves that do not share a corner more than twice the size
  apart, and the extrude longer than the size times the ends it rounds. A step that breaks the rule is left out.
- Orca variables have no ranges, so the rule holds at the current sizes only. When a variable sets the size of a
  round, `limits.ranges` walks that variable up and down (the others kept) to where the rule stops holding, and the
  parameter's line says how far it may go ("keep edge between 0.01 and 9.09 mm"). Orca stops the rebuild on a round
  of no size, so the lower limit is always told (`limits.words` with `floor`); a higher limit over ten times the
  value is not shown. When the part has corners cut by corner tools whose outline or size follows variables (see
  "Corner tools"), the walk also takes each free size that the outline and its tools read. At each value, the copy
  works out the outline with its rounded corners again (`corner_hosts.rebuilt`) and checks the rule on it
  (`limits.tell_sizes`): a corner arc must stay larger than 1.1 times the round, so the corner size gets a lower
  limit. When the copy cannot work the outline out again (an outline with holes, or formulas that do not give the
  outline the copy holds), or a limit cannot be told, the round is left out (`noRoom`). When a variable sets a size
  of the part (a bound extrude or outline), the result notes how far
  each side and the height may shrink: the rule is a set of lengths each larger than a share of the round size, so
  every length may shrink to the round size over the largest size the rule allows. The margin stays 1.1: live, a 1 mm
  chamfer on a 40 by 20 by 10 plate built up to 9.5 mm (the rule allows 9.09) and failed at 10, and a larger margin
  would leave out rounds Orca makes without making the part's own sizes safe.
- The shape that checks cuts (`solid.Solid`) does not show what a round or chamfer takes. So each copied one adds the
  material near its edges to the shape's `unsure` list (`finish_body.Rounded`): within the size of each rounded end
  plane and outline curve, and within the size over `sin(a / 2)` of each rounded corner (`a` the sharpest corner of
  material). A later cut, hole or thread must meet material away from it (`Solid.firm`); a hole that meets only that
  material is left out with its own reason (cause `nearRound`).
- A round or chamfer changes the edges. A later one is copied only on the other end of the same part (top after
  bottom, or bottom after top), with the two sizes counted together; after a cut, a hole or a thread, none is. A round
  drawn into an outline (below) leaves the copy's shape as Orca builds it, so a round of a face group may follow it.
- One size for each Orca feature. The sets of a step are read by the shared layer (`design_model/steps/finish.py`)
  and put in parts of one size. Sets with the same number are one part, made with the size of the first set (the sizes
  of the others, when they follow other variables, get the reason). A step with one part is one Orca feature. A step
  with sets of different sizes is copied as one feature for each size, one after the other, when each part is a whole
  group of edges of the part and Orca can make the groups one after the other (a top group and a bottom group, with the
  sizes counted together as below). Each feature has its own `dressup_size`. Fusion makes the sizes in one step, and
  Orca one after the other; this gives the same part, because the top and the bottom edges do not meet. A part that is
  not a whole group (hand-picked edges), or a group that cannot follow the first (a side group after a top group), leaves
  the whole step out with the reason of the different sizes. A size that does not leave enough material together with
  the other sizes leaves it out with the cause `noRoom`. A chamfer with two equal distances, or a distance and 45
  degrees, is even; the second value stays as it is (its sizes get the reason). A chamfer with different sides is left
  out. Fusion's setback corners and other chamfer corner types are noted.
- Edges along an extrude (`orca_translate/outline_rounds.py`). A side edge of a straight extrude runs along the
  extrude at a corner of its outline. A round of it is the same part as an arc at that corner of the outline, tangent
  to both lines (`radius / tan(a / 2)` from the corner along each line, `a` the angle between the lines), and an even
  chamfer is a line across the corner (its distance along each line). So a step whose picked edges are all such
  edges is copied by drawing its corners into the extrude's sketch: the sketch feature is written again as lines and
  arcs on the extrude's own plane, and the shape that checks cuts (`solid.Solid`) takes the new outline. This holds
  for every kind of corner: at a corner of material the round takes the material between the lines and the arc; at a
  corner that points into the material (the inward corner of an L, the corners of a window or a pocket cut into the
  part) it fills it. A step with edges along an extrude and other edges goes to the face groups above.
- That is the same part only when the round is the first change at that corner. So a step is copied only when:
  - every picked edge is matched by its measured middle point to a side edge of one copied straight extrude (an
    extrude with no taper, its sketch written by the copy) at a corner of two lines. A corner where an arc meets
    the outline is left out (cause `cornerCurve`);
  - when a size of the sketch follows a variable, or the outline is built from plane cuts, the corners are cut by
    corner tools instead of drawn (see "Corner tools" below), with the same checks;
  - the sketch of the extrude feeds no other Orca feature (a pattern of the extrude writes its copies on the same
    sketch, and they must keep sharp corners: cause `sketchShared`), no step between the extrude and the round is
    left out (see the next point), and no round of a face group or thread changed the part after the extrude;
  - a step left out between the extrude and the round may have changed the edge where the copy cannot see it, so it
    leaves the round out (cause `cornerChanged`). One kind of left out step does not: a round or chamfer that the
    copy measured when it left it out (`outline_rounds.note_left_out`, with `left_corners.py`). It is measured when each of its edges is a
    whole straight side edge of a copied extrude at a corner of two lines that fits it, found by Fusion's measured
    point, with flat faces beside it and flat ends square to it; when its size is known (a round of one radius with
    tangent continuity, a chamfer of one or two distances or of a distance and an angle under 89 degrees); and when
    no step left out before it comes near it by the same rule. Such a step changes the part only within its reach
    (`radius / tan(a / 2)`, or the larger chamfer distance) of each of its edges. It counts only when one of its edges
    lies in the plane of a face next to an edge of the round, or the other way round, or when its edges come closer
    to the edges of the round (taken over the whole length of the extrude) than twice the sum of the two reaches plus
    0.05 mm. Any other step left out (a cut, a hole, a round of a face group, a round the copy could not measure)
    always counts;
  - no other shape of the copy holds the extrude's prism (`outline_rounds._held_elsewhere`, all bodies of the copy).
    A Mirror of the body joined to it, a pattern, or a Combine that took the body as a tool copies the body as it
    was. Orca builds those copies again from the extrude's sketch, so a redrawn outline would round the copies too,
    where Fusion leaves them sharp, without an error. Such a round is left out (cause `bodyCopied`);
  - the corners fit their lines: what the corners take from a line is at most its length. A line taken whole is
    gone, as when the short sides of a rectangle are rounded with half their length (a slot); a line that stays must
    be 0.01 mm or longer. No other side of the outline may reach into a corner (cause `noRoom`). The margin of the
    face group rounds does not apply: Orca rounds nothing here, it draws an outline whose numbers no variable changes;
  - the part the copy built shows one straight edge at the corner whose middle is Fusion's measured point, with
    the two faces beside it flat over the corner, and the faces at its ends flat and square to it. The copy reads
    this along lines parallel to the extrude, just off each face and through the corner;
  - the part with the new outline gives what Fusion's round gives: along lines through each corner, the material of
    the part the copy built, less (or plus) the corner's region between the ends of the edge. Every later copied step
    is in that check, so one that cuts or adds near the corner leaves the round out (cause `cornerChanged`).
- Orca cannot tie sketch entities to variables (`CadDocument` binds feature fields only), so a drawn outline has
  numbers only. A round must never cost a size that follows a variable. So when the sketch of a picked corner has a
  size that follows a variable (a rectangle whose `width` or `height` is bound), or the outline of a picked corner is
  built from plane cuts (see "Outlines built from plane cuts"), its corners are not drawn: corner tools are cut from
  the outline (see "Corner tools"), and the outline keeps its bound sizes. One step may draw some corners and cut
  others. The size of a drawn round stays a number, and its sizes get the reason. The extrude's length still follows.
  A pattern or mirror that repeats the extrude after a drawn round is left out (`repeatsFinish`): its copies would get
  the round, which Fusion does not give them. When the step that made the round is taken back (`Context.rollback`, a
  tool body that cannot be copied), the sketch and the shape are put back (`Context.undo`).
- Orca's own edge numbers were checked as another way to name single edges. Orca numbers edges in the order
  `TopExp::MapShapes` meets them on the body it rebuilt (`GeometryEngine::edge_by_index`). For one extrude that
  starts a body, the order follows OCCT's prism: one side face per curve of the outline in the order of Orca's wire,
  then the bottom and the top, and each edge counted where it is first met. After a Boolean (a cut, a hole) the order
  is the one OCCT's Boolean builder gives, which is not that of the prism (seen live on a plate with a hole) and is
  not a documented order of any OCCT version. A number names a real edge whatever it is, so a wrong one rounds another
  edge without an error, also after a variable change that adds or removes an edge. The copy does not use them.
- Shell: Orca opens a shell only at a face it picks by its own numbering, and its shell without an open face keeps
  the inner block instead of a hollow part (seen live). Draft: Orca picks the face by its own numbering and tilts it
  about the bottom of the part. Both are left out.
- Thread (`thread_major_nominal`): `thread_radius` is half the major diameter, `thread_depth` half the difference of
  the major and minor diameters, the plane's normal the direction the thread runs, `thread_height` its length. The
  numbers come from Fusion's thread info (`design_model/steps/thread.py`, `spec_of`). Orca's limits (radius at least 0.5 mm,
  pitch over 0.1 mm, depth under 0.7 times the pitch and 0.45 times the radius, length over half a pitch, under 400
  turns) are kept with a margin; a thread outside them, a left hand thread, and one that does not meet the copied
  part are left out. A length that follows a variable gets its limits on the parameter's line ("keep len over
  1.89 mm"; a part length thread also no longer than its face).
- Ends: a thread whose groove runs out through a face of the part did not always build in Orca 2.5.1 (about one in
  four removed nothing, or less than it should), and starting or stopping it on or a pitch outside a face failed as
  often (25 of 41 runs, by the start angle and the direction of the thread). Every thread that stays inside built. So the
  Orca thread starts and stops half a pitch inside each end of Fusion's thread, and each end is judged on the copied
  part (`threads._end`), on the ring between the thread's face and its other diameter just past the end:
  - no material at all: open. Fusion's thread runs out there, and a plain half turn would stop a bolt or nut, so a
    lead-in is cut after the thread: in a hole, a Hole 0.1 mm wider than the major diameter; on a rod, a ring cut
    (a sketch of two circles and an Extrude cut) from the minor radius to 0.1 mm past the major one; each half a
    pitch less 0.05 mm deep. Cut after the thread, 204 of 204 live threads built as worked out (M3, M6, M8, M12;
    through and blind holes, free rods, rods on a shoulder, part length threads; six start angles); cut before it,
    one of eight failed.
  - firm material all round (no round may have taken it): closed (the bottom of a blind hole, a shoulder, the rest of
    a rod). No lead-in; the groove, which reaches about 0.42 of a pitch past its helix, stays out of the material
    past the end.
  - anything else (part material, part air, or next to a round): the thread is left out (cause `threadEnd`).
- A tapped hole: Fusion keeps its thread numbers in `HoleFeature.tappedHoleInfo` and in the hidden thread feature
  `HoleFeature.thread`. A cosmetic thread is drilled at its measured drill size; a modeled one at the thread's minor
  diameter, with an inside thread on the hole's plane after each hole and its lead-ins at the hole's plane and, for a
  through hole, at the far face (that Hole's plane faces back into the part; both follow the hole centre). The
  length of the thread of a hole through all runs to where the bore comes out of the part, measured from the side
  cylinders of the hole and never from Fusion's end faces (`hole.through_ends`; Fusion lists the faces of a modeled
  thread among them). Under a counterbore the thread starts at the counterbore floor, where Fusion starts it (measured
  live: `made_span` starts at the counterbore depth); its ends are judged with the counterbore cut, so the start gets
  a lead-in. The thread plane keeps its number, so a size that changes the counterbore depth is followed in part. A
  counterbore hole whose thread faces were not measured, and a tapped hole with a countersink and a modeled thread,
  are left out (cause `tappedRecess`): just below the mouth of a countersink the cone is only a little wider than the
  bore, so the copy cannot judge the start of the thread. The faces of a modeled thread must start at the hole's
  mouth and, for a thread over part of the hole, end at its length (`made_span`, `design_model/steps/thread.py`
  `hole_depth`); a modeled thread that Fusion did not build (the bore is not at the minor diameter) is left out too.
- The records of what changed a body's edges (rounds, chamfers, threads) live on the body (`context.Body.finishes`).

### Patterns, mirrors, Combine, split, move and revolve

`orca_translate/repeat.py`, `combine.py`, `body_pattern.py`, `tools.py`, `bodies.py` and `revolve.py`, checked against Orca 2.5.1
(`CadDocument::route_feature`, `apply_feature` Pattern and Revolve, `apply_boolean`, `apply_cut`, `apply_mirror`,
`apply_transform`) and live.

- Orca's body steps work on whole bodies, named by their place in Orca's list of bodies at that point of the recipe
  (`target_body`, `bool_tool_body`; -1 is the last one). An Extrude or Revolve with mode New adds a body at the end; a
  Boolean takes its tool body out of the list. The copy keeps that list as it writes (`context.Body`,
  `Context.bodies`): a feature on a body that is not the last one names it, and every tool body is used up by its
  Boolean right away, so the part is body 0 and the last one again after each step. Orca reads the indexes as written
  (`body_ref_ids` is worked out by Orca on the first rebuild, not stored).
- Tool bodies (`tools.build`): a Combine's tool, or a split's tool body, is written from the steps that made it before
  that step (`design_model.tool_chains.read`: the steps of the tool's component whose `bodies_after` list it), each by
  its own handler with the tool as the body it works on, the first one starting a new body. A tool that a step of
  another component changes (`Chain.unseen`, cause `changedFromOtherComponent`), or that lists the tool's name under
  another token (cause `bodyLost`), is left out, as is a tool that is a piece of a split (`Chain.links`, cause
  `unsupported`). Each of these steps reads what the reader measured on the tool itself
  (`body_states`, through `design_model.roles.seen_on`), not the box and volume of the exported part: a Combine
  intersect inside a tool takes its rule (`every` or `any`) from the tool's own volume, and is left out when the tool
  was not measured. A Combine inside a tool builds its own tools the same way, up to 3 levels. A step of
  the tool that cannot be copied leaves the whole step out, naming the tool and that step, and nothing of it is
  written. The reason reads "The tool body X cannot be copied because of its step Y. <reason of the
  step>", the same two sentences as in the recipe (`design_model.words.ToolStop`). When Y is a Combine whose own tool
  cannot be built, the reason names the step that really stops it once, and its tool body: "... because of the step Z
  in the tool body W. <reason of Z>". While a tool body is built, the reasons of its steps name the tool and not the part
  (`Context.body_words`: "the part", or "the tool body X"), for example the rounds and chamfers (`finishes`) and a
  cut that meets nothing (`steps.misses_reason`). A pattern whose tool cannot be built gives "This pattern cannot be
  copied." and then the reason of the tool. Those steps were passed by as building another body; once copied into a tool their verdict says so.
- Orca drops the tool after the Boolean even when Fusion keeps it (`keep_tools`): only the part is copied. A Combine
  that changes another body and keeps the part as a tool is passed by. An intersect with several tools follows the
  capture's `intersect_model`: `every` is one Boolean per tool, `any` joins the tools first, `unknown` is left out.
- Pattern of features (`entity_type: features`): Orca's Pattern copies a whole body and joins the copies, so the
  repeated steps are written again as a tool body (`tools.of_steps`: their extrudes and revolves on the same sketches,
  first New then Add, with the same bound fields; a hole as a cylinder of its size and depth, a counterbore as a
  second one), the tool is repeated, and a Boolean adds it to the part or cuts it away as the steps did. Steps that
  add and steps that remove get a tool body each, in timeline order. A Combine among the sources is repeated through
  its tool bodies when every step that built them is a source too. A round or chamfer among the sources, and a
  source left out of the copy, leave the pattern out (the copies would lack the round).
- A repeated hole whose centre follows a variable: the copies are drilled where the hole is now, and Orca cannot
  move them with the variable, so the hole keeps its place too (`tools.hold_place`, after the whole pattern is
  written) and its sizes get the reason. Else a variable change would move the hole and leave a copy at the old
  place. Inside a tool body such a pattern is left out, since a later step of the tool can still undo it.
- Rectangular: the copies are fitted to the grid of the measured elements (`design_model/steps/repeat.py`, `solve_lattice`), each
  direction with more than one copy gets its own Pattern on a plane whose x axis is that direction. A spacing distance
  is `pattern_spacing`; an extent distance becomes `distance / max(count - 1, 1)`. Copies that run against the stored
  direction turn it. A direction to both sides of the original is two runs from the original, one each way, each on
  its own tool body: the side with the extra copy (from the measured copies, else ahead, as Fusion does) counts
  `(n + 1) / 2`, the other `n / 2`; Orca rounds a count half up (`lround`), so these are `n // 2 + 1` and
  `(n - 1) // 2 + 1` for any n. An extent to both sides keeps its count fixed (the spacing then depends on whether the
  count is odd).
- Circular: a circular Pattern on a plane at the axis point whose normal is the axis, turned the way the copies
  turn. With `pattern_inclusive` Orca spreads the copies over the angle with both ends kept, and over a full
  turn evenly, the same as Fusion, so the count and the angle both follow, also across 360. A part turn to both sides
  is two tool bodies with their numbers fixed. Fusion 2706 gives element transforms one step ahead for circular
  patterns (hand check CP1), so a one-sided pattern takes the places of its copies from their ids and the way they
  turn from their faces (`design_model/steps/pattern_places.py`, developer guide 3.21). Ids that repeat or do not
  fill the count, faces that do not sit at the places, or a way of turning that nothing shows leave the pattern out
  (cause `copiesUneven`).
- Rectangular and two-sided circular patterns keep the places of their transforms. Two copies on one place, places
  that do not fill the count, or a copy whose faces are not at its place leave the pattern out (cause
  `copiesUneven`).
- Orca's pattern cannot leave copies out, so a pattern with suppressed copies is left out; so is one whose copies are
  turned, do not sit on an even grid, or whose direction or axis is of another component and could not be brought into
  the part's place.
- Path pattern (`repeat_path.py`): the shared reader (`design_model/steps/path_pattern.py`, `layout`) gives the plain
  pattern that a path of one line, one arc or one circle equals (developer guide 3.17). A line becomes a rectangular
  pattern of one direction along the line, and the rectangular handler writes it. An arc or a circle whose copies
  turn with the path (orientation Path Direction) becomes a circular pattern about the axis of the arc, and the
  circular handler writes it. Its `pattern_angle` is the distance times the turn per mm that the measured copies show
  (180 / (pi x radius), within 1 part in 10 000), times the count less one for a spacing. Thus the angle follows the
  distance and the count. A pattern round the whole circle is a full turn: the count follows, and the distance keeps
  its number.
- An arc whose copies keep their direction (orientation Identical) becomes Orca's pattern along a curve
  (`pattern_curve_sketch`, `pattern_curve_entity`). Orca moves copy i, without a turn, by the point of the sketch arc
  at i / (count - 1) of its sweep less the start of the arc (`CadDocument::apply_feature`, Pattern,
  `sample_entity_2d`, Arc). Fusion moves each copy by the point of the path at the distance of that copy, less the
  start of the path. The two agree when the arc starts at the start of the path and ends at the last copy, so the copy
  draws that arc. Each measured copy must sit at its place on the arc without a turn; else the step is left out
  (`copiesUneven`, `copiesTurned`). Orca cannot tie a sketch arc to a variable, so the distance keeps its number, and
  the count follows only for a distance over the whole extent. A circle has no start, and Orca's `sample_entity_2d`
  has no case for a circle, so copies that keep their direction round a circle are left out.
- The copies must land where Fusion's measured copies are: the rectangular and circular checks above, and the faces
  of each copy. Left out with the cause `pathPattern` (the tip "Use a rectangular or circular pattern, or a mirror."):
  a path of another curve or of more than one curve, copies to both sides of the start point, a round path with a
  start point other than 0 or with the flip (Fusion 2706 puts those copies off the arc, hand check PP1), copies that
  run against the path, copies past the end of the path at the current sizes, and copies that keep their direction
  round a whole circle. Suppressed copies leave the step out with `copiesSuppressed`, and copies that do not turn by
  the distance with `copiesUneven`.
- The path keeps its numbers in Orca. The sizes that may move or turn it are marked: for a line only the sizes that
  turn it or change its length (`edges.line_sizes`), for an arc or a circle every size of its sketch and of the plane
  under it, for an edge of the part the sizes before the step. The parameter's line of a variable that sets the count
  or the distance tells how far it may go before the last copy passes the end of the path (`limits.guard`, cause
  `pathEnds`), as the Paramability export cuts the range there. Past that limit Orca builds the copies off the path
  without an error. A variable whose limit cannot be told keeps its number.
- Mirror of features: the tool body and an Orca Mirror of it (Add), then the Boolean. Mirror of the body joined to it
  (`combine` true): an Orca Mirror of the part. A pattern or mirror of bodies that leaves its copies apart does not
  change the part and is passed by; a part that is such a copy is left out.
- Pattern or mirror of bodies whose copies a Combine takes (`body_pattern.py`). Orca's Pattern keeps the body it
  works on and fuses each copy into it (`CadDocument::apply_feature`, Pattern: copies 1 to count - 1 of the seed,
  `BRepAlgoAPI_Fuse`). Its Mirror with mode Add fuses the body with its image (`apply_mirror`;
  `mirror_keep_original` counts only for mode New). The shared layer tells which patterns the Combine takes whole
  (`design_model/steps/body_pattern.py`, `groups`): the copies pair up with the bodies the pattern made by their
  points, the Combine takes every copy and every source, and no step changed a copy or a source between the pattern
  and the Combine. The copy then builds the sources as one tool body (`tools.build` with the pattern as the anchor,
  so each source is built as it is just before the pattern; several sources are joined first). It repeats that tool
  with the layout of a pattern of features (`repeat.rectangular_layout`, `repeat.circular_layout`, or a Mirror), and
  adds it to the part or cuts it away with one Boolean with the Combine's operation. The other tools of the Combine
  follow, each built from its own steps. A direction to both sides is a tool body each way, as for features.
- The Combine holds a fixed list of bodies, and it is not known whether Fusion adds new copies to it when a count
  changes (hand test B6). So the count keeps its number, and its sizes get the reason "... makes more or fewer copies
  with it, and Fusion may not change what its Combine takes". The spacing and the angle follow variables, and an
  extent becomes a spacing of the distance over the count less one.
- Copies of the part joined to it (the Combine's target is the source of the pattern): an Orca Pattern or Mirror of
  the part itself, with no Boolean. This needs one layout (not to both sides), a join, the part as the only source,
  and no step that changed the part between the pattern and the Combine (`body_pattern.stays_as_copied`).
- The copies Orca makes from the numbers written must land on the bodies Fusion made: each move of the written
  layout must put every point of each source on the points of one copy, one move per copy (`_lands`, cause
  `copiesUneven`). The layout checks of a pattern of features apply too (an even grid, the places of circular copies
  from their ids, suppressed copies). A cut whose repeated tool meets nothing of the part as the copy builds it is
  left out (cause `missesPart`). A join of copies that only touch the part is copied, as Fusion joins them.
- Left out: a Combine that takes only some of the copies, or the copies without their source (cause `copiesTaken`);
  a step that changes a copy or a source on its own before the Combine (cause `copyChanged`); copies made in another
  component (cause `otherComponent`); an intersect with the copies (cause `copiesIntersect`); copies that do not pair
  up with the bodies (cause `copiesUneven`); the part cut by its own copies, copies of the part with other sources or
  to both sides, and copies of copies (cause `unsupported`). The reasons come from the shared layer where it gives
  them (`design_model.words`, `BODY_COPIES_*`).
- Copy and paste of a body (`paste.py`). Fusion keeps a pasted body tied to its source up to the paste. The copy
  builds the source as it stood just before the paste (`tools.build` with the paste as the anchor), each step by its
  own handler with the same bound fields, so a variable that changes the source before the paste changes the pasted
  body too. Steps of the source after the paste do not reach it. That body is then the body the walk builds: the part
  when the exported body is pasted, or a tool body when a Combine takes the pasted body, as for any tool. Later steps
  of the pasted body are copied by their own handlers on it: a Move as a Transform, a Combine as a Boolean. The shared
  layer tells which source a pasted body copies and where it sits (`design_model/steps/paste.py`: the only source,
  else the one at its place, else the one of its shape). Left out: a paste whose bodies cannot be read or paired with
  their sources (cause `refused`), a source of another component (cause `madeInOtherComponent`), a pasted body that
  does not sit where its source sat (cause `pastePlace`: Fusion pastes in place), and a source with a step that the
  copy cannot build before the paste (cause `afterGap`, the reason names that step). A Combine that takes such a
  pasted body is left out with the same reason. When the part is pasted and joined to its copy, the part's steps are
  written twice; the later steps of the part keep working on the part's own features (`paste._keep_earlier`).
- Split Body: the part's piece (followed through the split by `lineage`, so a piece with a new name is built by the
  steps of the body it came from, and those steps read the measures of that body, `design_model.roles`) must lie on one side of the plane and every other piece of that body on the other.
  Orca's Cut keeps the side its plane normal points to (`cut_keep_upper`) or the other one. A split by a solid body
  writes that body as a tool and keeps what lies inside it (Intersect) or outside it (Cut), from the pieces' `inside`
  answers (`design_model/steps/split.py`, `resolve`). A split is left out (cause `pieceUsedLater`) when a later step changes another of
  its pieces together with the part (`roles.other_pieces`, `roles.used_later`, the same facts that stop the recipe
  walk): the copy keeps only the part's piece, so the material that step brings back would be missing. A later
  Combine that takes such a piece as a tool does not count; its own handler builds that tool. Inside a tool body only
  the steps before the item that takes the tool count. Later steps that meet the part where the split would have cut
  are judged against the part as the copy builds it (cause `afterGap` when they miss it after a left out step).
- Move: the rigid move is fitted from the body's first vertices before and after (`design_model/steps/move.py`, `fit`). A
  body with no vertices (a sphere, a torus) moved along X, Y and Z moves by the shift of its box (`box_shift`); any
  other Move of such a body is left out. A Move that
  turns about an axis and agrees with the points becomes a Transform about that axis with `xf_angle_deg` bound to its
  angle (Orca turns by a positive angle, so a negative one turns about the reversed axis and its formula is
  negated); any other move a Transform by the fitted turn (about the component origin) and shift. Orca cannot tie a move
  distance to a variable, so those sizes keep their numbers with the reason.
- Revolve: Orca turns one closed loop per sketch (`build_sketch_wire` takes a single wire) about a line of that
  sketch (`revolve_axis_entity`) or the sketch plane's x or y axis. The copy writes each loop of an outline as a
  sketch of its lines and arcs with a construction line on the axis, so the axis may sit anywhere in the plane
  (`revolve.py` checks, `revolve_parts.py` writes). The turning sense comes from the measured caps
  (`design_model/steps/revolve.py`): the start cap's outward normal points against the turn for new material and
  along it for a cut, the end cap's the other way; when a join merged the start cap into a face of the part and the
  end cap does not tell (a quarter turn ends with the same normal either way), the box of the faces the revolve made
  must fit the box the outline sweeps one way only. For a join, the made faces (which can include faces of the part
  the revolve merged with) and the body after the step must fit the box of the body before it together with the
  swept box, one way only (`body_boxes`). A full turn needs none.
- Holes and several outlines: each hole of an outline is turned the same way as its outer loop and cut away (Revolve
  with mode Cut). On the first body this happens on the body itself. On a part that already holds material, the
  outline is a tool body (outer loop New, then the hole cuts) that a Boolean adds to the part, cuts from it or
  intersects with it, so a hole cuts nothing else of the part. Several outlines are turned one by one, each with its
  own sketches. An intersect of several outlines first joins them in a tool body, then one Boolean Intersect keeps
  what the part and the tool share. Of several cut outlines, those that do not meet the copied part are left out with
  a note. Orca writes the cuts of one step one after the other and stops on one that removes nothing, so each cut
  (each half of a symmetric cut too) must meet the part as the cuts before it left it (`revolve_checks.cut_order`).
  Outlines on the two sides of the axis turned a full circle make the same ring: an outline whose whole turn lies
  inside what the outlines before it cut is left out of the step with a note, when the angle is a number (at another
  angle its turn could reach elsewhere). Any other cut that would remove nothing after the ones before it leaves the
  step out (cause `revolveOverlap`). A join, new body or intersect of outlines whose turns share material is left out
  too (`revolveOverlap`): the copy cannot tell that Orca joins such turns as Fusion does. Also left out: a new body
  made of separate outlines (Fusion lists more than one new body, `roles.new_bodies`, as for extrudes), a cut that
  splits the part, and outlines that a turn of less than a full circle moves different ways at the sketch (on two
  sides of the axis, or on two planes through it; cause `revolveOutlineSides`): the one measured start face cannot
  tell how each one turned.
- Symmetric: Fusion's angle of a symmetric revolve is the turn to each side. When that angle follows sizes, the copy
  writes two revolves from the sketch plane: one by the right hand rule, one with `flip` (Orca turns by the negative
  angle, `CadDocument::apply_feature`, Revolve). Each has `revolve_angle = min(angle, 180)`, bound to the variable, so
  the ring closes at 180 degrees or more to each side, as in Fusion. A cut is written so only when each half meets
  the copied part after the cuts before it (Orca stops on a cut that removes nothing), and when the copy can tell how
  far the angle may shrink before a half misses (below). Otherwise, and for an intersect (two intersects would
  keep only what both halves share), the copy turns the sketch plane the angle back and turns twice the angle, so the
  angle keeps its number and its sizes are marked; 180 degrees or more to each side is then a full turn. Either way
  the measured caps must sit where the turn puts them.
- The angle's limits: Orca's revolve fails at an angle of 0 or below, and a cut or intersect that a smaller angle
  moves off the part stops the rebuild too. So the parameter's line of a variable that turns a revolve says how far it
  may go (`revolve_checks.tell_angle`, `limits.tell`): above 0 and at most a full circle for any revolve, and for a
  cut or intersect above the smallest angle at which every cut still removes material, one after the other, and an
  intersect still meets the part (`angle_floor`: ten halvings down from the current angle, then eight angles tested
  above it). When an angle tested above that floor fails, the halves are not used, and an angle of one turn keeps its
  number with the reason.
- A seam: Orca does not merge the faces of revolves that it joins (the two halves, or outlines turned one by one), so
  the faces stay split where they meet and Orca's groups of edges hold edges that Fusion does not have. The copy's
  shape marks such a revolve (`solid.Turned.seam`), and a later round or chamfer of a face group on that body is left
  out (cause `revolveSeam`). A round drawn into an extrude's outline (`outline_rounds`) does not use face groups and
  is not changed by this.
- Two sides: a turn to two sides with two angles turns the sketch plane back by the angle of one side and turns by
  the sum: the start face tells which side (`back_sides`), and both angles keep their numbers. When the start face
  fits both sides (one angle of 90 or 270 degrees), it is left out with the cause `revolveSides`.
- Also left out: an axis off the sketch plane, an outline across the axis. A cut is checked against the copied part
  like any cut. The outline and the axis keep their drawn numbers in Orca (the sizes that move them are marked), so
  the outline cannot pass to the other side of the axis in the copy; the recipe output cuts the ranges for that
  instead (developer guide 3.14, "The side of the axis").

### Sweeps, lofts and splines

`orca_translate/sweeps.py`, `sweep_splines.py`, `lofts.py` and `splines.py`, checked against Orca 2.5.1 (`CadDocument::apply_feature`
Sweep and Loft, `SketchEngine::make_sweep`, `make_loft`, `entities_to_wires`) and live.

- Orca's Sweep makes a face of the outline sketch and runs it along the wire of a path sketch (OCCT
  `BRepOffsetAPI_MakePipe`): the outline stays where it is drawn and turns with the path from the wire's first point.
  It has no twist, no taper, no guide rail and no way to keep the outline in one direction, and the outline must be
  one loop. Orca starts the wire of an open path at the free end of the first entity, and of a closed path at the
  start of the first entity, so the copy writes the path entities in order from the outline.
- The path is planned as for a recipe (`design_model.paths.planner.plan`, with the recipe's caps of 64 parts and its
  spline fit): ordered from the outline's plane, a closed path cut open there, and its rules checked (no crossing,
  the outline clear of the tightest bend and of the other parts of the path). A new body's measured volume and end
  face must match the outline and path (`design_model.steps.sweep`). A problem the planner finds leaves the sweep out
  with its own words and cause.
- A straight path is an Extrude of the outline (holes included), one arc or a full circle a Revolve about its axis,
  and lines, arcs and splines in one plane that meet smoothly an Orca Sweep. The outline must leave its plane square to the
  path (within a millionth): Orca's extrude runs along the outline's normal.
- A spline of the path is written exactly, never as the recipe's fitted curve: Orca builds the path wire from the
  same entities as an outline, so the spline is its Bezier pieces (see Splines below), turned round when the path
  runs against the way it is drawn. The path sketch's curve gives the definition in its `flat` record (`nurbs`,
  sketch 2D mm); `sweep_splines.with_exact_splines` puts it in the capture's coordinates and gives the spline its
  exact end directions from its first and last poles, before the path is planned. The measured points give those
  directions only to a fraction of a degree, and a spline that leaves a line smoothly would read as a sharp corner.
  The tightest bend is read again along the Bezier pieces (the planner reads it along its fitted curve), and the
  outline must stay clear of it. The shape for later cuts is a chain of prisms along chords of the measured points
  (within 0.002 mm of them), each made longer at its joints to fill the gap a turn opens on the outer side.
- Left out: a twist or a taper (cause `sweepShape`), an outline kept in one direction along a bend (`sweepShape`), a
  path out of one plane (`sweepPath`), a spline Orca cannot draw exactly (`sweepPath`: a body edge or a curve read
  without its definition, one of the splines left out below, or a spline the planner cut open where a closed path
  meets the outline), a closed path that holds a spline (`sweepPath`: live, Orca 2.5.1 crashed in OCCT's
  `BRepFill_Pipe::MakeShape` while it built a closed track of two lines and two splines), a sharp corner (`sharpCorner`: live, Orca built 286 mm3
  where Fusion's mitred wire has 384, and 202 for a closed square path against 439), also a corner inside a spline
  (`sharpCorner`: a joint of its Bezier pieces where the curve turns by more than 0.01 degrees, as at an inner knot
  that a cubic has three times or at a corner of a degree one spline; `splines.joint_turns`; a turn over 2 degrees
  is found first by the shared path planner, `geometry/spline_joints.joint_turns`), holes along a bent path
  (`outlineHoles`), guide rails and surfaces, part of a path, an outline of another component whose place is not
  known, a path in another component and the outlines of
  different planes.
- The path keeps its numbers (Orca cannot tie a path sketch to a variable): the sizes behind the path's sketch and
  its plane, or for a path of body edges every size read before the sweep, are marked. A plain rectangle or circle
  outline follows its sizes, and the parameter's line says how far it may grow before it reaches the centre of the
  tightest bend or another part of the path ("keep bar_w between 0.01 and 19.9 mm" for a bend of radius 10; the
  lower limit is where the outline vanishes, see "Limits").
- Orca's Loft builds one wire per outline sketch and skins them (OCCT `BRepOffsetAPI_ThruSections`, ruled), which is
  what Fusion makes between two outlines with free ends. OCCT joins the points of the two loops its own way. Two
  circles join point to point at the same angle when both sketches have one plane normal, so the copy writes them
  so. Two outlines of straight lines join at the corners closest together about the outlines' centres (live: also
  with the top square turned 20 and 40 degrees). The copy takes them when that pairing is the only close one, and
  either a new body's measured volume shows Fusion paired them the same way (`design_model.steps.loft`), or every
  corner lies within a degree of its partner (a square to a smaller square). Left out: other shapes or pairs (cause `loftShape`), planes that
  are not parallel (`loftShape`), holes (`outlineHoles`), more than two outlines, points, faces or edges as
  sections, end conditions other than free, rails, a centre line and closed lofts (`loftKind`).
- Splines: Orca's B-spline entity is clamped, uniform and of degree three (fewer poles: one less), with no weights.
  The reader keeps a spline's exact definition (`nurbs`: degree, knots, poles, weights; `NurbsCurve3D.getData`).
  A curve of degree three or less without differing weights is, piece by piece, a run of Bezier curves (each inner
  knot inserted up to the degree), and each piece is one Orca entity of 4 poles (3 for degree two), the same curve.
  The pieces must start and end where Fusion's curve does and pass within 0.002 mm of every measured point. Left
  out: a closed (periodic) spline, differing weights, a degree over three, knots not clamped at both ends, a break
  in the curve, and a spline read without its definition (older captures). An inner knot as many times as the degree
  can make a corner in the curve; Orca draws the same corner, so an outline keeps it. The same pieces draw a spline
  of a sweep path, where such a corner leaves the sweep out (see above).
- Live with OrcaSlicer 2.5.1 on 2026-11-16: the fixtures `sweep_pipe`, `sweep_far_end`, `sweep_closed_rim`,
  `sweep_ring`, `sweep_straight`, `sweep_edges`, `loft_two_squares` and `loft_on_plate` built with the capture's box
  and volume (1857.8, 1857.8, 420.5, 2261.9, 2400.0, the box only, 7000.0, 15000.0); the captures of
  `tests/orca_sweeps.py`: a 6 by 4 bar along a line, a quarter bend and a line (1577.0, then 2628.3 with `bar_w` 10
  and 5256.6 with `bar_h` 8, as worked out), a round groove along a bent path in a block (15681.4) with a pin cut
  below it after (15680.6), an oblique cone (3665.2, then 5110.3 with `top_d` 16), squares turned 0.5 degrees
  (6999.9), an arch of a two piece spline with uneven knots (1956.0), and a quarter bend of a round wire joined to a
  block at its start, turning each way (277.4 both, the block showing the turn). Sweeps along a spline: a round
  wire of radius 2 along a line and a two piece spline with uneven knots (660.2 against 660.2471, drawn either way
  round), and a 4 by 1.5 bar along a line and a three piece S spline with a turning point (479.9 against 479.9041,
  the box 1.5 high, so the bar does not flip at the turning point), each with the capture's box. The same wire cut
  out of a block that holds it (27339.8 against 27339.7529) and joined to a block at its start (1660.2 against
  1660.2471), and with its diameter set by `wire` (660.2, then 1485.6 with `wire` 6 against 1485.56); the first
  line's length `run`, a dimension of the path sketch, is marked and keeps its number.

### Pipes

`orca_translate/pipes.py`, checked against the source of Orca 2.5.1 (`CadDocument::apply_feature` Sweep,
`build_sketch_wire`, `SketchEngine::make_sweep` and `entities_to_wires`).

- Fusion builds a pipe as a sweep of a section that it draws itself: a circle at the start of the path, square to the
  path and centred on it, less a circle of the wall for a hollow pipe (`design_model.steps.pipe`, hand check PI1).
  The copy plans and checks the path as for a sweep with that outline (`sweeps.plan_path`). Thus the path rules of
  "Sweeps, lofts and splines" apply: one plane, lines, arcs and splines that meet smoothly, splines that Orca draws
  exactly, no sharp corner, and a new body's measured volume and end face must agree with the section and the path.
- Every path is an Orca Sweep, also a line, one arc and a full circle (a sweep writes those as an Extrude or a
  Revolve). Thus the section is Orca's simple circle, and its `radius` can follow the pipe's size. The copy writes a
  sketch of the circle on the plane square to the path at its start, a sketch of the path from the start in order (a
  full circle as two half arcs from the start), and a Sweep.
- Orca makes a face of the circle and runs it along the path wire (OCCT `BRepOffsetAPI_MakePipe`). The ends of the
  sweep are that face at the start and the face carried to the end. The circle starts square to the path, so both
  ends are square to the path, as Fusion ends a pipe on an open path.
- Orca's sweep takes one closed loop (`build_sketch_wire` refuses two circles in one sketch). Thus a hollow pipe is
  two sweeps: the outer circle, then the circle of the hole cut out of it (mode Cut). When the part already holds
  material, the two sweeps are a tool body and a Boolean with the step's operation, so that the hole cuts nothing
  else of the part.
- What follows variables: the circle's `radius` is half the pipe's size (`0.5 * pipe_d`), and the radius of the hole
  is that less the wall (`0.5 * pipe_d - wall`). The parameter's line tells how far each may go: the hole must stay
  open, and the pipe must stay clear of the centre of the tightest bend and of the other parts of the path ("keep
  pipe_d between 2 and 39.9 mm" for a wall of 1 on a bend of radius 20). The path keeps its numbers. The sizes that
  move the path are marked, and these include the sizes that move its start, where the section sits.
- A pipe that cuts or intersects must meet the part as the copy builds it (cause `missesPart`). The shape for later
  cuts is the tube carried along the path, with the hole of a hollow pipe.
- Left out: a square or triangle section (cause `pipe`: the capture does not say which way the section turns about
  the path), a pipe along part of its path (`pipePartOfPath`), a section that cannot be read, and each path that a
  sweep leaves out, with the words of a sweep said of a pipe. A closed path that starts on a sharp corner has a sharp
  corner (`sharpCorner`).
- The captures of `tests/orca_pipes.py` (see "Live check without Fusion") built in OrcaSlicer 2.5.1 with the volumes
  worked out, also the hollow pipe whose hole ends lie on the ends of the pipe.

### Coils

`orca_translate/coils.py` leaves every coil out (cause `coilShape`). This was decided from the source of Orca 2.5.1
(`make_helix_spine`, `CadDocument::apply_feature` Sweep and Thread, `SketchEngine::make_sweep`):

- Orca's Helix is a path only. Its axis is the normal of its plane through the plane's origin, it starts at the
  origin plus `helix_radius` along the plane's x axis, and it rises `helix_height` along the normal by `helix_pitch`
  per turn. It turns right hand about the normal, or left hand with `helix_left_handed`. A Sweep can name it as its
  path (`sweep_path_ref`).
- A Sweep along it is `BRepOffsetAPI_MakePipe` with the profile as a face. The Sweep has no setting for the frame
  that carries the profile, and that frame turns about the path. Orca's own Thread does not use the Sweep for this
  reason: it builds its groove with `BRepOffsetAPI_MakePipeShell` and the axis as a fixed binormal (`SetMode`), so
  that its profile stays on planes through the axis.
- Fusion's coil has its section on a plane through the axis and keeps it so (`translator/coil/coil_fit.py`): its
  two flat end faces lie on planes through the axis.
- A circle drawn square to the helix at its start stays square to it, so Orca makes a round tube. Its ends are square
  to the helix, so each end leans against Fusion's by the helix angle. The rim of an end lies up to the wire radius
  times the slope (the pitch over the length of one turn) away from Fusion's end: 0.08 mm for a wire of 2 mm on a
  coil of 20 mm with a pitch of 5 mm, which is more than 0.02 mm. The wire is also thicker along the axis than
  Fusion's by the wire radius times (1 / cos(helix angle) - 1), and the volume is larger by the factor
  1 / cos(helix angle): 792.06 mm3 against 789.57 mm3 for that coil of 4 turns.
- A circle drawn on the plane through the axis, as Fusion has it, does not stay on such planes, because the frame of
  the sweep turns about the path. Orca's comment on its Thread says the same of a profile swept with `MakePipe`.

Thus neither shape is Fusion's coil within 0.02 mm, and no coil is copied. The probes of `tests/orca_coils.py` (see
"Live check without Fusion") show what Orca builds. Two ways can copy a coil later: a Sweep in Orca that keeps the
axis as a fixed binormal, as its Thread does, with the circle on the plane through the axis (that is Fusion's coil,
ends included); or a tube along a helix made a little longer, with its ends cut off on planes through the axis
(Fusion's ends, but the wire stays thicker along the axis, so the pitch would need a limit on its line).

### Which parameters follow

- A feature value (an extrude length, a hole size) follows when its model parameter's expression translates to a
  formula of the sizes (`SizeTable.translate`, the same as for a recipe) and Orca can write that formula
  (`formulas.to_orca`: `+ - * /`, brackets, `pi`, `sqrt abs sin cos tan min max`; `pow` of a whole power up to 4 is
  written as a product; choices, comparisons, `round`, `mod` and the rest are not). The reason says in plain words
  what Orca cannot do ("Orca formulas cannot round a number up" for `ceil`, `formulas._CANNOT`).
- The reasons of a parameter are listed once each: a reason that two notes of one outline give alike, or that two
  steps give alike, is shown once (`sketch_sizes._drawn_reason`, `orca_result.parameter_line`).
- A rectangle's `width` and `height` and a circle's `radius` follow when the capture holds the graph of the sketch
  (`capture.sketch_graphs`): `sketch_solve` works out each corner as a formula of the sketch's dimensions, each
  dimension is a formula of the sizes (`design_model.dimension_sizes.dimension_formulas`), and a side is the difference of
  two corners. The side must give the drawn length now and keep its direction at the solver's other settings.
  Without a graph, or without a formula, the outline keeps its numbers.
- The corners of an outline of straight lines follow when the copy builds it from plane cuts (see "Outlines built
  from plane cuts"). That is also how a rectangle that a size moves or turns follows.
- Orca cannot move a sketch plane with a variable, and its rectangle is centred on its plane. So when a size also
  moves an outline that the cuts cannot build, the result says the rectangle grows about its centre in Orca; a
  circle centre that a size moves keeps its place in Orca, except a circle hole of the first body's outline, which
  is drilled as an Orca hole (see "Outlines built from plane cuts").
- Each outline of a step is judged on its own (`sketch_sizes.sketch_doubts`): a size that one outline follows (its cuts, a
  rectangle's width) may also move another outline of the same sketch that is drawn with numbers (a hole of lines,
  another profile). That size is then marked, with the reason of the outline that keeps its numbers. A size of the
  sketch that moves none of the written outlines is marked too: it moves other lines of the sketch, which may change
  the outline in Fusion.
- Geometry projected into a sketch (an edge of the part, a line of another sketch) is a measured input of the
  sketch's formulas (`@p3.x`), and the capture does not tell which sizes move it. The copy writes it as its number
  now. So when a corner or centre of an outline (of an extrude, revolve, sweep or loft), or a hole centre, reads such
  an input, every size read before the sketch is marked: "its outline is placed by geometry projected into Sketch2,
  and Orca keeps that geometry where it is now" (`sketch_sizes.projection_doubts`, `hole_place`,
  `reach.projection_sizes`, `SketchFormulas.follows_projection`, `sketches.reads_input`). The sketch's own dimensions
  come after its projections, so they are never marked for it and still follow. A projection of the origin point, an
  origin axis or an origin plane of the sketch's own component is no input when the export can show that no ticked
  size moves or turns the sketch plane (`reach.plane_fixed`): it is fixed, like the sketch origin. Otherwise it is a
  measured input and marks the sizes as above.
- A hole centre follows when the capture holds the frame of its sketch (`sketch_frame`) and the sketch's graph: the
  hole's plane is the sketch plane, turned so that its normal is the drilling direction, and `hole_x`, `hole_y` are
  the point's sketch coordinates as formulas of the sizes (`orca_translate/hole_place.py`). A size that an earlier
  step does not follow everywhere (a rectangle that grows about its centre in Orca, a left out step) is held at its
  value in that formula, since the hole would else move against the part around it; the result says so. A tapped
  hole's thread sits at the same place. Without the frame, a hole centre keeps its place.
- The plane of the holes keeps its place in Orca, so the sizes that may move it are marked (`design_model.reach.hole_plane_sizes`):
  for a sketch, as for an extrude's sketch, from what it sits on (`reference`, read from Fusion as a
  profile's `reference`); a sketch whose reference was not read (an older capture, or a sketch on a face in Fusion
  2706) counts as one on a face of the part, so every size read before the sketch is marked. For a hole placed on a face without a sketch, every size read
  before the step is marked. The centres' sketch coordinates still follow their sizes.
- Orca writes some places of a step as the numbers the capture measured: the plane of a split, the plane of a
  mirror, the axis of a circular pattern, of a revolve and of a Move that turns, the direction of a rectangular
  pattern taken from an edge, an axis or a sketch line, the cylinder face a ThreadFeature is cut on, and the thread
  length of a tapped hole through all. A size that may move such a
  place is marked with a reason ("Split1 cuts along a plane that may move with it, and the copy cannot follow
  that"), so it never reads as "not used" or as following everywhere (`kept_refs.mark`, `kept_refs.mark_faces`).
  Which sizes may move a place is a fact of the shared layer (`design_model.reach.reference_sizes`): the sizes behind
  a construction plane or axis and behind what it is built on, and, for a face, an edge or construction geometry
  built on the part, every size read before the step. For a line of a sketch (a revolve axis, a pattern axis), the
  sizes of that sketch and those that may move its plane, and every size read before the sketch when the sketch
  holds projections or may hold them (`reach.sketch_line_sizes`). Unknown counts as "may move": a record that does
  not say what it is (an older capture), and construction geometry that does not say what it is built on, may move
  with every size read before the step. Construction geometry built on another component may move with every ticked
  size (`reach.built_on_other`). The axis of a sweep path arc (`fixed`) is no
  place of its own: the path's sizes are marked. For a direction of a rectangular pattern taken from an edge or axis
  of the part, the same (the `own` place of the capture). For a direction taken from a sketch line, the same as for a
  line of a sketch. A direction whose source is unknown (an `unknown` place, or no place and no sketch in an older
  capture) may turn with every size read before the step. A part is plain before a step when every step of its component before it
  is a straight extrude (no taper, each side a distance, its end caps measured), a simple hole through all (round
  faces and edges only), a sketch or construction geometry (`design_model.edges`). Any other step (a revolve, a loft,
  a sweep, a pattern, a round, a move) may make an edge or face where an extrude's would lie. In a plain part, an
  edge or face that lies where a straight extrude made it (a side edge along its axis between its end caps, an edge
  over a fixed line of its outline at an end cap, an end face at an end cap or a side face between them) turns only
  with the sketch planes of the part's extrudes (`edges.direction_sizes`), so a pattern along an edge of a plain box
  marks no box size. For a thread, every size read before the step (`reach.any_face_sizes`). The thread of a tapped
  hole through all runs the part's thickness now ("Hole1: its thread runs through the part as thick as it is now,
  and Orca keeps that length", `threads.mark_through_length`). The thickness at a hole depends on where the hole is,
  so in general every size read before the hole is marked, also the sizes that place the hole
  (`reach.hole_end_sizes`): on a plate with a boss, a size that moves the hole under the boss makes it longer. Only
  when the part is plain, every extrude is one sided, adds material along the hole and spans the same two planes, and
  each hole goes in at one of these planes and out at the other, is the part as thick wherever a hole can go. Then
  only the sizes of the extrudes' lengths and sketch planes are marked, and for several extrudes their start offsets
  too (`edges.through_sizes`). The sizes that place the hole then keep following. The sizes that may move the plane
  of the holes are marked by the hole itself. The mark is made after the centres are placed, so it does not hold the
  hole's own centre. An origin plane or axis gives no size. A place of another component is marked by
  `other_components.mark_refs`. A marked size counts as held for a later hole centre (`Context.held`).
- Each ticked parameter ends as "follows the Orca variable" (everywhere it is used), "follows ... but not everywhere"
  (with the reasons), "stays a fixed number in Orca" (with the reasons) or "not used by the copy". Two kinds of size
  get a reason before any step is copied (`Context._doubt_unfollowed_readers`): a size that a joint reads, and a size
  that sets the height of a sketch text. The copy has no joints and no text, so such a size is never "not used". These
  reasons do not stop a hole centre from following the size, since they say nothing about the part that a step builds
  (`Context.held`). A step that is left out names every size of the sketches it uses, also a size that reaches one of
  these sketches through the geometry of another component (`reach.step_sizes`).
- Variable names are the recipe size names, except a name Orca keeps for itself (`pi`, `sqrt`, `abs`, `sin`, `cos`,
  `tan`, `min`, `max`, `deg`, `rad`), which gets `_v`. Orca names are a letter or `_` followed by letters, digits and
  `_`, as the size names already are. Numbers are written without an exponent (`formulas.orca_number`: digits,
  one point, at most 9 decimals, a minus in front): Orca's reader (`eval_expr` in `CadDocument.cpp`) takes a
  number as a run of digits and points only, so `1e-05` would read as 1 and a name `e`. The same helper writes
  the value of a free variable, every number of a bound formula, and each value the limit search tests, so the
  search walks a shape size down to where it really reaches zero.

### Outlines built from plane cuts

`orca_translate/outline_cuts.py` and `halfplanes.py`, called by the extrude handler (`steps._cut_built`), checked
against Orca 2.5.1 (`CadDocument::apply_feature` Cut and Transform, `apply_boolean`) and live.

- Orca binds variables to feature fields only. The entities of a drawn sketch keep their numbers, and a rebuild never
  solves a sketch again. A plane Cut has a bound field, `cut_offset`, and a Transform has `xf_angle_deg`. So an outline
  of straight lines whose corners are formulas of the sizes follows them when it is built from cuts:
  - each side is the line `n . p = offset`, with `n` the side's normal that points out of the outline (counter
    clockwise) and `offset = n . corner`, a formula of the sizes;
  - a side whose direction does not change is a Cut with a fixed plane through the sketch origin and a bound
    `cut_offset`;
  - a side whose direction is a constant plus a formula (an angle size) is cut between two Transforms of the body
    about the sketch origin: the first turns the body back by the formula, so that the side lies in a fixed
    direction, the Cut follows, and the second turns the body forward again. Sides that turn by the same formula
    share one pair of Transforms;
  - one body cut by planes is always convex. An inward corner needs a tool body. The outline is a formula of the
    half-planes of its sides, each side once: "and" at a convex corner, "or" at an inward one (Dobkin, Guibas,
    Hershberger and Snoeyink, 1988, `halfplanes.formula`; of the corners where the method may split the outline,
    the copy takes those that nest the formula least). An "and" node is a body cut by its sides. Each "or" node
    below it is a tool body: through all, cut to the outside of its sides, with its own tool bodies below it. The
    Boolean cuts the tool away. The copy uses differences only: in a live probe, a union of convex pieces left seams,
    and a top chamfer then stopped the whole rebuild.
- The bodies start as a square block on the sketch plane, at least 1000 mm from its centre to a side and 20 times the
  outline's size. The block is extruded as the Fusion extrude is (one side, symmetric or two sides, the same bound
  lengths). For the first extrude of the part the block is the part. Otherwise the block is a body of its own, and a
  Boolean adds it to the part, cuts it away or keeps what both share, as the extrude does. The block's faces and edges
  are those of the drawn outline, so Orca's rounds of a face group work on it as on a drawn outline (live: the same
  volume for a top round of an L built from cuts and of a drawn L).
- The corners come from the sketch solver (`sketches.SketchFormulas.point`), and the direction of each side from the
  solver's direction of its line (`SketchFormulas.line_angle`, `Solution.directions`). A side whose line has no
  direction formula is fixed when both gaps between its corners are numbers. The Orca copy solves sketches with the
  extended reading (`solve_sketch(extended=True)`), which the recipe output does not use:
  - a driving distance dimension between two lines keeps the two lines parallel (hand test OR18). Until OR18 has
    passed (`sketches.DISTANCE_KEEPS_PARALLEL` is False), the sketch is solved a second time without that rule, and
    every size read by a corner, radius or line direction that only the rule gives is marked: "the copy takes two
    lines that only a distance dimension ties to stay parallel when sizes change, which is not confirmed in Fusion
    yet" (`SketchFormulas.unconfirmed`). The cuts still follow those sizes;
  - an angle dimension and the parallel test of a distance between two lines may be off by what the rounding of the
    drawing allows for the lines' lengths (`checks.turn_slack`: four times the solver's tolerance over the length of
    the shorter line, in radians). A capture rounds each coordinate to a millionth of a mm, so a 120 degree angle
    between lines 3 mm long measures 59.9999986 degrees, which the default reading refuses. The slack is at most
    0.001 radians (`checks.MAX_SLACK`), so a very short line does not widen the test;
  - each line gets its direction as an angle formula (`Solution.directions`);
  - a line whose two ends are not known yet takes its direction from the gap between its ends when that gap is known
    on both axes (`_Solver._gap_of_ends`): the corners of a rectangle share their coordinates, so the gap of each
    diagonal is known from the width and the height. A centre point that lies on both diagonals (two coincident
    constraints, as some centre rectangles are drawn, without a midpoint constraint) then places the rectangle:
    "Extrude1 sketch keeps its numbers: the copy cannot work out its corners from the dimensions and constraints of
    the sketch" no longer comes for such a rectangle.
- When the solver gives no formula for a corner, a radius or a hole centre, the reason on the parameter's line says
  why in plain words, by the solver's code (`sketches.open_reason`): no rule reaches it, the sketch is not fully
  constrained, it rests on a constraint or dimension the copy does not read yet, a dimension does not match the
  drawing, the rules do not agree, or the sketch could not be read.
- The formula check. The corner formulas must give the drawn corners now (within 0.00001 mm), each side must run along
  its direction formula, the half-plane formula must give the outline in every cell of the lines through its sides
  (`halfplanes.check`: a point between each two neighbouring rays at each crossing of the lines), and Orca must be able
  to write every formula (`Context.orca_formula`).
- Limits. Orca builds whatever the cuts give: past some value of a variable the same cuts give another shape, without
  an error. So the copy walks each free size the outline reads, the others kept (`limits.bounds`), and checks at each
  value that the corners make a simple counter clockwise loop with no side shorter than 0.0001 mm, that the loop stays
  inside the block with a margin of 5 percent, that each side runs along its direction formula, that the choices of
  the sketch solver hold (its `assumptions`), and that the half-plane formula still gives the loop in every cell. The
  walk goes out in steps that double, so it can step over a band of values where the check fails; after it, 32
  evenly spaced values on each side, between the current value and the limit found (or ten times the current value
  away when none was found), are checked too, and the limit moves in to the first one that fails. A band narrower
  than these steps can still be missed. The parameter's line tells every limit found, also one far from the current
  value and one below zero (a place that may go below zero), but not a lower limit at zero, where a size ends ("keep
  wall under 29.9 mm" for an L whose leg is 30 mm, "keep ang between 45.1 and 178.7 degrees" for a trapezoid, "keep
  wx between -930 and 950 mm" for a window that may move off its plate). An outline whose check fails at the current
  values keeps its drawn numbers.
- Scope and fallbacks. Only an outline of one outer loop of straight lines without holes, of an extrude without
  taper, whose corners and side directions the solver gives as formulas of the sizes, is built from cuts. The first
  body of the part keeps its holes as cuts through it, so its outer loop may still be built from cuts. A plain
  rectangle that keeps its place and direction stays Orca's simple rectangle, which takes fewer features. An outline
  keeps its drawn numbers, with the reason on the parameters' lines ("Extrude1 sketch keeps its numbers: ..."), when
  nothing of it follows a size, when it has holes or sides that are not straight lines, when the extrude has a
  taper, when its corners do not make a plain closed loop (two corners on one spot, sides that cross), when a corner
  reads geometry projected into the sketch (see "Which parameters follow"), when the formula check fails, when it
  would take more than 60 Orca features or tool bodies nested more than 4 deep, or when the copy cannot tell how far
  a variable may change.
- Holes of the first body (`drilled.py`). When the outer loop is built from cuts, it grows the way Fusion grows it
  (a rectangle drawn from the origin grows to one side), so a circle hole cut as a circle sketch would keep its old
  place. A circle hole whose centre moves is drilled as an Orca Hole instead: on the sketch plane, along the extrude's
  direction (against the sketch normal for an extrude the other way), through all, at `hole_x` and `hole_y` (the
  centre's sketch coordinates as formulas) with `hole_diameter` (twice the radius formula). Orca drills from the
  plane one way only, so this is done only for a one sided extrude without taper, whose body lies on that side. For
  other extents the hole stays a circle cut that keeps its place, and a rectangle that a size moves together with
  such a hole stays a plain rectangle: it grows about its centre, as the hole stays where it is, and both sizes are
  marked.
- A round or chamfer of a side edge of such an outline is cut by corner tools (see "Corner tools"), so the outline
  keeps its cuts. Rounds of a face group are copied as usual.
- A pattern or mirror of the extrude writes the whole block, its cuts and tools again into its tool body
  (`outline_cuts.again`, from `tools.of_steps`), with the same formulas.
- The shape that checks later cuts (`solid.Prism`) is the drawn outline now, with `built` set, so the rounds of side
  edges know the outline is built from cuts.
- Live with OrcaSlicer 2.5.1 on 2026-11-16, the captures of `tests/orca_cuts.py`: an L (4960, then 6160, 4000 and
  6160 as the legs and the wall changed), a U (6640, 9280, 8580, 3540), a trapezoid whose sides turn with its angle
  (6544.12, then 4643.60 at 50 degrees, 8000 at 90 and 5631.38 at 120 degrees and a lower top), an L whose legs meet
  at an angle, its inner sides tied by distance dimensions only (5230.50, 4960, 2757.13), a window whose corner moves,
  cut from a plate (21600 at every place inside the plate, 22500 and 23500 when moved partly off it), and a pattern of
  that window (19200, then 21120 with a narrower window): every volume as worked out from the corners, to 1e-9.

### Corner tools

`orca_translate/corner_tools.py` (the formulas, the checks and the limits) and `corner_hosts.py` (where the features
go, and patterns), called by `outline_rounds.made`, checked against Orca 2.5.1 (`CadDocument::apply_feature` Cut,
Transform, Hole and Boolean) and live.

- A drawn outline has numbers only. So a round or chamfer of side edges on an outline whose sizes follow variables is
  not drawn into the outline. At each corner, a tool body is cut from the body that holds the outline, before that
  body goes into the part. This is done for an outline built from plane cuts, and for an Orca rectangle whose `width`
  or `height` is bound.
- A round of size `r` at a corner where the counter clockwise outline turns by `t` (above zero at a convex corner):
  the arc centre lies at `r` from both sides, and the round reaches `r * tan(|t| / 2)` along each side from the
  corner. The tool is a block through all on the outline's square sketch. Four planes cut it: each side line, moved
  0.05 mm away from the arc centre, and the two lines through the arc centre square to each side. An Orca Hole through
  all at the arc centre (`hole_x`, `hole_y`, `hole_diameter` `2 * r`) removes the cylinder. What stays is the region
  between the corner and the arc, and a strip 0.05 mm wide past each side, where the body has nothing to change. For
  an even chamfer of size `c`, the tool is the triangle of the corner and the two points `c` along each side, with
  the side lines moved in the same way. A chamfer has no Hole.
- Each plane is a Cut with a fixed normal through the sketch origin and a bound `cut_offset`. A line whose direction
  turns with an angle formula is cut between two Transforms of the tool body, as a side of an outline built from cuts
  is. The formulas come from the formulas of the outline's corners and sides (`outline_cuts.Planned`) and from the
  size of the round. When the size follows a parameter, the formulas read it too.
- Where the tool is cut from. An outline built from cuts is a formula of half-planes (`halfplanes`). The tool is cut
  from the body of the lowest node of the formula that holds both sides of the corner. At a convex corner, that body
  holds the material of the corner, so the tool takes material away. At an inward corner, the node is an "or" node.
  Its body is a tool body that the outline cuts away, and that body holds the empty corner. So the corner tool
  removes the fill region from it, and the outline keeps that material. A rectangle is one body, and its tools are
  cut right after its extrude. When the extrude of the rectangle adds to a part that is already there (or cuts from
  it), the extrude makes a body of its own. The tools are cut from that body, and then a Boolean adds it to the part
  (or cuts it away), as the extrude did. The copy uses only differences, so no union leaves seams.
- The features go back into the recipe, inside the steps that wrote the outline: after the last feature that built
  the node's body (`outline_cuts.Built.marks`), or after the extrude of the rectangle. The tool body comes and goes
  between two features, so the index of each later body does not change. The sketch index of each later feature
  moves up. When the step is taken back (`Context.rollback`), every change is put back (`Context.undo`).
- An Orca Hole through all is a symmetric cylinder (`CadDocument::apply_feature`, Hole:
  `make_extrude(..., 1.0e5, true)`). So the tools work for one sided, symmetric and two sided extrudes (live: an L
  extruded symmetric).
- Checks. First, the checks of a drawn round must pass: the edge, the room on the sides, the part along lines through
  the corner, and the steps left out between the extrude and the round (see "Rounds, chamfers and threads"). Then the
  formulas must give the corner that the copy measured (within 0.00001 mm), and Orca must be able to write each
  formula. Then, at the current values, and at each value of the limit walk:
  - each corner keeps its kind (convex or inward), and turns by more than 0.001 degrees and less than 179.999 degrees;
  - the size stays above 0.01 mm (`corner_tools.SIZE_MIN`), and a chamfer set by a distance and 45 degrees stays on
    a square corner;
  - on each side, the rounds and chamfers of all steps together take no more than the length of the side;
  - each tool stays inside the outline's square sketch;
  - inside the part of each tool that changes the body, the body of the node is only the corner of its two sides,
    and the formula of the outline passes that body on unchanged. That part is the tool less the region beyond the
    line through the two points where the round meets the sides; that region lies in the cylinder. The copy checks
    this at a point of every cell of the lines of the outline and of the tool (`halfplanes.line_samples`), so another
    side of the outline in the tool, or a side that a variable moves into it, stops the round.
- Limits. The copy walks each free size that the outline, the tools and the size of the round read (the others kept,
  `limits.bounds`). At each value it checks the outline (`Planned.fits`) and the tools as above. The limits found
  replace the limits told for the outline ("keep wall between 3 and 28 mm" for the L of the tests: its chamfer takes
  3 mm from a side that is `wall` wide). A size of the round gets its own line ("keep fr between 0.01 and 14.9 mm"
  for the trapezoid of the tests): below 0.01 mm the Hole has no size, and Orca stops the rebuild. Each limit needs
  the parameter's line; a variable without one leaves the round out. Past a limit, Orca builds another shape without
  an error. A later round of a face group of the part walks these sizes again with its own rule (see "Rounds,
  chamfers and threads").
- A step that is written more than once. The steps of a tool body are written for a Combine, and again for each
  pattern or mirror of that Combine (`tools.build`). Each writing of the outline gets its own corner tools: the host
  of the tools (`corner_hosts.Host`) belongs to one writing (`Host.key`: the `outline_cuts.Built` record, or the
  extrude feature of the rectangle). So the tools of every writing go into the body of that writing, and every copy
  has the rounded corners. `Context.corner_hosts` holds a list of hosts for each extrude, and `Context.corner_steps`
  the hosts each round changed.
- Patterns. A pattern of features that repeats the extrude and every step that cut tools from its outline writes the
  tools again with the outline (`outline_cuts.again`, `corner_hosts.for_again`). Orca's pattern also writes its first
  copy where the original is. So a pattern that repeats the outline without its rounds would put the sharp corners
  back on the original: it is left out (`repeatsFinish`). A pattern of a rectangle with corner tools is left out too.
  A mirror or pattern of the body after the extrude leaves the round out (`bodyCopied`), as for a drawn round.
- Fallbacks, with the cause `cornerTools`: the formulas do not give the corner, Orca cannot write a formula, the tools
  of one outline would take more than 100 Orca features, a check fails at the current values, or the limits of a
  size cannot be told (the check fails at the current values, or the size has no parameter line). A size of the round whose formula Orca cannot write keeps its number, with the reason. A sketch
  with a bound size that is not a rectangle keeps the cause `roundUnbinds`.
- The shape of the copy (`solid.Solid`) takes the outline with the rounded corners, as for a drawn round. So later
  cuts, holes and rounds of a face group are checked against it.
- Live with OrcaSlicer 2.5.1 on 2026-11-16, the captures of `tests/orca_corners.py`: an L built from cuts with an
  inward and an outer round and a chamfer (4915, then 5715, 8115 and 3205 as its legs and wall changed), the same L
  extruded symmetric (4915, 6915, then 13830 at twice the length), a trapezoid with a round whose size is a parameter
  at a side that turns with the angle, and a chamfer (6483.19, then 4537.38 at 50 degrees, 9429.05 at 110 degrees and
  9414.75 with the round from 3 to 5), a window cut through a plate with its four corners rounded (21634.34, the same
  when the window moved, 20434.34 wider, 21634.34 lower), a rectangle that keeps its place, joined to a plate, with
  four rounds (15922.27, 16306.27, 15586.27), a pattern of the rounded window (19268.67), and a box whose rectangle
  follows sizes with four corner tools, then a round of its top edges (153102.18, 176137.03, 117265.62): every volume
  as worked out, to 1e-5. Also live: a rounded rectangle in a tool body, joined by a Combine and repeated by a pattern
  of the Combine (15012.5, then 15140.5 and 14948.5: both copies rounded), a rounded rectangle cut from a plate
  (12116.6, 11540.6, 12980.6), two round steps on one rectangle (15913.7, 16297.7, 15337.7), and a pattern of a
  trapezoid window whose rounded corner turns with the angle (20849.8, 21582.6, 21499.6): every volume as worked out,
  to 0.1. A box with corners rounded by `fr` and a 2 mm round of its top edges built at `fr` 4, 3.2, 2.5 and 1.5,
  with the volumes Pappus gives; the told lower limit of `fr` (3.12) follows the copy's room rule, which is safer
  than Orca needs here.

### Thin extrudes

Orca has no thin extrude, so the copy builds the wall of a thin extrude from plain extrudes (`thin.py`).
`steps.extrude` sends each thin extrude to `thin.extrude`. The sides of the extrude come from `steps.extrude_sides`,
as for any extrude.

The side of the wall comes only from what Fusion measured. The shared layer (`design_model/steps/thin.py`) decides
it, with the same rules as the Paramability output:

- For a closed outline, the area of the end face is the cross section of the wall (`closed_side`). The copy also
  needs the area of a wall with sharp corners (`area_fits` with sharp corners): Fusion keeps the corners of the wall
  sharp, and the rectangle that Orca draws has sharp corners. A wall whose area fits only rounded corners is left
  out.
- For an open line, each face that Fusion made must lie on the wall of one side and one direction (`line_side`). A
  face that Fusion merged with a face of the part counts only while the copy builds the part, not a tool body.

When the side is not certain, the step is left out with the reason.

What the copy writes:

- One rectangle or one circle, one way or symmetric, no taper: two plain sketches on the sketch plane. The outer
  outline is extruded as a new body. The inner outline is cut through all of it. On a part that has a body already,
  the two extrudes make a tool body, and a Boolean adds it to the part, cuts it away or keeps what both share. On the
  first body of the part, the two extrudes go into the part. For a wall inside the outline, the outer outline is the
  drawn one, and the inner one is smaller by the thickness on each side. For a wall outside the outline, the outer
  one is larger by the thickness on each side, and the inner one is the drawn one. A centred wall takes half of the
  thickness to each side. So the width, the height and the radius are the drawn size plus or minus the thickness
  (`width + 2 * wall`, `0.5 * dia - wall`), and the length follows too. A rectangle or circle that Fusion moves when
  a size changes keeps its numbers, and the sizes that move it are marked. `limits.guard` tells how far a variable
  may go while the inner outline stays inside the outer one and above zero.
- One straight line with the wall centred on it: a rectangle centred on the middle of the line, along the line. Its
  width is the length of the line and its height is the thickness. The thickness follows its variable. The length
  follows when the line keeps its middle and its direction as the sizes change; else it keeps its number, and the
  sizes that move the line are marked.
- Any other open line of straight lines (an L, a U, a wall on one side of one line): the outline of the wall
  (`thin.band`, sharp corners as in Fusion) as sketch lines with numbers, extruded with the step's operation. The
  line and the thickness keep their numbers, and the sizes that move them are marked.

A cut or intersect that does not meet the part is left out (cause `missesPart`). A pattern or mirror cannot repeat a
thin wall, since its first extrude starts a new body (cause `notRepeatable`).

Left out:

- several outlines, an outline with holes, an open line with arcs, lines that do not run one after the other or
  against the line, a wall that folds, and a side that the faces do not show (cause `thinOutline`);
- a closed outline that is not one rectangle or one circle, and a face of the part as the outline (cause
  `thinShape`);
- two ways, To a face, through all, a taper, a wall setting that could not be read, a side that the end face does
  not show, and a wall with rounded corners (cause `refused`).

Live check: `tests/orca_thin.py` writes the captures as JSON files, and the volumes are worked out there (the
volumes of the divider, the L and the ring also agree with `scripts/fixture_geometry.py`):

```
python3 -m tests.orca_thin /tmp/thin
python3 scripts/orca_live_check.py write /tmp/thin/orca_thin_divider.json /tmp/divider.3mf
python3 scripts/orca_live_check.py check /tmp/thin/orca_thin_divider.json --set len=36 wall=3
```

| Capture | What it is | Volume (mm3) | After `--set` |
| --- | --- | --- | --- |
| `orca_thin_divider` | a 40 x 40 x 2 plate and a divider 30 long, 1.6 thick, 20 above the plate, centred on its line, joined | 4160 (3200 + 960) | `len=36 wall=3`: 3200 + 36 * 3 * 20 = 5360 |
| `orca_thin_ell` | an L shaped line (0, 0) to (30, 0) to (30, 20), the wall 2 thick inside the corner, 20 high | 1920 (96 mm2 x 20) | none: the line and the thickness keep their numbers |
| `orca_thin_frame` | a wall 2 thick outside a centred 80 x 50 rectangle, 30 high | 16080 | `wall=3`: 24480 |
| `orca_thin_ring` | a wall 2 thick inside a centred circle 40 across, 10 high | 2387.61 (760 pi) | `wall=3`: 3487.17 (1110 pi) |

### Ribs and webs

Orca's Design tab has a Rib, but how it ends its wall was not compared with Fusion. So the copy builds each wall as
the thin extrude of an open line it is (`rib_web.py`). The
shared layer (`design_model/steps/rib_web.py`) finds the wall along each line, with the same rules as the
Paramability output (see `docs/limits.md`): straight lines drawn one after the other, no draft, no fillet, the side
and the way from the faces Fusion made, and a part that grew by the whole wall. For a rib, the depth is the width of
the wall in the sketch plane and the thickness its length along the sketch normal; for a web, the other way round.
Each wall then goes to the thin extrude of an open line (see "Thin extrudes"): a straight line with the wall centred
on it is a rectangle whose width follows, any other line is the outline of its wall with numbers. The length of the
extrude follows its variable. A web of several lines writes the features of one thin extrude per line.

A depth that Fusion found (To Next) keeps its number, and the sizes read before the step are marked. A wall inside
the box of the part may run into the part at a larger depth, so its depth, the thickness of a web and the sizes
before it are marked too. A web whose lines Fusion stretches to the part is left out, and so is every wall that the
faces or the volume do not show (cause `ribWeb`).

Checked in OrcaSlicer 2.5.1 on 2026-11-19 with exports of test designs built in Fusion (the volume Fusion measured in
brackets):

| Design | What it is | Volume (mm3) | After `--set` |
| --- | --- | --- | --- |
| web on a plate | two crossing lines on a 60 x 40 x 4 plate, `wt` 2 centred, `wd` 10 up | 11160 (11160) | `wt=4`: 12640 (12640), then `wd=20`: 15680 (15680) |
| web L in a tray | one L line in a 60 x 40 x 20 tray, `wt` 2 on one side, `wd` 8 down | 17604 (17604) | `wd=16`: 18420 (18420) |
| web grid To Next | three lines from wall to wall in the tray, down to the floor, `wt` 2 | 20800 (20800) | `wt=4`: 24540 (24540) |
| rib in a channel | a line from wall to wall of a U channel, `rd` 8 down, `rt` 2 on one side | 21952 (21952) | `rt=4`: 22784 (22784) |
| rib To Next | the same line down to the floor of the channel, `rt` 2 centred | 23824 (23824) | `rt=4`: 26528 (26528) |

### Press Pull of a round face

Orca has no Press Pull. The copy builds a Press Pull (Offset Faces) of one whole round face as a ring between the old
and the new radius (`press_round.py`). Fusion moves the face along its outward normal: the radius of a pin or a boss
becomes the radius plus the distance, and the radius of a bore the radius less the distance. The shared layer decides
whether the face can be moved (`design_model/steps/offset_round.py`), with the same rules as the Paramability output
(see 3.20 in `docs/developer-guide.md`):

- the face goes all the way round, and both its ends are flat faces square to its axis;
- no face next to it moves in the same step;
- the new radius stays above zero and clear of the other edges of the end faces, by 0.01 mm;
- Fusion left a cylinder of the new radius on the same axis (`rounds_after`).

When one of these is false, the step is left out with the sentence of the shared layer and the cause `offsetCurved`.

The copy writes a tool body and a Boolean:

1. A sketch with a circle on the plane of one end, on the axis, extruded as a new body to the plane of the other end.
2. A sketch with a smaller circle on the same plane, cut through all of the tool body.
3. A Boolean with the part: Add when the distance moves the face out of the material (a pin or a boss that grows, a
   bore that shrinks), Cut when it moves the face into the material (a bore that grows, a pin that shrinks).

One circle has the new radius, and its `radius` follows the distance. The other circle has the face's own radius,
moved by 0.005 mm (`OVERLAP_MM`) into the side the Boolean already fills: into the material for an Add, into the air
for a Cut. So the tool body never shares a round face with the part, which a Boolean of a geometry kernel handles badly.
0.005 mm is half the clearance the shared layer keeps from the other edges, so this move never reaches one.

The checks of the copy:

- The face must be on the part as the copy builds it. For an Add, the copy must hold material in a ring of up to 1 mm
  on the material side of the face. For a Cut, the ring that the cut removes must meet material. Otherwise the step
  is left out (cause `missesPart`, or `afterGap` after a step that is left out).
- The radius of the face and the planes of its ends keep their numbers in Orca. Every size that a step of the part's
  component reads before the Press Pull is marked (`reach.any_face_sizes`), since such a size may change the face's
  radius or move its ends.
- The parameter's line tells how far the variable of the distance may go (`limits.guard`): the new radius stays on the
  same side of the old radius (cause "the round face moves the other way"), above zero, and clear of the other edges
  of the end faces (cause "the round face reaches another edge of the faces at its ends"). Past these limits Orca adds
  or cuts the wrong ring, or the tool body is empty.

Left out, each with its reason: a Press Pull of a flat face (cause `pressPullFlat`), a Press Pull of more than one
face (cause `pressPullFaces`), a Press Pull of another curved face, and a round face of another component.

### Other components

A step can use geometry of another component: a plane, face, axis or direction, a point a hole sits on, or an outline
of another component's sketch. The Orca copy reads no motion file, so it writes each one where the capture places it,
as numbers in the part's coordinates (`orca_translate/other_components.py`, with the shared layer `design_model`):

- The shared layer brings each step in when it reads the design (`design_model.design`; `design.resolve` for each
  step of a tool body in `tools.build`): an outline of another component's sketch whose place is known
  (`design_model.borrowed`), and a flat face or plane that an extrude starts from or reaches to or that a hole sits on
  (`design_model.refs`), lose `foreign`. The doubts and notes this records wait in the resolved step: before each
  handler, inside the step's checkpoint, the walk and `tools.build` replay them (`design.replay`), so a step left out
  keeps none of them. The reader already
  gives mirror planes, split planes, revolve and pattern axes and pattern directions of other components in the part's
  coordinates (`assembly: true`). So these are copied: a mirror across a plane of another component, a pattern along
  its axis or edge or about its axis, a revolve about its axis, a split by its plane, an extrude to or from its flat
  face or plane, a hole on its face or sketch point, and an extrude, revolve, sweep or loft of its sketch, also in a
  tool body.
- Once a step is copied, each measured reference it holds marks the ticked sizes that may move it
  (`refs.mark_all`, `refs.acting_sizes`): those whose parameter acts on the component that owns it, and those whose
  parameter acts on a joint, another assembly item or a Move of occurrences, which may place any component (the
  capture does not say which occurrence). "Mirror1 mirrors across a plane of Cover that may move with it, and the
  copy cannot follow that". Such a parameter is then fixed or partly followed, never "not used". When the capture does
  not say where the parameters act, the shared layer tells the context (`Context.movers_unknown`) and every ticked
  size is marked ("... that may move with it, and the export cannot tell which sizes move it, so the copy keeps it
  where it is now"): any parameter may drive steps of several components. A step that does not change the part (a
  mirror whose copies stay apart) marks nothing.
- An outline of another component's sketch is written as numbers, with a note. Every size that may move its sketch
  is marked (`design_model.borrowed.movers`): those its dimensions read ("it changes the sketch Rim of Lid, which
  Sweep1 copies as fixed numbers"), and those that may move the sketch's component, the plane it sits on or geometry
  projected into it, read from its sketch graph by token ("it may move the sketch Rim of Lid, which Sweep1 copies as
  fixed numbers"). Without data on where the parameters act, or without a sketch graph, every ticked size is marked
  as above. Its sketch keeps its name,
  which may be the name of a sketch of the part: such an outline gets no sketch graph (`sketches.graph_for`) and no
  sketch sizes by name (`sketch_sizes.profile_sizes`), and its sketch plane names no sizes of the part
  (`design_model.reach.placement_sizes`).
- A Combine's tool body of another component (`tools.build`, with `design_model.tool_chains`): its steps were read in
  that component's coordinates (`helper_of`), so they are written there, each named with its component ("Extrude1 of
  Rod", since step names repeat between components), and an Orca Transform ("Body2 of Rod place") then carries the
  tool to its place at the Combine (`tool_chains.place_of`: the component's frame, then the inverse of the part's
  own frame at that time). Orca turns about the component origin, then shifts; the shape the copy keeps moves the
  same way. The ticked sizes that act on that component are marked ("Combine1 puts its tool at the place of Rod
  that may move with it, and the copy cannot follow that"), so a size that sets a step of the tool is "partly" and
  one that only moves the component is "fixed". So is a size of a joint or a Move in the root that places the
  occurrence. For a tool of the root component only those sizes of the assembly count, since the root has no place
  of its own. The origin planes the
  reader measured for the place (`tool<n>.xy` and so on) mark nothing more (`tool_chains.is_place_slot`). Inside such
  a tool, the copies of a pattern are read in the tool component's frame (`Context.component_frame`). Left out (cause
  `otherComponent`, `refused` or the cause of the step that stops it): a place that could not be read or is not a
  turn and a shift, a tool record that does not name its component, a tool of another component inside another
  one, a step of the tool not read in its component or whose outline names its sketch only by name (it could be
  taken for a sketch of the part), a split in the tool (the split rules look for later uses of its other pieces in
  the part's component only), and a step of the tool the copy cannot hold (a round whose edges it cannot tell,
  for one).
- Still left out (cause `otherComponent`): a record that stays `foreign` (a curved face, an edge, a direction, axis or
  plane whose place could not be brought in), edges of another component that a round or chamfer picks, a thread on a
  face of another component and a sweep path in another component.

Checked live with OrcaSlicer 2.5.1 on 2026-11-16 (`scripts/orca_live_check.py`): the fixtures `component_foreign_mirror`
(8282.7 mm3 as worked out, and 8452.4 after `depth_mm = 8`), `component_ref_reach` (8424.1, the boss up to z 25 in the
part's coordinates), `component_ref_hole` (7803.7) and `sweep_borrowed` (1857.8), and a pattern along an axis of
another component, a circular pattern about one, a revolve about one, a split by a plane of one and a tool body from an
outline of another component's sketch (the captures of `tests/test_orca_other_components.py`) built as worked out,
without an Orca error. Also live: the fixture `component_tool_foreign` (a box cut by a tool of Rod, turned a quarter
about z: 23214.6 mm3 as worked out, 23607.3 after `tool_len = 5`, 28407.3 after `box_h = 12`), and the same tool
turned a quarter about x so that it lies along -y of the part (22994.7 as worked out, 23748.7 after `tool_len = 5`;
a turn the wrong way would leave half the rod outside the box).

### Sketch text and embosses

Sketch text arrives as one outline per letter (`geometry/text_outlines.py`): the outer loop and the holes inside it.
Orca has no sketch text that Fusion's can become, but a sketch can hold imported regions (`imported_regions`, the
field Orca's own Text and SVG import write): each region is a list of polygons, the outer loop first, then its holes,
in the sketch plane. Orca extrudes such a sketch through its own path (`SketchEngine::make_extrude_regions`), and the
regions take precedence over the entities of the sketch. So the extrude of text gets a sketch of its own
(`orca_translate/text_regions.py`), named after the step with " text", and an Extrude that names it.

Each letter is written as polygons. A line keeps its two ends. An arc or a circle gets points close enough that no
chord is more than 0.005 mm from the arc. A free curve (a spline of a font) starts from its samples, which lie within
0.0005 mm of the curve, and keeps only the samples it needs to stay within the rest of the 0.005 mm. Points closer
than 0.001 mm to the point before them are merged, as Orca merges them.

Orca leaves out a region that it cannot build, and gives no error. The copy therefore checks every letter before it
writes it, and leaves the step out (cause `textOutline`) when one check fails:

- each loop closes, has at least three points more than 0.001 mm apart, and has an area;
- no loop crosses or touches itself, and no two loops of the text cross or touch;
- every hole lies inside the outer loop of its letter and outside the other holes of that letter;
- no letter lies in the material of another letter (a letter inside the hole of another, as in a ring mark, is
  correct);
- every curve can be written: a free curve whose samples do not stand for the whole curve, and an ellipse, stop the
  copy;
- all letters lie in one sketch plane, and the extrude takes only text (text and other outlines in one extrude are
  left out: put the text in an extrude of its own);
- text of several letters does not start the part (Orca would make the part a set of separate solids).

Orca reads the distance and the flip of an extrude of regions, and treats every end other than Blind as symmetric: a
two sided extrude is built symmetric, through all is built symmetric 100000 mm long, and a taper is not read. The
copy writes one side (Blind), Symmetric, and through all as for any extrude: Orca's own through all only when no part
of the body lies behind the sketch (then it is the same as one way), else a 1000 mm one way Blind. Two sides and a
taper are left out (cause `textExtent`). A cut or intersect is checked against the part the copy built, letter by
letter: the letters that miss it are left out with a note, and a cut whose letters all miss is left out.

Only the depth follows a variable. The size and the place of the text keep their numbers, and these sizes are marked
with the reason: the text height (`text_params`), the dimensions of the text's sketch, the sizes that may move its
sketch plane, and the sizes read before the sketch when the sketch holds geometry projected from the part (or when the
capture has no graph of the sketch to tell).

An emboss on a flat face is an extrude of its outlines from that face by the depth: a join for a positive depth
(raised), a cut for a negative one (sunk). The shared layer gives that extrude (`design_model/steps/emboss.py`,
`as_extrude`), and the Orca copy hands it to the extrude handler, so text goes to imported regions and other outlines
are drawn as for any extrude. The depth follows its variable. Left out: an emboss on a curved face, on faces of more
than one plane, or that may follow tangent faces (cause `embossFace`); an outline that runs past its face, which
Fusion trims to the face (cause `embossTrimmed`: Orca has no step that keeps an extrude within a face); an outline
moved or turned on its face, a sketch plane tilted to the face, and a measured change that is not the outline area
times the depth. A size that moves the outline on its face is marked.

### Where the part sits

Capture values are in the body's component coordinates. They go to the root (`target.placement`), turn so the
design's up axis is Orca's Z (the dialog's up direction), and move so the part's box is centred on the bed centre
(128, 128, a 256 mm bed) with its lowest point on the bed. The bed centre is the recipe's modeling origin. The plate
mesh, read in root coordinates, takes the same turn and move (`orca_translate/place.py`).

The box is the Fusion part's while the copy holds every step. When steps are left out, the copy can be larger or
smaller than the Fusion part, and placed by the Fusion box it would float or sink into the bed (a part whose rounds
and chamfers are left out sat 0.25 mm below it). Then the box is the copy's own (`place.copy_box`: the box of
`solid.Solid`, measured with lines along each axis), when it differs from the Fusion box by more than 0.01 mm, and the
translation runs again with that placement. The mesh is the real Fusion body: it keeps the same turn and the same move
across the bed, so the two lie over each other, and is raised or lowered alone to rest on the bed. The report's
`placement` block says which box placed the copy (`by`: `copy` or `part`), the copy's box on the plate and how far the
mesh was raised (`mesh_lift`), and the result window says the two differ.

## Limits

- Orca 2.5 cannot tie sketch dimensions to variables. Outlines of straight lines are built from plane cuts so that
  their corners follow; outlines with arcs, circles that move and splines keep their numbers.
- An outline built from cuts gives the outline only within the limits on the parameters' lines. Past a limit Orca
  builds another shape without an error. The limits are worked out for one variable at a time.
- Geometry projected into a sketch keeps its place in Orca; every size read before the sketch is marked.
- Sketch text keeps its size and place in Orca; only the depth of its extrude or emboss follows a variable. The
  letters are polygons within 0.005 mm of Fusion's curves.
- A sketch whose plane Fusion does not name (Fusion 2706 does so for some sketches on a face) counts as one on a face:
  every size read before it is marked, also a size that only changes the face's extent (a width under a boss).
- A circular pattern whose copies Fusion places off its count and angle (Fusion 2706, hand check CP1) is left out.
- The copy reads a distance dimension between two lines as keeping them parallel. Until hand test OR18 confirms this
  in Fusion, the sizes that rest on it follow only partly.
- Orca rebuilds the whole Design body from the recipe. A step that fails there (a cut that no longer meets the part
  after a variable change, for one) fails the whole rebuild; Undo the change.
- Orca's own "through all" goes both ways from the sketch. A one way through all cut or hole is written as Orca's
  through all only when nothing of the part lies behind its sketch; otherwise as a 1000 mm blind cut. A join or new
  body through all is left out: Fusion ends it at the part, and Orca would add material far past it.
- A cut through all makes no end face, so Fusion's stored direction is all there is, and Fusion can store it toward
  the side without material (seen on a sketch on the XZ plane of a Z up design). Such a one way cut or hole goes to
  the side where its outline meets the copied part, with a note; when both sides meet material the stored direction
  stays.
- A blind hole's drill point is left flat; the result notes it. A hole up to a face with a drill point is left out.
- A round or chamfer drawn into an outline keeps its number, and the drawn outline has numbers only. On an outline
  with a size that follows a variable, corner tools cut the corners, and they follow within the limits on the
  parameters' lines. The checks against other steps hold at the current sizes: a variable that later moves another
  step into the corner's region is not checked.
- A round, chamfer or thread is checked at the current sizes. One that Orca cannot make after a variable change (a
  round larger than a face has become) fails the whole rebuild. The parameter's line gives the limits of a variable
  that sets a round size or a thread length; for a part size, a note gives how far the part may shrink.
- A thread and its lead-ins keep their place. A face that a size moves takes neither with it: a through hole whose
  part gets thinner by more than the lead-in depth leaves the far lead-in in the air, and Orca stops the rebuild on
  a cut that removes nothing.
- A hole's sketch plane keeps its place: a sketch on a face that a size moves does not follow it. The sizes that may
  move it are marked.
- An extrude's sketch plane, and a "From" face, keep their place too; the sizes that may move them are marked. The
  rule for a sketch on a face of the part is wide: every size read before the sketch is marked, since the copy
  cannot tell which face the sketch sits on.
- A "To" length follows its plane, but a variable that moves the plane past where the extrude starts gives Orca a
  length below zero, and Orca extrudes the other way where Fusion would stop with an error. The parameter's line
  says how far the variable may go.
- A hole "To" a face, or of a given depth, with a counterbore or countersink: a variable that makes the hole no
  deeper than the recess gives only the recess in Orca, without an error. The parameter's line says how far the
  variable may go.
- A hole "To" a face that Fusion may join with the faces next to it (Chain Faces, or a hole whose `matchShape` is not
  checked yet) follows only that face. The sizes that may move the face are marked.
- A tapered extrude is checked at the current sizes. When a variable change shrinks a side of its outline to nothing,
  Orca builds a straight extrude instead, without an error. The parameter's line says how far the variable may go.
- A sweep path keeps its numbers. A swept outline that a variable grows past the tightest bend of its path runs
  into itself; the parameter's line says how far it may grow, also when that is far from the current size. The same
  is true for a pipe, and its line also says how thick the wall of a hollow pipe may get before it closes the hole.
- The shape the copy keeps to check cuts (`solid.py`) does not know threads, and knows rounds and chamfers only as
  material a later cut may not count on (on the simple parts rounds are copied on).
- A revolve angle that follows a variable is checked at the current sizes and walked down for the limit on the
  parameter's line. That walk takes about 18 tests of the angle, so a band of angles where a cut misses the part, between
  the tested angles, can be missed.
- A path pattern's path keeps its numbers. Its count and distance follow only within the limits on the parameters'
  lines; past them Orca puts copies past the end of the path. Copies that keep their direction on an arc keep their
  distance as a number.
- A pattern or mirror plane, a turning axis and a split plane keep their place: one on a face that a size moves does
  not follow it.
- A Press Pull of a round face keeps the face's radius and its end planes as numbers. A variable that changes the
  radius of the pin or the bore in Orca, or moves its ends, leaves the ring where it was: Orca then adds or cuts a
  ring next to the face, without an error. The sizes that may do this are marked.
- A Boolean that adds or cuts nothing does not stop Orca's rebuild, but a pattern whose count or spacing a variable
  changes can put copies where the part has none; they then add material there or cut nothing.
- The count of a pattern or mirror of bodies that a Combine takes keeps its number in Orca: Fusion's Combine holds a
  fixed list of copies.
- A thin wall along an open line of more than one line, or not centred on its line, keeps its line and its
  thickness as numbers in Orca.
- A coil is left out: Orca's sweep along its helix gives the wire other ends and another thickness than Fusion's coil
  (see "Coils").
- One body per file. The recipe format is Orca's internal one (version 6) and may change.

## Live check without Fusion

`scripts/orca_live_check.py` runs a capture through the same plan as the export and writes the `.3mf`, with a box of
the part's size on the plate in place of the mesh:

```
python3 scripts/orca_live_check.py write box_graph /tmp/check.3mf
ORCA_CAD_MCP=1 /Applications/OrcaSlicer.app/Contents/MacOS/OrcaSlicer --datadir ~/.orca-dev-data /tmp/check.3mf
python3 scripts/orca_live_check.py check box_graph --set cube_mm=30 height_mm=20
```

Use a test copy of Orca with its own `--datadir`, never the everyday one. `check` reads the Design body through the
control socket (`/tmp/orca-cad-mcp.sock`, `describe_scene` and `mass_properties`), prints its box and volume next to
the capture's `target.box` and `target.volume_mm3` on the plate, and with `--set` changes variables
(`set_variable`) and prints the body again. A fixture's volume is worked out on a 0.2 mm grid
(`scripts/fixture_geometry.py`), so curved parts agree within about half a percent. The socket has no open method:
restart that Orca with the file to open another one. `box_graph` and `plate_hole_graph` name two captures with
sketch graphs, made by the tests. The captures of outlines built from plane cuts come from `tests/orca_cuts.py`
(`outline_capture`, `window_capture`, `window_pattern_capture`): save one as JSON and give its path to `write`. The
tests read the written recipe in Python (`orca_cuts.Section`: the cross section of each body, through the sketches,
extrudes, cuts, transforms, Booleans and patterns) and compare it with the outline at other values of the variables.

Revolves with holes, several outlines and symmetric angles that follow sizes have captures in
`tests/orca_revolves.py`. Save one with `python3 -m tests.orca_revolves <name> <file>` and give the file to `write`.
The volumes are exact (a loop of area A whose centre lies at radius R makes 2 pi R A per full turn):
`ring_with_hole` (radius 10 to 20, 10 high, a hole of radius 2 at radius 15, a full turn: 3000 pi - 120 pi^2 =
8240.43), `ring_on_rod` (that ring joined onto a rod of radius 12, 30 high: 6880 pi - 120 pi^2 = 20429.80),
`two_rings_on_rod` (two separate outlines joined onto that rod in one revolve: 6160 pi = 19352.21),
`groove_both_sides` (one Revolve Cut of a full turn with a groove from radius 9 to 12, z 10 to 14, drawn on both
sides of the axis, into that rod: Orca gets one cut, 4320 pi - 252 pi = 4068 pi = 12780.0, built so in Orca) and
`symmetric_ring` (the ring without the hole, 45 degrees to each side, the angle the variable `half_deg`: 750 pi =
2356.19, then `--set half_deg=90` 1500 pi = 4712.39 and `--set half_deg=200` the closed ring 3000 pi = 9424.78). All four built with these volumes in OrcaSlicer 2.5.1 on
2026-11-18, and `symmetric_ring` followed `half_deg`.

A hole up to a plane and extrudes that start at a distance from a face have captures in `tests/orca_to_faces.py`. Save
one with `python3 -m tests.orca_to_faces <name> <file>` and give the file to `write`. The volumes are exact. All three
built with these volumes in OrcaSlicer 2.5.1 on 2026-11-18, also after the `--set` changes:

- `hole_to_plane`: a 40 x 40 x 20 block (box -20 to 20 in x and y, 0 to 20 in z) with a hole of diameter 5 from the
  middle of its top down to Plane1 at `lift_mm` 8, so 12 deep: 32000 - 75 pi = 31764.38 mm3. The depth is
  `12 - (lift_mm - 8)`: `--set lift_mm=5` gives 15 deep, 31705.48 mm3, and `--set lift_mm=12` 8 deep, 31842.92 mm3.
- `boss_into_plate`: a 40 x 40 x 10 plate (16000 mm3) and a 10 x 10 boss that starts From its top face at the offset
  `-inset_mm` (`inset_mm` 2, so 2 mm inside the plate, z 8) and goes 5 mm up: 16000 + 100 x 3 = 16300 mm3, box z 0 to 13.
  The sketch plane keeps z 8, so `--set inset_mm=4` leaves the body as it is (16300 mm3): the offset keeps its number.
- `lowered_post`: the same plate and a 10 x 10 post that starts From its top face at the offset `rise_mm` (2, so 2 mm
  above it, z 12) and goes 4 mm down: 16000 + 100 x 2 = 16200 mm3, box z 0 to 12. `--set rise_mm=...` leaves the body as it
  is.

Path patterns: `tests/orca_path_patterns.py` makes three captures (`python3 -m tests.orca_path_patterns <name>
<file>`). Each is a plate with square pegs of 6 x 6 x 6 mm (216 mm3) joined on its top face at z = 4, and the
variables `count` and `pitch` set the count and the distance of the pattern. `pegs_line`: a 40 x 20 x 4 plate, 4 pegs
10 mm apart along a 40 mm line from (5, 10): 4064 mm3, box 0 to 40, 0 to 20, 0 to 10; `--set pitch=12` 4064 with
the box to x = 44; `--set count=5 pitch=9` 4280, box to x = 44; `--set count=3` 3848, box as at first. The
parameter lines say count under 5 and pitch under 13.3 mm. `pegs_arc`: a 50 x 40 x 4 plate, 5 pegs 12 mm apart
along a quarter arc of radius 35 about (5, 5) from (40, 5), turning with the arc: 9080 mm3, box 0 to 50, 0 to 42.84,
0 to 10; `--set count=4` 8864, box to y = 40; `--set pitch=13` 9080, box to y = 43.12; `--set count=3` 8648, box to
y = 40. The parameter lines say count under 5.58 and pitch under 13.7 mm. `pegs_arc_slide`: the same plate and arc,
5 pegs over 48 mm of the arc keeping their direction: 9080 mm3, box 0 to 50, 0 to 42.31, 0 to 10; `--set count=4`
8864 and `--set count=3` 8648, the box the same (the last peg stays at 48 mm). `pitch` keeps its number. All three
built with these volumes and boxes in OrcaSlicer 2.5.1 on 2026-11-19, also after the `--set` changes.

Patterns and mirrors of bodies that a Combine takes: the captures of `tests/orca_body_patterns.py`. Save one with
`python3 -m tests.orca_body_patterns <name> <file>` and give the file to `write`. Each peg is a 6 x 6 mm square body
standing on the top face of the plate (z 4), `peg_h` high (6 mm, 216 mm3). The volumes are exact, and the boxes are
in the capture's coordinates. `count` keeps its number in Orca, so `--set count=5` leaves each body as it is. All four built with
these volumes and boxes in OrcaSlicer 2.5.1 on 2026-11-19, also after the `--set` changes below.

- `peg_row`: a 60 x 20 x 4 plate (box 0 to 60, 0 to 20, 0 to 10) and a peg at (8, 10), patterned 4 times `pitch`
  (14) mm apart along X and joined by one Combine: 4800 + 4 x 216 = 5664 mm3. `--set pitch=18` gives 5664 mm3 with
  the box to x 65; `--set peg_h=10` gives 6240 mm3 with the box to z 14.
- `peg_ring`: a 60 x 60 x 4 plate round the origin (box -30 to 30, -30 to 30, 0 to 10) and a peg at (20, 0),
  patterned 6 times round the Z axis and joined: 14400 + 6 x 216 = 15696 mm3. `--set peg_h=10` gives 16560 mm3.
- `mirrored_peg`: a 40 x 20 x 4 plate round the origin (box -20 to 20, -10 to 10, 0 to 10) and a peg at (-12, 0),
  mirrored across the YZ plane and joined: 3200 + 2 x 216 = 3632 mm3. `--set peg_h=10` gives 3920 mm3.
- `cutter_row`: a 60 x 20 x 10 block (box 0 to 60, 0 to 20, 0 to 10) and a 6 x 6 cutter from z 4 to 14 at
  (8, 10), patterned 4 times `pitch` (14) mm apart and cut by one Combine, each pocket 6 deep: 12000 - 4 x 216 =
  11136 mm3. `--set pitch=12` gives 11136 mm3; `--set pitch=18` puts the last pocket 1 mm into the block, 11316 mm3.

Pasted bodies: the captures of `tests/orca_pastes.py`. Save one with `python3 -m tests.orca_pastes <name> <file>`
and give the file to `write`. Each is a 6 x 6 mm square body (Body2) pasted in place as Body3, Body3 moved 20 mm
along X, and one Combine that takes Body2 and Body3. The volumes are exact, and the boxes are in the capture's
coordinates. Both built with these volumes and boxes in OrcaSlicer 2.5.1 on 2026-11-19, also after the
`--set` changes; the source's steps written twice under the same names did not disturb Orca.

- `pasted_peg`: a 40 x 20 x 4 plate (box 0 to 40, 0 to 20, 0 to 10) and a peg at (8, 10) on its top face, `peg_h`
  (6) high, its copy at (28, 10), both joined: 3200 + 2 x 216 = 3632 mm3. `--set peg_h=10` gives 3920 mm3 with the
  box to z 14.
- `pasted_cutter`: a 40 x 20 x 10 block (box 0 to 40, 0 to 20, 0 to 10) and a cutter at (8, 10) from z -2, `cut_h`
  (8) high, its copy at (28, 10), both cut, each a pocket 6 deep from the bottom face: 8000 - 2 x 216 = 7568 mm3.
  `--set cut_h=10` gives 7424 mm3 (pockets 8 deep), `--set cut_h=4` 7856 mm3 (pockets 2 deep); the box stays.

Pipes: the captures of `tests/orca_pipes.py`. Save one with `python3 -m tests.orca_pipes <name> <file>` and give
the file to `write`. The volumes are exact (a circle of radius r whose centre runs along a path of length L makes
pi r^2 L), and the boxes are in the capture's coordinates:
`solid_pipe_on_plate` (a plate from (-5, -10, 0) to (45, 10, 6) with a solid pipe of diameter `pipe_d` 6 joined
along a 40 mm line on its top face, half of the pipe above the plate: 6000 + 180 pi = 6565.49 mm3, box to z 9; with
`--set pipe_d=8` 7005.31), `hollow_pipe_bend` (a new body: diameter 8, `wall` 1, along a 20 mm line, a tangent arc
of radius 20 through 90 degrees and a 30 mm line: 350 pi + 70 pi^2 = 1790.43 mm3, box from (0, -4, -4) to (44, 50,
4); with `--set wall=2` 3069.31, with `--set pipe_d=10` 2301.98) and `pipe_cut_into_block` (a block from (-10, -10,
0) to (50, 30, 20), the box, with a pipe of diameter 6 cut along a line, a tangent arc of radius 15 and a line, in
through one face and out through another: 48000 - 405 pi - 67.5 pi^2 = 46061.46 mm3; with `--set pipe_d=8`
44553.70). All three built with these volumes in OrcaSlicer 2.5.1 on 2026-11-19, also after the `--set`
changes.

Coils: `tests/orca_coils.py` writes raw recipes (no capture: the copy leaves coils out) that sweep a circle of
radius 1 along an Orca Helix on the XY plane through (128, 128, 2), right hand, as a new body. Write one with
`python3 -m tests.orca_coils <name> <out.3mf>`, open it in the test Orca, then run `python3
scripts/orca_live_check.py check`. The script prints the volume and the box of a round tube along the helix and of
Fusion's coil of the same sizes (a circle of radius r on the plane through the axis, carried round with a screw
motion: pi r^2 times 2 pi R times the turns). `spring_square` and `spring_upright` are a helix of radius 10, pitch 5
and height 20 (4 turns): the tube is 4 pi sqrt(400 pi^2 + 25) = 792.06 mm3, box (117, 117, 1.003) to (139, 139,
22.997), and Fusion's coil 80 pi^2 = 789.57 mm3, box (117, 117, 1) to (139, 139, 23). `quarter_square` and
`quarter_upright` are a quarter turn of radius 10 and pitch 20 (height 5), where the ends show most: the tube is
51.79 mm3, box (127.697, 127.697, 1.047) to (139, 139, 7.953), and Fusion's coil 5 pi^2 = 49.35 mm3, box (128, 128, 1)
to (139, 139, 8), its ends on the planes x = 128 and y = 128. A `square` probe has the circle square to the helix at
its start, an `upright` probe has it on the plane through the axis. Built in OrcaSlicer 2.5.1 on 2026-11-19: both
`square` probes gave the tube (792.1 and 51.8 mm3, the tube's box). `spring_upright` gave Fusion's volume (789.6 mm3)
and its box within 0.01 mm, but `quarter_upright`, with Fusion's volume (49.3 mm3), ends 0.14 mm off the plane x =
128 (box from x 127.857): Orca's sweep does not keep the section on planes through the axis everywhere, so its end
faces lean, and the copy leaves coils out.

A Press Pull of a whole round face has captures in `tests/orca_press_round.py`. Save one with `python3 -m
tests.orca_press_round <name> <file>` and give the file to `write`. The volumes are exact. All three built with these
volumes in OrcaSlicer 2.5.1 on 2026-11-19, also after the `--set` changes:

- `pin_grown`: a 40 x 40 x 5 plate (box -20 to 20 in x and y, 0 to 15 in z with the pin) and a pin of radius 5, 10
  high on its top, grown by `grow_mm` (1) to radius 6: 8000 + 360 pi = 9130.97 mm3. `--set grow_mm=2` gives
  9539.38 mm3, `--set grow_mm=0.5` 8950.33 mm3.
- `bore_grown`: a 40 x 40 x 10 block (box -20 to 20 in x and y, 0 to 10 in z) with a bore of radius 4 through it,
  grown by `grow_mm` (0.5, the distance `-grow_mm`) to radius 4.5: 16000 - 202.5 pi = 15363.83 mm3. `--set grow_mm=1`
  gives 15214.60 mm3, `--set grow_mm=2` 14869.03 mm3.
- `pin_shrunk`: the plate and pin of `pin_grown`, the pin shrunk by `shrink_mm` (1, the distance `-shrink_mm`) to
  radius 4: 8000 + 160 pi = 8502.65 mm3, the same box. `--set shrink_mm=2` gives 8282.74 mm3, `--set shrink_mm=0.5`
  8636.17 mm3.

Sketch text and embosses: the captures `orca_text_raised` (letters raised 1 mm by an extrude, 2492 mm3),
`orca_text_cut` (cut 0.6 mm deep, 2344.8 mm3), `orca_text_emboss` (raised 1 mm by an emboss, 2492 mm3) and
`orca_text_emboss_sunk` (sunk 0.6 mm, 2344.8 mm3) in `tests/fixtures/captures` are a 60 x 20 x 2 mm plate with an
"L" of six sides (28 mm2) and an "O" that is a square ring (64 mm2). `tests/orca_text.py` makes them (`python3 -m
tests.orca_text` writes them again). Each volume is 2400 plus or less 92 times the depth `text_depth`: with
`--set text_depth=2` a raised copy gives 2584 mm3, a sunk one 2216 mm3. All four built with these volumes in OrcaSlicer 2.5.1 on 2026-11-18,
also after `--set text_depth=2`.

A full ellipse: the capture `extrude_ellipse_turned` (radii 10 and 5, its major axis turned 30 degrees, 2 mm
thick) built in OrcaSlicer 2.5.1 on 2026-11-18 with a box of 18.03 x 13.23 x 2 mm and 314.2 mm3, as worked out.

Thin extrudes: the captures of `tests/orca_thin.py` (`python3 -m tests.orca_thin <folder>`) built in OrcaSlicer
2.5.1 on 2026-11-18 with the volumes worked out: `orca_thin_divider` 4160 mm3 (4352 at `len` 36, 5360 with `wall`
3 too), `orca_thin_ell` 1920, `orca_thin_frame` 16080 (24480 at `wall` 3) and `orca_thin_ring` 2387.6 (3487.2 at
`wall` 3).

Rounds, chamfers, threads and hole centres, checked with OrcaSlicer 2.5.1 on 2026-11-15 and 16: a top chamfer whose
size is a variable (7941 mm3 as the capture's 7941, then 7771 at twice the size), a top round of a cylinder (3112.27
as worked out), a bottom round then a top chamfer, a round of the top of a Y up plate, a through and a blind tapped M6
hole (the blind depth a variable), a rod with an M8 thread, and a hole centre that follows a size (149981, then 151037
when the hole is moved partly out of the part, both as worked out) built without an error. Raw recipes showed what
Orca does: all edges of a cylinder and of a slot round fine (the seam and the smooth edges are skipped), a top round
takes the rim of a through hole, the shell without an open face gives the inner block, and threads that run out of
the part can fail (8 of 32 failed; 0 of 24 when kept half a pitch inside).

Rounds and chamfers drawn into outlines, checked with OrcaSlicer 2.5.1 on 2026-11-16 (the captures of
`tests/orca_outline.py`): a plate with its four side edges rounded (7965.66) and chamfered (7920.0), an L with its
inward corner rounded (6019.31) and chamfered (6045.0) and with its inward and two outer corners rounded (5980.69), a
hexagon with corners of 120 degrees rounded (2585.18) and chamfered (2494.15), a window through a wall with its
corners rounded (11566.35), chamfered (11568.0) and rounded with half its height, so its short sides are gone
(11705.42), a pocket cut 8 mm deep with its upright edges rounded (22427.47), a plate with its side edges rounded and
then its top edges (Orca's top group over the new arcs, 7898.40), and a box whose rectangle followed sizes, rounded
(153160.50, then 95725.31 with its height from 32 to 20): every one built with the box and the volume worked out. On
an owner's design, nine corners of four steps drawn into two outlines changed Orca's volume by exactly the area the
corners take or fill times the length of their edges.

Thread ends and lead-ins, checked with OrcaSlicer 2.5.1 on 2026-11-16 (one file per run, the volume Orca builds
against the one worked out from Orca's groove): a thread started or stopped at or outside a face of the part failed
in 25 of 41 runs. With lead-ins cut after a thread kept half a pitch inside, 204 of 204 runs built as worked out (tapped
through holes 72, blind holes 36, rods 96: M3, M6, M8, M12, several lengths, six start angles), and the export's own
output 65 of 65 (the same kinds, three start angles). At the limits the result gives, a chamfer of `edge` built at
9.09 (the limit) and 9.5 and failed at 10; a part length thread built at `len` 1.9 (the limit 1.89) and failed at
1.85.

Patterns, mirrors, Combine, split, move and revolve, checked with OrcaSlicer 2.5.1 on 2026-11-15 and 16: 43
captures built with the box and volume worked out (rectangular rows, grids by spacing and extent, negative and to both
sides, holes repeated; circular full, part and to both sides; mirror of features and of the body; Combine join, cut,
intersect with every and any tool, a Combine inside a tool, a tool with a pattern, a cut inside, a moved tool; revolves
full, quarter both ways, symmetric and a cut; splits by a plane, both pieces, and by a body inside and outside). The
captures of `tests/orca_sized.py` followed their variables: a circular count 4 to 3 and angle 90 to 360, a grid of 3
by 2 to 2 by 3 with the spacing over the extent, a count to both sides 5 to 4 to 3 (the copies as Fusion places them),
a revolve angle 90 to 180 (volume twice), and a Move's angle and a tool's length. Three fixtures of patterns to both
sides (`rpattern_symmetric_odd`, `rpattern_symmetric_extent`, `cpattern_symmetric_part`) are written by hand, as
their `_comment` says; their volumes are worked out from the copies that land on the part. Orca builds them with
those volumes (7849.2, 7849.2, 7749.6). A Move by -90 degrees about the reversed axis gave the same body and centre
of mass as the +90 degree Move, also after the angle variable changed to 60; a repeated hole whose place a size
moved kept its place (146361.8, then 169401.8 at a wider box, both as worked out).

Checked with OrcaSlicer 2.5.1 on 2026-11-15: 28 fixtures (plates, rings, slots, cuts, intersect, start offsets, two
planes, flipped and sign-disagreeing extrudes, Y up, a linked component, simple, blind, counterbore, countersink and
three point holes) built with the capture's box and volume; the box and plate graphs followed variable changes.

Extents, checked with OrcaSlicer 2.5.1 on 2026-11-16: the captures of `tests/orca_extents.py` and the fixture
`extrude_to_plane` built with the box and volume worked out, and followed their variables: a post up to a plate's top
face plus 5 mm (8500, then 16500 with the plate's height from 10 to 20), a post up to an offset plane (8500, then
9500 with the plane from 15 to 25), a rod to two planes (1570.8, then 2356.2), a boss from a face (8500), a face as
the outline (12000), a shrinking block (7485.3), a rod with a taper size up and down (2620.2, then 2874.8 at -5
degrees), tapered symmetric and two sided rods (5240.4, 4123.3), a tapered slot (3199.1) and a tapered round cut
(7459.0).
