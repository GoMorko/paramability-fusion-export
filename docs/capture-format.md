# Capture format

The capture is the plain dict the reader (`lib/fusion_reader/`) returns for one design, and the only input of the
pure translator (`lib/translator/`). Fixtures in `tests/fixtures/captures/` use this format, so every translator test
runs without Fusion. They are written by hand or saved from real designs: the export writes the capture into
`report.json` (section 6). The reader writes capture number 2; the translator reads 1 and 2 (number 1 has no
`parameters`, `design_units` or `params`). It refuses any other number, or a capture that lacks `capture`, `target` or
`items`, with a `CaptureError`.

## 1. Rules for every value

- Lengths in mm (Fusion cm times 10), angles in degrees (Fusion radians times 180 / pi), through
  `lib/package/units.py`. Unitless values stay.
- 3D values are in the design's model frame, before any up axis turn. Points and vectors are `[x, y, z]` lists.
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
  "capture": 2,
  "fusion": "2.0.21508",
  "design": "Cable clip",
  "up_axis": "z",
  "design_units": "mm",
  "parameters": { "user": [ PARAMETER, ... ], "model": [ PARAMETER, ... ] },
  "target": { "token": "...", "name": "Body1", "box": { "min": [0, 0, 0], "max": [40, 20, 10] }, "volume_mm3": 8000.0 },
  "items": [ ITEM, ... ]
}
```

`design_units` is the design's default length unit (`fusionUnitsManager.defaultLengthUnits`, `mm` when unreadable); a
bare number in a length formula is read in it. `parameters.user` is `list_user_parameters(design)` and
`parameters.model` is `list_model_parameters(rootComponent)` (`lib/fusion_reader/parameters.py`: name, expression, value
in Fusion's internal cm and radians, unit, kind, favourite, dependency lists, and for model parameters `role` and
`created_by`). Both are empty lists when unreadable. The export builds its size table from them
(`lib/params/size_table.py`); the translator reads only `data.params` of the items and, through the size table,
the `created_by` kinds.

`target` is the picked body at the end of the timeline (`volume` cm3 times 1000). `items` lists every timeline
item in order. Group objects are skipped; the children of a group are listed as ordinary items, and the reader raises
when a group lists a child the walk did not reach.

What the translator trusts: `target.token` and `target.name` (to follow the body), the item fields in section 5,
and the item level `target_box_before` boxes (through all cuts, mirrors). It never reads `target.box` or
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
  "component_root": true,
  "bodies_after": [{ "token": "...", "name": "Body1" }],
  "data": { }
}
```

- `type`: the part of `entity.objectType` after the last `::` (`adsk::fusion::ExtrudeFeature` gives
  `ExtrudeFeature`). Items without an entity: `"type": "none"`.
- `health`: from `TimelineObject.healthState` (`ok`, `warning`, `error`); `message` from
  `errorOrWarningMessage`.
- `component_root`: the feature's `parentComponent` is the root component.
- `bodies_after`: `feature.bodies` read with the marker just after the item. `null` (with an item level
  `"read_error": "bodies: ..."`) when the bodies cannot be read; it is not the same as `[]`, which says the item
  makes no body. The driver must not treat `null` as helper geometry.
- `data`: per type, below. Types without a reader (sketches, construction geometry, unknown features) carry
  `"data": {}`. When a reader fails, `data` is `{ "read_error": "<message>" }`.
- A member that cannot be read never becomes a plausible value: it reads as `null` or as an `other` entry
  (`"extent_type": "other"`, `"hole_type": "other"`, `{ "kind": "other" }`), and the translator refuses it.

## 3. Walk and marker

`lib/fusion_reader/capture.py`, `read_capture(design, body) -> dict`:

1. Refuse unless `timeline.markerPosition == timeline.count` (existing `marker_at_end`).
2. For `k` from 0 to `count`: set `timeline.markerPosition = k`. Read `bodies_after` of item `k - 1` and the
   inputs of item `k` (profiles, edges, faces, tool bodies, the target box before it). One recompute per item.
3. `finally`: `timeline.moveToEnd()`, then check `markerPosition == count`.
   After that, each `timeline.timelineGroups` entry (`startIndex` to `endIndex`) must be covered by the walk;
   else `read_capture` raises `CaptureReadError` and the export lands as a fixed shape.
4. The STEP file is written before the capture, with the marker at the end.

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

From `Profile.parentSketch.transform`, `Profile.profileLoops`, `ProfileLoop.isOuter`, `ProfileLoop.profileCurves`,
`ProfileCurve.geometry` and `ProfileCurve.geometryType`. A planar face used as a profile is `{ "face": true }`
(the translator refuses it).

`space` says how the curve space was decided: `sketch` or `model` (the reader mapped model space curves into sketch
2D) or `ambiguous`. A curve off the plane z = 0 proves model space. In the plane z = 0 with a sketch frame other
than the identity, the reader compares the curve with `ProfileCurve.sketchEntity`; if that cannot decide it writes
`ambiguous` and the translator refuses the profile.

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

- `operation`: `join`, `cut`, `intersect`, `newBody`, `newComponent` (from `FeatureOperations`).
- `start`: `{ "kind": "profilePlane" }`, `{ "kind": "offset", "offset": mm }` (`OffsetStartDefinition.offset`),
  `{ "kind": "fromEntity", "plane": PLANE or null }` (`FromEntityStartDefinition`).
- `extent_type`: `one`, `two`, `symmetric`.
- EXTENT: `{ "kind": "distance", "distance": mm, "taper_deg": d }` (`DistanceExtentDefinition.distance`, the value
  as Fusion stores it, sign kept), `{ "kind": "throughAll", "positive": bool, "taper_deg": d }`
  (`ThroughAllExtentDefinition.isPositiveDirection`), `{ "kind": "all" }`, `{ "kind": "toEntity", "plane": PLANE or
  null, "offset": mm }`, `{ "kind": "other", "type": "..." }`.
- `symmetric`: `{ "distance": mm, "full_length": bool, "taper_deg": d }`
  (`SymmetricExtentDefinition.distance`, `isFullLength`, `taperAngle`).
- `target_box_before`: the target body's box with the marker before the item, or null when it does not exist yet.
- `end_offset`: signed distance along the first profile's sketch `z` from its sketch plane to
  `endFaces[0].pointOnFace`, or null. The measured check of the direction and, for one side, symmetric (half
  length) and two sided extrudes, of the length: the translator refuses when `abs(end_offset - start shift)` is not
  the planned length within 1e-3 mm.
- `profile_area`, `end_area` (optional, mm2): the area of the first profile and of `endFaces[0]`. Needed for a tapered
  extrude: the end face must be smaller for a positive recipe taper, else the translator refuses.
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
  "other" }`.
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
      "edges": [EDGE, ...]
    }
  ]
}
```

- `kind`: `constant` (`ConstantRadiusFilletEdgeSet`: `radius`, `edges`, `isTangentChain`, `continuity`),
  `variable`, `chordLength`, `asymmetric`, `other`.
- The reader expands the input: a face gives its `BRepFace.edges`; a tangent chain gives
  `BRepEdge.tangentiallyConnectedEdges`. A feature as input is listed in `input_kinds` as `feature` and not
  expanded.
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
- `distance_type`: `spacing` or `extent`.
- `elements`: every `PatternElement` (`id`, `isSuppressed`, `transform` as a frame; the first is the identity).

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
(`geometry`).

**CombineFeature** (`targetBody`, `toolBodies`, `operation`, `isKeepToolBodies`):

```json
{ "target": BODY, "tools": [BODY, ...], "operation": "cut", "keep_tools": false }
```

**ThreadFeature**: `{ "modeled": bool }` (`isModeled`).

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

How the translator uses them (`translate(capture, size_table=table)`):

- A value is written as `{ "expr": formula }` (never `{ "size": ... }`) when its expression translates, reads at least
  one free size, gives the unit of the field and equals the measured number within 1e-6. Lengths written as absolute
  values (extrude and hole depths, spacing) must also stay above zero over the size range; counts at least 1.
  A negative parameter is written negated.
- Symmetric half length is written as `2 * (formula)`. An extent spacing is `(distance) / ((count) - 1)`. Hole
  tip outlines and counterbore or countersink sizes follow sizes point by point.
- Values that stay numbers while a size reaches them: a sketch (points, placements, construction geometry), the start
  offset, the "up to" offset, a tip angle, a countersink angle, a full circular turn, a revolve that is not a plain
  part turn, and a pattern whose copies are left out by number or are rounds copied one by one. The sizes behind
  them are fixed.
- Every size that a model parameter created by a sketch dimension, construction plane or axis, or joint reads is
  fixed up front (reason "stays fixed for now: it changes a sketch"). Sketches follow sizes in a later version.
- Each fixed size becomes a plain number in a new size table (`with_fixed`) and the walk runs again, until nothing
  new is fixed. `TranslateResult.fixed` lists them as `{ name, reason }`.
- The recipe is version 12. With a size table it carries `sizesAsWritten: true` and `sizes`: the sizes that a written
  formula reads, plus the sizes those formulas read. A ticked size that nothing reads is left out, with a note.
  Without a table the recipe has no `sizes`, and no marker.

## 6. Report and capture file

The export writes `report.json` into the package: `{ "writer", "outcome": "recipe" | "stepOnly", "items": [ITEM
VERDICT, ...], "capture": CAPTURE }` (verdicts: see the translator, `lib/translator/result.py`). The app never reads it. The owner can send it from a real
design, and its `capture` becomes a fixture.

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
| Enum value names: `HoleTypes`, `HoleTapTypes`, `FeatureExtentTypes`, `PatternEntityTypes`, the spacing value of `PatternDistanceTypes`, the rounded value of `ShellTypes`, `Curve3DTypes`, fillet continuity, `ChamferCornerTypes` | the reader maps by name text with a fallback to `other`; the "Capture reader calls to watch" lists in `docs/hand-tests.md` logs unknown names |
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
| `isRollingBallCorner` still on `FilletFeature` (some fillet members are retired) | reader reads it in a try, default true; the Bin test |
| The members in the `params` table return a `ModelParameter` (name, expression, value): `DistanceExtentDefinition.distance`, `taperAngleOne` and `taperAngleTwo`, `OffsetStartDefinition.offset`, the `HoleFeature` size members, `ConstantRadiusFilletEdgeSet.radius`, chamfer set distances, `insideThickness`, pattern `quantityOne`, `distanceOne` and the circular ones | a member that is not one adds nothing and the value stays a number; the sizes hand test logs which members gave a parameter |
| `ModelParameter.createdBy` kinds and `name` for a sketch dimension | the kind comes from the type name; the sketch rule needs only the kind |
