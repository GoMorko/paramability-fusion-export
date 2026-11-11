# Recipe gaps

A step the copy cannot hold is left out of the recipe and recorded as a gap. This page describes the gaps file the
add-in writes next to the recipe. The format is published by the Paramability app as `paramability.recipeGaps`,
version 1 (`schemas/paramability.recipeGaps.v1.schema.json` in the app repository; a copy is in `tests/schema/`). That
schema is the contract: it holds every limit. This page says what the add-in puts in each field and why.

Code: `lib/translator/gaps.py` (the records and where a gap belongs), `lib/translator/walk.py` (what becomes a gap),
`lib/export_plan/reach_pass.py` and `lib/fusion_reader/read_gap_reach.py` (later steps that pick faces of a gap),
`lib/package/gaps_file.py` (the file), `lib/package/manifest.py` (the package version).

## When a step becomes a gap

The item loop (`walk_items`) has two outcomes for an item it cannot copy: stop the copy, or leave the item out. It
leaves out when the effect stays on the body and the rest of the timeline still reads right:

- a step type with no handler that changes the part (`StepType.unsupported`, or "Steps of type X are not copied
  yet"): sweep, loft, coil, draft and the like;
- a handler that answers a `Refusal` (an extrude with a taper on a face, a revolve axis it cannot use, a Combine whose
  tool cannot be built, a pattern whose sources it cannot repeat);
- a step that reaches into another component (`foreign` records in its data);
- a step that picks faces of a gap (see "Later steps that pick faces of a gap"), and a pattern or mirror of a gap.

Everything that leaves the body unknown still stops the copy and the part is a fixed shape: the place of the part in
the assembly, a step of another component or an assembly item that changes the part, a body that cannot be followed,
a step or its bodies that cannot be read, a step Fusion marks as an error, a step that splits the part or makes another
body, a gap before the copy has written its first step (a gap needs a body to add to), a gap inside a walk of
another component's body, more than 16 gaps in one part, and the size caps of the recipe.

A tool body of a Combine is walked by the same loop. A gap inside a tool body is kept only when the Combine writes that
tool, and the tool is then always a `toolBody` step (the gap is in its list). When the tool cannot be built (its first
step is a gap, for example) the Combine becomes one gap on its own level and the gaps inside the tool are dropped.

What a left out step would have recorded (doubts about sizes, notes) is dropped with it, so a step that is not
written never fixes a size.

## Where a gap belongs: `after`, `before`, `list`

The walk records the ids of the steps it wrote before the gap. Once the recipe is final, the gap is placed:

- `after`: the last of those ids that is still in the recipe. A step can move (a pattern of the whole body gathers
  every earlier step into a `toolBody`), so the place is worked out from the finished tree, not when the gap is seen.
- `list`: the id of the `toolBody` step whose `features` list holds `after`, or null at the top level.
- `before`: the step after `after` in the same list, or null when `after` is the last one.

The missing step goes into that list, right after `after`. A gap without a place stops the export.

## The file

`gaps.json` in a recipe package, `parts/NN/gaps.json` for a part of a `parts` package, named in the manifest by
`gaps`. A package that names a gaps file is manifest version 2, so an older reader refuses it ("made by a newer
exporter") rather than showing an unfinished copy as a finished part. A package without gaps stays version 1.
`validate_manifest` checks both rules, and refuses `gaps` on `stepOnly`, `valueRows` and on a part without a recipe.

```json
{
  "schema": "paramability.recipeGaps",
  "version": 1,
  "toRecipe": [1, 0, 0, 0, 0, -1, 0, 1, 0, 100, 50, 0],
  "gaps": [ GAP, ... ]
}
```

`toRecipe` is the move from the capture's coordinates (the component's millimetres, as Fusion stores the step's data)
to the recipe's: 12 numbers, the rows of a 3 by 3 rotation, then the offset. A point `p` of a gap's `data` is
`R * p + t` in the recipe. It folds in the part's place in the assembly and the Y up turn. The raw `data` is not
converted.

GAP:

```json
{
  "id": "gap_7",
  "name": "Extrude5",
  "type": "ExtrudeFeature",
  "words": "extrude",
  "reason": "The outline is a face of the part, with a taper.",
  "after": "extrude_3",
  "before": "round_9",
  "list": null,
  "dependsOn": [],
  "sizes": ["depth", "taper"],
  "looseSizes": ["taper"],
  "values": [{ "path": "side_one.distance", "fusion": "depth * 2", "expr": "depth * 2" }],
  "bodyBefore": { "box": { "min": [0, 0, 0], "max": [40, 20, 10] }, "volume": 8000 },
  "bodyAfter": { "box": { "min": [0, 0, 0], "max": [40, 20, 22] }, "volume": 8900 },
  "data": { },
  "trimmed": false
}
```

| Field | What the add-in writes |
| --- | --- |
| `id` | `gap_<timeline index>`; inside a tool body the walk's id prefix comes first, the way step ids are made. The step added for the gap takes this id, so the app can tell which gaps were filled |
| `name`, `type`, `words` | The Fusion name and type of the step, and the type in plain words (`step_kinds`) |
| `reason` | The refusal sentence, at most 200 characters. For a step that picks faces of a gap, a pattern of a gap, or a Combine with a tool that failed, it names the gap or the step |
| `after`, `before`, `list` | Where the step belongs (above) |
| `dependsOn` | Ids of earlier gaps whose faces the step picks, or whose steps it repeats |
| `sizes` | Names of the recipe sizes the step reads: through its values, the sketches it names (unless the probe measured that the size does not move the sketch), its construction geometry and its measured references |
| `looseSizes` | Of those, the sizes that are loose only because of this gap: no copied step reads them. They stay in the recipe `sizes` so the missing step can use them, and the reason says they change nothing in the copy yet |
| `values` | One entry per `data.params` value: the Fusion expression (`fusion`, at most 300 characters) and, when the size table can write it, the formula of the recipe (`expr`) |
| `bodyBefore`, `bodyAfter` | Box and volume of the part around the step, moved to the recipe's coordinates (the box of the moved corners). From the item's `target_before` and `target_after` (`docs/capture-format.md`, section 2). Left out when a side was not measured. Inside a tool body only `bodyBefore` can exist |
| `data` | The item's `data` as the reader wrote it, in the capture's coordinates, trimmed to 48 KiB. Item level fields such as `body_states` never go in. The app does not read into it |
| `trimmed` | True when `data` was cut |

Trimming goes in this order until `data` fits: free curve `samples` cut to 200 points each, loops past the first 8 of
an outline dropped, `profiles` dropped, and as a last resort `data` is left empty. When the whole file is over 1 MiB it
is written again with every `data` empty. When it still does not fit, or cannot be encoded, the part is not a recipe:
it is saved as a fixed shape with the note "The list of steps left out could not be written."

## Later steps that pick faces of a gap

A round, chamfer, shell, offset of faces or "up to face" extent picks its edges and faces with measured points. When
the step that made those faces is missing from the copy, the kernel would take the nearest edge it finds and round
the wrong one without a word. So the pipeline looks again when the first translation has gaps:

1. `reach_pass.with_reach` asks Fusion (`read_gap_reach.read_reach`) which step made the faces each later picking step
   touches. The answer is the capture's `reach` (`docs/capture-format.md`, section 2).
2. The capture is translated again. A step that picks faces of a gap becomes a gap itself (reason "It picks faces of
   Extrude5, which is missing from the copy.") with `dependsOn`.
3. Without an answer (`read: false`, or no Fusion run, as in translator samples and fixtures) every later step that
   picks geometry becomes a gap ("It may pick faces of ..."). A step that picks nothing is copied.

A mirror of bodies after a gap is left out, since it repeats the steps written so far and checks them against the
plane.

## Sizes

A size that only gap steps read would not be found by the copied steps and would be dropped. The audit
(`Audit.gap_reads`) finds the sizes each gap reads, and the driver keeps the ones nothing else reads as recipe sizes
with a loose reason: "Fusion uses it only in Extrude5, a step the export could not copy, so it changes nothing in the
copy yet." A size that a copied step reads too stays a plain free size, and a size that is already fixed or loose for
another reason keeps that state.

## report.json and the result window

`report.json` holds the same records under `gaps` (and `reach`) with the item verdict `leftOut` (section 6 of
`docs/capture-format.md`). The result window lists each gap as "name: reason" under "N steps left out", with one line
saying that Paramability keeps the original shape and an unfinished copy. A parts file puts the part name first and
names its own gaps file per part.
