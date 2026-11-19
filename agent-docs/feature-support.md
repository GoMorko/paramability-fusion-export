# Feature support

The tables show which Fusion design actions each export copies, and what could be copied later.
They are for ParamabilityExport 0.14.6.
`agent-docs/limits.md` (Export for Paramability) and `agent-docs/orca-output.md` (Export for Orca) have the details.

## The two exports

- **Export for Paramability** writes a `.paramability` recipe. The Paramability app rebuilds the part. The people who
  download it can change its sizes.
- **Export for Orca (experimental)** writes an OrcaSlicer 2.5 project. Orca's Design tab rebuilds the part. Its
  variables follow your user parameters.

## How to read the tables

Each table has one row for each Fusion action.
A cell that says "See notes" has its details in a list under the table.
In those lists, "Both" means both exports.

The words in the cells:

- **Copied**: the step is copied, and its sizes follow the parameters.
- **Partly**: the step is copied, but some of it is left out or keeps a fixed number. The note says what.
- **Left out**: the step is not copied. The result window gives the reason and, when there is one, a tip.
- **Not read**: the add-in passes the item by. It changes no shape of the part.

The words in the "possible later" columns:

- **Yes, add-in only**: the add-in can do it alone.
- **Yes, needs an app change**: the Paramability app cannot rebuild it yet.
- **Needs Orca**: Orca's Design tab has no such feature, or cannot tie it to a variable.
- **No**: the reason is in the note.
- **-**: it is copied already.

A step that one export leaves out makes the copy differ from the Fusion part.
Later steps are still copied when they can be.

## Sketch

| Fusion action | Paramability now | Paramability possible later | Orca now | Orca possible later | Notes |
| --- | --- | --- | --- | --- | --- |
| Line | Copied | - | Partly | Needs Orca | Orca: an outline of lines in an extrude without taper follows at its corners. Other outlines keep their numbers. |
| Rectangle | Copied | - | Copied | - | Orca: width and height follow in extrudes, sweeps and lofts. In a revolve it keeps its numbers. |
| Circle | Copied | - | Copied | - | Orca: the radius follows. A hole circle whose centre moves becomes an Orca hole. |
| Arc, sketch fillet | Copied | - | Partly | Needs Orca | Orca keeps arcs as numbers. |
| Polygon | Copied | - | Partly | Needs Orca | Orca: as for lines. |
| Slot | Copied | - | Partly | Needs Orca | Orca: the arcs keep their numbers. |
| Ellipse | Copied | - | Copied, fixed numbers | Yes, add-in only | See notes. |
| Spline, conic curve | Partly | No | Partly | No | The shape is copied as fixed numbers. The points of a free curve are not a formula of the sizes. Orca: only a spline that Fusion gives exactly. |
| Text | Partly | Yes, add-in only | Partly | Needs Orca | See notes. |
| Offset | Copied | - | Partly | Needs Orca | Orca: as for the curves it makes. |
| Project, Intersect, Include 3D geometry | Copied | - | Partly | Needs Orca | See notes. |
| Constraints | Copied | - | Partly | Needs Orca | See notes. |
| Sketch dimensions | Copied | - | Partly | Needs Orca | See notes. |
| Construction lines and points | Copied | - | Partly | Needs Orca | They build nothing. They place other curves. |
| Sketch rectangular or circular pattern | Copied | - | Partly | Needs Orca | Orca: the copies keep their numbers. |
| Sketch on a face of the part | Copied | - | Partly | Needs Orca | Orca: the sketch plane keeps its place. Every size read before the sketch is marked. |

Notes for Sketch:

- **Ellipse**
  - Paramability: a full ellipse is copied. An elliptical arc is copied as spline segments with fixed numbers.
  - Orca: a full ellipse is written as an ellipse curve with its current numbers. The curve has a centre, a major
    radius, a minor radius and the direction of the major axis.
  - Orca: an elliptical arc is written as an elliptical arc curve. It has those numbers and two angles. This works
    when its ends come out as Fusion measured them. Otherwise the outline is left out.
  - The sizes that move them are marked, as for other curves that keep numbers.
- **Text**
  - Paramability: each letter is an outline. The text height is not a size. There are at most 400 outlines.
  - Orca: each letter is a fixed outline in a sketch of its own. Only the depth follows.
  - Orca: the extrude is one side or symmetric, with no taper. It is not with other outlines in one extrude.
- **Project, Intersect, Include 3D geometry**
  - Paramability: it follows what the size tries measure. From another component it may give unexpected results.
  - Orca: it keeps its place. The sizes read before the sketch are marked.
- **Constraints**
  - Paramability: Fusion solves them during the size tries.
  - Orca: the add-in solves them itself. It does not read smooth, polygon, sketch pattern or face constraints.
- **Sketch dimensions**
  - Paramability: lengths follow. Angles follow through sine and cosine. Each value has up to 3 terms.
  - Orca cannot tie a sketch dimension to a variable. Only rectangle sides, circle radii and corners of straight
    outlines follow.

## Create

| Fusion action | Paramability now | Paramability possible later | Orca now | Orca possible later | Notes |
| --- | --- | --- | --- | --- | --- |
| Extrude: one side, distance | Copied | - | Copied | - | |
| Extrude: symmetric | Copied | - | Copied | - | |
| Extrude: two sides | Partly | - | Copied | - | See notes. |
| Extrude: To object, flat face or plane square to it | Copied | - | Copied | - | See notes. |
| Extrude: To object, tilted or curved | Partly | Yes, add-in only | Left out | Needs Orca | See notes. |
| Extrude: All, cut or intersect | Copied | - | Copied | - | Orca: a one way cut with material behind its sketch is a 1000 mm cut. |
| Extrude: All, join or new body | Partly | - | Left out | Needs Orca | See notes. |
| Extrude: start offset | Copied | - | Partly | Needs Orca | Orca: the offset keeps its number. |
| Extrude: start From object | Copied | - | Partly | Needs Orca | Orca: the sketch plane moves to the face, but does not follow it. |
| Extrude: start From object with an offset | Copied | - | Partly | Needs Orca | See notes. |
| Extrude: taper | Copied | - | Partly | Needs Orca | Paramability: under 45 degrees. A tapered cut through all both ways is left out. Orca: not with holes in the outline, not through all. |
| Extrude: new body, join, cut | Copied | - | Copied | - | See notes. |
| Extrude: intersect | Partly | Yes, add-in only | Copied | - | See notes. |
| Extrude, revolve or loft: new component | Copied | - | Copied | - | See notes. |
| Extrude of a flat face of the part | Copied | - | Partly | Needs Orca | See notes. |
| Thin extrude: one closed outline | Partly | Yes, add-in only | Partly | Yes, add-in only | See notes. |
| Thin extrude: open line | Partly | Yes, add-in only | Partly | Yes, add-in only | See notes. |
| Thin extrude: several outlines, holes, two ways, To object, taper | Left out | Yes, needs an app change | Left out | Needs Orca | |
| Revolve: full turn or angle | Copied | - | Copied | - | See notes. |
| Revolve: symmetric | Copied | - | Copied | - | See notes. |
| Revolve: two sides with two angles | Copied | - | Partly | Needs Orca | See notes. |
| Revolve: outline with holes, several outlines | Copied | - | Copied | - | See notes. |
| Revolve or circular pattern: axis on a cone or torus face | Copied | - | Copied | - | See notes. |
| Sweep: path in one plane (lines, arcs, splines) | Copied | - | Partly | Needs Orca | See notes. |
| Sweep: path in 3D | Partly | Yes, needs an app change | Left out | Needs Orca | Paramability: lines joined by tangent arcs, as measured. Splines in 3D are left out. |
| Sweep: twist, taper, parallel orientation | Copied | - | Left out | Needs Orca | Paramability: with a note to check the shape. A twist together with a taper is left out. |
| Sweep: guide rail, guide surface | Left out | Yes, needs an app change | Left out | Needs Orca | |
| Loft: two outlines | Copied | - | Partly | Needs Orca | See notes. |
| Loft: three or more outlines | Left out | Yes, add-in only | Left out | Needs Orca | The app lofts through many outlines. Check that the smooth shape matches Fusion's. |
| Loft: rails, centre line, point or tangent ends, closed | Left out | Yes, needs an app change | Left out | Needs Orca | |
| Rib, Web | Partly | Yes, add-in only | Partly | Yes, add-in only | See notes. |
| Emboss: flat face | Copied | - | Partly | Yes, add-in only | See notes. |
| Emboss: curved face, tangent chain | Left out | Yes, needs an app change | Left out | Needs Orca | |
| Hole: simple, counterbore, countersink | Copied | - | Copied | - | |
| Hole: depth distance or through all | Copied | - | Copied | - | |
| Hole: To face | Copied | - | Copied | - | See notes. |
| Hole: drill point | Copied | - | Partly | Needs Orca | Orca: the drill point is left flat. |
| Hole: tapped, cosmetic thread | Copied | - | Copied | - | Cut at the drill size Fusion measured (the thread's minor diameter). |
| Hole: tapped, modeled thread | Copied | - | Partly | Needs Orca | See notes. |
| Hole: taper tapped | Left out | Yes, needs an app change | Left out | Needs Orca | |
| Thread: modeled | Copied | - | Partly | Needs Orca | See notes. |
| Thread: cosmetic | Copied | - | Copied | - | It changes no shape. |
| Thread: other forms, tapered | Left out | Yes, needs an app change | Left out | Needs Orca | |
| Box, Cylinder, Sphere, Torus | Left out | Yes, add-in only | Left out | Yes, add-in only | See notes. |
| Coil | Partly | Yes, needs an app change | Left out | Needs Orca | See notes. |
| Pipe | Partly | Yes, add-in only | Partly | Yes, add-in only | See notes. |
| Rectangular pattern of features | Copied | - | Copied | - | Count and spacing follow. Orca: no rounds or chamfers among the copied steps. |
| Circular pattern of features | Copied | - | Copied | - | Count and angle follow. Paramability: an even count may give unexpected results. |
| Pattern with suppressed copies | Copied | - | Left out | Needs Orca | Orca's pattern cannot leave copies out. |
| Pattern of bodies, joined by a Combine | Copied | - | Partly | Yes, add-in only | See notes. |
| Pattern or mirror of faces | Left out | Yes, needs an app change | Left out | Needs Orca | |
| Path pattern | Partly | Yes, needs an app change | Partly | Needs Orca | See notes. |
| Mirror of features | Copied | - | Copied | - | Orca: the mirror plane keeps its place. |
| Mirror of bodies, joined to the part | Copied | - | Copied | - | |
| Thicken | Left out | Yes, needs an app change | Left out | Needs Orca | The app does not rebuild surfaces. |
| Boundary Fill | Left out | Yes, needs an app change | Left out | Needs Orca | |

Notes for Create:

- **Extrude: two sides**
  - Paramability: an intersect to two sides is one tool body of both sides.
  - Both: two sides that end on the same side of the sketch are left out.
  - Orca: a tapered intersect to two sides is copied.
- **Extrude: To object, flat face or plane square to it**
  - Paramability: it follows the face.
  - Orca: it uses the measured distance. It follows an offset plane or the end face of a copied extrude.
  - Both: with Chain Faces on, it is copied only when the outline lands on the face alone. The sizes that may move
    the face or the outline are marked.
- **Extrude: To object, tilted or curved**
  - Paramability: one side, no taper, no offset, and a face of the same body.
  - Paramability: with Chain Faces on, a tilted flat face is copied only when the outline lands on it alone.
  - Paramability: a face that a size may move is followed only when a copied extrude made it. Otherwise the step is
    left out.
  - Orca names a face by its own numbering.
- **Extrude: All, join or new body**
  - Fusion ends it where the part ends.
  - Paramability copies it only when all of these are true:
    - it goes one way, with no taper and no thin wall;
    - the picked body is the only body it joins;
    - Fusion's end is on the far side of that body.
  - The sizes that may change the body before it or move its outline are marked.
  - A new body has no body before it, so it is left out.
- **Extrude: start From object with an offset**
  - Both: the start face that Fusion measured (or the end cap of a join) shows which way the offset goes. Without it
    the step is left out.
  - Orca: the sketch plane moves to the face plus the offset. The offset keeps its number.
- **Extrude: new body, join, cut**
  - Both: a new body from several outlines that makes several bodies is left out.
  - Orca: a cut that splits the part is left out.
- **Extrude: intersect**
  - Paramability: one outline only.
  - Orca: several outlines, and the two tapered halves of a two sided extrude, are one tool body. One Boolean
    intersects it with the part.
  - Orca: the step is left out when Fusion leaves the pieces as several bodies, or when no outline meets the part.
- **Extrude, revolve or loft: new component**
  - Both: the body it makes is copied. Its sketch is from the component that was active. It is placed through the
    assembly.
  - A sketch of a component placed more than once is left out.
  - A sweep made so is left out. Its path stays in the other component.
- **Extrude of a flat face of the part**
  - Paramability: it follows when the face is the end of an earlier extrude without taper. Otherwise the face is
    measured, and the sizes are marked.
  - Orca: the face as it is now.
- **Thin extrude: one closed outline**
  - Paramability: one way, no taper, no To object. Sharp wall corners are rounded, with a note.
  - Orca: one rectangle or one circle, one way or symmetric, no taper.
  - Orca: the wall is the outer outline less the inner outline. Their sizes are the drawn sizes plus or minus the
    thickness.
  - Orca: the end face that Fusion measured must show the side of the wall and sharp corners.
  - Orca: other outlines are left out.
- **Thin extrude: open line**
  - Paramability: straight lines drawn one after the other, one way or symmetric, no taper. The ends are square and
    the corners are sharp, as in Fusion. The faces that Fusion made must show the side of the wall.
  - Paramability: a line with arcs is also copied. Each arc must meet the next line or arc smoothly. There is no
    corner next to an arc, and an arc is at most half a circle.
  - Paramability: such a wall is the outline of its wall, with lines and arcs and with numbers. The line and the
    thickness are marked. This works when the part grew by exactly that outline times the length.
  - Orca: one straight line with the wall centred on it is a rectangle. Its length and thickness follow.
  - Orca: any other line is the outline of its wall, drawn with numbers. The line and the thickness are marked.
  - Both: a corner next to an arc is left out.
- **Revolve: full turn or angle**
  - Paramability: a later shell, fillet or chamfer that picks its faces or edges follows its sizes. This holds also:
    - on the inner walls that a shell leaves on a full turn;
    - on an end face whose angle stays.
  - Paramability: a pick on an end face that turns with a size keeps its place, and the sizes are marked. The same
    holds for a pick inside a shelled part turn.
  - Orca: the axis is in the sketch plane. Each outline is on one side of it.
  - Orca: a cut that splits the part is left out.
- **Revolve: symmetric**
  - Fusion's angle is the turn to each side. An angle of 180 degrees or more to each side closes the ring.
  - Orca: an angle that follows a size is two turns, one to each side. A later round or chamfer of a group of edges
    on that part is left out.
  - Orca: the angle keeps its number for an intersect. It also keeps its number for a cut when one half would cut
    nothing.
- **Revolve: two sides with two angles**
  - The step is left out when one angle is 90 or 270 degrees and the start face fits both sides.
  - Two equal angles keep their numbers.
  - Orca: both angles keep their numbers.
- **Revolve: outline with holes, several outlines**
  - Paramability: outlines that share a line make one outline for the picks of later steps. So a round or chamfer
    where they meet follows the sizes. This holds also inside a shell.
  - Paramability: when the outlines overlap, or a size moves one so that they meet in another way, such a pick keeps
    its place. The sizes are marked.
  - Orca: each hole is turned and cut away. Each outline is turned by itself.
  - Orca: these cases are left out:
    - a new body made of separate outlines;
    - outlines that turn different ways (on two sides of the axis), unless the turn is a full circle;
    - a join of outlines whose turns overlap;
    - a cut where one outline would cut nothing after the others. An outline whose turn lies inside the others' turns
      is dropped instead.
  - Orca: a later round or chamfer of a group of edges on the part is left out.
- **Revolve or circular pattern: axis on a cone or torus face**
  - A cylinder, a cone or a torus face turns about its own axis.
  - A sphere or a free-form face has no axis. The step is left out.
  - The sizes that may move the face are marked.
- **Sweep: path in one plane (lines, arcs, splines)**
  - Paramability: a path of lines and arcs follows sizes. A spline path is copied as measured.
  - Orca: the path keeps its numbers. One outline without holes. No sharp corners.
- **Loft: two outlines**
  - Both: free ends, no rails.
  - Paramability: straight faces between the outlines.
  - Orca: two circles, or two straight outlines in parallel planes whose corners pair up. No holes.
- **Rib, Web**
  - Both: straight lines drawn one after the other, no draft, no fillet. The copy is a thin wall along each line.
  - Both: the faces that Fusion made must show the wall. The part must grow by the whole wall.
  - Both: these cases are left out:
    - a wall that runs into the part (where Fusion stops it);
    - a web whose lines Fusion stretches to the part.
  - A rib To Next that Fusion fills up to the part (a gusset in a corner) is copied as the outline that Fusion made,
    with numbers. This needs the faces and the volume to prove it. Only its thickness follows.
  - To Next keeps the depth that Fusion measured. The sizes before the step are marked.
  - A wall that may run into the part at other sizes marks its depth.
  - The sizes before the step are marked, unless the wall stands on the face that its sketch is drawn on.
  - Orca: the thickness and depth follow, as for a thin extrude of an open line. Orca's own Rib is not used yet.
- **Emboss: flat face**
  - Both: as an extrude from the face. It is not moved or turned on the face.
  - Orca: the depth follows. An outline that Fusion trims to its face is left out.
- **Hole: To face**
  - Both: the face or plane must be flat and square to the hole. The hole end must be flat.
  - Orca: it uses the measured depth. It follows an offset plane or the end face of a copied extrude.
- **Hole: tapped, modeled thread**
  - Paramability: through all holes need an export with this version.
  - Orca: simple and counterbore holes, right hand only. The thread start under a counterbore keeps its number.
- **Thread: modeled**
  - Metric and Unified 60 degree threads.
  - Paramability: at most 100 turns of threads and coils. Not in a tool body.
  - Orca: right hand only.
- **Box, Cylinder, Sphere, Torus**
  - Reason: Fusion does not tell add-ins where the step sits or how it joins the part.
  - Tip: "Draw it in a sketch instead: extrude a rectangle or a circle, or revolve a half circle or a circle."
  - The Fusion API reference and the API stubs (`adsk/fusion.py`, Fusion 2706) give `BoxFeature`, `CylinderFeature`,
    `SphereFeature` and `TorusFeature` only the members of `Feature` plus `deleteMe` and `dissolve`. They have no
    size, plane, centre, direction or operation.
  - `BoxFeatures`, `CylinderFeatures`, `SphereFeatures` and `TorusFeatures` have only `item`, `itemByName` and
    `count`. So a script cannot make these steps either.
  - The sizes may come from `ModelParameter.createdBy` and `role`, as for a coil. No live check has shown that yet
    (hand check 101, PM1).
  - A copy would have to measure the place and the operation from the faces and volumes, as the coil reader does.
- **Coil**
  - Paramability: round, square or triangle section, no taper, at most 8 coils. A spiral, a taper and half turns are
    left out.
  - Orca: left out. Its sweep along a helix keeps the wire square to the helix. Fusion keeps it on a plane through
    the axis. So the ends and the thickness of the wire differ.
  - A sweep that keeps the axis direction, as Orca's thread does, would copy it.
- **Pipe**
  - Paramability: a circle section, solid or hollow, along the whole path, as a sweep of the circle. Sharp corners are
    mitred.
  - Paramability: a square or triangle section is left out. A closed path that starts on a sharp corner is left out
    too. Both stay out until a hand check shows how Fusion builds them.
  - Orca: a circle section, solid or hollow, along the whole path, as a sweep of the circle.
  - Orca: the path is as for a sweep (in one plane, no sharp corners).
  - Orca: the diameter and the wall follow variables. The path keeps its numbers.
- **Pattern of bodies, joined by a Combine**
  - Orca: a rectangular or circular pattern, or a mirror, whose copies one Combine joins or cuts together with their
    source. Spacing and angle follow. The count keeps its number.
  - Orca: the step is left out when the Combine takes only some copies, when it intersects, or when a step changes a
    copy on its own.
- **Path pattern**
  - Paramability: a path of one line, arc or circle. Count and distance follow. Their ranges stop where the copies
    would leave the path. Other paths need an app change.
  - Orca: a path of one line, arc or circle. An arc whose copies keep their direction is also copied. Then the
    distance keeps its number.
  - Orca: count and distance follow. The parameter's line says how far they may go before the copies leave the path.
  - Orca's pattern along a curve does not space copies by length on other curves.

## Modify

| Fusion action | Paramability now | Paramability possible later | Orca now | Orca possible later | Notes |
| --- | --- | --- | --- | --- | --- |
| Press Pull of a flat face (Offset Faces) | Copied | - | Left out | Needs Orca | See notes. |
| Press Pull of a whole round face (a pin, a boss or a bore) | Copied | - | Copied | - | See notes. |
| Press Pull of another curved face, or of part of a round face | Left out | Yes, needs an app change | Left out | Needs Orca | The app moves flat faces and whole round faces only. |
| Fillet: constant radius | Copied | - | Partly | Needs Orca | See notes. |
| Fillet: variable radius | Partly | Yes, needs an app change | Left out | Needs Orca | See notes. |
| Fillet: chord length | Partly | - | Left out | Needs Orca | Paramability: a plain round of the radius the chord gives, where the faces meet at the same angle along each edge. |
| Fillet: two radii, curvature continuity | Left out | Yes, needs an app change | Left out | Needs Orca | |
| Fillet: setback corners | Partly | Yes, needs an app change | Partly | Needs Orca | Copied with rolling ball corners, with a note. |
| Fillet or chamfer with several sets picked in different ways (edges, faces, chains) | Copied | - | Partly | Needs Orca | See notes. |
| Fillet or chamfer set picked by a face with Tangent Chain on, no smooth neighbour faces | Left out | - | Left out | - | See notes. |
| Rule Fillet, Full Round Fillet | Left out | Yes, add-in only | Left out | Needs Orca | The add-in does not read these step types yet. |
| Chamfer: equal distance | Copied | - | Partly | Needs Orca | Orca: the same edges as for a fillet. |
| Chamfer: two distances, distance and angle | Copied | - | Left out | Needs Orca | Orca makes only even chamfers. Paramability: two distances need sides that the add-in could measure. |
| Shell: inside, open faces | Copied | - | Left out | Needs Orca | Orca opens only a face that it picks by its own numbering. |
| Shell: outward, closed, rounded corners | Copied | - | Left out | Needs Orca | See notes. |
| Draft | Partly | Yes, add-in only | Left out | Needs Orca | See notes. |
| Scale of bodies | Copied | - | Left out | Needs Orca | See notes. |
| Scale of sketches, or of a body and a sketch together | Left out | Yes, add-in only | Left out | Needs Orca | |
| Combine: join, cut, intersect | Copied | - | Copied | - | See notes. |
| Replace Face | Left out | Yes, needs an app change | Left out | Needs Orca | |
| Split Face | Copied | - | Copied | - | See notes. |
| Split Body: plane or flat face | Copied | - | Partly | Needs Orca | The part keeps its piece. Orca: the plane keeps its place. |
| Split Body: solid body | Copied | - | Copied | - | |
| Split Body: surface or curved face | Left out | Yes, needs an app change | Left out | Needs Orca | |
| Move/Copy of bodies: move, rotate, free move | Copied | - | Partly | Needs Orca | Orca: a turn about an axis follows its angle. Orca cannot tie a move distance to a variable. |
| Move/Copy of bodies: point to point, to position, along an entity | Partly | Yes, add-in only | Partly | Needs Orca | Written as the numbers Fusion measured. |
| Move/Copy of faces | Left out | Yes, needs an app change | Left out | Needs Orca | |
| Copy and paste a body | Copied | - | Copied | - | Paramability writes the steps of the source again. Orca: the same, as a body of its own. A paste of a body of another component is left out. |
| Align | Left out | Yes, add-in only | Left out | Yes, add-in only | A step type that the add-in does not know is left out. |
| Remove of another body | Not read | No | Not read | No | It changes nothing in the part. |
| Delete Face | Left out | Yes, needs an app change | Left out | Needs Orca | |

Notes for Modify:

- **Press Pull of a flat face (Offset Faces)**
  - Paramability: faces that meet are copied too. Faces with a leaning or rounded side are copied too.
  - Paramability: the app lets the faces around them follow.
- **Press Pull of a whole round face (a pin, a boss or a bore)**
  - Both: the face goes all the way round. Both ends are flat and square to its axis. The new radius stays clear of
    the other edges of the end faces.
  - Paramability: it needs an app that reads recipe version 17. It is checked over the size range of the distance.
  - Orca: one round face per Press Pull. It is built as a ring joined to the part or cut from it.
  - Orca: the distance follows its variable within the limits on the parameter's line.
  - Orca: the face's radius and its end faces keep their place.
- **Fillet: constant radius**
  - Orca: only when the edges are all, top, bottom or side edges of the part, or corners of straight extrudes.
  - Orca: other edges are left out, because Orca names edges by its own numbering.
- **Fillet: variable radius**
  - Paramability: one straight or arc edge, alone in its fillet or apart from its other sets.
  - Paramability: no radii between the ends. The radius must change evenly along the edge.
  - Radii between the ends need an app change.
- **Fillet or chamfer with several sets picked in different ways (edges, faces, chains)**
  - Paramability: sets that lie apart become one step for each way of picking. Each step has the pick that Fusion
    used. A set that cannot be copied is left out alone.
  - Paramability: the sizes read before the step are marked. The tries do not show whether a size brings the sets near
    each other.
  - Paramability: sets that meet or come near stay one step, with their edges picked one by one. This holds also
    through a sharp angle or a size range.
  - Orca: as in the rows above.
- **Fillet or chamfer set picked by a face with Tangent Chain on, no smooth neighbour faces**
  - Fusion does not give the edges of such a set and builds nothing for it.
  - The whole step is left out with a tip. The rest of the part is copied.
- **Shell: outward, closed, rounded corners**
  - Paramability: it needs a Paramability release that reads recipe version 17.
  - The part's volume must change as the shell says.
  - A shell that grows both inward and outward is left out.
- **Draft**
  - Paramability: one angle under 30 degrees, with faces on one side of the plane.
  - Paramability: a Symmetric draft with faces on both sides is copied as two equal angles (recipe version 17).
  - Two different angles are left out. Fusion does not say which angle leans which side. A hand check can settle it.
- **Scale of bodies**
  - Paramability: the factors follow sizes.
  - A point that sizes can move keeps its place. Those sizes are marked.
  - Factors per axis in a component turned at an angle are left out.
- **Combine: join, cut, intersect**
  - The tool bodies are copied from their steps, also from other components.
  - Orca: an intersect with several tools that the add-in cannot work out is left out.
- **Split Face**
  - Both pass it by when the solid stays the same.
  - Paramability adds a note: picks on the split faces may not follow.
  - A Split Face that may have changed the solid is left out.

## Construct

| Fusion action | Paramability now | Paramability possible later | Orca now | Orca possible later | Notes |
| --- | --- | --- | --- | --- | --- |
| Construction planes | Copied | - | Partly | Needs Orca | See notes. |
| Construction axes | Copied | - | Partly | Needs Orca | As for planes. |
| Construction points | Copied | - | Partly | Needs Orca | As for planes. |

Notes for Construct:

- **Construction planes**
  - Paramability: steps on them follow the places that the size tries measure.
  - Orca: they keep their place. The sizes that move them are marked.

## Assemble

| Fusion action | Paramability now | Paramability possible later | Orca now | Orca possible later | Notes |
| --- | --- | --- | --- | --- | --- |
| Body in a component | Copied | - | Copied | - | Placed where Fusion shows it. |
| Component moved by hand | Copied | - | Copied | - | Capture the position first (Position, Capture Position). The export asks for it. |
| Steps that use geometry of another component | Partly | Yes, add-in only | Partly | Needs Orca | See notes. |
| Joints, As-built Joints, Rigid Groups | Not read | No | Not read | No | See notes. |

Notes for Assemble:

- **Steps that use geometry of another component**
  - They are copied where Fusion shows them.
  - Sizes that move that component may give unexpected results.
  - Edges and curved faces of another component are left out.
- **Joints, As-built Joints, Rigid Groups**
  - They change no shape.
  - A joint parameter may move every place from another component. So its sizes are marked.

## Parameters

| Fusion action | Paramability now | Paramability possible later | Orca now | Orca possible later | Notes |
| --- | --- | --- | --- | --- | --- |
| User parameters | Copied | - | Copied | - | Lengths and angles in mm, cm, m, in, ft, deg, rad, or no unit. |
| Formulas of parameters | Copied | - | Partly | Needs Orca | Orca: a formula that Orca cannot write keeps its number. |
| `+ - * /`, `sqrt`, `abs`, `min`, `max`, `sin`, `cos`, `tan` | Copied | - | Copied | - | Orca: a whole power up to 4 is written as a product. |
| `ceil`, `floor`, `round`, `%`, `if`, comparisons, `and`, `or` | Copied | - | Partly | Needs Orca | Paramability: `%` only when its left side stays at zero or above. Orca keeps the number. |
| `asin`, `acos`, `atan`, `exp`, `ln`, `log`, other powers | Copied | - | Partly | Needs Orca | Orca keeps the number. |
| `random()`, text parameters, units other than lengths and angles | Left out | No | Left out | No | The formulas have no such values. |

## Surface, Form, Mesh, Sheet metal

| Fusion action | Paramability now | Paramability possible later | Orca now | Orca possible later | Notes |
| --- | --- | --- | --- | --- | --- |
| Surface steps that make separate surface bodies | Not read | No | Not read | No | They do not change the part. |
| Stitch, surface Offset, other surface steps that make the part | Left out | Yes, needs an app change | Left out | Needs Orca | The app does not rebuild surfaces. |
| Form (T-splines) | Left out | No | Left out | No | A free form has no sizes to rebuild from. |
| Mesh steps, mesh converted to a solid | Left out | No | Left out | No | A mesh has no steps or sizes to rebuild from. |
| Sheet metal: flange, bend | Left out | Yes, needs an app change | Left out | Needs Orca | |

## Insert

| Fusion action | Paramability now | Paramability possible later | Orca now | Orca possible later | Notes |
| --- | --- | --- | --- | --- | --- |
| Insert Mesh | Not read | No | Not read | No | Only solid bodies can be exported. |
| Insert SVG, Insert DXF | Partly | No | Partly | No | They make sketch curves with fixed numbers. Orca: splines only when Fusion gives them exactly. |
| Decal | Not read | No | Not read | No | It changes no shape. |
| Canvas | Not read | No | Not read | No | It changes no shape. |

## Could be added to Export for Paramability

Sorted by how many printing projects it helps:

1. Rounds and chamfers of more kinds: variable radius with radii between the ends (app change), two radii, Rule
   Fillet and Full Round Fillet.
2. Picks that follow sizes on the end faces of a revolve whose angle is a size, and on the inner walls a shell leaves
   on a part turn (add-in only).
3. Thin extrudes of an open line with arcs whose wall follows its sizes, and with a corner next to an arc (add-in
   only, after hand check 103): walls, brackets and stiffeners.
4. Box, Cylinder, Sphere, Torus, pipes with a square or triangle section or a closed path of lines (add-in only),
   and sweeps that make a new component (add-in only).
5. Join extrudes through all where the far side cannot be checked, and new body extrudes through all.
6. Lofts through three or more outlines (add-in only), and lofts with rails or tangent ends (app change).
7. Extrudes to a tilted or curved face with two sides (add-in only), or with a taper or an offset past the face (app
   change).
8. Coils with a taper or a spiral (app change), and half turns (add-in only).
9. Shells that grow both inward and outward (app change), and drafts with two different angles (add-in only, after a
   hand check of which side each angle leans).
10. Emboss on a curved face (app change).
11. Path pattern along other curves than one line, arc or circle, and patterns and mirrors of faces (app change).
12. Taper tapped holes and threads that are not 60 degree or are tapered (app change).
13. Sweeps along 3D splines, with a guide rail or a guide surface (app change).
14. Press Pull of curved faces other than whole round faces, Move of faces, Split Body by a surface, Delete Face,
    Replace Face, Thicken, Boundary Fill and sheet metal (app change).

## Orca does not support

These need a change in Orca's Design tab. So the Orca copy cannot do them while Orca stays as it is:

- Sketch dimensions that follow a variable. Only rectangle sides, circle radii and the corners of straight outlines
  can follow, through plane cuts.
- A sketch plane, a hole place or a construction plane that moves with a variable.
- Faces and edges picked by the person. Orca names them by its own numbering. This rules out shells, drafts, Press
  Pull, Delete Face, extrudes up to a face, and rounds or chamfers on hand-picked edges.
- Rounds with a variable radius, chord length, two radii or curvature continuity, and chamfers with two sizes.
- A move distance that follows a variable.
- A pattern that leaves copies out.
- Sweeps that twist, taper or keep the outline in one direction, sweeps with a 3D path, and sweeps with a guide rail
  or surface.
- Lofts through more than two outlines, with holes, with rails, a centre line or shaped ends.
- Left hand threads, other thread forms, tapered threads and drill points.
- Coils: a sweep along a helix that keeps the wire on planes through the axis, as Fusion's coil does.
- Through all for a join or new body that ends where the part ends.
- Formula functions other than `sqrt`, `abs`, `min`, `max`, `sin`, `cos` and `tan`: no `if`, `round`, `ceil`,
  `floor`, `%` or comparisons.
- Scale, Replace Face, surfaces and sheet metal.
