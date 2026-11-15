# Recipe gaps

A step the copy cannot hold is left out of the recipe and recorded as a gap. This page describes the gaps file the
add-in writes next to the recipe. The format is published by the Paramability app as `paramability.recipeGaps`,
version 3 (`schemas/paramability.recipeGaps.v3.schema.json` in the app repository; copies are in `tests/schema/`).
That schema is the contract: it holds every limit. Version 2 allowed more gaps (256 instead of 16). Version 3 added
`finishing`. The add-in always writes version 3 (`package/gaps_file.py`), so it needs a Paramability build that reads
version 3; an older build refuses the file and opens the part as a fixed shape. This page says what the add-in puts in
each field and why.

Code: `lib/translator/gaps/` (the records, the picked gaps, where a gap belongs, the file data, the hints), `lib/translator/walk.py` (what becomes a gap),
`lib/export_plan/reach_pass.py` and `lib/fusion_reader/read_gap_reach.py` (later steps that pick faces of a gap),
`lib/package/gaps_file.py` (the file), `lib/package/manifest.py` (the package version).

## When a step becomes a gap

The item loop (`walk_items`) has two outcomes for an item it cannot copy: stop the copy, or leave the item out. It
leaves out when the effect stays on the body and the rest of the timeline still reads right:

- a step type with no handler that changes the part (`StepType.unsupported`, or "Steps of type X are not copied
  yet"): coil and the like. A step that lists no body counts only when the reader saw the part
  change (`target_changed` true); when it cannot tell, the copy stops;
- a handler that answers a `Refusal` (an extrude with a taper on a face, a revolve axis it cannot use, a Combine whose
  tool cannot be built, a pattern whose sources it cannot repeat);
- a step that reaches into another component (`foreign` records in its data);
- a step that picks faces of a gap (see "Later steps that pick faces of a gap"), and a pattern or mirror of a gap;
- an extrude join whose material meets only material of earlier gaps of its walk (`faces/floating.py`, reason "It sits on a
  step that was left out, so it would float apart from the copy."). The app's kernel refuses a step that leaves the
  part in separate pieces, so such a join would stop the whole copy. The translator's model of the copied part (the
  placers, `follow.inside`) must hold no material on, around and inside the join, out to the size of the largest
  round or bevel written so far: the faces and a thin band round them are sampled closely, the join and that band on a
  coarse grid, and closely again wherever the box of a step of the model meets the band; a slab of the model with an
  outline corner inside the join keeps it, and so does a step of the model whose box cannot be told or whose part of
  the band would need more than 20000 points. Every written step whose material that model lacks must stay clear of the join by its
  own bounds: a sweep within its path grown by its profile and taper, a draft within its walk's slabs grown by its
  lean, each grown by the rounds and bevels written after it. Any other step that adds material (a revolve, a loft,
  an extrude up to a face), a thin or non-extrude join, or a join that needs more than 20000 sample points keeps the
  join in the copy. The gap of such a join has in `dependsOn` the gaps it sits on, from the body measured round each
  gap: those that grew the body out to the join (the body reaches it after the gap and not before), else those that
  added material with the body after them reaching it, else the latest gap that may have added material, else the
  latest gap.

Everything that leaves the body unknown still stops the copy and the part is a fixed shape: the place of the part in
the assembly, a step of another component or an assembly item that changes the part, a body that cannot be followed,
a step or its bodies that cannot be read (also a step type with no handler whose data could not be read), a step Fusion
marks as an error, a step that splits the part or makes another body (whether or not it has a handler or reaches into
another component; one that the reader saw leave the exported body as it was, `target_changed` false, is passed by
instead), a Split Body the copy cannot write as the removal of the other side (`bodies/split.py` answers a `Refusal` with
`stops`; a split that keeps the body as one piece apart from the others is copied, `bodies/split_rules.py`), a gap before the copy has written its first step (a gap needs a body to add to), a gap inside a
walk of another component's body, more than 256 gaps in one part (`gaps.stops.MAX_GAPS`, the most a gaps file holds; the gaps inside
the tool bodies count, and a tool that meets the cap stops the whole copy), and the size caps of the recipe.

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
  "version": 3,
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
  "reason": "The taper of this extrude is too steep to copy.",
  "hint": "Use a taper under 45 degrees, or draw the sloped wall in the sketch.",
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
  "trimmed": false,
  "finishing": false
}
```

| Field | What the add-in writes |
| --- | --- |
| `id` | `gap_<timeline index>`; inside a tool body the walk's id prefix comes first, the way step ids are made. The step added for the gap takes this id, so the app can tell which gaps were filled |
| `name`, `type`, `words` | The Fusion name and type of the step, and the type in plain words (`step_kinds`). A name that is empty or only spaces is the type in words |
| `reason` | The refusal sentence, at most 200 characters. For a step that picks faces of a gap, a pattern of a gap, or a Combine with a tool that failed, it names the gap or the step |
| `hint` | What to change in Fusion so the step copies, from the gap's cause (below). Left out when the cause has no useful advice |
| `after`, `before`, `list` | Where the step belongs (above) |
| `dependsOn` | Ids of earlier gaps whose faces the step picks, whose steps it repeats, or that a join left out because it would float sits on |
| `sizes` | Names of the recipe sizes the step reads: through its values, the sketches it names (unless the probe measured that the size does not move the sketch), its construction geometry and its measured references; at most 64 |
| `looseSizes` | Of those, the sizes that are loose only because of this gap: no copied step reads them. They stay in the recipe `sizes` so the missing step can use them, and the reason says they change nothing in the copy yet |
| `values` | One entry per `data.params` value: the Fusion expression (`fusion`, at most 300 characters) and, when the size table can write it, the formula of the recipe (`expr`) |
| `bodyBefore`, `bodyAfter` | Box and volume of the part around the step, moved to the recipe's coordinates (the box of the moved corners). From the item's `target_before` and `target_after` (`docs/capture-format.md`, section 2). Left out when a side was not measured. Inside a tool body only `bodyBefore` can exist |
| `data` | The item's `data` as the reader wrote it, in the capture's coordinates, trimmed to 48 KiB and 32 levels (the object itself is level 1). A number that is not finite becomes null, and so does an object or list that would hold values past level 32. Item level fields such as `body_states` never go in. The app does not read into it |
| `trimmed` | True when `data` was cut or changed |
| `finishing` | True when the step only finishes surfaces: a round (`FilletFeature`), a bevel (`ChamferFeature`), a draft (`DraftFeature`), an emboss or deboss (`EmbossFeature`), or a thread whose data says `modeled` is false (the `finishing` trait of the step kind table, read by `translator/gaps/finishing.py`; a cosmetic thread makes no gap today). Such a step changes neither the size of the part nor which bodies exist, so when only these are missing the app shows the editable copy first. Every other type is false |

Trimming goes in this order until `data` fits: free curve `samples` cut to 200 points each, loops past the first 8 of
an outline dropped, `profiles` dropped, and as a last resort `data` is left empty. When the whole file is over 1 MiB it
is written again with every `data` empty. When it still does not fit, or cannot be encoded, the part is not a recipe:
it is saved as a fixed shape with the note "The list of steps left out could not be written."

## Hints

Each gap has a cause (`gap_hints.py`), and the cause gives the hint: one short sentence per cause, from one table. A
handler names the cause with its `Refusal(..., cause=...)`; a step type with no handler names it in the step kind table
(`StepType.gap_cause`); a step that reaches into another component, a step that picks faces of a gap and a refusal
that names the gaps it depends on (a pattern of a gap) get theirs in the walk. A Combine left out because a step of
its tool body cannot be copied gets the cause of that step (`tool_walk.cannot_copy`, from the tool walk's
`TranslateResult.refusal_cause`), so a tool built with a thicken gets the thicken's hint. A refusal without a cause and
a step type without one have no hint. The wording follows the app's user guide page "Steps that do not copy yet" (chapter
"Designing in Fusion (experimental)"): when they disagree, the guide is right and the hint changes.
`tests/test_gap_hints.py` checks that every cause the translator gives has a hint and every hint is given.

## Later steps that pick faces of a gap

A round, chamfer, shell or offset of faces picks its edges and faces with measured points (`near`). When the step that
made those faces is missing from the copy, the kernel would take the nearest edge it finds and round the wrong one
without a word. So the pipeline looks again when the first translation has gaps, or stopped only because the part
holds more gaps than it may (later picking steps count as gaps until the read clears them):

1. `reach_pass.with_reach` asks Fusion (`read_gap_reach.read_reach`) which step made the faces each later picking step
   touches. It asks about the steps left out for their own reason, also inside tool bodies, and not about the steps
   left out only because they may pick faces of a gap: those are tested as picking steps. The answer is the capture's
   `reach` (`docs/capture-format.md`, section 2).
2. The capture is translated again. A step that picks faces of a gap becomes a gap itself (reason "It picks faces of
   Extrude5, which is missing from the copy.") with `dependsOn`. A gap the read did not cover (one that only this
   translation leaves out) counts as "may pick".
3. Without an answer (`read: false`, or no Fusion run, as in translator samples and fixtures) every later step that
   picks geometry becomes a gap ("It may pick faces of ..."). A step that picks nothing is copied.

A face given only by a point on it (an extrude that starts from or reaches to a face, the faces an emboss lands on) and
a face used as an outline are not such picks: the copy writes them as measured numbers or as shifts that follow sizes,
and marks the sizes it cannot follow, so they do not make a step a gap.

A mirror of the whole body after a gap gathers every step written so far, the gap's place among them, into one tool
step and mirrors that (`repeat/repeat_mirror.py`), so the gap stays one missing step inside the tool.

## Sizes

A size that only gap steps read would not be found by the copied steps and would be dropped. The audit
(`Audit.gap_reads`) finds the sizes each gap reads, and the driver keeps the ones nothing else reads as recipe sizes
with a loose reason: "Fusion uses it only in Extrude5, a step the export could not copy, so it changes nothing in the
copy yet." A size that a copied step reads too stays a plain free size, and a size that is already fixed or loose for
another reason keeps that state.

## report.json and the result window

`report.json` holds the same records under `gaps` (and `reach`) with the item verdict `leftOut` (section 6 of
`docs/capture-format.md`). The result window lists each gap as "name: reason", then "Tip: " and the hint when it has
one, under "N steps left out", with one line
saying that Paramability keeps the original shape and an unfinished copy. A parts file puts the part name first and
names its own gaps file per part.

When the copy stops (a stop reason, or more gaps than the cap), the package is still a fixed shape with the same
`refusal` (a stop that has a gap cause also carries its `hint`, which the export window shows as "Tip: ..." and the
package note repeats when it fits), and `report.json` adds `after_stop` (`translate._diagnosis`): a second walk without sizes in which every
stop is a gap and there is no cap. It holds `stopped_at` (the index of the step the copy stopped at, null for a stop
found after the walk), `items` (that walk's verdicts of the steps after it) and `steps` (`{ index, name, type, reason }`
of every step that walk could not copy, the last with `stops: true` when even that walk had to stop, as for a first
step that cannot be copied). The manifest gets a second note, "Not copied either: ...", with the names of those steps
other than the one it stopped at, so the person and an AI assistant see every failing step from one export. A parts
file puts `after_stop` in the part's record. Nothing in the package changes otherwise.

The export window warns early: under the body picker, "Likely left out of the copy:" lists the steps the first
translation leaves out for their own reason, at most three, then "and N more" (`dialog_model/left_out_preview.py`,
used by `dialog_model/stop_warning.py`). Each line is the same text as in the result window after the export: "name:
reason Tip: hint" (`export_plan/messages.left_out_line`), with the reason cut for the box and whole in the tooltip.
A copy that stops shows the hint of the stopping step too (`TranslateResult.refusal_cause`). The preview runs on the
capture the dialog read for the body (`CaptureCache`), with no size tries and no face read. A step that is a gap only
because it picks faces of another gap waits for the face read, so it is not listed and the box says "More may show
after the export." once (once for all bodies when several are picked). The log line "warning under the body picker"
gives the seconds the translation took and the seconds of the capture read behind it.
