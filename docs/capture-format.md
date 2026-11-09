# Capture format

The capture is the plain dict the reader (`lib/fusion_reader/`) returns for one design, and the only input of the
pure translator (`lib/translator/`). Fixtures in `tests/fixtures/captures/` use this format, so every translator test
runs without Fusion. They are written by hand or saved from real designs: the export writes the capture into
`report.json` (section 6). The reader writes capture number 3; the translator reads 1, 2 and 3 (number 1 has no
`parameters`, `design_units` or `params`; numbers 1 and 2 have no `targets`, `placement` or component fields, and their
items carry `component_root`). It refuses any other number, or a capture that lacks `capture`, `target` or `items`,
with a `CaptureError`.

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
Both are empty lists when unreadable. The export builds its size table from them
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
tapers, thin walls, modeled threads, face outlines). A fixture with no geometry in its items (the `core_*` cases and
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
  geometry, occurrences, joints and the like; `NOT_MODELING_TYPES` in `lib/translator/capture.py`). Feature readers
  run only for items in the target's component; the other items keep `"data": {}` with their `bodies_after`, health
  and message.
- `entity_context`: `"proxy"` only when `TimelineObject.entity` came as an occurrence proxy and was turned native
  (`nativeObject`) before reading; absent otherwise.
- `bodies_before` (not for suppressed items): the bodies of the target's component at the marker before the item.
- `target_changed`: whether the native target's box (1e-4 mm) or volume changed from the marker before the item to the
  marker after it. `true` also when the target appears or disappears; `null` when it exists on neither side or a
  measure could not be read.
- `bodies_after`: `feature.bodies` read with the marker just after the item. `null` (with an item level
  `"read_error": "bodies: ..."`) when the bodies cannot be read; it is not the same as `[]`, which says the item
  makes no body. The driver must not treat `null` as helper geometry. Items that are not modeling steps get `[]`
  without a read. The translator skips them whatever their bodies say (captures of add-in 0.3.1 have `null` there);
  an occurrence, joint or the like that changes the target is refused.
- `data`: per type, below. Types without a reader (sketches, construction geometry, unknown features) carry
  `"data": {}`. When a reader fails, `data` is `{ "read_error": "<message>" }`.
- A member that cannot be read never becomes a plausible value: it reads as `null` or as an `other` entry
  (`"extent_type": "other"`, `"hole_type": "other"`, `{ "kind": "other" }`), and the translator refuses it.

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
4. The STEP file is written before the capture, with the marker at `end`. The size checks keep it there: the
   parameter store puts the marker back after every recompute and counts only the items before it for health
   (`lib/fusion_reader/rows.py`), and the temporary copy of a component body deletes only what it added
   (`lib/export_plan/temp_copy.py`). `report.json` records `marker` (`position`, `count`).

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
  { "face": true, "type": "BRepFace" }
]
```

Optional keys that let the size probe find the sketch again (section 5, "Probe states"): `sketch_token`
(`Sketch.entityToken`) and `reference` (`{ "kind": "constructionPlane" | "face" | "plane" | "other", "token" }` from
`Sketch.referencePlane`; `token` is empty for a plane without one). Each curve also gets `entity`, the token of its
sketch curve (`ProfileCurve.sketchEntity.entityToken`). A key is left out when Fusion does not give it.

From `Profile.parentSketch.transform`, `Profile.profileLoops`, `ProfileLoop.isOuter`, `ProfileLoop.profileCurves`,
`ProfileCurve.geometry` and `ProfileCurve.geometryType`. A planar face used as a profile is `{ "face": true }`
(the translator refuses it).

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
within 2 mm keep their side of the face at every size setting of the range (each size at its ends, all low, all
high), and a face that lies on a wall stays on it. Where a gap would close or open, the ranges of the sizes it reads
are shortened toward their values (`lib/translator/kept_ranges.py`, each size alone first, then all together); when
a range would shrink to its value or the person typed it, the size cannot follow (fixed, or loose in the export).
In loose mode (the default) the ranges are not shortened: the size stays free over the range Fusion builds and is
listed in `loose` with the values past which the step may stop meeting the part ("past 2.05", "below 0.98"). With
"Keep doubtful sizes fixed" the result lists the shortened ranges in `narrowed` (`name`, `min`, `max`, `reason`); `report.json` adds them to `sizes.narrowed`.

CURVE, in sketch 2D mm, in the order Fusion lists them (not chained, not oriented):

| Fusion geometry | Dict |
|---|---|
| `Line3D` (`startPoint`, `endPoint`) | `{ "kind": "line", "start": [x, y], "end": [x, y] }` |
| `Arc3D` (`center`, `radius`, `startPoint`, `endPoint`) | `{ "kind": "arc", "start", "end", "mid", "center", "radius" }`; `mid` from the evaluator at the middle parameter |
| `Circle3D` (`center`, `radius`) | `{ "kind": "circle", "center", "radius" }` |
| `Ellipse3D` (`center`, `majorAxis`, `majorRadius`, `minorRadius`) | `{ "kind": "ellipse", "center", "major_dir": [x, y], "major_radius", "minor_radius" }` |
| `EllipticalArc3D`, `NurbsCurve3D`, other | `{ "kind": "other", "type": "NurbsCurve3D", "start", "end", "samples": [[x, y], ...] }`, 200 samples by parameter |

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
- `profile_area`, `end_area` (optional, mm2): the area of the first profile and of `endFaces[0]`. Without
  `side_leans`, a tapered extrude of one outline is checked by them (the end face must be smaller for a positive
  recipe taper); a tapered extrude of several outlines is refused. Fusion's positive taper widens the walls (the
  recipe's positive `taperDeg` narrows them), so the translator writes Fusion's angle with the other sign.
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
  `[position]`.
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

**CircularPatternFeature** (`inputEntities`, `axis`, `quantity`, `totalAngle`, `isSymmetric`, `patternElements`,
`suppressedElementsIds`):

```json
{ "entity_type": "features", "sources": [4], "axis": AXIS, "quantity": 6, "total_angle_deg": 360, "symmetric": false, "elements": [...], "suppressed_ids": [] }
```

**MirrorFeature** (`inputEntities`, `mirrorPlane`, `isCombine`):

```json
{ "entity_type": "features", "sources": [4], "plane": PLANE, "combine": false, "target_box_before": { "min": [..], "max": [..] } }
```

`target_box_before`: the target body's box with the marker before the item, or null when it does not exist yet (as
for extrudes).

`plane` from a `ConstructionPlane` (`geometry`, a `Plane`: `origin`, `normal`) or a planar `BRepFace`
(`geometry`). A construction plane adds `token`.

**CombineFeature** (`targetBody`, `toolBodies`, `operation`, `isKeepToolBodies`):

```json
{ "target": BODY, "tools": [BODY, ...], "operation": "cut", "keep_tools": false }
```

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
`lib/fusion_reader/placement.py`); when the target's place cannot be read it stays foreign.

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

Sketch dimensions, construction planes, axes and joints are not listed per item. They are model parameters whose
`created_by.kind` is `sketchDimension`, `constructionPlane`, `constructionAxis` or `joint`.

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
  before it is fixed, with the step's name in the reason. Rounds and chamfers that a pattern or mirror copies take
  their source's written points (formulas included) through each copy's motion; their count is fixed, and a circular
  angle too. A copied uneven chamfer turns its `sizeOn` with the copy. Without sizes the picks stay plain points.
- A formula longer than the app's cap (`MAX_FORMULA_LENGTH` in `lib/params/expressions.py`, 300 characters) fixes
  the sizes it reads, also when a step builds it from several values.
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
- A value that cannot follow its sizes is written as its number and its sizes are recorded (`Context.fix`). By
  default each such size becomes a plain number in a new size table (`with_fixed`) and the walk runs again, until
  nothing new is fixed; `TranslateResult.fixed` lists them as `{ name, reason }` ("... stays fixed: ..."). With
  `translate(..., loose=True)` (what the export uses unless the person ticks "Keep doubtful sizes fixed") these sizes
  stay free: a second walk keeps them in the table, every value that can follow them still does, and the values that
  cannot keep their numbers, so the shape at the current values is the same. In that walk a stuck sketch value
  follows its `rest` (the sizes that still move it), as it does once its own sizes are fixed.
  With `plain=True` (the export's default, with `loose=True`) no minimum is raised and no range is shortened: a size
  that would have needed that is loose instead (`Context.require` and `Context.narrow` record a doubt), and a loose
  size that no formula reads is not a size at all (it is not listed as fixed). The plain export passes no motion, so
  every size behind a sketch dimension, construction plane or axis, or a joint, is loose with a reason.
  `TranslateResult.loose` lists them as `{ name, reason }` ("... may give unexpected results: ..."); a loose size
  that no formula reads is listed under `fixed` instead. A formula too long to copy (`Context.fix_always`) fixes its
  sizes in both modes.
- The recipe is version 12, or the lowest version that holds its steps and selectors (13 with an `offsetFaces` step, 14
  with a `chain` or `faceEdges` pick). With a size table it carries `sizesAsWritten: true` and `sizes`: the sizes that a written
  formula reads, plus the sizes those formulas read. A ticked size that nothing reads is left out, with a note.
  Without a table the recipe has no `sizes`, and no marker.

### Sketch values that follow sizes (`lib/translator/sketch_motion.py`)

The export measures the sketches at other size values (probe states, next section) and fits each value the translator
writes as a sum over Fusion parameters, or marks it stuck (`lib/probe/`). That is the motion file, `probe.motion`:
keys `<item>/p<profile>/l<loop>/<field path>` (loop 0 is the outer one, then the holes; `center.0`, `width`,
`segments.2.through.1`), `<item>/p<profile>/plane` (the sketch plane along its normal, from the component origin),
`<item>/positions/<n>/<0|1|2>` (hole points) and `<item>/axis/point/<0|1|2>` (a revolve axis from a sketch line).
The sketch curves of each profile have `<item>/p<profile>/c<loop>.<curve>/<field>` in the capture's loop and curve
order: a line's `offset` (its distance from the sketch origin along the left normal of its captured direction) and
`turn` (degrees it turned), an arc's `center.0`, `center.1` and `radius`; `curves` lists the profiles
(`<item>/p<profile>`) whose curves were measured. A key that is not listed did not move. The translator uses it like
this:

- `motion=None`: the rule above, sketch sizes fixed up front. `motion=OPTIMISTIC` (the export's first translation):
  sketch values are written as numbers and nothing is fixed for them, so the export can see which sizes to try.
- Each written value with a key becomes a formula over the sizes (`{ "expr": "0.5 * FilterBox_width_mm" }`); a model
  parameter in a sum is written through its own expression. Its number stays the captured one; a formula that misses
  it by more than 1e-3 mm fixes its sizes ("could not be read at other values"). A width, height or radius that would
  reach zero over the size ranges fixes its sizes ("would shrink to nothing").
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
  at each size's ends, all low, all high and the probe's states; otherwise its sizes are fixed ("along a curve"). A
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
  the size range (count formulas such as `ceil(width_count) * 2` are evaluated at the range ends). When the count
  drops below that, the smallest value of the sizes it reads is raised (a whole number for a count, else two
  decimals) and named in a note and in `report.json` (`sizes.raised`); the recipe size `min` and the result dialog
  show it. A size whose minimum the person typed (`SizeTable.typed_ends`: a dialog range or a range comment that
  differs from the default half to double) cannot follow instead. Copies of a circular pattern keep their count and
  angle.
- A taper that follows sizes stays under 45 degrees either way: the ranges of its sizes are shortened.
- A through cut clears the part at the largest sizes tried (`box_max` of the motion file).
- A construction plane or axis that a step uses itself (start from, reach to, turn about, mirror across, with `token`)
  fixes the sizes of the model parameters it made (`created_by.token`); without a token, of every construction plane
  or axis.

### Probe states (`lib/fusion_reader/probe_state.py`)

The size probe sets other size values, recomputes and reads a state with `read_state(design, request, ctx)`.
`request` is `{ "sketches": [token], "points": [token], "lines": [token], "params": [name], "target": true }`. Every
entity is found with `Design.findEntityByToken` (the match without `assemblyContext`; for a proxy only, its
`nativeObject`), so values are in component coordinates like the capture. The result, mm and degrees except `params`:

```json
{
  "sketches": { "<sketch token>": { "frame": FRAME, "profiles": [PROFILE, ...] } },
  "points": { "<sketch point token>": [x, y, z] },
  "lines": { "<sketch line token>": { "point": [x, y, z], "dir": [x, y, z] } },
  "params": { "d12": 2.0 },
  "box": { "min": [..], "max": [..] }
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
- Nothing raises. A part that cannot be read has no key, which the fit treats as unread.

## 6. Report and capture file

The export writes `report.json` into the package: `{ "writer", "outcome": "recipe" | "stepOnly", "items": [ITEM
VERDICT, ...], "capture": CAPTURE }` (verdicts: see the translator, `lib/translator/result.py`). The app never reads it. A report saved from a real
design gives a fixture: its `capture` is copied as is.

`sizes.build_failures` lists the size checks Fusion could not build (value, error, why, and `tries`: every value
tried after it, toward the current value and at the other end of the range). Each end of a checked size's range is
tried: the check's end with a STEP, the other end as a rebuild only (`lib/export_plan/size_narrowing.py`). Where
Fusion cannot build, smaller steps toward the current value are tried; the first that builds ends the range there,
and when none builds the current value ends it. Such an end is listed in `sizes.narrowed` (`side`, the failed value
`from`, the new end `to`, the `note` shown to the person). Only a size that builds at no other value on either side
is fixed. A range the translator shortened (a taper, or in strict mode a step on another component's sketch that must keep
meeting the part) is listed there too, with the old end as `from`.

`sizes.loose` lists the sizes that stay free although the export could not follow them fully (`{ name, reason }` by
recipe size name, as in the manifest's `loose`): from the translator, from a check that moved the part in the
assembly or changed a sketch the probe does not follow, and from the probe. `sizes.fixed` lists the fixed ones.
`keep_doubtful` is true when the person ticked "Keep doubtful sizes fixed", so those sizes were fixed instead.
`check_sizes` is false for the plain export (the default): no check rows and no check STEPs, but the probe rows run
(recompute only, parameters restored), so `checks` in the manifest is empty, the report has a `probe` when a sketch
could be followed, and no `raised` or `narrowed`.

## 7. API names and what is not verified

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
| `CurveEvaluator3D.getParameterExtents`, `getPointAtParameter`; `SurfaceEvaluator.getNormalAtPoint` | the "Capture reader calls to watch" lists in `docs/hand-tests.md` |
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
| `Sketch.parentComponent`, `ConstructionPlane.component`, `BRepFace.body`, `BRepEdge.body` | `foreign` reads them in a try; an unreadable one leaves the record unmarked |
| `BRepBody.copyToComponent(proxy)` keeps the assembly place | the copy guard in `step_export.py` compares the bounding boxes (1e-3 mm) and refuses before writing |
