# Capture format

The capture is the plain dict the reader (`lib/fusion_reader/`) returns for one design, and the only input of the
pure translator (`lib/translator/`). Fixtures in `tests/fixtures/captures/` use this format. The translator refuses a
capture whose `capture` number is not 1, or that lacks `capture`, `target` or `items`, with a `CaptureError`.

The reader (`lib/fusion_reader/`) walks the timeline and returns one JSON-safe dict, the **capture**. The
translator (`lib/translator/`) reads only the capture. Fixtures are captures written by hand or saved from real
designs (the export writes the capture into `report.json`, section 6), so every translator test runs without
Fusion.

## 1. Rules for every value

- Lengths in mm (Fusion cm times 10), angles in degrees (Fusion radians times 180 / pi), through
  `lib/package/units.py`. Unitless values stay.
- 3D values are in the design's model frame, before any up axis turn. Points and vectors are `[x, y, z]` lists.
- 2D sketch values are in the sketch's own frame: `[x, y]` in mm.
- A frame is `{ "origin": [..], "x": [..], "y": [..], "z": [..] }` (unit axes, model frame), read with
  `Matrix3D.getAsCoordinateSystem()`.
- A plane is `{ "point": [..], "normal": [..] }`. An axis is `{ "point": [..], "dir": [..] }` (dir unit).
- A box is `{ "min": [..], "max": [..] }` from `BRepBody.boundingBox` (`minPoint`, `maxPoint`).
- Bodies are named by `BRepBody.entityToken` plus `BRepBody.name` (fallback when tokens change).
- An entity the reader cannot express becomes `{ "kind": "other", "type": "<objectType>" }`; the translator
  refuses it with a note. The reader never throws for an unknown shape.

## 2. Envelope

```json
{
  "capture": 1,
  "fusion": "2.0.21508",
  "design": "Cable clip",
  "up_axis": "z",
  "target": { "token": "...", "name": "Body1", "box": { "min": [0, 0, 0], "max": [40, 20, 10] }, "volume_mm3": 8000.0 },
  "items": [ ITEM, ... ]
}
```

`target` is the picked body at the end of the timeline (`volume` cm3 times 1000). `items` lists every timeline
item in order. Group objects are skipped; the children of a group are listed as ordinary items.

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
(refused in F3).

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
  `endFaces[0].pointOnFace`, or null. The measured check of the direction.

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
{ "entity_type": "features", "sources": [4], "plane": PLANE, "combine": false }
```

`plane` from a `ConstructionPlane` (`geometry`, a `Plane`: `origin`, `normal`) or a planar `BRepFace`
(`geometry`).

**CombineFeature** (`targetBody`, `toolBodies`, `operation`, `isKeepToolBodies`):

```json
{ "target": BODY, "tools": [BODY, ...], "operation": "cut", "keep_tools": false }
```

**ThreadFeature**: `{ "modeled": bool }` (`isModeled`).

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

Not verified (each has a measured check or a hand test in section 5):

| Item | Check |
|---|---|
| Enum value names: `HoleTypes`, `HoleTapTypes`, `FeatureExtentTypes`, `PatternEntityTypes`, the spacing value of `PatternDistanceTypes`, the rounded value of `ShellTypes`, `Curve3DTypes`, fillet continuity, `ChamferCornerTypes` | the reader maps by name text with a fallback to `other`; hand test (enum names) logs unknown names |
| `ProfileCurve.geometry` in sketch space or model space; `ProfileCurve.sketchEntity` and `SketchCurve.geometry` in sketch space | reader decides per profile and writes `space` (`ambiguous` is refused); hand test 2 (offset, tilted, bottom face sketch) |
| `getAsCoordinateSystem()` returns `(origin, xAxis, yAxis, zAxis)` in Python | hand test 2 |
| `CurveEvaluator3D.getParameterExtents`, `getPointAtParameter`; `SurfaceEvaluator.getNormalAtPoint` | hand test (enum names) |
| A flipped one sided extrude stores a negative distance | `end_offset`; hand test 4 |
| Taper sign (Fusion positive grows or shrinks) | one constant `FUSION_TAPER_SIGN` in `extrude.py`; hand test 4 |
| `ToEntityExtentDefinition`, `TwoSidesDistanceExtentDefinition`, `TwoSidesAngleExtentDefinition`, `FromEntityStartDefinition` field names | reader falls back to `other`; hand test 4 |
| Revolve turning sense | `start_face_normal`; hand test 3 |
| Hole `direction` points into the material; blind depth is measured to the shoulder, not the tip; how a flat drill point shows (`tipAngle` 180 or another member) | `end_points`; hand test 5 |
| `patternElements` includes suppressed elements | translator fills missing lattice places from the quantities; hand test 6 |
| `entityToken` of a body stays the same across marker positions | name fallback; hand test 7 |
| `Timeline.item` walks inside groups; `TimelineGroup.startIndex`, `endIndex` | reader raises `CaptureReadError` when a group child is not in the walk; hand test (enum names) |
| Moving the marker marks the document changed or adds undo entries | hand test 8 |
| `isRollingBallCorner` still on `FilletFeature` (some fillet members are retired) | reader reads it in a try, default true; hand test 6 |
