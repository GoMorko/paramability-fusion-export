# Adding a Fusion step type

This guide is for a developer who wants the export to copy one more kind of Fusion timeline step (for example a
modeled thread). Read `docs/capture-format.md` sections 1 and 5 first. The Emboss
step (`read_emboss.py`, `extrude/emboss.py`, `tests/test_translate_emboss.py`) is a small worked example of every part below,
and of a step that reuses another handler. The sweep handler (`sweep/step.py`, the `sweep_*.py` modules next to it and the `paths/` package) is a second example
of that.

## What a new step type touches

1. One entry in the step kind table, `ParamabilityExport/lib/capture_model/step_kinds.py`.
2. One reader pair in a `lib/fusion_reader/read_*.py` module, registered in that module's `READERS` dict.
3. One handler function in a `lib/translator/` module, in the folder of its family (`extrude/`, `finishes/`, `bodies/` and so on),
   registered in the translator's `HANDLERS` map (`lib/translator/handlers.py`).
4. When the step writes a recipe kind the translator does not write yet: one `RecipeKind` entry in the same table,
   plus the recipe schema copy in `tests/schema/` and support for the kind in the Paramability app.
5. Tests: a capture fixture, handler tests, and a hand test entry for every new Fusion call.
6. The README limits list and `docs/capture-format.md` section 5, where the reader data is described.

Nothing else holds a list of step types. `tests/test_step_kinds.py` fails when a type name or a list of recipe kinds
shows up in another module, when a reader registers a type that the table does not give to that reader module, when
the handler map registers a type that is not a modeling type of the table, and when a modeling type has neither a
handler nor an `unsupported` reason.

## 1. The table entry

```python
StepType("EmbossFeature", "emboss", reader="read_emboss", sketches=(PROFILES, OUTLINE_FACE)),
```

- `name`: the capture `type`, the Fusion object type name (`objectType` after the last `::`).
- `words`: the type in plain words. Messages use them: "Copy stopped at Loft1 (loft)".
- `role`: `MODELING` for a step that can make or change a body (the default). Sketches, construction geometry and
  assembly items have their own roles and are never copied.
- `reader`: the name of the `lib/fusion_reader` module that reads it.
- `unsupported`: while the step has no handler, the plain reason the step is left out of the copy (it becomes the
  gap's reason). Once a handler exists, drop `unsupported`: the handler gives its own reasons.
- `sketches`: the sketch records in the step data that the size probe can follow (`PROFILES`, `AXIS`, `HOLE_POINTS`, `PATH`),
  and `OUTLINE_FACE` when the probe reads a flat face the step uses as its outline.
  The probe (`lib/probe/plan/`) tries other size values only for sketches it can follow. A sketch token anywhere
  else in the data leaves that sketch unfollowed for every step that uses it, so its sizes end up loose. Name a
  record only when the probe fits it the same way it fits extrude profiles, revolve axes or hole points.
- `repeats_sources`: for a pattern or mirror whose data names the items it repeats (`data.sources`); a round or
  chamfer checks it to see whether a later step repeats its edges.
- `finishing`: `FINISHING_ALWAYS` when a missing step of this type only finishes surfaces (a round, a bevel, a draft, an
  emboss), or `FINISHING_UNMODELED` for a thread whose data says it is not modeled. It sets the gap's `finishing` flag,
  which lets the app show the copy as the part when only such steps are missing. Leave it out for a step that can
  change the size of the part.

A step that writes a recipe kind the table does not have needs a `RecipeKind` too: the recipe version that brought
the kind, the paths to its points and directions (so `place.place` can move the part into the assembly), and how
patterns, mirrors and combines treat it (`repeat`, `repeats`, `combine_tool`, `always_cuts`). A kind without a
`repeat` value is refused as the source of a pattern or mirror, which is safe.

## 2. The reader

The reader is a pair `(before, after)` in the reader module's `READERS` dict, keyed by the capture type:

```python
READERS = {"EmbossFeature": (emboss_before, emboss_after)}
```

`before(feature, ctx)` runs with the marker just before the step and returns the step's `data` dict. `after(feature,
ctx, data)` runs with the marker just after it and returns more keys for `data` (measured faces, end points). Either
may be None.

The capture must be plain data: dicts, lists, strings, numbers, booleans and null, in mm and degrees, in the target
component's coordinates (`docs/capture-format.md` section 1). The translator runs without Fusion, in tests and on
saved `report.json` files, so it can only use what the reader wrote down. Read every value the handler needs, and
measure what Fusion builds where a stored flag could be wrong (an end face, a side cylinder), so the handler can check
the two against each other.

- Wrap each Fusion call in `geo.safe` (`read_geometry.py`). A member that cannot be read becomes null or `"other"`,
  never a guess; the handler refuses it.
- Mark inputs that belong to another component with `mark_foreign`, so the walk refuses the step. A flat face or plane
  of another component that the translator can follow carries a measured `ref` (`ref_motion.bring_in` turns it into
  an `assembly` record, `ref_motion.plane_shift` and `axis_moves` give its move as a formula); see
  `docs/capture-format.md`, "Measured references".
- Read the parameters behind each value into `data.params` (see "Parameters behind values" in
  `docs/capture-format.md`). The size table and the end of walk audit read them.
- A reader that raises leaves `{"read_error": ...}` as the data; the walk refuses the step.

## 3. The handler

```python
def handle(item, ctx):
    data = item.get("data") or {}
    if data.get("kind") == "other":
        return Refusal("This emboss works in a way that is not copied yet.")
    out = StepResult()
    out.add({"kind": "extrude", ...}, placers=[SlabMaker(...)], repeatable=True)
    return out
```

A handler is `handle(item, ctx) -> StepResult | Refusal` (`lib/translator/result.py`). Register it under the capture
type in `lib/translator/handlers.py` (`"EmbossFeature": emboss.handle`); the walk looks handlers up there.

- `StepResult`: the recipe steps the item writes, in order. `out.add(step, placers=..., picks=..., repeatable=...)`
  writes one step; `StepResult.of(steps)` makes a result of plain steps. An empty result means the item makes no step
  on purpose (a cosmetic thread); its notes become the verdict note.
- `placers`: placer makers (`lib/translator/faces/placer_makers.py`). Without one, a later round, chamfer or offset that
  picks a face of this step cannot follow sizes, so it marks every size written so far. A maker builds placers
  (`lib/translator/faces/placer.py`) once the step has its id: `place(p, edge)` places a measured point on the step's faces,
  `material_at(p)` says whether the step adds or removes material at a point. Add a maker class when the existing
  slab, shell, moved faces and copies makers do not describe the new faces. A step that leaves material whose faces
  the copy cannot place (a thin wall, `thin_wall.ThinWall`) gives a placer whose `place` returns None and whose
  `material_at` answers for the material; it sets `opaque = True`, so a step on another part's sketch (`meets_part`)
  says it cannot check that it still meets the material. A sweep or loft gives `EndCapsMaker`
  (`lib/translator/faces/end_caps.py`): its start and end faces are named by a later pick of all their edges, and any other
  pick on them keeps its points and marks the sizes the step reads.
- `picks`: for a round or bevel, the measured edge points, so a later pattern or mirror can copy them.
- `repeatable=False`: Fusion recomputes the step for each copy of a pattern (it reaches to a face or through the
  part), so patterns and mirrors refuse it as a source.
- `Refusal(reason)`: the item cannot be copied. The reason is one plain sentence for a hobbyist, at most 200
  characters, since it is the reason of the gap and the app shows it. The walk leaves the item out and goes on (a gap,
  `docs/recipe-gaps.md`); only a refusal before the copy has written a first step, or in a walk of another
  component's body, stops the copy and leaves the part a fixed shape. A refusal that comes from earlier gaps (a step
  that repeats or picks what a gap made) is `Refusal(reason, depends_on=[gap ids])`; `ctx.gap_of(index)` gives the gap
  of an earlier item. Doubts and notes a handler recorded before it refused are dropped with the
  item, so a step that is not written fixes no size.

A step whose result is another step in other words can hand its item to that step's handler. Emboss on a flat face is
an extrude that starts on the face, so `emboss.handle` checks what the copy relies on, builds the data of an extrude
(`start`, `side_one`, `params` under the extrude's field paths such as `side_one.distance`) and returns
`extrude.handle(dict(item, data=built), ctx)`. Keep the item's `index` and `name`, and pass the capture's `profiles`
list as it is: the size probe's motion keys (`<item>/p<profile>/...`) count profiles by their place in that list. The
walk still lists the original item as the copied one, so the end of walk audit reads the original `data.params` and
sketches. A value the other handler asks for under another path is mapped back with
`values.handled(ctx, item, "depth", same_as="side_one.distance")`. A key that only the new step needs (a fixed direction of travel, for instance) goes into the other handler as
an optional field of its data, and must not change what that handler writes without it.

A sweep hands over in two ways (`sweep/step.py`). `paths.plan` orders the path and names it. A straight path builds the data
of an extrude (`start` on the profile plane, one `side_one` distance as long as the path, no taper) and returns
`extrude.handle(...)`, so the sweep gets the extrude's slab placer and later rounds follow sizes. One arc or a full
circle builds the data of a revolve (the arc's axis, the arc's angle, the direction the start face looks) and returns
`revolve.step.handle(...)`. Only a chain of lines, arcs and free curves, or a 3D chain with tangent arcs, is written as a
`sweep` step of its own, with the path as measured. The handler checks every setting it does not follow (twist,
taper, rail, part of the path, a path that is not square to the outline) before it hands over, and refuses with a
plain reason. A size the written path cannot follow is marked on the sweep's side, whichever form is written: the
sizes behind the path sketch (its plane, face or projected curves), behind a plane that moves the outline away from
the path, and behind an outline that could reach past the tightest bend (`sweep/sweep_reach.py`).

The sweep code is split by concern. `sweep/step.py` is the handler. `sweep_settings` (twist, taper, direction, rail),
`sweep_outline`, `sweep_volume` (volume checks), `sweep_ends` (the made end face against the path end), `sweep_marks` (sizes the copy cannot follow), `sweep_rules` (the path's
rules held over the size ranges) and `sweep_write` (the extrude, revolve or `sweep` step written) each hold one part, and
`sweep_limits` holds the refusal texts. `loft/step.py` is the loft handler; `loft_volume` pairs the corners of two
straight outlines as the kernel does, for a volume check of a new body. The path side follows the same pattern: `paths/paths.py` orders and classifies the path,
`path_curves` (curve geometry, chaining), `path_checks` (the app's limits as refusals), `path_writing` (arc, circle, flat
and corners forms), `path_closed` (closed chains), `path_rebuilt` (a path read back from numbers, for the range rules),
`path_model` (`PathOptions`, `PathPlan`) and `path_limits` (tolerances, caps, refusal texts). A new refusal text goes into
the limits module of its side.

A step that takes sketch outlines checks each profile record with `loops.outline_refusal` (sketch text that could not
be read, a flat face or an unknown entity is not an outline) and gets its loops from `loops.profile_loops`. Only the
extrude takes a flat face as its outline, through `face_outline.prepare`, which marks the sizes the face may follow. Its reader
reads them with `read_sketch.read_outlines(raw, ctx)`, which gives the profile records and one area per record: a
sketch text becomes one record per outer outline, so the list can be longer than the feature's own list of profiles.
Records are expanded in the reader, never in the handler, so the position of a profile in `data.profiles` (the key of
its motion values) is the same in the capture, the probe and the translator. A free curve (a spline) is a `kind:
other` curve with dense `samples`, which `loops.loop_of` fits with spline segments (`sketch/spline_fit.py`); a sketch that
holds free curves or text is not followed by the size probe, so the sizes behind it stay loose or are left out.

Write every value through `lib/translator/values.py`: `values.quantity` turns a Fusion expression into a formula of
the sizes, with the right dimension and sign rules, or writes it as a number and records why. Points, faces and planes
that later steps or this step pick go through `lib/translator/faces/follow.py`.

A handler reports what it cannot follow in one way: `ctx.doubt(names, why)`. It says that a value is written as its
number although the sizes `names` move it in Fusion. The export then keeps those sizes free and marks them "may give
unexpected results" with the reason, or leaves them out of the sizes with the reason when no formula reads them. Use
`ctx.note(text)` for a remark on the step (a value Fusion stored two ways, a setting the copy does not keep). Both go
into the handler's StepResult, so they count only when its steps are written. A step of another body, kept for a
later Combine, counts only once the Combine joins it.

The walk runs a handler many times per export (once per pass, with other size tables), so a handler must not keep
state outside `ctx`. Work that depends on the capture alone can be kept in `ctx.cache` under the module name.

### Inside a tool body

A Combine takes tool bodies, and a tool that is more than steps that add material is written as one `toolBody` step
that holds the steps that made the tool (`features`). A handler does not need to know about this: the tool is walked
on its own (`lib/translator/combine/tool_walk.py`) by the same item loop, in a child context (`Context.child`) whose
`target` is the tool body. So a handler that tests `ctx.is_target(body)`, reads `data["target_box_before"]` and
`data["volume_before"]`, and writes steps with `out.add(...)` works unchanged for a tool.

- Which handlers see the tool as their target: all of them. The walk of a tool starts with the items that made the tool
  (`tool_walk.chain_of`), in the component that holds it. The reader gave the items of the target's component their
  data; for another component's items (`helper_of`) the second pass in `lib/fusion_reader/helper_pass.py` read them in
  that component's frame. For the numbers measured on the body itself (box and volume before and after), a walk takes
  `item["body_states"][token]` (`bodies.body_states.seen_on`), not the exported body's fields.
- What a handler may not assume: that the part is its target's whole world. A child walk cannot see the part. A step
  that reaches to a face of the part has no place for it in the child; `tool_walk.on_part` works such steps out again
  against the part when a Combine writes them one by one, and a tool step that holds them marks the sizes it cannot
  follow. Put every pick, plane and axis through `faces/follow.py`, as for any step, and the audit says when one is missed.
- `combine_tool` on the `RecipeKind`: the step can be one of the steps that a tool made only of such steps is written
  with, one by one, onto the part (`combine.step.adds_only`). Set it only for a kind that adds material and nothing else
  (extrude and revolve do). A kind without it is still copied inside a `toolBody`; it just stops the flat form.
- `RecipeKind.in_tool`: False for a kind the recipe keeps out of a tool body's `features` (thread, coil, skin, bevel
  gear). A Combine or pattern whose tool walk wrote such a step refuses with a hint (`step_walk.outside_tool`); the coil
  is written onto the part when it is the only step of its tool.
- `RecipeKind.repeat`: `toolBody` is `SOLID`, so a pattern repeats a tool. A step inside a tool is a `features` entry:
  walk steps with `step_walk.all_steps`, never `ctx.steps` alone, when code must see every step (the version, the
  `place.place` of a body into the assembly, the audit and the copy limits do). A new `RecipeKind` with `positions` and
  `directions` is moved inside a tool by `place.place` the same way.
- Ids: a step in a tool keeps the id the child gave it, built from the Combine's index and the tool's place in the
  list, so one item written twice (a paste, or a tool that two Combines use) has distinct ids. `Context.add_steps`
  keeps an id a handler set. A step that Fusion made twice from one item, such as a paste, has its steps in
  `ctx.steps_of(index)`, and the audit reads all of them through `written_for`.
- Placers: a tool step is one placer (`tool_placer.ToolPlacer`) for the steps after it. Its slabs are copies owned by
  the tool step, so `follow` never names a step inside it. A kind whose faces a later pick must follow needs a placer
  maker, as for any step; a tool made of such steps hands them over through `ToolMaker`.
- The reader's limits: `tool_items.MAX_ITEMS` steps, `MAX_TOOLS` tool bodies and `MAX_DEPTH` levels for the second
  pass, and `tool_walk.MAX_DEPTH` for nesting in the translator. A step type that makes bodies (a paste, a pattern of
  bodies: `makes_bodies` on the step type) or moves them (`moves_bodies`) must say so, or the walk skips it when it
  names no body of its target.
- A step type that cannot be copied inside a tool gives `unsupported` as usual, and the Combine becomes one gap whose
  reason names it: "The tool body Body3 cannot be copied: Thicken1 (thicken): ...". The gaps inside the tool are dropped
  with the failed tool. A tool that is written but has a gap is always a `toolBody` step, never written one by one
  onto the part (`combine.step._writes_flat`).

### What a gap needs from a step type

A step that cannot be copied is kept as a gap, with the data the reader has for it, so that the missing step can be
added later (by hand or by an AI assistant connected to Paramability) from the gap alone. What makes a gap useful:

- A reader, even a small one. A type with no reader gives `"data": {}`, and the gap then has only the name, the
  reason and the measured box and volume of the part around the step (`target_before` and `target_after`, written for
  every item). Read the member values a person would need to redo the step: extents, distances, angles, operation, the
  inputs.
- `data.params` for every value that a user parameter can drive (see "Parameters behind values" in
  `docs/capture-format.md`). The gap lists them as `values` with the Fusion expression and the formula of the recipe,
  and the audit finds the sizes the step reads (`sizes`, `looseSizes` of the gap). A size that only this step reads
  is kept as a size and marked, so the missing step can use it.
- Sketches by token where the step uses them (`sketches=` in the table entry), so the sizes behind those sketches are
  found.
- Picks as records the capture already uses (`edges` lists with `token` or `points`, `faces` lists with `token`,
  `point` or `loops`), so `gap_picks.pick_records` sees them: a later round or shell that picks faces of a gap is then left
  out too, instead of landing on another edge of the copy. A face given only by a `face_point` is not a pick. A list of faces the step made, or of bodies, goes under one of the names
  `gap_picks.pick_records` skips (the `_NOT_PICKS` list in `lib/capture_model/gap_picks.py`); add a new name there so it is not
  taken for a pick.
- Marked `foreign` records for inputs of another component, as for a copied step. A step with such an input is left
  out as a gap, with the reason of `ref_motion.why_foreign` when there is one.
- Plain data in millimetres and degrees, in the component's coordinates (the gap file gives `toRecipe` to turn them).
  The file keeps at most 48 KiB of `data` per gap: free curve `samples` and extra loops are cut first, so avoid
  writing more than the step needs.
- `makes_bodies` and `moves_bodies` on the table entry when the type makes or moves bodies, as for a copied step.

## 4. What protects a new handler

- The end of walk audit (`lib/translator/audit.py`) runs after every translation. Every free size that a copied step
  reads (through its `data.params`, the sketches it draws on, the construction geometry it uses) must end read by a
  written formula, or marked with a reason. It checks each value of `data.params` on its own: `values.quantity`,
  `values.pin` and `values.handled` record that the handler dealt with that path, and a path that reads a free size and
  was never asked for makes the size loose ("Emboss1 reads it, and the copy does not follow it"), even when another
  value of the step follows the same size. A value the step kind or its settings do not use (a tip angle of a
  through hole, the second direction of a pattern with one copy) is declared with `values.handled`; a value the copy
  writes as a fixed number (a taper of zero) is declared with `values.pin`. So a forgotten value gives a warning, not
  a wrong part.
- `tests/test_follow_or_flag.py` translates every capture fixture with every user parameter ticked and checks the
  same rule from the outside: each parameter a copied step reads is followed, loose or dropped with a reason, and no
  written formula can reach zero inside the size ranges. A new fixture is picked up on its own, but only when it has
  `parameters.user` and the model parameters behind the step's `data.params`: give the fixture of a new step type
  user parameters that drive its sizes.
- `tests/test_step_kinds.py` keeps the table, the readers and the handler map in step.

## 5. Tests to write

- A capture fixture in `tests/fixtures/captures/` (by hand, or saved from `report.json` of a real design), with the
  box and volume from `scripts/fixture_geometry.py` (or a null volume where the script cannot model the step). The
  script knows the step types it models by name: give a new type a branch in its `evaluate` (an emboss is turned into
  the extrude it equals), or the fixture keeps a null volume and an unchanged box. Run it as
  `python3 scripts/fixture_geometry.py <fixture name> --write`.
- Handler tests in a `tests/test_translate_<name>.py`: the recipe the fixture gives, checked against the schema
  (`assert_schema_ok`); one test per refusal branch; one test with a size table that shows the values follow the
  sizes, and one that shows a value that cannot follow marks its size with a reason. Assert outcomes (recipe values,
  verdicts, loose and dropped names), not wording.
- A step type that was listed as unsupported can be the example of a left out step in older tests (the gap tests,
  the result window, the capture reader walk). When it becomes copyable those tests need another example type.
- A new refusal branch is a gap: a test that the walk leaves the item out, with its `after` and `before`, and that the
  later steps are copied. A step that picks faces of the new step is covered by the reach tests in
  `tests/test_translate_gaps.py`.
- Reader tests in `tests/test_capture_reader*.py` with the fakes, for each member the reader reads and for an
  unreadable one.

A new feature of an existing step type (the thin wall of an extrude) follows the same parts: the reader adds keys
under the existing type, the handler checks them before it writes anything, and `scripts/fixture_geometry.py` models
them when the fixture needs a volume (it only has a branch per step type, and reads the new keys inside it).

## 6. Hand tests

The reader is the only code that talks to Fusion, and no tool runs it. Every new `adsk` call goes into
`docs/hand-tests.md`, in the "Capture reader calls to watch" part: the member, what the reader expects it to return,
and what to look for in `report.json`. Add a design that shows the step, with what the part must look like in
Paramability: to section 7 for a plain step, or to a numbered section of its own when the step has several cases to
try (Emboss has section 10).
