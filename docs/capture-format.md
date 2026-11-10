# Capture format

The capture is the plain dict the reader (`lib/fusion_reader/`) returns for one design, and the only input of the
pure translator (`lib/translator/`). Fixtures in `tests/fixtures/captures/` use this format, so every translator test
runs without Fusion. They are written by hand or saved from real designs: the export writes the capture into
`report.json` (section 6). The reader writes capture number 3 and the translator reads only that number: a capture is
made and read in one export run, so no older number is kept. The translator refuses any other number, or a capture
that lacks `capture`, `target` or `items`, with a `CaptureError`.

## 1. Rules for every value

- Lengths in mm (Fusion cm times 10), angles in degrees (Fusion radians times 180 / pi), through
  `lib/package/units.py`. Unitless values stay.
- 3D values are in the coordinates of the target's component (the native body's own frame; for a body in the root
  component these are the design's model coordinates), before any up axis turn. `target.placement` (section 2)
  maps them to the root. Points and vectors are `[x, y, z]` lists.
- 2D sketch values are in the sketch's own frame: `[x, y]` in mm.
- A frame is `{ "origin": [..], "x": [..], "y": [..], "z": [..] }` (unit axes, model frame), read with
  `Matrix3D.getAsCoordinateSystem()`.
- A plane is `{ "point": [..], "normal": [..] }`. An axis is `{ "point": [..], "dir": [..] }` (dir unit).
- A box is `{ "min": [..], "max": [..] }` from `BRepBody.boundingBox` (`minPoint`, `maxPoint`).
- Bodies are named by `BRepBody.entityToken` plus `BRepBody.name`. Two refs name one body when both tokens match; the
  names are compared only when a token is missing. A body with the target's name and another token is not matched:
  the translator refuses ("The body could not be followed through the timeline") rather than guess.
- An entity the reader cannot express becomes `{ "kind": "other", "type": "<objectType>" }`; the translator
  refuses it with a note. The reader never throws for an unknown shape.

## 2. Envelope

```json
{
  "capture": 3,
  "fusion": "2.0.21508",
  "design": "Cable clip",
  "up_axis": "z",
  "design_units": "mm",
  "parameters": { "user": [ PARAMETER, ... ], "model": [ PARAMETER, ... ] },
  "targets": [ TARGET ],
  "target": TARGET,
  "items": [ ITEM, ... ],
  "sketch_links": [ SKETCH LINK, ... ],
  "marker": { "position": 48, "count": 120 }
}
```

`marker` says where the timeline marker was: `position` items sat before it, `count` is the length of the timeline.
`items` holds only the items before the marker; the design is read as it is there. The translator does not read
`marker` (captures without it read as before).

TARGET:

```json
{
  "token": "...", "name": "Body1",
  "box": { "min": [0, 0, 0], "max": [40, 20, 10] }, "volume_mm3": 8000.0,
  "component": { "token": "...", "name": "Tray", "root": false },
  "placement": PLACEMENT
}
```

`target` is the first of `targets` (the same object; a later version lists several bodies there). The token, name, box
and volume are those of the **native** body (component coordinates), not of the occurrence proxy that the person
picked. `component` is the component that owns the body. `placement` is `null` for a body of the root component;
otherwise:

```json
"placement": {
  "path": "Box:1+Tray:2",
  "frame": { "origin": [100, 50, 0], "x": [0, 1, 0], "y": [-1, 0, 0], "z": [0, 0, 1] },
  "source": "transform2",
  "checked_points": 3,
  "uses": 2,
  "linked": false
}
```

- `frame` maps component coordinates to root coordinates (mm, before any up axis turn). `path` is
  `Occurrence.fullPathName`.
- `source` names the candidate that passed (`lib/fusion_reader/placement.py`): `transform2` (the picked occurrence's
  own transform), `path_transform2` (the native occurrence transforms from the top down, multiplied), or the same with
  `transform` for the retired member when `transform2` cannot be read.
- A candidate passes when its frame is a pure rotation plus move (unit, perpendicular, right handed axes within 1e-9;
  no scale or mirror) and up to 3 native vertices (face points when the body has fewer than 3 vertices), mapped by
  it, land on the same vertices of the proxy within 1e-3 mm. `checked_points` is how many were compared.
- `uses` is the number of occurrences of the component in the design; `linked` is true when an occurrence on the path
  comes from a linked design (`Occurrence.isReferencedComponent`).
- When no candidate passes, or the body was not picked through an occurrence, the record is
  `{ "path", "error": "<reason>", "uses", "linked" }` without `frame` and `source`; the export then lands a fixed shape.

`design_units` is the design's default length unit (`fusionUnitsManager.defaultLengthUnits`, `mm` when unreadable); a
bare number in a length formula is read in it. `parameters.user` is `list_user_parameters(design)` and
`parameters.model` is `list_model_parameters(component)` (`lib/fusion_reader/parameters.py`: name, expression, value
in Fusion's internal cm and radians, unit, kind, favourite, dependency lists, and for model parameters `role` and
`created_by` as `{ kind, token, name, sketch, component }`, where `sketch` is the name of the sketch that holds a sketch
dimension (`SketchDimension.parentSketch`) and empty otherwise, and `component` is the token of the component the maker
lives in: the sketch's component for a dimension, else the component the parameter is listed from) for the target's
component, then for each component on its occurrence path up to the root, merged by name (the nearest component wins).
Both are empty lists when unreadable. Each user parameter also has `dependents` (see "Geometry links" below). The
export builds its size table from them
(`lib/params/size_table.py`); the translator reads only `data.params` of the items and, through the size table,
the `created_by` kinds. How a Fusion expression becomes an app formula (operators, `if`, units, functions) is in
`docs/expressions.md`.

`target` is the picked body at the end of the timeline (`volume` cm3 times 1000). `items` lists every timeline
item in order. Group objects are skipped; the children of a group are listed as ordinary items, and the reader raises
when a group lists a child the walk did not reach.

What the translator trusts: `target.token` and `target.name` (to follow the body), `target.placement`, the item fields
in section 5, and the item level `target_box_before` boxes (through all cuts, mirrors). It never reads `target.box` or
`target.volume_mm3`; they are kept for a later geometry check against the rebuilt recipe. In fixtures both are
computed from the capture by `scripts/fixture_geometry.py` (needs numpy; box within one 0.2 mm voxel, volume within
about 0.5 percent). `volume_mm3` is null when the part has steps that script does not model (rounds, chamfers, shells,
tapers, modeled threads, face outlines). A fixture with no geometry in its items (the `core_*` cases and
unreadable ones) keeps a nominal box.

ITEM:

```json
{
  "index": 3,
  "name": "Extrude2",
  "type": "ExtrudeFeature",
  "suppressed": false,
  "health": "ok",
  "message": "",
  "component": "<component token>",
  "in_target_component": true,
  "bodies_after": [{ "token": "...", "name": "Body1" }],
  "target_changed": true,
  "data": { }
}
```

- `type`: the part of `entity.objectType` after the last `::` (`adsk::fusion::ExtrudeFeature` gives
  `ExtrudeFeature`). Items without an entity: `"type": "none"`.
- `health`: from `TimelineObject.healthState` (`ok`, `warning`, `error`); `message` from
  `errorOrWarningMessage`.
- `component`: the token of the component the item lives in (read on the native entity; empty when unreadable): the
  `parentComponent` of a feature or sketch, the `component` of construction geometry, and for an `Occurrence` the
  component it sits in (the `component` of its `assemblyContext`, else its `sourceComponent`; its own `component` is
  the one it shows). `in_target_component`: that component is the target's component, compared as Fusion objects and
  not by token text. When the component cannot be read it is true for a feature (so the translator still refuses a
  feature of the target it cannot read) and false for the items that are not modeling steps (sketches, construction
  geometry, occurrences, joints and the like: the roles `sketch` and `assembly` in the step kind table,
  `lib/translator/step_kinds.py`). Feature readers run only for items in the target's component; the other items
  keep `"data": {}` with their `bodies_after`, health and message.
- `entity_context`: `"proxy"` only when `TimelineObject.entity` came as an occurrence proxy and was turned native
  (`nativeObject`) before reading; absent otherwise.
- `bodies_before` (not for suppressed items): the bodies of the target's component at the marker before the item.
- `target_changed`: whether the native target's box (1e-4 mm) or volume changed from the marker before the item to the
  marker after it. `true` also when the target appears or disappears; `null` when it exists on neither side or a
  measure could not be read. The translator uses `false` to skip a step it has no handler for (see "Parameters behind values" in section 5).
- `bodies_after`: `feature.bodies` read with the marker just after the item. `null` (with an item level
  `"read_error": "bodies: ..."`) when the bodies cannot be read; it is not the same as `[]`, which says the item
  makes no body. The driver must not treat `null` as helper geometry. Items that are not modeling steps get `[]`
  without a read. The translator skips them whatever their bodies say (captures of add-in 0.3.1 have `null` there);
  an occurrence, joint or the like that changes the target is refused.
- `data`: per type, below. Types without a reader (sketches, construction geometry, unknown features) carry
  `"data": {}`. When a reader fails, `data` is `{ "read_error": "<message>" }`.
- A member that cannot be read never becomes a plausible value: it reads as `null` or as an `other` entry
  (`"extent_type": "other"`, `"hole_type": "other"`, `{ "kind": "other" }`), and the translator refuses it.

### Geometry links (`sketch_links`, `dependents`, `sketch_inputs`)

A sketch of the target can follow another component without any parameter of its own: a circle projected from a
pipe in another component, an arc constrained to such a projection, a sketch drawn on a face of another component.
`lib/fusion_reader/read_links.py` reads, with the marker back at its start position, every sketch whose
`sketch_token` a record of an item in the target's component names (records marked `foreign` are skipped):

```json
{ "sketch": "PipeHole", "token": "...", "unknown": 0,
  "links": [{ "token": "...", "name": "Pipe", "references": 2, "constrained": 1, "plane": false,
              "bodies": [{ "token": "...", "name": "Pipe body" }], "sketches": [] }] }
```

- `links`: one entry per component other than the target's that the sketch is tied to. `references` counts the
  reference entities of the sketch (`Sketch.sketchCurves` and `sketchPoints` with `SketchEntity.isReference`) whose
  `referencedEntity` belongs to it: the component of the occurrence it is seen through (`assemblyContext.component`),
  else its own (`component_of`, through `nativeObject` when there is one). `constrained` counts the geometric
  constraints (`Sketch.geometricConstraints`) that tie such a reference to an entity that is not a reference
  (members `point`, `entity`, `entityOne`, `entityTwo`, `curveOne`, `curveTwo`, `lineOne`, `lineTwo`, `line`,
  `curve`). `plane` is true when the sketch lies on a face or plane of that component (`Sketch.referencePlane`).
- `bodies` and `sketches`: what the references point at, by the token and name of the native object: the `body` of
  a referenced edge, face or vertex, the `parentSketch` of a referenced sketch curve or point.
- `unknown` counts reference entities whose `referencedEntity` is null (a reference that is not parametric).
- A sketch that cannot be found by its token (`Design.findEntityByToken`) or read is `{ sketch, token, error }`.
- At most 200 sketches, 5000 entities and 5000 constraints per sketch are read.

Each item that is not a sketch, of any component, has `sketch_inputs` when it takes outlines, a path or points from
sketches: `[{ token, name }]` of each `parentSketch` of its `profile` and `profiles` (a profile, a sketch text or an
ObjectCollection of them; a planar face adds nothing), of the `PathEntity.entity` items of its `path` and
`guideRail`, of the `LoftSection.entity` of its `loftSections`, and of the sketch points of a hole
(`holePositionDefinition.sketchPoints`). It is read with the marker before the item and reads no geometry. The key
is left out when nothing is found.

Each user parameter has `dependents`: one record per model parameter that reads it, directly or through other
parameters that read it (`dependentParameters`, walked transitively, at most 2000 visits; user parameters on the way
are walked but not listed):

```json
{ "name": "d26", "kind": "sketchDimension", "component": "<token>", "sketch": "Top_thick", "sketch_token": "..." }
{ "name": "d30", "kind": "feature", "component": "<token>", "feature": "Extrude8" }
```

`kind` is the maker kind of `created_by` (section 2), read from `ModelParameter.createdBy` (made native when it comes
through an occurrence). `component` is the token of the maker's component: `parentSketch.parentComponent` for a
sketch dimension or text, `component_of` of the feature or construction geometry; `ModelParameter.component` only
when the maker gives none (in a real design Fusion answered the root component there for every parameter). A maker
that cannot be read gives `{ name, kind: "other", component: "" }`. The model parameters of other components are not
listed in `parameters.model`; these records are all the capture keeps of them.

Where a user parameter acts (`lib/params/geometry_links.py`, `acts`): the component of each dependent; for a sketch
dimension, every item whose `sketch_inputs` names that sketch (by token, else by name in the same component) and that
item's component; for a feature value, the item of that name in that component. A user parameter may reach the
target through a link (`reach`), in this order:

1. `via: "sketch"`: the link's `sketches` names a sketch one of its dimensions sits on;
2. `via: "body"`: when the link's `bodies` name a body that items before the target's sketch made or changed
   (`bodies_after`), one of those items is one it drives; when such items exist and it drives none of them, it has
   no link through that component;
3. `via: "component"`: otherwise, when the link's component is one it acts on.

Tokens are compared, names only when a token is missing. The export works with the sketches the picked body's own
steps use (`body_scope.body_links`), and the translator, given a size table without links, takes them from the whole
capture. A link is `{ "param", "sketch", "component", "via" }` (the component's name). Such a parameter is ticked to
start with like one the body reads, the size probe tries it like a size behind a sketch dimension, and the translator
counts it as a size the sketch reads (`sizes.sketch_sizes`, section 5). The link only makes it worth trying; the
probe decides.

A step can also use a plane, axis, direction or point of another component directly (measured references, "Measured
references", section 4). A user parameter that acts on the component that owns such a reference (not an `origin`
plane or axis) gets a link `{ "param", "sketch": "", "component", "via": "reference", "step", "ref" }` once per
component (`reference_links`; `step` is the step's name, `ref` the key of the first reference). It is offered, ticked
to start with and probed like a sketch link; the offer text says which step uses which component.

When a sketch of the body is tied to another component (a link, or only `unknown` references), or a step of the body
uses a reference of another component, the user parameters that act on a component other than the target's
(`outside`: the ones acting on a tied or referenced component first, then the rest, each in parameter order) are
candidates for discovery tries ("Probe states", section 5). A try also counts as moving the part when a measured
reference moved.

## 3. Walk and marker

`lib/fusion_reader/capture.py`, `read_capture(design, body) -> dict`:

1. Read the start marker `end = timeline.markerPosition` (`timeline.count` when the marker is at the end). The walk
   treats it as the end of the timeline: items at `end` and after are left out, never refused.
2. For `k` from 0 to `end`: set `timeline.markerPosition = k`. Read the target's box and volume once. Read
   `bodies_after` and `target_changed` of item `k - 1` and, for items of the target's component, the inputs of item `k`
   (profiles, edges, faces, tool bodies, the target box before it). One recompute per item.
3. `finally`: put the marker back at `end` (`moveToEnd` when `end == count`, else `markerPosition = end`), then
   check it reads `end`; else `MarkerError`. After that, each `timeline.timelineGroups` entry that starts before
   `end` must be covered by the walk up to `end`; else `read_capture` raises `CaptureReadError` and the export lands
   as a fixed shape.
4. The STEP file is written before the capture, with the marker at `end`. The sketch tries keep it there: the
   parameter store puts the marker back after every recompute and counts only the items before it for health
   (`lib/fusion_reader/rows.py`), and the temporary copy of a component body deletes only what it added
   (`lib/design_edit/temp_copy.py`). `report.json` records `marker` (`position`, `count`).

Reading inputs at the position before the item covers the getters that the reference says need
`timelineObject.rollTo(True)` (fillet `edges`, chamfer `edges`, extrude and revolve `profile`, `participantBodies`).

## 4. Sketch profiles (inside extrude and revolve data)

```json
"profiles": [
  {
    "sketch": "Sketch1",
    "frame": { "origin": [0, 0, 5], "x": [1, 0, 0], "y": [0, 1, 0], "z": [0, 0, 1] },
    "space": "sketch",
    "loops": [
      { "outer": true, "curves": [ CURVE, ... ] },
      { "outer": false, "curves": [ CURVE, ... ] }
    ]
  },
  { "face": true, "type": "BRepFace" },
  { "text": true, "sketch": "Sketch2", "sketch_token": "...", "frame": { ... }, "space": "sketch", "loops": [ ... ] },
  { "text": true, "sketch": "Sketch2", "sketch_token": "...", "problem": "open" }
]
```

Optional keys that let the size probe find the sketch again (section 5, "Probe states"): `sketch_token`
(`Sketch.entityToken`) and `reference` (`{ "kind": "constructionPlane" | "face" | "plane" | "other", "token" }` from
`Sketch.referencePlane`; `token` is empty for a plane without one). Each curve also gets `entity`, the token of its
sketch curve (`ProfileCurve.sketchEntity.entityToken`). A key is left out when Fusion does not give it.

From `Profile.parentSketch.transform`, `Profile.profileLoops`, `ProfileLoop.isOuter`, `ProfileLoop.profileCurves`,
`ProfileCurve.geometry` and `ProfileCurve.geometryType`. A planar face used as a profile is `{ "face": true }` and a
A `SketchText` is read from `SketchText.asCurves()` (transient curves; the text and the design are not changed): the
curves are chained into closed loops, and each loop is an outer outline or a hole by how many loops contain it (even
count: outer, odd: hole of the nearest loop around it). Each outer outline with its holes is one profile record like
the one above, plus `"text": true` and no curve `entity`: a text of "OI" with a hole in the "O" is two records. The
space of the points (sketch or model) is decided like for other profiles, except that the curves have no sketch entity:
the points are compared with `SketchText.boundingBox` (sketch space) and the record is a marker when both readings
fit or neither does. Every text record, outline or marker, carries `text_params` (the name of the text's height
parameter, `SketchText.heightParameter`) or `text_params_unknown: true` when Fusion does not give the name; the sizes
behind them are kept from following the copied letters. A text that cannot be turned into profiles is one record with
`text`, `sketch`, `sketch_token` and a `problem`: `unread` (no curves), `open` (the curves do not close), `overlap`
(two loops cross, as in a script font whose strokes overlap, so holes cannot be told from strokes), `space`,
`too_many` (over 4000 curves or 400 outlines) or `foreign` (a text of another component). The translator refuses a marker with its own reason
(`loops.TEXT_PROBLEMS`), and every size that moves the sketch of a text stays loose or is left out, since the size
probe does not follow it.

`space` says how the curve space was decided: `sketch` or `model` (the reader mapped model space curves into sketch
2D) or `ambiguous`. A curve off the plane z = 0 proves model space. Points all at z = 0 that do not lie on one line
prove sketch space when the sketch plane is not the plane z = 0 (model points on such a plane cannot all have
z = 0). In the plane z = 0 with a sketch frame other than the identity, the reader compares the curve with
`ProfileCurve.sketchEntity`; if that cannot decide it writes `ambiguous` and the translator refuses the profile. A
loop whose chained curves enclose no area is refused.

A profile of another component's sketch (Fusion hands it over through that component's occurrence) is read from its
`nativeObject`, so `loops` are in that sketch's own 2D frame, and it keeps `"foreign": true`. It adds:

- `native_frame`: the sketch frame in its own component's coordinates;
- `frame`: the same frame brought into the target's coordinates through the assembly (that component's `placement`,
  then the inverse of the target's), only when both places can be read;
- `component`: `{ token, name }` of the sketch's component;
- `placement`: like the target's placement (section 2), read for the occurrence the profile came through. Its point
  check compares `SketchPoint.worldGeometry` of up to three native sketch points with the same points made for the
  occurrence (`SketchPoint.createForAssemblyContext`). Without a match it holds `error` and no `frame`;
- `sketch_params`: one `{ name, expression, reads }` per sketch dimension (`Sketch.sketchDimensions`,
  `SketchDimension.parameter`), where `reads` lists every parameter it reads, directly or through others
  (`dependencyParameters`).

The translator copies such a profile like its own when `frame`, `native_frame` and `placement.frame` are present
(`lib/translator/borrowed.py`). The size probe reads the sketch at every state (section 5, "Probe states"), so the
outline follows the sizes through the motion file under the usual keys (`<item>/p<profile>/...`). Where the motion
holds no value for the profile, the outline is written as numbers and every size that `sketch_params` read becomes a
fixed number; the first translation of an export (no sizes fixed for sketches) skips that. The step gets a note that
names the sketch and its component. Without the frames and the place the step is refused as before.

Nothing ties such a step to the walls of the part, so it must keep meeting the part as measured
(`lib/translator/meets_part.py`): along the normal of each of its faces, the nearest flat parallel faces of the part
within 2 mm keep their side of the face at every size setting of the range (every mix of the ends for up to 6
sizes, a bounded sample past that), and a face that lies on a wall stays on it. Where a gap would close or open, the sizes it reads stay free over
their ranges and are listed in `loose`, with the values past which the step may stop meeting the part ("past 2.05",
"below 0.98"). Those values come from `lib/translator/kept_ranges.py`, which finds, without changing any range, the
values up to which the gaps keep their side (each size alone first, then all together); when that value would be the
size's own value or the person typed the range, no value is given and the size cannot follow (`Context.doubt`, listed
in `loose` without one).

CURVE, in sketch 2D mm, in the order Fusion lists them (not chained, not oriented):

| Fusion geometry | Dict |
|---|---|
| `Line3D` (`startPoint`, `endPoint`) | `{ "kind": "line", "start": [x, y], "end": [x, y] }` |
| `Arc3D` (`center`, `radius`, `startPoint`, `endPoint`) | `{ "kind": "arc", "start", "end", "mid", "center", "radius" }`; `mid` from the evaluator at the middle parameter |
| `Circle3D` (`center`, `radius`) | `{ "kind": "circle", "center", "radius" }` |
| `Ellipse3D` (`center`, `majorAxis`, `majorRadius`, `minorRadius`) | `{ "kind": "ellipse", "center", "major_dir": [x, y], "major_radius", "minor_radius" }` |
| `EllipticalArc3D`, `NurbsCurve3D`, other | `{ "kind": "other", "type": "NurbsCurve3D", "start", "end", "mid", "samples": [[x, y], ...], "tangent_start", "tangent_end" }` |

A free curve is read as a dense polyline: 16 equal parameter spans, each split at its middle parameter until the middle
point lies within 0.0005 mm of the chord, at most 800 points (`truncated: true` when the cap stopped the splitting or
when the chords do not add up to the curve's own length, and the translator then refuses the curve). `start`, `end` and `mid` are samples. `tangent_start` and `tangent_end` are unit
directions of the curve at its ends (`CurveEvaluator3D.getTangent`), left out when they cannot be read; the recipe's
spline segment has no tangent field, so they are for checks only. A curve that cannot be evaluated has `samples: []`.
The translator fits the app's spline through points chosen from the samples (`lib/translator/spline_fit.py`, tolerance
0.005 mm between the points, also where the curve runs between two samples, at most 64 points inside one segment, split into several segments past that, at most 1000 points in a loop).

## 5. Feature data

**ExtrudeFeature** (`operation`, `profile`, `extentType`, `hasTwoExtents`, `extentOne`, `extentTwo`,
`symmetricExtent`, `startExtent`, `taperAngleOne`, `taperAngleTwo`, `isThinExtrude`, `participantBodies`,
`endFaces`):

```json
{
  "operation": "join",
  "profiles": [ ... ],
  "start": { "kind": "profilePlane" },
  "extent_type": "one",
  "side_one": EXTENT,
  "side_two": null,
  "symmetric": null,
  "thin": false,
  "participants": [{ "token": "...", "name": "Body1" }],
  "target_box_before": { "min": [..], "max": [..] },
  "end_offset": 10.0
}
```

- `operation`: `join`, `cut`, `intersect`, `newBody`, `newComponent` (from `FeatureOperations`). A new body from
  several profiles is copied only when `bodies_after` lists one body (the profiles touch).
- `start`: `{ "kind": "profilePlane" }`, `{ "kind": "offset", "offset": mm }` (`OffsetStartDefinition.offset`),
  `{ "kind": "fromEntity", "plane": PLANE or null, "entity_type": "...", "face_point": [..] }`
  (`FromEntityStartDefinition`, TARGET below).
- `extent_type`: `one`, `two`, `symmetric`.
- EXTENT: `{ "kind": "distance", "distance": mm, "taper_deg": d }` (`DistanceExtentDefinition.distance`, the value
  as Fusion stores it, sign kept), `{ "kind": "throughAll", "positive": bool, "taper_deg": d }`
  (`ThroughAllExtentDefinition.isPositiveDirection`), `{ "kind": "all" }`, `{ "kind": "toEntity", "plane": PLANE or
  null, "offset": mm, "entity_type": "...", "face_point": [..] }` (TARGET below), `{ "kind": "other", "type": "..." }`.
- TARGET (the face or plane of a from or to entity): `plane` from the entity's `geometry` (its origin need not lie on
  the face), `entity_type` the entity's type name (`BRepFace`, `ConstructionPlane`, or null), and for a face
  `face_point` (`BRepFace.pointOnFace`). Both keys are optional; without `face_point` the translator cannot tell
  whether the face moves with sizes. For a `ConstructionPlane` or `ConstructionAxis` the record also has `token`
  (`entityToken`), which names the model parameters behind it (`created_by.token`).
- `symmetric`: `{ "distance": mm, "full_length": bool, "taper_deg": d }`
  (`SymmetricExtentDefinition.distance`, `isFullLength`, `taperAngle`).
- `target_box_before`: the target body's box with the marker before the item, or null when it does not exist yet.
- `end_offset`: signed distance along the first profile's sketch `z` from its sketch plane to
  `endFaces[0].pointOnFace`, or null. The measured check of the direction and, for one side, symmetric (half
  length) and two sided extrudes, of the length: the translator refuses when `abs(end_offset - start shift)` is not
  the planned length within 1e-3 mm. A one sided cut that ends past the whole `target_box_before` makes no end face
  of its own, so a nearer measured end is not checked there. A two sided extrude has faces on both sides of its
  sketch, so the measured face turns its direction only when it lies out of reach of the stored one.
- `side_leans` (optional): per face of `ExtrudeFeature.sideFaces` (at most 256), the outward normal at
  `pointOnFace` along the first profile's sketch `z`, which is the sine of how far that wall leans. The taper check:
  a wall that narrows away from the sketch leans its outward normal along the travel; a cut lists the part's walls,
  which face the other way. Every measured wall must match a side of the plan (within 1e-4), and each tapered side
  must have a wall that shows it, else the translator refuses.
- `thin_wall` (only when `thin` is true): `{ "location", "thickness", "location_two", "thickness_two",
  "profile_type" }` from `thinExtrudeWallLocationOne` and `thinExtrudeWallLocationTwo` (`ThinExtrudeWallLocation`:
  `side1`, `side2`, `center`, else `other`; null when unreadable), `thinExtrudeWallThicknessOne` and
  `thinExtrudeWallThicknessTwo` (mm, null when unreadable) and the type name of `ExtrudeFeature.profile` (an open
  line shows here and as `{ "kind": "other", "type": ... }` in `profiles`). The thickness of side one also names its
  parameter as `params["thin.thickness"]`. The translator copies one closed outline without holes, one way or
  symmetric, without a taper. Side one and side two are not taken for inside and outside (the API does not say):
  `end_area`, the area of the wall's end face, is compared with the expected area of each side of the outline,
  worked out from its lengths and corners, and decides the side. The area is used rather than the volume change
  because a wall that joins or cuts an existing part overlaps it, while the end face stays the wall's cross section.
- `profile_area`, `end_area` (optional, mm2): the area of the first profile and of `endFaces[0]`. Without
  `side_leans`, a tapered extrude of one outline is checked by them (the end face must be smaller for a positive
  recipe taper); a tapered extrude of several outlines is refused. Fusion's positive taper widens the walls (the
  recipe's positive `taperDeg` narrows them), so the translator writes Fusion's angle with the other sign.
- `areas`, `volume_before`, `volume_after` (only when the outlines hold sketch text or a free curve): `areas` as for an
  emboss (one entry per profile record; the area the reader worked out for text, `Profile.areaProperties` for a
  spline), and the volume in mm3 the part had before and after the item: the target's, or for a new body 0 and the
  summed volume of `ExtrudeFeature.bodies`. The translator expects a new body to have exactly the outline area times
  the length; a join or cut may lose volume to material it overlaps, so it only refuses a change larger than that or in
  the wrong direction. A taper, through all, thin and intersect are not checked. A capture without these keys (made
  before they were read) is not checked.
- Profiles of one extrude that share a sketch curve are merged into one outline with holes before they are copied
  (`lib/translator/outlines.py`), since Fusion extrudes and tapers their whole region at once. Outlines that stay
  apart are written so that each step touches what is already built (the part, or an outline written before it).
- `bodies_before` (optional, on any item): root bodies at the marker before the item. With it the driver finds a
  body the item made or split off (refused); without it the driver compares `bodies_after` with the bodies the item's
  data names (`participants`, `tools`, `target`).

**RevolveFeature** (`operation`, `profile`, `axis`, `isProjectAxis`, `extentDefinition`, `startFaces`):

```json
{
  "operation": "newBody",
  "profiles": [ ... ],
  "axis": { "point": [..], "dir": [..] },
  "project_axis": false,
  "extent": { "kind": "angle", "angle_deg": 360, "symmetric": false },
  "participants": [ ... ],
  "start_face_normal": null
}
```

- `axis` from a `SketchLine` (`worldGeometry`), a `ConstructionAxis` (`geometry`, an `InfiniteLine3D`), a linear
  `BRepEdge` (`geometry`, a `Line3D`) or a cylindrical `BRepFace` (`geometry`, a `Cylinder`); else `{ "kind":
  "other" }`. An axis from a sketch line also has `entity` (the line's token), `sketch_token` and `sketch` (the
  sketch's token and name); one from a construction axis has `token`. Circular pattern axes are read the same way.
- `extent`: `{ "kind": "angle", "angle_deg", "symmetric" }` (`AngleExtentDefinition.angle`, `isSymmetric`),
  `{ "kind": "twoSidesAngle", "angle_one_deg", "angle_two_deg" }`, `{ "kind": "other", "type" }`.
- `start_face_normal`: outward normal of `startFaces[0]` at its `pointOnFace` (surface evaluator), or null for a
  full turn. The measured check of the turning sense.

**HoleFeature** (`holeType`, `holeTapType`, `holeDiameter`, `tipAngle`, `counterboreDiameter`, `counterboreDepth`,
`countersinkDiameter`, `countersinkAngle`, `position`, `direction`, `extentDefinition`, `holePositionDefinition`,
`sideFaces`, `endFaces`, `thread`):

```json
{
  "hole_type": "simple",
  "tap_type": "simple",
  "thread_modeled": null,
  "diameter": 5.0,
  "tip_angle_deg": 118,
  "counterbore": null,
  "countersink": null,
  "direction": [0, 0, -1],
  "positions": [[10, 10, 10]],
  "extent": { "kind": "distance", "depth": 8.0 },
  "side_cylinders": [{ "origin": [..], "axis": [..], "radius": 2.5 }],
  "end_points": [[10, 10, 2.0]],
  "end_face_types": ["cone"],
  "participants": [ ... ]
}
```

- `hole_type`: `simple`, `counterbore`, `countersink`. `tap_type`: `simple`, `clearance`, `tapped`,
  `taperTapped`. `thread_modeled`: `thread.isModeled` for a tapped hole, else null.
- `counterbore`: `{ "diameter", "depth" }`; `countersink`: `{ "diameter", "angle_deg" }`.
- `positions`: one point per `SketchPointsHolePositionDefinition.sketchPoints` item (`worldGeometry`), else
  `[position]`. Points of another component's sketch are brought into the target's coordinates; such a hole gets
  `position_refs` (one measured reference per point, slot `positions.<n>`) and no `sketch_token`, `sketch` or
  `point_tokens`, so the size probe leaves the sketch alone. When a point cannot be brought in, the hole is marked
  `foreign`. A hole placed on a face, plane or edge of another component (the `planarEntity`, `edge`, `face` and similar
  members of the position definition) is marked `foreign` and carries `position_refs` too.
- `sketch_token`, `sketch` (optional): token and name of the sketch of the first sketch point.
  `point_tokens` (optional): `entityToken` of each sketch point, same order as `positions`; absent when a token is
  missing or the points sit on more than one sketch.
- `extent`: `{ "kind": "distance", "depth" }`, `{ "kind": "throughAll" }` (also for the `All` kind), `{ "kind":
  "toEntity" }`, `{ "kind": "other" }`.
- `side_cylinders`: every `sideFaces` item whose geometry is a `Cylinder` (`origin`, `axis`, `radius`).
  `end_points`: `pointOnFace` of each `endFaces` item. `end_face_types`: the geometry type of each of those faces
  (`"plane"` or `"cone"`; `null` when the type is another one or cannot be read), one per `end_points` entry; a flat or
  tipped bottom is decided from it, not from `tip_angle_deg`. Measured checks of direction, count and diameter.

**FilletFeature** (`edgeSets`, `isRollingBallCorner`):

```json
{
  "rolling_ball": true,
  "sets": [
    {
      "kind": "constant",
      "radius": 2.0,
      "continuity": "tangent",
      "input_kinds": ["edge"],
      "tangent_chain": true,
      "edges": [EDGE, ...],
      "faces": [{ "token": "...", "point": [..] }]
    }
  ]
}
```

- `kind`: `constant` (`ConstantRadiusFilletEdgeSet`: `radius`, `edges`, `isTangentChain`, `continuity`),
  `variable`, `chordLength`, `asymmetric`, `other`.
- The reader expands the input: a face gives its `BRepFace.edges`; a tangent chain gives
  `BRepEdge.tangentiallyConnectedEdges`. A feature as input is listed in `input_kinds` as `feature` and not
  expanded.
- How the set picked its edges: `tangent_chain` is `isTangentChain`; with it on, each EDGE that was an input of the
  set (not one the chain added) has `"seed": true`. `faces` lists the face inputs, as the shell's `faces` records
  (`point` is `BRepFace.pointOnFace`); it is absent when the set has no face input or a face cannot be read. Captures
  of add-in 0.5.0 and older have none of these keys.
- EDGE: `{ "token", "closed": bool, "points": [[..]] }`. `points` holds the middle point for an open edge and the
  points at 0.25 and 0.75 of the parameter range for a closed edge (`startVertex` equal to `endVertex`), from
  `BRepEdge.evaluator`.

**ChamferFeature** (`edgeSets`, `cornerType`):

```json
{ "corner_type": "chamfer", "sets": [{ "kind": "equal", "distance": 1.0, "edges": [EDGE, ...] }] }
```

`kind`: `equal` (`EqualDistanceChamferEdgeSet.distance`), `twoDistances` (`distanceOne`, `distanceTwo`,
`isFlipped`, as `distance`, `distance_two`, `flipped`), `distanceAngle` (`distance`, `angle`, `isFlipped`, as
`distance`, `angle_deg`, `flipped`), `other`. Edges expanded as for fillets.

The API does not say which face of an edge takes the first distance (`isFlipped` only swaps them, and is reported
as unreliable). For `twoDistances` and `distanceAngle` sets each EDGE also gets, per point in `points`:

- `sides` (before the item): `[[a], [b]]`, the outward normals of the edge's two faces (`BRepEdge.faces`,
  `SurfaceEvaluator.getNormalAtPoint`) at the point;
- `cut_normals` (after the item): the normal of the chamfer face nearest to the point (`ChamferFeature.faces`;
  `getParameterAtPoint`, `getPointAtParameter`, `isParameterOnFace`, `getNormalAtParameter`), a face whose nearest
  point lies on it first.

The chamfer face normal is `d1 * a + d2 * b` (normalized) when `d1` lies on face `a` and `d2` on face `b`, for any
angle between the faces, so the ratio of its two weights names the face of the first distance (for a distance and
an angle, the second distance is taken as `distance * tan(angle)`). An edge without these keys, or whose weights fit
neither way, refuses an uneven chamfer.

**ShellFeature** (`inputEntities`, `insideThickness`, `outsideThickness`, `isTangentChain`, `shellType`):

```json
{ "faces": [{ "token": "...", "point": [..] }], "bodies_input": false, "inside": 2.0, "outside": 0.0, "shell_type": "sharp" }
```

`faces[].point` is `BRepFace.pointOnFace`; tangent chains expanded with `tangentiallyConnectedFaces`;
`bodies_input` true when the input is a body (a closed hollow). `shell_type`: `sharp` or `rounded`.

**RectangularPatternFeature** (`patternEntityType`, `inputEntities`, `directionOne`, `directionTwo`,
`quantityOne`, `quantityTwo`, `distanceOne`, `distanceTwo`, `patternDistanceType`, `isSymmetricInDirectionOne`,
`isSymmetricInDirectionTwo`, `patternElements`, `suppressedElementsIds`):

```json
{
  "entity_type": "features",
  "sources": [4, 5],
  "direction_one": [1, 0, 0], "quantity_one": 3, "distance_one": 20.0,
  "direction_two": null, "quantity_two": 1, "distance_two": 0.0,
  "distance_type": "spacing",
  "symmetric_one": false, "symmetric_two": false,
  "elements": [{ "id": 1, "suppressed": false, "frame": FRAME }, ...],
  "suppressed_ids": []
}
```

- `entity_type`: `features`, `faces`, `bodies`, `occurrences`. `sources`: `timelineObject.index` of each input
  feature.
- `distance_type`: `spacing` or `extent` (enum `PatternDistanceType`), `other` when unreadable. The translator then
  takes the kind whose grid holds every kept element.
- `elements`: every `PatternElement` (`id`, `isSuppressed`, `transform` as a frame; the first is the identity).
- `direction_one_sketch`, `direction_two_sketch` (optional): `{ "sketch_token", "sketch" }` when that direction is a
  sketch line, so the sketch is known to feed a pattern.
- `direction_one_place`, `direction_two_place` (optional): a direction taken from an axis, edge or face of another
  component. The entity is seen in the root's coordinates, so its direction is turned into the target's
  (`direction_one` holds the result) and the place is `{ "assembly": true, "dir": [..], "ref": REF }` (slot
  `direction_one` or `direction_two`, see "Measured references"). When the direction cannot be brought in, `direction_*`
  is null and the place is `{ "foreign": true, "ref": REF }`, so the pattern is refused. The sketch of a foreign sketch
  line is not named in `direction_*_sketch`.

**CircularPatternFeature** (`inputEntities`, `axis`, `quantity`, `totalAngle`, `isSymmetric`, `patternElements`,
`suppressedElementsIds`):

```json
{ "entity_type": "features", "sources": [4], "axis": AXIS, "quantity": 6, "total_angle_deg": 360, "symmetric": false, "elements": [...], "suppressed_ids": [] }
```

**MirrorFeature** (`inputEntities`, `mirrorPlane`, `isCombine`):

```json
{ "entity_type": "features", "sources": [4], "plane": PLANE, "combine": false, "target_box_before": { "min": [..], "max": [..] } }
```

The mirror `plane` and the circular pattern `axis` also say what they are, so the translator can tell whether sizes move
them (`lib/fusion_reader/read_reference.py`). All keys below are optional and are added next to the plane or axis keys
(`point`, `normal` or `dir`, `token`); a record of another component gets none.

- `origin`: true for an origin plane or axis of the component. Nothing else is read then; it never moves.
- `entity_type`: the type name of the picked entity (`BRepFace`, `BRepEdge`, `ConstructionPlane`, `ConstructionAxis`).
- `face_point` and `surface` (`Plane`, `Cylinder`, ...) of a face; `edge_points` of an edge.
- Construction geometry also has `token`, `made_by` (the timeline index of the feature that made it), `definition` (the
  type name of how it is defined) and `built_on`, a list of the same descriptions for the entities that definition
  names (own component only, up to three levels deep).

A reader that cannot read one of these leaves it out, and the plane or axis then stays where it was measured.

`target_box_before`: the target body's box with the marker before the item, or null when it does not exist yet (as
for extrudes).

`plane` from a `ConstructionPlane` (`geometry`, a `Plane`: `origin`, `normal`) or a planar `BRepFace`
(`geometry`). A construction plane adds `token`.

**CombineFeature** (`targetBody`, `toolBodies`, `operation`, `isKeepToolBodies`):

```json
{ "target": BODY, "tools": [BODY, ...], "operation": "cut", "keep_tools": false }
```

Optional `volume_before` and `volume_after` (mm3) hold the volume of the target with the marker before and after the
Combine (`read_geometry.target_volume`; null when it cannot be read). When both are present the translator refuses a Combine that changes the part by more than its tool steps can
fill (`combine_volume.py`).

The translator copies a Combine when every tool body is built, in the target's component, by steps that only add
material to it (`combine.adds_only`): `ExtrudeFeature` and `RevolveFeature` items whose recipe steps are `new` for the
first and `add` for the rest. Each such step is written at the Combine's place with the Combine's operation. An
intersect takes a tool of one step. A tool step that starts from or reaches to a face (`fromEntity`, `toEntity`) is
refused when the tool has more than one step. Any other item that touches the tool body before the Combine (a cut, a
round, a chamfer, a hole, a pattern, a step the walk could not copy) refuses the Combine, naming that item.

**ThreadFeature**: `{ "modeled": bool }` (`isModeled`).

**OffsetFacesFeature** (press pull; `inputFaces` (a list or a collection), else `faces`, read before the item;
`distance`; `faces` after it. When no face is readable before the item, `faces` holds the flat faces of
`feature.faces` read after it, moved back by `distance`):

```json
{
  "distance": 2.0,
  "faces": [
    { "token": "...", "frame": FRAME, "space": "sketch", "loops": [LOOP, ...], "sides": "square", "meets_offset": false }
  ],
  "faces_after": [{ "point": [x, y, z], "normal": [x, y, z] }]
}
```

- `distance`: mm, positive along the outward face normal.
- `faces[]`: a flat face as a profile record (section 4): `frame` is the face plane with `z` the outward normal
  (`SurfaceEvaluator.getNormalAtPoint`) and `x` the plane's `uDirection`; `loops` from `BRepFace.loops`
  (`isOuter`, `edges`, each `edge.geometry` mapped into the frame). A face that is not a plane is
  `{ "kind": "other", "type": "Cylinder" }`.
- `sides`: `square` when every face next to it (`edge.faces`) is a plane across it or a cylinder along its normal,
  else `other`. `meets_offset`: a face next to it is moved by the same step.
- `faces_after`: a point and the outward normal of each flat face of `feature.faces` with the marker after the item.
  The translator copies a face only when one of them lies on the face plane moved by `distance`; each face becomes an
  extrude of its outline (join outwards, cut inwards).

**EmbossFeature** (`profiles`, `inputFaces`, `faces`, `isTangentChain`, `depth`, `horizontalDistance`,
`verticalDistance`, `rotationAngle`; `adsk.fusion.EmbossFeature` is marked preview in the API reference):

```json
{
  "profiles": [ ... ],
  "areas": [304.0],
  "faces": [{ "entity_type": "BRepFace", "surface": "Plane", "plane": PLANE, "outward": [0, 0, 1],
              "face_point": [30, 20, 4] }],
  "tangent_chain": true,
  "tangent_faces": [{ "surface": "Cylinder", "plane": null }],
  "made_surfaces": ["Plane", "Plane"],
  "depth": 1.0,
  "offset_x": 0.0, "offset_y": 0.0, "rotation_deg": 0.0,
  "participants": [{ "token": "...", "name": "Body1" }],
  "target_box_before": { "min": [..], "max": [..] },
  "volume_before": 9600.0,
  "volume_after": 9904.0,
  "end_offset": 1.0,
  "end_area": 304.0
}
```

- `profiles`: sketch profile records (section 4), including the outline records of a `SketchText`. `areas` holds
  `Profile.areaProperties` of each, in mm2; for a text record it is the area of its outlines (outer less holes),
  computed by the reader, null for a text marker.
- `faces`: the `inputFaces` the outline lands on. `surface` is `Plane`, `Cylinder`, `Cone` or `other` (from
  `BRepFace.geometry`); `plane` (origin and normal of the geometry), `outward` (`getNormalAtPoint` at `pointOnFace`) and
  `face_point` are null when they cannot be read. `participants` are the bodies of these faces.
- `depth`: mm, as Fusion stores it. There is no emboss or deboss flag: the sign decides (assumed: positive raises the
  outline, negative sinks it; hand test E1 and E2). `offset_x`, `offset_y` (`horizontalDistance`,
  `verticalDistance`, mm) and `rotation_deg` (`rotationAngle`) move and turn the outline on the face in a frame the
  reference does not document; the translator copies the step only when all three are zero. Each setting is null when
  it cannot be read. A size behind any of the three is pinned (a loose size with the reason), since it would move the
  outline in Fusion at other values.
- `tangent_chain` is `isTangentChain`. `tangent_faces` lists the faces that touch the input faces tangentially
  (`BRepFace.tangentiallyConnectedFaces`) as `{ surface, plane }`; null when they cannot be listed. `made_surfaces` is
  the surface kind of every face in `feature.faces` (read after the item), null when unreadable.
- `volume_before` and `volume_after`: the target's volume in mm3 with the marker before and after the item.
- `end_offset` and `end_area`: signed distance along the first outline's sketch `z`, from its sketch plane, and the
  area (mm2) of the farthest flat face of `feature.faces` that is parallel to the input face (the top of a raised
  outline or the floor of a sunk one); null when none is found.

The translator (`lib/translator/emboss.py`) copies a flat face emboss as an extrude that starts on the face
(`start.kind` is `fromEntity`): `join` for a positive depth, `cut` for a negative one, going out of the face or into
it. The measured `end_offset` decides the direction when it is known. It refuses a curved face, faces that are not on
one plane, a moved or turned outline, text, a sketch plane tilted to the face, Tangent Chain on (or unreadable) with a
tangent neighbour that is curved or not on the input plane (when the neighbours could not be listed: any curved made
face), and a measured volume change that is not
`sum(areas) * abs(depth)` within 1 percent in the direction the sign of `depth` says.

### Inputs from another component (`foreign`)

A record whose entity does not belong to the target's component carries `"foreign": true`; the key is absent
otherwise. Fusion can hand a feature's inputs over as occurrence proxies even when they are the target component's
own; such an entity is read through its `nativeObject` (component coordinates) and is not foreign
(`native_input()` in `lib/fusion_reader/read_geometry.py`). Any other entity is foreign when it has an
`assemblyContext` (it is seen through an occurrence) or its component is not the target's component, compared as
Fusion objects (`foreign()` in `lib/fusion_reader/read_geometry.py`; the
component is read from `parentComponent`, `component`, `body.parentComponent` or `parentSketch.parentComponent`,
whichever answers). An entity whose component cannot be read is not marked.

| Where | Record |
|---|---|
| Extrude and revolve `profiles[]` | the profile entry (its profile or sketch is foreign) |
| Extrude `start` and `side_one` / `side_two` of kind `fromEntity` / `toEntity` | the extent entry (the picked face or plane) |
| `participants[]` of extrude, revolve and hole | the body ref |
| Combine `target` and `tools[]` | the body ref |
| Fillet and chamfer `sets[].edges[]` | the edge record (`edge.body`) |
| Shell `faces[]` | the face record (`face.body`); a foreign body input sets `"foreign": true` on the data itself |
| Revolve and circular pattern `axis`, mirror `plane` | the axis or plane (see below) |
| Offset faces `faces[]` | the face record |

A revolve or circular pattern `axis`, or a mirror `plane`, of another component that is seen through an occurrence
or belongs to the root is read in the root's coordinates. The reader brings it into the target's coordinates
(inverse of the target's placement) and writes `"assembly": true` instead of `"foreign"` (`from_assembly()` in
`lib/fusion_reader/placement.py`); when the target's place cannot be read it stays foreign. An axis from a sketch line
of another component loses `entity`, `sketch_token` and `sketch` (the probe follows only the target's own sketch
lines); the sketch is named in its `ref`.

### Measured references (`ref`)

An entity of another component that a step uses (the face or plane an extrude starts from or reaches to, a mirror
plane, a pattern or revolve axis, the point or face a hole sits on) is recorded as a plain `ref` dict, built by
`ref_record()` in `lib/fusion_reader/placement.py`. The record keeps what is needed to find the entity again and to
tell which sizes may move it:

```json
{ "slot": "plane", "type": "ConstructionPlane", "token": "<native token>",
  "component": { "token": "...", "name": "Cover" }, "path": "Cover:1",
  "body": { "token": "...", "name": "Body1" }, "sketch": { "token": "...", "name": "Sketch2" }, "origin": true,
  "point": [0, 0, 21.6], "normal": [0, 0, 1], "face_point": [3, 4, 21.6] }
```

- `slot`: where the step uses it: `start`, `side_one`, `side_two` (extrude), `plane` (mirror), `axis` (revolve and
  circular pattern), `direction_one`, `direction_two` (rectangular pattern), `positions.<n>` (hole). The key of a
  reference is `<item index>.<slot>` (`params.geometry_links.ref_key`, `item_refs`). The holes' `position_refs` take
  `<n>` from their place in the list.
- `type`: the Fusion type of the native entity (`BRepFace`, `ConstructionPlane`, `ConstructionAxis`, `SketchLine`,
  `SketchPoint`, `BRepEdge`). `token`: the `entityToken` of the native entity, which `Design.findEntityByToken` finds
  again. `component`: the component that owns it (the component of the occurrence it is seen through, else its own).
  `path`: the `fullPathName` of the occurrence it is seen through, empty for the root.
- `body` (faces, edges) and `sketch` (sketch entities): the native body or sketch it belongs to.
- `origin`: true for an origin plane or axis of the owning component. It moves only with its occurrence.
- `point`, `normal` or `dir`, and for a face `face_point`: the entity's geometry in the target's coordinates. They are
  left out when the entity is not in root coordinates or the target's place cannot be read.

Mirror planes and pattern or revolve axes keep their geometry in the record (`assembly: true`); `ref` repeats it with
the identity. An extrude `start` or `side_one` / `side_two` of kind `fromEntity` / `toEntity` on a face or plane of
another component is read as `foreign` and carries `ref` with the geometry in the target's coordinates; its own `plane`
and `face_point` stay as Fusion gave them (the translator replaces them from `ref` when the face is flat).

The translator (`lib/translator/ref_motion.py`) reads these records as follows.

- `bring_in` makes a flat face or plane of another component that an extrude starts from or reaches to usable: the
  record loses `foreign`, gets `assembly: true`, and its `plane` and `face_point` are taken from `ref` (the target's
  coordinates). The same for a hole whose `position_refs` are all flat faces or planes. A record without a flat `ref`
  (a curved face, an edge, a place that could not be brought in) stays `foreign` and the step is refused, with a reason
  that says which.
- For a record with `assembly: true` (and the `position_refs` of a hole, a `direction_*_place` of a pattern) the
  size marks come from the motion file (`probe.motion.refs` and the `<item>/r/<slot>/...` keys,
  `sketch_values.coverage.ref_answer`), for each ticked size whose user parameter acts on `ref.component`
  (`dependents` of the parameter, the rule in `lib/params/geometry_links.py`):
  - measured and the size does not move it: nothing is marked;
  - measured and moved by an `Affine`: the step writes the move as a formula (mirror plane origin, pattern `axisPoint`,
    revolve axis point, extrude start shift or reach, hole centre) and the size stays free;
  - a `Stuck` key (the reference turns, or the move is no exact formula): the sizes behind it are marked loose and the
    place stays where the capture has it;
  - not measured (`probe.motion.refs` holds a reason, or the size was left without rows), not looked at (no entry),
    or no motion file: every such size is marked loose with the step and the component named.
  The first translation of an export (`OPTIMISTIC`) marks nothing. An `origin` reference marks nothing. A capture that
  lists no `dependents`, or a record without a component, gives the step a note instead.
- A plane or face moves along its captured `normal`; an axis moves across its direction. A pattern direction stays the
  number read; only a turn marks sizes.

### Parameters behind values (`data.params`)

A value that Fusion keeps as a model parameter is listed in the item's `data.params`: capture field path to
`{ "name": "d12", "expression": "FilterBox_height_mm", "value": 32.0 }`. `value` is in mm, degrees or as is (counts),
like the field it belongs to. Written by `lib/fusion_reader/param_refs.py`; a member that is not a model parameter (a
plain number, a retired member) adds nothing, and `params` is absent when nothing is listed. The translator
(`lib/translator/values.py`) turns a listed value into a formula over the sizes when its expression reads one.

| Type | Field paths |
|---|---|
| ExtrudeFeature | `side_one.distance`, `side_two.distance`, `side_one.taper_deg`, `side_two.taper_deg`, `side_one.offset` (to entity), `side_two.offset`, `symmetric.distance`, `symmetric.taper_deg`, `start.offset` |
| RevolveFeature | `extent.angle_deg` |
| HoleFeature | `diameter`, `tip_angle_deg`, `extent.depth`, `counterbore.diameter`, `counterbore.depth`, `countersink.diameter`, `countersink.angle_deg` |
| FilletFeature | `sets.<n>.radius` |
| ChamferFeature | `sets.<n>.distance`, `sets.<n>.distance_two`, `sets.<n>.angle_deg` |
| ShellFeature | `inside` |
| RectangularPatternFeature | `quantity_one`, `quantity_two`, `distance_one`, `distance_two` |
| CircularPatternFeature | `quantity`, `total_angle_deg` |
| EmbossFeature | `depth` (read like an extrude length; a negative depth is written negated), `offset_x`, `offset_y`, `rotation_deg` (not followed: the copy needs them to be zero, and a size behind them is pinned) |

Sketch dimensions, construction planes, axes and joints are not listed per item. They are model parameters whose
`created_by.kind` is `sketchDimension`, `constructionPlane`, `constructionAxis` or `joint`. The full list of kinds is
`feature`, `sketchDimension`, `sketchText` (the height of a sketch text), `constructionPlane`, `constructionAxis`,
`joint` and `other`.

How the translator uses them (`translate(capture, size_table=table, motion=motion)`):

- A value is written as `{ "expr": formula }` (never `{ "size": ... }`) when its expression translates, reads at least
  one free size and equals the measured number within 1e-6 once scaled to the unit of the field (a plain number in a
  length is read in the parameter's unit or the design's, whichever gives Fusion's number). Lengths written as absolute
  values (extrude and hole depths, spacing) must also stay above zero over the size range; counts at least 1.
  A negative parameter is written negated.
- Symmetric half length is written as `2 * (formula)`. An extent spacing is `(distance) / ((count) - 1)`. Hole
  tip outlines and counterbore or countersink sizes follow sizes point by point.
- Pattern counts that follow sizes must give whole numbers at every size value: the formula is rounded as a whole
  (`round`, `floor`, `ceil`), or it adds, subtracts and multiplies whole numbers and count sizes. Otherwise the sizes
  are fixed. An extent spacing divides by `max((count) - 1, 1)`, so a count of 1 never divides by zero.
- Values that stay numbers while a size reaches them: construction geometry that a step uses itself, the "up
  to" offset, a tip angle, a countersink angle, a full circular turn, a revolve that is not a plain
  part turn, and a pattern whose copies are left out by number or are rounds copied one by one. The sizes behind
  them are fixed.
- Picks and reaches that follow sizes (`lib/translator/follow.py`). Every extrude step is kept with its placement,
  profile and length. A pick point (fillet and chamfer edge points, shell face points) or a TARGET `face_point` that
  lies on an end face of an earlier extrude (inside its profile), or on its side at a profile corner (any outline
  point for a face), moves with that extrude's length:
  - a shell that opens one such moving end face writes `{ "featureFace": <id>, "which": "start" | "end" }`;
  - a round or chamfer whose edges are exactly the side edges, or exactly the edges of a moving end face, of one
    extrude writes `{ "featureEdges": <id>, "which": "sides" | "start" | "end" }`;
  - otherwise, a round or chamfer step that holds whole sets of one size picks the way Fusion did (recipe version
    14): sets picked only by faces write `{ "faceEdges": <face selector of the face points> }`, every edge around
    those faces, and tangent chain sets picked only by edges write one point per `seed` edge with
    `"chain": "tangent"`. Both keep picking every edge when a size adds edges (more bumps along a rim) or splits
    one, which one point per edge cannot. A step with part of a set, mixed inputs or sizes per edge keeps a point
    per edge;
  - other points write the coordinate along the extrude as a formula (`0.5 * height` for a side point half way up);
  - a "to entity" reach to a moving end face writes its length as a formula; a construction plane stays where it is;
  - a start offset that follows sizes, or a "from entity" start on a moving end face, moves the sketch placement
    along its normal (`sketch.on.origin` as formulas), and the picks on that extrude follow it too. Such a moving
    start with a side that reaches "to" a face is fixed.
  - a copy made by a pattern or mirror of an extrude is placed like the extrude and moved by the copy's motion: a
    linear spacing that follows sizes moves the point with it, a turn or a mirror moves it by numbers. A pick on a
    copy fixes the sizes behind that pattern's count (and a circular angle), since the list of points cannot grow.
    A copy has no `featureEdges` or `featureFace`: the app traces only extrudes, so copies are picked by points.
  - a point on the inner wall of a shell (`lib/translator/shells.py`) is moved back out by the thickness and placed
    on the extrude whose outer wall it came from; its coordinates follow that extrude and the thickness.
  - an edge where the flat walls of two steps cross (`lib/translator/crossings.py`), for example a cut's floor
    running into a rib, stays on both walls as they move; along the edge it follows the shorter wall.
  - a point on the far outline of a tapered extrude follows its length; a taper that follows a size is fixed.
  A point or face that no extrude explains may sit on geometry that moves, so every size read by the steps written
  before it is marked, with the step's name in the reason. Rounds and chamfers that a pattern or mirror copies take
  their source's written points (formulas included) through each copy's motion; their count is fixed, and a circular
  angle too. A copied uneven chamfer turns its `sizeOn` with the copy. Without sizes the picks stay plain points.
- A formula longer than the app's cap (`MAX_FORMULA_LENGTH` in `lib/params/expressions.py`, 300 characters) fixes
  the sizes it reads (they become plain numbers), also when a step builds it from several values.
- Sketch values follow sizes through the probe's motion file (next section). Without one, every size that a model
  parameter created by a sketch dimension (also one whose creator reads as `other` but whose `role` names a
  dimension), construction plane or axis, or joint reads cannot be followed (reason "it changes a sketch, which could
  not be tried at other values"). A size that a joint reads can never be followed ("it moves a joint"). The
  dimensions of another component's
  sketch are not model parameters of the target's path; the sizes in their `sketch_params` are fixed when the step
  that borrows the sketch is copied, and its outline stays numbers.
- An uneven chamfer writes `sizeOn` (one direction per step: the sum of `first - other` face normals over its edge
  points, which must favour the first face by at least 0.1 at every point; edges that one direction cannot serve
  start another step) with `otherSize` or `cutAngleDeg`. Both distances follow sizes; an angle must stay under 90
  degrees over the size range, else its sizes are fixed.
- A value that cannot follow its sizes is written as its number and its sizes are recorded (`Context.doubt`; the notes
  here say a size is "fixed" or "marked" for such a value). The translator walks twice. The first walk makes each
  recorded size a plain number in a new size table (`with_fixed`) and walks again until nothing new is recorded, to
  learn which sizes and reasons there are. The second walk keeps those sizes free: every value that can follow them
  still does, and the values that cannot keep their numbers, so the shape at the current values is the same. In that
  walk a stuck sketch value follows its `rest` (the sizes that still move it), as it does once its own sizes are
  fixed. `TranslateResult.loose` lists the sizes as `{ name, reason }` ("... may give unexpected results: ..."). A
  size that no formula reads after that is not a size: it is left out and listed in `TranslateResult.dropped` with its
  reason. The ranges are always the table's. A rule that can fail inside a range
  (a count that a pick needs, a taper, a step that must keep meeting the part) marks the sizes it reads, with the
  value past which it fails where `kept_ranges` gives one. Only `TranslateResult.fixed` holds sizes that became
  numbers: a formula too long to copy (`Context.doubt` with `fixed`). Without a motion (`motion=None`) every size behind
  a sketch dimension, construction plane or axis, or a joint, is marked with a reason, and the ones no formula reads
  are dropped with that reason.
- End of walk audit (`lib/translator/audit.py`). After the last walk every free size that a copied step reads must be
  in a known state: read by a written formula, fixed, loose, or dropped, each with a reason. A step reads a size
  through its `data.params` (what each expression reads), the dimensions of the sketches its data names, and the
  construction geometry it uses. A value of a step's `data.params` that its handler never dealt with
  (`values.quantity`, `values.pin` or `values.handled` record the path) and that reads a free size, or a sketch size that a measured motion says moves something and no formula reads, and that no handler named, gets the
  reason "<step> reads it, and the copy does not follow it": loose when another formula reads it, else dropped. A sketch
  size that a measured motion says moves nothing is dropped as "changes nothing in the copied steps" (for a size tied
  to the sketch only through another component, as "nothing in this part moved with it"). This makes a value a
  handler forgets to record safe by default.
- `TranslateResult.dropped` is `[{ name, reason, used }]`, one per ticked size the recipe does not hold: `used` is
  true when a step reads it and the copy could not follow it (the reason says why), false when no copied step reads it
  ("not used by any copied step") or a measured sketch does not move with it.
- Only steps whose result reaches the exported body count. The steps of another body wait in `Context.pending_tools`
  with the doubts of their handlers: the sizes they cannot follow join the walk only when a Combine takes that body
  (`StepResult.join`), and only then do its items count for the audit.
- A step with no handler stops the copy, with two exceptions that the capture proves harmless: a step that lists no
  body and whose `target_changed` is false (a Remove of another body) is skipped, and so is a Split Face of the exported
  body with `target_changed` false, with the note that picks on its faces may not follow. A step of another body that
  has no handler is helper geometry and is skipped. A `target_changed` of true or null keeps the stop.
- A copied step that Fusion reports with a `warning` health gets a note with Fusion's message.
- The copy limits (`MAX_PATTERN_COPIES`, `MAX_FEATURES`, `MAX_NEAR_POINTS`) are checked at the current values; a pattern
  count that can pass its limit inside the size ranges (`range_check.sweep`) marks the sizes it reads.
- The recipe is version 12, or the lowest version that holds its steps and selectors (13 with an `offsetFaces` step, 14
  with a `chain` or `faceEdges` pick). With a size table it carries `sizesAsWritten: true` and `sizes`: the sizes that a written
  formula reads, plus the sizes those formulas read. A ticked size that nothing reads is left out (see `dropped`).
  Without a table the recipe has no `sizes`, and no marker.

### Sketch values that follow sizes (`lib/translator/sketch_motion.py`)

The export measures the sketches at other size values (probe states, next section) and fits each value the translator
writes as a sum over Fusion parameters, or marks it stuck (`lib/probe/`). That is the motion file, `sketch_values.motion`:
keys `<item>/p<profile>/l<loop>/<field path>` (loop 0 is the outer one, then the holes; `center.0`, `width`,
`segments.2.through.1`), `<item>/p<profile>/plane` (the sketch plane along its normal, from the component origin),
`<item>/positions/<n>/<0|1|2>` (hole points) and `<item>/axis/point/<0|1|2>` (a revolve axis from a sketch line).
`lib/sketch_values/keys.py` writes all keys; the probe and the translator both use it.

Measured references of other components (below) have their own keys, `<item>/r/<slot>/...`, and their own list `refs`.

The probe tries (`lib/probe/plan.py`, at most 64 rows): each ticked size that moves a covered sketch value or reaches
a sketch dimension, a construction plane or, through another component, a sketch ("Geometry links" in section 2),
at the ends of its range. Then up to 8 ticked sizes that nothing ties to a sketch (`MAX_EXTRA_SIZES`, in table order)
while rows are left: the person ticked them, so a sketch may follow them in a way the capture cannot show. Such a size
left without rows is not listed as untried. With two or more sizes tried, one row puts every size at its minimum and
one at its maximum. A ticked size the probe set to other values that no formula reads at the end is dropped with
"it was tried at other values, and it changes nothing in this part" (`used` false, `tried` true). Every state also
reads the body's box (and volume when the state has it): a size whose state alone changed the box but moved no
followed sketch or reference is kept in `Motion.body_moved` (`SizeProbe.finish`). The translator treats it as doubtful
with "it changes this part in a way the copy does not follow": loose when a formula reads it, else dropped with
`used` true. It is never reported as changing nothing.

Discovery tries come last, in the rows the cap leaves: up to 12 unticked plain parameters (`MAX_DISCOVERY`) from the
discovery candidates of "Geometry links" (section 2), one row each with only that parameter at one end of its range
(the upper end, the lower one when the upper is its value). They are not states of the motion: each read is only
compared with the first read over the covered sketches, the followed references and the body's box and volume
(`SizeProbe.discover`, moved past the fit tolerance, or an outline with other keys). They never become sizes in this
export. `probe.discovery` in `report.json` lists `{ param, moved }` (`moved` null when the row did not build or could
not be read); a candidate the cap or the row room left without a row is listed as `{ param, moved: null, tried: false,
reason }`, and the result window counts those in a "Not tried" group (ticking one makes the export try it).
`also_changes` lists the parameters that moved the part; the result window says "These parameters also change this
part: ... Tick them and export again to get them as sizes." For a parts file the group is "Also change these parts" and
each parameter names the parts it changed (read from each part's `probe.discovery`).
The sketch curves of each profile have `<item>/p<profile>/c<loop>.<curve>/<field>` in the capture's loop and curve
order: a line's `offset` (its distance from the sketch origin along the left normal of its captured direction) and
`turn` (degrees it turned), an arc's `center.0`, `center.1` and `radius`; `curves` lists the profiles
(`<item>/p<profile>`) whose curves were measured. For a sketch the probe measured, a key that is not listed did not
move. A sketch the probe could not measure (a step uses it in a way the probe cannot follow, its first read did not
match the capture, or there was no read at the current sizes) is listed in `unmeasured` (sketch name to reason), and
nothing is known about it. For one sketch and one size the motion file therefore gives one of three answers: measured
and still, measured and moved (the keys), or not measured (`translator.sizes.sketch_answer`). A motion file without
`unmeasured` (written by hand) says nothing about such sketches. The translator uses it like this:

- `motion=None`: the rule above, sketch sizes fixed up front. `motion=OPTIMISTIC` (the export's first translation):
  sketch values are written as numbers and nothing is fixed for them, so the export can see which sizes to try.
- Each written value with a key becomes a formula over the sizes (`{ "expr": "0.5 * FilterBox_width_mm" }`); a model
  parameter in a sum is written through its own expression. Its number stays the captured one; a formula that misses
  it by more than 1e-3 mm fixes its sizes ("could not be read at other values"). A width, height or radius that would
  reach zero over the size ranges fixes its sizes ("would shrink to nothing").
- A value of an unmeasured sketch is stuck with cause `untried` for every size the sketch reads (`sizes.sketch_sizes`:
  the sizes behind that sketch's dimensions, and the sizes that may reach it through the geometry of another
  component, "Geometry links" in section 2). The size is loose, with "it changes <sketch> and could not be tried at
  other values". A size the sketch does not read is not touched: a size that moves the sketch only through its
  construction plane is not named here.
- A size that may reach a sketch only through another component follows the measured motion like any other: when the
  probe saw the sketch move with it and the fit holds, the outline is written as formulas of it (two arcs of radius
  `pipe_d_mm / 2` give points such as `0.5 * pipe_d_mm`; a circle writes its `radius`). When the fit fails or the
  outline changes shape, its sizes are loose or dropped with the probe's cause, which names the sketch. When the
  sketch was measured and did not move, the size is dropped ("it changes <component>, but nothing in this part moved
  with it", `used` false). Without a motion (`motion=None`), it is dropped with "it changes <component>, which
  <sketch> is drawn around, and could not be tried at other values".
- A stuck value that a step writes fixes every size the probe lists for it, with the probe's cause: `curve` (a point
  moves along a curve), `shape` (the outline changes), `turns` (the sketch plane turns), `unread`, `untried`. When
  only some states failed (a size whose state changed the outline), the probe lists only those sizes and fits the
  value over the other states as `rest`, which the translator writes once the listed sizes are fixed. A sketch can
  have more than one solution, and Fusion may land on another one after the rows run before: when a sketch reads as
  the same different outline in states that change different sizes, those states blame no size for it (`apart`
  lists them, by number in `states`).
- An outline merged from touching profiles takes each point from the part profile that has it (rect corners from
  centre, width and height); a rect drawn through merged corners gets its centre, width and height from them. Pieces
  of one sketch line in a merged loop are joined back into the line, and a loop of arcs of one circle becomes the
  circle, with the centre and radius of that sketch circle.
- A corner the probe could not fit (it moves along a curve) is rebuilt from the two sketch curves that cross there:
  two lines give an affine point, a line and a circle or two circles a point with `sqrt`. An arc's middle point
  becomes a fixed direction from its centre. The rebuilt outline must keep its crossings and the order of its corners
  at every mix of the size ends (up to 6 sizes; a bounded sample past that) and the probe's states; otherwise its sizes are fixed ("along a curve"). A
  line that turns cannot carry its crossings.
- A sketch plane that moves writes the placement origin along its normal (`sketch.on.origin`); a "to entity" reach is
  the face's move less the plane's move. Outlines of one step whose planes move differently fix those sizes.
- A reversed placement negates the y formulas of its loops.
- Hole points write `origin` as formulas (the drill tip revolve too); a revolve axis from a sketch line writes
  `axis.point` in the sketch plane. A symmetric revolve turns its moving origin about the axis.
- Picks on an extrude whose outline moves follow it: a side corner moves with that corner, a point on an outline line
  between its two ends, a point on an arc with the arc's middle (or with the whole arc when it only shifts), on a
  circle with its centre and radius, and a point inside an end face with the outline's centre. A point on an arc that
  changes shape fixes those sizes. The same holds for pattern and mirror copies, shell inner walls, crossing edges
  and faces an `offsetFaces` step moved (the point moves back by the distance, then follows what made the face).
- A pick on a tapered wall follows the taper and the length: the wall leans in by `tan(taper)` times the height along
  the extrude, also when the taper is a size.
- A pick on a copy of a rectangular pattern needs that copy at every size: copy n needs a count of n or more over
  the size range (count formulas such as `ceil(width_count) * 2` are evaluated at the range ends, `lib/translator/
  copy_counts.py`). When the count can drop below that, the sizes it reads are marked ("a smaller value would leave
  that copy out"); the range stays. Copies of a circular pattern keep their count and angle.
- A taper that follows sizes should stay under 45 degrees either way: the sizes it reads are marked past the value
  where it reaches 45.
- A through cut clears the part at the largest sizes tried (`box_max` of the motion file).
- A construction plane or axis that a step uses itself (start from, reach to, turn about, mirror across, with `token`)
  fixes the sizes of the model parameters it made (`created_by.token`); without a token, of every construction plane
  or axis.

### Measured references in the motion file (`lib/probe/ref_fit.py`)

The probe reads every measured reference (`ref`, section 4) that has a place in the target's coordinates and fits how
far it moves from the captured place. A size that acts on the reference's component is probed like a size behind a
sketch (`reference` links, section 2). The values are moves, zero at the sizes the capture was read at:

| Reference | Keys | Meaning |
|---|---|---|
| plane (`point` and `normal`: a mirror plane, a plane or face an extrude reaches or starts from, a hole's face) | `<item>/r/<slot>/offset` | distance the plane moved along its captured normal |
| axis (`point` and `dir`) | `<item>/r/<slot>/point/<0|1|2>` | how far the axis moved across its direction, per coordinate (a slide along the axis is not a move) |
| point (a sketch point or vertex) | `<item>/r/<slot>/point/<0|1|2>` | how far the point moved, per coordinate |
| direction (`dir` alone: a pattern direction) | `<item>/r/<slot>/dir` | stuck only, when the direction turns |

Each value is an `Affine` of the sizes (exact within 1e-4 mm, same fit and checks as sketch values), or a `Stuck`: with
cause `turns` when the normal or direction changes or flips (the sizes of those states), `unread` when a state did not
give the reference, `curve` or `untried` when the move is no exact formula of the sizes. Like the sketch values, a
`Stuck` may carry `rest`. A measured reference that stays has no key.

`refs` lists every reference the probe looked at, by key `<item>.<slot>`: `""` when it was measured, else why not
(it has no place in the target's coordinates or no token, the first read did not match the capture within 1e-4 mm, the
reader could not read it, or there was no first read). Such a reference is not read at the other states. A key that is
not in `refs` was not looked at (older motion file, or the export's first translation): nothing is known. For one
reference and one size acting on its component, `sketch_values.coverage.ref_answer` gives the same three answers as for
sketches: `STILL`, `MOVED` (with the keys) or `NOT_MEASURED` (with the reason, or `NOT_TRIED` for a size left without
rows, `NOT_LOOKED` for a key not in `refs`).

### Probe states (`lib/fusion_reader/probe_state.py`)

The size probe sets other size values, recomputes and reads a state with `read_state(design, request, ctx)`.
`request` is `{ "sketches": [token], "points": [token], "lines": [token], "params": [name], "target": true }`, plus
`borrowed` and `refs` below. Every
entity is found with `Design.findEntityByToken` (the match without `assemblyContext`; for a proxy only, its
`nativeObject`), so values are in component coordinates like the capture. The result, mm and degrees except `params`:

```json
{
  "sketches": { "<sketch token>": { "frame": FRAME, "profiles": [PROFILE, ...] } },
  "points": { "<sketch point token>": [x, y, z] },
  "lines": { "<sketch line token>": { "point": [x, y, z], "dir": [x, y, z] } },
  "params": { "d12": 2.0 },
  "box": { "min": [..], "max": [..] },
  "refs": { "57.plane": { "point": [x, y, z], "normal": [x, y, z] } }
}
```

- `sketches`: `frame` from `Sketch.transform`; `profiles` are every `Sketch.profiles` item read like a capture
  profile (section 4, each curve with `entity`). A sketch with more than 200 profiles, or a profile whose space is
  `ambiguous`, is left out.
- `points`: `SketchPoint.worldGeometry`; `lines`: `SketchLine.worldGeometry` start point and unit direction.
- `params`: `value` of each named parameter in Fusion's own units (cm, radians), as in `parameters.*.value`. A name
  is looked up in the user parameters, then in the target component's model parameters.
- `box`: the target body's box, as `target.box`.
- A sketch of another component that a step borrows is requested with the optional `borrowed`: `{ "<sketch token>":
  { "path": "<fullPathName the capture recorded>" } }`. It is found by token, read native, and its place is found
  again at every state: the occurrence of its component with that path (the only one when there is no path), then the
  placement check of section 4 (native sketch points against the same points through the occurrence). Its `frame` is
  brought into the target's coordinates (that place, then the inverse of the target's, read once per capture), so
  it compares with the capture profile's brought-in `frame`; it adds `native_frame` and `placement` (`{ path, source }`).
  When it cannot be read or placed, it has no key under `sketches` and `unread` (only then present) gives
  `{ token: reason }`.
- Measured references are requested with `refs`: `{ "<key>": { "token", "type", "path", "shape" } }` (`shape` is
  `plane`, `axis`, `direction` or `point`, from the record: `lib/probe/plan.py` `refs`). Each is found by the token of
  its native entity (`lib/fusion_reader/probe_refs.py`), shown through the occurrence with the recorded `path` as that
  occurrence sits now (`createForAssemblyContext`), read the way the capture read it (`plane_of`, `axis_of`,
  `direction_of`, `worldGeometry`), and brought into the target's coordinates with the inverse of the target's own
  place read again at this state (the body is shown through its occurrence again, so a size that moves the target's
  component is taken out). `refs` maps a key to `{ point, normal }`, `{ point, dir }`, `{ dir }` or `{ point }`; a
  reference that cannot be read has no key there and `unread` gives `{ key: reason }`. The reads change nothing in the
  design.
- Nothing raises. A part that cannot be read has no key, which the fit treats as unread.

## 6. Report and capture file

The export writes `report.json` into the package: `{ "writer", "outcome": "recipe" | "stepOnly", "items": [ITEM
VERDICT, ...], "capture": CAPTURE }` (verdicts: see the translator, `lib/translator/result.py`). The app never reads it. A report saved from a real
design gives a fixture: its `capture` is copied as is.

`also_changes` (only when not empty) names the unticked parameters that a discovery try showed changing the part.
`links` (only when the export found geometry links) lists each link of the picked body with what became of its
parameter: `{ param, sketch, component, outcome, reason }`, `outcome` one of `size`, `loose`, `fixed`, `dropped` or
`not ticked` (`recipe_export.link_outcomes`; `reason` when the size has one).

`sizes` holds `free` (recipe size names), `fixed` and `loose` (`{ name, reason }` by recipe size name, as in the
manifest), and `dropped` (`{ name, reason, used }` by Fusion name, plus `tried: true` for a size the probe set to
other values that changed nothing: the ticked parameters that are not sizes, from
`TranslateResult.dropped`; `used` is true when a step reads the parameter and the copy could not follow it). `loose` comes
from the translator and from the probe. `checks` in the manifest is
always empty. The report has a
`probe` when a sketch could be followed (the rows only recompute and the parameters are restored), `marker` and
`health`. A probe row that Fusion cannot build is listed in `probe.dropped`; no size is fixed for it.

## 7. API names and what is not verified

Read in the API reference on 2026-11-10: `SketchEntity` (`isReference`, `referencedEntity`, `isLinked`,
`geometricConstraints`, `parentSketch`), `Sketch` (`sketchCurves`, `sketchPoints`, `geometricConstraints`,
`referencePlane`, `parentComponent`), `SweepFeature` (`profile`, `path`, `guideRail`), `PathEntity.entity` (a sketch
curve or an edge), `LoftSection.entity`, `ExtrudeFeature.profile` (a profile, a planar face or an ObjectCollection;
null for a feature that is not parametric), `BRepFace` (no member names the feature that made it, so links are
matched through `body` and `bodies_after`), `CoincidentConstraint` (`point`, `entity`), `ConcentricConstraint`
(`entityOne`, `entityTwo`), `EqualConstraint` and `TangentConstraint` (`curveOne`, `curveTwo`), `ModelParameter`
(`component`, `dependentParameters`, `createdBy`).

Read in the API reference on 2026-11-08: `HoleFeature` (all members above, plus `isDefaultDirection`;
the page says "the extent type of a hole is currently limited to a distance extent" but also lists
`setAllExtent` and `setOneSideToExtent`), `SketchPointsHolePositionDefinition.sketchPoints`,
`SymmetricExtentDefinition` (`distance`, `isFullLength`, `taperAngle`), `DistanceExtentDefinition.distance`,
`ThroughAllExtentDefinition.isPositiveDirection`, `OffsetStartDefinition` (`offset`, `profilePlane`),
`ExtrudeFeature` (members above), `RevolveFeature` (members above), `AngleExtentDefinition` (`angle`,
`isSymmetric`), `PatternElement` (`id`, `isSuppressed`, `transform`, `faces`), `RectangularPatternFeature`
(members above), `ProfileCurve` (`geometry`, `geometryType`, `sketchEntity`), `Arc3D`, `Ellipse3D`, `Matrix3D`
(`getAsCoordinateSystem`, `asArray`, `translation`), `Timeline` (`markerPosition` get and set, `moveToEnd`,
`item`, `count`, `timelineGroups`), `BRepEdge` (`evaluator`, `faces`, `startVertex`, `endVertex`,
`tangentiallyConnectedEdges`, `pointOnEdge`), `BRepFace` (`pointOnFace`, `evaluator`, `geometry`, `edges`,
`tangentiallyConnectedFaces`), `BRepBody` (`volume`, `boundingBox`, `name`, `entityToken`),
`ConstantRadiusFilletEdgeSet` (`edges`, `radius`, `isTangentChain`, `continuity`), `TwoDistancesChamferEdgeSet`
(`distanceOne`, `distanceTwo`, `edges`, `isFlipped`), `ShellFeature` (members above; default `SharpOffsetShellType`).
Read on 2026-11-07: `TimelineObject`, `FilletFeature`, `ChamferFeature`, `CircularPatternFeature`,
`MirrorFeature`, `CombineFeature`, `Sketch`, `Profile`, `ProfileLoop`, `FeatureOperations`.

Not verified (each has a measured check or a test in section 7 of `docs/hand-tests.md`):

| Item | Check |
|---|---|
| Enum value names: `HoleTypes`, `HoleTapTypes`, `FeatureExtentTypes`, `PatternEntityTypes`, the spacing value of `PatternDistanceType` (add-in 0.3.1 looked for `PatternDistanceTypes` and wrote `other`), the rounded value of `ShellTypes`, `Curve3DTypes`, fillet continuity, `ChamferCornerTypes` | the reader maps by name text with a fallback to `other`; the "Capture reader calls to watch" lists in `docs/hand-tests.md` logs unknown names |
| `ProfileCurve.geometry` in sketch space or model space; `ProfileCurve.sketchEntity` and `SketchCurve.geometry` in sketch space | reader decides per profile and writes `space` (`ambiguous` is refused); the Tilted sketch test (offset, tilted, bottom face sketch) |
| `getAsCoordinateSystem()` returns `(origin, xAxis, yAxis, zAxis)` in Python | the Tilted sketch test |
| `CurveEvaluator3D.getParameterExtents`, `getPointAtParameter`, `getTangent`; `SurfaceEvaluator.getNormalAtPoint` | the "Capture reader calls to watch" lists in `docs/hand-tests.md` |
| A flipped one sided extrude stores a negative distance | `end_offset`; the Extrude directions test |
| Taper sign (Fusion positive grows or shrinks) | one constant `FUSION_TAPER_SIGN` in `extrude.py`; the Extrude directions test |
| `ToEntityExtentDefinition`, `TwoSidesDistanceExtentDefinition`, `TwoSidesAngleExtentDefinition`, `FromEntityStartDefinition` field names | reader falls back to `other`; the Extrude directions test |
| Revolve turning sense | `start_face_normal`; the Turned knob test |
| Hole `direction` points into the material; blind depth is measured to the shoulder, not the tip; how a flat drill point shows (`tipAngle` 180 or another member) | `end_points`; the Holes test |
| `patternElements` includes suppressed elements | translator fills missing lattice places from the quantities; the Bin test |
| `entityToken` of a body stays the same across marker positions | a token that changes makes the translator refuse the capture; the Combine test |
| `Timeline.item` walks inside groups; `TimelineGroup.startIndex`, `endIndex` | reader raises `CaptureReadError` when a group child is not in the walk; the "Capture reader calls to watch" lists in `docs/hand-tests.md` |
| Moving the marker marks the document changed or adds undo entries | the Marker and document test |
| New timeline items (the temporary copy) go in at a rolled back marker, and `computeAll` leaves the marker in place | the copy is checked for a body, the marker is put back after each recompute and at the end; the Marker rolled back tests |
| `isRollingBallCorner` still on `FilletFeature` (some fillet members are retired) | reader reads it in a try, default true; the Bin test |
| The members in the `params` table return a `ModelParameter` (name, expression, value): `DistanceExtentDefinition.distance`, `taperAngleOne` and `taperAngleTwo`, `OffsetStartDefinition.offset`, the `HoleFeature` size members, `ConstantRadiusFilletEdgeSet.radius`, chamfer set distances, `insideThickness`, pattern `quantityOne`, `distanceOne` and the circular ones | a member that is not one adds nothing and the value stays a number; the sizes hand test logs which members gave a parameter |
| `Sketch.entityToken`, `Sketch.referencePlane`, `ProfileCurve.sketchEntity.entityToken`, `entityToken` of sketch points, lines, construction planes and axes; the sketch curve tokens staying the same after a recompute | the probe compares its first state with the capture and fixes the sizes of a sketch that does not match; the Sketches that follow sizes tests in `docs/hand-tests.md` |
| `Design.findEntityByToken` for a sketch of a component inside an occurrence (native object, proxies, or both) | `read_state` takes the match without `assemblyContext`, else the `nativeObject` of the first |
| `ModelParameter.createdBy` kinds and `name` for a sketch dimension | the kind comes from the type name; the sketch rule needs only the kind |
| `ToEntityExtentDefinition.entity` and `FromEntityStartDefinition.entity` give the picked face (`BRepFace`, read for `pointOnFace`) or construction plane | an unreadable face point fixes the sizes written before the extrude; the "Pick points that follow sizes" hand test |
| `BRepBody.nativeObject`, `BRepBody.assemblyContext` of a picked body inside a component; `Feature.assemblyContext`, `Feature.nativeObject` of timeline entities | the target is the native body and a proxy entity is turned native; `entity_context` logs when it was a proxy; the "Bodies inside components" hand tests |
| `Occurrence.transform2` of a nested proxy is relative to the root or to the parent | `placement.source` says which candidate passed the point check (`transform2` or `path_transform2`) |
| Vertex and face point geometry of a proxy body is in root coordinates, of the native body in component coordinates | the point check; a mismatch gives `placement.error` and a fixed shape |
| `Occurrence.isReferencedComponent`, `Component.allOccurrencesByComponent` | `linked` and `uses`; a wrong value only changes a note or refusal |
| `Sketch.transform`, `SketchPoint.worldGeometry` of a native component sketch are in component coordinates | the "Nested and turned" hand test compares one hole position |
| `Occurrence.sourceComponent` and `Occurrence.assemblyContext` of a timeline occurrence; `ConstructionPlane.component` | the item `component`; the "Bodies inside components" hand tests |
| Feature inputs (profiles, edges, planes, faces) of a component feature come as proxies through the occurrence; `nativeObject` gives the component's own entity | records of the target's own inputs carry no `foreign`; the "Bodies inside components" hand tests |
| `OffsetFacesFeature.inputFaces` (or `faces` before the item), `distance`, `faces` after it; `BRepFace.loops`, `BRepLoop.isOuter`, `BRepLoop.edges`, `Plane.uDirection`; positive distance moves the face outwards | `faces_after` must show the face moved by `distance`; the Offset faces hand test |
| `EmbossFeature.profiles` (`Profile` and `SketchText` items; the area of a text is computed from its outlines), `inputFaces`, `faces` after the item, `isTangentChain`, `depth`, `horizontalDistance`, `verticalDistance`, `rotationAngle`; `BRepFace.area`, `BRepFace.body`; a positive `depth` raises and a negative one sinks; the feature exists only in Fusion builds from September 2025 and is marked preview in the API reference | `volume_after` must differ from `volume_before` by `sum(areas) * abs(depth)` with the sign of `depth`, else the translator refuses; the Emboss hand tests (section 10 of `docs/hand-tests.md`) |
| `SketchText.asCurves()` returns the text outline as closed `Curve3D` loops (lines, arcs, free curves) without changing the design; the points are in sketch or model space; `SketchText.boundingBox` is in sketch space | `space` is decided by the bounding box and `ambiguous` or a failed read gives a text marker; an emboss checks the text area against the measured volume; the Text hand tests (section 11 of `docs/hand-tests.md`) |
| Free curves (`NurbsCurve3D`, `EllipticalArc3D`) evaluate through `CurveEvaluator3D.getPointAtParameter` over `getParameterExtents`, and `getTangent` gives the direction at an end | a curve that cannot be evaluated has no samples and is refused; a missing tangent is left out; the Spline hand tests (section 11 of `docs/hand-tests.md`) |
| `Sketch.parentComponent`, `ConstructionPlane.component`, `BRepFace.body`, `BRepEdge.body` | `foreign` reads them in a try; an unreadable one leaves the record unmarked |
| `SketchEntity.referencedEntity` of an entity projected from another component comes as a proxy whose `assemblyContext.component` is that component (confirmed by a real export: the pipe component was found); the `body` of such an edge and its `nativeObject` token equal the token `bodies_after` gives; `lineOne`, `lineTwo`, `line` and `curve` name the entities of the other line constraints; `ModelParameter.createdBy` of a parameter that `dependentParameters` gives names the same maker as when the parameter is listed from its component (`ModelParameter.component` answered the root for every one); `profile`, `path`, `guideRail`, `loftSections` and `holePositionDefinition` can be read with the marker before a step of another component | a wrong read only leaves a link out; the discovery tries still find a parameter that moves the part; the K10 hand test in `docs/hand-tests.md` |
| `BRepBody.copyToComponent(proxy)` keeps the assembly place | the copy guard in `step_export.py` compares the bounding boxes (1e-3 mm) and refuses before writing |
