# Adding a Fusion step type

This guide is for a developer who wants the export to copy one more kind of Fusion timeline step (for example a
modeled thread, a loft or a sweep). Read `docs/capture-format.md` sections 1 and 5 first. The Emboss
step (`read_emboss.py`, `emboss.py`, `tests/test_translate_emboss.py`) is a small worked example of every part below,
and of a step that reuses another handler.

## What a new step type touches

1. One entry in the step kind table, `ParamabilityExport/lib/translator/step_kinds.py`.
2. One reader pair in a `lib/fusion_reader/read_*.py` module, registered in that module's `READERS` dict.
3. One handler function in a `lib/translator/` module.
4. When the step writes a recipe kind the translator does not write yet: one `RecipeKind` entry in the same table,
   plus the recipe schema copy in `tests/schema/` and support for the kind in the Paramability app.
5. Tests: a capture fixture, handler tests, and a hand test entry for every new Fusion call.
6. The README limits list and `docs/capture-format.md` section 5, where the reader data is described.

Nothing else holds a list of step types. `tests/test_step_kinds.py` fails when a type name or a list of recipe kinds
shows up in another module, when a table entry names a handler that does not exist, and when a reader registers a
type that the table does not give to that reader module.

## 1. The table entry

```python
StepType("EmbossFeature", "emboss", reader="read_emboss", handler="emboss:handle", sketches=(PROFILES,)),
```

- `name`: the capture `type`, the Fusion object type name (`objectType` after the last `::`).
- `words`: the type in plain words. Messages use them: "Copy stopped at Loft1 (loft)".
- `role`: `MODELING` for a step that can make or change a body (the default). Sketches, construction geometry and
  assembly items have their own roles and are never copied.
- `reader`: the name of the `lib/fusion_reader` module that reads it.
- `handler`: `"module:function"` in `lib/translator`. Leave it out while the step cannot be copied; then give
  `unsupported`, the plain reason the copy stops at it. Once a handler exists, drop `unsupported`: the handler gives
  its own reasons.
- `sketches`: the sketch records in the step data that the size probe can follow (`PROFILES`, `AXIS`, `HOLE_POINTS`).
  The probe (`lib/probe/plan.py`) tries other size values only for sketches it can follow. A sketch token anywhere
  else in the data leaves that sketch unfollowed for every step that uses it, so its sizes end up loose. Name a
  record only when the probe fits it the same way it fits extrude profiles, revolve axes or hole points.

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

A handler is `handle(item, ctx) -> StepResult | Refusal` (`lib/translator/result.py`).

- `StepResult`: the recipe steps the item writes, in order. `out.add(step, placers=..., picks=..., repeatable=...)`
  writes one step; `StepResult.of(steps)` makes a result of plain steps. An empty result means the item makes no step
  on purpose (a cosmetic thread); its notes become the verdict note.
- `placers`: placer makers (`lib/translator/placer_makers.py`). Without one, a later round, chamfer or offset that
  picks a face of this step cannot follow sizes, so it marks every size written so far. A maker builds placers
  (`lib/translator/placer.py`) once the step has its id: `place(p, edge)` places a measured point on the step's faces,
  `material_at(p)` says whether the step adds or removes material at a point. Add a maker class when the existing
  slab, shell, moved faces and copies makers do not describe the new faces. A step that leaves material whose faces
  the copy cannot place (a thin wall, `thin_wall.ThinWall`) gives a placer whose `place` returns None and whose
  `material_at` answers for the material; it sets `opaque = True`, so a step on another part's sketch (`meets_part`)
  says it cannot check that it still meets the material.
- `picks`: for a round or bevel, the measured edge points, so a later pattern or mirror can copy them.
- `repeatable=False`: Fusion recomputes the step for each copy of a pattern (it reaches to a face or through the
  part), so patterns and mirrors refuse it as a source.
- `Refusal(reason)`: the item cannot be copied. The reason is one plain sentence for a hobbyist. The walk stops there
  and the part is saved as a fixed shape.

A step whose result is another step in other words can hand its item to that step's handler. Emboss on a flat face is
an extrude that starts on the face, so `emboss.handle` checks what the copy relies on, builds the data of an extrude
(`start`, `side_one`, `params` under the extrude's field paths such as `side_one.distance`) and returns
`extrude.handle(dict(item, data=built), ctx)`. Keep the item's `index` and `name`, and pass the capture's `profiles`
list as it is: the size probe's motion keys (`<item>/p<profile>/...`) count profiles by their place in that list. The
walk still lists the original item as the copied one, so the end of walk audit reads the original `data.params` and
sketches. A value the other handler asks for under another path is mapped back with
`values.handled(ctx, item, "depth", same_as="side_one.distance")`. A key that only the new step needs (a fixed direction of travel, for instance) goes into the other handler as
an optional field of its data, and must not change what that handler writes without it.

A step that takes sketch outlines checks each profile record with `loops.outline_refusal` (sketch text that could not
be read, a flat face or an unknown entity is not an outline) and gets its loops from `loops.profile_loops`. Its reader
reads them with `read_sketch.read_outlines(raw, ctx)`, which gives the profile records and one area per record: a
sketch text becomes one record per outer outline, so the list can be longer than the feature's own list of profiles.
Records are expanded in the reader, never in the handler, so the position of a profile in `data.profiles` (the key of
its motion values) is the same in the capture, the probe and the translator. A free curve (a spline) is a `kind:
other` curve with dense `samples`, which `loops.loop_of` fits with spline segments (`spline_fit.py`); a sketch that
holds free curves or text is not followed by the size probe, so the sizes behind it stay loose or are left out.

Write every value through `lib/translator/values.py`: `values.quantity` turns a Fusion expression into a formula of
the sizes, with the right dimension and sign rules, or writes it as a number and records why. Points, faces and planes
that later steps or this step pick go through `lib/translator/follow.py`.

A handler reports what it cannot follow in one way: `ctx.doubt(names, why)`. It says that a value is written as its
number although the sizes `names` move it in Fusion. The export then keeps those sizes free and marks them "may give
unexpected results" with the reason, or leaves them out of the sizes with the reason when no formula reads them. Use
`ctx.note(text)` for a remark on the step (a value Fusion stored two ways, a setting the copy does not keep). Both go
into the handler's StepResult, so they count only when its steps are written. A step of another body, kept for a
later Combine, counts only once the Combine joins it.

The walk runs a handler many times per export (once per pass, with other size tables), so a handler must not keep
state outside `ctx`. Work that depends on the capture alone can be kept in `ctx.cache` under the module name.

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
- `tests/test_step_kinds.py` keeps the table and the readers in step.

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
- A step type that was listed as unsupported can be the example of a stopping step in older tests (the stop dialog,
  the stop warning, the capture reader walk). When it becomes copyable those tests need another example type.
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
