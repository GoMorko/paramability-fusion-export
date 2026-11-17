# The Paramability export add-in for Fusion: a guide for debugging

## 0. About this guide

This guide explains the Fusion add-in "Paramability export". The add-in saves a Fusion body as a `.paramability`
file. Paramability opens that file as a part. The part has sizes that come from the Fusion user parameters.

The guide is for a developer who knows Fusion as a user and knows Python. The developer did not write the add-in. The
goal is that the developer can find and fix a problem alone.

The guide describes the code as it is on `main` of the add-in repository, version 0.14.0.
The layout of the code is in section 2. The short rules of the layout are in `docs/development.md`, part "Code layout".

What version 0.12.0 added, with the sections that explain it:

- A readable label for each size, made from the comment or from the name of the parameter (1.3, "The label of a size").
- Formulas of plain numbers (`3 * 0.4 mm`, `3/8 in`) that can be ticked as sizes, and more counts that follow their
  sizes (1.3 and 1.9.6).
- Modelled threads and coils that copy as recipe steps (3.12 and 3.13). Tapped holes with a modelled thread are read
  from `tappedHoleInfo` and the hidden thread feature of the hole, and checked against the faces of the thread, but
  this is unproven until hand check TD2 (3.12). Symmetric revolves turn twice their angle (3.14). Holes that end at a face or at a body copy as blind holes
  (3.12).
- More causes and hints for steps that do not copy, also for a step that stops the copy (1.9.3).
- An early list, in the export dialog, of the steps that the copy will probably leave out (1.2).
- A time limit for the size tries (1.8, "The time limit of the tries").
- Ranges that stop where the part comes apart into pieces, where an outline would cross itself or where a hole would
  leave its outline (1.8 and 3.2).
- A Split Body by a solid body that no longer needs the answer of the reader for every piece (3.4).
- Sizes that are marked when they also move a part that stays a fixed shape in the same file (1.10).
- A note when a part follows the sizes of a component that is not in the file (1.10).

What this version writes:

- recipe version 17 when a shell needs it, else 16 when a sweep needs it, else a lower version;
- a gaps file of version 3 always (up to 256 left-out steps, each with a `finishing` flag). Version 0.11.1 wrote version 1 for up to 16 steps and version 2 for more;
- a `report.json` with a `timing` block and a `health` block, and also the record of the time limit
  (`probe.time_limit`), the count of pieces in the tries (`pieces`) and a `hint` in `refusal`;
- recipe sizes with a readable `label` (the manifest `parameters` list keeps the Fusion name as the label).

Names of files, functions and fields are in backticks. Line numbers change often, so the guide names functions and not
lines. In commands, `<add-in repo>` is the folder of the add-in repository.

Where to find the code:

| What | Where |
| --- | --- |
| The add-in | `<add-in repo>/ParamabilityExport/` (the folder you load in Fusion) |
| The add-in tests | `<add-in repo>/tests/` |
| The add-in scripts | `<add-in repo>/scripts/`: `fixture_geometry.py` (box and volume of a capture fixture), `formula_census.py` (counts how the formulas of exports translate, see 4.5) |
| The add-in docs | `README.md`, `docs/capture-format.md`, `docs/recipe-gaps.md`, `docs/hand-checks.md` (the short check before a release), `docs/hand-tests.md` (every hand test), `docs/adding-a-step-type.md`, `docs/expressions.md`, `docs/test-projects.md` (fifteen typical printing projects to build and export, to see how many kinds of projects the copy covers), `docs/user-guide.md` and `docs/limits.md` (what a user sees and what does not copy), `docs/development.md` (code layout and tests), `docs/publishing.md` |

The docs in the add-in repository are long and exact. This guide tells the story in order. When you need every
detail of one field, read `docs/capture-format.md`. When the docs and this guide do not agree, the code is right.

The guide has five parts:

1. The whole workflow, from the click in Fusion to the part in Paramability.
2. The code map: the packages, the main modules and how data flows.
3. Key ideas with small examples.
4. Debugging: `report.json`, grep, replay, tests, Fusion calls, failure patterns and checklists.
5. A glossary of the project terms.

## 1. The whole workflow

### 1.1 The big picture

The add-in has three buttons in the Utilities tab, in the panel "Paramability":

- "Export for Paramability" saves one body (or several bodies) with its modeling steps. Paramability opens it as an
  editable part with sizes. Most of this guide is about this button.
- "Export size choices" saves fixed shapes at several sets of parameter values. Paramability shows them as a
  dropdown. This button is simple: it sets the values, lets Fusion rebuild, writes one STEP file per row and puts the
  values back (`commands/ExportSizeChoices/`, `lib/design_edit/runner.py`).
- "Export for Orca (experimental)" saves one body as an OrcaSlicer 2.5 project with Design tab features. It uses the
  same reader, the same shared design layer and the same `PutBack`, but its own translator (`lib/orca_translate/`).
  `docs/orca-output.md` tells how it works.

"Export for Paramability" does these stages, in this order:

```
 click
   |
   v
 dialog: pick body, tick parameters, set ranges, up axis,
         "Faster tries", time limit of the tries, "Lighter on memory"
   |  (the dialog already reads the capture to tick parameters and to show a stop warning)
   v
 OK, choose file name
   |
   v
 1. STEP file of the body as it is now               (fusion_reader/step_export.py)
 2. capture: read the timeline into a plain dict     (fusion_reader/capture.py)
 3. size table: which parameters are sizes           (params/size_table.py)
 4. first translation, without measured sketches     (translator/, motion = OPTIMISTIC)
 5. reach read, only when steps were left out        (fusion_reader/read_gap_reach.py)
 6. size probe: set sizes to other values, rebuild,
    read sketches and places, fit formulas           (export_plan/probe_flow/, probe/)
 7. final translation with the measured motion       (translator/)
 8. put everything back: parameters, suppressed
    steps, sketches, timeline marker, then the
    end check of every timeline step                 (design_edit/, export_plan/pipeline/)
 9. package: manifest, recipe, gaps, report, STEP    (export_plan/recipe_export.py, package/)
   |
   v
 result window in Fusion
   |
   v
 Paramability opens the file: reads it, builds the recipe in its CAD kernel,
 compares it with the STEP, puts the sizes on the form
```

Stages 2 to 9 run in `run_pipeline` (`lib/export_plan/pipeline/run.py`). The pipeline talks to Fusion only through a
"port" object. The members of the port are declared in one place (`ExportPort` in `lib/export_plan/pipeline/port.py`).
The real port is `FusionPort` in `commands/ExportForParamability/export_flow.py`. The tests use a fake port
(`tests/fakes/port.py`). So the whole pipeline can run without Fusion. Stage 8 is done by one object, `PutBack`
(`lib/export_plan/pipeline/put_back.py`), that the pipeline makes at the start of the export (see 1.11).

Export of several bodies in one file has its own driver (`lib/export_plan/pipeline/parts.py`, see 1.10). It uses the
same `PutBack`, the same try runner and the same probe interface.

Two ideas are important from the start:

- The add-in never edits the design for good. It changes parameter values for a short time, moves the timeline
  marker for a short time, and sometimes turns off timeline steps for a short time. It always puts them back. If it
  cannot put something back, it tells the person.
- The add-in never guesses in silence. When it cannot copy something exactly, it writes a reason. The reason goes to
  the result window, to the manifest notes, to the gaps file or to `report.json`. Most debugging starts from such a
  reason.

### 1.2 The click and the dialog

The file `ParamabilityExport/ParamabilityExport.py` is the add-in entry. Fusion calls `run(context)` when the add-in
starts. `run` calls `commands.start()`, which adds the three buttons (`commands/panel.py`). When the add-in stops,
`stop(context)` removes the buttons and drops the add-in modules from the Python cache (`_forget_modules`). So "Stop"
and then "Run" in the Scripts and Add-Ins dialog loads the files on disk again. Use this after you change the code.

When the person clicks "Export for Paramability", Fusion calls `_on_created` in
`commands/ExportForParamability/entry.py`. It does this:

1. It gets the design (`panel.design_or_reason`). A design without history gets a short message and no dialog: the
   export needs a parametric design.
2. It asks if parts were moved by hand and the position is not captured (`export_flow.position_pending`, which reads
   `design.snapshots.hasPendingSnapshot`). If yes, the dialog shows only "Capture the position of moved parts first".
   This question comes first because reading the timeline moves the marker, and a marker move can drop such a
   pending move.
3. It reads the user parameters (`list_user_parameters`), the model parameters of the root, the design's length unit
   and the timeline marker. When the marker is not at the end, the dialog shows "Exporting the design as it is at the
   timeline marker (step 48 of 120)" (`design_edit/marker.py`, `marker_note`).
4. When the design has only one solid body, that body is picked to start with.
5. It makes a `CaptureCache`. Each time the person picks a body, the dialog reads the capture of that body (stage 2
   above) and keeps it. The export later uses the same capture when the marker did not move.
6. For the picked bodies it builds the parameter table (`size_offers`, see 1.3) and the early warning
   (`dialog_model/stop_warning.py`, see "The early warning under the body picker" below). The early warning translates
   the capture once, without sizes. When a step stops the copy, the warning says "Copy stops at Extrude9 (extrude)."
   and "The part will be saved as a fixed shape". When the copy goes on, it lists up to three steps that are "Likely
   left out of the copy". A button "Show in timeline" selects the stopping step in Fusion.
7. On OK, `export_flow.run_export` runs. It asks for the file name (`package/naming.py`: the name of the component
   that holds the bodies, else the name of the design; the root component gives the name of the design, because
   Fusion names the root "(Unsaved)" before the first save), reads the marker again, builds an
   `ExportRequest` (title, writer text, up axis, parameters, ticked names, typed ranges, marker, "Faster tries", the
   time limit of the tries) and
   runs the pipeline inside `export_common.run_guarded`.
8. The export runs only once per dialog. With "Lighter on memory" ticked, the export calls Fusion's
   `Command.beginStep`. Fusion then fires the execute event of the command again. `on_execute` in `entry.py` remembers
   that the export started, and it ignores the second event.

`run_guarded` catches every way the export can stop and shows one plain message. A cancel shows "Export cancelled.
Your parameters are back to their values." A known error (`RowBuildError`, `StepExportError`, `PackageCapError`,
`MarkerError`) shows its own message. Any other exception shows "The export stopped. Nothing was saved." with the
Python traceback, and writes the traceback to the log. In every case it puts the timeline marker back and warns about
parameters that did not go back.

The dialog itself is in `lib/fusion_ui/recipe_dialog.py`. The texts of the dialog come from `lib/dialog_model/`, which
is pure Python. The dialog holds:

- the body picker (up to 32 bodies);
- the parameter table: one row per user parameter, with a tick, the name, the value now, Min, Max and what the
  parameter becomes in Paramability;
- a details box under the table (the comment, the formula or the full reason of the row you click);
- the stop warning;
- the up axis ("Z up" or "Y up");
- the check box "Faster tries" (on to start with, see 1.8);
- the list "Stop the size tries after" (1, 5, 10, 20 or 30 minutes, 1 or 2 hours, or "No limit"; 10 minutes to start
  with, see 1.8);
- the check box "Lighter on memory" (off to start with, an experiment, see 1.11). When the person ticks it, a line under
  the box reminds them to save the design first.

#### The early warning under the body picker

Under the body picker the dialog shows a short warning about the picked body. The warning comes from one translation of
the capture that the dialog already read. This translation has no sizes, no size tries and no face read, so it is
fast. The export log gets one line with the time of the warning and the seconds that the reads of the picked bodies
took, since the reads are the slow part (`entry.py`, `_log_warning_time`). All the logic is pure Python:
`dialog_model/stop_warning.py` (`summarize` and `summarize_many`) and `dialog_model/left_out_preview.py`.

There are two cases:

1. The copy stops. The warning shows, in this order: the title ("Copy stops at Extrude9 (extrude)."), a short reason, a
   "Tip: ..." line when the cause of the stop has a hint in `gap_hints` (the same table of causes as for a gap, see
   1.9.3), and the sentence that the part will be saved as a fixed shape. `refusal_hint(result)` in
   `export_plan/recipe_export.py` gives the hint.
2. The copy goes on. The warning lists up to three steps under "Likely left out of the copy:". Each line reads
   "name: reason Tip: hint". When more steps are left out, the line "and N more." follows. When a later step may pick
   faces of a step that is left out, the line "More may show after the export." follows once. Only the face read of
   the export (1.7) decides that later step, so the early warning cannot list it.

The wording of a line is shared with the result window (`export_plan.messages.left_out_line`). So a step reads the
same before and after the export. The result of `summarize` has these keys: `hint`, `left_out` (a list of dicts
`{ index, name, reason, hint }`) and `more_may_show`. For several bodies, `summarize_many` joins the lines of each
body, with the name of the body in front, and adds "More may show after the export." once.

The dialog of Export for Orca uses the same parameter table. Its offers name their destination
(`size_offers.offers(..., destination=ORCA)`, the key `destination` of each offer). Thus the texts of the table name
Orca's Design tab and not Paramability: the reason of a tick, the line under the table for a ticked row, the title of
the status column ("In Orca", `dialog_rows.header`) and the tooltip of the up direction (`dialog_rows.up_tooltip`).

The dialog of Export for Orca has the same box under the body picker. Its warning comes from `preview(capture, up_axis)`
in `dialog_model/orca_result.py`, and `commands/ExportForOrca/entry.py` shows it through `recipe_dialog.show_stop`. The
preview makes one Orca translation of the capture, with no sizes ticked. It lists up to three steps under "Likely left
out of the copy:", in the same lines as the recipe dialog and with the same "and N more." line. The Orca translation
decides every step that it leaves out by itself, so this list is whole: `find_orca` in `left_out_preview.py` reads the
left out records of the result, and `waits_for_faces` is always false. The result has the same keys as the one of
`summarize`, with `stops` false. The preview gives None when the part is not read or when nothing is left out. A size
that you tick can change which steps the Orca copy leaves out (a round that would cost the binding of an outline), so
the list says "likely".

### 1.3 Parameters, the size table and the dependency resolver

#### What the reader gives

`lib/fusion_reader/parameters.py` reads the parameters into plain dicts. Values stay in Fusion's internal units
(cm and radians). Each user parameter has:

- `name`, `expression`, `value`, `unit`, `comment`, `is_favorite`;
- `kind`: `derived` when the expression names another parameter, calls `random()` or cannot be parsed. Else
  `length`, `angle`, `count` or `unsupported` (a unit the add-in does not convert, such as a mass). A formula of plain
  numbers has the kind of its unit: `3 * 0.4 mm`, `3/8 in` and `PI * 10 mm` are `length`, and `2 * PI` is `count`
  (`is_constant_expression` in `params/expressions/text.py`);
- `dependency_parameters` and `dependent_parameters`: Fusion's own lists of what the parameter reads and what reads it;
- `dependents`: every model parameter that reads it, directly or through other parameters, with the kind of thing that
  made the model parameter (`sketchDimension`, `feature`, `constructionPlane`, `joint` and so on), its component and
  its sketch. The reader walks this at most 2000 times per parameter.

Each model parameter has `created_by`: `{ kind, token, name, sketch, component }`. This says which sketch dimension,
feature or construction plane made it.

#### The dependency resolver

A user parameter can reach the body directly ("Extrude1 distance = Height") or through formulas
("Inner = Outer - 2 * Wall", and a sketch dimension reads "Inner"). The resolver finds both.

`lib/params/dependencies.py` builds one `Graph` per table. The graph has an edge from a parameter to each name it
reads. It takes the names from three places:

1. The names in the expression. The add-in has its own expression parser (`lib/params/expressions/`, `reading.py`). When the
   parser refuses a text (an unknown unit, for example), the resolver still takes the words of the text that are
   known parameter names (`names_in`).
2. Fusion's own list `dependency_parameters`.
3. The reverse direction: `dependent_parameters` and `dependents` of each user parameter. This finds a chain through
   a model parameter of another component, which the capture does not list.

`Graph.walk` follows the edges at any depth. A cycle stops at the first name seen twice.

`Graph.usage(starts, linked)` gives a `Usage` record for a body:

- `used`: every user parameter the body reaches, at any depth;
- `direct`: the user parameters a model parameter of the body names itself (also through other model parameters);
- `through`: for a user parameter that the body reads only through formulas of other user parameters, the outermost
  of those formulas. The dialog uses this for the line "This part uses it through the formula Inner."

Example. The design has `Outer = 60 mm`, `Wall = 2 mm` and the formula `Inner = Outer - 2 * Wall`. A sketch dimension
`d4` of the body has the expression `Inner`. Then:

- the graph has `d4 -> Inner`, `Inner -> Outer`, `Inner -> Wall`;
- `used` is `{Inner, Outer, Wall}`;
- `direct` is `{Inner}`;
- `through` is `{Outer: [Inner], Wall: [Inner]}`.

`Inner` is a formula, so it cannot be ticked. `Outer` and `Wall` are ticked to start with. In the recipe, `Inner`
becomes a derived size with the formula `Outer - 2 * Wall`.

#### Which parameters are ticked to start with

`size_offers.initial_table` decides the first ticks. The rules are in `params/defaults.py`, `default_ticked`:

1. A parameter is "offered" when it is a plain number in a length, an angle or no unit (`is_offered`). A formula of
   plain numbers counts as a plain number here, since its kind is the kind of its unit.
2. When the person has favourites that the body uses, only those favourites are ticked. A plain parameter that only a
   favourite formula reads counts as a favourite too. A favourite is ticked also when it is a unitless formula of
   numbers.
3. Else every offered parameter the body uses is ticked, with one exception: a formula of plain numbers with no unit
   (`2 * PI`) is a helper constant and not a size, so it starts unticked (`defaults._unitless_constant`). It is still
   offered, so the person can tick it. A formula of plain numbers with a length or an angle unit (`3 * 0.4 mm`) is
   ticked like a plain parameter.
4. A parameter that a joint reads is not ticked (`joint_reasons`). The part does not follow a joint in the assembly.
   The person can still tick it; its row then says "size, may be unexpected".
5. At most 64 parameters can be ticked (`MAX_SIZES` in `size_table.py`, the app's recipe cap).

When the person picks another body, the ticks follow that body. With several bodies, a parameter that any body uses is
ticked (`size_table.merged`).

#### The range of a size

Each ticked row has Min and Max. The default comes from `defaults.size_range`:

- A comment that ends with `[min..max]` (for example `Wall [1..6]`) sets the range, when the value lies inside it.
- Else a length goes from half to double its value (0 to 10 for a value of 0).
- An angle goes 45 degrees below and above, kept inside 0 to 360 for a value in that span.
- A count goes from 1 to twice its value, at most 64.

The person can type other numbers. A typed end is kept: the add-in never cuts a typed end (see 1.9.5).

#### The size table

`params/size_table.py`, `SizeTable`, holds the result. Each user parameter gets one `Entry` with a `state`:

| State | Meaning |
| --- | --- |
| `free` | A plain number kept as a size. The recipe gets `sizes[name] = { kind, value, min, max, label }`. |
| `derived` | A formula over other sizes. The recipe gets `{ expr, label }`. |
| `constant` | A plain number that is not a size. A formula that reads it writes its number. |
| `fixed` | Ticked, but it cannot follow. It is shown greyed with its reason. |
| `not_offered` | A text or a unit that cannot be copied. |

The recipe name of a size is the Fusion name when it is valid (`^[A-Za-z_][A-Za-z0-9_]*$`, at most 64 characters).
Else `names.assign` replaces the bad characters with `_`, puts `p_` before a leading digit and adds `_2`, `_3` on a
clash. The recipe name and the label are two different things. The label is the text on the form in Paramability. It is
not the Fusion name any more (see "The label of a size" below). `Entry.label` still holds the Fusion name, and the
messages and reasons use it. `Entry.title` holds the label of the form.

The table can also translate a Fusion expression into a recipe formula (`SizeTable.translate`). The translator uses
this for every value that a model parameter holds (see 1.9.6).

#### The label of a size

The label of a size is the text that Paramability shows next to the field. A person reads it, so it must be words.
A Fusion name such as `BaseCup_midExtrude_offset__mm` is not good for this. `lib/params/labels.py` (`assign`) makes the
labels of all the sizes of one recipe together. `SizeTable` keeps each one in `Entry.title` and writes it as `label` in
`sizes`.

The rules for one size:

1. A short comment on the parameter gives the label. Take the first sentence of the comment. Remove a trailing
   `[min..max]` first, since that is the range (see "The range of a size"). When the sentence has 48 characters or
   fewer and has a letter in it, it is the label, with a capital first letter ("Wall thickness"). A comment longer
   than 48 characters is a description and not a label.
2. Else the name gives the label, in words. `name_words` splits the name at underscores, symbols and camelCase. It drops
   a trailing unit word (`mm`, `cm`, `deg`, `degrees`, `rad`, `unitless`, or the unit of the parameter) when it is not
   the only word. It writes the words in lower case with a capital first letter. So `BaseCup_midExtrude_offset__mm`
   becomes "Base cup mid extrude offset". An acronym such as `ID` stays as it is. A name written all in capitals is made
   lower case.
3. Two sizes of one recipe never keep the same label (the case of the letters does not count). Sizes whose label came
   from a comment go back to their name in words. Sizes that still share a label get the Fusion name in brackets behind
   the label, for example "Wall (Wall_a)". The labels are cut to the label length (120 characters) before they are
   compared, and the text in brackets is made to fit. When names are so long that the cut makes them alike, a number is
   added.

What keeps the Fusion name: `Entry.label` (messages and reasons), the recipe size name, and `label` in the manifest
`parameters` list (`params/listing.py`). The Paramability app words the label of a package from an older add-in in the same way, and it shows the Fusion name of the parameter in the tip of
the field.

#### Formulas of plain numbers, and fractions

A formula of plain numbers needs no other parameter. `3 * 0.4 mm`, `25.4 * 2 mm`, `3/8 in` and `PI * 10 mm` are
examples. Fusion works them out alone. The size probe sets such a parameter to a number, and the restore puts the text
back, as for every parameter. So the add-in treats it like a plain number: it has the kind of its unit, it is offered
and it can be ticked. In the manifest `parameters` list it is a plain entry with its value and no `expr`. A formula that
names another parameter stays `derived`.

The parser reads a unit word right after a division of two number literals as the unit of the whole fraction. So
`3/8 in` is three eighths of an inch (`_fraction_unit` in `params/expressions/reading.py`). In every other division the
unit word binds to its divisor only: `w / 2 mm` is `w / (2 mm)`. `docs/expressions.md` has the full grammar.

### 1.4 Body scope

A design often holds many bodies. Only some steps and parameters belong to the picked body. `lib/export_plan/
body_scope.py` finds them from the capture alone:

- `body_items(capture)`: the timeline items that touch the picked body, a body it was split from (up to that split),
  or a tool body that a Combine joins into it. It repeats until nothing new is found, since a Combine adds its tools to
  the list of wanted bodies.
- `scoped_model_params(capture)`: the model parameters the body can read. A parameter is dropped only when it is
  matched to a step or a sketch that the body does not use. Anything that cannot be matched stays. Names are matched
  together with the component token, because every component has its own `Sketch1`.
- `quantity_refs(capture)`: the model parameters that set a pattern count. The user parameters behind them become
  whole number sizes (kind `count`). `defaults.count_names` finds these user parameters. It starts at the quantity
  parameters and follows the names that each formula reads. It does not follow a name inside `round`, `floor` or
  `ceil`. It does not follow a name in a comparison. In these places a fraction cannot reach the quantity, so Fusion
  accepts a fraction there. Thus `Ratio` in `ceil(Ratio * 4)` is not a count. It becomes a size of kind `number`, and
  that size has decimals. A formula can be unreadable, or it can read a parameter that the capture does not hold. For
  such a formula, the walk follows every name that Fusion lists as read (`Graph.reads`). Thus a parameter that can be
  a count is never lost. A size of kind `count` must also have no unit and a whole value of 1 or more
  (`defaults.size_kind`). Every other size with no unit is of kind `number`.
- `body_links(capture)`: the geometry links of the body (a sketch drawn around another component, or a step that uses
  a plane of another component; see 3.3).

The rule is "drop only what is proven to belong to another body". So a wrong match never hides a parameter.

### 1.5 The STEP file

The pipeline writes the STEP file first, before it reads the capture (`export_body_step` in
`lib/fusion_reader/step_export.py`). The STEP is the shape "as it is" at the timeline marker.

- When the design holds only one solid body, Fusion exports the root component.
- Else the add-in makes a temporary component, copies the picked body into it (`BRepBody.copyToComponent`), checks that
  the copy sits where the body sits (bounding boxes within 0.001 mm), exports that component and deletes it.

Fusion puts the timeline items of the copy at the marker. `lib/design_edit/temp_copy.py` deletes only the items that
were not there before (it compares Fusion objects with `==`, not tokens). Then the marker goes back. When items are
left behind, the export stops with "The temporary copy of the part left N steps in the timeline."

`MULTI_BODY_ROUTE` in `step_export.py` can switch to `ROUTE_ASK_DESIGNER`. Then the add-in asks the person to hide the
other bodies instead of making a copy.

### 1.6 The capture: reading the timeline

The capture is one plain dict that holds everything the add-in knows about the design. It has only JSON values:
dicts, lists, strings, numbers, booleans and null. The translator reads only the capture. It never calls Fusion. This
is why the translator can run in tests and on a saved `report.json`.

`read_capture(design, body)` in `lib/fusion_reader/capture.py` makes it. The format is capture number 3. The full
format is in `docs/capture-format.md`, sections 1 to 5.

#### Units and frames

- Lengths are in mm (Fusion's cm times 10). Angles are in degrees.
- 3D values are in the coordinates of the body's own component (the native body), before any up axis turn.
- `target.placement` says where that component sits in the assembly (`frame`, the occurrence path, how many times the
  component is used, and whether it comes from a linked design).

The reader reads the placement once, before the walk (`placement.py`). To check a frame, it maps a few points of the
body and compares them with the body in the assembly. It fetches only three vertices (`POINTS_TO_CHECK = 3`). When the
body has fewer vertices, it takes points on faces. It fetches the items one at a time. So a body with many vertices
costs no more time than a simple body. The probe reads the place of the body again at each state in the same way
(`probe_refs._target_back`).

#### The walk, step by step

The timeline marker is the bar in the Fusion timeline. Fusion builds only the items before it. The reader uses this:
it moves the marker through the timeline, one item at a time, and reads the design at each place.

1. It reads where the marker is now: `end`. Items at `end` and after are left out of the export. They are not
   refused, they are simply not part of the design "as it is at the marker".
2. For `k` from 0 to `end`, it sets `timeline.markerPosition = k`. Fusion rebuilds the items before `k`.
3. At each `k` it reads the picked body once: its box and its volume (`_target_state`).
4. It finishes item `k - 1` (`_finish_item`): the bodies the item lists (`bodies_after`), its health (`ok`, `warning`,
   `error`) and Fusion's message, whether the body changed (`target_changed`), the body before and after
   (`target_before`, `target_after`), and the "after" reader of the step type.
5. It starts item `k` (`_start_item`): its name, type, component, whether it is suppressed, the sketches it takes
   (`sketch_inputs`), the bodies of the component before it (`bodies_before`), and the "before" reader of the step type.
6. After the loop, the second pass reads the steps that built the tool bodies of a Combine (see "Tool bodies" below).
7. In a `finally` block the marker goes back to `end`. If it does not read `end` after that, the reader raises
   `MarkerError`. The export then stops with a message.
8. The reader checks that timeline groups hide no item before `end` (`_check_groups`). A group with an unread child
   raises `CaptureReadError` and the part is saved as a fixed shape.
9. It reads the parameters, the sketch links (`read_links.py`) and the sketch graphs (`read_constraints.py`) with the
   marker back at `end`.

So a capture of a timeline with 120 items costs about 121 marker moves and as many rebuilds. This is one cost of an
export (see checklist 4.10.5).

#### What the reader reads per step

Each step type has a pair of reader functions `(before, after)`. The pairs are in the `READERS` dict of a module in
`lib/fusion_reader/` (`read_solid.py`, `read_hole.py`, `read_finish.py`, `read_repeat.py`, `read_sweep.py`, `read_split.py`,
`read_move.py`, `read_paste.py`, `read_scale.py`, `read_offset.py`, `read_emboss.py`, `read_thread.py`, `read_coil.py`, `read_pipe.py`). The step kind table
(`lib/capture_model/step_kinds.py`) says which module reads which type.

`read_solid.py` reads the extrude, the revolve and the combine. `read_hole.py` reads the hole. Both need the same facts
of an extent: where it starts, how a side ends, and the face or plane it goes to. `lib/fusion_reader/read_extent.py`
gives these facts, so the extrude and the hole read an extent in one way. `read_extent.py` has no `READERS` dict.

- `before(feature, ctx)` runs with the marker just before the step. It returns the step's `data`: the profiles, the
  extent, the operation, the edges and faces it picks, the bodies it takes, the parameters behind its values.
- `after(feature, ctx, data)` runs with the marker just after the step. It adds what Fusion built: end faces, side
  wall leans, volumes, the faces the step made.

Inputs such as fillet edges and extrude profiles must be read with the marker before the step. The Fusion reference
says so (`timelineObject.rollTo(True)`). This is why there are two readers.

Every Fusion call in a reader is wrapped in `geo.safe(...)` (`lib/fusion_reader/read_geometry.py`). A member that
raises gives `null` or `"other"`. The reader never invents a value. The translator then refuses what it cannot read.
When a reader function raises, the step's data becomes `{"read_error": "..."}` and the translator stops the copy at
that step ("This step could not be read from Fusion.").

Types without a reader (sketches, construction geometry, a thicken) get `"data": {}`. They still get `target_before`
and `target_after`. So even a step the add-in does not know says where it changed the body and by how much.

#### The values behind parameters

A value that Fusion keeps as a model parameter is listed in `data.params`, by its path in the data:

```json
"params": { "side_one.distance": { "name": "d12", "expression": "Height + 2 mm", "value": 32.0 } }
```

`lib/fusion_reader/param_refs.py` writes these. The translator turns each of them into a formula of the sizes when it
can (see 1.9.6). Sketch dimensions and construction planes are not listed per step. They are model parameters whose
`created_by.kind` is `sketchDimension` or `constructionPlane`. The size probe handles them (see 1.8).

#### Body measures

The reader measures the picked body around each step. These numbers are the "proof" the translator uses:

- `target_changed`: true when the box moved by more than 0.0001 mm or the volume changed. False when the step did not
  change the body. Null when the body exists on neither side or a measure failed.
- `target_before` and `target_after`: `{ box, volume_mm3 }` before and after the step.
- Some readers also write `volume_before` and `volume_after` in the step data (a Combine, a sweep, an emboss, a
  draft). The handlers check their copy against these volumes.

Example: a sweep makes a new body. The reader measures 1250 mm3. The outline area is 25 mm2 and the path is 50 mm
long, so the expected volume is 25 * 50 = 1250 mm3. The volumes agree, so the handler trusts its reading of the
sweep. If Fusion had made 1310 mm3, the handler would leave the sweep out, since Fusion did something the copy does
not model.

#### Tokens

Bodies, sketches, faces and construction planes are named by `entityToken`, a text that Fusion gives each entity. The
capture names a body as `{ "token": "...", "name": "Body1" }`. Two records name the same body when the tokens match.
Names are compared only when a token is missing.

When a step makes a body with the picked body's name but another token, the translator does not guess. It stops with
"The body could not be followed through the timeline." So when you see that reason, look at the tokens in
`bodies_after` of the items around the stop.

The size probe also uses tokens. It finds each sketch, sketch point, line, face and plane again with
`Design.findEntityByToken` after each rebuild.

`bodies_after` can be `null`. This is not the same as `[]`. `[]` means "the step makes no body". `null` means "the
bodies could not be read". The translator stops at a `null` for a step that may touch the body.

#### Tool bodies and the second pass

A Combine can take tool bodies. A tool body can be made by its own steps, even in another component. The first walk
reads feature data only for items of the picked body's component. So `lib/fusion_reader/helper_pass.py` runs a second
pass when a Combine that changes the body lists a tool. It moves the marker to the items that made the tool and reads
them in the tool's own component frame. It runs in rounds, since those items can name more bodies. The limits are 120
items, 32 tool bodies and 3 levels deep (`capture_model/tool_items.py`).

Items read this way carry:

- `helper_of`: the token of the tool body (for items of another component);
- `body_states`: per body token, `{ box_before, volume_before, volume_after }` of that body around the item. A tool
  step reads these numbers, not the numbers of the exported body.

`body_states` is also written on the steps that built a body the picked body was split from (see 3.4).

#### Sketch links and sketch graphs

- `sketch_links` (`read_links.py`): for each sketch the body uses, the other components it is tied to: projected
  curves, constraints to such curves, or a sketch drawn on a face of another component. With this, a parameter that
  changes a pipe in another component can be offered for a hole drawn around that pipe.
- `sketch_graphs` (`read_constraints.py`): every point, curve, dimension and constraint of each sketch the body uses.
  Only the shadow check `derived` reads it (see 4.2). The recipe does not depend on it.

### 1.7 The first translation and the reach read

The pipeline now builds the size table (`size_table.build`) with the ticked names, the typed ranges, the scoped
model parameters and the body links.

Then it translates once with `motion = OPTIMISTIC` (`sketch_values/motion.py`). OPTIMISTIC means: write every sketch
value as a number, and fix nothing because of sketches. This first look tells the pipeline:

- whether the copy stops (then the size probe still runs, but the result will be a fixed shape);
- which sizes the recipe keeps (`free_sizes`), so the probe tries only those;
- whether steps were left out (gaps).

When the first translation left steps out, or stopped because the part had more than 256 gaps, the pipeline asks
Fusion one more question: which step made the faces that each later step picks (`reach_pass.with_reach`, reader
`read_gap_reach.read_reach`). This is the "reach read".

Why: a round picks its edges by measured points (`near`). If the step that made those edges is missing from the copy,
the kernel would round the nearest other edge without a word. With the answer, only the later steps that really pick
faces of a missing step are left out too.

The reach read moves the marker to just after each candidate step (to read `Feature.faces`) and to just before each
picking step (to find the picked faces). The answer goes into the capture as `reach`:

```json
"reach": { "read": true, "gaps": [12], "makers": { "17": [12], "19": [12, 17] }, "moves": 3 }
```

This says: step 12 was left out; step 17 picks a face that step 12 made; step 19 picks faces of steps 12 and 17. A
failed read gives `{ "read": false, "error": "..." }`. Then every later step that picks geometry is left out, with
"It may pick faces of Extrude5, which is missing from the copy." This is the safe side.

The capture with `reach` is translated again. That result decides the sizes the probe tries.

### 1.8 The size probe

#### Why the probe exists

A sketch dimension is not a step value. The capture holds the sketch as Fusion drew it at the current values: points
and curves with numbers. The capture does not say how a corner moves when `Width` changes. Fusion's sketch solver
knows, but the add-in cannot call the solver directly.

So the add-in asks Fusion by experiment. It sets a size to another value, lets Fusion rebuild, and reads the sketch
again. From several such readings it fits a formula for each sketch value. This is the "size probe". Each experiment
is a "row" (or a "try"). The design read at one row is a "state". The first read, at the current values, is "E0".

#### Which sizes get rows

One module decides which sizes get rows: `lib/export_plan/probe_flow/sizes.py`. Both export pipelines call its
`sizes_to_try`. It uses `kept_sizes` (the sizes the first translation kept, plus the sizes that reach a sketch) and
`extra_sizes` (the guessed ones, see the last point below). It gives the probe size dicts (`size_offers.probe_sizes`)
and the Fusion names of the guessed sizes. A size gets rows when it can move something the probe follows:

- a sketch dimension of a followed sketch, a construction plane or a sketch tied through another component
  (`design_model.reach.probed_sizes`);
- a plane that a followed sketch sits on (`plane_sizes.plane_driven`);
- a measured reference of another component (a mirror plane, a pattern axis, a face an extrude reaches to);
- a flat face that a step uses as its outline;
- up to 8 more ticked sizes that nothing ties to a sketch (`MAX_EXTRA_SIZES`). The person ticked them, so they may
  matter in a way the capture cannot show.

A size that only feeds step values (an extrude distance, a fillet radius, a pattern count) needs no row. Its formula
is exact from the expression.

A symmetric pattern is a special case. Its copies lie on both sides of the original. The tries read its copies at
every state (see "What a state holds"), but its count gives the count's size no rows of its own. So Fusion's places
at an even count are read only when that size gets rows for another reason: it moves a sketch, or it is one of the
extra ticked sizes. Section 3.11 explains why the even count matters.

What the probe follows (`plan.scan`): the sketch profiles of extrudes, revolves, sweeps, lofts and embosses, the hole
points, a revolve axis on a sketch line, a sweep path of sketch lines and arcs, and a flat face used as an outline. The
step kind table says which records of a step the probe may follow (`sketches=` in `StepType`). A sketch token in any
other place leaves that sketch unfollowed. A sketch with a spline or text is not followed either.

#### The start: E0

`SizeProbe.start(capture, table, read)` builds the request (`plan.request`): the sketch tokens, point tokens, line
tokens, parameters, references and faces to read. It reads E0 through the port (`read_state` in
`lib/fusion_reader/probe_state.py`). A sketch whose E0 read does not match the capture is not followed
(`match.readable`). A reference whose E0 read does not match is not read again (`ref_fit.measurable`). When nothing is
left to follow, the probe does not run.

#### The marker roll and "Faster tries"

Each row rebuilds the design. Fusion rebuilds every item before the marker. Items after the last item the part needs
are only lost time. So `TryTimeline.begin` (`lib/export_plan/timeline_trim.py`) does two things:

1. The marker roll (`marker_roll.py`, `MarkerRoll`). `needed_position` finds the last item the tries need: any item
   that may change the body, the sketches the steps use, the items of each other component a link depends on that
   come before the step holding the link (a step never depends on a later item), joints and unknown items (an unknown
   `...Feature` of another component excepted). The store holds the marker just after it (`DesignParameterStore.roll_marker`). The roll
   stays only when a read at the rolled marker gives the same sketches, points, lines, references and box as E0.
2. "Faster tries" (`TimelineTrim`), on unless the person unticks the box (it starts ticked). It suppresses items of
   other components that the tries do not need. The unit of trust is the component: an item is turned off only when no item of its
   component is needed. Nothing is turned off when the evidence is unclear (an unknown item type, a joint before the
   stop point, a link without a component). After turning items off, the design must read the same as E0 and show no
   new error, else every item is turned back on. The items come back on before the discovery rows (`ProbeRun.discover`
   calls `before_discovery`), since those rows look for links to other components.

Both are undone on every way out: after the rows, on cancel and on error. The marker goes back without a full
`computeAll` when every parameter expression is as it was at the roll (`DesignParameterStore.unroll_marker`); Fusion
builds the later items as the marker passes them. `report.json` keeps what happened in
`probe.timeline` (see 4.2).

#### The rows, in order

`ProbeRun.measure` and `ProbeRun.discover` in `lib/export_plan/pipeline/probe_run.py` run the rows. The plans come from
`lib/probe/plan/`. All rows of one export share one budget of 64 rows (`MAX_PROBE_ROWS`).

`ProbeRun` does not know if the probe is one part or a group of parts. It asks the probe for each kind of row through
one declared interface, `Probe` (`lib/export_plan/probe_flow/interface.py`). `SizeProbe` (one part) and `ProbeGroup`
(several parts over shared rows) both have every member of it. A new row kind or probe call is declared there first
(see 4.11).

The probe also keeps where it is in the order below. A `RowSchedule` (`probe_flow/row_schedule.py`) holds the row phase
(`NOT_PLANNED`, `NEAR`, `FAR`, `DONE`), the sizes the near rows tried (`moved` for sizes that move a sketch or a
measured place, `extra` for the guessed ones), how many nearer rows ran (the cap of 24) and whether the check rows
were planned (they are planned once). A group keeps one schedule for the nearer rows and the check rows its parts
share (`ProbeGroup.schedule`).

1. Near rows (`plan.probe_rows`). Each tried size gets two rows: 25 percent of its value below and above
   (`NEAR_SHARE`), kept inside its range. A count moves by whole numbers. A value of zero moves 25 percent of the way
   to each range end. The sizes come in an order (`rows.tried_sizes`): first the sizes that move a sketch or a measured
   place, then the guessed ones. In each group the favourites of the design come first, since the designer starred
   them for the form. When the time limit stops the tries (see "The time limit of the tries" below), the sizes that
   come last lose their tries first.
2. Pair rows (`plan.pair_rows`), after the near rows ran. With two or more tried sizes: one row with all of them at
   the lower near value, one at the higher. A size whose own near row on that side failed stays at its value.
3. Nearer rows (`plan.nearer_rows`) for the rows that did not build. See below.
4. Far rows (`plan.far_rows`): the range ends of each tried size, when they differ from the value and the near values.
   An end past a value of that size that failed alone is not tried.
5. Nearer rows again, for far rows that did not build. Then, with two or more sizes, all sizes at their minimum and all
   at their maximum (`plan.far_pair_rows`), each tried size only as far as it built alone.
6. Check rows (`plan.check_rows`), once per export: for a value that one size moves along a curve (see 3.1), more
   rows that let the add-in fit and check a formula with sine, cosine or products. Some of these rows are pair rows.
   A pair row sets a curved size together with one other size. The other size is one of the sizes of the curved
   values, or any size that moves a value of the same sketch (`series.curve_sizes`).
7. Discovery rows (`plan.discovery_rows`), in the rows still left: up to 12 unticked parameters of other components
   (`MAX_DISCOVERY`), each set once to one end of its range. They only answer "does this parameter also change the
   part?". They never become sizes in this export. They do not run after the time limit stopped the tries.

Nearer rows. A row that Fusion cannot build is tried again nearer to the value now: half way to that range end, then a
quarter, then a tenth (`NEARER_STEPS`). When one value built and a farther one did not, the add-in halves between them
(at most 4 times, `BISECT_STEPS`, until the two are within a tenth of the way, `BISECT_GAP`). At most 24 nearer rows run
per export (`MAX_NEARER_ROWS`). A row where the size alone made a followed sketch take another outline counts like a
row that did not build. A row where the part came apart into separate pieces counts the same way. Section 3.2 shows a
full example.

#### One row, in detail

`RowExport.run` (`lib/design_edit/runner.py`) runs the rows. For one batch of rows:

1. Before the first row ever, it saves every parameter expression and measures a baseline: one rebuild with nothing
   changed, and the list of items already in error (`apply.measure_baseline`). A design with an old error elsewhere
   can still be probed.
2. Per row, it first asks `stop_when` whether the time limit is reached (see "The time limit of the tries" below).
   Then it asks the progress window if the person cancelled. The window shows "Try 5 of 31: Width at 32 mm" and, under
   it, a line about the time that the tries took.
3. From the second row on, it puts every parameter back to the saved expression and rebuilds
   (`_back_to_current`). So every row starts from the design as it was. A row never builds on the values of the row
   before it.
4. It calls the hook `ProbeRun._before_row` (see "Solver flips" below). The hook first brings the marker home. Then,
   with "Lighter on memory" on, it lets Fusion forget the Undo data of the rows so far (`_drop_undo`, see 1.11). Every
   value is back at this point, so the dropped data holds no change that the add-in does not undo itself.
5. It sets the row's values as expressions (`apply.apply_row_values`). The value is written in the parameter's own unit
   (`format_expression`). All values go in as one change (`Design.modifyParameters`), so Fusion rebuilds once; a
   Fusion without that call gets them one at a time and a `design.computeAll`. Before that, after a row that did not
   build, a step still in error with the values back (after one full recompute) that was fine in the baseline stops
   the tries (`RowExport.not_back`). The row
   fails when Fusion refuses the expression, when the rebuild raises or reports failure, or when an item before the
   marker goes into error that was fine in the baseline. After one change, a step in error is judged after one full
   recompute, since that change rebuilds only the steps it touches. The first new item in error is the "failed step"
   of the row.
6. For a probe row there is no STEP file (`"step": False`). The step callback reads the probe state instead
   (`ProbeRun._export`). A row with a STEP file (Export size choices) is recomputed in full after the change, and
   judged by that recompute, before its STEP is written.
7. In a `finally` block, the parameters go back.

So each row costs two rebuilds: one with the new values and one to put the values back. A row whose read includes an
outline face leaves the marker before the face's step (`park`, `read_faces(stay=True)`); the change that puts the
values back then moves it home, so the face read adds no third rebuild. `ProbeRun._home` brings the marker back before
any other read and when a batch ends, and stops the probe when it does not go back.

#### What a state holds

`read_state(design, request, ctx)` reads, for each followed sketch, its frame and every profile, each curve with the
token of its sketch entity. It also reads the sketch points and lines (hole points, revolve axes), the values of the
named parameters, the body's box, the measured references (`probe_refs.py`) and the outline faces (`read_face.py`).
Every value is in the component's coordinates, like the capture. A part that cannot be read has no key. Nothing
raises.

With the box, a state also holds the volume of the body (`volume_mm3`, from `BRepBody.volume`). The box alone does not
show a change inside the body, for example a deeper pocket or a wider hole. The volume shows it
(`probe.state.body_changed`). The area of the body is not read: it would cost a second computation of the body at
each try. It would show only a change that keeps the box and the volume exactly as they were. Such a change is rare.

A state also holds `pieces`: `{ lumps, others }`. `lumps` is the number of solids that the picked body holds
(`BRepBody.lumps`). `others` is the list of boxes of the other solid bodies of the same component. It is left out when
there are more than 64 of them (`MAX_OTHER_BODIES`). Reading them recomputes nothing. The reason for this read: the app
builds a part only while it is one connected solid. Fusion also builds a part in several pieces. A body can hold several
solids. A cut can cut the body in two. A join whose new material does not touch the body makes a new body beside it.

`probe/pieces.py` (`count`, `came_apart`) counts the pieces of the part at a state, against E0. The count is the lumps of
the body, plus the other bodies whose box comes within 1 mm of the box of the body at that state or at E0, less the
bodies that did so at E0 already. Never more of them count than the number of bodies that are new since E0. So a tool
body kept beside the part, a second body of the design, and a lid laid out next to a box that grows toward it do not
count as pieces. A try where the part comes apart while it was one piece at E0 is stored as a try that did not build
(`SizeProbe.add_states`): `built: false`, `pieces: n` and no `read`. `probe.dropped` gets the entry "the part came apart
into N separate pieces". Nothing is fitted to such a state. Section 3.2 shows what happens to the range.

A state can also hold `patterns`. This happens when the capture has a symmetric pattern whose count follows a
parameter (`plan.symmetric_patterns`). For each such pattern, the reader gives the counts and the copies (`elements`)
that Fusion made at that state (`fusion_reader/probe_patterns.py`). The motion keeps them per state
(`Motion.states[n].patterns`, only for a state that built). A `start` read and a `put_back` read skip them.

#### Solver flips and put backs

A sketch can have two solutions. Example: a point at a distance from a projected point, with no side given. After a
row that did not build, Fusion may leave the sketch on its other solution, also after the values are put back. Then
every later row starts from the wrong outline.

The pipeline protects against this:

- Before the rows, `SketchKeeper` (`lib/fusion_reader/sketch_keep.py`) keeps the place of every own point of the
  followed sketches (projected and fixed points stay).
- `ProbeRun._before_row` reads the design before a row when the row before did not build or read another outline.
  This read is the state's `start`. It holds only the outlines (sketches, points, lines and outline faces), not the
  parameters, references or box, since it only tells where the row starts from. A row can bring a sketch back as well
  as move it away, so each such row reads its own start, also after put backs are given up.
- When that read shows a followed sketch away from E0 (another outline, or a value more than 0.05 mm or degrees off,
  `FLIP_TOLERANCE`), the keeper moves every kept point more than 0.0001 mm from its place back, with its sketch's
  compute deferred and then set back to its start value (a sketch with all points in place is not touched), and the design is rebuilt once, also when no point moved: the
  keeper matches points by their entity token and skips a point that is gone, and a rebuild may still bring the
  sketch back. The read after that is the state's `put_back`. After two put backs in a row that do not help, no more
  are tried.
- A row that did not start from a checked read, and after which the sketch was found flipped, is run once more from a
  checked start. The second run is marked `again`. Its first run is left out of the states.
- Before the discovery rows, and once after all tries (`ProbeRun.settle`), the sketch is put back again, so the design
  is left on the solution it had. Before the discovery rows the read after the put back is a full read: it is the base
  the discovery rows are compared with, box and parameters included.

`probe.recovery` in `report.json` counts the extra rebuilds (`put_backs`, `again`). `health.flipped` names the
sketches that stayed on their other solution for a while.

#### The time limit of the tries

The tries rebuild the design twice per row. On a large design they can take most of the export. So the dialog has the
list "Stop the size tries after". The choices are in `export_plan/time_limit.py` (`CHOICES`): 1, 5, 10, 20 and 30
minutes, 1 and 2 hours, and "No limit". The default is 10 minutes (`DEFAULT_SECONDS`). The slowest design measured took
about a minute per try, so ten minutes still gives it about ten tries. The choice goes to `ExportRequest.probe_time_limit`
in seconds, with `None` for no limit.

How it works:

1. `ProbeRun` gets `time_limit` and a `clock`. The clock starts when the runner is made, just before the first try. It
   also counts the reads and the put backs between the tries. The clock is the one of the export timer, so a test can
   drive it.
2. `RowExport` gets `stop_when` (`ProbeRun._out_of_time`). Before each row, `RowExport._halt` asks it. When the time is
   up, the run ends there, cleanly. No later row runs. The parameters go back as at the end of any run.
   `RowExport.halted` stays true for every later run of the same job. A clock that fails never stops the tries. A row
   that did not build is still checked first (`not_back`), so a time stop never hides a design that a failed row left
   broken.
3. After a halt, `ProbeRun._left` is 0, so no further rows are planned. The probe is told which sizes got no try
   (`SizeProbe.note_time_limit(record, unrun)`). A discovery row that did not run is told apart by its key
   (`plan.DISCOVERY_KEY`) and kept as "not tried: the tries ran out of time". `ProbeRun.discover` does not run after a
   halt. `note_time_limit` and `time_left_out` are members of the `Probe` interface, so `ProbeGroup` has them too.
4. A time stop is not a health problem. The put back is the same as after tries that ended on their own:
   `PutBack.tries_done`, `tries_ended` and `settle` make the same calls, and nothing goes into `health`. The Undo step
   is dropped as usual when the end check confirms that the design is as it was.

Which sizes count as left out: `SizeProbe.time_left_out()` gives the Fusion names of the sizes that move a sketch or a
measured place and have no try of their own that built. Their rows did not run, or their last row did not build and its
nearer tries did not run. A size that was only tried on a guess is not counted, since nothing is known to move with it.
These sizes go to `motion.untried` and to `motion.timed_out`. `translate()` reads `motion.timed_out` and gives them the
reason `TIMED_OUT_WHY`: "the tries ran out of time before this size was tried. Tip: raise the time limit in the export
dialog, or untick sizes that need no change". A size that a formula still reads is loose ("may give unexpected
results"). A size that only a sketch reads is "not a size".

What the person and the report see:

- `probe.time_limit` is `{ limit_seconds, hit, seconds?, left_out }`. `seconds` is there only when the limit was hit.
- `timing.probe.time_limit` is `{ limit_seconds, hit, left_out? }`. `left_out` is there only when the limit was hit.
- The result window adds a line to "Result" when the limit was hit: "The size tries stopped at the time limit (1 min). 3
  sizes were not tried, see Sizes." (`messages.time_stop_line`).
- The progress window shows a third line: "Time spent: 2 min 10 s. About 4 min left (limit: 10 min)." The estimate is the
  average time of a try so far times the tries planned so far. It never goes past the time that the limit leaves
  (`messages.time_note`). The step of the progress window of the port has a fourth argument for this line:
  `step(index, total, name, note)`.

Hand check TL1 in `docs/hand-checks.md` tests this in Fusion.

#### The end of the probe

The put back of the design is one object per export, `PutBack` (`lib/export_plan/pipeline/put_back.py`). Both
pipelines make it at the start of the export. `_Pipeline._measure` (in `pipeline/run.py`) calls it after the rows:

1. `put_back.tries_done(run)` notes the time the tries took (`TryTimeline.tries_done`). Then it puts the design back
   (`PutBack._after_tries`), in this order:
   1. Every parameter is put back (`PutBack.restore`, which calls `restore_parameters`). After one change, the
      expressions are read back as text; any that did not take is set on its own, and one that still differs is
      listed in `health.unrestored`.
   2. The suppressed items are turned back on (`PutBack.end_trim`).
   3. `run.settle()` puts a flipped sketch back.
2. `probe.finish(read_now(), labels)` builds the motion file from the states (`probe/build.py`). It also lists the
   sizes the probe cannot follow: sizes left without rows by the cap (`untried`), sizes that the time limit left
   without a try (`timed_out`, also in `untried`), sizes that change a borrowed sketch it could not follow, and sizes
   that changed the body but moved nothing the probe follows (`body_moved`). The motion file also keeps, for each
   size that a try set alone, whether the body changed at that try (`body_changes`, `probe/build.py`).
3. `finish` compares the sketches read after the restore with E0 (`measure_restore`). The largest difference is
   `restore_gap_mm`. The end of the export reads and compares once more (see 1.11).

The tries end through a `finally` block: `put_back.tries_ended(run)` runs on every way out, also when the tries fail
or are cancelled. When `tries_done` did not run, it does the same put back (`_after_tries`). It also keeps how the
tries stopped and the timing of the probe. So a flipped sketch is put back on every way out.

A probe that fails (an exception other than a cancel) does not stop the export. The final translation then runs
without a motion file, and every size behind a sketch is marked with "it changes a sketch, which could not be tried at
other values". `health.probe` says `failed`, and the restore gap is still measured, so `health.sketch_drift` says when
a sketch stayed off its first solution.

### 1.9 The final translation

The translator gets the capture, the size table and the motion file. It returns a `TranslateResult`
(`lib/translator/result.py`): the recipe or a refusal, a verdict per item, notes, and the sizes in four lists:
`fixed`, `loose`, `cuts` and `dropped`. It may also return `gaps` and `after_stop`.

A verdict has the same shape in the recipe output and in the Orca output (`results/verdicts.py`, `verdict`): the
`index`, the `name` and the `type` of the item, the `verdict` and a `note`. The recipe output adds `steps` (the ids of
the recipe steps that the item wrote) and, for a step left out, `gap` (the id of its gap) and `cause` (`own`, `picks`
or `stop`). The Orca output adds nothing. The words of a verdict differ in one place: a step that is copied is
`translated` or `translatedWithNote` in the recipe output and `copied` in the Orca output. `skipped` and `leftOut` mean
the same in both. The record of a step that is left out has one shape too (`results/left_out.py`, `left_out`): the `name` (the type in
words when the item has no name), the `type`, the `reason` and a `hint` when the output has a tip for the cause. The gap
of the recipe output (`gaps/gap_file.record`) and the left out record of the Orca output (`orca.left_out[]`) add their
own keys after these. The dialogs read the shared keys only (`export_plan.messages.left_out_line`,
`dialog_model/left_out_preview.py`, `dialog_model/orca_result.py`).

The driver is `translate()` in `lib/translator/translate.py`. In order:

1. `validate_capture` checks the capture number and the main keys. A bad capture raises `CaptureError`.
2. `_placement_refusal`: a part from a linked design, or a place in the assembly that cannot be read, stops here.
3. The size table gets the capture's geometry links when it has none.
4. `tried_ranges.built_ranges` (`design_model/tried_ranges.py`) cuts the ranges where the probe saw Fusion fail to
   rebuild, or saw a followed sketch change its outline (see 3.2).
5. It collects "upfront doubts": sizes behind a joint, sizes that change sketch text, sizes the probe saw changing the
   body in a way the copy does not follow (`BODY_MOVED_WHY`), sizes that did not rebuild at any value tried.
6. It walks the capture (`_settle`), maybe several times (see 1.9.5).
7. `_finish` runs the end of walk audit, adds the sizes that only gaps read, cuts the ranges, and fills `loose` and
   `dropped`.
8. When the walk stopped, `_diagnosis` runs one more walk for `after_stop` (see 1.9.4).

#### 1.9.1 The walk, item by item

The item loop is `walk_items(ctx, result)` in `lib/translator/walk.py`. It visits every item of the capture in
timeline order.

Before the walk starts, it reads the design from the shared layer: `design.read` in `lib/design_model/design.py`
gives one resolved step (`ResolvedStep`) for each item. The walk of the Orca output reads the same steps (see
`docs/orca-output.md`). A resolved step is a set of facts. It does not tell the walk to copy or to stop. It holds:

- the item as the walk reads it. Before the split that made the exported body, the item has the measures of the body
  that was split (`roles.seen_before_split`);
- the role of the item (`roles.role_of` in `lib/design_model/roles.py`, see below);
- the problems of the item: the reader could not read the step (`UNREAD`), the step does not build in Fusion
  (`FAILS`), or the reader could not read the bodies after the step (`BODIES_UNREAD`). Each problem has a plain
  sentence. The walk uses that sentence when it stops;
- the item with the geometry of other components brought in (see below), and whether a record of another component
  stays in it (`foreign`);
- the doubts, the notes and the followed components that the bring in recorded (`events`). The shared layer does not
  record them on the context. The walk replays them (`design.replay`) at the point where it brings the step in, inside
  the recording of the step. This makes sure that a step that is not copied keeps none of them.

The role gives:

- the kind of the item: suppressed, not a step (a sketch or construction geometry), an assembly item, a step of
  another component that builds a tool body, another step of another component, a step that builds the body, or a
  step of another body of the same component (a helper);
- the body that the walk builds just before the item and just after it (they are different only at a split of the
  lineage, see 3.4);
- whether the item lists one of these bodies (`touches`);
- the bodies that the item makes and that did not exist before it (`new_bodies`), and whether they are copies of
  other bodies (a Paste, or a pattern or mirror of bodies);
- the reader's `target_changed`;
- whether the item lists a body with the name of the target but with a different token (`lost`).

The walk then makes one of these decisions from the role. The first rule that matches wins:

| The item is | Verdict |
| --- | --- |
| suppressed | `skipped`, "Suppressed in Fusion." |
| a sketch, construction geometry or unreadable | `skipped` |
| an assembly item (occurrence, joint) | `skipped`; but if it changed the body: stop |
| a step of another component that builds a tool body | `skipped`, the Combine walks it |
| a step of another component | `skipped`; but if it changed the body: stop |
| a step whose body cannot be followed (token changed) | stop |
| a step whose `bodies_after` is null | stop |
| a step in error in Fusion that touches the body | stop |
| a step that does not touch the body | `skipped`, "Helper geometry" (with special cases for types that copy or move bodies) |
| a step that makes another body, or a split | stop, unless `split_rules.stop_reason` allows the split |
| a Split Face that left the body unchanged | `skipped` with a note |
| a step whose reader failed (`read_error`) | stop |
| a step type with no handler | gap, with the type's `unsupported` reason |
| a step that reaches into another component (`foreign`) | gap |
| a step that picks faces of a gap | gap (`cause: picks`) |
| otherwise | the handler runs |

Before the check for `foreign` records, the walk brings in the geometry of other components that the step can use as
its own. The shared layer did this when it read the design (`design.read`), for each step of the component of the
body (`lib/design_model/`, see 2.2). The walk takes the brought in item and replays the recorded doubts and notes:

- `borrowed.bring_in` takes each outline of another component's sketch whose place is known. It removes `foreign` and
  writes the name of the component in `borrowed`. It also records the sizes that move that sketch, or the component
  that the outline follows (see "A place of another component" in 3.3).
- `refs.bring_in` takes the flat face or plane of another component that an extrude starts from or reaches to, and the
  flat face or plane that a hole sits on. It removes `foreign`, writes `assembly: true`, and takes the plane from the
  measured reference (`ref`), in the coordinates of the part.

A record that these two cannot bring in stays `foreign`, and the step becomes a gap.

The walk gives the handler the resolved step (`handler(ctx, step)` through `run_handler`). The handler reads the item
from `step.brought` and its data from `step.brought_data`. It does not read the data from the item itself (see
"Handlers read the resolved step" in 2.2).

The handler answers with a `StepResult` (the recipe steps) or a `Refusal` (a reason):

- A `Refusal` normally makes the item a gap. A `Refusal(stops=True)` stops the copy.
- An empty `StepResult` makes the item `skipped` on purpose (a cosmetic thread, for example).
- A `StepResult` with steps is written. The verdict is `translated`, or `translatedWithNote` when the handler or the
  walk added a note. A step that Fusion shows with a warning gets a note with Fusion's message.

An error that the add-in did not expect can occur while the walk handles an item (a bug in a handler, for example).
The walk does not let this error stop the whole translation. It stops the copy at that item, as for any other stop:

- The verdict of the item is `unsupported`. The reason is "This step could not be copied because of an error in the
  add-in. Please report it." The cause is `addinError` (see 1.9.3), so the refusal gets the hint that tells the person
  which files to send.
- The walk removes the verdicts and the notes that it added for that item before the error.
- `result.error_trace` holds the traceback. The pipeline writes it to the log (4.8) and so to the export trail.
- `after_stop` (1.9.4) walks past the item, as after any stop, so the report also lists the steps after it.
- In the walk of a tool body (1.9.3), the walk does not catch the error. The error goes to the walk of the part, and
  the copy stops at the Combine that takes the tool. Thus an error in a tool body never becomes a gap.

The steps that the walk wrote before the error are not used: a stop gives a fixed shape and a report, never a recipe
that could be wrong.

One check runs after the handler. When the handler wrote an extrude join that meets only material of earlier gaps,
the walk leaves the step out instead (`faces/floating.py`, "It sits on a step that was left out", see 1.9.3).

The first written step must make a body (`combine: "new"`). Else the copy stops with "The body starts in a way that
cannot be copied."

Each written step gets an id `<kind>_<timeline index>` (for example `extrude_3`) and the label of the Fusion item
(for example `Extrude2`). A second step of the same item gets `_2`, `_3`. So a recipe step always tells you which
Fusion item made it.

#### 1.9.2 Handlers and the step kind table

`lib/capture_model/step_kinds.py` holds one table, `STEP_TYPES`. It is the only list of step types in the add-in. It
sits in `capture_model`, below the translator, the probe and the Fusion reader, so all of them read the same table.
Each entry says, for one Fusion type: the words used in messages ("rectangular pattern"), the role (modeling, sketch,
assembly), the reader module (in `lib/fusion_reader`), the sketch records the probe follows, and some flags
(`makes_bodies`, `moves_bodies`, `turns_faces`, `splits_bodies`, `splits_faces`, `reaches_bodies`, `pattern`,
`repeats_sources`).
`repeats_sources` marks the pattern and mirror types; `finishes/finish.py` uses it to see whether a later step repeats
the edges of a round or a chamfer. A type with no handler has `unsupported` (the plain reason) and, when the reason has
a tip for the person, `gap_cause`. `facts` names the shared step reader that reads facts of the type from its data
alone (`ROUND_SETS`, `CHAMFER_SETS`). The resolved step of the shared layer gives these facts (`design_model/design.py`,
see 2.2).

The table holds no handler. The handlers are in `lib/translator/handlers.py`: `HANDLERS` maps a capture type to a
function `handle(ctx, step)`. `step` is the resolved step of the item (`ResolvedStep`, see 2.2). The table never
imports translator code, and only the translator reads `HANDLERS`.

| Fusion type | Handler in `HANDLERS` |
| --- | --- |
| `ExtrudeFeature` | `extrude.handle` |
| `RevolveFeature` | `revolve.step.handle` (see 3.14) |
| `HoleFeature`, `ThreadFeature` | `hole.step.hole`, `hole.step.thread` (a cosmetic thread writes nothing; a modelled one goes on to `hole.thread.feature`, see 3.12) |
| `CombineFeature` | `combine.step.handle` |
| `FilletFeature`, `ChamferFeature`, `ShellFeature` | `finishes.finish.fillet`, `.chamfer`, `.shell` |
| `DraftFeature` | `finishes.draft.handle` |
| `OffsetFacesFeature` | `finishes.offset.handle` (see 3.20) |
| `RectangularPatternFeature`, `CircularPatternFeature`, `MirrorFeature` | `repeat.body_copies.rectangular`, `.circular`, `.mirror` |
| `PathPatternFeature` | `repeat.body_copies.path` (see 3.17) |
| `SplitBodyFeature` | `bodies.split.handle` |
| `CopyPasteBody`, `MoveFeature` | `bodies.paste.handle`, `bodies.move.handle` |
| `ScaleFeature` | `bodies.scale.handle` (see 3.18) |
| `EmbossFeature` | `extrude.emboss.handle` |
| `SweepFeature`, `LoftFeature` | `sweep.step.handle`, `loft.step.handle` |
| `CoilFeature` | `coil.step.handle` (see 3.13) |
| `SplitFaceFeature` | none (skipped when the body is unchanged) |

Any other modeling type has no entry. It becomes a gap with the reason of its table entry (`unsupported`). When the
entry gives none, the reason is "Steps of type thicken are not copied." (`design_model.words.unsupported_type`, which both outputs use). These are the
types that the add-in does not copy, with the reason and the cause of the hint (the table of causes is in 1.9.3):

| Fusion type | Reason | Cause |
| --- | --- | --- |
| `DeleteFaceFeature` | "Steps of type delete face are not copied." | `deleteFace` |
| `ThickenFeature` | "Steps of type thicken are not copied." | `surface` |
| `StitchFeature` | "Steps of type stitch are not copied." | `surface` |
| `OffsetFeature` (surface offset) | "Offsetting a surface is not copied." | `surface` |
| `BoundaryFillFeature` | "Boundary Fill is not copied." | `boundaryFill` |
| `ReplaceFaceFeature` | "Replace Face is not copied." | `replaceFace` |
| `RibFeature`, `WebFeature` | "Rib is not copied.", "Web is not copied." | `ribWeb` |

Scale, Replace Face, Rib, Web and the surface Offset also have the flag `reaches_bodies`. The Path Pattern has it too. They can change
or take bodies of another component, so the capture walk measures the body around them also when they sit in another
component. A coil, a modelled thread, a path pattern and a scale are copied, so they are not in this table (3.12, 3.13, 3.17 and
3.18). A path pattern that is left out keeps the cause `pathPattern`. A scale that is left out keeps the cause `scale`.

A second table, `RECIPE_KINDS`, lists the recipe step kinds the translator writes (`extrude`, `revolve`, `hole`,
`round`, `bevel`, `shell`, `offsetFaces`, `pattern`, `mirror`, `toolBody`, `move`, `loft`, `sweep`, `draft`, `thread`,
`coil`, `scale`). Each kind has the recipe version that brought it, and the paths of its points and directions (so `place.place`
can move the recipe into the assembly and turn it for Y up). The `thread` and the `coil` use the base recipe version.
The `scale` kind (version 17) also has `factors`: the path of its per-axis factors. `place.place` does not move these
values. It puts each factor on the axis that the map turns its axis to.

A kind can also say that it may not stand inside a tool body (`in_tool` is false). This holds for `thread` and `coil`,
and for `skin` and `bevelGear`, which the translator never writes. These kinds build on the whole part. `tool_words` is
the plain name of the kind in the refusal "A coil cannot be part of a tool body that has other steps." `tool_cause`
selects the hint of that refusal (`coilTool` or `threadTool`). `step_walk.tool_refusal` makes the refusal, and the code of
a Combine and of a pattern of bodies calls it before it writes a tool step (see 3.5).

`docs/adding-a-step-type.md` explains how to add a new type: a table entry, a reader in `READERS` and a handler in
`translator/handlers.py`. Read it before you add a handler.

#### 1.9.3 Gaps, stops and the cap of 256

A step the copy cannot hold has two possible outcomes:

- A gap (the step is "left out"). The walk goes on without the step. The recipe is still written. The gap is recorded
  with its reason, its place in the recipe and the step's Fusion data. Paramability opens such a part with the original
  STEP shape and an unfinished copy beside it.
- A stop (the copy "stops"). The walk ends at the step. No recipe is written. The part is saved as a fixed shape: the
  STEP plus the parameters as variables. The verdict of the item is `unsupported` and `report.json` has `refusal`.

The rule: a step is left out when its effect stays on the body and the rest of the timeline still reads right without
it. Everything that leaves the body unknown stops the copy. Section 3.10 has the full list.

A gap also stops the copy in these cases (`stop_reason` in `lib/translator/gaps/stops.py`):

- the walk has not written a first step yet (a gap needs a body to add to);
- the walk is inside a tool body of another component;
- the part already holds 256 gaps (`MAX_GAPS = 256`, the most a gaps file holds). The 257th gap stops
  the copy with "More than 256 steps of this part cannot be copied." Gaps inside tool bodies count too. A tool walk
  that meets the cap stops the whole copy.

Before this version the cap was 16. A part with 17 or more gaps became a fixed shape. Now such a part keeps its recipe
and every gap, and it opens in the app as an unfinished copy that the person can repair. The gaps file is version 3 (see 1.10). Before
version 0.11.2 a part with 16 gaps or fewer got a version 1 file, so an older app still opened it. Now every gaps file
is version 3, so the app must be a release that reads version 3.

Later picking steps count as gaps until the reach read clears them. This is why the pipeline also runs the reach read
when the first translation stopped only because of the cap (`TranslateResult.over_gap_cap`).

What a left out step would have recorded (doubts, notes) is dropped with it. So a step that is not written never
fixes or marks a size by itself.

A join that would float. An extrude join can meet only material of a step that was left out. Example: a rib stands
on a floor, and the Combine that made the floor is a gap. In the copy the rib would float apart from the part. The
app's kernel refuses a step that leaves the part in separate pieces, so this one step would stop the whole copy. So
the walk leaves such a join out too (`faces/floating.py`), with the reason "It sits on a step that was left out, so it would
float apart from the copy." It decides this from its own model of the copied part (the placers):

1. It samples the faces of the join and a thin band round them closely.
2. It samples the inside of the join and the band on a coarse grid.
3. Where the box of a step of the model comes near the band, it samples closely again.
4. When any sample meets material of the model, the join is kept.

On any doubt the join is kept: a step of the model whose box cannot be told, a step that adds material in a way the
check does not model (a revolve, a loft, an extrude up to a face), a thin join, or more than 20000 sample points. The
gap of a left-out join lists in `dependsOn` the gaps it sits on (`floating.sat_on`). Its cause is `afterGap`, so its
hint says to fix the step it builds on first. `docs/recipe-gaps.md` gives the
order in which those gaps are picked.

#### Causes and hints

Every gap has a cause. The cause is a short code that says why the step was left out, for example `taperSteep` or
`guideSurface`. The cause selects a hint. The hint is one plain sentence that tells the person what to change in
Fusion so that the step copies. One table in `lib/capture_model/gap_hints.py` holds every cause and its hint.

Where a cause comes from:

- A handler gives it with its refusal: `Refusal(reason, cause=...)`.
- A step type with no handler gets it from the step kind table (`StepType.gap_cause`).
- The walk gives it to a step that reaches into another component (`otherComponent`) and to a step that picks faces of
  a gap (`afterGap`). A refusal with no cause that names the gaps it depends on also gets `afterGap`
  (`gap_hints.refusal_cause`).
- A Combine left out because a step of its tool body cannot be copied gets the cause of that inner step. The tool walk
  keeps it in `TranslateResult.refusal_cause`, and `tool_walk.cannot_copy` passes it on. So a tool built with a thicken
  gets the hint for surface work.
- A step that stops the copy gives its cause to the refusal of the walk (`TranslateResult.refusal_cause`). The `refusal`
  record then has a `hint` (`walk._refusal`). The early warning in the dialog shows it as "Tip: ...", and the package
  note adds it when it fits (`notes.step_only_note`). Before, only a gap had a hint.

A refusal with no cause, and a step type with no cause in the table, give no hint. The table follows the app's user
guide page "Steps that do not copy yet", in the chapter "Designing in Fusion (experimental)". When the two do not
agree, the guide is right and the hint must change. `tests/test_gap_hints.py` checks that every cause the translator
gives has a hint, and that every hint is used.

The hint goes into the gap record as `hint` (see 1.10). The result window shows it after the reason, as "Tip: ...".
Example, made up: a cut with a taper of 50 degrees is left out with "The taper of this extrude is too steep to copy."
and the tip "Use a taper under 45 degrees, or draw the sloped wall in the sketch."

The table of causes. The column "Given by" says which code gives the cause. The hint is the sentence of
`lib/capture_model/gap_hints.py` (`HINTS`).

| Cause | Given by | Hint |
| --- | --- | --- |
| `deleteFace` | the step type Delete Face | Cut the shape away with an extrude cut, or change the step that made the face. |
| `surface` | the step types thicken, stitch and surface offset; a sweep or a loft that makes a surface | Build the solid with an extrude, sweep, loft or shell. |
| `draftSteep` | a draft of 30 degrees or more (`finishes/draft.py`) | Draw the sloped wall in the sketch, or give the extrude a taper. |
| `taperSteep` | an extrude or a sweep with a taper that is too steep | Use a taper under 45 degrees, or draw the sloped wall in the sketch. |
| `taperCutBothWays` | a tapered cut through all, both ways | Make two tapered cuts through all, one for each way, or give the cut a distance. |
| `extrudeEndFace` | an extrude that starts or ends on a face it cannot follow (a surface that is not flat or a tilted one), or ends on a tilted or curved face in a way the app cannot build (`extrude/up_to.py`, section "Extrudes: a tilted or curved end face, a start at a distance from a face, an intersect to two sides") | Start and end on flat faces or planes, or give a distance. |
| `extrudeStartOffset` | an extrude that starts at a distance from a face or plane, when the measured start face or end cap does not show which way the distance goes (same section) | Start the extrude on the face itself, or on a plane at that distance from the face. |
| `extrudeWay` | an extrude whose measured faces and body do not show which way it goes (`WAY_UNSURE` of `design_model/steps/extrude.py`) | End the extrude on a flat face or plane, or give it a distance. |
| `throughAllAdds` | a join or a new body extruded through all that the add-in cannot copy: both ways, with a taper or a thin wall, a new body, one in the walk of a tool body or of a body before a split, or an end that the capture does not show on the far side of the body (`extrude/through.py`, "A join through all"; the Orca output gives the same cause for every join or new body through all) | Give the extrude a distance, or end it on a face or plane. |
| `throughAllBodies` | a join through all that joins other bodies too, so the add-in cannot tell where Fusion ends it (`extrude/through.py`) | Let the extrude join only this body, or give it a distance. |
| `thinOutline` | a thin extrude of an outline with holes or of several outlines, or of an open line that the copy cannot hold (arcs, lines that run against it or do not join, a corner past 135 degrees, a wall that does not keep its shape, faces that do not show the side of the wall) | Draw one closed outline for the wall, or shell a solid body. |
| `roundKind` | a round of a kind the copy does not write, a round by chord length whose faces turn along the edge, a changing radius that does not change evenly | Use a fillet with one radius. |
| `roundChanging` | a changing radius on more than one edge, with other sets in its fillet, with radii between the ends, or on an edge that is not straight or an arc (`finishes/measured_rounds.py`) | Give the changing radius a fillet of its own with one edge and no radii between the ends. |
| `shellKind` | a shell that grows its wall both inward and outward, or one with corners that are not sharp or rounded (`finishes/finish.py`, see 3.19) | Shell one way only, inward or outward, with sharp or rounded corners. |
| `repeatFaces` | a pattern or a mirror of faces or bodies (`repeat/repeat_sources.py`) | Pattern or mirror the feature or the body. |
| `sweepKind` | a sweep with a rail, or one that both twists and tapers | Use a twist or a taper alone, or a loft between two outlines. |
| `twistLong` | a sweep with a twist of more than 3600 degrees | Use a twist of 3600 degrees or less. |
| `partOfPath` | a sweep along a part of its path | Sweep along the whole path. |
| `guideSurface` | a sweep with a guide surface | Sweep along the same path without the guide surface, or build the shape with a loft. |
| `sharpCorner` | a sweep path with a corner that is too sharp | Round the sharp corner of the path with a sketch fillet. |
| `loftKind` | a loft along a centre line, or with rails | Build it from lofts of two outlines each, or from extrudes. |
| `threadProfile` | a thread that is not a 60 degree metric or Unified form, or is tapered (3.12) | Use a metric or Unified thread (60 degrees) that is not tapered, or a cosmetic thread. |
| `threadLimits` | a pitch outside 0.2 to 10 mm, more than 8 threads, or more than 100 turns in all | Use a pitch of 0.2 to 10 mm, at most 100 turns in all and 8 threads, or a cosmetic thread. |
| `threadTool` | a thread that would stand in a tool body with other steps | Make the thread on the finished part, not on a body that is combined later, or use a cosmetic thread. |
| `threadHole` | the modeled thread of a tapped hole whose depth, start or end cannot be measured or does not agree with the faces of the thread (section "A tapped hole") | Make the thread of the hole cosmetic: the hole then copies at its drill size, without the thread. |
| `holeEnd` | a hole whose end faces are flat and pointed at the same time, so the shape of its end cannot be told | Let the hole end inside the part with a flat or pointed end, or make it go through all. |
| `coil` | any other coil that does not copy (an older export, sizes that could not be read, a shape that is not a plain helix) | Your AI assistant can add a coil to the copy. |
| `coilSpiral` | a spiral (3.13) | Use a coil with a height, or let your AI assistant add the spiral to the copy. |
| `coilTaper` | a coil with a taper angle | Use a taper angle of 0, or let your AI assistant add the taper to the copy. |
| `coilPlace` | a coil whose place cannot be worked out from its end faces, or whose operation cannot be told | Make the coil a new body, then join it to the part with a combine. |
| `coilLimit` | more than 8 coils, or more than 100 turns of coils and threads in all | A copy holds up to 8 coils and 100 turns of coils and threads in all. Your AI assistant can add the rest. |
| `coilHalf` | revolutions that end in a half turn | Use revolutions that do not end in a half, such as 3.25 or 4. |
| `coilTool` | a coil that would stand in a tool body with other steps | Join the coil to the part with a combine before you move or change it. |
| `pipe` | a pipe with a square or triangle section; every pipe in the Orca output | Draw the section on a sketch square to the path at its start, and sweep it along the path. |
| `pipePartOfPath` | a pipe along a part of its path | Let the pipe run along the whole path. |
| `scale` | a Scale that is left out (it also scales sketches, it cannot be read, or the measured body does not agree with it), and every Scale in the Orca copy | Change the sizes in the sketches instead of scaling the body. |
| `moveUnmeasured` | a Move whose body could not be measured before and after it: the body or its box was not found, or a body with no corners turns or follows a point (`bodies/move.py`) | Draw the sketch of the body where the body should be, instead of moving the body. |
| `offsetCurved` | a Press Pull (Offset Faces) that moves a curved face other than a whole round face, or a round face it cannot move, also with flat faces in the same step (`finishes/offset.py`, `finishes/offset_round.py`) | Press Pull flat faces only, or change the size of the curved face in its sketch. |
| `replaceFace` | the step type Replace Face | Cut the shape with an extrude, or extrude the face up to the shape you want. |
| `ribWeb` | the step types Rib and Web | Draw the rib or web outline in a sketch and extrude it. |
| `pathPattern` | a path pattern that is not copied (a path that is not one line, arc or circle, copies on both sides of the start point, copies that keep their direction on a round path, copies past the end of the path) | Use a rectangular or circular pattern, or a mirror. |
| `revolveSides` | a revolve to two sides whose start face does not tell which side each angle turns to (3.14) | Make two revolves, one to each side of the sketch. |
| `revolveAxisSide` | a revolve whose outline would reach or cross its axis inside size ranges that the person typed (3.14) | Type size ranges that keep the outline on one side of the axis, or leave the ranges to the add-in. |
| `boundaryFill` | the step type Boundary Fill | Build the solid with extrudes and cuts instead of filling a boundary. |
| `newComponent` | an extrude, revolve, loft or sweep that makes a new component | Make the body in the component that holds the part. |
| `otherComponent` | a step that reaches into another component (the walk) | Use sketches, planes and faces of the part's own component. |
| `oldExport` | a step whose only records of another component are sketch outlines, planes or axes, in a capture that an add-in before 0.10.6 read (`addin` of the capture, `refs.old_writer`) | Export again with this version of the add-in. |
| `changedFromOtherComponent` | a step of another component that changes the part (a stop) | Make the step in the part's own component, or export both parts together. |
| `madeInOtherComponent` | a body that was made in another component and moved here later (a stop) | Model the body in the component you export, or export the component that holds it. |
| `afterGap` | a step that picks faces of a gap, repeats a gap, sits on a floating join, or extrudes through all to the far side of a part that a gap may change | Fix the step it builds on first. |
| `addinError` | a step whose handling raised an error that the add-in did not expect (a stop, 1.9.1) | Send the report and the file export-trail.log from the ParamabilityExport temp folder with it. |
| `refused`, `unsupported` | a refusal with no cause, or a step type with no handler and no cause | no hint |

A step that does not copy is told in the app's user guide page "Steps that do not copy yet". `tests/test_gap_hints.py`
checks that every cause that the translator gives has a hint and that every hint is used.

After the walk, each gap gets its place in the final recipe (`gaps/gap_place.py`, `place_all`): `after` (the last step written
before it that is still in the recipe), `before` (the step after that one in the same list) and `list` (the
`toolBody` step that holds the list, or null). `gaps/gap_file.py`, `record`, writes the record for the gaps file (see 1.10).

#### 1.9.4 after_stop

When the copy stops, the person would see only the first failing step. They fix it in Fusion, export again, and meet
the next one. To avoid this, `translate()` runs `_diagnosis` after a stop. It is one more walk, without sizes, with
`Context.diagnose = True`. In this walk every stop becomes a gap and there is no cap.

The result goes to `report.json` as `after_stop`:

```json
"after_stop": {
  "stopped_at": 9,
  "items": [ ... verdicts of the steps after the stop ... ],
  "steps": [
    { "index": 9, "name": "Split1", "type": "SplitBodyFeature", "reason": "This split cuts along a curved surface ..." },
    { "index": 14, "name": "Thicken1", "type": "ThickenFeature", "reason": "Steps of type thicken are not copied." }
  ]
}
```

The manifest gets a second note: "Not copied either: Thicken1." (`notes.also_failing_note`). The package stays a fixed
shape with the same refusal. `after_stop` only explains. It never changes the export. When even the diagnosis walk
has to stop (for example at the first step), its last entry has `stops: true`.

#### 1.9.5 Loose, cut, fixed and dropped sizes

A ticked size ends in one of these states. The words are used everywhere: in the code, in `report.json`, in the
result window and in the app.

| State | Meaning | Where you see it |
| --- | --- | --- |
| free | A size of the recipe. Every value that reads it follows it. | `sizes.free` |
| loose (marked) | A free size, but some value cannot follow it and keeps its number. The app shows a warning mark. Reason: "<name> may give unexpected results: ...". | `sizes.loose`, manifest `loose` |
| cut | A free size whose range was made shorter. The app shows a quiet info mark, not a warning. Reason: "<name>: the range stops at 68.75, since ...". | `sizes.cut`, manifest `cuts` |
| fixed | Not a size: it became a plain number, since a free size would make the recipe invalid. Today only a formula too long to write does this. | `sizes.fixed`, manifest `fixed` |
| dropped | Ticked, but no written formula reads it. Reason: "<name> is not a size: ..." or "... is not used by any copied step". | `sizes.dropped` |

A size can be both loose and cut.

How the translator gets there. A handler reports a value it cannot follow with `ctx.doubt(names, why)`. The value is
then written as its number. `translate()` walks in two phases (`_settle`):

1. First phase: every doubted size is made a plain number in a new size table (`with_fixed`), and the walk runs again,
   until no new size is doubted (at most 70 passes, `MAX_PASSES`). This phase learns which sizes are doubted and why.
2. Second phase: the doubted sizes stay free. Every value that can follow them still does. The values that cannot
   follow keep their numbers. So the shape at the current values is the same, and the other values still move.

The doubts become `loose`. A doubt with `fixed=True` (a formula too long to write) makes the size `fixed`. A doubt
with `cut` ranges (`ctx.cut(ranges, why)`) cuts the range instead of marking the size.

A doubted size that no formula reads after the second phase is `dropped` with `used: true`.

The end of walk audit (`lib/translator/audit.py`) runs after the last walk. It checks every free size that a copied
step reads. The size must be read by a written formula, or be fixed, loose or dropped with a reason. A step reads a
size through its `data.params`, the sketches it uses and the construction geometry it uses. A handler must "ask" for
each `data.params` path (`values.quantity`, `values.pin` or `values.handled`). A path that reads a free size and that
no handler asked for makes the size loose with "<step> reads it, and the copy does not follow it". So a value a
handler forgot gives a warning, not a wrong part.

The audit also drops a sketch size that the probe measured and that moves nothing ("changes nothing in the copied
steps"), and a size that the probe tried and that changed nothing in the part ("it was tried at other values, and it
changes nothing in this part").

The text "changes nothing" must be true. Thus the translator looks at the body that the probe read at each try that
set that size alone (`Motion.body_changes`, `translate._dropped`). The probe compares the box and the volume of the
body with the first read. A try tells that the body stayed the same only when it and the first read hold
the box and the volume (`probe.state.body_compared`).

- The body read the same at each such try. Then the size is dropped with "it was tried at other values, and it
  changes nothing in this part" (`used` false, `tried` true).
- The body changed at one such try, and no written formula reads the size. Then the copy cannot follow the size. The
  size is dropped with "it changes this part in a way the copy does not follow" (`used` true). The copy keeps the
  value now, so the part is correct at that value.
- The probe did not read the box and the volume at such a try (an older export). Then the size gets the plain
  reason "is not used by any copied step" (`used` false, no `tried`).

A try where a sketch landed on another solution (`apart`), or where a size is past the values where its outlines
hold (`outside`), does not count. The body change there does not come from the size alone.

A size that only gaps read stays a size. It is loose with "Fusion uses it only in Extrude5, a step the export could
not copy, so it changes nothing in the copy yet." (`_gap_sizes`). So the missing step can use it later.

#### 1.9.6 Formulas and the 300 character cap

`values.quantity(ctx, item, path, literal, dim=...)` (`lib/translator/values.py`) is the one way a handler writes a
value that a parameter may drive. It does this:

1. It looks for `data.params[path]`. Without it, the value is a plain number.
2. It translates the Fusion expression into a recipe formula over the sizes (`SizeTable.translate`). The formula
   grammar is described in `docs/expressions.md`.
3. It checks the formula at the current values (`params/expressions/evaluation.py`: `evaluate` for the text of a
   formula, `evaluate_tree` for a parsed tree). It must give the number Fusion measured within 1e-6. Else the sizes
   are doubted: "its formula in Extrude2 does not match what Fusion measured".
4. It checks the length of the formula. The app accepts at most 300 characters (`MAX_FORMULA_LENGTH` in
   `params/expressions/text.py`). A longer formula is doubted.
5. A count must give whole numbers at every size value (the whole-number check in `values.py`). It reads the parsed
   formula and accepts it when it is built from whole parts: whole number literals, count sizes, derived sizes that
   are whole, `+`, `-` and `*`, `round`, `floor` and `ceil` of anything, `min`, `max` and `abs` of whole parts, `mod`
   of whole parts, `pow` of a whole part to a whole literal of 0 or more, and a choice `test ? a : b` whose two
   results are whole (the test can be anything). A division or a decimal literal makes the count not whole. The
   count is then written as its number and its sizes are marked. The check follows derived sizes up to 8 levels deep.
6. A length that the step needs above zero (`absolute=True`) must stay above zero over the whole size range. A count
   (`whole=True`) must stay at 1 or more. The check tries every mix of the range ends (`range_check.sweep`). When the
   value leaves that range, the add-in cuts the ranges of the untyped sizes that it reads, so that the value stays
   above 0.005 (a count at 1 or more), and keeps the formula (`_kept_above`). An angle the step needs above zero gets
   the same cut. When no cut keeps the value (every size it reads has a typed range, or the value now is outside),
   the value is written as its number, and its sizes are marked.

   Example. A join of length `Tall - Low` sits on a part of height `Low`. `Low` goes from 5 to 20 mm, and `Tall` from
   15 to 60 mm. At `Low` 20 and `Tall` 15 the length is -5 mm. So the add-in cuts the ranges where the length stays
   above zero: `Low` stops at 17.99 and `Tall` starts at 18.01. The length stays `Tall - Low`, and both sizes stay
   free. If the length became a number instead, the join would stay 20 mm high while `Low` moves its start.
7. It returns a `Quantity` (`lib/design_model/values.py`, shared with the Orca output): the number plus the formula and
   the Fusion names it reads. `.json()` writes
   `{ "expr": "..." }` or a plain number.

Some formulas are built later from several values, for example a plane's move minus another plane's move. They can
pass 300 characters. `_fix_long_formulas` in `translate.py` first adds up equal terms (`collected_sum`:
`a + 2 * b - (b + 1) + 3` becomes `a + b + 2`). A size whose terms cancel is no longer read. A formula still too long
fixes the sizes it reads (`fixed=True`). This is the main source of `sizes.fixed`.

One source of long formulas is now smaller. A round or a chamfer can pick an end face by a point inside it. Before,
that point always followed the centre of all outline corners, and its formula summed every corner. Now it follows one
corner when it can (see 3.3, "A point on an earlier extrude"). Its formula is then a few times shorter.

#### 1.9.7 Where the recipe sits

The capture is in the component's coordinates. The STEP file is in the design's coordinates. The recipe must land
where the STEP lands. So `_walk` ends with `place.place(recipe, rigid.move_for(capture))`. `place.place` is in `lib/translator/place.py` and `rigid.move_for` (the
rigid map of the part's frame, `Move`) is in `lib/geometry/rigid.py`. This moves every point
and turns every direction of every step by the part's place in the assembly. For a Y up design it also turns
(x, y, z) to (x, -z, y), since a recipe is always Z up. The paths of the points and directions of each step kind come
from `RECIPE_KINDS`.

The gaps file does not move the raw `data` of a gap. It gives `toRecipe` instead: 12 numbers (a 3 by 3 rotation by
rows, then the offset) that map a point of the capture to the recipe.

The recipe version is the lowest version that holds every written step and selector: 12 as the base, 13 with an
`offsetFaces` step, 14 with a `chain` or `faceEdges` pick, 15 with a `toolBody` or `move` step or a pattern of more
than 64 copies, 16 with a sweep that has `twistDeg`, `taperDeg`, `orientation` or a closed path, 17 with a `scale`
step, a shell that grows outward, rounds its corners or has no open faces, a draft with `angleTwoDeg`, or an
`offsetFaces` step that moves a round face. So a simple part still opens in an older app.

The step of a round face has no field that shows version 17. So the handler writes it as a `NewerStep`
(`lib/translator/result.py`). This is a plain dict for JSON, with the attribute `version`. `translate.py` reads this
attribute from each written step and takes it into the version.

`_over_caps` checks the app's limits at the current values: at most 400 steps, tool steps nested at most 3 deep, at most
256 copies per pattern. A limit that is broken stops the copy. A pattern count that can pass its limit somewhere in the
size ranges marks the sizes it reads.

### 1.10 The package

`plan_single_export` in `lib/export_plan/recipe_export.py` turns the results into files. `write_package`
(`lib/package/writer.py`) writes them into one zip with the extension `.paramability`. The zip is written to a
temporary file beside the target and then renamed, so a failed export never leaves half a file.

#### Package kinds

| `kind` | When | Files |
| --- | --- | --- |
| `recipe` | The translation gave a recipe. | `manifest.json`, `part.step`, `recipe.json`, `report.json`, and `gaps.json` when steps were left out (up to 256) |
| `stepOnly` | The copy stopped, the capture failed or the translator raised. | `manifest.json`, `part.step`, `report.json` |
| `parts` | Several bodies were picked. | `manifest.json`, `parts/NN/part.step`, `parts/NN/recipe.json`, `parts/NN/gaps.json`, one `report.json` |
| `valueRows` | "Export size choices" with two or more rows. | `manifest.json`, `rows/NN.step` |

Whatever goes wrong while reading or translating, the person still gets the STEP as a `stepOnly` package with one
plain note. This is the fallback of every failure.

#### The manifest

`manifest.json` (schema `paramability.recipePackage`) holds:

- `schema`, `version`, `kind`, `name` (the design title), `upAxis` (`z` or `y`, for the STEP only), `writer` (for
  example "Paramability Fusion export 0.11.0, Fusion 2.0.21508");
- `notes`: at most 5 short sentences. The app shows the first one when the file opens. `_most_useful` ranks them: the
  step count first ("12 steps copied from Fusion."), then the left out steps, then the loose, cut and fixed sizes,
  then a note about doubtful measures or a note that the part follows the sizes of a component that is not in the file
  ("This part follows the sizes of FilterBox. Export both together so they change together."), then "N sizes are
  ready to put on the form.", then the notes about dropped sizes;
- `parameters`: every user parameter of the design, up to 64 (`params/listing.py`): `name`, `label` (the Fusion name,
  not the readable label of the form), `value`,
  `unit`, `comment`, and `expr` for a formula the add-in could write. A formula it could not write keeps `expression`
  (Fusion's text) and `untranslated` (the reason). The parameters come along also when the shape is fixed, so the
  person gets them as variables;
- for a recipe: `part`, `recipe`, `checks` (always empty: the add-in writes no size checks), `fixed`, `loose`, `cuts`
  and `gaps` (the path of the gaps file).

The manifest version is 1. It is 2 only when the package names a gaps file. An older app then refuses the file as "made
by a newer exporter" instead of showing an unfinished copy as a finished part.

`validate_manifest` (`lib/package/manifest.py`) checks the package rules locally before the file is written. A broken
rule raises `ValueError`. The app stays the authority: it checks again when it opens the file. `lib/package/caps.py`
checks the byte limits of the app: 256 MB per STEP, 1 GB in all, 200 files, 1 MB per gaps file. A recipe above 8 MB is
not written (the part becomes a fixed shape with "The recipe is too large to open.").

#### recipe.json

```json
{ "schema": "paramability.recipe", "version": 12, "features": [ ... ], "sizesAsWritten": true,
  "sizes": { "Width": { "kind": "length", "value": 40, "min": 20, "max": 68.75, "label": "Box width" },
             "Inner": { "expr": "Width - 2 * Wall", "label": "Inner width" } } }
```

`label` is the readable text of the form (see 1.3, "The label of a size"). In this example the parameters have the
comments "Box width" and "Inner width".

`sizes` holds the free sizes that a written formula reads, the derived sizes those formulas read, and the sizes only
gaps read. `sizesAsWritten: true` tells the app to keep the sizes as written and not to look for more sizes in the
numbers. The marker is in every recipe, also in one that has no `sizes` (`translate()` writes it for a recipe with a
size table and for one without). Version 12 of the format brought the marker, so it does not raise the version. The
app also reads the marker as "an add-in wrote this recipe": it then builds the lofts as the recipe says and does not
change them to make them build. So a recipe with no `sizes` needs the marker too. In an export from the add-in the
size table always exists, so the file was already marked; the translation for the stop warning has no table and is
not written to a file.

The recipe format is published by the Paramability app as JSON schemas (copies are in `tests/schema/`).

#### gaps.json

Only when steps were left out. One record per gap. `docs/recipe-gaps.md` describes every field.

The file has a version. `package/gaps_file.py` always writes version 3. Version 2 allowed more gaps (256 instead of
16). Version 3 added `finishing`. An app that does not know version 3 refuses the gaps file, and then opens the part
as a fixed shape. So release the add-in after the app release that reads version 3. The schemas are published with the
app, and copies are in the add-in's `tests/schema/`.

The main fields of a gap record:

| Field | Meaning |
| --- | --- |
| `id` | `gap_<timeline index>`. The step added later for this gap takes this id, so the app knows which gaps are filled. |
| `name`, `type`, `words` | The Fusion name and type, and the type in words. |
| `reason` | Why it was left out, at most 200 characters. |
| `hint` | What to change in Fusion so the step copies, from the gap's cause (see 1.9.3). Left out when the cause has no hint. |
| `after`, `before`, `list` | Where the step belongs in the recipe. |
| `dependsOn` | Earlier gaps whose faces it picks, whose steps it repeats, or that a floating join sits on. |
| `sizes`, `looseSizes` | The recipe sizes it reads, and those loose only because of it. |
| `values` | Per `data.params` value: the Fusion expression and the recipe formula when one exists. |
| `bodyBefore`, `bodyAfter` | Box and volume of the part around the step, in recipe coordinates. |
| `data` | The step's capture data as the reader wrote it, cut to 48 KiB. |
| `trimmed` | True when `data` was cut. |
| `finishing` | True when the step only finishes surfaces: a round, a bevel, a draft, an emboss or deboss, or a thread whose data says `modeled` is false (the `finishing` trait of the step kind table, read by `gaps/finishing.py`, `is_finishing`). When only such steps are missing and the copy matches, the app shows the editable copy first. The app reads this flag and no Fusion type names. |

#### report.json

`report.json` is the full record for debugging. The app never reads it. It holds the capture, the verdicts, the probe
record, the sizes and the health. Section 4.2 explains it field by field.

#### Several bodies

`run_parts_pipeline` (`lib/export_plan/pipeline/parts.py`, class `PartsPipeline`) does the same for up to 32 bodies.
It has its own port interface (`PartsPort`, in the same file): the calls take the body index. It uses the same
`PutBack` and the same `ProbeRun` as the export of one body. Differences:

- One STEP per body. One capture per body.
- One size table for all bodies. A parameter is one size for every body that reads it.
- One probe run for all bodies (`ProbeGroup`): the same rows, one read per body per row. The 64 rows are for the whole
  export, not per body.
- A size fixed in one body is fixed in all. A size loose in one body is loose in all, and the reason starts with the
  body names. A cut range is the narrowest over the bodies (`PartsPipeline._share_cuts`, which calls `shared_cuts(table, probed)`).
- A body that cannot be copied is a fixed shape beside the editable ones, with its own note.
- A size that also moves a body that stays a fixed shape in the same file is listed as loose. `export_plan/fixed_parts.py`
  (`marked` and `joined`) does this, called from `plan_parts_export`. A size moves a fixed part when the model
  parameters in the scope of that part, its quantity references or its geometry links reach it (`body_scope.scope_inputs`
  and `body_links`). The reason is "<Part> stays a fixed shape in this file and does not change with this size." (up to
  three names, then "and N more"). It goes in front of an older reason of the same size, so the part is still named
  when the reason is cut to the length of the manifest. The size stays free and is marked loose. It is not made fixed. A
  part with no capture marks nothing. The other bodies change with the size, and the fixed one does not.
- A note names the components that are not in the file but whose sizes the copy follows (`follows_components_note`
  with `parts=True`). The record behind it is `TranslateResult.follows_components` (`[{ token, name }]`). The translator
  fills it from the other components whose sizes a written step follows: a measured reference, a borrowed outline, and a
  sketch tied to a component that the probe saw move (`Context.follow_component` and `Audit.follows`). Steps inside a
  tool body walk do not add to it. In a parts file, a component whose body is one of the parts is left out
  (`recipe_export.followed_outside`). `report.json` does not hold this record. Only the manifest note shows it.
- `report.json` has a `parts` list with one record per body: `name`, `outcome`, `items`, `notes`, `capture`, `probe`,
  `sizes`, `derived`, and `refusal`, `after_stop`, `gaps`, `reach` when they apply. `sizes`, `health`, `parameters`
  and `also_changes` are at the top.

### 1.11 After the export, in Fusion

When the file is written, `_show_result` in `export_flow.py` shows a result window (`lib/fusion_ui/result_dialog.py`).
The texts come from `lib/dialog_model/result_rows.py`. The window has sections, each with a `# Title` line. A section
with nothing to say is left out:

- `# Check your design` (first, and only when something went wrong): a parameter that did not go back, timeline
  steps whose health differs from the start, sketches that did not come back to their first shape, sketches that
  could not be checked or measured, sketches left with their compute deferred (`health_lines`);
- `# Result`: the file, whether it is an editable copy (or one with steps left out) and how many parameters come along.
  When the size tries stopped at the time limit, a line says so and how many sizes were not tried (`time_stop_lines`);
- `# Sizes`: one line per size with its range and its state ("may be unexpected", "range cut", "kept fixed",
  "not followed", "not used") and the short reason;
- `# Left out`: each step left out, with its reason and, when the gap has one, "Tip: " and its hint (see 1.9.3);
- `# More sizes`: unticked parameters that also change the part (from the discovery rows), and parameters that could
  not be tried.

A part saved as a fixed shape gets a message box instead. Its first line names the stopping step. Fusion's status line
(bottom right) shows a short form of the same (`lib/fusion_ui/notice.py`). When the design may be changed (a parameter
not put back, sketch drift, a step worse than at the start, a sketch left deferred), a message box with the health
lines comes first. A step worse than at the start counts also when it is past the eight steps that `report.json` lists
(`health.steps_worse`).

#### What an export changes, and how each is put back

An export changes the design in these ways. Each row says how it is put back and what can still leave a step in
another state than before. One object does all the put backs of one export, in one fixed order: `PutBack`
(`lib/export_plan/pipeline/put_back.py`). The table is the list of what it brings back. The order is below the table.

| Change | Put back by | What can still differ |
| --- | --- | --- |
| Parameter values (the tries) | `RowExport` puts every expression back before each row and at the end (`restore_parameters`): one `Design.modifyParameters`, the expressions read back as text, any that did not take set one by one, then `computeAll`. `PutBack.restore` does the same at every point of the end (after the tries, in `settle`, in `close` and in `close_failed`). | The text is back, but the steps were rebuilt from the last try. A step that only solved by luck from its previous solution (a fillet that barely fits, a sketch with two solutions) can land elsewhere. `modifyParameters` rebuilds only the steps it touches, so a step can keep an error or warning that a full rebuild would clear. |
| Timeline marker (capture walk, helper pass, face reads, reach reads, marker roll, temporary copy) | Each read puts it back in a `finally` (`restore_marker`, `put_back`), the store puts it back after every recompute, `unroll_marker` rebuilds once, `PutBack.close` and `PutBack.close_failed` put it back (`TryTimeline.end`), and `run_guarded` puts it back once more at the very end. | Moving the marker rebuilds the steps after it one by one; a risky step can come out of that rebuild in a warning. The capture walk of the dialog runs before the export, so its effect is only seen when the start is read before it (it is, since this change). |
| Suppressed steps (Faster tries) | `TimelineTrim.end` (called by `TryTimeline.end_trim`) turns them on, read back, then one rebuild; `left_off` names those that stay off. The end check below tries again to turn them on. | A step that stays off; the steps after it rebuilt without it. |
| Sketch points (`SketchKeeper.put_back`) | Points more than 0.0001 mm off are moved back with the sketch's compute deferred, then one rebuild. | Moving a point of an under-constrained sketch changes the sketch even when it goes to its old place; a fully constrained sketch may solve to the other side. The compute flag goes back to its start value and is read back (`deferred_left` names a sketch where it would not). |
| Compute calls | `computeAll` in the baseline, after a failed row, after one change with a step in error, in the restore fallback, after unsuppress and unroll. | A full rebuild can show warnings the person's last incremental rebuild did not show: a step reads worse although the export did not change it. |
| Temporary copy (`step_export`) | The occurrence and only the timeline items the copy added are deleted; the marker goes back; leftovers stop the export. | Nothing in the steps before the marker. |
| Selections | `timeline_select` selects the stopping step when the person asks. | Not a design change. No visibility, light bulb or appearance is ever changed. |

#### The put back, in order

`PutBack` is the one place that knows the order. Both pipelines make it at the start (`PutBack.start`) and call it at
fixed points. The order is the same for one body and for several bodies:

1. `start`: save every parameter expression and read the timeline steps (the read the request carries, taken before
   the dialog read the design, else one read now).
2. `hold_timeline`: before the tries, hold the marker early and turn off the items the tries do not use
   (`TryTimeline.begin`). The try runner calls `end_trim` before the discovery rows, since those rows look for links
   to other components.
3. `tries_done(run)` after the tries, and `tries_ended(run)` on every way out of them: the values and the items go
   back, and a sketch left on another solution is put back (`ProbeRun.settle`), before the probe's last read.
4. `settle(read_gap, read_outline_gap)` once the export is made: the values and the items back, the sketch gap read,
   the marker back, the end check of the timeline steps (next part), and the outlines read again when the end check
   rebuilt the design.
5. `close(health)` when the export is made. It puts the values and the marker back once more, names the items that
   stayed off (`_warn_left_off`) and, as its last call, drops the last Undo step when the health record says the design
   is as it was (`undo_steps.drop_after`, see "Lighter on memory").
6. `close_failed()` when the export stops: the values and the marker go back, the person is told which parameters did
   not go back (`port.warn_unrestored`), which timeline steps differ from the start (`_warn_steps`, the end check runs
   here when it did not yet) and which items stayed off. A warning that fails is logged and the next warnings still
   run, so the error or cancel that stopped the export is the one that is raised.

In Export for Paramability, `run_guarded` (in `commands/export_common.py`) no longer puts values back or drops Undo
data. It shows the message boxes and puts the timeline marker back once more at the end. (Export size choices does not
use `PutBack`: it still gives `run_guarded` the restore of its own rows.) The record `health` of the result is made from one
object, `health.HealthInputs` (`lib/export_plan/health.py`): `health.make_health(HealthInputs(...))`, and
`PutBack.health_inputs(probe, probe_error, unchecked, flipped)` fills in what the put back knows. The test that holds
the expected call order for every way an export ends is `tests/test_put_back_order.py` (see 4.11).

#### The end check of the timeline

At the end of every export, once all of the above is back, `settle_timeline` (`lib/design_edit/timeline_health.py`)
checks every timeline step. `PutBack._settle_steps` calls it, once per export. It runs also after a failed or cancelled
export. Step by step:

1. At the start, the add-in reads every step before the marker: its health (fine, warning or error), Fusion's message
   and whether it is turned off. It reads this when the dialog opens, before the dialog reads the capture.
2. At the end, it reads the same again and compares.
3. When a step differs, it turns back on every step that was on at the start and reads off now. This also covers a
   step of the faster tries that would not turn back on. Such a step leaves `left_off` when the end check turns it
   on, so the person gets no separate box about it.
4. It rebuilds the whole design once. The last rebuild may have been one change that rebuilt only some steps.
5. When a step is still worse than at the start, it sets every parameter to its start expression once more, and it
   rebuilds again.
6. When step 4 or 5 ran and the probe followed sketches, it reads the outlines again
   (`PutBack._gap_after_settle`). A rebuild can move a sketch. The gap of that read is
   `health.sketch_gap_after_rebuild_mm`. `sketch_gap_mm` and `sketch_drift` take the larger of this gap and the gap
   read before.
7. What is still different goes to `health.steps_changed` and to the person.

A step that still differs gets one line in the result window. When the export stopped, the same lines come in a
message box. The box about steps of the faster tries that stayed off (`PutBack._warn_left_off`, then `port.warn_left_off`) names
only the steps that the end check does not name already.

The hand tests TH1 to TH6 in `docs/hand-tests.md` check this in Fusion: a fillet that only just fits, a sketch with
two solutions, a chamfer that meets a fillet, a step that already shows a warning, a cancelled and a failed export,
and the faster tries with a second component.

#### Lighter on memory

Fusion keeps Undo data for every rebuild of a command until the command ends. The whole export is one command. So a
long export with many tries can make Fusion grow to many GB. The dialog box "Lighter on memory" is an experiment
against this. It is off to start with.

How it works (`lib/export_plan/undo_steps.py`):

1. With the box ticked, `run_export` makes an `UndoSteps` for the running command and gives it to the port
   (`undo_steps.attach`).
2. At points where every value is back, the tries call `UndoSteps.drop`: before each row (`ProbeRun._before_row`) and
   once after the tries (`ProbeRun.settle`). `drop` calls Fusion's preview call
   `Command.beginStep(makeExistingStepNonUndoable=True)`. Fusion then ends the current step of the command without
   Undo data, and it starts a new step.
3. The add-in puts every value back itself, so nothing should be lost. But Undo may not step back through the export
   afterwards. This is why the dialog shows a line that reminds the person to save first.
4. After the export, one more call drops the Undo data of the last part of the export (`undo_steps.drop_after`,
   called by `PutBack.close` as its last call, not by the command). This happens only when the end check confirms the design is as it was (`health.back_as_it_was`): every value back, no
   sketch drift, no step worse or left off, nothing left deferred, the steps read, the sketches compared and the
   marker back. On any doubt the data is kept, so Undo can still help.

The drop rule is fail safe. When the call is missing, raises or answers False, no further call is made, and the export
goes on as with the box off.

When Undo data was dropped, `health.undo_dropped` is true. Then no line sends the person to Undo. The health lines,
and the box about steps that stayed off, say to close the design without saving and to open the version saved before
the export (`health.NO_UNDO_ADVICE`).

`report.json` keeps the record in `timing.undo` (`on`, `applied`, `steps`, `error`). The hand test UM1 in
`docs/hand-tests.md` checks the memory in Fusion.

### 1.12 What the app does with the file

The Paramability app is a separate project. This section says what it does with a package, so a developer can tell
which side a problem belongs to. The add-in code never runs in the app.

When the person opens a `recipe` package:

1. The app reads the manifest and checks every rule. A wrong required field refuses the file. A wrong optional field
   reads as absent, except `gaps`.
2. It reads `recipe.json` and builds it in its CAD kernel at the sizes as written.
3. It reads `part.step` as a mesh and compares the two shapes: the volume overlap, the typical gap and the largest gap,
   at the "Standard" bar. The answer is one of three levels: it matches, it is close, or it is far off.
4. A match lands as a CAD part that keeps its recipe. The free sizes go on the form ("Put on the form"), each with its
   label, value, Min, Max and step. A `loose` size gets a warning mark with its reason. A `cuts` size gets a quiet
   info mark ("Range shortened."). The `fixed` list shows as "Kept fixed by the export" on the Shape sizes card.
5. A copy that is close, or far off but still builds, is not thrown away. The part keeps the STEP shape (the
   "original") and the recipe beside it (the "editable copy"). A switch on the Shape sizes card shows one or the
   other. The card also shows the gaps between the two surfaces. This is the "copy note" (`RecipeCopyNote`).
6. A recipe that does not build lands the STEP as a fixed shape. The message names the step where the kernel stopped.

The range end check. The add-in cuts the ranges where Fusion fails (3.2). Fusion can build designs that the kernel of
the app cannot. Examples are rounds or chamfers that meet at a corner, and an emboss whose hole reaches past its
outline. The add-in cannot see this. So the app checks the ends itself when it opens a package:

1. It builds every free size at its smallest and at its largest value in its own kernel, with the other sizes at their
   values.
2. An end that does not build is pulled in. A short search halves the gap between the end and the value of the size, up
   to 6 times, and stops at the last value that builds. The end moves only when the kernel names the step that fails. A
   time out, a stopped kernel, a Skip or a spent budget leave the end as it was written.
3. The shorter range is written into the recipe that lands. It is an extra entry in the `cuts` list, with the old end
   and the reason. The card shows "Range shortened". A size that several parts share gets the shortest range that any
   part allows.
4. A package builds at most 80 times for this check, over all its parts (`RANGE_CHECK_BUILDS`). The open dialog shows
   "Skip the range check" beside Cancel while it runs. After a Skip, or for an end that was not checked, the range
   stays as exported and the size is marked "may give unexpected results" ("Its range ends were not checked").

The check proves the two ends. It does not prove every value inside the range. A Fusion size check where the recipe
does not build waits for the range check: once the end is pulled in past the value of that check, the size is not
frozen.

For a package with a gaps file (an "unfinished copy"):

- The part always lands beside the original, and the original shows first. Its build is never stored as the finished
  body, also when it matches.
- An exception: when every missing step is cosmetic (a round, a chamfer, an emboss, or a cosmetic thread) and the
  copy matches or is close, the copy lands shown, with its sizes on the form. The toast says "N small steps are
  missing".
- The copy is built best effort. A step that the kernel cannot build is left out, and the build goes on from the last
  good part. The note lists such a step in `leftOut` with the kernel's reason. Example: a join whose missing steps
  leave it floating apart from the part. So one such step does not turn the whole part into a fixed shape. Before, a
  failed step there made the whole copy fail.
- The gaps file is kept verbatim beside the CAD source (`assets/cad/<id>.gaps.json`), so a saved project keeps it. The
  app reads version 1, 2 and 3 files. A version 1 or 2 file has no `finishing` flag, so the app sets it from the Fusion
  type of each gap. A version 1 file with more than 16 gaps is refused, with a message that says why.
- With assistant mode on, a second message says that the person's AI assistant can add the missing steps.

The AI assistant data. The app has no AI of its own. A person can connect their own AI assistant. The assistant reads
the copy with `object.readRecipeCopy`: the copy note, the recipe (paged) and the gaps, each with its reason, its place,
its sizes, its hint and its Fusion data. It edits the copy with `object.editRecipeCopy`. A step it adds with the id
of a gap fills that gap, but only when the kernel built that step. An edit also builds best effort: a step that does
not build is answered in `leftOut` with its reason, and its gap stays open (`gapsNotBuilt`). After each edit the app
compares the copy with the original again. This is why the add-in keeps so much in
each gap: the name, the reason, the place, the Fusion expressions and the raw data. A good gap lets the assistant (or a
person) redo the step without Fusion.

`report.json` is never read by the app. It is only for you.

## 2. The code map

### 2.1 Packages and layers

The code is in `ParamabilityExport/lib/`, one package per job, plus `ParamabilityExport/commands/`. The packages sit in
layers. A package may import only packages that are lower in the layers, and only those listed for it. The table
`ALLOWED_IMPORTS` in `tests/test_boundary.py` holds the exact list. The add-in `README.md` ("Code layout") gives the same
order. The table below follows that order, lowest layer first. `commands` is on top.

| Package | May import | What it owns |
| --- | --- | --- |
| `package` | nothing | The `.paramability` file: units, manifest builders and checks, caps, file names, zip writer, gaps file bytes. |
| `geometry` | nothing | Pure geometry that the translator, the probe and the reader share: vector helpers (`vec`), the rigid map of a frame (`rigid`: `Move`, `move_for`, `frame_problem`), sketch outlines (`outlines`, `text_outlines`, `footprint`), a region inside another (`region_inside`), 2D helpers on points (`plane2d`), the volume checks of a Combine (`combine_volume`) and the tolerances (`tolerances`). The volume checks take the data of the steps, not the timeline items: the caller reads the data through the shared layer (`design_model.design`). |
| `orca_recipe` | nothing | The OrcaSlicer 2.5 Design tab recipe (features, sketch entities, enums) and its 3MF writer. |
| `capture_model` | `geometry` | What a capture and a recipe step are made of: the step kind table (`step_kinds`), the capture checks (`capture`: `validate_capture`, `CaptureError`, `same_body`), the chain of splits (`lineage`), the items that build tool bodies (`tool_items`), and the gap causes, hints and picks (`gap_hints`, `gap_picks`). |
| `timing` | nothing | Stopwatch helpers and the `timing` block of `report.json`. |
| `params` | `capture_model`, `package` | Fusion parameters as sizes: names, defaults and ranges, the expression parser, the dependency graph, geometry links, the size table, the parameter listing. The geometry links do not read the data of a step. They get the measured references of the steps and the names of the parameters that can place an occurrence as plain values from `design_model/step_links.py`. |
| `sketch_values` | `package` | The motion file (`Affine`, `Stuck`, `Terms`), its keys and the "measured / not measured" answers (`coverage`). |
| `sketch_solve` | `package`, `sketch_values` | A small sketch solver for the shadow check `derived` and for the Orca output. `slots.slot_text(slot)` names a solver slot in words. `constants.constants_of` says which projected entities no size moves. The Orca output uses the extended reading (`extended=True`). In that reading, a line gets its direction from the gap between its two ends when the solver knows that gap on the x axis and on the y axis, also when it does not know the ends. Example: the diagonals of a rectangle. A centre point on the two diagonals then gives the place of the rectangle. The solver reasons are for developers. The Orca output changes them into plain words for the user (`orca_translate/sketches.open_reason`). |
| `design_edit` | `package`, `params` | Changing the design for a while: apply a row, restore parameters, the timeline marker, the timeline health, the temporary copy, and the declared interface of the parameter store (`store.py`). |
| `design_model` | `capture_model`, `geometry`, `package`, `params`, `sketch_solve`, `sketch_values` | The shared layer: facts about the design that every output needs, and doubts about sizes. It does not refuse a step. It records what it finds through a recorder (`recorder.py`). See 2.2. |
| `results` | `design_model` | The shape of what an output says about a timeline item, for both outputs and the dialogs: the verdict (`verdicts.py`: `verdict` and the verdict kinds) and the record of a step left out (`left_out.py`: `left_out`, `item_name`). It holds shapes and the words of a verdict kind, not facts about the design. See 1.9. |
| `translator` | `capture_model`, `design_model`, `geometry`, `package`, `params`, `results`, `sketch_values`, `timing` | A capture in, a recipe and verdicts out. One handler per step kind. |
| `probe` | `capture_model`, `design_model`, `geometry`, `package`, `params`, `sketch_solve`, `sketch_values` | Plans the rows, matches the reads with the capture, fits the motion file. It does not import the translator. It measures the sketch values through the loop writer of the shared layer (`design_model/loops.py`), which the translator also writes with. Thus a measured value is the value that the translator writes. The range cuts of the tries (`design_model/tried_ranges.py`) are also in the shared layer. |
| `orca_translate` | `capture_model`, `design_model`, `geometry`, `orca_recipe`, `params`, `results`, `sketch_solve`, `sketch_values` | A capture in, an OrcaSlicer Design tab recipe and verdicts out. It does not import the recipe translator or the probe: what both need is in `design_model`. `limits.py` finds how far a variable can change before a step stops fitting. A check can give `limits.Stop(kind)` instead of False. `Stop` counts as False, and its kind tells why the value does not fit. The search keeps the kind of the first value past each limit (`Range.why`). The limit text then tells the cause in plain words (`limits.CAUSES`), for example "(below that, the end of the extrude passes its start)". The kind changes only the text. It does not change the place of a limit. `formulas.orca_number` writes each number that Orca reads as text: a variable value, a number in a formula, and a value that the limit search tests. It writes digits and one point, and a minus for a value below zero. It does not write an exponent, because the formula reader of Orca does not read an exponent. |
| `export_plan` | `capture_model`, `design_edit`, `design_model`, `geometry`, `orca_recipe`, `orca_translate`, `package`, `params`, `probe`, `results`, `sketch_values`, `timing`, `translator` | The export itself: the pipelines, the put back, body scope, size offers, the probe flow, marker roll, timeline trim, reach pass, health, package plan. |
| `dialog_model` | `design_model`, `export_plan`, `package`, `params`, `results`, `translator` | What the dialogs show, as plain data: rows, stop warning, result view. |
| `fusion_reader` | `capture_model`, `design_edit`, `geometry`, `package`, `params`, `timing` | Reads the design with `adsk`: the capture, the probe states, the reach, the STEP export, the parameter store. It does not import the translator. |
| `fusion_ui` | `dialog_model`, `export_plan`, `fusion_reader`, `package` | Draws the dialogs with `adsk` and handles their events; the log and message boxes. |
| `commands` | `design_edit`, `dialog_model`, `export_plan`, `fusion_reader`, `fusion_ui`, `package`, `timing` | The three buttons, their flows and the panel. |

Only `fusion_reader`, `fusion_ui` and `commands` use `adsk`. Everything else is pure Python and runs without Fusion.

`tests/test_boundary.py` checks these rules. A change that breaks one fails the test:

1. Every folder in `lib/` is in the table and has more than one module.
2. A package imports only the packages the table lists for it. The table has no cycle.
3. Only `fusion_reader`, `fusion_ui` and `commands` import `adsk`. Two reader files (`parameters.py` and `rows.py`)
   do not import `adsk` at the top, so the tests can run them with fakes.
4. A name with a leading underscore is private to its module. No module imports it from another module.
5. A test may reach a private name only when the test file and the name are listed in `PRIVATE_REACHES_IN_TESTS` in the
   same file. The test imports it with a plain `from module import _name`, not with `importlib`.

Style rule for imports: inside one block, relative imports from the farther package come first, then the rest in
alphabetical order by module.

### 2.2 The main modules

#### commands

- `commands/ExportForParamability/entry.py`: the dialog life cycle (`_on_created`, `on_changed`, execute).
- `commands/ExportForParamability/export_flow.py`: `run_export`, the ports `FusionPort` and `FusionPartsPort`, the
  `CaptureCache`, `_show_result`.
- `commands/export_common.py`: `run_guarded` (every way an export stops becomes one message, and the marker goes
  back), the writer text, the progress window.

#### export_plan

- `pipeline/` (a package, see its docstring in `__init__.py`):
  - `port.py` holds `ExportPort` (every member the pipeline asks of Fusion), `ExportRequest` and `PipelineResult`.
  - `run.py` holds `run_pipeline` and the stages of one export (`_Pipeline`).
  - `parts.py` holds `run_parts_pipeline` and `PartsPipeline` for several bodies, `PartsPort` (its port, with the body
    index in each call) and `shared_cuts`.
  - `probe_run.py` holds `ProbeRun` (the try runner: rows, put backs, rows run again, discovery) and `MarkerNotHeld`.
  - `put_back.py` holds `PutBack`: what the export changed, put back in one order on every way out, the end check, the
    last Undo drop and the health inputs (see 1.11).
  - The package re-exports what the rest of the add-in reads as `pipeline.<name>`.
- `probe_flow/` (a package):
  - `size_probe.py` holds `SizeProbe` (one part: states, the rows it plans, the discovery rows, the motion). It is one
    class in one module on purpose: the states, the rows, the discovery and the findings all read the same state, and
    split parts would need that state handed in and forwarding methods (the class docstring has the reason).
  - `probe_group.py` holds `ProbeGroup` (several parts over shared rows).
  - `interface.py` holds `Probe`, the interface that `ProbeRun` and both pipelines call. `SizeProbe` and `ProbeGroup`
    both have every member.
  - `row_schedule.py` holds `RowSchedule` (the row phases, see 1.8).
  - `sizes.py` holds `kept_sizes`, `extra_sizes` and `sizes_to_try`, the one place that decides which sizes get tries.
  - `borrowed_view.py` (`probe_view`, `borrowed_sketches`, `covers_a_sketch`, `with_borrowed`), `shared_reads.py`,
    `states.py` (compare states), `reasons.py` (the texts of untried sizes) and `shadow.py` (`shadow_of`).
  - The package re-exports what the rest of the add-in reads as `probe_flow.<name>`.
- `recipe_export.py`: `translate_capture`, `plan_single_export`, `plan_parts_export` (the package plan),
  `link_outcomes`. `assemble.py` makes the manifest and the files for the writer. `part_names.py` holds the names of the
  parts of a several-body export.
- `body_scope.py`, `size_offers.py`: what belongs to the picked body; the dialog rows and the probe sizes.
- `marker_roll.py`, `timeline_trim.py`: the marker roll and "Faster tries" (`TryTimeline`).
- `reach_pass.py`: when and how to ask for the reach.
- `health.py`: the `health` record and its sentences (`HealthInputs`, `make_health`, `health_lines`, `back_as_it_was`,
  `left_off_line`). `messages.py`: the package notes and the "Tip: " lines of the left-out steps.
- `undo_steps.py`: the "Lighter on memory" experiment (`UndoSteps`, `attach`, `drop_after`).
- `time_limit.py`: the choices, the default and the words of the time limit of the size tries (see 1.8).
  `fixed_parts.py`: the sizes that also move a part that stays a fixed shape in a parts file (`marked`, `joined`, see
  1.10).

#### dialog_model

- `stop_warning.py`: the early warning under the body picker (`summarize`, `summarize_many`) and the texts after the
  export (`saved_message`, `status_text`). `left_out_preview.py`: the steps that the copy will probably leave out, as the
  dialog lists them before the export (`Found`, `find` for the recipe, `find_orca` for the Orca copy, `lines`, see 1.2).
  `orca_result.py`: the result window of Export for Orca (`orca_view`) and its early warning (`preview`). When two
  reasons of a parameter have the same text, the line of the parameter shows that text one time only.
- `dialog_rows.py`: the texts and the checks of the rows of the parameter table. `result_rows.py`: what the result
  window shows. `sizes_table.py` and `sizes_text.py`: the sizes table of the dialog as plain data, and the sizes as CSV
  text.

#### translator

The top level of `lib/translator/` holds the driver and the parts that every handler uses. The handlers sit in folders,
one folder per family of steps.

- Driver and shared parts: `translate.py` (`translate`, `_settle`, `_walk`, `_finish`, `_diagnosis`, `_over_caps`,
  `_fix_long_formulas`), `handlers.py` (`HANDLERS`, the handler of each capture type), `walk.py` (the item
  loop, `walk_items`), `context.py` (`Context`: doubts, notes, cuts, gaps, steps, placers), `result.py` (`StepResult`,
  `Refusal`, `Doubt`, `TranslateResult`, the verdicts), `step_walk.py` (`all_steps`: every step at every depth),
  `notes.py` (every reason sentence; the type names in words are in `design_model/words.py`), `audit.py`, `turn_budget.py` (the turns of the
  threads and coils written so far: the 100 turn cap that both share).
- Values and sizes: `values.py` (`quantity`, `pin`, `handled`), `sizes.py` (the sizes the recipe cannot follow:
  `untried_reasons`, `construction_only`, `text_reasons`, `sketch_answer`, and `used_sizes`). Which sizes can move a
  sketch, a plane or a face is not here: it is in `design_model/reach.py`.
- Places: `place.py` (`place`, `POSITIONS`, `DIRECTIONS`, `NOT_WRITTEN`: moves a finished recipe by the rigid map from
  `geometry.rigid`), `placement.py` (sketch frames to recipe placements), `ref_motion.py` (how places of other
  components move, from the motion file; what is known without it is in `design_model/refs.py`).
- Handler folders:
  - `extrude/`: `step.py` holds `handle`. Also `plan.py` (the recipe sides from the sides of the shared reader,
    `design_model/steps/extrude.py`), `side.py` (`RecipeSide`: one side as the recipe writes it), `reach.py` (the
    start and the length to a face as values that follow sizes), `reach_motion.py` (a face or plane placed by the
    probe's measure), `taper.py`, `through.py`, `through_taper.py`, `material.py`, `checks.py` (the refusals of the
    measured checks of the shared reader), `built.py`, `order.py`, `common.py`, `up_to.py` (a side up to a tilted or
    curved face, see the section "Extrudes: a tilted or curved end face, a start at a distance from a face, an intersect to two sides" in part 3), `thin_line.py` (the wall along an open line, see "A thin extrude of an open line" in the same section), and `emboss.py` (the Emboss handler).
  - `sweep/`: `step.py` holds `handle`, with `sweep_*.py` for settings, outline, frames, taper (also the taper read
    from the volume), reach, marks, rules, write and limits. The outline's points, the volume check and the end face
    check are in `design_model/steps/sweep.py`.
  - `paths/`: what the recipe adds to the shared path planner (`design_model/paths/`). `path_limits.py` holds the caps
    of the recipe (`MAX_SEGMENTS`, `MAX_POINTS`), `options` (the planner options with these caps and the spline fit)
    and `refusal` (the refusal of a problem of the shared layer). `path_motion.py` holds the path that follows sizes,
    and `path_rebuilt.py` the rules of a path read back from written numbers, for the checks over the size ranges.
  - `loft/`: `step.py`, `loft_sections.py`. The volume of the corner pairing is in `design_model/steps/loft.py`.
  - `revolve/step.py` (see 3.14; which side each angle of a revolve to two sides turns to is in
    `design_model/steps/revolve.py`) with `revolve/axis_side.py` (the ranges where the outline stays on its side of
    the axis), `hole/step.py` (holes and cosmetic threads) and `hole/thread.py` (modelled threads and the thread
    of a tapped hole, see 3.12). They read the hole and the thread through `design_model/steps/hole.py` and
    `thread.py`; they keep the caps of the recipe, the values that follow sizes and the refusals.
  - `coil/`: the coil handler (see 3.13). `step.py` holds `handle`. Also `coil_fit.py` (the axis, the hand and the check of
    the helix), `coil_section.py` (the wire's section from an end face), `coil_operation.py` (new body, join or cut from
    the volumes), `coil_values.py` (the sizes of the coil as formulas) and `coil_limits.py` (the caps and the refusal
    texts).
  - `repeat/`: patterns and mirrors. `body_copies.py` (bodies), `repeat_*.py` (sources, build, lattice, the
    rectangular, circular and path patterns, the mirror, the mirror reach) and `symmetric.py` (copies on both sides:
    `extra_side`, `value_at`). The reading of the copies, the grid index, the reach of a symmetric direction and the
    mirror plane is in `design_model/steps/repeat.py`. The plain pattern that a path pattern equals is in
    `design_model/steps/path_pattern.py` (see 3.17). The package `__init__` is the entry point the walk imports.
  - `combine/`: `step.py` (`handle`) and `tool_walk.py` (the walk of a tool body, `cannot_copy`).
  - `finishes/`: `finish.py` (fillet, chamfer, shell; it reads the sets of rounds and chamfers from `design_model/steps/finish.py`), `measured_rounds.py` (rounds by chord length and rounds with a changing radius, see 3.16), `draft.py`, `offset.py` and `offset_round.py` (offsets of faces, see 3.20).
  - `bodies/`: `move.py` (the fit of the move is in `design_model/steps/move.py`), `scale.py` (see 3.18), `paste.py`, `split.py`, `split_rules.py` (`stop_reason`: when a split stops the copy, from
    the split facts of `design_model/roles.py`) and `design_model/steps/split.py` (which pieces of a split by a body lie
    inside the tool, when the reader could not say, see 3.4).
- Picks and faces that follow sizes, `faces/`: `follow.py` (picks, faces and planes that follow sizes), `picks.py`,
  `placer.py` (the placer protocol), `placer_makers.py`, `moved_placer.py`, `scaled_placer.py`, `tool_placer.py`, `slabs.py`, `shells.py` (the hollow of a shell that goes inward, the outer wall of one that goes outward, see 3.19),
  `offset_faces.py`, `end_caps.py`, `thin_wall.py`, `crossings.py`, `copy_counts.py`, `meets_part.py`, `floating.py`
  (joins that would float), `material_boxes.py` (the boxes around the material of written steps) and
  `added_bounds.py` (the boxes of material that written steps may add and the model does not hold).
- Sketch values, `sketch/`: `loops.py` (the shared loop writer `design_model/loops.py`, with each problem as a
  `Refusal`), `written_loops.py`, `sketch_motion.py` (sketch values from the motion file),
  `curved.py` (formulas with sines and products), `sketch_crossings.py` (`order_ranges` and
  `simple_ranges`, an outline that would cross itself or have a hole reach its edge, and `OutlineChecks`, the shared
  time of these checks), `rect_corners.py` (the corners of a rectangle loop as numbers and as raw size values), `inner_pick.py` (a face picked inside an end face follows one corner; an edge keeps the
  centre of all corners), `face_outline.py` (`may_change`, `doubt`) and `borrowed.py` (`mark_unchecked`: the sizes that
  can move an outline from another component's sketch in a sweep or a loft, from the `borrowed_movers` key of the
  profile. The outline itself is brought in by `design_model/borrowed.py`).
- Checks over the size ranges, `ranges/`: `range_check.py` (`recipe_size_values` gives the value of every size at a setting) and
  `kept_ranges.py` (`holding_ranges`, `holding_ranges_where`, `past_reasons`). The range cuts of the size probe's tries
  (`part_step`, `built_ranges`) are in `design_model/tried_ranges.py`.
- Gaps, `gaps/`: `stops.py` (the gap record, the gap names, `stop_reason`, `MAX_GAPS`), `gap_place.py`,
  `gap_measures.py` (`to_recipe`, the move of a gap in recipe form), `gap_file.py`, `finishing.py` (the `finishing` flag). The causes and hints are not here: they are in `capture_model` (`gap_hints.py`,
  `gap_picks.py`).
- The step kind table, the chain of splits (`lineage`) and the tool items are not in the translator. They are in
  `capture_model`, since the Fusion reader uses them too.

#### design_model

The shared layer between the capture and the outputs. Both translators read it, and the probe plan can read it. It
does not use the words of one output, and it does not refuse a step. It gives facts (what a step uses, where it is,
which sizes can move it) and doubts (sizes that can move something whose motion is not known).

- `recorder.py`: `Recorder`, the declared interface of what the layer asks of a translation: `table`, `capture`,
  `cache`, `motion` (None for the Orca output), `doubt(names, why)`, `note(text)`, `follow_component(component)` and
  `movers_unknown(phrase)`. The context of the translator and the context of the Orca output have every member.
  `tests/test_interfaces.py` checks this. It also checks that the layer asks a recorder only for these members.
  - The layer calls `movers_unknown` when the copy keeps something of another component where it is now and the
    capture cannot say which sizes can move it. `phrase` tells what the step does with it ("Mirror1 mirrors across a
    plane of Cover"). The layer does not decide what to do. Each output decides:
  - The translator writes a note on the step (`words.movers_unknown`).
  - The Orca output marks every ticked size with a doubt (`words.movers_unknown_doubt`). One parameter can drive steps
    of several components, so any ticked size can move the other component.
- `refs.py`: planes, faces, axes, directions and points of other components. The shape names (`PLANE`, `AXIS`,
  `POINT`, `DIRECTION`), `BODY_LISTS`, `is_foreign`, `bring_in`, `acting_sizes`, `reaching`, `mark_all`,
  `old_writer`, `from_old_export` and `why_foreign`.
- `step_links.py`: the facts of the steps that the geometry links (`params/geometry_links.py`) need. The geometry
  links tell which user parameters can move the part through the geometry of another component. That module is in
  `params`, below the shared layer, and it does not read the data of a step. This module reads the data and gives
  plain values to it:
  - `item_refs(item)` gives the measured references of one step (`ref`, see docs/capture-format.md). A step that is
    suppressed, that is in another component or that the reader could not read has none. `capture_refs(capture,
    items)` gives the measured references of all steps, or of the steps in `items`.
  - `places_item(item)` is true for an item that can place an occurrence: an assembly item, or a Move whose inputs are
    not bodies or faces. `moves_occurrence(capture, dependent)` and `places_occurrence(capture, param)` find the model
    parameters and the user parameters that act on such an item. `placing(capture)` gives the names of these user
    parameters.
  - `reach(capture, sketches)`, `reference_links(capture, items)` and `outside(capture, sketches, items)` call the
    functions of the same name in `params/geometry_links.py` with these facts. The export plan, the probe and the
    translators use these three functions.
- `borrowed.py`: outlines of another component's sketch (`usable`, `bring_in`, `movers`, `BORROWED_KEYS`,
  `MOVERS`). The probe flow reads `usable` and `BORROWED_KEYS`
  (`export_plan/probe_flow/borrowed_view.py`). `movers` gives the sizes that can move such a sketch (see "A place of
  another component" in 3.3). `bring_in` writes them in the `borrowed_movers` key (`MOVERS`) of the profile that it
  brings in.
- `steps/`: one reader per kind of step, as facts. `steps/repeat.py`: the copies a pattern kept (`kept_elements`), their
  frames in the frame of the part (`data_in_component` for the data of a pattern, `read_in_component` for a probe
  read), the grid index of a copy (`solve_lattice`), the steps a symmetric direction runs each way (`reach`,
  `FUSION_EXTRA_SIDE`), the plane of a mirror (`mirror_plane`) and the timeline items that a pattern or a mirror
  repeats (`repeated_items`). `steps/pattern_places.py`: where the copies of a pattern sit (see 3.21): the places of
  circular copies from their ids (`circular_sign`, `id_frames`), the check of a place against the faces of a copy
  (`agrees`), and the check that the places do not repeat and fill the count (`listed_places`, `grid_places`).
  `steps/path_pattern.py`: the plain pattern that a path pattern on one line, arc or
  circle equals (`layout`), how far its copies can run before they pass an end of the path (`room`), and which way a
  measured copy runs along the path (`run_of`, `turn_deg`). `steps/move.py`: the rigid move that carried a body, fitted from its corners before and after
  (`fit`). `steps/split.py`: which piece of a split lies inside the tool body (`resolve`). How a copy is written
  and what it does about a size stay in each translator.
- `design.py`: the design as the walks read it. `read(capture, table, motion, chain, cache)` gives one
  `ResolvedStep` for each item of the capture, in timeline order. The walk of the recipe (also for a tool body), the
  walk of the Orca output and the probe plan (`probe/plan/covered.py`) read these steps. A `ResolvedStep` has these
  facts:
  - `index`, `name` and `type` of the item. `raw` is the item as the capture holds it. `item` is the item with the
    measures of the body that the walk builds before the split that made the exported body
    (`roles.seen_before_split`).
  - `role`: the `roles.Role` of the item (see `roles.py` below).
  - `outside`: the item is in another component. `helper`: the reader read the item in the coordinates of its own
    component, for a tool body of a Combine (`helper_of`).
  - `problems`: a `Problem` for each thing that the reader could not read. The codes are `UNREAD` (`read_error`),
    `FAILS` (the step is in error in Fusion) and `BODIES_UNREAD` (`bodies_after` is null). The words are in
    `words.py`. `has(code)` and `problem(code)` find one.
  - `brought`: the item with the geometry of other components brought in (`borrowed.bring_in`, then
    `refs.bring_in`). Only a step of the component of the body is brought in (the roles `BUILDS` and `HELPER`).
    `foreign` is true when a record of another component stays in `brought`. `old_export` and `why_foreign` say
    more about it (`refs.from_old_export`, `refs.why_foreign`). The Orca output gives the sentence of
    `why_foreign` for an extrude that starts from or reaches to a face or plane of another component that it cannot
    place (`orca_translate/extents.reader_skip`). The sentence says if the face is curved or if its place is not
    known.
  - `events`: the doubts, notes and followed components that the bring in recorded, in order. The bring in records
    them on a `Tally`, not on the context of the translation. `replay(step, ctx)` records them on the context. Each
    walk calls `replay` where it brings the step in, inside the recording or the checkpoint of the step. This makes
    sure that the doubts and notes of a step count only when the walk copies the step. `error` is an exception that the bring in
    raised. `replay` raises it again, at the same point where the bring in raised it before.
  - `brought_data`: the data of `brought`. It is an empty dict when the item has no data. A handler copies the step
    from this data. `data` is the data of `item`, and `raw_data` is the data of `raw`. The probe plan reads
    `raw_data`, because it reads the sketches of the step as the capture holds them.
  - `facts`: the facts that a shared step reader reads from the data of the step alone (`FACT_READERS`). The step
    kind table says which reader applies to a type (`StepType.facts` in `capture_model/step_kinds.py`). The sets of
    a round or a chamfer step (`steps/finish.py`) are such facts. The Orca handlers of a round and of a chamfer
    (`finishes.fillet`, `finishes.chamfer`) read them. The Orca output also reads them when it measures a round or a
    chamfer that it leaves out (`finishes.note_left_out`). The recipe handlers of a round and of a chamfer
    (`finishes/finish.py`, `fillet` and `chamfer`) read them too. For another kind, `facts` is None.
  `resolve(item, ctx, role)` gives the `ResolvedStep` of one item. The Orca output uses it for each step of a tool
  body (`tools.build`), without a role.
  `as_read(item)` gives a `ResolvedStep` of an item as the capture holds it. It has no role, it brings in nothing,
  and it has no events. Use it for an item that no walk resolves, but that a handler reads or copies. Examples are a
  source of a pattern, a Combine among the sources, and an item that a handler writes again as a step of another
  kind (a straight sweep that the Orca output writes as an extrude). The recipe output uses it for the same
  kinds of items: the Combines among the sources of a pattern (`repeat/repeat_sources.py`), the pattern that made a
  tool body (`repeat/body_copies.py`), the steps of a tool body that a Combine writes onto the part one by one
  (`combine/step.py`, `combine/tool_walk.on_part`), the item of a left out step (`gaps/`), the item that wrote a
  sweep (`faces/floating.py`), and the extrude or revolve that a sweep or an emboss is written as
  (`sweep/sweep_write.py`, `extrude/emboss.py`). A test that calls a handler directly also gives it
  `as_read(item)`.
  `params_of(item)` gives the model parameters that Fusion keeps for the values of an item (`data.params`), by the
  path of each value in the data. Each parameter has its name, its expression and its value. It is an empty dict when
  the item has none. The Orca output reads a value that can follow sizes through it (`Context.quantity`). The recipe
  output reads it in `values.py` (`quantity`, `pin`), in the audit and in the record of a gap.
  `sketches_of(item)` gives the names of the sketches that the data of an item names. It finds every `sketch` field,
  at each depth of the data. Each name is in the list one time, in the order in which it first occurs. The audit of
  the recipe output (`translator/audit.py`) reads it. The audit uses it to find the sizes of the sketches that a
  copied step or a left out step uses.

  Handlers read the resolved step. The rule is for each module above the shared layer that reads a timeline step:

  1. The walk gives the handler the `ResolvedStep` of the step: `handler(ctx, step)`. The walk does not give the
     item.
  2. The handler reads the item from `step.brought` and the data from `step.brought_data`. When the step kind has a
     shared reader with facts, the handler reads `step.facts`. The handler does not call the reader again.
  3. The handler gives the data, or the facts, to the shared step readers (`design_model/steps/`) and to its own
     helpers. A helper does not read the data from the item again.
  4. When the handler must read another item (a source of a pattern, for example), it reads that item through
     `as_read(item)`. When it writes a step again as a step of another kind, it gives `as_read(new item)` to the
     other handler.
  5. A fact that the output needs and that the shared layer does not give yet goes into the shared layer, as a fact
     that does not name an output. An example is `steps/repeat.py`, `data_in_component`: the copies of a pattern in
     the frame of the component, from the data alone. Another example is `steps/repeat.py`, `repeated_items`: the
     timeline items that a pattern or a mirror repeats. The policy of the output (the limits, the checks of the part,
     the choice to leave a step out) stays in the output.

  The recipe output applies the rule in these places:
  - The walk (`translator/walk.py`) gives each handler the `ResolvedStep` through `run_handler(handler, step, ctx)`.
    The split rules get the `ResolvedStep` too (`bodies/split_rules.stop_reason(step, ctx)`).
  - The walk of a tool body (`combine/tool_walk.build`) uses the same walk, so each step of a tool body is resolved.
    When a Combine writes the steps of a tool onto the part one by one (`tool_walk.on_part`), it gives each handler
    `as_read(item)`.
  - A pattern or mirror handler (`repeat/`) carries the data of its step into the frame of the component with
    `data_in_component`, as the Orca output does. It gives the data to the helpers of the grid
    (`repeat_lattice.lattice_axes`). A Combine that takes a whole pattern runs the handler of the pattern on
    `as_read(pattern item)`.
  - A helper gets the data, or a part of it, from its handler. Examples: `sketch_motion.points` gets the data of the
    hole, and `sketch_motion.axis_point` and `axis_raw` get the axis record of the revolve.
  - In a handler, the name `step` is the resolved step. A recipe step that the handler writes has the name
    `recipe_step`.

  Some modules do not copy steps. They read all the items of a capture to find facts: the steps of the picked body
  (`export_plan/body_scope.py`), the items that the tries need (`export_plan/marker_roll.py`), the sketches of other
  components (`export_plan/probe_flow/borrowed_view.py`) and the patterns with a sized count
  (`probe/plan/request.py`). These modules read the data of each item through `as_read(item)`. They do not read
  `item["data"]`. The probe plan (`probe/plan/covered.py`) reads the steps of `read` and their `raw_data`.

  The packages below the shared layer (`geometry`, `params`) cannot import it. Thus they do not read the data of a
  step from an item:
  - A function of `geometry` gets the data of the step. Example: `combine_volume.exceeds(data, tools)` gets the data
    of the Combine and the data of each tool step. The caller reads the data through `as_read`.
  - A function of `params` gets plain values. The shared layer reads the steps and gives these values. Example:
    `params/geometry_links.reach` gets the names of the parameters that can place an occurrence. The function
    `design_model/step_links.reach` reads them from the steps and calls it.

  `tests/test_boundary.py` checks that no module takes the data of a step from the item, except the modules of the
  shared layer (`design_model`), of the reader (`fusion_reader`) and of the capture model (`capture_model`). The
  modules of `translator`, `orca_translate`, `probe`, `export_plan`, `geometry` and `params` follow the rule.
- `roles.py`: what each timeline item is for the body that a walk builds, and which measures of that body apply to
  the item. The walk of the recipe and the walk of the Orca output both read them:
  - `role_of(item, target, chain)` gives a `Role`: the kind of the item (`SUPPRESSED`, `NOT_A_STEP`, `ASSEMBLY`,
    `TOOL_ELSEWHERE`, `OTHER_COMPONENT`, `BUILDS`, `HELPER`), the body before and after the item, the bodies that
    the walk builds around the item (`held`), `touches`, `new_bodies`, `copies`, `changed` and `lost`. See 1.9.1.
  - `seen_on(item, body, exported)` gives the item with the measures of `body` (`body_states[token]`: the box and
    the volume before, the volume after). The data fields of the exported body (`target_box_before`,
    `volume_before`, `volume_after`, `intersect_model`) get the values of `body`. The item's `target_before` and
    `target_after` become null, because they are measures of the exported body. When the reader did not measure
    `body`, these fields are null, and the handlers do not do the checks that need them. A walk of a tool body uses
    this function for each step of the tool.
  - `seen_before_split(item, target, chain)` does the same for an item before the split that made the exported
    body: the item gets the measures of the body that was split. It does not change the split itself, a step of
    another component, or an item that the reader did not measure on that body.
  - `other_pieces(item, before, kept)` and `used_later(timeline, item, body, target, chain)`: the pieces that a
    split leaves in addition to the piece that the walk follows, and the first later step that changes one of them
    together with the body. The recipe walk stops on such a step (`split_rules.stop_reason`). The Orca output
    leaves the split out (`orca_translate/bodies.py`, cause `pieceUsedLater`). The Orca copy keeps only the piece of
    the part, so the material that the later step adds back is not in the copy. In a tool body, the Orca output looks
    only at the steps before the item that takes the tool (`context.Body.anchor`). Steps after that item do not
    change the tool as the item uses it.
  - `lost` in the `Role`: the item lists a body with the name of the exported body but another token. The recipe walk
    stops on such an item. The Orca output leaves the item out (cause `bodyLost`). The copy cannot tell if the item
    changes the part.
  - `copies_bodies`, `changes_named_bodies`, `only_splits_faces`, `existing_bodies`: smaller facts that the walks
    and some handlers use.
- `values.py`: `Quantity`, the one value type of both outputs, and the helpers that work on it. It has no output in it:
  - `Quantity(n, text, reads)` is a measured number `n` with, when sizes move it, a formula `text` over the sizes and
    the Fusion names `reads` of those sizes. When `text` is None, no size moves the value. `scaled`, `plus`, `times`,
    `divided_by` and `magnitude` give a new `Quantity` and keep the formula in step with the number. A sum with a
    plain number keeps the number apart (`core`, `const`), so a later sum folds the numbers into one. `json()` gives
    the form that the recipe writes: a plain number, or a `Sized`.
  - `Sized` is `{ "expr": formula }` that remembers its number and its `reads`. It is a normal dict for JSON.
    `number`, `negated`, `reads_in` and `numbers_of` read and change written values and steps.
  - `negated_text` and `wrapped` write the text of a formula for a minus sign or for another operation, without
    extra brackets.
  The decision of how a value follows the sizes stays in each output. The recipe output uses `translator/values.py`
  (`quantity`, `pin`, `handled`, the checks of ranges and the audit). The Orca output uses `Context.quantity` and
  `Context.bind`, which turn the formula into an Orca formula. The formula text of a result can differ between the
  two outputs. The value that it gives at every size is the same.
- `steps/finish.py`: the sets of a round or a chamfer step, as facts. A step holds
  one or more sets. Each set has the edges that Fusion picked (records with measured points), a kind, and sizes. The
  module says what is known about a set. It does not say if a set is copied, and it does not name the edges. Each
  output does both:
  - `FinishSet` is what every set has: its `index` (the number in the names of its parameters, `path`), its `kind`, its
    `edges`, and the facts `follows_step` (Fusion was given the edges of another step), `unlocated` (an edge has no
    measured point) and `foreign` (an edge is on another component). `entry` is the capture dict, for the picks that
    read the faces or the tangent chains that Fusion was given.
  - `RoundSet` adds `radius` and `continuity`. The kinds are `CONSTANT`, `VARIABLE`, `CHORD_LENGTH` and `ASYMMETRIC`.
    A value that is not a positive number reads as None. A `CHORD_LENGTH` set also has `chord`. A `VARIABLE` set also
    has `start` and `end` (the radii at the two ends of the edge) and `mid_count` (the number of radii between the
    ends). `chord_size` and `end_sizes` give these values as `Quantity`s.
  - The functions for the samples along an edge (`samples` of an edge record, 3.16):
    - `face_angle` gives the angle between the normals of the two faces of the edge. It gives None when the angle
      changes by more than `FACE_ANGLE_TOL` along the edge, or when a sample has no normals.
    - `chord_radius` gives the radius that a chord length gives at an angle. It gives None when the faces are almost
      flat into each other or folded back (`FACE_ANGLE_RANGE`).
    - `matches_radius` tells if the radius that the reader measured at each sample is a given radius, within
      `RADIUS_TOL` plus `RADIUS_SHARE` of the radius. It can skip the samples at the two ends of the edge.
    - `law` tells how a radius that changes from `start` to `end` runs along the edge: `FROM_START`, `FROM_END`,
      `LEVEL` (the two radii are equal, so the samples cannot tell) or None (the change is not even, or a sample is
      missing).
  - `ChamferSet` adds `distance`, `other` (the second distance), `angle` and the facts that come from them. The kinds
    are `EQUAL`, `TWO_DISTANCES` and `DISTANCE_ANGLE`. `problem` says what a set lacks (`NO_SIZE`, `NO_ANGLE`,
    `UNKNOWN_KIND`). `even` is true when both sides of the cut have the same size: two equal distances, or a distance
    and 45 degrees. `second` is the second `Measure` of an uneven chamfer. `held` is the second `Measure` of an even
    chamfer that is even only while that value stays so. `ratio` is the first distance over the second on a square
    edge. `reach` is how far the chamfer reaches along a face.
  - `reach` also exists on `RoundSet`. The Orca output uses it to measure a step that it leaves out
    (`outline_rounds.note_left_out`).
  - `ChamferSet.sides()` splits the edges of an uneven chamfer by the face that takes the first distance. The reader
    measured, for each point of an edge, the normals of the two faces (`sides`) and the normal of the chamfer face
    (`cut_normals`). The chamfer face normal is a mix of the two face normals, weighted by the two distances. The
    mix tells which face has the first distance. All points of a group must agree on one direction (`sizeOn`). Edges
    that no one direction fits make more groups. When an edge was not measured, or the chamfer face does not tell, the
    result is None. For an even chamfer the result is one group with no direction.
  - A size that follows the sizes is a `Quantity`. The set gives the number and the path of its parameter, and the
    output makes the `Quantity` (`size(quantity)`, where `quantity(path, number, dim)` is the function of the output:
    `translator/values.py` or `Context.quantity`). This keeps the rule of how a value follows the sizes in the output.
  - `Part` and `merge` put the edges of a step in parts of one size. A part has a size, a direction (the face of the
    first distance), the second measures and its edges. `merge` joins the parts that are equal and keeps the order of
    the first appearance. The recipe output writes one step for each part ("chamfers of different sizes are applied
    one after the other"). The Orca output makes one round or chamfer for each part (see `docs/orca-output.md`).
  The picks stay in the outputs: the recipe names edges by points that follow the sizes (`faces/`), the Orca output by
  a group of faces of the part (`finish_body`) or by the corners of an outline (`outline_rounds`).
- `words.py`: the sentences that both outputs give for the same fact: the noun of a reference, "may move with it", the
  note of a borrowed outline, the reasons of `why_foreign`, the problems of the readers of extrudes, holes, threads and
  sweeps, and the refusals that the two translators word the same (patterns, mirrors, splits, revolves, lofts, sweeps,
  rounds and chamfers), and the sentence of a tool body that cannot be copied because one of its steps cannot
  (`ToolStop`, 3.5). The words of the problems of sweep paths are in `paths/words.py`. A sentence in these files
  says what the design has and that it is not copied. It does not name an output (no "Orca", no "Paramability"), and
  it does not say "yet", since the layer cannot promise that a later version copies it. So each sentence reads right
  in the recipe and in the Orca copy, and the Orca output shows the sentence of a `Problem` as it is (`Skip.of`). A
  refusal that comes from a limit of only one output stays in that output. `type_words` (a step type in words) and
  `unsupported_type` (the reason of a step of a type that has no handler) are here too.
- `reach.py`: which ticked sizes can move something that a step uses. Each
  function reads the size table and the capture only. No function says what a copy does about a size. The recipe
  output, the Orca output and the probe plan decide that for themselves. The functions are in five groups:
  - The sizes behind the model parameters of the design. These functions are in `param_reach.py`, and `reach.py`
    gives the same names. `sketch_params` and `sketch_sizes` give the sizes behind the
    dimensions of a sketch. `linked_sizes` gives the sizes that reach the sketch through the geometry of another
    component (`table.links`). `construction_sizes` gives the sizes behind construction planes or axes.
    `joint_reasons` gives the sizes that a joint reads. `text_sizes` gives the sizes that set the height of a sketch
    text, with the name of the sketch. `reasons` is the helper that finds the sizes behind the parameters of one maker.
  - The plane of a sketch. `placement_sizes` gives the sizes that can move the plane a sketch sits on: the sizes behind
    its construction plane and, for a plane on the part, every size that an earlier step reads. `sketch_plane_sizes`
    does this for an outline, also when the outline is a face of the body. Fusion 2706 gives no
    `Sketch.referencePlane` for some sketches on a face, so the capture has no `reference` for them. Thus a sketch
    without a reference counts as a sketch on a face of the part: `placement_sizes` gives every size that an earlier
    step reads. Example. A boss is sketched on the top face of a plate, and `Height` sets the plate. The Orca output
    then marks `Height` ("follows but not everywhere"). The probe tries `Height` (`probe/plane_sizes.plane_driven`),
    so the recipe follows the measured plane of the boss sketch; without a try or a motion file, the recipe marks
    `Height`. A sketch whose frame lies on an origin plane is an exception, because older captures give no reference
    for any sketch. An emboss outline is another exception (`on_start_face`): the recipe starts it on the face, which
    it follows. `hole_plane_sizes` does this for the holes
    of one step. `borrowed_plane_sizes` does this for a sketch of another component: a face, or a construction
    plane built on geometry, can be of the part, so it gives every size that the body's component reads before the
    step. `on_part` and `offset_param` say if a plane sits on the part and which parameter is the own distance of an
    offset plane.
  - A face or plane that a step starts from or reaches to. `moving_reaches` lists the flat faces and planes of the part
    that can move, and that the probe can find again. `reach_sizes` gives the sizes that can move one of them.
    `any_face_sizes` gives the sizes that can change any face of the body: every size an earlier step reads.
  - Geometry projected into a sketch. `projection_sizes` gives the sizes that can move it: every size that a step
    before the sketch reads. A sketch takes its projections at its place in the timeline. Thus the dimensions of the
    sketch and the steps after the sketch do not move them. The Orca output marks these sizes when an outline corner
    or a hole centre follows projected geometry (`sketch_sizes.projection_doubts`, `hole_place`). A projection of the
    origin point, an origin axis or an origin plane of the component of the sketch does not move with the sizes. The
    reader marks it with `origin: true` in the sketch graph. When the export can show that no ticked size moves or
    turns the sketch plane (`plane_fixed`), the sketch solver keeps it as a fixed number (`sketch_solve/constants.py`,
    `own_origin`), as it keeps the origin of the sketch. `plane_fixed` shows this for an origin plane, for a
    construction plane with no ticked size behind it or behind what it is built on, and for a plane on the part when
    the sketch item is found and no step before it reads a ticked size. In every other case, the answer is "not
    fixed": a sketch without a reference, a sketch item that is not found, an outline that follows a face, or a sketch
    of another component. When a size can move or turn the plane, the projection moves in the sketch. Then it stays a
    measured input, and the output marks the sizes as for other projected geometry. The sizes that move the
    plane are also among the sizes of the plane (`placement_sizes`), so a line of such a sketch still gets them.
  - Another plane, axis or face of the component of the body that a step uses as a place: a split plane, a mirror
    plane, a turning axis. `reference_sizes` gives the sizes that can move it. These are the sizes behind a
    construction plane or axis and behind the construction geometry that it is built on. A record without a token
    stands for all construction geometry of its kind. For a face, an edge, or construction geometry built on the
    part, the sizes also include every size that an earlier step reads (for construction geometry: a step before the
    geometry was made). For a line of a sketch, `sketch_line_sizes` gives the sizes. These are the sizes of that
    sketch and the sizes that can move the plane of that sketch. When the sketch holds projections, or when the
    capture does not tell, they also include every size that a step before the sketch reads. Projected geometry of
    the part moves with those sizes. A projection of the origin point, an origin axis or an origin plane of the
    component of the sketch is not counted as a projection (`read_sketch.holds_projection`), because it does not move
    with the sizes. An origin plane or axis gives no size. A record of another component gives no
    size here, because its sizes come from its measured reference (`refs.mark_all`). A place that the step works out
    from another record (`fixed`, the axis of a sweep path arc) gives no size, because the step marks the sizes of
    that record. Unknown counts as "can move". A record that does not say what it is (an older capture) gives every
    size that an earlier step reads. The Orca output marks the sizes of each such place that it writes as numbers
    (`orca_translate/kept_refs.py`). The recipe output does this for a revolve axis that the probe does not follow
    (`ref_motion.check_own_axis`) and for a mirror plane or pattern axis that it cannot follow
    (`follow.place_plane`). For a revolve axis on a line of another sketch, the recipe output marks only the sizes
    that the probe did not try (see "A turning axis").
  - The direction of a rectangular pattern. `direction_sizes` gives the sizes that can turn it. For a direction
    taken from an edge, an axis or a face of the part (the `own` place that the reader writes), these are the sizes
    of `reference_sizes`. For a direction taken from a sketch line, these are the sizes of `sketch_line_sizes`. A
    direction of another component gives no size here. The source of a direction can be unknown: the place is
    `unknown` (the reader could not tell the component), or an older capture gives no place and no sketch. When the
    pattern uses that direction (more than one copy along it), `direction_sizes` gives every size that an earlier step
    reads. `direction_kind` gives the Fusion type of the entity, for the reason.
    Both outputs write the direction as a number, so both mark these sizes. They read them through
    `edges.direction_sizes` (see `edges.py` below): the recipe output in `ref_motion.check_own_direction` (not in the
    first translation of an export), the Orca output in `repeat._mark_directions`.
  - The faces where a hole goes in and comes out. `hole_end_sizes` gives every size that an earlier step reads. This
    includes the sizes of the sketch of the hole. These sizes move the hole centres. If the part does not have the
    same thickness everywhere, a hole that moves goes in and comes out at different faces. For example, a size can
    move a hole from a thin plate to a position below a boss. The Orca output marks these sizes for the thread of a
    tapped hole through all, because the thread length is the thickness of the part now. It reads them through
    `edges.through_sizes` (see `edges.py` below).
- `edges.py`: edges and faces of the part, matched to the straight extrudes that made them. The match applies only
  to a plain part (`_plain_body`). A part is plain before a step when each step of its component before that step is
  one of these:
  - a straight extrude;
  - a simple hole through all (it makes only round faces and round edges);
  - a sketch or construction geometry;
  - a step of another component that cannot change the bodies of this component.
  Any other step (a revolve, a loft, a sweep, a pattern, a round, a move, or a step that the step kind table does not
  know) can make an edge or a face at the same place as an edge or a face of an extrude. Then there is no match.
  An extrude is straight when all of these conditions are true:
  - it starts on its sketch plane or at an offset from it;
  - it has no taper, and each side ends at a distance;
  - its outlines are read fully and lie in one plane;
  - the measured end face (`end_offset`) shows where its two end caps are.
  The match uses the place of the edge or the face now:
  - A side edge along the axis of the extrude. Its middle point lies over a corner of the outline, between the end
    caps.
  - An edge across the axis. Its middle point lies over a line of the outline, at an end cap, and the edge runs
    along that line.
  - An end face across the axis. Its point lies inside the outline, at an end cap.
  - A side face. Its point lies over a line of the outline, between the end caps, and its normal is perpendicular to
    that line.
  A matched edge or face turns only with the sketch planes of the extrudes (`reach.placement_sizes`). The function
  uses the sketch planes of all extrudes of the part, because an edge where two extrudes meet turns with the two
  planes. An edge across the axis and a side face also turn with their line. The line does not turn when the sketch
  solver (the default reading, `sketch_solve`) gives its two ends a gap of zero across or along, or a constant gap.
  Otherwise the line can turn, and the general sizes stay. Without a match, `direction_sizes` gives
  `reach.direction_sizes`.
  `angle_sizes` gives the sizes that can change the angle between two faces of the part, for a round by chord length
  (3.16). Each face record has a point, a surface kind and an outward normal. When each face is a flat face that a
  straight extrude of a plain part made (an end face or a side face, as above), the faces turn only with the sketch
  planes of the extrudes. Then `angle_sizes` gives the sizes of these planes. Otherwise it gives
  `reach.any_face_sizes`: every size that a step before the round reads.
  `through_sizes` gives the sizes that can change the thickness of the part where a hole goes through. The thickness
  is the same at all positions of the hole only when all of these conditions are true:
  - the part is plain before the hole;
  - each extrude is one sided, and makes a new body or joins;
  - the axis of each extrude is parallel to the hole;
  - all extrudes start and end on the same two planes;
  - each hole goes in at one of these planes and comes out at the other, inside an outline.
  Then the sizes are the sizes of the lengths and of the sketch planes of the extrudes (a plane can tilt against the
  hole). For more than one extrude, the sizes of the start offsets are also included. A hole that moves out of all
  outlines cuts no material. The sizes that move the plane of the holes are not included, because the Orca output
  marks them for the hole itself. Otherwise `through_sizes` gives `reach.hole_end_sizes`.
  - The sizes that a step reads. `step_sizes` gives the sizes behind the values of one step and behind the sketches it
    uses (the sketch graphs and the dimensions of an outline brought in from another component included).
    `profile_sizes` gives the sizes that move the sketch of one outline. An outline of another component gives none:
    its sizes are marked when it is brought in. `item_reads` is the same for one timeline item.
    `construction_fixes` gives, for a step, the sizes behind the construction planes and axes that it uses itself.
  - The sizes that the probe has to try. `probed_sizes`, `placement_driven` and `reach_driven`.
- `problem.py`: `Problem(code, words, cause)`. A reader of the shared layer gives its record, or a `Problem` when the
  design cannot be read or placed. `words` is one plain sentence. `cause` is the cause of `gap_hints.py` that gives the
  person a tip, or None. `code` names the problem, so a caller can tell two of them apart. The layer does not refuse a
  step. The recipe translator turns a `Problem` into a `Refusal` with the same sentence and cause. The Orca output turns
  it into a `Skip` (the cause `refused` when `cause` is None). `is_problem(found)` tells a record from a problem.
- `loops.py`: the loop writer. It changes the curves of a sketch outline into the loops that the recipe writes:
  circle, ellipse, rect, polygon or profile. `loop_of` changes one loop. `profile_loops` changes one outline record into
  its outer loop and its inner loops. `outline_problem` finds an outline record that is not a drawn sketch outline
  (text without outlines, a flat face, or an entity that the reader does not know). `flip_y` mirrors a loop across the
  x axis of the sketch. When an outline cannot be written as loops, the writer gives a `Problem`. Its sentence is
  in `words.py` (`OUTLINE_...`, `TEXT_PROBLEMS`). The recipe translator reads the loop writer through
  `translator/sketch/loops.py`, which turns each `Problem` into a `Refusal` with the same sentence. Two outlines are
  limits of the recipe, not facts of the design: a flat face used as an outline, and text with overlapping outlines.
  For these two codes the translator gives its own sentence (`OWN_WORDS`). The probe reads the loop writer directly (`probe/match.py`, `probe/plan/covered.py`). The
  probe measures a sketch value through the same loops that the translator writes. Thus a measured value is the
  value that the translator writes.
- `tried_ranges.py`: the range cuts that come from the tries of the size probe. `built_ranges` cuts the range of a
  free size on each side, to the farthest value that Fusion rebuilt (`failure_cut`), that kept each followed outline
  (`outline_cut`) and that kept the part in one piece (`split_cut`). Only a failure in a step that the part is built
  from counts (`part_step`). An end that the person typed is not cut. The recipe translator cuts its size table with
  `built_ranges` before the walk, and so does the export of several parts (`export_plan/pipeline/parts.py`). The probe
  uses the same cuts to find a size that kept no value other than its value now (`probe/build.py`,
  `outline_windows`).
- `steps/`: one reader for each kind of timeline step. A reader gives facts that any output needs. It has no value, no
  range, no recorder and no output word in it. A fact that it cannot read is a `Problem`. There are readers for
  extrudes, holes and threads, patterns, mirrors, moves and splits, rounds and chamfers, sweeps and lofts.
  - `steps/thread.py`: the thread of a ThreadFeature and the thread of a tapped hole. `spec_of` gives the `Spec` (pitch,
    major and minor diameter, hand, and the pitch diameter when Fusion gives one between the minor and the major
    diameter) of Fusion's thread info. It gives a `Problem` for a profile that is not the 60
    degree form (cause `threadProfile`), for a number that is missing and for a thread that has no usable depth. A
    caller can pass the range of pitches that it copies (`pitches`). A pitch outside it is a `Problem` with the cause
    `threadLimits`. `cylinder` gives the one `Cylinder` that the faces make (the point on the axis, the unit axis, the
    radius, the span along the axis, and which side the material is), or a `Problem` for a face that is not a cylinder,
    a face of another component, faces that are not one cylinder, and faces that do not touch. `is_full` and
    `start_end` say if the thread runs the whole face and at which end it starts. `read_feature` does all of these and
    the checks of the side and the size in order, and gives a `Feature`. For a tapped hole, `hole_spec` gives the
    `Spec` and checks it against the measured bore, and `hole_depth` gives how deep the thread runs (`Depth`).
  - `steps/hole.py`: the HoleFeature. `placed` checks the position, the direction and the diameter. `kind_of` gives the
    `Kind` (simple, counterbore or countersink, with its record), `tap_of` says if the tap is plain, tapped or
    tapered, and `extent_of` gives the depth as a distance, through all or up to a face. `direction_of` gives the unit
    direction of the hole into the material. The stored direction is turned round when a measured end lies behind the
    position it belongs to, and the fact `flipped` says so. `drill_diameter` gives the measured drill size of a tapped
    hole: the narrowest measured cylinder. The stored size does not limit it, because Fusion drills a tapped hole at
    the minor diameter of the thread, and this diameter can be larger than the stored size. `size_differs` says that
    the measured cylinders disagree with the stored size. `end_shape` gives the measured end of the hole (cone, plane
    or mixed). `reach_depth` gives the measured depth of a hole that ends at a face. `through_ends` gives the point
    where the bore of each hole through all comes out of the part (see "A tapped hole"). `tapped_bore` gives the
    diameter at which the bore is cut and the thread `Spec` (None for a cosmetic thread). For a cosmetic thread, the
    measured drill size must agree with the minor diameter of the thread when Fusion gives it.
  Each output decides what to do with these facts: the recipe translator checks the thread caps and follows the sizes,
  the Orca output checks the limits of Orca and the part that it built.
- `steps/extrude.py`: the reader of an extrude. The recipe output (`translator/extrude/plan.py`) and the Orca output
  (`orca_translate/steps._sides`) read the same sides. Each output then applies its own limits.
  - `start_of(data, frame, offsets)` gives a `Start`. The kind is the sketch plane, an offset, or a flat face or
    plane (`Target`). `shift` is the signed distance along the sketch normal from the sketch plane to the start. A
    start on a face that is not flat, on a tilted face, or on a curved face of another component gives a `Problem`.
    A start at a distance from a face also gives a `Problem`, unless the caller sets `offsets`. The API does not
    tell in which direction Fusion measures that distance. With `offsets`, the measured start face (`start_offset`)
    tells it. The face plus the distance, or the face minus the distance, must put the start on the measured face.
    When exactly one of the two does this, `Start.offset` is the distance with that sign, and `Start.way` is the
    sign. When there is no measured start face, the measured end cap can tell the sign (`_way_from_end`, see the
    section "A start at a distance from a face" in part 3). Else the result is a `Problem`. The recipe output sets
    `offsets`. The Orca output does not set it.
  - `read_sides(data, frame, shift, faces)` gives one `SidePlan` for each side, or a `Problem`. A `SidePlan` has
    the kind (`DISTANCE`, `REACH`, `UP_TO`, `THROUGH`, `THROUGH_BOTH`, `SYMMETRIC`), the capture field of the side
    (`which`, which is also the start of its parameter paths), the direction (`sign`), the length as a `Quantity` of
    the number, Fusion's taper in degrees, the face or plane of a `REACH` or `UP_TO` side and Fusion's offset past it,
    the measured end face, the direction that Fusion stored, and the number that Fusion stores for the length
    (`value`, `scale`). Each output makes the length follow the sizes with its own rules.
  - `UP_TO` is a side that ends on a tilted or curved face of the part. Only a caller that sets `faces` gets it, and
    only for an extrude with one side. For all other callers, such a face gives a `Problem`. The face
    must be a `BRepFace` with a `face_point`. The side goes toward that point. A curved face can lie on the two sides
    of the sketch, so the measured end face (`end_offset`) must lie on the same side as the point. A join merges its
    end cap into the curved face, so Fusion gives no end face. Then the body that the join made must lie wholly on
    the same side as the point (`joined_side`, see below). In all other cases the result is a `Problem`
    (`WAY_UNSURE`). A flat face that is tilted meets the line of the sketch normal on one side only,
    so its point gives the direction. The `Target` of the side has the plane of a tilted face, and no plane for a
    curved face. A face without a plane must be curved (`surface`), else the result is a `Problem` (`FACE_UNREAD`).
    Where Fusion can end the side on other faces than the app, the outline must land on the face alone, else the
    result is a `Problem` (`CHAINED`, `PAST_CURVED`; see the section about extrudes in part 3). The side has no
    length. The recipe output sets `faces` (see the section about extrudes in part 3). The Orca output does not set it.
  - The direction of one side: the measured end face (`end_offset`) wins over the direction that Fusion stored,
    because Fusion can store the direction in two ways. An end face nearer than 0.001 mm to the start does not show a
    direction. A side that has `direction` (a step that the translator writes again as an extrude) goes in that
    direction. A side to a face or plane goes toward the face or plane, and the measured end face does not turn it.
    The legacy "all" extent stores no direction. When no end face was measured, its direction is a `Problem`.
  - The direction of two sides: side two goes against side one. A face or plane of side one or side two sets the
    direction. If both sides go to faces or planes on the same side of the sketch, the result is a `Problem`. Else the
    stored direction of side one stays, and the measured end face turns it only when the face fits the turned sides
    and does not fit the stored sides. Example: side one is 30 mm up and side two is 10 mm down. A face 8 mm down
    fits side two, so the direction stays. A face 20 mm down fits only side one turned down, so the direction turns.
  - The taper of a side that goes to a face is in its parameter only (`<which>.taper_deg`). Without the parameter,
    the measured side walls must show no taper. Without walls, the end face must have the area of the outline. Else
    the taper cannot be read.
  - The next checks are in `steps/extrude_checks.py`, a second module of the reader. It reads the sides that
    `read_sides` gives and does not read them again. `end_check(sides)` gives an `EndCheck`: the measured end face is at the end of a side (`AT_END`), on the way of
    a side but nearer than its end (`SHORT`), or at another place (`ELSEWHERE`). For two sides, the reader compares
    the face with the side on the same side of the sketch as the face. For a symmetric extrude, it compares the face
    with half the length. Each output decides what a `SHORT` face of a cut means. A side of a cut that goes out of
    the part makes no end face, and Fusion then measures a wall that the cut went through. Only the side that the
    face lies on can make the face acceptable. The other side of a two sided cut tells nothing about the face, because
    the face is not on its way. `passes_box(box, start, z, way, length)` is the fact that a side ends past every
    corner of the part box (`target_box_before`). The recipe output accepts the face only when the side of the face
    passes the whole part. The Orca output accepts the face only when no material is past the face on the side of the
    face. No material is there when that side passes the whole part, or when the part that the copy built has no
    material there.
  - `end_is_cap(data, z)` tells if the measured end face is an end cap of the extrude. Fusion can list a face that
    is not an end cap first in `endFaces`. An example is a small wall that a two sided cut made where it went through
    a rib of the part. Such a face can lie anywhere on the way of the extrude, so it tells nothing about the length or
    the direction. The answer is True, False, or None when the capture cannot tell:
    - When the reader recorded the normal of the face (`end_normal`), the face is an end cap only when the normal is
      parallel to the sketch normal (the sine between them is 1e-6 or less).
    - Without the normal, the face is an end cap only when its area (`end_area`) is the area of one outline, or of
      all outlines together. The area of each outline comes from its loops (`geometry.combine_volume.profile_area`),
      else from `areas` or `profile_area`. `profile_area` puts the lines and arcs of a loop in order first
      (`footprint.closed_chain`), because the capture can list the curves of a loop in any order and direction. The
      volume checks of a Combine use the same area. The tolerance is 0.1 % of the outline area plus 0.001 mm2
      (`CAP_RELATIVE_TOL`, `CAP_ABSOLUTE_TOL`). The area that Fusion measures and the area of the captured outline
      agree much better than this. A face that is not an end cap, an end cap that merges with a face of the part, or
      an end cap that is partly outside the part, has a different area.
    - A tapered extrude or a thin extrude has end caps with other areas. An outline without an area that the code
      can calculate (text, free curves) gives no area. In these cases the answer is None, and the face stays a
      measure, as before.
    `read_sides` uses a face that is not an end cap as no measure: `measured` is None, the stored direction and the
    stored lengths stand, and `end_check` gives None. The other checks stay, for example the check of Orca that a cut
    through all goes to the side with material. One case is different. A face that is not an end cap can show a
    direction of one side that is not the stored direction. Fusion can store the direction of one side in two ways,
    and the measured face usually decides. A face that is not an end cap cannot decide. When the body that a join made
    shows the direction (`joined_side`), that direction is used. Else the extrude is a problem (`WAY_UNSURE`).
    For all other extrudes with one side, the direction from the stored data, a face or the measured end face must
    agree with `joined_side` when it gives a direction. Else the extrude is a problem (`WAY_UNSURE`). Example. A join
    merges its end cap into the part, so there is no measured end face, and the stored direction says up. The body
    after the step lies wholly below the start plane. The two do not agree, so the step is left out.
  - `joined_side(data, bodies, origin, z)` gives the side of the start plane that a join with one side went to, or
    None. `bodies` is the body before and after the step (`target_before` and `target_after` of the timeline item,
    with `box` and `volume_mm3`). The callers give it to `read_sides` (`bodies`). A join merges all its material
    into the body. Thus, when the volume of the body increased, the material of the extrude is in the box of the body
    after the step. When that box lies wholly on one side of the start plane, the extrude went to that side. Example.
    Posts start on a plane above a round roof and go down to the roof. The body after the step lies wholly below
    that plane, so the posts go down. A box that is larger than the body can only hide the side. It cannot give the
    wrong side. For a cut, a new body, or a body that did not grow, the answer is None.
  - `taper_problem`, `leans_problem` and `walls_confirm` (also in `steps/extrude_checks.py`) compare the taper of the sides with the measured side walls
    (`side_leans`) or, for one outline, with the area of the end face. `volume_problem` compares the volume of an
    extrude of text or spline outlines with the outline area times the length. Both outputs use these checks.
- `tool_chains.py`: the tool bodies of a Combine: the items that make a tool, the place of a tool of another
  component, and the frame of the component a walk builds in. The walk of the recipe and the Orca output both read it:
  - `read(timeline, body, before, component, exported)` gives a `Chain`. `component` is the token of the component
    that the walk is in, or None for the component of the exported body. The `Chain` has these facts:
    - `items`: the items that made the tool before the index `before`, in timeline order (`made_by`). These are the
      items of the component of the tool that list the tool after them. For a tool that a split made, the items of
      the bodies that it was split from are also included, up to each split (`lineage_chain`, the links of
      `capture_model.lineage`). Each item has the measures of the body that it built (`roles.seen_on`).
    - `owner`: the token of the component whose steps made the tool. It is empty for the component of the exported
      body.
    - `links`: the splits that the tool comes through.
    - `unseen`: an item that can change the tool, but that `items` does not hold (`unseen_change`), with the reason.
      This is a step of another component that lists the tool (`CHANGED_ELSEWHERE`). It can also be a step that lists
      the name of the tool with another token (`NOT_FOLLOWED`).
  - `place_of(body)` gives a `Place` for a tool of another component. The reader read the steps of such a tool in the
    coordinates of its own component (`helper_of` items). `move` is the rigid move that carries these coordinates
    into the coordinates of the component of the exported body, at the Combine. It is the frame of the component of
    the tool, then the inverse of the frame of the exported body at that time. When the place cannot be used,
    `move` is None and `problem` is a `Problem` (see `problem.py` above): a code (`PLACE_UNREAD` or
    `PLACE_UNUSABLE`), the plain reason and the cause `otherComponent`. `moves_with` is the reference for the sizes
    that can move the component of the tool (`refs.mark_all`, type `Place`). For a tool of the root component, the
    reference has the mark `root`. The root has no place of its own, but a joint or a Move can move the occurrence of
    the exported body. Thus only the sizes of such assembly items apply (`refs.acting_sizes`). `planes` are the
    measured references of the origin planes of the component, which the probe reads again at other sizes. A tool of
    the root component has no `planes`.
  - `component_frame(capture, bodies)` gives the frame of the component that a walk builds in. `bodies` are the tool
    bodies that the walk is inside, the outermost first. The innermost tool of another component gives the frame of
    its component. Without such a tool, the frame of the component of the exported body applies. The copies of a
    pattern are in assembly coordinates, so the walk carries them into this frame (`steps/repeat.py`, `data_in_component`).
    Both contexts give this frame as `component_frame()`.
  - `is_place_slot(slot)`: the slot of an origin plane that places a tool of another component (`tool<n>.<plane>`).
    Such a reference is the place of the tool, not geometry that a step uses.
  - `sketch_by_name_only(item)`: an outline of the item gives the name of its sketch but no token. In a tool of
    another component, such a sketch can have the same name as a sketch of the part.
  What each output does with these facts is in 3.5 (the recipe) and in `docs/orca-output.md` (the Orca output).
- `dimension_sizes.py`: the dimensions of a sketch graph as formulas of the sizes (`dimension_formulas`), the size
  settings a sketch is tried at (`moving_sizes`, `override_sets`, `near_values`) and the value of every size at one
  setting (`size_values`, `size_env`, which takes overrides by the Fusion name of a size). The shadow check of the probe and the Orca output both read it.
- `paths/`: the path of a sweep. The recipe output and the Orca output both plan
  the path here:
  - `planner.plan(path, profile_frame, profile_points, options)` gives a `PathPlan` or a `Problem`. It chains the
    curves of the path, turns the chain so that it starts on the plane of the outline, and names the kind of path
    (`line`, `arc`, `circle`, `flat` or `corners`). It also writes the flat form and the corners form of a recipe
    sweep step (`PathPlan.recipe`).
  - `model.py`: `PathOptions` and `PathPlan`. `PathOptions` holds what the sweep asks (`as_step`, `twisted`,
    `tapered`, `growth`, `fixed`) and what the output asks. The output gives its caps (`max_segments`, `max_points`)
    and its spline fit (`splines`). By default there is no cap and no spline fit. Without a spline fit, a path with a
    free curve gives the problem `too_complex`.
  - `curves.py` (the geometry of the curves, and the chain), `checks.py` (the limits of the app's sweep as problems:
    crossing, overlap, an outline that reaches past a bend, sharp corners, a path that stops rising), `writing.py`
    (the arc, circle, flat and corners forms), `closed.py` (closed chains), `tolerances.py` and `words.py` (the words
    and the code of each problem).
  The recipe caps stay in `translator/paths/path_limits.py`. The Orca output gives the same caps and the same spline
  fit, so that it takes the same paths as the recipe output. The Orca output does not write the fitted curve. It
  writes each spline of the path exactly, as the pieces of its definition. Before it plans the path, it gives each
  spline its exact end directions (`orca_translate/sweep_splines.py`). Thus the check for sharp corners uses the
  exact directions, and not the directions between two measured points. A spline can also have a corner inside it,
  at a joint between two of its pieces. This occurs when an inner knot occurs as many times as the degree (three
  times in a cubic spline, or any inner knot of a spline of degree one). `sweep_splines` gives the largest turn at
  these joints (`inner_turn_deg`, from `splines.joint_turns`), and the check for sharp corners uses it too. An
  outline keeps such a corner, because Orca draws the same corner.
  The planner itself also finds a corner inside a spline, for both outputs. The spline fit of the recipe makes a
  smooth curve through the points of the spline. Thus it rounds off such a corner, and the copy is wrong. The
  shared fact is `geometry/spline_joints.joint_turns`. It reads the definition of the spline (`flat.nurbs`) and
  gives the turn at each inner knot that occurs as many times as the degree. The weights of a rational spline do not
  change the turn. `curves.inner_turn` gives the largest turn of one curve. `checks.corners_problem` gives the
  problem `sharp_corner` when this turn is more than `SMOOTH_JOIN_DEG`. When the definition cannot be read (the knots
  do not agree with the poles, or the curve breaks at a knot), it gives the problem `unreadable`. A free curve
  without a definition (an edge of a body) has no such check.
- `steps/`: one reader for each kind of step:
  - `sweep.py`: the settings of a sweep: `settings_problem` gives the problem of a guide surface, a guide rail, a
    setting that Fusion did not give, or an orientation that is not perpendicular or parallel, and `cover_problem`
    gives the problem of a sweep that covers only part of its path (`runs_both_ways` says that the second side runs
    the whole closed path too). The limits of twist and taper are not here: each output sets its own (the recipe
    output in `translator/sweep/sweep_settings.py`). The module also holds the points of a sweep outline
    (`profile_points`), its loops (`loop_polygon`, `outline_shapes`) and its centroid. Also the volume of a new body (`made_volume`) and the check of that volume against the outline and
    the path (`volume_problem`), and the check of the end face that Fusion made against the end of the planned path
    (`end_check`). A result that does not agree gives the problem `MISMATCH`.
  - `emboss.py`: the check of an emboss against what Fusion measured (`volume_check`: the change of the part against
    the outline area times the depth, or the end face area times the depth when the outline runs past its face) and
    the face an outline is trimmed to (`trimmed_face`). The recipe output and the probe plan both read it.
  - `loft.py`: the volumes of a ruled loft between two parallel outlines of straight lines, one for each pairing of
    corners that the kernel can choose (`ruled_volumes`), and the check of a measured volume against them
    (`matches`).

#### capture_model and geometry

- `capture_model/step_kinds.py`: the step kind table, with `gap_cause` per type and `pattern_kind()`.
  `capture.py`: `validate_capture`, `CaptureError`, `same_body`. `lineage.py`: `of`, `at`, `bodies`.
  `tool_items.py`: the items that build tool bodies (`makers`, `built_by`, `plan`, `MAX_ITEMS`, `MAX_TOOLS`,
  `MAX_DEPTH`). The frame of a walk is in `design_model/tool_chains.py`.
  `gap_hints.py`: causes and hints (`refusal_cause`). `gap_picks.py`: `pick_records`.
- `geometry/vec.py`: one place for vector helpers. A module does not keep its own `_dot`. `geometry/rigid.py`: `Move`,
  `IDENTITY_ROWS`, `TURN_Z_UP`, `move_from_frame`, `frame_problem`, `move_for`, `axis_angle` (the axis and the angle of
  a turn). `geometry/tolerances.py`: see 4.11. `geometry/plane2d.py`: small 2D helpers on `(x, y)` points: the distance to a segment
  or to a ring, a point inside a ring, and an arc drawn as points the way the app draws it (`to_segment`, `to_ring`,
  `inside_ring`, `arc_points`). `footprint`, the outline checks and the coil fit use them. `geometry/footprint.py`
  also has `closed_chain`, which puts the curves of one loop in order, end to end. `geometry/region_inside.py`:
  whether one region lies inside another (`inside`, exact for lines, arcs and circles), the loops of one frame moved
  into another (`moved_loops`), and points spread over a region (`sample_points`). The check that an extrude lands on
  a face alone and the rays of the reader use them. `geometry/spline_fit.py`: the
  spline of the app (`interpolate`, `evaluate`) and the fit of points to a free curve (`fit`). The sketch outlines of
  the recipe and the free curves of a sweep path use them.

#### probe

- `plan/`: what to read and which rows to run. `covered.py` (`scan`), `references.py` (`refs`), `request.py`
  (`request`, `symmetric_patterns`), `rows.py` (one row, `MAX_PROBE_ROWS`), `near_far.py` (`probe_rows`, `pair_rows`,
  `far_rows`, `far_pair_rows`), `nearer.py` (`nearer_rows`), `extra_rows.py` (`check_rows`, `discovery_rows`),
  `history.py` (what earlier states show). The package re-exports the names the rest of the add-in reads as
  `plan.<name>`. The choice of which sizes get rows is not here any more: it is in `export_plan/probe_flow/sizes.py`.
- `state.py`: `ProbeState`, the record of one probe state (`json()`, `from_json()`, `as_states()`,
  `REPORT_READ_KEYS`), and the comparison of the body in two reads (`box_numbers`, `body_changed`). `build.py`,
  `plan` and `derived` take these records, or the report dicts. Rows stay dicts (`design_edit.runner.row_key(row)`
  gives the key of a row).
- `build.py`: from the states to the motion file (`build`), the spans (`spans`), the outline limits, the body change
  of each size tried alone (`body_changes`). `build`, `StateRun` and the plan entry functions (`probe_rows`, `nearer_rows` and the others) turn report dicts into `ProbeState` records once, with `as_states`. The helpers in `plan/history.py` and `spans` take `ProbeState` records only.
- `match.py`: which read profile stands for which captured profile, values of a state (`state_values`).
- `pieces.py`: how many separate pieces the part is in at a state (`count`, `came_apart`, see 1.8).
- `fit.py`: the straight line fit (`fit_value`, `least_squares`, `fit_residual`, `snap_coefficients`).
  `terms.py`, `series.py`: fits with angle functions and products (`terms.turn_terms`, `series.partners`,
  `series.curve_sizes`). `columns.py`: the parameter columns a written value may follow.
- `ref_fit.py`: the places of other components. `plane_sizes.py`: sizes that may move a sketch plane or a face.
- `derived*.py`: the shadow check from the sketch graphs.

#### params

- `expressions/`: Fusion expression text to an app formula. `reading.py` (tokens and parse tree, `parse`,
  `referenced_names`), `units.py` (unit words, `unit_factor`, `internal_factor`), `translation.py` (`translate_tree`,
  `unit_scale`), `writing.py` (`render`), `formula.py` (`parse_formula`), `functions.py` and `evaluation.py`
  (`evaluate` for the text of a formula, `evaluate_tree` for a parsed tree), `simplify.py` (`collected_sum`), `text.py`
  (`format_number`, `MAX_FORMULA_LENGTH`, `is_constant_expression`), `errors.py` (`ExpressionError`).
- `labels.py`: the readable label of each size (`assign`, see 1.3).

#### design_edit

- `store.py`: `ParameterStore` (the members every parameter store has), `TIMELINE_CONTROLS` (the optional group for a
  design with a timeline) and `timeline_control(store, name)` (the method, or None when the store has none).
- `apply.py`, `runner.py` (`RowExport`, `row_key`), `restore.py` (`restore_parameters`), `marker.py`,
  `timeline_health.py` (`settle_timeline`), `temp_copy.py`, `errors.py`.

#### fusion_reader

- `capture.py`: `read_capture`. `helper_pass.py`: the second pass for tool bodies.
- `read_*.py`: one module per family of step types, each with a `READERS` dict. `read_thread.py` reads the modelled
  thread of a `ThreadFeature` (and the thread info of a tapped hole), `read_coil.py` reads a coil from its parameters,
  volumes and faces (3.12 and 3.13), `read_pipe.py` reads a pipe's section, its cover of the path and its path (3.8.1). `read_geometry.py`: `safe`, boxes, frames, `same_entity`, `foreign`. `read_links.py`, `read_constraints.py`: sketch links and graphs.
- `placement.py`: the place of the body in the assembly, `ref_record`.
- `probe_state.py`, `probe_refs.py`, `read_face.py`, `probe_patterns.py`: the reads at each probe row.
- `read_gap_reach.py`: the reach read.
- `read_face_rays.py`: the rays from the outlines of an extrude to a curved face it ends on (`outline_hits_face`).
- `read_flat_faces.py`: the flat faces of the target body square to the sketch of a join through all, with the marker
  before the step (`target_flat_faces`).
- `rows.py`: `DesignParameterStore` (set expressions, rebuild, health, marker roll, suppression). It has every member of
  `ParameterStore` and of the timeline controls.
- `sketch_keep.py`: `SketchKeeper`. `step_export.py`: the STEP file.
- `parameters.py`: the parameter lists.

### 2.3 How data flows

```
 Fusion design
     |  read_capture (fusion_reader)
     v
 capture dict  ---------------------------------------------+
     |  body_scope, size_table.build (export_plan, params)   |
     v                                                       |
 SizeTable                                                   |
     |  translate(capture, table, OPTIMISTIC)                |
     v                                                       |
 TranslateResult (first look)                                |
     |  read_reach (fusion_reader) when gaps                 |
     v                                                       |
 capture + reach                                             |
     |  SizeProbe + ProbeRun: rows -> read_state (fusion_reader)
     v                                                       |
 states -> probe.build -> Motion (motion file)               |
     |  PutBack: values, items, sketches, marker back        |
     |  translate(capture, table, motion)                    |
     v                                                       v
 TranslateResult (final) -> plan_single_export -> manifest, recipe, gaps, report (capture inside)
     |  write_package (package)
     v
 .paramability zip -> Paramability app
```

Things to note:

- The capture inside `report.json` is the same dict the translator used, with `reach` when it was read. So the
  translation can be run again from the report alone (see 4.4).
- The motion file is not in the report as a file. But `report.json` keeps the probe states (`probe.states`, the
  `report.json` form of `ProbeState`) and the motion (`probe.motion`). A replay rebuilds the motion from the
  states (`motion_for` in `tests/test_local_captures.py`).
- The step kind table (`capture_model/step_kinds.py`) is read from three sides: the Fusion reader (which module reads a
  type), the translator (which handler copies it) and the probe (which sketch records it may follow).
- The put back is not a stage in the diagram, since it happens at several points. `PutBack` makes the calls, in one
  order (1.11).

### 2.4 Pure parts and Fusion parts

Pure (tested directly, no Fusion needed): `package`, `geometry`, `capture_model`, `params`, `sketch_values`,
`sketch_solve`, `timing`, `design_edit` (it works on any object with the right methods), `design_model`, `results`,
`translator`, `orca_translate`, `orca_recipe`, `probe`, `export_plan`, `dialog_model`.

Fusion facing (tested with fakes, and by hand in Fusion): `fusion_reader`, `fusion_ui`, `commands`.

The border is the port and the parameter store. Both are declared once, as protocols:

- `ExportPort` (`lib/export_plan/pipeline/port.py`) and `PartsPort` (`pipeline/parts.py`) list every member the pipeline
  asks of Fusion: `store`, `units`, `timing`, `undo_steps`, `read_timer`, `export_step`, `read_capture`, `read_reach`,
  `probe_reader`, `sketch_keeper`, `progress`, `warn_unrestored`, `warn_left_off`, `warn_steps` and `log`. The real
  ports are `FusionPort` and `FusionPartsPort` (`commands/ExportForParamability/export_flow.py`).
- `ParameterStore` (`lib/design_edit/store.py`) lists the store members (`saved_expressions`, `set_expression`,
  `set_expressions`, `recompute`, `read_value`, `error_items`, `error_entries`, `return_marker`, `marker_holds` and so
  on) and `TIMELINE_CONTROLS` lists the optional ones (`timeline_health`, `turn_on`, `keep_marker`, `roll_marker`,
  `unroll_marker`, `suppress_items`, `unsuppress_items`). The real store is `DesignParameterStore`
  (`lib/fusion_reader/rows.py`).
- `Probe` (`lib/export_plan/probe_flow/interface.py`) is the interface between the try runner and the probe. It is not
  a border to Fusion, but it follows the same rule: one declaration, and a test that checks every class has it.

`tests/test_interfaces.py` checks all of this (see 4.11).

### 2.5 Fakes and test helpers

All in `tests/`:

| File | What it gives |
| --- | --- |
| `context.py` | Puts `ParamabilityExport/` on the import path, so tests import `lib....`. Every test imports it first. |
| `fakes/` (a package, by domain) | The shared fakes. `store.py`: `FakeStore` (a parameter store with expressions as text; options `bad_when`, `breaks`, `reject`, `flaky`, `stuck`, `answers`, `errors`, `on_recompute`), `RollingStore` (also holds the timeline marker) and `TrimStore` (also turns timeline items off). `port.py`: `FakePort` (one body) and `FakePartsPort` (several bodies), with options for the answers a test needs (`reader`, `keeper`, `reach`, `fail_read_from`, `fail_step_at`, `cancel_at`) and the warnings they keep (`warned`, `left_off`, `warned_steps`). `design.py`: Fusion objects for the reader tests (`FakeDesign`, `FakeTimeline`, where new items go in at the marker like in Fusion, `FakeMarkerTimeline`, occurrences, matrices, solids, `FakeBRepManager`). `dialog.py`: the dialog inputs. |
| `translator_helpers.py` | `load_capture(name)`, `translate_fixture`, `edited`, `variant`, `steps_of`, `verdict_of`, `left_out`, `stopped`, `assert_schema_ok`. |
| `probe_helpers.py` | Builders for user and model parameters, sizes, sketch lines and states as the reader gives them. |
| `params_fixtures.py`, `row_helpers.py`, `sketch_graph_fakes.py`, `sketch_solve_helpers.py`, `derived_fixtures.py`, `filter_box_motion.py`, `coil_helpers.py` | Builders for their own test families. `coil_helpers.py` builds the `data` of a coil from exact helix geometry, so a test can break one thing at a time. |
| `schema_check.py`, `schema/` | Checks a recipe, a manifest or a gaps file against copies of the app's JSON schemas. |
| `fixtures/captures/*.json` | About 180 captures, made by hand or saved from real designs. Each test family loads them. |
| `fixtures/motion/*.json` | Motion files for some captures. |

Rule for new tests: use an option of a shared fake for an answer. A test that needs a new answer from a store or a
port adds an option to the shared fake. Subclass a fake store only to act out Fusion behaviour over several calls:
`OrderStore` (`test_put_back_order.py`), `ParkStore` (`test_face_outline_follow.py`), `StepStore`
(`test_timeline_health.py`) and `BatchStore` (`test_row_baseline.py`).

Tests of the layout and of the order:

| File | What it checks |
| --- | --- |
| `test_boundary.py` | The import table, the `adsk` rule and the private names (see 2.1). |
| `test_undefined_names.py` | That every name a module of the add-in uses is bound: by an import, a definition, an assignment, a parameter or a builtin. It also refuses a star import. A missing import fails here, not only in Fusion when the line runs. |
| `test_interfaces.py` | That the real classes, the shared fakes and both probes have every declared member, and that the pure code asks a store, a port or a probe only for a declared member. |
| `test_put_back_order.py` | The order of the calls an export makes to put the design back, on every way it ends. |
| `test_probe_row_schedule.py` | The row phases and the nearer and check rows of a probe or a group. |
| `test_probe_state_record.py` | The `ProbeState` record and its `report.json` form. |
| `test_step_kinds.py` | The step kind table, its handlers and the readers. |

`tests/test_pipeline.py`, `tests/test_pipeline_gaps.py` and `tests/test_parts_pipeline.py` run the whole pipeline
against `FakePort` or `FakePartsPort`: a simulated Fusion, with reads you can script per row.

`scripts/fixture_geometry.py` computes the box and the volume of a capture fixture from its steps (it needs numpy).
Run it after you edit a fixture: `python3 scripts/fixture_geometry.py <fixture name> --write`.

## 3. Key ideas, with examples

The examples in this part are made up. They show the logic, not a real design.

### 3.1 How a sketch point becomes a formula from tries

#### The problem

A sketch has a corner point. The designer placed it with two dimensions, so that its x is `Width / 2 - Wall`. With
`Width = 40` and `Wall = 3`, the corner sits at x = 17.

The capture does not hold the rule `Width / 2 - Wall`. It holds only the number Fusion drew: 17. To write x as a
formula, the add-in measures it at other values.

#### The keys

Every value the translator writes for a sketch has a key (`lib/sketch_values/keys.py`). The key says which step,
which profile, which loop and which field:

- `4/p0/l0/center.0`: step 4, profile 0, loop 0 (the outer loop), the x of the centre;
- `4/p0/l1/radius`: the radius of the first hole;
- `4/p0/plane`: how far the sketch plane moved along its normal;
- `7/positions/2/0`: the x of the third hole point of step 7;
- `9/axis/point/1`: the y of a revolve axis point;
- `12/path/c3/end.0`: a field of curve 3 of a sweep path;
- `15/r/plane/offset`: how far a measured plane of another component moved.

The probe and the translator use the same keys, so they talk about the same numbers.

#### The tries

The probe reads E0 and then the rows. Here the corner value at each state:

| State | Width | Wall | x read |
| --- | --- | --- | --- |
| E0 | 40 | 3 | 17 |
| Width near min | 30 | 3 | 12 |
| Width near max | 50 | 3 | 22 |
| Wall near min | 40 | 2.25 | 17.75 |
| Wall near max | 40 | 3.75 | 16.25 |

#### The fit

`fit_value` in `lib/probe/fit.py` looks for `x = const + a * Width + b * Wall`:

1. It takes the columns (one per parameter) that change in some state. It sorts first the columns that change where
   the value changed.
2. It tries one column, then two, up to four (`MAX_COLUMNS`). For each set it solves a least squares fit of the
   changes of `x` from E0.
3. A fit counts only when every state agrees within 0.0001 mm (`FIT_TOLERANCE` in `lib/geometry/tolerances.py`). It must also have enough states: the
   columns must change in at least one more state than there are columns. Else the fit is not trusted (cause
   `untried`).
4. Each coefficient is snapped to the nearest k / 24 when that keeps every state within the tolerance. So 0.4999999
   becomes 0.5.

Here the result is `const = 0`, `Width: 0.5`, `Wall: -1`. The motion file keeps it as an `Affine`:

```json
"4/p0/l0/points.1.0": { "const": 0, "terms": { "Width": 0.5, "Wall": -1 } }
```

The translator (`sketch_motion.raw`, then `curved.render`) writes it as the formula `0.5 * Width - Wall`. It checks
that the formula gives the captured number (17) within 0.001 mm. It checks that a width, a height or a radius stays
above zero over the ranges. Then the recipe point is `{ "expr": "0.5 * Width - Wall" }`.

A term can also be a model parameter. Then the translator writes it through that parameter's own expression, so the
formula reads only sizes.

#### When no straight line fits

Some values move along a curve. Example: the end of a leg of length `L` that turns with an angle `A`: `x = L * cos(A)`.
No straight formula fits. Before it gives up, the probe tries a sum of terms (`lib/probe/terms.py`): each size, the
product of two lengths, and for an angle `sin`, `cos`, `tan`, `cot` of the angle and of half the angle, alone or times a
length. At most 3 such terms. The sum is used only when every state follows from the others (leave one state out, fit,
and the fit must still give that state). The check rows (1.8, step 6) give the extra states for this test. The motion
file keeps it as `Terms`:

```json
{ "const": 0, "sum": [ { "k": 1, "of": [["", "L", 1], ["cos", "A", 1]] } ] }
```

The translator writes `L * cos(A)` (angles in degrees).

A corner on a leg that turns often needs more than 3 terms. Example: the end of a leg that starts at the end of
another leg, with `x = L1 + L2 * cos(A)`, and the corner set back by a wall `W` along the turned leg. Then `x` needs
`L1`, `L2 * cos(A)`, `W * cos(A)` and more. The search one term at a time can miss such a sum. So, when it fails, a
second step runs (`terms.turn_terms`, `_turned`):

1. It takes every term of a turn at once: each size, and for each angle size its sine and its cosine, alone and times
   each length size.
2. It solves for all of them together.
3. It drops the terms that the fit does not need (it prunes), and it checks the rest with the same leave-one-out test.

Some sizes move the value only after the angle turned. Example: at `A = 0` a leg lies along the line it moves, so a
row that sets only that leg moves nothing. `series.partners` finds such a partner size. It compares a state that sets
the angle and the size with a state that sets only the angle to the same value. When the two values differ, the size
is a partner, and the fit takes it in.

#### When nothing fits: Stuck

A value that cannot be fitted is `Stuck`, with the sizes that move it and a cause:

| Cause | Meaning | Reason text (from `notes.stuck_reason`) |
| --- | --- | --- |
| `curve` | It moves along a curve no formula follows. The translator first tries to cut the ranges (3.2, "An outline that would cross itself"); it marks the size only when no cut works. | "it moves Sketch3 along a curve, which cannot be copied yet" |
| `shape` | The outline changes (a line appears, two profiles merge). | "Sketch3 makes a different outline at other values" |
| `turns` | The sketch plane turns. | "it turns the plane of Sketch3" |
| `unread` | A state did not give the value. | "Sketch3 could not be read at other values" |
| `untried` | Not enough states. | "it changes Sketch3 and could not be tried at other values" |

The translator writes the captured number and doubts the sizes. When only some sizes are to blame, the probe also fits
`rest`: what the value follows once those sizes keep their value. The other sizes then still follow. So one bad size
does not freeze the whole sketch.

A different outline is special. When a size changes the outline only in its own row, that is a limit of its range,
not a reason to drop it (see 3.2).

### 3.2 How a range is cut

#### An example

`Width` is 40 mm. Its default range is 20 to 80. A fillet in the part fails above about 70. The rows go like this
(checked with `lib/probe/plan/`):

| Row | Width | Why this value | Result |
| --- | --- | --- | --- |
| near min | 30 | 25 % below | builds |
| near max | 50 | 25 % above | builds |
| far min | 20 | range end | builds |
| far max | 80 | range end | Fusion does not rebuild (Fillet2 in error) |
| nearer | 65 | half way between 50 (built) and 80 (failed) | builds |
| nearer | 72.5 | half way between 65 and 80 | fails |
| nearer | 68.75 | half way between 65 and 72.5 | builds |
| (none) | | 68.75 and 72.5 are within a tenth of the way (`BISECT_GAP`) | stop |

The probe keeps the span of `Width`: `low` 20, `high` 68.75, and `failed` `[[80, "Fillet2"], [72.5, "Fillet2"]]`.

The translator (`tried_ranges.built_ranges`, `failure_cut`) then cuts the range to 20 to 68.75. The reason comes from
`notes.cut_reason`:

"Width: the range stops at 68.75, since Fusion did not rebuild the design at 72.5 (Fillet2)."

The reason names the nearest failure past the cut end.

#### When a near row fails

If the row at 50 had failed, the next row on that side is nearer: a tenth of the way to 80, so 44 (the half and the
quarter are not nearer than 50). The progress window says "Width at 44 mm. The last value did not work, so this one
is nearer." The far end 80 is still tried later, since a far end that builds gives the widest span.

#### The rules around the cut

- Only a failure in a step the part is built from counts (`tried_ranges.part_step`): an item of the body's component, or a step
  that built a tool body. A failure in another component cuts nothing.
- A row that Fusion builds can still be wrong. A step can show a warning: for example, a revolve whose outline crosses
  its axis. Fusion then builds a shape that the copy cannot match. Thus a step of the part that shows a new warning
  counts as a failure. The runner reads the steps in warning after each try (`apply.new_warnings`, through the store's
  `warning_entries`, which reads `TimelineObject.healthState`). A step that was in warning or in error before the
  first try (the baseline) does not count. Only a step that the part is built from counts (`counts_warning` of the
  probe, which the runner gets). When such a step reads in warning after a rebuild of only the changed steps, the
  design is recomputed in full once and read again, as for errors. A step that is in error after that recompute makes
  the row a row that did not build. A warning on any other step costs no recompute. The result of the row then has
  `warned`, the names of those steps. The trim turns some timeline items off for the tries, and these items show no
  warning while they are off. Thus, when the items come back on before the discovery rows, the runner measures the
  baseline again (`RowExport.rebase`). A warning that such an item has in the person's design then does not count. `SizeProbe.add_states` keeps such a row as a state that did not build, with `failed` the first
  of those steps that the part is built from, and `warned` true. Thus the rows nearer to the value now and the halving
  run as for a failure, and the range stops at the farthest value that built without a new warning. The span keeps
  the try in `failed`, and in `warned` too, so the reason says what Fusion showed: "Height: the range stops at 11.8,
  since Fusion shows a warning on Revolve1 at 12.5." (`Cut.warned`, `notes.warned_why`). A warning on a step of
  another component changes nothing.
- A typed end is never cut. Then the size keeps its typed range and says "it was followed between A and B; beyond that
  it could not be tried".
- A size whose row changed a followed outline is cut in the same way, at the farthest value that kept the outline
  (`outline_cut`). Reason: "Width: the range stops at 55, since Sketch3 makes a different outline at 60."
- A size whose row left the part in several separate pieces is cut in the same way, at the farthest value tried in one
  piece (`tried_ranges.split_cut`, `Motion.spans[size].split`, `Cut.split`). Reason: "Width: the range stops at 55, since
  the part comes apart into 2 separate pieces in Fusion at 60." This happens when copies of a pattern or a join no
  longer touch the part, or when a cut cuts the part in two. The app builds a part only in one piece. The reasons
  "no value other than 40 could be copied" and "could not be measured" name such tries too. A typed end is never cut,
  as for the other cuts.
- A cut leaves an end that it does not move at its exact value. It does not round that end to hundredths
  (`kept_ranges.holding_ranges_where`).
- A size that built at no value other than its value now is not a size. Its reason: "no value other than 40 could be
  copied, since ...".
- A size that did not rebuild at any value tried is doubted up front: "the design does not rebuild in Fusion at 30
  (Fillet2) or 50 (Fillet2), the nearest values tried, so it could not be measured".
- When the person typed a wide range and the rows covered less, the size is loose: "it was followed between 20 and
  68.75; beyond that it could not be tried".

#### Cuts that come from the recipe rules

Some limits come from the app, not from Fusion. The handler calls `ctx.cut(ranges, why)` with the values inside which
the rule holds (`kept_ranges.holding_ranges`):

- A taper that follows sizes must stay under 45 degrees (the app refuses a steeper one).
- A draft or revolve angle must stay above zero. Since the default range of a small angle starts at 0, the range is
  cut to start at 0.01 (`values._kept_above`). A length or count that leaves its working range is cut the same way.
- A "to entity" length must not pass its own start.
- A coil: the wire must clear the axis, the turns must not touch each other, and the turns of coils and threads together
  stay under 100 (3.13).

When no cut can keep the rule (every size it reads has a typed range), the sizes are marked loose instead.

#### An outline that would cross itself

A curved outline can follow its sizes well inside the ranges, and still break in a corner of the ranges. Example: a
leg turns with an angle, and at the shortest leg and the largest angle it crosses another leg. Then the outline would
cross itself or lose a corner. Before, the translator marked the sizes "along a curve". Now it cuts the ranges first
(`sketch_crossings.order_ranges`):

1. For each loop, it writes checks that must stay above zero while the corners keep their order.
2. It tests these checks over the ranges with the same settings as the whole-range check (`range_check.sweep`): every
   mix of the range ends, the middles of the ranges, and the probe's built states inside them.
3. It cuts the ranges to where every check holds (`kept_ranges.holding_ranges_where`).

The reason says "the outline of Sketch3 would cross itself or lose a corner". The sizes are marked "along a curve"
only when no cut works.

In a parts file, a size read by several bodies gets the narrowest cut over the bodies.

The first check works for corners that the translator rebuilt from curves that cross. Other outlines need a check too. A
corner can follow a size while the curve it meets is written as a plain number, since that curve moves along a curve that
the probe could not fit. So a second check runs for every written outline whose corners follow sizes
(`sketch_crossings.simple_ranges`, called by `sketch_motion._crossing_cut`). It runs when `order_ranges` made no cut. It
also runs for rectangle and circle loops, for the loops of a flat face that the probe read (3.3), and for the face that
an emboss is trimmed to. It tests at the same settings as `order_ranges`: every mix of the range ends, the middles of the
ranges and the states of the probe inside them that built. At each setting it works out the written corners, and it
holds every loop to the rule that the app holds sketch loops to:

- no two edges cross, touch (within 0.0001 mm) or fold back on each other;
- an arc is drawn as 16 chords, the way the app draws it (`geometry/plane2d.py`, `arc_points`);
- every hole stays inside its outline: every point that the app samples on the hole lies inside the outline and is
  0.0001 mm clear of its edges.

Where a loop breaks only past some values, the ranges are cut. The reason reads "the outline of Sketch3 would cross
itself, lose a corner or have a hole reach its edge". The check costs time, so it has limits:

- An outline of more than 300 points is not checked (`MAX_SIMPLE_POINTS`).
- The far ends are cut first, and each setting is worked out only once.
- One check is made for each outline in one translation, since the walks of one translation write the same outline
  many times (`OutlineChecks`).
- The checks of one translation share 20 seconds (`OUTLINE_CHECK_SECONDS`, timed as `timing.phases.outline_check`).
  When the time is used up, the sizes behind an outline that was not checked are marked "there was no time left to
  check that the outline of Sketch3 does not cross itself".

When no shorter ranges keep the loops (they break at the values now, or a size behind them has a typed range), no cut is
possible. The sizes that move the loops are marked loose with the crossing reason.

The add-in cuts where Fusion fails and where the outline rules fail. The app cuts what is left when the file opens: it
builds the ends of every range in its own kernel (1.12, "The range end check").

### 3.3 How a face or a construction plane follows sizes

Rounds, chamfers and shells pick edges and faces by measured points. An extrude can start from a face or reach to one.
If the face moves when a size changes, a fixed point would pick the wrong face. `lib/translator/faces/follow.py` places such
points on what the copy knows.

#### A point on an earlier extrude

Every written extrude is kept as a `Slab`: its sketch placement, its outline and its length. A point is placed against
the slabs, latest first.

Example. `Extrude1` draws a 40 by 20 rectangle and extrudes it by `Height` (10 mm). Later, `Fillet1` rounds the four
top edges, and `Shell1` opens the top face.

- The top face is the end face of `Extrude1`. It moves with `Height`. So `Shell1` writes
  `{ "featureFace": "extrude_1", "which": "end" }` instead of a point. The app finds the face on the extrude itself.
- The four top edges are exactly the edges of that end face. So `Fillet1` writes
  `{ "featureEdges": "extrude_1", "which": "end" }`.
- A point half way up a side wall writes its height along the extrude as a formula: `0.5 * Height`.
- A point inside an end face moves with the face when the outline follows sizes (`inner_pick.anchor`). The add-in tries
  the 3 nearest outline corners, nearest first. It takes the first corner whose move keeps the point inside the written
  outline, with some room to its edges, at every size setting of the range check. When no corner works, the point
  follows the centre of all corners. A round or a rectangle uses its centre. One corner gives a formula a few times
  shorter than the centre of all corners, so it stays under the 300 character cap.
- This corner rule is for a face that a step picks by a point inside an end face. An edge that a step picks inside an end
  face is different. Such an edge comes from another step, and the add-in found no side walls that cross it. A corner
  can carry the point off that edge when the sizes change. So an edge point always follows the centre of all corners
  (`inner_pick.centre`). Example: a chamfer picks an edge inside the top face of a symmetric outline. When the depth
  grows, the centre stays on the middle line and the point stays on the edge.
- A point that no slab places "may sit on geometry that moves". Then every size the steps before it read is marked
  loose, with the step named in the reason.

#### A face of another body

An extrude can start from a face of another body, or reach to it. That other body is often a helper body: the designer
uses it only to give the extrude a place.

Example. `Body1` is a helper box. Its height is `Height` (10 mm). `Body2` is the exported body. The extrude of
`Body2` starts 3 mm above the top face of `Body1` (`Lift`).

- The walk builds `Body2` only. It does not write the steps of `Body1`, so it keeps no slab for `Body1`.
- The capture keeps the body of each face that a step uses (`body` in the face record). When that body is not the
  body that the walk builds (`Context.is_target`, also through the lineage), the face is never "on this body"
  (`follow._another_body`, `follow._beyond_tool`). This is also true when a slab of `Body2` has a face at the same
  place. That slab face is not the face that the step uses.
- A body with the name of the exported body under another token is also another body. A name does not prove that
  it is the same body: a copy, a split piece or a renamed body can have that name. Fusion can give the exported body a
  new token along the timeline, but then the walk stops at the first step that shows the new token (`roles.lost`).
  So such a face never reaches this rule.
- No slab places the face. Thus every size that the items before the step read can move it
  (`reach.any_face_sizes`). These sizes are marked, and the face counts as a face that the copy cannot follow.
- When the probe measured the face, the measured move is written instead (see the next part). In the example, the
  sketch origin of `Body2` gets `z = { "expr": "Height + Lift" }`. Both sizes stay free.
- This rule is for a step outside a tool. In a tool, the walk that holds the tool places a face that is not on the
  tool (`_beyond_tool`, see the tool walk).

#### A face that the probe measured

The probe reads a flat face or a construction plane again at every try when an extrude starts from it or reaches to
it (`reach.moving_reaches`). The slabs can also give a move for that face. Two answers are then available. The
translator uses the move of the slabs only when these two conditions are true (`extrude/reach_motion.py`,
`target_shift`):

1. The slabs place the face without a doubt.
2. The move of the slabs is equal to the measured move at each try that built and that set the free sizes inside
   their ranges (`_agrees`). The tolerance is 0.001 mm (`AGREE_TOL`). At least one such try must be available,
   unless neither move follows a size. Without a try, nothing proves that the two moves agree.

When one condition is false, the translator writes the measured move (`_measured_shift`). It also writes the
measured move when the measured move is stuck, because then the two answers cannot be compared. Thus a move that
the slabs work out never wins over a move that the probe saw.

Example. The slabs say that a face does not move, because nothing that the walk wrote reads a size yet. The probe
tried `Height` at 7.5 mm and at 12.5 mm, and the face moved by -2.5 mm and +2.5 mm. The two answers are different
at these tries. So the translator writes the measured move, `Height - 10`, and `Height` stays free.

#### The picks that Fusion was given: faces and tangent chains

A round or chamfer set can get its edges from faces (every edge around each face) or from a tangent chain (every edge
that runs on from a picked edge without a corner). At other sizes, such a pick can hold more edges or fewer edges. A
copy that picks each edge by a point does not see these edges. Thus the handler (`finishes/finish.py`,
`_edge_steps`) picks the edges in this order:

1. Whole sets of one size, all picked only by faces or all picked only by tangent chains: the step writes the pick
   of Fusion (`_input_pick`). Sets picked by faces write `faceEdges`, the edges around the face points. Tangent chain
   sets write one point for each edge that was an input (`seed`) and `chain: tangent`. This pick comes before
   `featureEdges`. The edges of one extrude are the same edges now, but at other sizes the pick of Fusion can hold
   other edges.
2. Whole tangent chain sets of different radii in one round (`_chains_of_sizes`): the step writes one point for each
   seed, `chain: tangent`, and `edgeSizes` with the radius of the set of each seed. The app gives each edge of a
   chain the size of the point that the chain grew from. Thus all the chains are rounded in one step, as Fusion
   does, and a chain that grows at other sizes keeps the radius of its set. These conditions must be true: each set
   is picked only by edges, the sets have no edge in common, the edges of each set have one radius, each set has a
   seed, and all the seeds fit in one pick (32 points). A pattern or a mirror copies the seed points with their
   sizes.
3. The edges of one extrude (`featureEdges`), when all the edges have one size.
4. One point for each edge.

The recipe cannot say the pick of Fusion for these cases: a step that mixes sets picked by faces and sets picked by
tangent chains, sets of different sizes picked by faces, a chamfer set that is split by the face of its first
distance, part of a set, and picks with too many points. Each step of the copy is then a different operation than
the one step of Fusion, so the steps can only be the same where the sets do not meet. The capture cannot show that
the sets stay apart at all sizes. Thus, for steps 3 and 4, when a set was picked by faces or by a tangent chain, the
handler marks the sizes that can change which edges the pick holds (`_mark_own_picks`). These are all the sizes that
the steps before the round or chamfer read (`reach.any_face_sizes`). Each one is marked "may give unexpected results".
The first translation of an export marks nothing.

#### A construction plane

A step can use a construction plane: a sketch on it, an extrude that reaches to it, a mirror across it, a split along
it. The reader records what the plane is (`read_reference.describe_plane`): an origin plane, or `made_by`,
`definition` and `built_on`.

Example. `Lift = 12 mm`. A plane is offset from the XY plane by `Lift`. A sketch on it draws a boss.

- An origin plane stays. Nothing moves.
- An offset plane: the translator finds the parameter of its distance (`reach.offset_param`). The plane moves along its
  normal by that distance. So the sketch origin of the boss gets `z = { "expr": "Lift" }`.
- Fusion sometimes gives an offset plane a second parameter, a fixed extra offset. The distance is followed only where
  it matches the measured plane.
- A midplane follows its two bases. Chains of planes are followed too.
- Any other plane built on the part (at an angle, through an edge, tangent, along a path) cannot be followed from its
  definition. The probe then reads the plane at every row (`reach.moving_reaches`, `extrude/reach_motion.py`, `target_shift`) and the
  translator writes its measured move as a formula. Only a size the probe could not follow is marked.
- The reader reads the members of the plane or axis definition that name what it is built on (`_BUILT_ON_MEMBERS`
  in `read_reference.py`). Each name comes from the `ConstructionPlane...Definition` and
  `ConstructionAxis...Definition` objects of the API reference. An entity of another component goes into `built_on`
  as `{ "foreign": true }`.
- Sometimes the reader cannot tell what a plane is built on. The definition can be unreadable, or the chain can be
  deeper than three levels. Then the plane has no `built_on`. `reach.on_part` counts such a plane as built on the
  part. It also counts a plane with a `{ "foreign": true }` entry as built on the part. The export does not measure
  how those bases move, so the sizes are marked. This rule prevents a wrong copy: a plane that moves in Fusion, but
  stays where it is in the copy.

#### A turning axis

A revolve, a circular pattern and a Move turn about an axis. The reader records what the axis is
(`read_reference.axis_with_reference`): an origin axis, a construction axis, an edge, a face or a sketch line.

Example. `AxisAt = 5 mm`. Sketch2 has a vertical line at `AxisAt` from the origin. A revolve turns a rectangle of
Sketch1 about that line.

- The record of the axis has `entity_type: "SketchLine"`, the name of Sketch2, `sketch_reference` (what Sketch2 sits
  on) and `sketch_projected` (true when Sketch2 holds projected geometry).
- The probe follows the line in Sketch2, so the recipe writes the axis point as a formula of `AxisAt`.
- The probe reads the line in world coordinates at every try. Thus a try also measures a move of the plane of
  Sketch2. But the probe measures only the sizes that it tries. The probe tries each size that can move or turn the
  line (`probe/plane_sizes.axis_sizes`, which uses `reach.reference_sizes`). These are the sizes of Sketch2, the sizes
  that can move the plane or face that Sketch2 sits on, and the sizes that can move the projected geometry in
  Sketch2.
- Sketch2 is not the sketch of the outline. Thus the outline does not mark the sizes that move the plane of Sketch2.
  The recipe output marks them at the axis (`ref_motion.check_own_axis`, `_check_axis_line`): each size of
  `reach.reference_sizes` that the probe did not try with Sketch2 measured (`sketch_motion.tried`). When there is no
  motion file, it marks all these sizes. The axis point then stays as measured.
- When the line is in the sketch of the outline, the outline marks the sizes of its plane
  (`sketch_motion.placement_doubts`). The axis adds no mark.
- The Orca output writes the axis as numbers. `reach.reference_sizes` gives `AxisAt`, so the Orca result marks it.
- For an axis on an edge, a face or a construction axis, the probe does not follow the axis. Both outputs write it as
  numbers and mark the sizes that can move it (`ref_motion.check_own_axis` in the recipe output, `kept_refs.mark` in
  the Orca output).
- An axis record of an older capture does not say what it is. Both outputs then mark every size that an earlier
  step reads.

#### A face used as an outline

An extrude or an emboss can take a flat face of the part as its outline. `lib/translator/sketch/face_outline.py` writes it in
one of three ways:

1. Followed: the probe read the face before its step at every row. Its loops and its plane are written as formulas. The
   ranges are cut where its loops would cross itself, or where a hole of the face would leave the face
   (`simple_ranges`, 3.2). The reason reads "the outline of the face Extrude3 starts on would cross itself, lose a
   corner or have a hole reach its edge". The face that an emboss is trimmed to is checked the same way.
2. Same outline: the face is the top or bottom of an earlier extrude without a taper, and nothing changed it. The
   copy draws that extrude's outline again on a plane at the face. The outline then follows that extrude's sizes.
3. As measured: any other face is written as numbers. The sizes the earlier steps read are marked loose. This is also
   the result for a face that the probe did not read, for example in an export of an older add-in: the face stays as it
   was measured, and its sizes stay loose.

#### A place of another component

A step can use a plane, axis or point of another component. The reader records it as a `ref` with its token. The probe
reads it again at every row (`probe_refs.py`) and fits how far it moves (`ref_fit.py`). The translator
(`ref_motion.py`) writes the move as a formula, or marks the sizes that act on that component when the place turns or
was not measured.

For one size and one place, `sketch_values.coverage.ref_answer` gives the answer of the motion file: still, moved or
not measured. A size that no try set to another value is not measured (`coverage.tried`). It is never still, because
the tries tell nothing about it. This is important for the size of a joint, or of a move that places an occurrence:

1. Such a size can move every place of another component (`refs.acting_sizes`).
2. The probe tries it as a linked size (a link with `via: "assembly"`, see below). The row limit or the time limit can
   still leave it without a try.
3. When no row set it, the answer is "not tried". The translator gives the size a doubt that names the step and says
   that the size was not tried at other values. The size is then loose, or left out with that reason when no formula
   reads it. The audit does not say "nothing in this part moved with it".

A motion file without states (a test file written by hand) cannot tell which sizes were tried. Its values are then the
answer. The same rule applies to a sketch (`translator.sizes.sketch_answer`).

The probe can try such a size like any other size. The try changes the parameter, and Fusion moves the occurrence
through its joint or move when it rebuilds. The reader reads each place through the occurrence where it is now, and
brings it into the coordinates of the part as the part is now (`fusion_reader/probe_refs.py`). The put back restores
the parameter, and Fusion puts the occurrence back when it rebuilds. The tries keep every joint: the marker roll keeps
the assembly items before the marker, and the timeline trim turns nothing off when a joint comes before the stop
point. An export does not start when the position of a moved part is not captured (`position_pending`).

The facts that do not need the probe are in the shared layer, `lib/design_model/refs.py`. Both translators use them:

- `acting_sizes` gives the ticked sizes that can move the reference. It also tells if the capture can say this. An old
  capture has no data on where the parameters act. The sizes are of two kinds:
  - The sizes whose user parameter acts on the component that owns the reference (`params.geometry_links.acts`).
  - The sizes of the assembly. These are the sizes whose user parameter acts on an item that can
    place an occurrence: a joint, another assembly item of the timeline (a rigid group, a motion link), or a Move whose
    inputs are not bodies or faces. Such an item is usually in the root component, not in the component that it
    moves. The capture does not say which occurrence such an item places. Thus these sizes apply to every reference
    of another component. They do not apply to a reference of the component of the exported body (`own`).
    `design_model.step_links.places_occurrence` finds these parameters. The geometry links use the same test: such a
    parameter gets a link (`via: "assembly"`) to every sketch of the part that is tied to another component, for
    example a sketch that projects an edge of that component. Thus the size counts as a size that the sketch reads
    (`reach.sketch_sizes`):
    `reference_links` gives such a parameter the same kind of link to every component whose plane, axis, point or
    face a step of the part uses (not the component of the part itself). Thus:
    1. The probe tries it like a size behind a sketch dimension. When the row limit leaves it without a try, it is
       listed as not tried. The dialog offers it as linked: "It may move Cover in the assembly, and the step ...".
       A joint parameter is still not ticked to start with.
    2. The recipe translator follows the sketch as the probe measured it. It marks the size when no try set it, or
       when there is no motion file.
    3. The Orca output marks the size, because it writes the sketch with its numbers.
- `mark_all` marks those sizes with a doubt: the copy keeps the reference where it is now. When the capture cannot say
  which sizes can move the reference, `mark_all` calls `movers_unknown` on the recorder, and the output decides (see
  `recorder.py` in 2.2).
- `is_foreign`, `bring_in`, `why_foreign` and `from_old_export` read the `foreign` and `assembly` records (see 1.9.1
  and 3.10).

The translator calls `mark_all` when it has no measure of the reference. The Orca output has no motion file. Thus it
keeps every reference of another component where the capture puts it, and calls `mark_all` for each reference of a step
that it copies (`orca_translate/other_components.py`). A size that acts on that component thus never shows as "not
used" in the Orca result.

The Orca output also copies a tool body of another component (`orca_translate/tools.py`). It uses the facts of
`design_model/tool_chains.py`:

1. It writes the steps of the tool in the coordinates of the component of the tool, because the reader read them in
   these coordinates. Each step gets the name of its component ("Extrude1 of Rod"), because the names of steps can be
   the same in two components.
2. It writes an Orca Transform on the tool. The Transform carries the tool by the move of `tool_chains.place_of`. Orca
   turns the tool about the origin of the component, then moves it. The shape that the copy keeps for its checks
   moves in the same way.
3. It marks the sizes that can move the component of the tool (`refs.mark_all`, "Combine1 puts its tool at the place
   of Rod that may move with it"). Thus such a size shows as "partly" or "fixed", and never as "variable" only. These
   are also the sizes of a joint or a Move in the root that places the occurrence. For a tool of the root component,
   only the sizes of the assembly apply, because the root has no place of its own.

The Orca output leaves the Combine out (cause `otherComponent`, `refused` or the cause of the step) when one of these
is true:

- The place of the component cannot be used (`Place.problem`), or the tool record does not name its component.
- The Combine is inside a tool of another component. Then the place of the inner tool is not known relative to the
  outer tool.
- A step of the tool was not read in the coordinates of its component (no `helper_of`), or an outline of a step gives
  the name of its sketch but no token (`sketch_by_name_only`).
- A step of the tool is a Split Body. The split rules look for a later step that uses another piece of the split.
  They look only in the component of the part, so they cannot see such a step in the component of the tool.
- A step of a third component changes the tool (`Chain.unseen`, cause `changedFromOtherComponent`).
- A step of the tool cannot be copied. The reason names that step.

Inside a tool of another component, the copies of a pattern are carried into the frame of that component
(`Context.component_frame`).

The reader gives an outline of another component's sketch in two ways. In the first way, Fusion gives the profile
through the occurrence of that component. The reader then reads the place of the sketch through that occurrence. In
the second way, Fusion gives the native profile, with no occurrence. This is the usual way for an extrude, a revolve,
a loft or a sweep that a person made with the operation New Component. That step and its body are in the new
component, but the sketch stays in the component that was active (often the root). Fusion reads the operation of such
a step as New Body. The reader then reads the place of the sketch from the component of the sketch
(`placement.native_sketch_placement`). A sketch of the root gets the frame of the root. A sketch of another component
gets the place of the one occurrence of that component. When that component has more than one occurrence, the place
is not known, and the step stays a gap. The size probe reads the place of the sketch in the same way at each try.

An outline of another component's sketch follows the same rules (`design_model/borrowed.py`). When the motion file has
values for the outline, the outline follows them like an outline of the part's own sketch. When it has none, the outline
is written as numbers, and every size that can move that sketch is marked. `borrowed.movers` finds these sizes:

1. The sizes that the dimensions of the sketch read. These come from the `sketch_params` of the profile, from the model
   parameters of its dimensions (the name of the sketch in the component of the sketch), from the `dependents` that
   name the sketch by its token, and from the dimensions of its sketch graph.
2. The sizes that can move the component of the sketch (`refs.acting_sizes`). These include the sizes of a joint or a
   Move that places an occurrence.
3. The sizes that can move the plane of the sketch (`reach.borrowed_plane_sizes`). The plane can be on a face of the
   part. Thus a face, or a construction plane built on geometry, gives every size that the body's component reads
   before the step.
4. The sizes that can move geometry projected into the sketch. The sketch graph of the sketch (found by its token)
   tells where each projection comes from. A projection of the part gives every size that the body's component reads
   before the step. A projection of a third component gives the sizes that can move that component.

When the capture cannot say which sizes act on a component, or the sketch has no graph, `bring_in` calls
`movers_unknown` on the recorder. The translator then writes a note. The Orca output then marks every ticked size.

A sweep or a loft cannot check that a borrowed outline still meets the part. Thus it marks the sizes that `movers`
found (`translator/sketch/borrowed.py`, `mark_unchecked`). It reads them from the `borrowed_movers` key of the profile.

A borrowed outline keeps the name of its sketch. That name can be the same as the name of a sketch of the part. Thus no
code may find the sketch of a borrowed outline by its name. `reach.placement_sizes` gives no sizes for the plane of such
a sketch, and the Orca output finds no sketch graph for it.

### 3.4 How a Split Body is translated

A split makes new bodies. Later steps may belong to the other piece. So a split normally stops the copy. The add-in
copies a Split Body only when the picked body comes out of it as one piece, and the other pieces stay apart from it.

#### The lineage

When the picked body was made by a split, its token is new at that split. The steps before the split built the body it
was split from. `lib/capture_model/lineage.py` finds the chain: `of(capture)` gives `[(index of split, parent body)]`.
During the walk, `Context.is_target` answers yes for the parent body before the split. The steps before the split read
the parent's measures (`body_states`, from the reader). The shared layer gives these measures
(`design_model/roles.py`, `seen_before_split`). The Orca output reads them in the same way.

#### The checks

`bodies/split_rules.py` (`stop_reason`, used in the walk) and `bodies/split.py` (`handle`) check:

1. The split's tool was read (`data.tool`). An older export without it stops with "What this split cuts with was not
   read. Exporting again with this version of the add-in reads it."
2. The kept piece is among the bodies after the split.
3. No later step changes another piece together with the part ("Fillet3 changes Body2, another piece of this split,
   together with the part. That is not copied yet."). A later Combine that takes a piece as a tool is fine.
4. The pieces add up to the volume of the body that was split (within 0.01 mm3 or 0.1 percent).

#### A split by a plane

Example. A cup is split by the YZ origin plane. The kept piece lies on the +X side. The other piece lies on the -X side.

1. `_side` checks that the kept piece's box lies on one side of the plane (within 0.01 mm), and every other piece on
   the other side.
2. The copy removes the far side with a cut by a big box: a `toolBody` with `combine: "cut"` that holds one extrude of a
   square on the plane, facing away from the kept piece.
3. The square reaches far past the body (4 times the half diagonal plus 100 mm, times how much the sizes may grow the
   part, at most 25 times). So the part stays inside the box at every size.
4. The plane follows sizes like a mirror plane (`follow.place_plane`, see 3.3). A split by a plane offset by `Gap`
   moves the box with `Gap`.

#### A split by a body

The reader measures, for each piece, whether it lies inside the tool body (`inside`, `read_split.inside`). It tries two
ways:

1. It moves a point 0.01 mm into the piece, under each of the first 16 faces of the piece, and asks the tool body with
   `BRepBody.pointContainment`. The first face that gives an answer decides.
2. When no face tells, it intersects a temporary copy of the piece with a temporary copy of the tool
   (`TemporaryBRepManager`, nothing is added to the design). What is left gives the answer: 99.9 percent of the piece or
   more means inside, and 0.1 percent or less means outside. Any other result gives no answer. A boolean that fails gives
   no answer too (it often fails for faces that coincide, since a piece shares its split faces with the tool). A
   piece and a tool that are seen in different coordinates (one of them through an occurrence) give no answer either.

Exports of the add-in from before 0.10.6 have no `inside` at all.

The translator takes the answers in `design_model/steps/split.py` (`resolve`). The kept piece outside the tool becomes a cut by
the tool. The kept piece inside the tool becomes an intersect with the tool. The Combine code writes it
(`combine.write_tools`). A split by a surface or a curved face stops the copy.

When an answer is missing (an old export, or a read that failed), these rules hold:

- A missing answer is filled only for a split into exactly two pieces. The two pieces lie on opposite sides, so the
  answer of one piece gives the answer of the other. When neither piece has an answer, the boxes and the volumes decide
  (`decide`). A piece whose box is not inside the box of the tool cannot lie inside it. A piece that is larger than the
  tool (by more than 0.1 percent of the volume) cannot lie inside it either. The boxes must settle the question: when
  both pieces could be inside, or neither, there is no answer.
- The boxes never replace an answer that the reader gave. When the boxes and the reader disagree, there is no answer,
  and the copy stops with "The copy could not tell which pieces of this split lie inside its tool body."
- With three or more pieces, only the answers of the reader count. Example: a disc split by a tube leaves a core, a ring
  inside the tube and an outer ring, so the sides are not certain from the boxes.
- A tool of another component is not decided from boxes, since its box is in other coordinates.

### 3.5 How a Combine and its tool bodies are translated

A Combine joins, cuts or intersects tool bodies with the part. Each tool body is made by its own steps.
`combine.step.handle` (`lib/translator/combine/step.py`) does this:

1. It checks the operation and that the Combine changes the exported body. A Combine where this body is only a kept
   tool writes nothing.
2. For each tool, `tool_walk.build` walks the steps that made the tool, with the same item loop, in a child context
   whose target is the tool. Handlers do not know they work on a tool. The shared layer gives these steps
   (`design_model.tool_chains.read`, see "design_model" in 2.2).
3. It decides the form:
   - Flat: when every tool is made only of steps that add material (a new body, then joins), each tool step is written
     onto the part with the Combine's operation. Cutting A then B removes A and B together. This form opens in older
     app versions. For an intersect, only one tool of one step can be flat.
   - Tool step: else each tool becomes one `toolBody` step that holds the tool's steps (recipe version 15). A tool with
     a gap inside is always a tool step. Only a gap of a step that finishes surfaces can stay inside a tool (see
     "A gap inside a tool body" below).
   - A pattern of bodies that the Combine takes whole becomes a tool per source and one `pattern` or `mirror` step
     (`body_copies.py`), so its count and spacing can follow sizes.
4. It checks the volumes. A Combine that changes the part by more than its tools can give is left out ("This combine
   changes the part by more than its tool bodies hold ...").
5. An intersect of several tools: Fusion does not document whether it keeps what every tool holds or what any tool
   holds. The reader tests both on temporary copies (`TemporaryBRepManager`, never added to the design) and records
   `intersect_model`. When both give the same volume, the sizes of the tools are marked.

A tool from another component is read in its own frame (the second pass, 1.6). The Combine moves its steps into the
part's frame with the tool's place in the assembly (`tool_move`, with the move of `tool_chains.place_of`). A size that
moves the tool's component follows when the probe measured it, else it is marked ("puts its tool at the place of Rod
that turns with it").

A tool that cannot be built makes the whole Combine one gap. The reason names the step that stops the tool. It is
two sentences: the first names the tool body and the step the way the timeline shows them, the second is the reason of
that step, as it is: "The tool body Body3 cannot be copied because of its step Thicken1. Steps of type thicken are not
copied." No kind word follows the step name, and the reason of the step is not joined into the first sentence, so it
keeps its own capital letter and full stop.

Both outputs give this sentence from one place, `design_model.words.ToolStop`, so the recipe and the Orca copy say the
same. A tool built from another tool can stop for a step of the inner tool. Then the sentence names that step once and
the tool body that holds it: "The tool body Body2 cannot be copied because of the step Thicken1 in the tool body
Body3. Steps of type thicken are not copied." It does not name the Combine steps in between. To do this, a `Refusal`
(recipe) and a `Skip` (Orca) that say a tool body cannot be built carry the `ToolStop` as `stop`, and the Combine
that meets such a step passes it to `ToolStop.through`. The recipe walk keeps it in `TranslateResult.refusal_stop`
beside `refusal_cause`. The cause of the inner step goes on as before, so the hint stays right. The handlers of the Orca output name the body that they work on with
`Context.body_words`. On the part, this is "the part". While the Orca output builds a tool body, this is "the tool
body Body3". So the reason of a round, a chamfer or a cut in a tool body names the tool body and not the part (see
`docs/orca-output.md`).

**A gap inside a tool body.** The walk of a tool can leave a step out (a gap), as the walk of the part can. The
Combine then looks at each gap of the tool (`tool_walk.unfinished`, `tool_walk.shaping_gap`):

- A gap of a step that only finishes surfaces stays in the list of the `toolBody` step. These steps are a round, a
  chamfer, a draft, an emboss and a cosmetic thread. The gaps file marks such a gap with `finishing: true`
  (`gaps/finishing.py`).
- Any other gap makes the whole Combine one gap. Examples are a Move, an extrude, a shell and a Combine of the tool.
  Such a step can change the place of the tool or the material of the tool. Without the step, the tool sits at a
  different place or holds different material. A join, a cut or an intersect with that tool gives a wrong part, and
  the gap in the tool does not show this. For example, a sphere that a Move lowers into a box and an intersect that
  keeps the shared part give a dome. Without the Move, the sphere holds all of the box, and the copy is a flat box.
- The reason names the tool body and the step, in the same words as for a tool that cannot be built
  ("The tool body Body2 cannot be copied because of its step Move1. ..."). The cause of the gap in the tool goes to
  the Combine, so the hint stays right. The gaps inside the tool are dropped with the tool.

A pattern of bodies that the Combine takes whole is checked in the same way. When a source of the pattern has a gap
that does not only finish surfaces, the Combine does not write the pattern (`_whole_patterns`). It walks each tool on
its own, and that walk refuses the Combine and names the step.

**The Move of a body with no corners.** The Move handler (`bodies/move.py`) measures what the body did from its first
vertices before and after the Move. A sphere, a torus and a closed revolve have no vertices. For such a body the
reader also reads the box of the body before and after the Move (`boxes_before`, `boxes_after`). A box moves by
exactly the same vector as the body when the body only shifts. A box does not show a turn. Thus the handler does
this:

- A Move along X, Y and Z must move the box by its distances. Then the handler writes the Move with its distances as
  sizes. A box that moves by a different vector, or that changes its size, refuses the Move.
- A free Move whose transform only shifts must move the box by that shift. A free Move that turns refuses.
- A Rotate and the kinds that only the points can measure (point to point, to a position, along an entity) refuse.
  The reason says that the body has no corners.
- A body with no box after the Move refuses ("could not be measured").

The Orca output uses the same box shift for a Move along X, Y and Z only (`orca_translate/bodies.py`, `_motion`).

A tool may not hold a thread or a coil together with other steps. The recipe keeps these kinds out of a tool body
(`RecipeKind.in_tool`, 1.9.2), since they build on the whole part. A Combine, or a pattern of bodies, whose tool walk
wrote such a step refuses. The Combine becomes one gap with the cause `coilTool` or `threadTool`. One case is different:
a Combine whose tool is one coil body. There the coil is written onto the part with the operation of the Combine (the
flat form). The reader tells the handler which bodies a coil made (`data.made`), so the check "the step makes one body"
looks at those bodies and not at every body of the component (`_writes_flat`).

### 3.6 How a mirror is translated

`repeat.body_copies:mirror` is the handler of every mirror item. A mirror of bodies is handled like a pattern of bodies
(`body_copies.py`: the copies are matched to their sources by their corners). A mirror of features goes to
`repeat.mirror` (`repeat/repeat_mirror.py`). This section is about the mirror of features and of the whole body.

- A mirror of features writes a recipe `mirror` step that repeats the source steps (`of`) across the plane. The source
  steps must be repeatable: a step that Fusion recomputes per copy (it reaches to a face, or cuts through all) is
  refused as a source.
- A mirror plane that sits on a face or edge of the part follows sizes (`follow.place_plane`). When the plane moves by
  `d`, the copies move by `2 * d`.
- A mirror plane record that does not say what it is (an older capture) stays where it was measured. The sizes that
  can move it (`reach.reference_sizes`: every size that an earlier step reads) are marked.
- A mirror of the whole body repeats every earlier step when that gives the body joined with its image
  (`repeat_mirror_reach.py`). When it does not (a round, chamfer, shell or Move among the steps, a gap, a cut across the
  plane, a body on both sides), everything written so far is gathered into one `toolBody` step, and the mirror repeats
  that. A gap then stays one missing step inside the tool.
- A mirror of a gap is left out too ("It repeats Extrude5, which is missing from the copy.").

### 3.7 How a draft is translated

`draft.handle` (`lib/translator/finishes/draft.py`) writes a recipe `draft` step: the faces (picked by points), the neutral plane
and one angle. A Symmetric draft with faces on both sides of the plane also writes a second angle, `angleTwoDeg`.

The difficulty: Fusion's API does not say which way its angle and its flip lean a face. So the copy reads it from the
part:

1. Every drafted face must lie on one side of the neutral plane, or the draft must be Symmetric (see step 5). Else the
   draft is left out ("This draft leans faces on both sides of its plane, so the way it leans cannot be checked.").
2. The volume must change. A draft that takes material off leans the faces in on that side. One that adds material
   leans them out. So the sign of the recipe angle comes from `volume_after < volume_before` and the side.
3. The angle must be under 30 degrees (`MAX_ANGLE_DEG`, the app's cap). Two angles from the same formula are fine.
4. The angle follows its parameter. Its range is cut to stay above zero and under 30 degrees, so the default range of
   a 3 degree draft becomes about 0.01 to 29.98.
5. A Symmetric draft with faces on both sides of the plane leans the part of each face on the pull side and the part
   on the other side by the same angle, away from the plane or both toward it. So both parts take material off, or
   both add it, and the sign comes from the volume change alone, with no side. The recipe step gets `angleDeg` and
   `angleTwoDeg` with the same value and the same sign. Both follow the same size. This is the only step that needs
   recipe version 17 (`DRAFT_VERSIONS` in `translate.py`). A Symmetric draft with all faces on one side stays a step
   with one angle, so it needs no new version.
6. A Two Sides draft with two different angles is left out ("This draft gives each side of its plane its own angle,
   and the copy cannot tell which angle leans which side."). Fusion says only "the first side" and "the second side"
   of the plane, not which one is the side the pull direction points to. One volume cannot tell it. The copy does not
   guess, because a wrong guess is a wrong part. A Two Sides draft with two equal angles and faces on one side stays as
   it was: the volume gives the sign. With faces on both sides it is left out, since Fusion does not say that two equal
   angles lean like a Symmetric draft.
7. The neutral plane follows sizes like a mirror plane.

Example: two side walls of a 40 by 20 by 10 block are drafted by `Taper = 3` degrees about the bottom plane. The
volume goes from 8000 to 7900 mm3. The walls lie above the plane, so the copy leans them in: `angleDeg: { "expr":
"Taper" }`. With a Symmetric draft about a plane at half height, the walls lie on both sides of the plane. The volume
goes from 8000 to 7900 mm3, so both sides take material off: `angleDeg` and `angleTwoDeg` are both `{ "expr": "Taper" }`
and the recipe is version 17.

### 3.8 How a sweep is translated

`sweep.step.handle` (`lib/translator/sweep/step.py`). The other sweep modules of the recipe output
(`sweep_limits.py`, `sweep_rules.py` and the rest) sit next to `step.py`. The shared parts are in `design_model`, and
the Orca output uses them too:

- The path planner is in `lib/design_model/paths/` (see 2.2). It gives a `PathPlan` or a `Problem`.
- The points of the outline, the volume check and the end face check are in `lib/design_model/steps/sweep.py`.

The recipe output asks the planner with its own caps and its spline fit (`paths/path_limits.options`). It turns a
problem into a refusal with the same words and the same cause (`paths/path_limits.refusal`).

The outline must be one closed sketch outline (holes allowed). Several outlines become one sweep each along the same
path.

The path decides what is written (`planner.plan`):

| Path | Written as |
| --- | --- |
| a straight line | an extrude of the outline (`extrude.handle`), so later rounds follow its sizes |
| one arc or a full circle | a revolve about the arc's axis (`revolve.handle`) |
| a chain of lines, arcs and splines in one plane | a `sweep` step with a flat path |
| lines joined by tangent arcs in 3D | a `sweep` step with a corners path |
| a closed chain in one plane | a `sweep` step with `closed: true` (version 16), cut open where it meets the outline's plane; sharp corners between lines are mitred |
| any of the above with a twist, a taper or a parallel orientation | a `sweep` step with `twistDeg`, `taperDeg` or `orientation` (version 16) |

The checks before writing:

- The path must start on the outline, square to it, and run one way.
- No crossing, no bend tighter than the outline (`design_model/paths/checks.py`).
- Sharp corners: see below.
- A new body must have the volume the outline and the path give (outline area times path length; for a closed path,
  Pappus' rule). With mitred corners, see below.
- The end face Fusion made must lie where the path ends (`design_model/steps/sweep.py`, `end_check`).
- Many settings are refused: a guide rail, a twist with a taper, part of a path, a surface sweep and others
  (`sweep_limits.py` holds the texts).

Sharp corners. A sharp corner is a place where two curves of the path meet at an angle. Fusion builds a sharp corner
between two straight lines of a flat path as a mitre: the two straight pieces meet on the plane that halves the
corner. A test export confirmed this for open paths too (the volume was the outline area times the path length). The
copy does the same (`design_model/paths/checks.corners_problem`):

1. A corner between two lines of a flat path, open or closed, is mitred. This is so only when the sweep does not
   twist, does not taper and does not keep the outline direction.
2. The corner may turn by at most 160 degrees (`MAX_MITRE_DEG`). A sharper turn has no usable mitre.
3. A mitre needs straight path on both sides of the corner: the outline's reach across the path's plane times
   tan(turn / 2). So a line between two corners needs room for both mitres. When a line is too short, the sweep is
   left out.
4. Any other sharp corner is left out with the cause `sharpCorner`: a corner next to an arc or a spline, a corner in a
   3D path, or a corner on a sweep that twists or tapers. The hint says to round the corner with a sketch fillet.
5. A corner inside a spline is left out with the cause `sharpCorner` too (`curves.inner_turn`). Examples are a
   spline of degree one (a polyline) that turns, and a cubic spline with a corner point. The recipe writes a spline
   as a smooth fitted curve, which cannot keep such a corner.

The check of the size ranges (`path_rebuilt.rebuilt_refusal(mitres=...)`) uses the same rule. The volume check counts
each mitred corner too. For a closed path, Pappus' rule counts 2 tan(t/2) for a corner that turns by t, instead of t.
For an open flat chain of lines with the outline beside the path, `design_model/steps/sweep._open_lines_volume` counts the same
for the offset of the outline's centre.

On a closed path, an outline that sits on a corner seam moves to the middle of the line it is square to
(`design_model/paths/closed.py`, `PathPlan.moved`). There the path is straight, so the cut that opens the ring is clean. A closed
path with `distance_two` = 1 is the whole ring, which is Fusion's default. A twist on such a sweep is refused.

Guide surfaces. A sweep can follow a guide surface. The reader records them as `guide_surfaces`
(`SweepFeature.guideSurfaces`). A listed surface means "not copied yet" (cause `guideSurface`). Some Fusion versions
do not give the list. Then the reader sees an `InternalValidationError` when it reads the orientation, and it cannot
read the twist and the taper either. This mix means "likely a guide surface", and the sweep is left out with the same
cause. The hint says to sweep along the same path without the guide surface, or to build the shape with a loft.

The path follows sizes when the probe measured a path of sketch lines and arcs (`path_motion.py`). The path rules are
then tested over the size ranges and the ranges are cut where they stop holding (`sweep_rules.py`). Any other path is
written as measured, and the sizes behind its sketch are marked.

Fusion does not document how it measures the sweep taper or which way the twist turns (`TAPER_MEANING_CONFIRMED` and
`TWIST_SIGN_CONFIRMED` are false). So a written twist or taper gets a note that asks the person to check the shape,
and marks its sizes.

### 3.8.1 How a pipe is translated

`pipe.handle` (`lib/translator/sweep/pipe.py`). A pipe is a sweep. Fusion draws the outline of this sweep itself: the
section. The handler makes this section, puts it into the data of a sweep, and gives the data to the sweep handler
(3.8). Thus the path of a pipe is planned, checked and written by the same rules as the path of a sweep. A refusal of
the sweep handler keeps its reason, but the reason names the step a pipe ("This pipe ...").

The reader (`lib/fusion_reader/read_pipe.py`) reads these values:

- `section`: `circular`, `square`, `triangular`, or `other`.
- `section_size`: the diameter of a circle section, in mm.
- `hollow` and `section_thickness`: the wall of a hollow pipe, in mm. The thickness is null when the pipe is solid.
- `distance_one` and `distance_two`: how much of the path the pipe covers. `distance_two` is null on an open path.
- `operation`, `participants` and `path` (the same path record as a sweep). Fusion gives the path only when the
  marker is before the pipe.
- `faces_after`: a point and a normal on each start face and end face, with the marker after the pipe.

The facts of a pipe are in `lib/design_model/steps/pipe.py`. Hand check PI1 gave them:

- The section is at the start of the path. The start is the start of the first curve of the path, in the direction
  of the path (`opposed` turns the curve).
- The section is square to the path at the start, and its centre is on the path.
- The section size is the diameter of the circle.
- The wall of a hollow pipe goes inward from the section size. A thickness of 2 mm on a diameter of 10 mm gives a hole
  of 6 mm.

A circle that moves along a path makes the same shape from each end of the path. Along a closed path, it makes the
same shape from each point. Thus the start only tells the sweep which end face is the start face and which is the end
face. The end face check of the sweep (3.8) compares this with the end faces that Fusion made.

But the start must be an end of the path, never a joint inside it. When Fusion does not give `opposed` for the first
curve, the start is the end of the first curve that the second curve does not touch. This rule applies unless the
path is known to be closed (`closed` true); a path whose `closed` could not be read counts as open. When both ends or
no end of the first curve touch the second curve, the start is not known and the pipe is left out.

The handler writes the section as a profile record: one circle, and a second circle for the hole of a hollow pipe.
The plane of the profile is square to the path at its start. The sweep handler then writes an extrude for a straight
path, a revolve for one arc or a full circle, and a `sweep` step for a chain.

Sizes:

- The section size and the wall follow sizes. The probe measures no sketch for the section. Thus, while the sweep
  handler writes the outline, the handler gives the radii of the circles as motion values (`_section_values`). The
  outer radius is half the section size. The radius of the hole is that value less the wall. These values use the
  parameters of the pipe, so they follow the sizes behind those parameters. The rules of an outline then apply to
  them over the size ranges: a radius stays above zero, the hole stays inside the circle, and the circle stays clear
  of the tightest bend of the path. A size that breaks one of these rules is marked.
- Before that, the handler cuts the ranges where a radius would reach zero (`_open_section`). For a hollow pipe this
  is where the wall would close the hole: the radius of the hole, half the size less the wall, must stay above zero
  at every mix of the range ends. The cut is recorded, so the written ranges stop there. While the sweep handler
  writes the step, the size table has the cut ranges, so the rules of the outline and of the path are tested inside
  them. Thus the sizes are cut, not marked. When no shorter ranges keep the hole open (for example, ranges that the
  person typed), the outline marks the sizes as for a drawn circle.
- The first translation (with `OPTIMISTIC`) writes the outline as numbers. There the handler writes the radii as
  formulas of the section values (`_first_look`). Thus the sizes behind the section count as sizes that a copied
  step reads, as the distance of an extrude does. The size probe then does not try them on a guess. A size that the
  probe tries on a guess, that changes the body and that moves no followed sketch, is marked as "it changes this part
  in a way the copy does not follow" (`body_moved`). Without this, the section sizes got that mark.
- Without a motion file, the radii stay numbers and the sizes behind them are marked.
- The path follows sizes in the same way as the path of a sweep. But the copy keeps the section where Fusion had it.
  Thus a size that moves the start of the path is marked (`_keep_start`). A size that turns the path at its start is
  held by the sweep rule that the path must start square to its outline.

These pipes are left out:

- A square or triangle section (cause `pipe`). The API does not tell which way the section turns about the path.
- A pipe along a part of its path: `distance_one` is not 1, or `distance_two` is set and not 0 (cause
  `pipePartOfPath`).
- A closed path that starts on a sharp corner (cause `sharpCorner`). It is not known how Fusion closes the pipe
  there. Fusion starts a closed path of lines on a corner, so a closed path of lines only is always left out.
- A section, a cover of the path or a path start that cannot be read, and an export of an older add-in that did not
  read pipes ("Export again with this version of the add-in", cause `oldExport`).
- All that the sweep handler leaves out.

A sharp corner of an open path is mitred, as for a sweep (3.8). Hand check PI2 showed that Fusion mitres a pipe:
the two legs of a 90 degree corner meet on the plane that halves the corner, and the volume is the section area times
the path length. The app builds a sharp corner of a sweep as a mitre too (`BRepBuilderAPI_RightCorner`). The limits
of a sweep apply: corners between lines in one plane, at most 160 degrees, with room for the mitres.

The Orca output does not copy a pipe. The step kind table gives the pipe the cause `pipe`, so the Orca gap has the
same tip.

### 3.9 How a loft is translated

`loft.step.handle` (`lib/translator/loft/step.py`) copies a loft through exactly two sections with free ends. Fusion joins two such sections with straight
faces, so the recipe `loft` step is ruled. Holes are paired by the nearest centre and need the same count on both
sides. The planes of the sections must not cross.

A section can be one of three things:

1. A closed sketch outline. It is written like an extrude outline, and it follows sizes.
2. A closed flat loop of edges. The reader gives it as a path record (`Path`).
3. A flat face of the part.

The second and the third kind are written as measured (`loft/loft_sections.py`). So they do not follow sizes. The sizes of
the steps that made them are marked as for any measured outline.

A new body of two parallel outlines of straight lines must have the volume the kernel's pairing of corners gives
(`design_model/steps/loft.py`). Another volume means Fusion paired the corners another way: the loft is left out. Outlines of
different shapes get a note.

Left out: three or more sections, a point end, a curved face, an open or non-flat loop of edges, end conditions,
rails, a centre line, a closed loft and a surface loft.

### 3.10 Why a step becomes a gap or a stop

The rule: a gap when the effect of the step stays on the body and the rest still reads right; a stop when the body
after the step is unknown.

A step becomes a gap (left out, recipe still written):

- its type has no handler, and the reader saw it change the body (`target_changed` true): a thicken, for example;
- it is a modelled thread or a coil that the copy cannot hold (a profile that is not a 60 degree form, a taper, a spiral,
  a cap that is passed, a step in a tool body: see 3.12 and 3.13);
- its handler answers a `Refusal` (an extrude with a taper on a face, a revolve axis it cannot use, a draft with two
  different angles);
- it reaches into another component in a way the copy cannot follow (`foreign` records). An add-in before 0.10.6
  marked the part's own sketches and planes, when seen through an occurrence, as records of another component. The
  capture tells which add-in version read it (`addin`). When that version is before 0.10.6, a step whose only such
  records are sketch outlines, planes or axes is left out with the cause `oldExport` and the tip to export again
  (`design_model/refs.py`, `old_writer` and `from_old_export`). A capture with no version, or with a later one, is
  never taken for old. A missing key of a record does not tell the version. An edge or a face record is never taken
  for old;
- it picks faces of a gap, or may pick them (`cause: picks`);
- it is a pattern or mirror of a gap;
- it is a Combine whose tool cannot be built;
- it is an extrude join that meets only material of earlier gaps, so it would float apart from the copy (1.9.3).

A step stops the copy (fixed shape):

- the place of the part in the assembly cannot be used, or the part comes from a linked design;
- a step of another component or an assembly item changes the part;
- the body cannot be followed (a new token with the same name);
- the bodies of the step cannot be read (`bodies_after` null), or its reader failed (`read_error`);
- Fusion shows the step in error;
- the step splits the part or makes another body, except a Split Body that `split_rules` allows;
- a step with no handler whose effect cannot be told (`target_changed` null);
- a handler answers `Refusal(stops=True)` (the split handler does this);
- the gap would come before the first written step, or inside a tool of another component;
- there would be more than 256 gaps;
- the recipe breaks a cap (more than 400 steps, a pattern of more than 256 copies, too deep nesting), it is too large
  (over 8 MB), or the gaps file cannot be written.

A stop that has a cause carries its hint: the `refusal` record holds it, the early warning in the dialog shows
"Tip: ...", and the package note adds it when it fits (1.9.3).

A step is passed by (skipped, no gap) when it is suppressed, a sketch, construction geometry, a step of another body
that is never joined to the part, a Remove of another body (`target_changed` false), or a Split Face that left the body
unchanged.

### 3.11 How a pattern with copies on both sides is translated

A pattern direction can be symmetric: the copies spread to both sides of the original. A recipe pattern starts at the
original and runs one way. So `lib/translator/repeat/symmetric.py` writes a symmetric direction as two parts that both start
at the original: a forward part and a backward part.

The rule for the places, for `count` copies:

- An odd count: the original is the middle copy. There are `count // 2` steps each way.
- An even count: the original is one of the two middle copies. There are `count // 2` steps one way and one less the
  other way. Fusion's rectangular patterns put the extra copy ahead of the original, the way the distance points
  (`FUSION_EXTRA_SIDE = 1`). Test exports showed this at counts 4, 6 and 8.

The step between copies. With a `spacing` distance, the distance is the step, as usual. With an `extent` distance, the
distance is the reach ahead of the original. So the step is `distance / (count // 2)`, not
`2 * distance / (count - 1)` (`repeat_lattice._extent_gaps`). Example, made up: an extent of 30 mm and 7 copies give a
step of 30 / 3 = 10 mm. With 6 copies the step is also 10 mm, and the copy behind stops one step short.

A count that follows sizes. When a size can make the count even, the side of the extra copy matters. `extra_side`
decides it:

1. When the count is even now, the measured copies show the side.
2. When it is odd now, the copies that the probe read at tries with an even count show it (1.8, "What a state holds").
3. Without such a try, the side Fusion was seen to use is taken (rectangular patterns only). A negative distance flips
   that side. This flip is not confirmed in Fusion yet.
4. When the copies at a try break the rule, or no side is known (a circular pattern without an even try), the sizes
   that can make the count even are marked. The reason says "Pattern3 spreads copies to both sides of the first one,
   and where Fusion puts them for an even count was not confirmed".

`value_at` gives the value of the count at a try, so the copies of that try can be compared with the rule.

Two more details:

- The frames of the copies are in assembly space. For a part placed in the assembly, the translator first carries them
  into the part's frame (`design_model/steps/repeat.py`, `data_in_component`, with the frame of `Context.component_frame`,
  which reads `design_model.tool_chains.component_frame`). The probe's reads of the
  copies are carried the same way (`read_in_component`).
- A direction with a distance of 0 makes copies on top of one another. Fusion keeps a count of 3 in an unused second
  direction, for example. The translator ignores that direction and merges such copies.

Circular patterns. Fusion's transforms of a symmetric circular pattern are not always right for the copies behind the
original. So an odd count is taken as centred, but only when every copy is listed and kept (none suppressed or left
out by number), the original is among them, and every copy turns by a whole number of steps. Else the pattern is
refused. An even count of a symmetric circular pattern stays marked.

The places of the copies of a symmetric pattern come from the element transforms. The checks of 3.21 apply to them:
two copies on one place, or places that do not fill the count when no copy is suppressed, leave the step out. Each
copy whose faces were read must sit where its place puts the faces of the original. A probe try that reads two copies
on one place counts as a try that breaks the rule.

### 3.12 How a thread and a tapped hole are translated

A recipe `thread` step is a helical thread of a set form on a cylinder. It holds an axis (origin and direction), a length,
the major diameter, the pitch, the minor diameter, whether it is internal, and the hand (written only for a left hand
thread). It can also hold the pitch diameter (`pitchDiameter`, in mm). This is the diameter where the ridge of the
thread is half a pitch wide. The app cannot find it exactly from the major diameter, the minor diameter and the pitch,
so it reads the number from Fusion's thread info (`ThreadInfo.pitchDiameter`). The field is optional. The translator
writes it only when Fusion gives a value that lies between the minor and the major diameter. It writes it only in a
recipe of version 17 or newer. A recipe gets that version for other reasons, for example a shell or a draft with two
angles. The pitch diameter never raises the version by itself, because an app that does not know the field would
refuse the recipe for a detail that it can do without. When the recipe stays below version 17, `translate._walk`
removes the field from every thread step, also inside a tool body. The Orca output does not use it: the Orca thread
feature has a pitch and a depth, and no pitch diameter. The form is a 60 degree form. Fusion's metric and Unified profiles are that form.

#### A cosmetic thread

A cosmetic thread changes no solid. The handler writes nothing and adds the note "The thread is not copied; the exported
shape has none either." (`hole.step.thread`). The verdict is `skipped`. When a gap is a cosmetic thread, its `finishing`
flag is true (1.10).

#### A modelled thread

`read_thread.py` reads a modelled `ThreadFeature`:

- the `threadInfo`: the profile name, the designation, the class, `isInternal`, `threadPitch`, the major and the minor
  diameter and `threadAngle`;
- `isRightHanded`, `isFullLength`, `threadLength` and `threadOffset`;
- the faces it sits on (`inputCylindricalFaces`). For each face it gives the cylinder (origin, axis, radius), the span of
  its end vertices along the axis, a point on the face, and whether the face looks away from the axis (a bolt) or toward
  it (the wall of a hole);
- after the step, `made_span`: the same span for the faces that the thread made.

`docs/capture-format.md` has the exact fields. Every member is read on its own. A member that cannot be read is null, and
the translator then leaves the thread out. It never guesses. Fusion keeps lengths in cm, and they leave the reader in mm.
`threadAngle` is in degrees already.

`hole/thread.py` (`feature`) checks these points in this order (`read_feature` in `design_model/steps/thread.py` does
points 1 to 5; it gives a `Problem`, and `feature` turns it into a refusal with the same sentence and cause). A failed
check is a refusal, so the thread is a gap:

1. The profile. A given angle must be 60 degrees (within 0.01). The name must say metric or Unified. A name with acme,
   trapezoid, whitworth, BSP, NPT, pipe, buttress, square or taper in it is refused (cause `threadProfile`).
2. The numbers. The pitch, both diameters and the hand must be there. The pitch must be 0.2 to 10 mm (cause
   `threadLimits`). The thread must have a usable depth.
3. The faces. They must all be cylinders with one axis and one radius, and they must touch each other.
4. Inside or outside. The thread info and the direction of the face must agree. The diameter must fit the cylinder: the
   minor diameter for an internal thread, the major diameter for an external one, within 0.3 mm. This also catches a
   unit mix-up in the read.
5. The start. A full length thread starts at the low end of the cylinder. Fusion uses the length and the offset only for
   a thread that is not full length. Fusion 2706 gives no length and no offset for a full length thread, so the
   handler does not look at them for such a thread. When the faces that the thread made are measured (`made_span`),
   they must reach both ends of the cylinder. A partial thread must have an offset of 0. It starts at the end that the
   faces it made touch (`made_span`). When that cannot be told, the thread is left out.
6. The caps. At most 8 threads in one recipe (cause `threadLimits`). A thread is refused while the walk is inside a tool
   body.

The length and the start follow the sizes that move the end faces of the cylinder (`faces/follow.py`). A size that changes
the diameter of the cylinder is marked, since a thread fits one diameter.

The recipe starts every thread at its own standard angle, and Fusion starts it somewhere else. So the step gets the note
"The thread starts at a standard angle, not where Fusion starts it." Hand check TD1 compares the shapes.

#### The turn budget

Threads and coils share one cap: 100 turns in all in one recipe (`threadTurnsTotal` in the app).
`translator/turn_budget.py` adds up the turns of every thread (its length over its pitch) and of every coil that the walk
wrote so far, in the walk and in the walks around it, in timeline order. The step that would pass the cap is left out,
and so is every later one (cause `threadLimits` or `coilLimit`). A thread whose length could pass the cap at some size
keeps its number, and its sizes are marked.

#### A tapped hole

A Hole step with a tapped thread that is modelled is written as two things: a hole at the minor diameter of the thread,
and an internal `thread` step for each hole position (`design_model/steps/thread.py` `hole_spec`, and `hole/thread.py` `hole_threads`). Before, such a hole was
a gap. This path is unproven until hand checks TD2 and TD3 pass (see the end of this part). The depth of each thread:

- a through hole: measured from the entry to the point where the bore comes out of the part, less the start of the
  thread (see below and "Where a through hole comes out");
- a blind hole: the depth of the hole, less the start of the thread;
- a thread over part of the length: `thread.depth` (a parameter that can follow a size);
- when it cannot be told whether the thread is full length, the hole is left out.

The thread starts at the mouth of its bore (`thread_mouth` in `design_model/steps/thread.py`). The mouth is not always
the top of the hole:

- A simple hole: the mouth is at the position of the hole.
- A counterbore hole: the counterbore is wider than the thread, so the thread cannot start in it. The mouth is at the
  bottom of the counterbore, at the counterbore depth below the position.
- A countersink hole: the cone of the countersink is wider than the thread down to the depth where the cone narrows
  to the drilled bore. The mouth is at that depth: (countersink diameter - bore diameter) / 2 / tan(countersink angle
  / 2). The bore diameter is the minor diameter of the thread.

The reader also measures the faces that the thread made (`made_span`). It gives how deep below the position of the
first hole the vertices of these faces are, along the direction of the hole. `hole_depth` in
`design_model/steps/thread.py` uses these numbers as a check. Thus the copy does not assume where Fusion starts the
thread. It copies the thread only when the measured faces agree with the mouth:

- The faces must start at the mouth, within one pitch and 0.5 mm. Else the hole is left out.
- A thread over part of the hole must have measured faces, and they must end at the mouth plus `thread.depth`, within
  one pitch and 0.5 mm. Else the hole is left out. Thus a thread length that Fusion counts from the top of the hole
  gives a gap, not a thread that is too long.

`hole/thread.py` (`hole_threads`) writes each thread from the mouth: the position of the hole moved along the
direction of the hole by the start. `hole/step.py` (`_thread_start`) gives the start as a value that follows the
sizes: the counterbore depth, or the cone depth from the countersink diameter and the hole diameter. Thus the start
and the length of the thread follow a size that changes the counterbore depth. The countersink angle is pinned
already, so the cone depth stays exact.

The Orca output copies the thread of a tapped hole with a counterbore. The thread starts at the counterbore floor
(`threads.hole_lengths` gives the start from `hole_depth`). The measured faces of the thread (`made_span`) must be
there; without them the hole is left out (cause `tappedRecess`). The Orca thread plane is a fixed number, so the
start of the thread does not follow a size that changes the counterbore depth. Thus the Orca output marks these sizes
as followed in part. The ends of the thread are judged with the counterbore already cut from the part, so the start at
the floor is an open end and gets a lead-in. The Orca output still leaves out a tapped hole with a countersink (cause
`tappedRecess`): just below the mouth, the cone of the countersink is only a little wider than the bore, so the copy
cannot tell whether the start of the thread is open or closed.

##### Where a through hole comes out

Fusion gives no end face for a hole through all. For a modeled thread, Fusion puts the helical faces of the thread into
`HoleFeature.endFaces`. Thus an end face cannot tell where a hole through all comes out. If the copy measured to such a
face, the thread would stop at a point on the thread. This is a wrong copy.

The reader keeps an end face only when it is a plane whose normal is along the hole, or a cone whose axis is along the
hole (`_end_face` in `read_hole.py`). The faces of a thread have no such geometry, so the reader leaves them out. For
each side cylinder, the reader also records the span of its vertices along its axis (`span`).

`through_ends` in `design_model/steps/hole.py` uses the side cylinders, not the end faces. For each position, it finds
the measured cylinders on the axis line of that hole. The far end of these cylinders along the hole direction is where
the bore comes out of the part. Then it does these checks:

- Each position must have a cylinder with a measured span. Else the hole is left out (cause `threadHole`).
- The faces of the modeled thread (`made_span`) must be measured. Else the hole is left out (cause `threadHole`).
- For a thread over the full length, the faces of the thread must reach the deepest exit, within one pitch and 0.5
  mm. Else the hole is left out (cause `threadHole`). Thus a hole through two walls with a thread in one wall only
  gives a gap, not a thread through both walls.

The recipe output and the Orca output both use `through_ends`.

The exit is right only at the sizes of the export. When a size moves the hole, or changes the part around the hole, the
bore can come out at a different face. Example: a plate 5 mm thick has a boss 10 mm high next to the hole. A size moves
the hole under the boss. Then the bore goes through 15 mm of material, and Fusion makes a thread 15 mm long. A thread
length that follows only the plate thickness stays 5 mm. This is a wrong copy.

Thus the thread length follows the sizes only in a plain part that is equally thick wherever the holes can go
(`edges.even_sizes`, see the module text of `design_model/edges.py`). In such a part, every extrude spans the same two
planes, and each hole goes in at one plane and comes out at the other. `even_sizes` finds where each hole comes out
from the measured bore (`hole.bore_exits`). Then:

- In a plain part, the recipe output makes the exit points follow the sizes that move the face where the hole comes
  out (`hole/thread.py`, `_through_lengths`). The Orca output writes the length as a number and marks only the sizes
  of the extrude lengths and sketch planes.
- In every other part, both outputs write the length as a number. They mark every size that a step before the hole
  reads (`reach.hole_end_sizes`), also the sizes of the hole's own sketch, with a reason. The recipe output marks the
  sizes only for a thread over the full length; a thread over part of the hole has its own length.

The probe does not measure the thread at the sizes it tries. A later change can let the probe read the bore exit at
each try and keep the formula where the readings agree.

The measured bore must also be at the minor diameter of the thread (`hole_spec`). Fusion can keep the "Modeled" flag on
and still make no thread, so that the bore stays at the full size. Such a hole is left out.

A tapered tapped hole is refused ("Tapered threads are not copied.", cause `threadProfile`). A cosmetic tapped hole is
still a plain hole at the drill diameter, with a note. The drill diameter is the narrowest measured cylinder of the hole.
Fusion drills a tapped hole at the minor diameter of the thread, also for a cosmetic thread. For an M6x1 hole, the stored
size is 5 mm and the bore is 5.035 mm. Thus the stored size does not limit the drill diameter. A pattern or a mirror of a threaded hole is a gap: the `thread` kind
has no repeat rule, so the pattern refuses with "A step of this pattern cannot be repeated."

Fusion (September 2025 and later) keeps the numbers of a tapped hole in two places (`_hole_thread` in `read_hole.py`):

- `HoleFeature.tappedHoleInfo` is a `ThreadInfo`. It holds the profile name, the designation, the class, the pitch and the
  diameters.
- `HoleFeature.thread` is a thread feature that Fusion makes for the hole and does not show in the timeline. Its
  `threadInfo` holds the same numbers. It also holds `isRightHanded`, `isModeled`, `isFullLength`, `threadLength`,
  `threadOffset` and the faces of the thread.

The reader reads the numbers from these two places first. The Fusion API stub of July 2025 has none of these members,
so the reader still tries the older guesses (`threadInfo` and `threadDepth` on the hole) after them. Fusion 2706 gave
`isFullLength` false for tapped holes that were made with the default settings, also for holes through all. Then
`threadLength` is the length of the thread. Hand check TD2 compares this length with the Hole dialog. A member that
Fusion does not give reads as null, and the hole then stays a gap with a reason.

#### A hole that ends at a face or at a body

A Hole whose extent is "To" a face or a body is written as a blind hole of the measured depth, with a flat end only
(`hole.step._up_to_depth`). The depth is the distance from the entry to the end point that the reader measured
(`end_points`; the reader keeps only a flat end or a drill point along the hole). All holes of the step must end at the
same depth, and the end faces must be planes. A hole that ends in a
drill point on such a face is left out with a reason. The depth follows the face or body that the hole goes up to
(`follow.target_shift`) and the entry, as the length of an extrude up to an entity does. When the depth could be zero or
negative at some sizes, those sizes are marked.

### 3.13 How a coil is translated

A coil is a wire swept along a helix. It is the recipe step `coil` (the sketch of the section of the wire, the axis, the
pitch, the turns, the operation, and the hand when it is left). Fusion's API gives an existing coil only what every
feature has: no type, no axis, no hand, no section and no operation. So the add-in works these out from measurements,
and then proves that they are right.

#### What the reader measures

`read_coil.py` reads:

- `roles` and `params`: the model parameters that the coil made, by their role text (Diameter, SectionSize, TaperAngle,
  Revolutions, Height, Pitch). Which two of revolutions, height and pitch are there tells the type of the coil. A spiral
  has revolutions and pitch too;
- `volumes_before`: the bodies of the component and their volumes, with the marker before the coil;
- `made`: the bodies that the coil made or changed, with their volumes after it;
- `faces`, with the marker after the coil: the flat end faces (up to two, as outlines with their area), the number of
  curved faces, and 17 sampled points along each edge of the curved faces (up to 24 edges). It is null when the faces
  cannot be read or there are more than 8.

A capture of an older add-in has no `faces`. Its coil is left out with "This coil was captured without its details.
Export again with this version of the add-in to copy it."

#### From the measurements to the step

The approach: worked out from measurements, then verified. `translator/coil/step.py` does this in order:

1. A taper angle that is not 0 is refused (cause `coilTaper`).
2. The parameters must give a type: revolutions with height, revolutions with pitch, or height with pitch.
3. Revolutions that end a half turn from where they start are refused (cause `coilHalf`). The two end faces of such a
   coil lie in one plane, on the two sides of the axis, so they do not give the axis. A coil of height and pitch is
   exempt, since its turns come from the measured rise. The same cause is given when the check in step 6 fails and the
   measured turns end in a half.
4. Two flat end faces must be there. Each must be one outline without holes, and its area must agree with the area that
   Fusion gives. The outline is a circle, a rectangle or a polygon (a round, square or triangle wire). A wire of another
   shape is refused with no hint. A place that cannot be worked out gets the cause `coilPlace`.
5. The axis, the hand and the rise come from the end faces and the helical edges (`coil_fit.find_axis`). For a coil of
   whole turns the two faces lie in one plane. The axis then runs along the line between their centres, and where it sits
   across that line comes from a circle that is fitted to the points of a helical edge seen along the axis. Otherwise the
   axis is where the two end planes cross. The hand follows from which way the first end face looks.
6. The check. `coil_fit.verify` walks every sampled point back to the first turn and tests that it lies on the outline of
   the section. This rejects a tapered coil, a section that is not on a plane through the axis, and a wrong pitch, turns,
   hand or axis. A coil of revolutions and pitch that does not fit may be a spiral, since a spiral has the same two
   parameters. It is refused with the cause `coilSpiral`.
7. The operation (new body, join or cut) comes from the volumes (`coil_operation`). A body that the coil made and that was
   not there before is a new body, and its volume must be the volume of the coil (within 0.5 percent). A body that was
   there grows by at most the volume of the coil for a join. It shrinks for a cut, but a shrink also fits an intersect
   that keeps a piece of the size of the coil, so only a body that stays larger than the coil can be a cut. Anything
   else is refused (cause `coilPlace`).
8. The caps. At most 8 coils in one recipe, at most 100 turns in one coil, and 100 turns in all with the threads (3.12,
   "The turn budget"). Coils are copied in timeline order. From the cap on, that coil and every later one is a gap (cause
   `coilLimit`). The turns of a coil must not touch each other.

#### The values

`coil_values.py` tries each formula against the number that was measured. It writes a formula only when it gives that
number. This holds for the section size, for the place of the wire against the diameter (inside, on or outside it) and
for the rise. When the height does not match the measured rise, the pitch and the turns are written as numbers, and the
sizes behind them are marked (`_fixed_rise`). The taper is never followed. The ranges of the sizes are cut where the wire
stays clear of the axis, the turns stay apart and the turns stay under the cap (`keep_inside_ranges`). When no cut keeps
them, every value is a number and its sizes are marked.

A coil is not repeatable: a pattern or a mirror of a coil is a gap. The handler writes the step with `repeatable=False`,
and the `coil` kind has no repeat rule.

### 3.14 How a revolve is translated

`revolve.step.handle` (`lib/translator/revolve/step.py`) writes one recipe `revolve` step for each sketch outline of the
revolve. The recipe turns the outline about its axis by the right hand rule. Fusion does not say which way it turned.
So the handler reads the measured caps of the turned material. `design_model/steps/revolve.py` gives the facts to
both translators: the whole turn (`total_turn`), the turning direction (`sense`), the check of a symmetric turn
(`symmetric_ok`) and the side of a turn to two sides (`back_sides`).

#### The angle

The reader records the angle and the symmetric flag of the extent. For a revolve that turns to one side, the angle is
the whole turn. For a symmetric revolve, Fusion's angle is the turn to each side of the sketch
(`RevolveFeatures.setAngleExtent` in the API reference). Thus the whole turn is twice the angle.

Example. A symmetric revolve has the angle 60 degrees. The outline turns 60 degrees back and 60 degrees forward. The
whole turn is 120 degrees. The copy turns the sketch plane 60 degrees back and turns the outline by 120 degrees.

When the whole turn is 360 degrees or more, the ring closes. `total_turn` then gives a full turn. Example. A symmetric
revolve of 270 degrees closes the ring, and Fusion makes no start face and no end face.

#### The turning direction

Fusion does not record in which direction a revolve with one side turned. The reader measures three things after the
step:

- `start_face_normal`: the outward normal of the first start face (the cap in the sketch plane);
- `end_face_normal`: the outward normal of the first end face (the cap where the turn stops);
- `made_box`: the box around all the faces that the revolve made.

For new material, the start cap points against the travel and the end cap points along it. After a cut, both caps
point the other way. `sense` tries the two directions. It keeps a direction when each measured cap points where that
direction puts it.

A join can merge a cap into a face of the part. Example. A quarter round turns from the front face of a box. Its start
face lies on the front face of the box, so Fusion merges it and gives no start face. The end cap is then the only cap.
After a quarter turn, the end cap has the same normal for the two directions. In this case `sense` uses `made_box`. It
calculates the box that the outline sweeps in each direction (`turned_box`). The faces that the revolve made must fit
in the box of one direction and not in the box of the other direction. When the measurements do not give one
direction, the revolve is left out with the reason "The turning direction of this revolve could not be read."

The points that `turned_box` turns come from the outlines of the capture (`outline_points`). A line gives its two
ends. An arc or a circle gives a chain of points around the curve. The code moves these points out from the centre of
the curve, so that each straight piece between two points lies outside the curve. Thus the box that the points sweep
is never smaller than the box that the curve sweeps. A free curve gives its samples.

A join can also merge other faces of the revolve with faces of the part. Example. A lip turns a quarter turn about the
top front edge of a box. Its start cap lies on the front face of the box, so Fusion merges it with the front face.
The faces that the revolve made then include the whole front face of the box. These faces do not fit in the box that
the outline sweeps in either direction. Thus, for a join, `sense` also uses the body before and after the step
(`body_boxes`: the `target_before` and `target_after` of the timeline item). A join adds material only where the
outline sweeps. Thus, for the correct direction, these two boxes fit in the box of the body before the step together
with the box that the outline sweeps:

- the box of the faces that the revolve made (`made_box`);
- the box of the body after the step.

When the two directions fit, the material that the revolve added is inside the box of the part before the step, and
the boxes do not show the direction. The revolve is then left out. A box that is larger than the body before the
step lets more directions fit. Thus it cannot give the wrong direction: it can only cause the revolve to be left out.

Fusion does not promise that the box of a curved face or a curved body is tight. The box can be larger than the
shape. A box that is too large can stand out of the swept box of the correct direction. Then the code could rule out
the correct direction and keep the wrong direction. Thus `_box_holds` rules out a direction only when a measured box
stands out of its swept box by more than a margin: 0.5 mm plus 2 percent of the largest side of the measured box
(`BOX_LOOSE_MM`, `BOX_LOOSE_SHARE`). The code assumes that the boxes of Fusion are not larger than the shape by more
than this margin. Hand check RC1 measures this. When the part grows by less than the margin, the two directions fit,
and the revolve is left out.

A symmetric revolve looks the same in the two directions. `symmetric_ok` checks only that each measured cap sits at the
angle before or after the sketch plane. This check also shows that Fusion counts the angle on each side. When a cap is
at another place, the revolve is left out ("The turn of this symmetric revolve does not match its measured ends.").

#### The four ways to set the angle

Fusion has four ways to set the angle:

1. A full turn. The step has no angle. The start face is not necessary.
2. One angle from the sketch. When the measured caps show a right hand turn, the axis keeps its direction. Else the
   handler writes the axis in the opposite direction. The angle can follow a size.
3. A symmetric angle. Fusion's angle is the turn to each side, so the whole turn is twice the angle. The handler turns
   the sketch plane back by the angle about the axis, and writes twice the angle. The measured caps must be the angle
   before and after the sketch (`_symmetric_ok`). If they are not, the revolve is left out. The angle keeps its
   number. When twice the angle is 360 degrees or more, the step is a full turn.
4. Two sides with two angles (`angleOne` and `angleTwo`). Fusion does not say to which side each angle turns. The
   material covers one turn of angle one plus angle two. If side one turns by the right hand rule, the turn starts
   angle two before the sketch. If side one turns the other way, the turn starts angle one before the sketch. The
   start face is one of the two end faces of that turn. `design_model/steps/revolve.py` (`back_sides`) compares the
   start face with the four end faces of the two possible turns, and gives the side whose angle is before the sketch.

For two sides, these results are possible:

- No end face agrees with the start face. The revolve is left out.
- The end faces of the two possible turns agree with the start face. This occurs when one angle is 90 or 270 degrees
  and the other angle is different: the two faces lie in one plane on the two sides of the axis. The revolve is left
  out with the cause `revolveSides`.
- The two angles are equal. The two possible turns are the same at these values. But at other values of the sizes
  the copy cannot tell which side each angle turns to. So both angles keep their numbers, and their sizes are marked.
- One side agrees. The handler writes the sum of the two angles as the angle of the step. Each angle can follow a
  size. If the sum of the two angles can be more than 360 degrees in the size range, both angles keep their numbers,
  and their sizes are marked.

The handler then puts the start of the turn back by the angle before the sketch. There are two ways:

1. The angle before the sketch is a number. The handler turns the sketch plane back by that angle about the axis, as
   for a symmetric revolve (`_turned`, and `_turned_sized` when the plane or the axis moves with sizes).
2. The angle before the sketch follows a size. The revolve stays at the sketch. A `move` step turns it back about the
   axis by that angle. The `move` turns about the reversed axis, so a positive angle turns it back. The revolves and
   the `move` are in one `toolBody` step with the combine of the revolve, so the `move` turns only the revolve. The
   axis point of the `move` is a number. So when the axis is projected onto the sketch, or the axis moves with sizes,
   the angle before the sketch keeps its number and its sizes are marked. Then the first way is used.

An intersect of several outlines keeps the part only where any of the outlines turns. Thus the handler does not write
one intersect for each outline. It writes one `toolBody` step with `combine: "intersect"`. In that step, the first
outline makes a new body and the other outlines join it.

#### The side of the axis

Fusion turns a revolve toward one side of the sketch plane. Fusion keeps that side when the outline is on the other
side of the axis. Thus, when the outline passes to the other side of the axis, the turn about the axis reverses. When
the outline touches the axis or crosses it, Fusion can build the step with a warning. The recipe writes one turn about
the axis by the right hand rule, and this turn does not change. The app refuses an outline that crosses its axis.
Thus the copy is correct only while the outline stays on the side of the axis where it is now.

Example. A box is 40 x 20 mm, and its height is a size. A line on the top front edge of the box is the axis. The
outline is a 10 x 3 mm rectangle on the XZ plane, from z = 12 to z = 15. The revolve turns it 90 degrees toward the
box. At the height 10, the axis is below the outline. At the height 15, the axis is on the top edge of the outline.
At the height 20, the axis is above the outline. Fusion then turns the outline into the box, but a copy with one
turn would turn it out of the box.

`revolve/axis_side.py` (`keep_side`) does this check after the handler writes the steps. The check uses each written
`revolve` step: its outline and its axis point, as numbers or formulas. When no size moves the outline or the axis,
there is nothing to check. Else the check calculates the distance of the outline from the axis, across the axis, at
these size settings:

- the ends and the corners of the ranges of the sizes that the step reads (`range_check.corners`);
- the inner settings too, when a formula is more than sums and products (`range_check.needs_inner`).

A line gives its two ends. An arc gives its two ends, and the point nearest to the axis or farthest from it when that
point is on the arc. A circle and an ellipse give their nearest and farthest points. A free curve gives its samples.

At the current sizes, the outline is on one side of the axis. The rule is that the outline stays on that side, more
than 0.0001 mm (`SIDE_TOL_MM`) away from the axis. An outline that touches the axis now (for example a vase drawn
from its centre line) can stay on the axis, but it must not pass it. When the rule fails at a setting, the check
finds the shorter ranges where it holds (`kept_ranges.holding_ranges_where`) and cuts the ranges there
(`Context.cut`, with the reason "the outline of ... would reach its axis"). In most designs the outline and the axis
move in a straight line with the sizes. Then the halvings find the place where the outline reaches the axis, and the
range stops at the step of the form before it. In the example, the range of the height stops at 11.99.

When no shorter ranges keep the rule, the step is left out with the cause `revolveAxisSide`. This occurs when every
size that the step reads has a range that the person typed.

The Orca export (`orca_translate/revolve.py`) uses the same `back_sides` check for two sides. It turns the sketch plane
back by the angle before the sketch and turns by the sum. Both angles keep their numbers in Orca, and their sizes are
marked.

### 3.15 Extrudes: a tilted or curved end face, a start at a distance from a face, an intersect to two sides

#### An extrude up to a tilted or curved face

Fusion can extrude up to a face that is not square to the sketch normal ("To object"). Example: a post is drawn on
a plane above a domed lid, and the post goes down to the dome. The app has an extent for this:
`extent: { upTo: { near: [p] } }` (recipe version 5, and version 12 when `p` holds formulas). The app grows the
outline along the sketch normal until it meets the face that the point `p` picks. The app uses a flat face as its
whole plane. The app uses a curved face as it is, so the face must lie in front of the whole outline. If it does
not, the app refuses the step. This is not a wrong shape.

The shared reader gives such a side as `UP_TO` (see `steps/extrude.py` in 2.2). Then `translator/extrude/up_to.py`
writes the step. A point that is not on the face picks a different face. That gives a wrong copy. Thus the add-in
leaves the step out in these conditions:

1. The face is on a different body (`body` of the face record is not the body that the walk builds).
2. A step before this step is a gap. The gap can have made the face, and the copy does not have that face. The
   reason names the gaps, and the gap depends on them.
3. A size that the person can change can move the face (`design_model.reach.reach_sizes`), and no step that the
   copy wrote before places the point (`faces.follow.placed_point`, the slabs of 3.3). When a slab places the point,
   the point follows the sizes, as a point of a round or a shell does.

The app cannot build some sides. Thus the add-in also leaves the step out in these conditions:

1. The side has a taper.
2. The side has an offset past the face.
3. The face is flat, Fusion can also stop at the faces next to it, and the outline does not land on the face
   alone. See "A face that Fusion chains to the faces next to it" below.
4. The face is curved, and Fusion can also stop at the faces next to it (`chained` is true or null). The reader
   records no outline of a curved face, so the add-in cannot show that the outline lands on the face alone.
5. The face is curved, Fusion extends it (`chained` is false), and a ray from a point of the outline does not hit
   the face, or the reader could not cast the rays. See "A curved face that Fusion extends" below.
6. The face has no plane, and its surface is flat (`surface` is `Plane`) or not known (`surface` is null or not
   in the capture). Such a face can be a flat face whose plane did not read. If the add-in used it as a curved face,
   the copy could end on a different surface.

The shared reader (`_up_to` in `design_model/steps/extrude.py`) gives conditions 3 to 6 as a `Problem`. The codes are
`CHAINED`, `PAST_CURVED` and `FACE_UNREAD`.

A thin extrude up to a face never gets to `up_to.py`: `faces/thin_wall.prepare` leaves it out before. An extrude
with two sides, where one side goes up to such a face, stays a `Problem` of the reader. The step of an `UP_TO` side
has no slab. A later step that picks a face of it cannot follow sizes there, so its sizes are marked. Patterns and
mirrors do not repeat the step, because Fusion finds its length again for each copy.

The Orca output does not copy such a side: Orca names a face by its own numbering, and the Orca output does not
set `faces`.

#### A face that Fusion chains to the faces next to it

The reader reads `isChained` of `ToEntityExtentDefinition` (`chained` in the capture). When it is false, Fusion
extends the face to its whole surface. When it is true, Fusion also stops at the faces next to the face. The app
always extends a flat face to its whole plane. The two shapes are different when the outline goes past the edge of
the face. Then the extrude ends on the faces next to it in Fusion, but on the plane in the copy. This applies to a
side up to a flat face square to the sketch (`REACH`) and to a side up to a tilted flat face (`UP_TO`).

Thus the reader also reads the outline of a face that can be chained (`face_outline`, `read_face.face_loops`, with
the marker before the step). For a face of another component, the outline goes into the measured reference (`ref`)
in the coordinates of the part, and `refs.bring_in` takes it from there. `outline_on_face` in
`design_model/steps/extrude.py` then moves the loops of the face along the sketch normal onto the sketch plane of
each outline. When the face is square to the sketch normal, this move keeps all lengths, so an arc stays an arc. When
the face is tilted, the move changes the shape of an arc, so the arc becomes a chain of points.

Then `region_inside.inside` (in `geometry/`) compares the two regions. The region of the face is its outer loop less
its holes. The answer is true when the outline lies in that region. The outline can touch the edges of the face
(within 0.001 mm). The check is exact for lines, arcs and circles. It does not compare only the corners, because a
straight edge of the face can cross the outline between two corners. Example: a slot in the face, 2 mm wide, crosses
a 6 mm square post. No corner of the slot is in the post, and no corner of the post is in the slot. But the post
does not land on the face alone. The check does these steps:

1. It cuts each edge of the outline and each edge of the face at each point where the two edges meet, and at each
   corner of the other region that lies on the edge.
2. Each piece of an edge of the outline must lie in the face or on its edge. The check tests the middle point of
   each piece.
3. When a piece of an edge of the outline lies on an edge of the face, the check tests a point 0.01 mm into the
   outline. That point must lie in the face. Else the outline fills a hole of the face, or lies outside the face.
4. No piece of an edge of the face can lie inside the outline. Such a piece shows a hole of the face under the
   outline, or a face that is smaller than the outline.

A curve that does not read gives no answer (null). The inside test of a point uses chords that are not more than
0.00001 mm from the arcs, so it is correct for points more than 0.001 mm from the edges.

When `chained` is true or null (not read), and the answer is not true, the reader gives a `Problem` (`CHAINED`).
This includes a face without an outline. Both outputs then leave the step out. When `chained` is null, the add-in
does not know what Fusion does, so it uses the same rule as for true. Every export reads `chained`, so null occurs
only in captures of older versions and when Fusion does not give the value.

When the answer is true, the extrude ends on the face alone at the values of the export. At other values, a size can
move the outline past the edge of the face. The add-in does not measure the edges of the face at other values. Thus
each output marks the sizes that can move the face or the outline (`reach_sizes`): `extrude/up_to.keep_on_face` for
the recipe and `extents.reach` for Orca. These sizes stay free, with the reason "ends on a face that Fusion joins with
the faces next to it". A construction plane is never chained.

#### A curved face that Fusion extends

When `chained` is false, Fusion extends a curved face past its edges, where the outline reaches past them. The app
uses a curved face as it is. Thus the two shapes are different when the outline reaches past the edge of the face.
The reader records no outline of a curved face (`face_loops` reads flat faces only). Thus the reader casts rays
(`fusion_reader/read_face_rays.py`), with the marker before the step:

1. It takes points of each outline of the extrude (`region_inside.sample_points`): points along each curve, and
   points of a grid inside the outline. All outlines together get not more than 200 points.
2. From each point, it casts a ray along the sketch normal, toward the point on the face (`face_point`).
3. It asks Fusion which faces the ray meets (`Component.findBRepUsingRay`, with hidden bodies included).
4. The answer (`outline_hits_face`) is true when every ray meets the face. It is false when a ray does not meet it.
   It is null when Fusion gives no answer.

The reader casts the rays only for a curved face of the part with `chained` false. The shared reader gives the side
only when the answer is true. At other values, a size can move the outline past the edge of the face. Thus
`keep_on_face` marks the sizes that can move the face or the outline, with the reason "ends on a curved face". The
points are a sample: a narrow gap of the face between two points is not found. In that case Fusion and the app can
make different shapes. The app refuses the step when the face is not in front of the whole outline, so this does
not give a wrong shape that looks correct.

#### A start at a distance from a face

Fusion can start an extrude at a distance from a face or a plane (`FromEntityStartDefinition` with `offset`). The
API says that a positive distance goes along the positive normal of the face. The reader does not read which way
that normal points. Thus the reader measures the start face. `extrude_after` reads `startFaces` and takes the first
face that is parallel to the sketch. `start_offset` is the signed distance from the sketch plane to a point of that
face, along the sketch normal.

Example. The sketch is on the top face of a lid at height 4 mm. The extrude starts 2 mm from that face. Fusion
measures the start face at 2 mm from the sketch plane. The face plus 2 mm gives 2 mm, and the face minus 2 mm gives
-2 mm. Only the first fits, so the start is at 2 mm and `way` is +1. The written sketch origin then follows the
parameter of the distance: `4 + start_mm`.

A join that starts inside the material of the part has no start face: Fusion merges the start cap into the part.
Then the measured end cap can tell the sign (`_way_from_end`). The end cap of an extrude with one side and a distance
lies at the start plus or minus the length. The code tries the two signs of the start distance and the two directions
of the side (only the stored direction when the side has a set `direction`). Exactly one of the four pairs must put
the end on the measured end cap (`end_offset`). The face must be an end cap (`end_is_cap` is true).

Example. A box is 10 mm high. A post starts 2 mm below its top face and goes 5 mm. Fusion measures the end cap at
13 mm. The starts are 8 mm and 12 mm, and the ends are 3, 7, 13 and 17 mm. Only the start at 8 mm going up gives
13 mm. Thus the start is at 8 mm, and the post goes up.

The add-in leaves the step out in these conditions:

- There is no measured start face, and the end cap does not tell the sign. For example, the side goes up to a face,
  the extrude has two sides, the measured end face is not an end cap, or two pairs give the same end. Two pairs give
  the same end when the start distance is as long as the side.
- No sign puts the start on the measured face.
- The two signs put the start on the measured face. This occurs when the distance is almost zero.

The tip of this gap is "Start the extrude on the face itself, or on a plane at that distance from the face."

#### An intersect to two sides

Fusion keeps the part where it meets the two sides of an intersect. The tool is one solid: the two sides start on
the same plane, so they touch. The recipe writes the two sides as one `toolBody` step with `combine: "intersect"`
(recipe version 15). Its first step makes a new body with side one. Its second step joins side two. A tool step
that is already nested as deep as the cap (`tool_walk.MAX_DEPTH`) cannot hold one more level, so the step is left
out. An intersect with more than one outline is left out.

#### A join through all

Fusion can join an extrude "through all" (the extent "All"). Fusion then ends the extrude at the far side of the
body that the extrude joins (its participant body). The far side is the plane through the farthest point of the body
along the direction of the extrude. Hand checks in Fusion (TA1 and TA2) showed this:

- A join "All" with one body as its only participant ends at the top of that body, not at the top of a taller body
  next to it.
- On a body with a step, a square under the low part ends at the top of the tall part. It does not end where the
  square leaves the body.
- On a curved far side (a cylinder that lies on its side), a join "All" adds nothing and has no end face.
- A join "All" that joins two bodies can end at the top of the body under it, not at the top of the taller body
  beside it. The add-in does not know the rule for this case.

The app has an extent for this: an extrude with `combine: "add"` or `"new"`, `extent: "through"` and no `distance`
(recipe version 17). The app extrudes the outline from the sketch plane along the sketch normal to the far side of
the part that it built so far. The app finds the far side exactly: it measures the gap between the part and a plane
past the part. The recipe walk builds one body. Thus "the part" in the app is the copy of the target body before
the step (or, in a `toolBody`, the copy of the tool body before the step).

`extrude/through.py` (`_join_far_side`) writes this extent only when the capture shows that Fusion and the app end
the extrude at the same plane. First, the add-in checks the walk:

- The step is a join. A new body through all has no body before it to end at, so it is left out
  (`throughAllAdds`).
- The walk builds the exported body itself at this step. The reader measures the box, the end face and the flat
  faces on the exported body. In the walk of a tool body of a Combine, or before a split while the walk builds the
  body that was split, these measures are of another body. Thus the step is left out (`throughAllAdds`).
- No earlier step of the walk is a gap. The app ends the extrude at the far side of the part that it built. A step
  that is not in the copy can change where that part ends. Thus the step is left out after a gap, with the cause
  `afterGap` and the ids of the earlier gaps, as for an extrude up to a tilted or curved face.

Then the add-in checks these conditions, in this order:

1. The target body is the only participant body (`participants`, read with `ctx.is_target`). When Fusion joins more
   bodies, the add-in cannot tell where Fusion ends the extrude, and the app knows only the target body. The cause
   of this gap is `throughAllBodies`. When the capture has no participant bodies, the add-in cannot tell, and the
   cause is `throughAllAdds`.
2. The extrude has one side, no taper and no thin wall. The app does not accept a taper or a thin wall with this
   extent, and a join through all both ways has no extent in the recipe.
3. The capture has the box of the target body before the step (`target_box_before`) and a measured end face that
   is an end cap (`end_offset` and `end_is_cap`).
4. The end cap lies on the far side of the box. The add-in calculates the farthest corner of the box along the
   direction of the extrude, from the start of the extrude. The measured end must be at that distance, within
   `LENGTH_TOL`.
5. The body had material on the plane of the end before the step (`_reaches_end`). One of these shows it:
   - The reader found a flat face of the body on that plane, and its outward normal points along the extrude
     (`target_flat_faces`). The reader reads these faces only for a join or new body through all.
   - The end face that Fusion measured is larger than the end caps of all the outlines together (`end_area` against
     the outline areas, with `CAP_RELATIVE_TOL` and `CAP_ABSOLUTE_TOL`). A join merges its end cap with a face of
     the body on the same plane.

Condition 5 is necessary because a box can be larger than its body. For example, the box of a body with a curved
top can be higher than the body. If Fusion used the box and the app used the body, the two ends would not agree.
When the body has material on the plane of the end, the body reaches the plane, and the box does not go farther
than the plane (condition 4). Thus the far side of the body is on that plane, and the app ends the extrude at the
same plane as Fusion. A join onto a curved far side has no end cap in Fusion, so condition 3 leaves it out.

When a condition is not true, the step is left out with a reason. A new body through all has no target body before
the step, so it is always left out.

The app finds the far side again each time that it builds the part, so the end follows the sizes. But the add-in can
check the far side only at the sizes of the export. At other sizes, a different part of the body can become the
farthest part, for example a curved face. The add-in cannot check that Fusion and the app find the same far side
there. Thus the add-in marks these sizes ("may give unexpected results", with the step named): the sizes that the
steps written before it read (`ctx.written_reads`), and the sizes that move its outlines
(`sketch_motion.outline_movers`). This mark is broad. It also marks sizes that cannot move the far side, for example
the size of a small hole. The probe does not record the box of the body at each try (the motion file has only
`box_max`, the union of all tries), so the add-in cannot tell which sizes move the body along the extrude. A taper of zero that follows a size is pinned, as for a cut through all both ways.

The written step has no slab, so later picks on its faces do not follow it. Its length follows the part, so it is not
repeatable: a pattern or a mirror of the step is left out. The Orca output still leaves a join through all out
(`throughAllAdds`).

#### A thin extrude of an open line

Fusion can make a thin extrude of an open line. This is a wall along a chain of sketch lines that does not close.
People use it for fences, dividers, ribs and brackets. The recipe has a wall for this (recipe version 17). It is an
extrude whose outline is an `open` loop, with `thin.ends: "square"` and `thin.corners: "sharp"`. The app then cuts
each end of the wall square to the line. At a corner, the app extends the two sides of the wall until they meet.
Fusion builds the wall in the same way.

What the reader reads:

- For an open line, `ExtrudeFeature.profile` is a `Path`, not a `Profile`. The reader keeps one record
  `{ "kind": "other", "type": "Path" }` in `profiles`.
- The reader reads the path into `path` with `read_sweep.path_record`, as for a sweep. Each curve of the path has
  its points in the sketch plane (`flat`) and `opposed`. `opposed` is true when the path goes against the direction
  of the sketch line.
- Fusion lists no start faces and no end faces for this extrude. Thus `extrude_after` reads all the faces that the
  extrude made (`ExtrudeFeature.faces`) into `wall_faces`. For each face, it reads the type of surface, a point on
  the face and the normal at that point.
- For a join or a cut, `extrude_before` also reads the faces of the target body before the step
  (`target_faces_before`), in the same form, and which body that is (`target_faces_body`). A face of the wall that
  Fusion merges with a face of the part lies on the plane of one of these faces.

The table entry of `ExtrudeFeature` has `PATH`. Thus the size probe follows the curves of the line, as it does for
a sweep path.

The translator writes the step in `translator/extrude/thin_line.py`. `extrude/step.py` sends an extrude to it when
the extrude is thin and its outline is a `Path`. Then:

1. `line_of` reads the line. The path must be one open chain of sketch lines of one sketch. Each line must start
   where the line before it ends. No line can be `opposed`. The add-in leaves out a line with an arc or a free
   curve, a line that runs against the path, a chain with a gap, a closed chain and a path of body edges.
2. `outline` writes the `open` loop from the first point of the line to the last point. Thus the loop keeps the
   direction of the line. When the probe followed the path, each point follows its sizes (the keys of
   `sketch_values.keys.path`). When the probe did not follow the path, the loop keeps its numbers, and the sizes of
   its sketch are marked.
3. `wall_step` checks the line alone (`line_problem` with no wall). Then `decide` finds the side of the wall. Then
   `line_problem` checks the wall on that side.

The side of the wall. The app puts an `inside` wall on the left of the line. You look along the line from its start,
and you look from the front of the sketch (along its normal). An `outside` wall is on the right. A `middle` wall has
half of the thickness on each side. Fusion names the side "side one", "side two" or "center". Tests in Fusion showed
that side one is on the left of the path, and side two is on the right (`RULE`). This is true when the extrude goes
along the sketch normal, against it, or to the two sides. When the line goes the other way, the wall goes to the
other side.

The add-in does not use the rule alone. It compares the wall with the faces that Fusion made (`fits`). For each side
that the location in Fusion permits, and for each direction, it makes the outline of the wall (`band`). Then each
measured face must agree with that wall:

- The face must be flat.
- The point of the face must be between the two ends of the wall.
- A face across the sketch normal must be at one end of the wall, and its point must be on the outline of the wall
  or in it.
- A face along the sketch normal must be on a side of the outline, and its normal must be square to that side.
- At least one face must agree in this way.

A face that does not agree in this way can be a face that Fusion merged (`merged`). The add-in accepts it only when
these two conditions are true:

- The face is on the plane of a face of the target body before the step (`target_faces_before`), and the two faces
  point to the same side.
- The face is on the plane of a face of the wall, and the two faces point to the same side.

Exactly one side and one direction must agree. The direction must be the direction that the extrude reader found.
The side must also be the side that `RULE` gives. If one of these conditions is false, the add-in leaves the step
out.

Example. The line goes from (0, 0) to (30, 0) to (30, 20). The wall is 2 mm thick on side one and 15 mm high. The
left wall has the outline (0, 2), (28, 2), (28, 20), (30, 20), (30, 0), (0, 0). The right wall has the outline
(0, 0), (30, 0), (30, 20), (32, 20), (32, -2), (0, -2). Fusion made a face at y = 2, and its normal is along y. Only
the left wall has a side there. Thus the side is `inside`.

A join can merge a face of the wall with a face of the part. Example: the plate is 60 x 40 x 3 mm, and the line
starts at the corner of the plate, on its top face. The wall is flush with the front edge and the left edge of the
plate. Fusion merges the start end of the wall with the left face of the plate. It lists one face at (0, 20, 1.5)
with its normal toward -x. That point is on the plate, not on the wall. The plate had a face on the plane x = 0 with
its normal toward -x, and the start end of the wall is on that plane with its normal toward -x. Thus the face is a
merged face, and the side is found from the other faces. When the add-in has no faces of the part (an older
capture, a new body), or no face of the part explains the face, the add-in leaves the step out.

The faces of the part must be the faces of the body that the walk builds (`ctx.is_target` of `target_faces_body`).
The reader reads the faces of the exported body. In the walk of a tool body of a Combine, the walk builds the tool,
not the exported body. A face of the exported body does not prove that a face of the tool merged. Thus in that walk
the add-in accepts no merged face, and a wall flush with the edge of the tool is left out.

Each refusal of the open line has the cause `thinOutline`, so the gap shows its tip.

An extrude that goes against the sketch normal is written on the reversed sketch plane, and its loop is mirrored
(`flip_y`). Then the left of the line becomes the right. Thus `LineWall.written` changes `inside` to `outside`, and
`outside` to `inside`.

The shape of the wall at other sizes. The app and Fusion build the same wall only while the wall keeps its shape.
`line_problem` gives a problem in these conditions:

- A line is 0.001 mm long or shorter.
- A corner turns more than 135 degrees (`MAX_TURN_DEG`). Fusion was seen to keep corners of 90 and 135 degrees
  sharp, as the app does: the two outer sides of the wall run on until they meet in one tip. A sharper corner is
  not proven yet. Example (hand check 40): the line goes from (0, 0) to (30, 0), then 20 mm at 135 degrees to
  (15.858, 14.142). A 2 mm wall on side two has its tip at (34.828, -2), and the wall is 1644.853 mm3 at 15 mm.
- At a corner, the side of the wall on the inner side of the turn cuts each of the two lines short. The cut is the
  reach of the wall on that side times tan(turn / 2). A line must be longer than what its two corners take.
- Two lines that do not touch come nearer than two times the farthest reach of the wall. The wall reaches the
  thickness of its side from its line. At a corner, the outer side of the wall meets in a sharp tip. The tip is at
  the reach of the outer side divided by cos(turn / 2) from the corner. Example: a wall of 2 mm on the outer side of
  a 90 degree corner has its tip 2.83 mm from the corner, so two lines must be more than 5.66 mm apart.

`keep_line_valid` tests these conditions at the ends and at the middles of the size ranges. For a formula that is
not only sums and products, it also tests inner settings. It cuts the ranges where the wall stops keeping its shape.
If no cut helps, it marks the sizes.

Example. The second line is 3 mm long, and the wall is 2 mm on the inner side of the corner. The corner turns 90
degrees, so it takes 2 mm of the line (2 times tan 45 degrees). The range of the wall thickness stops before 3 mm.

The material of the wall. A later step can ask if a point is in the wall (`material_at`). The add-in gives the wall
as the closed outline that it fills (`band_profile`), in a `ThinWall` with the side `inside`. The faces of the wall
are not placed.

### 3.16 How a round by chord length or with a changing radius is translated

Fusion has two more kinds of fillet sets that the copy can write as a `round` step:

- A chord length set (`ChordLengthFilletEdgeSet`). The person gives the chord length: the distance between the two
  lines where the round touches its faces.
- A changing radius set (`VariableRadiusFilletEdgeSet`). The person gives a radius at the start of the edge and a
  radius at its end, and can give more radii between the ends.

The API does not give the radius of a chord length round. The API also does not say how a changing radius changes
between the ends. Thus the copy measures what Fusion made.

#### What the reader measures

The reader (`fusion_reader/read_finish.py`) reads each edge of these sets at five places along the edge: at 0, 0.25,
0.5, 0.75 and 1 of its parameter range (`SAMPLE_FRACTIONS`). A closed edge has no sample at 1, because it starts
there again. Each sample has:

- the point and the direction of the edge there (`point`, `tangent`);
- for a chord length set, the outward normals of the two faces of the edge at the point (`sides`);
- after the step, the radius of the round at the point (`radius`).

The radius is measured on the faces that the step made (`FilletFeature.faces`). The reader finds the round face that
is nearest to the point. Then it reads the two main curvatures of the face there (`SurfaceEvaluator.getCurvature`).
The curvature across the edge gives the radius. The reader uses the curvature whose direction is more across the
edge than along it. The other curvature comes from the bend of the edge itself. A sample that the reader cannot
measure has a null radius.

The reader also reads the kind of curve of the edge (`curve`). For a chord length set, it records the two faces of
the edge (`side_faces`): a point on each face, the surface kind and the outward normal. For a cylinder or a cone, it
also records the direction of the axis (`axis`, null when the reader cannot read it).

#### A chord length set

The radius of a round between two faces is r = c / (2 sin(a / 2)). Here c is the chord length and a is the angle
between the outward normals of the two faces. For faces at a square corner, a is 90 degrees and r is c divided by
the square root of 2.

The handler (`finishes/measured_rounds.py`, `chord_sizes`) does these steps for each edge:

1. It reads the angle a at each sample (`face_angle`). The angle must be the same along the edge, within 0.05
   degrees. If the angle changes, the radius changes along the edge too. The recipe has no such round, so the step
   becomes a gap (cause `roundKind`).
2. It calculates the radius from the chord length and the angle (`chord_radius`).
3. It compares this radius with the radius that the reader measured on the round (`matches_radius`). It uses only
   the samples between the ends, because at an end the round can meet another round of the same step. When the
   radii are not the same, the step becomes a gap. This check makes sure that the formula above is the rule that
   Fusion uses.

Edges with different angles get different radii. The step then writes `edgeSizes`.

The formula is exact only when each face is straight across the edge. Look at a cut through the part that is
square to the edge. In this cut, each face must be a straight line. Then the round is a circle that touches two
lines, and only the angle between the lines sets the factor between the chord length and the radius. These faces are
straight across the edge (`finish.straight_across`):

- a flat face;
- a cylinder or a cone whose axis is square to the edge at each sample. The edge then goes round the axis, for
  example the top edge of a round boss. The cut square to the edge holds the axis, and it cuts the face along a
  straight line.

Other faces curve across the edge: a sphere, a torus, or a cylinder whose axis is along the edge. On such a face, the
factor also changes with the radius of the face. When the reader did not read the surface kind or the axis, the
handler also counts the face as curved.

The radius follows the size of the chord length only when both faces are straight across the edge and no size can
turn the faces. The handler asks `design_model/edges.py` (`angle_sizes`) for the sizes that can change the angle
between the faces of each edge:

- When both faces are straight across the edge and there are no such sizes, the radius is the chord length times a
  constant number (1 / (2 sin(a / 2))). The formula is exact at all sizes.
- When a face curves across the edge, or when there are such sizes, the radius is written as a number. The chord
  length is pinned (`values.pin`): its sizes are not sizes of the copy, and the reason says that the copy writes the
  radius. Each size that can turn the faces is marked "may give unexpected results". For a face that is not flat,
  `angle_sizes` gives every size that the steps before the round read, so the sizes that can bend the face are also
  marked. The first translation of an export marks nothing.

The handler writes one point for each edge. It does not use the picks that Fusion was given (the faces of the set, or
a tangent chain). At other sizes, such a pick can include an edge that has a different angle, and thus a different
radius. The copy cannot give that edge its own radius.

But a pick of Fusion can also hold more or fewer edges at other sizes. The copy with one point for each edge does not
see these edges. Thus, when a set was picked from faces or from a tangent chain (`input_kinds` has `face`, or
`tangent_chain` is true), the handler marks the sizes that can change which edges the pick holds
(`finish._mark_own_picks`). These are all the sizes that the steps before the round read (`reach.any_face_sizes`).
Each one is marked "may give unexpected results". The same rule applies to a round with a changing radius, and to
every round and chamfer whose pick the recipe cannot say (section "The picks that Fusion was given: faces and
tangent chains").

#### A changing radius set

The recipe has `sizeEnd` (recipe version 5): the radius changes evenly along the edge, from `size` at the end of the
edge that is lowest along x (then y, then z) to `sizeEnd` at the other end. The app reads the ends in the axes of the
recipe, after the move into the assembly (`place.place`).

The handler (`changing`) writes such a round only when all these conditions are true:

- The set is the only set of the step. Sets of one step are made together in Fusion. Steps one after the other can
  make different corners.
- The set has one edge, and that edge is a straight line or an arc (`EVEN_CURVES`). Along these curves, the fraction
  of the parameter range is the fraction of the length.
- The set has no radii between the ends (`mid_count` is 0). The recipe has no round with more than two radii.
- The step is not in a tool body (`ctx.outer` is None). A tool body is moved into place, and the move can change
  which end is lowest.
- The radii that the reader measured at the five samples change evenly from one end to the other (`law`). Fusion can
  blend the radius in a smooth curve. Then the step becomes a gap (cause `roundKind`).

The measured radii also tell which end of the edge has the start radius. The handler does not use the direction of
the edge in Fusion, because the API does not say how Fusion relates it to the start radius.

Then the handler finds the end that the app starts from (`end_order`):

1. It takes the points of the two ends. When earlier steps move these points with the sizes, the points are formulas
   (`follow.follow_points`).
2. It turns the gap between the two ends into the axes of the recipe (`rigid.move_for`).
3. Along x, then y, then z: a gap of at most 0.000001 mm is level, as in the app, and the next axis decides. A gap of
   less than 0.001 mm on the axis that decides is too small to tell. Then the step becomes a gap.
4. When a gap is a formula, the range check (`range_check.sweep`) tells if the gap keeps its sign over the size
   ranges, and if a level gap stays level. If not, its sizes are marked "may give unexpected results", because the
   app could then start from the other end.

When the two radii are equal now, the samples cannot tell the ends apart (`LEVEL`). When the two radii are the same
value (the same formula), the step is a plain round. Otherwise the radius is written as a number, and the two radii
are pinned.

A pattern or a mirror cannot repeat a round with `sizeEnd` (`repeat/repeat_sources.py`, `UNCOPYABLE_FINISH_KEYS`): a
turned or mirrored copy can swap the ends. The Orca output leaves both kinds of sets out.

### 3.17 How a path pattern is translated

A path pattern (`PathPatternFeature`) puts copies along a path. The recipe has no pattern along a path. But two kinds
of path give a pattern that the recipe has:

- A straight line. Each copy moves along the line by the distance. A copy does not turn on a line. Thus the pattern is
  a rectangular pattern with one direction: the direction of the line.
- An arc or a circle. Each copy turns with the path, about the centre of the arc. Thus the pattern is a circular
  pattern about the axis of the arc. The axis goes through the centre of the arc and is normal to its plane. The
  distance along the arc gives the angle: angle in degrees = distance x 180 / (pi x radius).

The reader (`fusion_reader/read_repeat.py`, `path_before`) reads the path as the sweep reader reads a path
(`read_sweep.path_record`). It also reads the count (`quantity`), the distance, the distance type (`extent` or
`spacing`), the start point (from 0 to 1 along the path), the flip, the symmetric flag and the orientation
(`along_path`). A setting that cannot be read is null. For a path of one body edge, `path_place` says what the edge is.
With the marker after the step, the reader reads the copies (`elements`), as for the other patterns.

The shared reader `design_model/steps/path_pattern.py` (`layout`) gives the plain pattern, or a problem:

1. The path must be one line, one arc or one circle. Another curve, or more than one curve, is a problem (cause
   `pathPattern`).
2. Copies on both sides of the start point (`symmetric`) are a problem.
3. On an arc or a circle, the copies must turn with the path (`along_path` is true). Copies that keep their direction
   only slide along the arc. No plain pattern does that, so it is a problem. On a line, the setting changes nothing.
4. A setting that cannot be read is a problem.

`layout` also gives `room`: how far the copies can go from the start point to each end of the path. On a closed path
(a circle), the room is the length of the path. The start point is a fraction of the path, counted from the start of
the path. A curve can run against the path (`opposed`). Then the path starts at the end of the curve. For a line,
`layout` turns the direction. For an arc, `layout` turns the sense of the turn. In both cases, the room toward the end
of the path is the length x (1 - start point), and the room toward the start is the length x the start point. It is not known what Fusion does with copies past an end of the path.
Thus the translator keeps the copies on the path.

The handler is `translator/repeat/repeat_path.py`, `path`. It does these steps:

1. It refuses the problems of `layout` with their words.
2. It checks the way the copies run. Fusion counts the distance toward the end of the path, or toward its start when
   the flip is set. On a line, a measured copy that runs the other way leaves the step out. On an arc or a circle,
   a start point other than 0, or the flip, leaves the step out (`PATH_PATTERN_OFF_ROUND`). Hand check PP1 found
   that Fusion 2706 can then put the copies off the arc, and that their element transforms do not agree with their
   faces. On an arc that starts at 0 without the flip, the handler tries the measured turns both ways
   (`_measured_turn`).
3. It finds how far the last copy goes along the path (the travel). For an `extent` distance, the travel is the
   distance. For a `spacing` distance, it is the distance x (count - 1). A travel that is longer than the room leaves
   the step out. When the count or the distance follows sizes, the travel can grow. Then the handler cuts the ranges
   of those sizes to where the copies stay on the path (`_keep_on_path`). When no cut can do that, it marks the sizes.
4. It marks the sizes that may change what the copy takes from the path (`_mark_path`). The path is written as
   numbers. For an edge of the part, these are the sizes of the steps before it (`reach.reference_sizes`). For a
   sketch path, the handler starts from the general set: the sizes of the sketch, the sizes that move the plane of
   the sketch, and the sizes before a sketch with projected geometry (`reach.sketch_line_sizes`). Then it removes
   sizes when it can show that they change nothing that the copy uses (`_sketch_path_sizes`):
   - A line gives only its direction and its length. The place of the line does not move the copies. The sketch
     solver gives the gap between the two ends of the line as formulas of the dimensions of the sketch
     (`edges.line_sizes`). When the formulas read no projected or linked geometry, only the sizes behind these
     dimensions and the sizes that move the plane of the sketch can turn or stretch the line. When the solver cannot
     give the gap, the general set stays.
   - When the size probe measured the path (its key `<item>/path` is in the motion file), a size that the probe
     tried and that moved no value the copy uses is removed. For a line, these values are the gaps between the ends.
     For an arc or a circle, they are every point of the curve, its radius and the place of its plane. A value that
     the probe could not follow (the plane turned, the sketch was not read) keeps its sizes. A size that the probe
     did not try stays.
5. It writes the data of the plain pattern and gives it to the rectangular or the circular handler. The item keeps its
   index and name.

For a line, the data has `direction_one` (the line), `quantity_one`, `distance_one` and the distance type. The
parameters of the count and the distance go under the new names. An edge of the path goes in as
`direction_one_place`. Thus the rectangular handler marks the sizes that may turn the edge, as it does for a direction
of its own (`ref_motion.check_own_direction`). A sketch line goes in as a `direction_one_place` that is marked
`fixed`, because step 4 already marked the sizes that may turn or stretch the line. The rectangular handler then marks
nothing more for the direction.

For an arc or a circle, the data has the axis (marked `fixed`, because the handler marked the sizes of the path), the
count and the total angle. The radius is read rounded. Thus the handler takes the turn between copies from the
measured copies. The measured turn must agree with the turn from the distance and the radius to 1 part in 10 000
(`TURN_SHARE`). Else the step is left out. The circular handler takes a function for the total angle
(`total_angle`). The function writes the angle as a formula of the distance (and of the count for a `spacing`
distance). Thus the angle follows the sizes. A path pattern that goes round a whole circle is written as a full turn.
Its distance then stays a number, and its sizes are marked.

The rectangular and the circular handler check the measured copies against the pattern that they write, and they
check the place of each copy against its faces (3.21). Thus a copy that Fusion put in another place leaves the step
out. A refusal that has no cause of its own gets the cause `pathPattern`, unless it comes from an earlier gap.

The step kind table gives the path pattern `sketches=(PATH,)`. Thus the size probe follows the path sketch as it
follows a sweep path. The probe does not read the copies again (no `pattern` value): a pattern with copies on both
sides is not copied. A path pattern of bodies or faces is refused by the pattern handler, as for the other patterns.
The Orca output has no handler for a path pattern, so it leaves the step out.

Example, made up: a sketch line of 30 mm, a hole at its start, a count of 3 and a spacing of 15 mm. The recipe gets a
`pattern` step with `linear: {dir: [1, 0, 0], count: 3, step: 15}`. The travel is 2 x 15 = 30 mm, which is the room.
Thus the ranges of the count and the spacing stop at their values now.

### 3.18 How a scale is translated

`scale.handle` (`lib/translator/bodies/scale.py`) writes a recipe `scale` step. The step has a factor and a point.
The app scales all the steps before the `scale` step in the same list about the point. The list is the main list of
the part, or the `features` list of a tool body.

The reader (`lib/fusion_reader/read_scale.py`) reads these items with the marker before the Scale:

- The input entities. The copy can use only bodies. When a sketch is an input too, `input_kind` is `sketches`.
- The point that stays in place. This point is the origin point of the component, a sketch point, a construction
  point, or a corner of a body.
- The factor. A uniform Scale has one factor. A non-uniform Scale has one factor for each axis.
- The box and the volume of each body.

The reader reads the box and the volume of each body again with the marker after the Scale.

The handler does these checks in this sequence. When a check fails, the Scale becomes a gap with the cause `scale`:

1. All the inputs must be bodies. A Scale that also scales a sketch is left out. A later step can use the scaled
   sketch, and the copy cannot change that sketch.
2. The point and the factors must be readable. A point of another component is left out.
3. Each factor must be from 0.001 to 1000. This is the range that the app accepts.
4. The copy must have a step before the Scale in the same list. The app does not accept a `scale` step as the first
   step of a list.
5. For a non-uniform Scale, the map that moves the recipe into the assembly must turn each axis onto an axis
   (`place.axis_turn`). This map comes from the place of the component and from the Y up turn. When the component
   is turned by an angle that is not a quarter turn, the factors have no axes in the assembly, so the Scale is left
   out. A Scale in a tool body of another component has one more map. The Combine moves the steps of the tool with
   the place of the tool component, then with the inverse of the place of the exported body. Both places are read at
   the Combine. The Combine checks this map against the steps of the tool before it moves them (`place.factors_fit`).
   When a step of the tool has factors per axis that are not equal, and the map turns an axis off the axes, the
   Combine is left out with the cause `scale`. The export does not stop.
6. The measured body must agree with the Scale. The volume after the Scale must be the volume before it, multiplied
   by the three factors. Each side of the box must move as the factors and the point move it. This check finds a
   point or an axis that the reader did not read correctly. If the body was not measured, the Scale is left out.

Then the handler writes the step:

- The factors follow their parameters (`values.quantity`, without a unit). A factor must stay above zero, at or above
  0.001 and at or below 1000 in the size ranges. When the formula of a factor can go out of that range, the copy
  writes the factor as a number. The sizes in that formula are marked.
- The point is written where Fusion measured it. When the point is the origin, no size can move it. For a sketch
  point, a construction point or a corner, `reach.reference_sizes` gives the sizes that can move the point. The copy
  marks these sizes "may give unexpected results".

After the `scale` step, the placers of the steps before it become `ScaledPlacer` (`faces/scaled_placer.py`). A
`ScaledPlacer` knows where the material is: it moves a point back through the Scale before it asks the old placer.
But it does not place picks. Thus a round, a chamfer or an offset after the Scale that picks a face made before the
Scale keeps its measured points, and the sizes are marked.

The recipe is carried into the assembly by `place.place`. The point moves like every other position. A factor list
`[x, y, z]` is put on the new axes: for a Y up design, `[1, 2, 0.5]` becomes `[1, 0.5, 2]`.

The Orca copy leaves every Scale out (`orca_translate/bodies.py`), because Orca's Design tab has no step that scales
a body. The cause is `scale`, and the Orca result shows its tip.

Example: a block of 40 by 20 by 10 mm is scaled by the user parameter `Grow` = 1.5 about the origin. The volume goes
from 8000 mm3 to 27000 mm3, which is 8000 multiplied by 1.5 three times. The box goes from (40, 20, 10) to
(60, 30, 15). The copy writes `{ "kind": "scale", "factor": { "expr": "Grow" }, "point": [0, 0, 0] }`. The recipe has
version 17.

### 3.19 How a shell is translated

`finish.shell` (`lib/translator/finishes/finish.py`) writes a recipe `shell` step. A shell hollows the part and leaves a
wall of one thickness. The copy reads four things from Fusion.

1. The direction. Fusion has an inside thickness and an outside thickness (`ShellFeature.insideThickness`,
   `outsideThickness`). Only one of them is more than 0 in the copy. The inside thickness gives a wall that grows
   inward: the outer shape of the part stays. The outside thickness gives a wall that grows outward: the faces of the
   part stay as the walls of the hollow, and the wall is added outside them, so the part gets bigger by the thickness.
   The step then has `outside: true`. When both thicknesses are more than 0, the wall grows both ways. The recipe
   cannot say that, so the step is left out with the cause `shellKind`. Fusion gives no parameter for the side that
   has no wall. It gives an empty value (None), and it does not give an error. An inward shell has no outside
   thickness, and an outward shell has no inside thickness. The reader reads an empty value as 0 (no wall on that
   side). The reader reads a side as unknown only when Fusion gives an error for it or does not have the member. When
   one of the two thicknesses is unknown, the step is left out. The reader does not guess 0 for an unknown side,
   because that would write an inward wall for an outward one (`_shell_side` in `fusion_reader/read_finish.py`).
2. The corners. `shellType` is sharp or rounded. A rounded shell writes `corners: "round"`. A sharp shell writes no
   `corners` field. A type that cannot be read, or that is neither of the two, is left out with the cause `shellKind`.
3. The open faces. A shell that picks faces opens them: the step has `openFaces`, picked as before (`follow.faces`). A
   shell that picks the body opens nothing, and it is a closed hollow: the step has no `openFaces`. A shell that picks
   a body and faces together is left out.
4. The volume of the part before and after the step (`volume_before`, `volume_after`, read with `target_volume`). An
   inward shell must make the part smaller, and an outward shell must change the volume. A step that does not is left
   out, because the copy then does not do what Fusion did. A shell that grows outward or has rounded corners is also
   left out when the volume was not measured. A shell that goes inward with sharp corners is copied without the
   measure, as before, but it is checked when the measure is there. The volume does not tell the corners apart.
   So the corners come from `shellType` only.

Example, made up: a box of 40 by 20 by 10 mm. `Shell1` picks the body, with an outside thickness of 1.5 mm and sharp
corners. Fusion measures 8000 mm3 before the step and 5200 mm3 after it. The recipe gets
`{ "kind": "shell", "thickness": 1.5, "outside": true }` and no `openFaces`. The recipe is version 17.

The version is the lowest one that holds the step (`_shell_version` in `translator/translate.py`). A shell with
`outside`, with `corners` or without `openFaces` needs version 17. A shell with open faces, a thickness and sharp
corners keeps the lowest version. The app reads the three fields only from version 17, and it refuses a file that
states an older version.

The thickness follows its parameter. An inward wall reads `inside`, and an outward wall reads `outside`, both as a
length that stays above 0 (`values.quantity`).

How later steps find faces after a shell. Each step that makes faces is kept as a placer (3.3).

- A shell that goes inward is the placer `Shell`. A point on an inner wall is moved back out by the thickness, placed on
  the step that made the outer face, and follows that step and the thickness. A closed hollow is the same placer with no
  open face.
- A shell that goes outward is the placer `OutsideShell`. The faces of the part before it stay where they are, and a
  pick on one of them is placed as before. The new outer faces are not placed. A point that lies outside the part as it
  was, and inside the box of the wall, is "claimed" by the placer (`Placer.claims`). Then `follow.locate` stops and
  gives no place. Without it, an earlier step could place such a point by chance: for example, a cut that reaches 2 mm
  past the top of the part has an end face where the new outer wall is. A pick with no place is written as measured
  points, and every size that an earlier step reads is marked, as for any pick the copy cannot follow. A tool placer
  and a moved placer pass the claim of the placer inside them.
- The box of the wall (`OutsideShell.wall_box`) limits the claim to points near the new wall. This is important for a
  shell inside a tool body. The part as it was before the tool does not belong to the tool, so every point on a face
  of the part lies outside the material of the tool. Without the box, the shell in the tool claims these points too,
  and a later pick on a face of the part gets no place. `added_bounds.outside_wall_box` makes the box when the shell
  is written. It starts from the box of all the material that the walk has written before the shell: the material
  of the placers (`material_boxes.material_boxes`) and the bounds of the steps that have no placer for their
  material, for example a sweep (`added_bounds.bounds`). It grows this box by the largest round or bevel and then by
  the wall:
  - A rounded wall lies no further than the thickness from the part. The box grows by the thickness.
  - A sharp wall reaches further at a sharp corner (the mitre). A corner that turns by an angle a moves out by the
    thickness divided by cos(a / 2). The copy can find all the corners only when the part is a stack of straight
    extrudes along one axis, without a taper, cut, round, bevel or other step (also in tools, patterns and mirrors).
    Then the box grows by the thickness multiplied by sqrt(f * f + 1), where f is the largest mitre factor of the
    outline corners. A corner that turns by more than 150 degrees has no box.
  When one part of this cannot be told, the shell has no box. It then claims every point outside the part as it was,
  as before. This gives more picks without a place, but it never places a pick on a wrong face.
- `OutsideShell` knows the hollow (the part before it, as material that is removed) and does not know the wall. It is
  `opaque`: a later step on the sketch of another part says it cannot check that it still meets the wall.
- The check for a join that would float (`faces/floating.py`) treats an outward shell as a step that may add material.
  The material lies in the box of the wall (`added_bounds.outside_shell_bound`), so a join on the outer wall stays.
  A shell without a box is a step that the check cannot bound: every later join stays. An inward shell only removes
  material.

An outward shell, a closed hollow and a rounded shell cannot be checked in Fusion's tests. They have hand checks in
`docs/hand-checks.md` (SH1, SH2 and SH3). The Orca output leaves every shell out (`orca_translate/finishes.py`).

### 3.20 How an offset of faces (press pull) is translated

`offset.handle` (`lib/translator/finishes/offset.py`) writes one recipe `offsetFaces` step for one Press Pull (Offset
Faces) item. The step has one `near` point for each face that the item moves, and the distance. Fusion and the app
use the same sign: a positive distance moves the face along its outward normal, out of the material.

A flat face gets a point inside its outline, away from its edges and holes (`inside_point`). The face is copied only
when Fusion left a flat face on the plane of the face, moved by the distance (`faces_after`). The app lets the faces
around a moved face extend or shrink, so a leaning side wall and two moved faces that meet need no special case.

A round face is a cylinder. It is a pin or a boss when its outward normal points away from the axis. It is a bore when
the normal points towards the axis. The move changes the radius:

- For a pin or a boss, the new radius is the radius plus the distance.
- For a bore, the new radius is the radius minus the distance.

So a Press Pull of -0.2 mm on the wall of a bore of radius 2.5 mm gives a bore of radius 2.7 mm. This is the usual way
to tune a hole for a fit.

The app (recipe version 17) moves a round face only when these conditions are true. `offset_round.py` checks each
condition before the step is written:

1. The face goes all the way round. The reader gives one entry for each edge loop of the face (`ends`). A whole
   cylinder has two loops, and each loop has one circle edge. Part of a circle, or a face with a seam edge, has other
   loops. Then the step is left out.
2. Both ends are flat faces square to the axis. The face across each end circle must be a plane. Its normal must be
   parallel to the axis. A round or a chamfer at an end is not a plane, and an end on a slope is not square. Then the
   step is left out.
3. The ring does not run into other faces. The reader gives the outline of each end face. The circle of the round
   face is one curve of that outline. Each other curve of the outline must stay clear of the ring between the old
   radius and the new radius (`_limits`, with a margin of 0.01 mm). A curve inside the circle sets the lowest radius,
   and a curve outside the circle sets the highest radius. A curve that touches or crosses the circle leaves the step
   out.
4. The face does not touch another face that the same item moves (`meets_offset`).
5. The new radius stays above zero.
6. Fusion left a cylinder on the same axis with the new radius (`rounds_after`). This checks the sign rule on the real
   part. If no such cylinder is found, the step is left out.

When one of these conditions is false, the whole step is left out with the cause `offsetCurved`, also when the step
moves flat faces too.

The pick point of a round face is on the face, halfway between its two ends. It is on the side of the point that
Fusion gave for the face (`pointOnFace`).

The distance can follow a size. Then the translator checks the size range:

- The distance must not reach zero.
- For each round face, the new radius must stay between the lowest and the highest radius of step 3 over the whole
  range (`clear_over_range`).

If one of these checks fails, the distance is written as a number. The size then gets the reason "the round face
that ... moves could close or run into other faces".

The step adds a `MovedFaces` placer (`lib/translator/faces/offset_faces.py`). This placer knows the material that the
move added or removed, and the faces after the move:

- A later pick on a moved flat face moves back along the normal of the face by the distance.
- A later pick on a moved round face moves back along the radius by the distance. Then it follows the step that made
  the face, and the distance.
- The ring between the old and the new radius counts as added material when the distance is positive. It counts as
  removed material when the distance is negative. `follow.inside` and the check for joins that float use this.

Example, made up: a plate 40 x 20 x 10 mm has a hole of radius 2.5 mm through it. A Press Pull on the hole wall has
the distance `-Fit`, with `Fit` = 0.2 mm. Fusion leaves a cylinder of radius 2.7 mm. The recipe gets
`{ "kind": "offsetFaces", "faces": { "near": [[12, 7.5, 5]] }, "distance": { "expr": "-Fit" } }` and version 17. The
default range of `Fit` is 0.1 to 0.4 mm. The new radius stays between 2.6 and 2.9 mm, far from the plate edges, so the
distance follows `Fit`.

### 3.21 Where the copies of a pattern sit

Each pattern element has a transform (`PatternElement.transform`). The transform is the move from the original to
the copy. The reader writes it as the `frame` of the element. But Fusion does not always give the right transform.
Hand check CP1 measured this in Fusion 2706 on circular patterns:

- The element ids follow the real order of the copies. Copy `id` sits `id` steps from the original. The step is
  360 / count for a full circle, and the total angle / (count - 1) for a part turn.
- The transform of each copy after the original is one step ahead. The last copy of a full circle reads as the
  original (no turn).

Example, from CP1: a full circle of 6 holes. The faces of the holes are at 0, 60, 120, 180, 240 and 300 degrees. The
transforms turn 0, 120, 180, 240, 300 and 0 degrees. A copy made from the transforms has two copies at 0 degrees and
no copy at 60 degrees. That is a wrong copy that looks right.

Thus the add-in does not take the place of a copy from the transform alone. The shared module
`design_model/steps/pattern_places.py` does these jobs:

1. The reader reads the faces. With the marker before the pattern, it reads the faces of the original
   (`source_faces`): the faces that each source feature made (`Feature.faces`), the source faces themselves for a
   pattern of faces, or the faces of the source bodies. With the marker after the pattern, it reads the faces that
   each element made (`PatternElement.faces`, the `faces` of the element). For each face, it writes the centroid
   (`BRepFace.centroid`, in mm) and the area (`BRepFace.area`, in mm2). It reads up to 32 faces of the original and
   up to 8 faces of each element. A list that cannot be read is null.
   Each face costs Fusion a measure. Thus, in a pattern with more than 12 kept copies, the reader reads the faces of
   12 kept copies only (`SAMPLED_ELEMENTS`): the first three, the last two, and copies spread evenly between them.
   A suppressed copy gets no faces. The checks below then prove the places of the sampled copies only. The wrong
   transforms that hand check CP1 found are wrong for every copy in the same way, so a sample shows them. The checks
   of step 5 do not use faces, so they still cover every copy.
   The faces are in the space of their own component. The reader reads a face seen through an occurrence as its
   native face (`nativeObject`). The element transforms are in assembly space: the exports of a part placed 2400 mm
   along Y (T19 in the test projects) show this. Thus `data_in_component` carries the frames into the frame of the
   part, but not the faces.
2. `agrees` checks one place. It moves the faces of the original to the place. At least one face of the copy, and
   at least half of the faces that the place moves, must land on a face of the original with the same area (to
   0.01 mm and 1 part in 1000). A face that the place does not move (a face on the axis of a turn) tells nothing. A
   copy without faces, or a pattern without the faces of the original, cannot be checked. Then `agrees` gives no
   answer, and the other checks still apply.
3. A circular pattern that turns to one side gets its places from the ids (`id_places`). The ids must be copy
   numbers (0 to count - 1), all different, and they must fill the count when no copy is suppressed.
   `circular_sign` finds the way the copies turn: right hand about the axis, or the other way. The faces decide when
   they were read. Else the transforms decide, but only when they agree with the ids (older Fusion versions and
   path patterns on an arc). Else the way is taken only when it does not change where the kept copies land: a full
   circle with no copy suppressed. Else the step is left out ("Which way this pattern turns its copies could not be
   read."). The transforms must still be turns about the axis that was read. That checks the axis.
4. A rectangular pattern, a symmetric circular pattern and a path pattern keep the places of their transforms. Each
   copy whose faces were read must agree with its place. Else the step is left out.
5. In every pattern, `listed_places` and `grid_places` refuse two elements on one place, and places that do not fill
   the count when no copy is suppressed (`suppressed_ids` empty and no element marked suppressed). A missing place
   is then not a copy that the user left out, so the step is left out. A rectangular pattern with a direction whose
   distance is 0 makes copies on top of one another by design. There the check uses the merged copies.
6. A pattern of bodies pairs each copy with a result body by its points (`body_copies.match`). A circular pattern of
   bodies that turns to one side tries the places from the ids, one way and then the other (`id_frames`). The way
   whose copies land on the result bodies is taken.

The Orca output uses the same module. Its circular pattern takes the places from the ids, its rectangular pattern
checks the places, and both check the faces.

A capture from before this change has no faces. A full circle with no copy suppressed still copies. A part turn
whose transforms are wrong, as in Fusion 2706, is left out, because the way of the turn cannot be read. Export the
design again to get the faces.

Nobody has measured the transforms of rectangular, path and body patterns against their faces in Fusion yet. Hand
checks PE1, PE2 and PE3 in `docs/hand-checks.md` do that. Until then, the checks above guard these patterns.

## 4. Debugging

### 4.1 What you need

- The `.paramability` file of the export. It is a zip. Rename it to `.zip` or use `unzip -l` to see the files.
- `report.json` from inside it. Open it in an editor that folds JSON. It can be large, since it holds the whole
  capture and every probe state.
- The add-in repository and Python 3.10 or newer (standard library only; `scripts/fixture_geometry.py` needs numpy).

A quick way to read the main facts of a report:

```bash
unzip -p Part.paramability report.json > /tmp/my-scratch/report.json
python3 -c "
import json; r = json.load(open('/tmp/my-scratch/report.json'))
print(r['outcome'], r.get('refusal'))
for v in r['items']:
    if v['verdict'] not in ('translated', 'skipped'):
        print(v['index'], v['name'], v['verdict'], v.get('cause', ''), v['note'])
for k in ('fixed', 'loose', 'cut', 'dropped'):
    for e in (r.get('sizes') or {}).get(k, []):
        print(k, e['name'], e['reason'])
print(r.get('health'))
"
```

Use your own scratch folder (`mktemp -d`), not the repository.

### 4.2 How to read report.json, field by field

`report.json` of one body (`plan_single_export`). Keys that do not apply are left out.

| Key | What it holds | Look here when |
| --- | --- | --- |
| `writer` | Add-in version and Fusion version. | You compare two exports. |
| `outcome` | `recipe` or `stepOnly` (`parts` for a several-body file). | Always first. |
| `items` | One verdict per timeline item, in order, up to the stop. | A step is missing or has a note. |
| `notes` | The translator's notes (also the dropped size reasons). | You want all remarks in one list. |
| `refusal` | `{ index, name, type, reason, note?, hint? }` of the step that stopped the copy, or of a check after the walk (index null). `hint` is there when the cause of the stop has one (1.9.3). | The part is a fixed shape. |
| `after_stop` | The diagnosis walk after a stop: `stopped_at`, `items`, `steps`. | You want every failing step, not only the first. |
| `error` | `Type: message` of an exception in the reader or the translator. | The note says "the steps could not be read" or "could not be copied". |
| `marker` | `{ position, count }` of the timeline marker. | Steps seem to be missing (they may be after the marker). |
| `capture` | The full capture (section 1.6). | You check what Fusion gave for a step. |
| `probe` | The size probe record (below). | Sizes are marked, cut or dropped. |
| `derived` | The shadow check from the sketch graphs. Not used for the recipe. | You work on reading sketches directly. |
| `timing` | Where the export spent its time (below). | The export is slow. |
| `health` | How the design came out of the export (below). | The design may be changed. |
| `parameters` | `{ listed, left_out, no_formula }`: the user parameters in the manifest, those left out (unit) and the formulas kept as numbers. | A parameter is missing in Paramability. |
| `sizes` | `free`, `fixed`, `loose`, `cut`, `dropped` (section 1.9.5). | Always, for sizes. |
| `gaps` | The gap records, as in `gaps.json`. | Steps were left out. |
| `reach` | The reach read (`read`, `gaps`, `makers`, `moves`, or `error`). | A round or shell was left out "because it picks faces". |
| `links` | Each geometry link of the body with what became of its parameter (`size`, `loose`, `fixed`, `dropped`, `formula`, `not ticked`). | A parameter of another component did not follow. |
| `also_changes` | Unticked parameters that the discovery rows saw changing the part. | You wonder why the result says "These parameters also change this part". |

A `parts` report has `parts: [ { name, outcome, items, notes, capture, probe, sizes, derived, refusal, after_stop,
gaps, reach } ]`, and `marker`, `health`, `parameters`, `sizes`, `links` and `also_changes` at the top.

#### items: the verdicts

```json
{ "index": 7, "name": "Fillet2", "type": "FilletFeature", "verdict": "leftOut", "steps": [],
  "note": "It picks faces of Thicken1, which is missing from the copy.", "gap": "gap_7", "cause": "picks" }
```

- `verdict`: `translated`, `translatedWithNote`, `skipped`, `unsupported` (the step that stopped the copy) or
  `leftOut` (a gap).
- `steps`: the recipe step ids this item wrote (`fillet_7`, `round_7` and so on).
- `note`: the reason or remark.
- `gap`, `cause`: for `leftOut`. `cause` is `own` (its own reason), `picks` (it picks faces of a gap) or `stop` (only in
  `after_stop`: a stop turned into a gap). This `cause` is not the cause of the hint (1.9.3). The hint is in the gap
  record, in `gaps[]`.
- `tool_steps`: for a Combine written with tool steps, the verdicts of the items that built the tools. Look inside
  them when a Combine is left out: the failing step of the tool is there.

#### sizes

```json
"sizes": {
  "free": ["Width", "Wall", "Height"],
  "fixed": [],
  "loose": [{ "name": "Wall", "reason": "Wall may give unexpected results: it moves Sketch3 along a curve, which cannot be copied yet." }],
  "cut": [{ "name": "Width", "reason": "Width: the range stops at 68.75, since Fusion did not rebuild the design at 72.5 (Fillet2).",
            "words": "the range stops at 68.75", "why": "Fusion did not rebuild the design at 72.5 (Fillet2)",
            "min": 20, "max": 68.75, "shared": false }],
  "dropped": [{ "name": "Lid_gap", "reason": "Lid_gap is not used by any copied step, so it is not a size.", "used": false }]
}
```

`free`, `loose` and `cut` use recipe size names. `dropped` uses Fusion names. In `dropped`, `used: true` means a copied
step reads the parameter but the copy could not follow it. `tried: true` means the probe set it to other values and
nothing in the part changed.

#### probe

| Key | Meaning |
| --- | --- |
| `request` | What each state read: sketch tokens, point and line tokens, parameter names, references, faces, borrowed sketches. |
| `states` | One record per state, as `ProbeState.json()` writes it (`lib/probe/state.py`). The first has `e0: true`. Each has `values` (the sizes this row set, by Fusion name, in mm or degrees), `built`, `failed` (the first step in error when it did not build), `warned` (true when the row built but `failed` showed a new warning, so it counts as not built), `read` (what was read), and when they happened `start` (the read before the row), `put_back` (the read after a sketch was put back) and `again` (a row run a second time). A try where the part came apart has `pieces` (the count) and no `read`. `read.pieces` is `{ lumps, others }` (1.8). `read.patterns` holds the copies of each symmetric pattern: `{ key: { count: [n1, n2], elements } }` (3.11). |
| `dropped` | The rows that did not build, with Fusion's error detail (`reason`: `expression_refused`, `recompute_raised`, `recompute_failed`, `new_errors` or `new_warnings`, and `items`). A try where the part came apart is listed too, with the `error` "the part came apart into N separate pieces" and no detail. |
| `untried` | Sizes that move a sketch but got no near rows (the 64 row cap). |
| `restore_gap_mm` | The largest difference between E0 and the read after the parameters went back. |
| `motion` | The motion file (below). |
| `discovery` | The discovery rows: `{ param, value, built, moved, changed, unread }`, or `{ param, moved: null, tried: false, reason }`. |
| `after_rows` | What read differently from E0 once the rows were done and the values were back (`changed`, `unread`). A sketch named here stayed on another solution. |
| `restore_unchecked` | Sketches the restore check could not compare, with why. |
| `recovery` | `{ put_backs, again }`: the extra rebuilds for solver flips. |
| `timeline` | `{ rolled, items, of, reason, suppressed, try_seconds }`: the marker roll (each try rebuilt `items` of the `of` items before the marker), why it did not roll, the "Faster tries" record (`asked`, `on`, `items`, `reason`, `left_off`) and the seconds the tries took. |
| `time_limit` | `{ limit_seconds, hit, seconds?, left_out }`: the time limit of the tries (`null` for none), whether it stopped them, how long they had taken then, and the Fusion names of the sizes that got no try that built (1.8). |

The motion file (`probe.motion`):

| Key | Meaning |
| --- | --- |
| `values` | Key to a fitted value: `{ const, terms }` (Affine), `{ const, sum }` (Terms) or `{ stuck, cause, sketch, rest }` (Stuck). A key that is not listed did not move. |
| `spans` | Per size the probe set: `low`, `high` (the values that built), `failed` (`[value, step]`), `warned` (the entries of `failed` where the step showed a new warning, only when there is one), `split` (`[value, pieces]`, only when a row left the part in several pieces), and `kept`, `changed` when a row changed an outline. |
| `unmeasured` | Sketch name to why the probe could not measure it. |
| `untried` | Sizes left without rows. |
| `timed_out` | Sizes that the time limit left without a try. They are in `untried` too. |
| `refs` | Per measured reference key: an empty text when measured, else why not. |
| `faces` | The outline faces that were measured. |
| `body_moved` | Sizes that changed the body but moved nothing the probe follows. |
| `body_changes` | Per size that a try set alone: `true` when the body changed at one such try, `false` when it read the same at all of them. A try on another sketch solution (`apart`) or past an outline limit does not count. |
| `apart` | State numbers where a sketch was solved another way, so a different outline blames no size. |
| `flipped` | Sketches that stayed on another outline after the values went back. |
| `box_max` | The union of the body boxes over the states (used by cuts through all). |
| `curves` | The profiles whose sketch curves were measured. |

How to use the states. To see what a size did, find the states whose `values` hold only that size. Compare their
`read` with the E0 `read` under the same sketch token. A state with `built: false` and `failed: "Fillet2"` tells you
that Fusion could not build that value.

#### health

```json
"health": { "unrestored": [], "sketch_gap_mm": 0.0, "sketch_drift": false, "restore_unverified": false,
            "probe": "measured", "probe_error": "", "flipped": ["Sketch3"] }
```

| Key | Meaning |
| --- | --- |
| `unrestored` | Parameters that could not be put back. The design is changed. |
| `sketch_gap_mm` | How far the followed sketches are from E0 after the restore (null when not measured). |
| `sketch_drift` | True when that gap is over 0.0001 mm. The design may be changed. |
| `restore_unverified` | True when the probe measured, but the restore could not be compared. `unchecked` says which sketch and why ("reads another outline", "could not be read", "lies on a turned plane"). |
| `probe` | `measured`, `not needed` (no sketch to follow) or `failed`. |
| `probe_error` | The exception of a failed probe. |
| `flipped` | Sketches that stayed on their other solution for a while during the tries. |
| `steps_changed` | Timeline steps still not as at the start after the end check: `{ name, type, before, after, message, was_message?, suppressed? }`, at most 8 (`steps_more` counts the rest). `before: new` for a step not there at the start, `after: gone` for one not there now. |
| `steps_recovered` | Steps that differed and came back by the end actions. |
| `end_actions` | What the end check did: `marker_back`, `marker_lost`, `turned_back_on`, `full_compute`, `values_again`. |
| `steps_unread` | The steps could not be compared. |
| `broken` | The steps in `steps_changed` that are in error now and were not at the start (at most 5). |
| `deferred_left` | Sketches whose compute stayed deferred after their points were moved back. |
| `steps_worse` | True when any step that differs is worse than at the start, also one past the steps `steps_changed` lists. |
| `left_off` | Items of the faster tries that are still off after the end check (at most 5). |
| `sketch_gap_after_rebuild_mm` | The gap of the sketches read again after the end check rebuilt the design (1.11). |
| `undo_dropped` | True when "Lighter on memory" made Fusion forget Undo data. Then no message sends the person to Undo. |

#### timing

`timing` says where the export spent its time (`lib/timing/`, `docs/capture-format.md`, "Timing"). The numbers are
seconds, rounded to 0.01. A failure of the timing code drops the block and changes nothing else.

```json
"timing": { "total": 61.5,
  "phases": { "step_export": 1.2, "capture": 40.1, "size_table": 0.0, "translate_first": 0.8, "reach": 0.0,
              "probe": 15.0, "translate_final": 0.9, "restore": 0.5, "package": 0.1, "after_stop": 0.0,
              "outline_check": 0.0 },
  "capture": { "seconds": 40.1, "steps": 120, "cached": true, "marker_moves": { "count": 124, "seconds": 31.0 },
               "by_type": { ... }, "by_component": { ... }, "slowest": [ ... ] },
  "probe": { "tries": 31, "tries_seconds": 12.0, "rebuild": 10.5, "read": { "count": 40, "seconds": 1.5 },
             "put_back": { "count": 0, "seconds": 0.0 }, "time_limit": { "limit_seconds": 600, "hit": false },
             "try_seconds": 13.2 } }
```

| Key | Meaning |
| --- | --- |
| `total` | From the start of the pipeline to the moment `report.json` is made. The dialog's read before OK and the file write are not in it. |
| `phases` | One time per stage of section 1.1. `after_stop` and `outline_check` (the check that written outlines do not cross themselves, 3.2) are already inside the translate phases. A stage that did not run is 0. |
| `capture` | The timeline read: `cached: true` when the dialog read it before the OK click (then its time is not part of this export). `marker_moves` counts the marker moves and their time. `readers` is the time of all step readers. `placement` is the place of the picked body, read once before the walk. `tail` is the read after the walk, split in `tail_parts` (`target`, `parameters`, `links`, `graphs`). `by_type` and `by_component` add up the time per step type and per component. `slowest` lists the 10 slowest steps. A several-body export has `captures`, one per body. |
| `probe` | `tries` (rows run), `tries_seconds` (time inside them), `rebuild` (that time without the reads: setting sizes, rebuilding, putting back), `read` and `put_back` (count and time), `read_parts` (the time of each part of the reads, with `pieces`), `time_limit` (`limit_seconds`, `hit` and, when hit, `left_out`, 1.8), `try_seconds` (the same as in `probe.timeline`). |
| `undo` | The "Lighter on memory" record: `{ on: false }`, or `{ on, applied, steps, error }` (1.11). |

The time of one step in the capture is mostly the marker move that builds it. So a step type that is slow in
`by_type` is a step type that Fusion rebuilds slowly.

#### derived

The shadow check: the add-in solves each sketch from its graph (`sketch_solve`) and compares the solved values with
what the probe read. `summary` counts the sketches and values that agree and disagree. It changes nothing in the
export. It is useful only when you work on reading sketches without tries.

### 4.3 From a note in the app to the code

Every reason text in the add-in is built from fixed words plus names and numbers. To find the code that wrote a text:

1. Pick a part of the text without names and numbers. From "Width: the range stops at 68.75, since Fusion did not
   rebuild the design at 72.5 (Fillet2)." pick "did not rebuild the design".
2. Search the add-in code:

   ```bash
   cd <add-in repo>
   grep -rn "did not rebuild the design" ParamabilityExport/lib
   ```

3. If nothing is found, the text may be split around a `%s`. Try a shorter piece: "did not rebuild", "range stops".
4. You find the function that builds the text (here `notes.not_rebuilt_why`, `notes.cut_words`, `notes.cut_reason`).
   Then search who calls it: `grep -rn "not_rebuilt_why" ParamabilityExport/lib`.

Where the texts live:

| Text family | Module |
| --- | --- |
| Size reasons: "may give unexpected results", "stays fixed", "is not a size", "the range stops at", stuck causes, gap texts, fixed shape notes | `lib/translator/notes.py` |
| Sentences that both outputs give for the same fact ("This extrude starts in a way that is not copied.", "Steps of type thicken are not copied.") | `lib/design_model/words.py`, and `lib/design_model/paths/words.py` for sweep paths |
| Step refusals ("This draft leans faces on both sides ...") | the handler module of the step type; sweep texts in `sweep/sweep_limits.py`, path texts in `design_model/paths/words.py` |
| Walk stops ("The body could not be followed through the timeline.") | `lib/translator/walk.py`, `bodies/split_rules.py`, `gaps/stops.py`, `translate.py` |
| Package notes ("12 steps copied from Fusion.", "N sizes may give unexpected results") and "Tip: " lines | `lib/export_plan/messages.py`, `lib/translator/notes.py` |
| Hints of left-out steps and of stops ("Round the sharp corner of the path with a sketch fillet.") | `lib/capture_model/gap_hints.py`; the Orca output shows only the hints that fit it (`lib/orca_translate/causes.py`, `tip`) |
| Labels of sizes ("Base cup mid extrude offset") | `lib/params/labels.py` |
| Time limit lines ("Time spent: 2 min 10 s. About 4 min left ...") | `lib/export_plan/messages.py`, `lib/export_plan/time_limit.py` |
| Probe reasons ("it changes a sketch and could not be tried at other values") | `lib/export_plan/probe_flow/reasons.py` |
| Health lines ("These parameters could not be set back ...") and the box about steps left off | `lib/export_plan/health.py` |
| Dialog, early warning ("Likely left out of the copy:") and result window | `lib/dialog_model/` |
| Error messages of a stopped export ("Fusion could not rebuild the design for this size.") | `lib/design_edit/`, `lib/fusion_reader/step_export.py`, `commands/export_common.py` |

A text that is not in the add-in comes from the Paramability app. Examples: "Range shortened.", "Kept fixed by the
export", "N small steps are missing". Search the text of the app.

The step label tells you which Fusion item a recipe step came from: the recipe step `{ "id": "round_7", "label":
"Fillet2" }` was written for timeline index 7, named Fillet2. A gap id `gap_12` is timeline index 12. A step inside a
tool has a prefix, for example `t9_0_extrude_4`.

### 4.4 Replay an export without Fusion

The capture inside `report.json` is enough to run the translator again. This is the most useful debug tool: change
the code, translate the same capture again, compare. To check an export against many captures at once, keep them in a
local folder and list them in `tests/local/captures.json` (see `tests/test_local_captures.py`).

Put this file in your scratch folder, not in the repository:

```python
# replay_one.py: translate the capture of one export again, without sizes.
import json, sys, zipfile

ADDIN, EXPORT = sys.argv[1], sys.argv[2]
sys.path.insert(0, ADDIN + "/ParamabilityExport")
from lib.translator import translate

if EXPORT.endswith(".json"):
    with open(EXPORT, encoding="utf-8") as f:
        report = json.load(f)
else:
    with zipfile.ZipFile(EXPORT) as z:
        report = json.loads(z.read("report.json"))
capture = report["capture"]          # a parts file: report["parts"][n]["capture"]
result = translate(capture)
for v in result.items:
    print(v["index"], v["name"], v["verdict"], v["note"])
print("refusal:", result.refusal)
print("gaps:", [g["name"] for g in result.gaps])
```

Run it with `python3 -I replay_one.py <add-in repo> Part.paramability`.

Without a size table every value is a number. This shows the walk: which steps are copied, left out or stop the copy,
and why. For the sizes, also build the size table and the motion like the export did (`table_for` and `motion_for` in
`tests/test_local_captures.py` show how).

To try a change, edit the capture (a copy of it) and translate again. For example, set a step's `data.angle_deg` to
another number, or remove a key to see what the handler does without it.

### 4.5 Run the tests

From the add-in repository:

```bash
python3 -m unittest discover -s tests -t .                 # the full suite
python3 -m unittest tests.test_translate_draft             # one module
python3 -m unittest tests.test_translate_draft.DraftTest.test_the_angle_follows_its_size   # one test
```

The full suite has about 2500 tests and takes about a minute on a laptop. Set `PYTHONDONTWRITEBYTECODE=1` if you do
not want `__pycache__` folders (they are ignored by git anyway).

Tests that help most when you debug:

- `tests/test_follow_or_flag.py` translates every capture fixture with every user parameter ticked. Each parameter a
  copied step reads must be followed, loose or dropped with a reason. A new fixture is picked up on its own.
- `tests/test_step_kinds.py` keeps the step kind table and the readers in step.
- `tests/test_boundary.py` checks the import table of the packages and the private names (see 2.1).
- `tests/test_interfaces.py` checks the declared store, port and probe members (see 4.11).
- `tests/test_put_back_order.py` holds the call order of the put back on every way an export ends (see 4.11).
- `tests/test_pipeline.py`, `tests/test_pipeline_gaps.py` and `tests/test_parts_pipeline.py` run the whole pipeline
  against a fake Fusion (`FakePort`, `FakePartsPort` in `tests/fakes/port.py`).
- `tests/test_local_captures.py` covers captures saved from real designs. They stay on one machine (git-ignored
  `tests/local/captures.json`, packages in the folder `PARAMABILITY_LOCAL_REPORTS`), and the module skips without them.
- `tests/test_gap_hints.py` keeps the hint table and the causes of the translator in step.
- `tests/test_undo_steps.py` covers "Lighter on memory" with a fake `Command.beginStep`.
- `tests/test_formula_corpus.py` holds typical printing formulas, made up (a wall of `3 * 0.4 mm`, a fraction of an inch,
  a guarded count). Each case is a set of user parameters, or a feature value that reads them. The test asks whether the
  size table and `values.quantity` keep the formula, so that the shape follows a size that is changed in Paramability.
  A case marked as an expected failure waits for the change that fixes that class of formula.
- `tests/test_left_out_preview.py` covers the early list of left-out steps, `tests/test_probe_time_limit.py` the time
  limit (the stop, the put back, the words, the progress line and the choice in the dialog), `tests/test_probe_pieces.py`
  the count of pieces, and `tests/test_params_labels.py` the labels of the sizes.
- `tests/test_translate_thread.py`, `tests/test_translate_coil.py` and `tests/test_capture_reader_coil.py` cover the
  threads, the tapped holes and the coils. `tests/coil_helpers.py` builds the coil captures.

Two more tools help to measure, outside the unit tests:

- `docs/test-projects.md` is a set of fifteen small, typical printing projects: an electronics box with a lid, a threaded
  jar, a hinge, a cable clip, a gear, a phone stand, a name tag, a spring, a bracket, a lamp shade and a mug, a plant pot,
  a drawer organizer, a pen cup with a name, a lid with a centred label, and a plate with a tuned hole. Build each one in
  Fusion (a Fusion AI assistant can do this from the first line of its text), export it as the "Export:" line says, start
  the file name with its number (`P1_`, `P2_`), and open each file in Paramability. Then you see how many kinds of
  projects the copy covers, and not one design. Every project uses parameters with comments and at least one
  formula.
- `scripts/formula_census.py` counts how the formulas of exported packages translate. Run it from the add-in root:
  `python3 scripts/formula_census.py <folder of .paramability or .zip exports>`. For each distinct set of user
  parameters it builds the size table the way the manifest list does (every offered parameter ticked). It counts the
  formula parameters that become derived sizes or constants and those that stay numbers, the feature values that read a
  size and whether they translate, and the forms that the formulas use (operators, functions, unit words, fractions). It
  prints counts only, with the reasons masked: never a value or a name. So its output can go in a ticket. Run it before you
  change the expression code, to see which forms real designs use.

### 4.6 Add a synthetic capture test for a new case

Example: you want to check what the walk does with a step type it does not copy, after a copied extrude.

1. Start from a fixture close to your case. `tests/fixtures/captures/` has about 180. Small ones: `core_*.json`,
   `extrude_plate.json`, `combine_cut.json`.
2. Write the test in a `tests/test_translate_<topic>.py` file. Build the capture in the test with `load_capture` and a
   small edit, so the test shows what is special:

   ```python
   import unittest

   from tests import context  # noqa: F401  puts the add-in on the import path
   from tests.translator_helpers import load_capture, left_out, stopped

   from lib.translator import translate


   def with_thicken(target_changed=True):
       """The plate of extrude_plate, then a thicken on the part."""
       capture = load_capture("extrude_plate")
       capture["items"].append({
           "index": len(capture["items"]), "name": "Thicken1", "type": "ThickenFeature", "suppressed": False,
           "health": "ok", "message": "", "in_target_component": True,
           "bodies_after": [{"token": capture["target"]["token"], "name": capture["target"]["name"]}],
           "target_changed": target_changed, "data": {}})
       return capture


   class ThickenTest(unittest.TestCase):
       def test_a_thicken_that_changes_the_part_is_left_out(self):
           result = translate(with_thicken())
           self.assertIsNotNone(left_out(result))
           self.assertIsNone(stopped(result))
   ```

3. Assert outcomes, not wording: the recipe values, the verdicts, the loose and dropped names. Wording changes
   often.
4. For a case with sizes, give the capture `parameters` and a `data.params` entry, build a table
   (`tests/test_translate_sized.py` has `table_of(capture, ["Height"])`) and call `translate(capture,
   size_table=table)`. For sketch values, also give a motion (`tests/fixtures/motion/` or `tests/probe_helpers.py`).
5. When you save a fixture file, run `python3 scripts/fixture_geometry.py <fixture name> --write` so its box and volume
   are right.
6. To make a fixture from a real export, copy the `capture` of `report.json` as it is. Keep private designs out of the
   repository: rename and simplify, or build a small capture by hand that shows the same thing.

`translate(capture, handlers={...})` lets a test replace a handler, to test the walk alone.

### 4.7 The Fusion calls, and which ones are risky

No tool runs Fusion. The Fusion side is checked by hand. There are two pages:

- `docs/hand-checks.md` is the short page for each release. Export your usual projects and compare them with the last
  release ("same or better"). Then do the 10-second check in Fusion after each export: the marker is back, no step is
  newly yellow or red, the sketches look the same, and the parameters show their formulas and old values. It also has
  a short list of small test models for cases your own projects do not cover, and the first fields of `report.json`
  to open when something looks wrong.
- `docs/hand-tests.md` lists every hand test, with past results. Use it only when `hand-checks.md` points to a test.
  Its sections "Fusion calls to watch" and "Capture reader calls to watch (...)" list every Fusion call that was
  written from the API reference and not yet confirmed on a real design. When you add a Fusion call, add it there too.

Where the calls are:

- `lib/fusion_reader/`: all reads (capture, probe states, reach, faces, references), the parameter store
  (`rows.py`), the sketch keeper and the STEP export.
- `lib/fusion_ui/`: the dialogs, the log and the message boxes.
- `commands/`: the buttons and the flows.

The calls with most risk, since they change the design or depend on Fusion's exact behavior:

| Call | Where | Risk |
| --- | --- | --- |
| `Timeline.markerPosition` (set), `moveToEnd` | `capture.py`, `read_gap_reach.py`, `read_face.py`, `rows.py`, `design_edit/marker.py` | The marker may not go back. The code checks after every move and raises `MarkerError`. |
| `UserParameter.expression` (set), `Design.computeAll` | `rows.py` | A parameter may not go back. `restore_parameters` tries twice, plain numbers before formulas. |
| `TimelineObject.isSuppressed` (set) | `rows.py` (`suppress_items`) | An item may stay off. Only with "Faster tries" (on to start with). `left_off` names it, and the end check turns it on again. |
| `Command.beginStep(makeExistingStepNonUndoable=True)` | `undo_steps.py` (through the port) | A preview call. Only with "Lighter on memory". Undo may not step back through the export. On a failed call no further call is made. |
| `SketchPoint.move`, `Sketch.isComputeDeferred` | `sketch_keep.py` | Moves sketch points back after a solver flip. The flag goes back to its start value, read back. |
| `TimelineObject.healthState`, `errorOrWarningMessage`, `isSuppressed` (set to False) | `rows.py` (`timeline_health`, `turn_on`) | Read at the start and end of each export; a step off at the end that was on at the start is turned on again. |
| `Occurrences.addNewComponent`, `BRepBody.copyToComponent`, `Occurrence.deleteMe` | `step_export.py`, `temp_copy.py` | The temporary copy adds timeline items; they must all go. |
| `Design.findEntityByToken` | everywhere in the probe and reach reads | A token may change after a rebuild. A probe sketch that does not match E0 is not followed. |
| `Feature.faces` | `read_gap_reach.py` | May not list every face after later steps. An empty or short list counts as "reached". |
| `TemporaryBRepManager` | `read_intersect.py`, `read_split.py` | Tests an intersect on copies: the volumes of a Combine, and which pieces of a split lie inside the tool when no face tells. It must never touch the design. A boolean that fails gives no answer. |
| `ThreadFeature.threadInfo`, `isFullLength`, `threadLength`, `threadOffset`, `inputCylindricalFaces`; the thread of `HoleFeature` | `read_thread.py`, `read_hole.py` | The member names and the units come from the API reference. Where a tapped hole keeps its thread (`thread`, `threadInfo` or the hole itself) is not confirmed: hand check TD2. A member that is missing reads as null, and the thread is left out. |
| `ChordLengthFilletEdgeSet.chordLength`, `VariableRadiusFilletEdgeSet.startRadius`, `endRadius`, `midPositions`, `CurveEvaluator3D.getTangent`, `SurfaceEvaluator.getCurvature`, `Cylinder.axis`, `Cone.axis` | `read_finish.py` | The radius of the round is measured from the curvature of the face that the step made. The axis of a cylinder or cone beside a chord length edge tells if the face is straight across the edge. Hand checks CR1 and VR1 confirm the rule of a chord length and the change of a changing radius. A member that is missing reads as null: the round is left out, or, for an axis, the chord length keeps its number. |
| `CoilFeature.faces`, `Edge.evaluator`, `ModelParameter.role`, `ModelParameter.createdBy` | `read_coil.py` | The API gives a coil no type, axis or hand. The reader takes the parameter roles, the faces and points along the edges. A member that is missing leaves the coil out. |
| `PipeFeature.path`, `sectionType`, `sectionSize`, `isHollow`, `sectionThickness`, `distanceOne`, `distanceTwo`, `startFaces`, `endFaces` | `read_pipe.py` | The path can be read only with the marker before the pipe. Hand check PI1 (Fusion 2706) confirmed the place of the section, the size as a diameter and the inward wall. A member that is missing reads as null, and the pipe is left out. |
| `Component.findBRepUsingRay`, `ToEntityExtentDefinition.isChained` | `read_face_rays.py`, `read_extent.py`, `read_solid.py` | The rays from the outline of an extrude to a curved face it ends on, with the marker before the step. Hidden bodies are included. Hand check EX3 confirms that a ray meets the face when the outline lands on it, and misses where the outline reaches past it. No answer gives null, and the step is left out. |
| `PatternElement.transform`, `PatternElement.faces`, `Feature.faces`, `BRepFace.centroid`, `BRepFace.area`, `BRepFace.nativeObject` | `read_repeat.py` | Fusion 2706 gives the transforms of a circular pattern one step ahead (hand check CP1). The translators place circular copies by their ids and check the places of up to 12 sampled copies against their faces (3.21). Rectangular, path and body patterns, and the space of the faces of a pattern in a placed component, are not measured yet: hand checks PE1, PE2 and PE3. A face list that cannot be read is null, and that copy is not checked. |
| `BRepBody.lumps`, `Component.bRepBodies` | `probe_state.py` | Read at each try for the pieces of the part. Nothing is recomputed. |
| `BRepBody.volume` | `probe_state.py` | Read at each try with the box (`volume_mm3`). Without it, a try does not show that the body stayed the same. |
| `createForAssemblyContext`, `Occurrence.transform2` | `placement.py`, `probe_refs.py` | Places of other components. A wrong frame gives `placement.error` and a fixed shape. |

Every read is wrapped in `geo.safe`, so a failed read gives null and never a guess. The risky part is the writes.

### 4.8 The add-in log in Fusion

`lib/fusion_ui/log.py`, `log(text)`, writes with `Application.log`. Each line starts with "Paramability export:". In
Fusion the lines show in the Text Commands window (in recent Fusion versions: File menu, View, Show Text Commands).
Open it before you export.

What is logged: a capture that failed, a translation that failed, a probe that could not start or failed, a sketch
put back that failed, a marker roll or suppression that failed, the reach read result, the shadow check line,
parameters that could not be restored, steps that would not turn back on, a "Lighter on memory" call that stopped
("keeping the tries out of Undo stopped: ..."), and the full traceback of an unexpected error. An unexpected error also shows a
message box with the traceback (`error_box`).

To debug code in Fusion: change the file, then in Scripts and Add-Ins click Stop and Run on the add-in. `stop` drops
the add-in modules from Python's cache, so Run loads your change. Fusion can also attach a Python debugger (VS Code)
to an add-in from the Scripts and Add-Ins dialog; see Autodesk's help for your version.

### 4.9 Common failure patterns

| What you see | What it looks like in report.json | Usual cause | Where to look |
| --- | --- | --- | --- |
| Fixed shape, note "the steps could not be read" | `outcome: stepOnly`, `error: "CaptureReadError: ..."` or another exception, often no `items` | The reader raised: a timeline group with an unread child, an exception outside `geo.safe` | the log; `capture.py` |
| Fixed shape at a named step | `refusal` with `index` and `reason`; that item's verdict `unsupported` | A stop rule (3.10) | the reason text, grep (4.3); `after_stop` for more |
| "The body could not be followed through the timeline." | `refusal` at a step; tokens differ in `bodies_after` around it | A step made a new body with the same name (a split, a Move with copy) | `capture.items[n].bodies_after`, `lineage.py` |
| "More than 256 steps of this part cannot be copied." | `refusal` with index null; `after_stop.steps` lists them | Too many gaps; often one gap makes many later picks gaps | `reach`; fix the first gap |
| A join left out with "It sits on a step that was left out" | `leftOut` verdict; the gap's `dependsOn` names the gaps it sits on | The join meets only material of gaps (1.9.3) | the first gap in `dependsOn` |
| Many rounds left out "It may pick faces of ..." | verdicts `leftOut` with `cause: picks`; `reach.read: false` | The reach read failed or did not run | `reach.error`, the log |
| A size is marked | `sizes.loose` with a reason | A value could not follow (3.1), a pick on moving geometry (3.3), the audit | checklist 4.10.2 |
| A size is not a size | `sizes.dropped` | Not read by any copied step, or tried and changes nothing, or cannot follow | `used`, `tried`; `probe.motion.spans` |
| Range too short | `sizes.cut` with `why` | A step failed in Fusion, or a sketch changed outline, or a recipe rule | checklist 4.10.3 |
| Sketch sizes all marked "could not be tried" | `health.probe: failed`, `probe` missing | The probe failed to start or a read failed | `health.probe_error`, the log |
| Sizes marked "it changes a sketch and could not be tried" | `probe.untried` not empty | The 64 row cap | untick sizes you do not need |
| Strange size results after a failed try | `health.flipped`, `probe.recovery`, `probe.after_rows.changed` | A sketch with two solutions flipped | the sketch's constraints in Fusion |
| "Check your design" in the result | `health.unrestored` or `health.sketch_drift: true` | A parameter did not go back, or a sketch did not come back | checklist 4.10.6 |
| Slow export | `timing.phases`; many `probe.states`, `probe.timeline.rolled: false`, high `try_seconds` | Each row rebuilds the whole timeline twice | checklist 4.10.5 |
| Sizes marked "the tries ran out of time before this size was tried" | `probe.time_limit.hit: true` and `left_out`; `probe.motion.timed_out` | The time limit of the dialog was reached | raise the limit or untick sizes (1.8) |
| A range stops with "the part comes apart into N separate pieces" | `sizes.cut`; `probe.states` with `pieces`; `probe.dropped`; `probe.motion.spans[...].split` | Copies of a pattern or a join no longer touch the part, or a cut cuts it in two | 1.8, "What a state holds"; 3.2 |
| Fixed shape at a named step, "because of an error in the add-in" | `refusal` with `hint`; that item's verdict `unsupported` | A bug in the handler of that step, or of a step of a tool body when the step is a Combine (1.9.1) | the traceback in the log and in the export trail (4.8) |
| A step left out with "Export again with this version of the add-in" | verdict `leftOut`; the gap has the hint | An export of an older add-in (before 0.10.6) | export again |
| "<Part> stays a fixed shape in this file and does not change with this size." | `sizes.loose` of a `parts` report | A size also moves a part that stays a fixed shape | 1.10, "Several bodies" |

### 4.10 Checklists

#### 4.10.1 "A step was left out"

1. In `report.json`, find the item: `items[]` with `verdict: "leftOut"`. When it is not at the top level, look in the
   `tool_steps` of a Combine.
2. Read `cause`:
   - `picks`: the step was left out only because it picks faces of another gap. Go to step 5.
   - `own`: the step has its own reason. Go on.
3. Read `note` (the reason). Grep a piece of it (4.3) to find the handler branch that refused it.
4. Look at the step's capture data: `capture.items[]` with the same `index`. Check that the reader gave what the
   handler needs. A `null` or `"other"` value means Fusion did not answer: the reader could not read a member. Compare
   with `docs/capture-format.md`, section 5, for that type.
5. For `picks`: look at `reach`. Is `read` true? Does `makers["<index>"]` list the gap? If `read` is false, the reach
   read failed (`reach.error`, the log), and every later picking step is left out on the safe side. If the gap is in
   `makers`, the pick is real: fix the first gap.
6. Look at the gap record in `gaps[]`: `after` and `before` say where it belongs; `sizes` and `looseSizes` say which
   sizes it reads; `hint` says what the person was told to change. A gap with no `hint` has a refusal without a cause.
   A refusal that stops the copy has its `hint` in `refusal`, when its cause has one.
   When the advice is useful, give the refusal a cause and add a hint to `gap_hints.py` (and a row to the app's page
   "Steps that do not copy yet").
7. Replay the capture (4.4) with your fix. Write a test with a small capture of the case (4.6).
8. If the type has no handler at all, read `docs/adding-a-step-type.md`.

#### 4.10.2 "A size is marked" (may give unexpected results)

1. Find the size in `sizes.loose`. Read the reason after "may give unexpected results". A "past 2.05" before the colon
   means the problem starts only past that value.
2. Find the family of the reason:
   - A stuck cause ("moves Sketch3 along a curve", "makes a different outline", "turns the plane", "could not be read
     at other values", "could not be tried"): the probe could not fit a sketch value. Go to step 3.
   - "picks a point ...", "may move with it", "a face that may move": a pick or a reach on geometry the copy cannot
     place (3.3).
   - "<step> reads it, and the copy does not follow it": the audit. A handler did not deal with a `data.params` path.
     This is a gap in the handler, not in the design.
   - "it changes this part in a way the copy does not follow": the probe saw the body change in the size's own row,
     but no followed sketch or reference moved (`probe.motion.body_moved`).
   - "Fusion uses it only in Extrude5, a step the export could not copy": only a gap reads it. Expected.
   - "it was followed between A and B": the rows covered less than the range.
   - "it moves a joint": a joint reads it.
3. For a stuck value: in `probe.motion.values`, find the keys with `stuck` that name the size. The key tells the step,
   profile, loop and field. The `sketch` tells the sketch.
4. In `probe.states`, find the rows that set only that size. Compare their `read` of that sketch with E0. Did the
   outline change shape? Did the value move along a curve?
5. Check `probe.motion.apart` and `health.flipped`: a flip may have spoiled some rows.
6. In Fusion, look at the sketch: is it fully constrained? Does a dimension have two solutions? A fully constrained
   sketch with clear dimensions fits much better.

#### 4.10.3 "The range is cut too short"

1. Find the size in `sizes.cut`. Read `why`:
   - "Fusion did not rebuild the design at X (Step)": a try failed in Fusion.
   - "Sketch makes a different outline at X": a try changed the outline.
   - "the part comes apart into N separate pieces in Fusion at X": a try left the part in several pieces. Look at
     `probe.motion.spans[<Fusion name>].split` and at the states with `pieces`. In Fusion, set that value and look at
     the browser: does a post, or a half of the part, show as its own body?
   - "the outline of Sketch3 would cross itself, lose a corner or have a hole reach its edge": the outline check (3.2).
   - another text: a recipe rule (a taper near 45 degrees, an angle near zero, a length that would pass its start, a coil
     whose wire would touch the axis).
2. For a failure: look at `probe.motion.spans[<Fusion name>]`: `low`, `high` and `failed`. Check the step named in
   `failed`. Is it a step of the part? (Only those cut.) Set the same value in Fusion by hand and see if that step
   fails. If Fusion really fails there, the cut is right.
3. Count the nearer rows. The probe has at most 24 nearer rows per export and 64 rows in all. With many sizes, some
   get only one nearer try. Then the cut end can be far from the real limit. Untick sizes you do not need, or type the
   range in the dialog.
4. Check `probe.dropped` for the detail of each failed row (`reason`, `items`). `expression_refused` means Fusion did
   not accept the value text (a unit problem), not a geometry failure.
5. Check flips (`health.flipped`, `probe.recovery`): a row that started on the wrong solution can fail for no real
   reason. The `again` rows protect against most of this.
6. A typed range is never cut. If you need the full range, type it; the size then gets "followed between A and B".
7. When `report.json` has no cut for a size but the app shows "Range shortened", the app made the cut when it opened the
   file (1.12, "The range end check"). The message of the app names the step that fails there.

#### 4.10.4 "The copy does not match"

1. In the app, the Shape sizes card shows the gap between the copy and the original. Read the copy note: largest gap,
   typical gap, and the steps the kernel left out, with the kernel's reason.
2. Translate the capture again with your change (4.4). Compare the verdicts and the gaps with the report.
3. In `report.json`, list the verdicts `translatedWithNote`. Their notes often say what the copy does another way
   ("Fusion's stored direction ... turned", "a twist or taper ... check the shape", "Fusion joins the corners ... another
   way").
4. Check the gaps: an unfinished copy cannot match until the steps are added.
5. Check the place: `upAxis` of the manifest, `capture.up_axis`, `capture.target.placement`. A Y up design with the wrong
   choice in the dialog turns the recipe.
6. Find the first step where the copy and Fusion differ. Build the recipe with the steps up to step N (edit a copy of
   `recipe.json`, or replay a capture with later items removed) and compare the volume with `capture.items[N]
   .target_after.volume_mm3`.
7. Check the sizes at their current values: every formula must give the captured number. The translator checks this,
   so a mismatch here points to the app's formula evaluation or units.

#### 4.10.5 "The export is slow"

1. Read `timing.phases` in `report.json`. It tells you which stage to look at. Then count the work. The capture
   moves the marker once per timeline item (one rebuild each); it measures the body only around runs of steps of other
   components, not inside them. Each probe row costs two rebuilds (the row and the restore). With a Fusion that has
   `Design.modifyParameters` each is one rebuild of the steps the sizes change; without it, one per parameter and a
   full `computeAll`; Export size choices adds one `computeAll` per size before its STEP. The reach read moves the
   marker `reach.moves` times. A face used as an outline is read with the marker before its step, in each row that
   may change that face; the marker stays there until the values go back, so it adds a rollback but no rebuild.
2. Look at `probe.timeline`:
   - `rolled: false` and a `reason`: each row rebuilt the whole timeline. The reason says why the marker could not
     move earlier. Steps of other components after the part's last needed step never keep the marker back (a link
     counts only for the items before the step that holds it), so a `rolled: false` on a design with many components
     points to a joint, an unknown step type that is not a `...Feature`, or a link whose step could not be found.
   - `items` and `of`: how many items each row rebuilt.
   - `suppressed`: was "Faster tries" asked, did it turn items off, and how many.
   - `try_seconds`: the time of all tries.
3. Count `probe.states`. Up to 64 rows plus the rows run again. Fewer ticked sizes give fewer rows.
4. Look at `probe.recovery`: many put backs mean a sketch flips often. Fix the sketch in Fusion. Look at
   `probe.stopped` and `health.tries_stopped`: a try left a step in error with the values back, so the tries ended
   there. The step named is the one to fix in Fusion (often a Remove or a Combine that lost its body).
5. Look at `probe.discovery`: up to 12 rows for parameters of other components.
6. "Faster tries" is on by default; untick it once and compare `try_seconds` with and without it.
7. In `timing.probe`, `read_parts` splits the state reads of the tries into sketches, points, params, refs, box, pieces and
   faces (the marker roll check and the read after the tries are not counted). A `faces` part with
   a large time means outline face reads, each of which moves the marker before the face's step. A large `refs` part
   points at the place of the body read at each state (`probe_refs._target_back`); it fetches only three vertices.
8. Read `probe.time_limit`: when `hit` is true, the time limit of the dialog stopped the tries, and `left_out` names the
   sizes that got no try (1.8).
9. Read `timing` (4.2) first: `phases` says which stage took the time. When `capture` is large, `slowest` and
   `by_type` name the steps Fusion rebuilds slowly. When `probe` is large, compare `rebuild` with `read`: a large
   `read` time points to many outline face reads or borrowed sketches.

#### 4.10.6 "The design is not put back"

1. Read the result window section "Check your design" and `report.json` `health`.
2. `health.steps_changed` names each step whose health differs from the start, with `before`, `after` and Fusion's
   `message`. `end_actions` says what the add-in did about it: `full_compute` alone means a full rebuild did not
   help, `values_again` that setting the start values again did not help either. `steps_recovered` lists the steps
   those actions brought back. Look at the step types first: a fillet or chamfer points to a value round trip, a
   sketch to a solver flip (check `health.flipped`), a step that was already in a warning to a risky step. A step
   that reads worse after `full_compute` may only show a warning Fusion hides until a full rebuild: do Compute All on
   the saved design without the add-in and compare. `steps_unread` means nothing could be compared.
3. `health.deferred_left`: a sketch whose compute stayed deferred. Edit it and finish it, or use Undo.
4. `health.unrestored` names parameters that did not go back. In Fusion, open the parameters and check them. Use Undo,
   or reopen the last save.
   When `health.undo_dropped` is true, Undo is not valid advice: "Lighter on memory" made Fusion forget Undo data. Then
   close the design without saving and open the version saved before the export. Every message of the add-in says the
   same in that case.
5. `health.sketch_drift: true` with `sketch_gap_mm`: a sketch did not come back to E0. Most often a sketch with two
   solutions stayed on the other one. Check `health.flipped` and `probe.after_rows`. With `health.probe: failed` the
   tries ended early; the sketch was still put back once, so a drift there means the put back did not help.
6. `health.restore_unverified` with `unchecked`: the add-in could not compare. Look at the named sketches.
7. `probe.timeline.suppressed.left_off` and `health.left_off`: timeline items that stayed suppressed after "Faster
   tries", also after the end check tried to turn them on. The person got a message only for the items that the end
   check does not name already. Unsuppress them in the timeline.
8. The timeline marker (`end_actions` has `marker_back` or `marker_lost`): the person got a message "The timeline marker could not be moved back ..." when it failed.
   Move it by hand.
9. Items left by the temporary copy: the export stops with "The temporary copy of the part left N steps in the
   timeline." Delete them or use Undo.
10. To find the cause in the code, start at `PutBack` (`export_plan/pipeline/put_back.py`, see 4.11.1). It calls
    these, in this order: `restore` (`design_edit/restore.py`, `restore_parameters`), `end_trim` and `_end_roll`
    (`TryTimeline.end_trim` and `TryTimeline.end` in `timeline_trim.py`), `_after_tries` (with `ProbeRun.settle` and
    `_put_back` in `pipeline/probe_run.py`, and `SketchKeeper.put_back` in `fusion_reader/sketch_keep.py`),
    `_settle_steps` (`settle_timeline` in `design_edit/timeline_health.py`), `_gap_after_settle`, `_warn_steps`,
    `_warn_left_off` and `undo_steps.drop_after`. The store calls (`unsuppress_items`, `unroll_marker`) are in
    `DesignParameterStore` (`fusion_reader/rows.py`).

### 4.11 The end of an export, the interfaces, the order tests and the tolerances

#### 4.11.1 Where an export ends: `PutBack`

When the design is not as the person left it, the cause is in the end of the export. All of the end is in one class,
`PutBack` (`lib/export_plan/pipeline/put_back.py`). Both pipelines (one body and several bodies) use it. Step by step:

1. Open `put_back.py`. The docstring of `PutBack` lists the calls in order (see also 1.11, "The put back, in order").
2. Find how the export ended. A made export ends in `close`. An export that stopped (an error or a cancel) ends in
   `close_failed`. Tries that failed end in `tries_ended`.
3. Find the `health` key in `report.json` and the member that sets it:

   | `health` key | Set by |
   | --- | --- |
   | `unrestored` | `PutBack.restore` (it keeps the names that would not go back) |
   | `sketch_gap_mm`, `sketch_drift` | `PutBack.settle`, from the gap read after the restore |
   | `sketch_gap_after_rebuild_mm` | `PutBack._gap_after_settle` |
   | `steps_changed`, `steps_recovered`, `end_actions`, `steps_unread`, `broken`, `steps_worse` | `PutBack._settle_steps` (`settle_timeline`) |
   | `left_off` | `PutBack.left_off` (`TryTimeline.left_off`) |
   | `deferred_left` | `PutBack.deferred_left` (`SketchKeeper.deferred_left`) |
   | `tries_stopped` | `ProbeRun.stopped`, kept by `PutBack.tries_ended` |
   | `undo_dropped` | `PutBack.undo_dropped` (`undo_steps.UndoSteps.record`) |
   | `probe`, `probe_error`, `flipped`, `unchecked` | The probe. The pipeline hands them to `PutBack.health_inputs`. |

4. All these go into one record, `health.HealthInputs`. `health.make_health(HealthInputs(...))` makes the `health` of
   the report. When a key is wrong, look at the `HealthInputs` the pipeline built (`PutBack.health_inputs`), not at the
   sentence that shows it.
5. To see the calls an export makes on one way out, read the list of that way in `tests/test_put_back_order.py` (see
   4.11.3).

The `run_guarded` function (`commands/export_common.py`) is not the place to look for a lost value in Export for
Paramability. It only shows the message boxes and puts the marker back once more.

#### 4.11.2 The interfaces and the conformance tests

Four things are declared once and checked by a test. A class that lacks a declared member fails the test. Code that
asks for a member that is not declared fails it too. A declared member that no code asks for also fails it, so a
declaration never keeps a dead member.

| Interface | Declared in | Real classes | Fakes |
| --- | --- | --- | --- |
| Parameter store | `design_edit/store.py` (`ParameterStore`, `TIMELINE_CONTROLS`) | `DesignParameterStore` in `fusion_reader/rows.py` | `FakeStore`, `RollingStore`, `TrimStore` in `tests/fakes/store.py` |
| Port of one body | `export_plan/pipeline/port.py` (`ExportPort`) | `FusionPort` in `commands/ExportForParamability/export_flow.py` | `FakePort` in `tests/fakes/port.py` |
| Port of several bodies | `export_plan/pipeline/parts.py` (`PartsPort`) | `FusionPartsPort` in the same `export_flow.py` | `FakePartsPort` |
| Probe | `export_plan/probe_flow/interface.py` (`Probe`) | `SizeProbe`, `ProbeGroup` | none: both real classes are pure |

The test is `tests/test_interfaces.py`. It does these things:

1. It checks that each real class has every declared member: the Fusion store (with the timeline controls), both Fusion
   ports and both probes. It reads the Fusion classes with the Python parser, since they sit beside `adsk` and the test
   cannot import them.
2. It checks the parameters too. The Fusion classes and the shared fakes must match the declared parameters exactly:
   names, kinds and defaults. The probes match by position, and may take extra parameters when each has a default.
   When a call passes a keyword to a probe, that keyword must exist on both probes.
3. It checks that each shared fake has every declared member. The shared fake stores need not have the timeline
   controls, since a store may leave them out.
4. It reads all of `lib/` and `commands/`, except `commands/ExportForParamability/export_flow.py` (the real port), and
   lists every member they ask of a store, a port or a probe. It finds `store.name`, `port.name`,
   `timeline_control(store, "name")`, and also an ask through an alias (`x = self.port`) or through `getattr` and
   `hasattr`. Each member must be declared, and each declared member must be asked for somewhere.
5. For the probe, each declared member is asked for by the runner or by both pipelines.

When you see "missing member" from this test, you have used or added a member in one place and not in the others. The
fix is in 4.12.

#### 4.11.3 The order tests

`tests/test_put_back_order.py` records the calls an export makes to put the design back: the store calls, the reads,
the sketch keeper, the warnings, the log lines and the Undo drop. It notes each call in one list. A batch of try rows
counts as one entry (`rows`). It runs the export once for each way an export can end. For one body these are:

- a clean export, which puts everything back and then drops the last Undo step;
- a sketch put back, an end rebuild and a step left off;
- a step that stays changed, which gets the values again and keeps the Undo data;
- a failed probe, which puts back after its log line;
- a cancel, which puts back and then warns about values, steps and items;
- tries stopped on a broken design;
- a STEP file that fails before the tries.

For several bodies the tests cover a clean export, a cancel, a failed probe and a STEP file that fails. Each test holds the expected list. When a change moves a call, the list differs and the test fails. Read the diff. A
change that is meant to change the order must change the lists in the same commit. A change that is not meant to
change the order, but fails here, moved a put back call by mistake. Use this test to see what a refactor did to the
end of an export.

Two other tests hold a fixed behavior in the same way: `tests/test_probe_row_schedule.py` (the row phases) and
`tests/test_probe_state_record.py` (the `report.json` form of a probe state).

#### 4.11.4 The tolerances file

All the numbers that decide if two reads of the design agree are in one file: `lib/geometry/tolerances.py`. Each value
has a one line comment that says what it compares. The values are separate names even when they are equal, so one can
change without the others.

| Name | Value | Compares |
| --- | --- | --- |
| `SAME_SIZE` | 1e-9 | Two values of one size are the same value (probe rows, kept ranges). |
| `FIT_TOLERANCE` | 1e-4 | A probed value fits a model, or two fits agree (the fit, terms and series, the comparison of states). |
| `POINT_TOLERANCE_MM` | 1e-4 | Two reads of a sketch point or of a reference point are the same point. |
| `BODY_TOLERANCE_MM` | 1e-4 | Two reads of the box of a body agree (the capture and the probe states). |
| `RESTORE_TOLERANCE_MM` | 1e-4 | The sketches after the put back are where they were (`health.sketch_drift`). |
| `FLIP_TOLERANCE` | 0.05 | A followed value may be this far from E0 before the sketch counts as on another solution. |
| `CHAIN_TOL` | 1e-4 | Curve ends closer than this are one point (outlines, loops, paths). |

Use the file when a report looks like noise:

- "A discovery row says a parameter changes the part, but it only moves a point by a tiny amount", or "`sketch_drift`
  is true with a gap of about 0.0001 mm": the cause can be a tolerance that is too tight for the design, or a value
  that is not in this file. First check which name the code uses (`grep -rn "<name>" lib`). Then compare it with the gap
  in the report (`probe.restore_gap_mm`, `health.sketch_gap_mm`).
- A sketch that "stayed on another solution" with a small shift: see `FLIP_TOLERANCE`. Fusion's own restore can leave up
  to about 0.01 degrees on short lines, so the value is 0.05.
- One local constant is not in the file: `POINT_TOLERANCE_MM = 1e-3` in `fusion_reader/placement.py` (the check of a
  frame by three points). It has the same name as the shared one but another value.

A number that decides if two reads agree does not go in a module. It goes in this file (see 4.12).

### 4.12 Adding things

Each of these has one declaration and one or two tests that tell you what you missed. Do the steps in this order. Run
the named test after each.

#### A new member of the parameter store, the port or the probe

1. Declare the member where the interface is declared (the table in 4.11.2):
   - a store member in `ParameterStore` (`design_edit/store.py`), or, when a design without a timeline can go on without
     it, in `TIMELINE_CONTROLS`;
   - a port member in `ExportPort` (`pipeline/port.py`) and `PartsPort` (`pipeline/parts.py`);
   - a probe member in `Probe` (`probe_flow/interface.py`).
2. Write the docstring line of the member in the same place. The docstring says what the caller can count on.
3. Add the member to every real class: `DesignParameterStore` for a store member; `FusionPort` and `FusionPartsPort`
   for a port member; `SizeProbe` and `ProbeGroup` for a probe member.
4. Add it to the shared fakes: `FakeStore` (or `RollingStore` or `TrimStore` for a timeline control) in
   `tests/fakes/store.py`, `FakePort` and `FakePartsPort` in `tests/fakes/port.py`. Give the fake an option for the
   answers a test needs. Do not write a subclass in one test file.
5. Run `python3 -m unittest tests.test_interfaces`. It lists the class or the call site that does not agree. A member
   that you declare but do not use yet also fails it: add the call first, or leave the declaration out.

#### A new tolerance

1. Do not write the number in a module. Put it in `lib/geometry/tolerances.py` with a one line comment that says what it
   compares.
2. Give it its own name, also when the value equals another. One value can then change alone.
3. Import it in the module that needs it (`from ...geometry.tolerances import NAME`). `geometry` imports no other
   package, so every package may import it.

#### A new package, or a new import between packages

1. Add the package to `ALLOWED_IMPORTS` in `tests/test_boundary.py`, at the right layer, with the packages it may
   import. A package needs more than one module.
2. Add it to the code layout in the add-in `README.md` and to the table in 2.1 of this guide.
3. Run `python3 -m unittest tests.test_boundary`.

#### A new step type

Follow `docs/adding-a-step-type.md` in the add-in repository. The short version:

1. Add one entry to the step kind table, `lib/capture_model/step_kinds.py`. A step that writes a new recipe kind also
   needs a `RecipeKind` entry in the same file. Set `finishing` when a missing step of the type only finishes surfaces
   (the `finishing` flag of its gap is then true, 1.10). Set `in_tool` to false, with `tool_words` and `tool_cause`, for
   a recipe kind that must not stand in a tool body (1.9.2). For a type that is not copied, give `unsupported` and, when
   a hint exists, `gap_cause` (1.9.3).
2. Write the reader pair in a `lib/fusion_reader/read_*.py` module and register it in that module's `READERS` dict.
3. Write the handler in the folder of its family under `lib/translator/` (`extrude/`, `finishes/`, `bodies/`, `sweep/`
   and so on). Make a new folder only when no family fits, and let its `__init__.py` docstring say what it holds.
4. Register the handler in `HANDLERS` in `lib/translator/handlers.py`, keyed by the capture type, for example
   `"EmbossFeature": emboss.handle`. Give `unsupported` in the table entry instead while the step cannot be copied. Set
   `repeats_sources` when the step is a pattern or a mirror.
5. Write the tests: a capture fixture, handler tests, and a hand test entry for every new Fusion call.
6. Run `python3 -m unittest tests.test_step_kinds`. It fails when `HANDLERS` registers a type that is not a modeling type of the table,
   when a modeling type has neither a handler nor an `unsupported` reason, when a type name or a list of recipe kinds shows up in another module, and when a reader registers a type that the
   table does not give to that reader module.

## 5. Glossary

The project uses these words in a fixed meaning. The code, the docs, `report.json` and the messages all use them.

| Term | Meaning |
| --- | --- |
| add-in | The Fusion program in `ParamabilityExport/`. Fusion runs it from Scripts and Add-Ins. |
| after_stop | A record in `report.json` when the copy stopped: a second walk without sizes, in which every stop is a gap and there is no cap. It names every step the copy could not hold. |
| Affine | A fitted value `const + sum(a * parameter)`. The probe writes it in the motion file. |
| apart | States where a sketch was solved another way. A different outline there blames no size. |
| assembly (record) | A plane, axis or point of another component brought into the part's coordinates (`assembly: true`). The copy can follow it. |
| audit | The check after the last walk (`audit.py`): every free size a copied step reads must be followed, or marked with a reason. |
| bisect | Halving between the farthest value that built and the nearest that did not, to find the end of a range closely. At most 4 times per side. |
| body measures | The box and volume of the body around each step (`target_before`, `target_after`, `target_changed`, `body_states`). |
| body scope | What of the capture belongs to the picked body (`body_scope.py`). |
| body_states | Per body token, the box and volume of a tool body (or a body the part was split from) around a step. |
| borrowed sketch | A sketch of another component that a step of the part uses. |
| capture | The plain dict of everything the reader read from the design. The only input of the translator. Format number 3. |
| check rows | Probe rows that test a formula with sines or products (`plan.check_rows`). |
| copy (editable copy) | In the app: the recipe built beside the original STEP shape. |
| copy note | In the app: the record that says which shape shows and how far the copy is from the original. |
| cosmetic gap | In the app: a missing round, chamfer, emboss or cosmetic thread. A copy missing only such steps can land shown. |
| cut (range cut) | A free size whose range was made shorter: where Fusion did not rebuild, where a sketch changed its outline, where the part came apart into pieces, where an outline would cross itself or lose a hole, or where a recipe rule stops. The app adds cuts when it opens the file (range end check). Shown as a quiet note. |
| derived (size) | A parameter whose value is a formula of other parameters. In the recipe, `{ expr }`. |
| derived (report) | The shadow check that solves sketch graphs and compares them with the probe. Not used for the recipe. |
| discovery rows | Probe rows that set an unticked parameter of another component once, only to see if the part changes. |
| doubt | A handler's record that a value cannot follow some sizes (`ctx.doubt`). It becomes a loose, fixed or cut size. |
| dropped | A ticked parameter that is not a size of the recipe, with a reason. |
| E0 | The first probe read, with every value as the person left it. Every other state is compared with E0. |
| end check | The check of every timeline step at the end of an export (`settle_timeline`): steps turned back on, a full rebuild, the start values once more. What is left goes to `health.steps_changed`. |
| far rows | Probe rows at the ends of a size's range. |
| favourite | A parameter that the designer starred in Fusion (`is_favorite`). Favourites are ticked first, and their rows run first. |
| Faster tries | A dialog option: turn off timeline items of other components during the tries. On to start with. |
| featureFace, featureEdges | Recipe picks that name an extrude's end face or edges instead of a point, so they follow its sizes. |
| fixed | A ticked size that became a plain number, since a free size would break the recipe (a formula over 300 characters). |
| fixed part | A body of a parts file that is saved as a fixed shape. A size that also moves it is marked loose (`fixed_parts.py`). |
| fixed shape | A part saved as its STEP only (`stepOnly`), with the parameters as variables. |
| flip (solver flip) | A sketch with two solutions that stays on the other one after the values go back. |
| floating join | An extrude join that meets only material of left-out steps. It is left out too, since the copy would be in separate pieces. |
| foreign | A record of an input that belongs to another component and cannot be followed. The step becomes a gap. |
| free (size) | A size of the recipe that the person can change on the form. |
| gap | A step left out of the copy. The recipe is still written. The gap records the reason, the hint, the place and the Fusion data. |
| gap cause | The code of why a step was left out (`taperSteep`, `guideSurface` and so on). It selects the hint. |
| gaps file | `gaps.json`: the list of gaps of a recipe (`paramability.recipeGaps`). Version 1 holds at most 16 gaps, version 2 and 3 at most 256. Version 3 adds the `finishing` flag, and the add-in writes it always. |
| handler | The translator function for one step type: `handle(ctx, step) -> StepResult or Refusal`, where `step` is the resolved step of the item. |
| health | The record of how the design came out of the export (`report.json` `health`). |
| helper geometry | A step that does not touch the exported body. It is skipped. |
| hint (remodel hint) | One sentence per gap that says what to change in Fusion so the step copies. It comes from the gap's cause (`gap_hints.py`). The result window shows it as "Tip: ". |
| item | One timeline entry in the capture: index, name, type, bodies, measures, data. |
| key | The name of one sketch value in the motion file, for example `4/p0/l0/center.0`. |
| label | The readable text of a size on the form (`params/labels.py`): the short comment of the parameter, else its name in words. It is not the Fusion name, which stays in `Entry.label`, the messages and the manifest `parameters` list. |
| left-out preview | The early list, in the export dialog, of the steps that the copy will probably leave out (`dialog_model/left_out_preview.py`). |
| Lighter on memory | A dialog option, an experiment: Fusion forgets the Undo data of the tries. Off to start with. Save the design first. |
| lineage | The chain of splits the picked body comes through (`lineage.py`). Before a split, the walk builds the body that was split. |
| link (geometry link) | A sketch of the part tied to another component (projected, constrained or drawn on its face), or a step that uses a plane or axis of another component. |
| loose (marked) | A free size that some value cannot follow. It stays a size, with a warning and a reason ("may give unexpected results"). |
| marker (timeline marker) | The bar in the Fusion timeline. Fusion builds only the items before it. The export works on the design as it is at the marker. |
| marker roll | Holding the marker earlier during the tries, so each row rebuilds fewer items. |
| motion (motion file) | What the probe found: per key an `Affine`, `Terms` or `Stuck`, plus spans, unmeasured sketches and references. |
| near rows | The first probe rows: each size 25 percent below and above its value. |
| nearer rows | Probe rows nearer to the value, after a row did not build or changed an outline. At most 24 per export. |
| note | A plain remark on a step (`ctx.note`), or a sentence in the manifest `notes`. |
| OPTIMISTIC | The motion of the first translation: write sketch values as numbers and fix nothing for them. |
| outline check | The check that every written outline keeps the rule of the app for sketch loops (`sketch_crossings.simple_ranges`). It cuts ranges where a loop would cross itself or a hole would leave its outline. The checks of one translation share 20 seconds. |
| original | In the app: the STEP shape of the package. |
| package | The `.paramability` zip: manifest, STEP, recipe, gaps, report. |
| parts | The package kind for several bodies. |
| pick | How a round, chamfer, shell or draft names its edges or faces: measured points (`near`), or a feature selector. |
| pieces | The number of separate pieces the part is in at a probe state (`probe/pieces.py`). A try where the part comes apart while it was one piece at E0 counts as a try that did not build. |
| placement | Where the body's component sits in the assembly (`target.placement`). |
| placer, slab | What the translator keeps about each written step so that later picks on its faces can follow sizes. A slab is an extrude. |
| port | The object through which the pipeline reaches Fusion (`FusionPort`, `FusionPartsPort`). Its members are declared in `ExportPort` and `PartsPort`. Tests use a fake (`FakePort`, `FakePartsPort`). |
| probe (size probe) | The part of the export that sets sizes to other values, rebuilds and reads the design, and fits formulas. `SizeProbe` is the probe of one part and `ProbeGroup` the probe of several parts; both have the members of `Probe`. |
| probe state record | `ProbeState` (`probe/state.py`): one probe state as a typed record, with its `report.json` form (`json()`, `from_json()`). |
| put back | Moving the points of a flipped sketch back to E0 and rebuilding once. For the whole export, see `PutBack`. |
| PutBack | The one object per export (`export_plan/pipeline/put_back.py`) that brings the design back on every way the export ends: values, suppressed items, sketches, marker, the end check and the last Undo drop. It also gives the inputs of `health`. |
| range end check | The check that the app makes when it opens a package: it builds each end of each free size range in its own kernel and pulls an end that does not build in to the last value that does. |
| reach | The answer of Fusion about which step made the faces a later step picks. In the capture as `reach`. |
| read | One reading of the design at a probe row (`read_state`). |
| reader | The `(before, after)` functions that read one step type from Fusion. |
| recipe | The JSON list of steps the app builds in its kernel (`paramability.recipe`, version 12 to 16). |
| ref (measured reference) | A record of a plane, axis or point of another component, with its token, so the probe can read it again. |
| refusal | Why the copy stopped (`report.json` `refusal`), or a handler's `Refusal` (usually a gap). |
| row (try) | One experiment of the probe: set some sizes, rebuild, read. At most 64 per export. |
| row schedule | `RowSchedule` (`probe_flow/row_schedule.py`): the row phase of a probe (`NOT_PLANNED`, `NEAR`, `FAR`, `DONE`), the sizes its near rows tried, the nearer rows planned and whether the check rows were planned. |
| size | A ticked user parameter that becomes a recipe size. |
| size table | `SizeTable`: what each user parameter becomes (free, derived, constant, fixed, not offered). |
| sketch graph | The points, curves, dimensions and constraints of a sketch, read as plain data. |
| span | Per probed size: the lowest and highest values that built, and the values that failed. |
| state | One probe reading with the values that were set (`probe.states`). |
| step kind table | `STEP_TYPES` and `RECIPE_KINDS` in `capture_model/step_kinds.py`: the one list of Fusion step types and recipe step kinds. A step type names its reader module. The handlers are in `translator/handlers.py` (`HANDLERS`). |
| stepOnly | The package kind of a fixed shape. |
| stop | The copy ends at a step. No recipe is written; the part is a fixed shape. |
| Stuck | A value no formula fits, with the sizes that move it and a cause (`curve`, `shape`, `turns`, `unread`, `untried`). |
| symmetric pattern | A pattern direction whose copies spread to both sides of the original (3.11). |
| Terms | A fitted value with angle functions or products, such as `L * cos(A)`. |
| time limit | The time that the size tries may take before they stop (the list "Stop the size tries after", 10 minutes to start with). Sizes left without a try are marked. |
| token | Fusion's `entityToken`: the text that names a body, sketch, face or plane. Used to follow and find entities. |
| tolerances | `geometry/tolerances.py`: the numbers that decide if two reads of the design agree (`SAME_SIZE`, `FIT_TOLERANCE`, `POINT_TOLERANCE_MM`, `BODY_TOLERANCE_MM`, `RESTORE_TOLERANCE_MM`, `FLIP_TOLERANCE`, `CHAIN_TOL`). |
| tool body | A body that a Combine joins, cuts or intersects with the part. |
| toolBody (step) | A recipe step (version 15) that holds the steps of a tool body. |
| translator | The pure Python code that turns a capture into a recipe (`lib/translator/`). |
| turn budget | The 100 turns that threads and coils share in one recipe (`translator/turn_budget.py`). |
| up axis | Z up or Y up. The recipe is always Z up; a Y up design is turned. |
| upfront doubt | A size marked before the walk (a joint, sketch text, a size that changes the body in a way the copy does not follow). |
| valueRows | The package kind of "Export size choices": fixed shapes as a dropdown. |
| verdict | The outcome per item: `translated`, `translatedWithNote`, `skipped`, `unsupported`, `leftOut`. |
| walk | One pass of the item loop over the capture. One translation walks many times. |
