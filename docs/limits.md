# Limits

What the copy can and cannot do, step by step. The README lists only the main limits.

- A part with left out steps is exported the same way as any other, so it takes as long as a full export. At most 256
  steps can be left out of one part; a longer list stops the copy. A part with left out steps needs a
  Paramability build that reads version 3 gaps files; an older build opens it as a fixed shape.
- Every size row and sketch try starts from the saved values: before each one after the first the add-in puts the
  parameters back and recomputes. A sketch with two solutions can still land on its other one after a try that did
  not rebuild, and stay there. After such a try the add-in reads the design again before the next one. A size is
  blamed for a sketch that "makes a different outline" only when its own try started from the right outline and the
  outline came back after it. Such a size keeps its range up to the last value tried that kept the outline (the
  add-in halves toward it, as for a value that does not rebuild); only when no other value works is it not a size,
  and the reason says why. The tries made while a sketch stayed on its other solution count against no size, and
  the result window says so in one line. A sketch that stays on its other solution is brought back the way the try
  took it away: the size set a little past its value on the other side and back, or walked back in small steps.
  When a try leaves a step in a new warning or error that does not go away with the values back, the tries stop
  there; only the tries before it are used, and the sizes not tried yet are marked. When the sketch still reads
  another outline after the export, or the body has another volume or size than before, the result window says that
  your design is changed. Fusion sometimes gives a projected curve a new name, or one curve two names, when it
  recomputes; the add-in then compares the curves themselves, so this is not taken for another outline.
- A round on the four side edges of a rectangle (a slot cut, a block) whose radius is half the short side at every
  size makes round ends: the copy draws that outline as a slot and writes no round, which builds the same part.
- The rounds and chamfers on the copies of a rectangular pattern follow its count: the copy writes them for every
  count the size range allows, each kept only while the count makes its copy. Paramability cannot repeat a round
  itself yet. A round that is wider than the face next to it, or a chamfer as big as a whole face (Fusion rolls over
  such edges), may still be left out by Paramability on some copies.
- A sketch value that one size moves along a curve is copied only with the sine, cosine, tangent or cotangent of an
  angle size (or of half of it), alone or times a length, and products of two lengths, up to 3 such terms per value.
  Other curves (a square root, a power, an angle divided by a length) leave that size loose or not a size.
- A cut through all to one side cuts on the side of its sketch where it meets the part. When Fusion's stored
  direction points to a side without material there, the other side is used, with a note. A tapered one is copied
  as a tapered cut that ends past the part; one whose walls lean in ends just past it, and is left out when its
  outline would come close to closing there.
- A join through all to one side is copied as an extrude to the far side of the part. It is copied only when it joins
  the picked body alone: with more bodies, the export cannot tell where Fusion ends it. The export must also show that
  Fusion ended it on the far side of that body: its end face lies on the far side of the body, and the body has a flat
  face on that plane (or the end face merged with one). Else it is left out with a reason. A join through all onto a
  curved top adds nothing in Fusion and is left out. A join through all after a step that the copy left out is left
  out too, and so is one that builds the tool body of a Combine. A join through all both ways,
  with a taper or with a thin wall, and a new body through all, are left out. Each size that may change the body before
  the join, or move its outline, is marked "may give unexpected results" with the step named: the export cannot check
  that Fusion and the copy still end it at the same place at other sizes. This marks more sizes than needed (also a
  hole size or a fillet radius that cannot move the far side), because the export cannot tell which sizes move the
  body along the extrude. Give the extrude a distance or end it on a face to keep these sizes unmarked.
- A round or chamfer that picks an edge inside one flat side wall of an extrude (where a round meets the wall) follows
  that wall.
- A revolve axis the copy cannot use (an edge that is not straight, a face that is not round, an axis that cannot be
  read) leaves the revolve out of the copy; the reason says which of these it is.
- A revolve or pattern axis, a mirror or split plane, or a pattern direction of the part that the copy keeps where it
  is now (an edge, a face, a construction axis or plane, a line of a sketch) is not moved by the sizes. Each size
  that may move it is marked "may give unexpected results" with the step named. When the export cannot tell what such
  a place is, or what a construction plane or axis is built on (for example in a file from an older add-in), every
  size that the steps before it use is marked. A revolve axis on a line of another sketch than the outline's follows
  the sizes the size probe tried; each other size that may move or turn that line (a size of its sketch, of the plane
  or face that sketch sits on, or of part edges projected into it) is marked the same way, and with no tries every
  such size is.
- Fusion turns a revolve toward one side of its sketch plane, also when a size moves the axis (or the outline) to the
  other side of the outline. Then the turn about the axis reverses, and the copy turns one way only. So the range of
  such a size stops just before the outline would reach the axis. An outline drawn on the axis may stay on it. When the
  person typed the ranges of all the sizes that move it, the revolve is left out instead.
- A revolve whose axis is not in the plane of its sketch (or is not square to that plane) is left out too, unless Fusion
  itself projects the axis onto the sketch plane.
- A revolve to two sides with two angles is copied when its start face shows which side each angle turns to. When one
  angle is 90 or 270 degrees and the other is not the same, the start face can fit both sides: the revolve is left
  out, with the tip to make two revolves. Both angles follow sizes while their sum stays at 360 degrees or less. Two
  equal angles keep their numbers, since the copy cannot tell their sides apart at other sizes. The angle on the far
  side of the sketch keeps its number when the axis is projected onto the sketch or moves with sizes.
- A round with two different radii (Fusion's "asymmetric" rounds) is left out by both exports.
- A round set by chord length is copied as a plain round. Its radius is the one the chord length gives at the angle
  where the two faces meet. That angle must be the same along each edge, and the radius Fusion made must match.
  The radius follows the chord length size only while both faces are flat, or round faces that the edge goes
  round (the top edge of a round boss), and no size can turn the faces (faces of plain extrudes of the part).
  Otherwise the copy writes the radius as a number: the chord length is not a size, and each size that may turn or
  bend the faces is marked "may give unexpected results". On a ball shaped or ring shaped face, and on a round face
  along the edge, the radius also depends on how the face curves.
- When Fusion picked the edges of a round or chamfer from faces or from a chain of edges that touch smoothly, the
  copy picks them the same way where it can: sets of one size picked only by faces or only by chains, and chains of
  different radii in one round. Otherwise the copy picks the edges one by one, and the sizes read before the step
  are marked "may give unexpected results": at other sizes the faces or the chain may hold other edges, which the
  copy does not round. This happens for a round set by chord length, a round whose radius changes along the edge,
  sets picked by faces and sets picked by chains in one step, sets of different sizes picked by faces, and a chamfer
  with two different sizes whose edges take the first size on different faces.
- A round whose radius changes along its edge is copied only on one straight or arc edge, alone in its fillet, with
  no radii set between the two ends, and only when the radius Fusion made changes evenly from one end to the other
  (Fusion may blend it in a curve). The copy cannot repeat it in a pattern or mirror, and leaves it out inside a
  tool body. A size that may swap which end of the edge lies lowest along x, y and z is marked "may give unexpected
  results". The Orca export leaves both kinds out.
- One solid body per part. Several bodies go in one file as parts (see "Several bodies in one file").
- A body inside a component (at any depth) exports as a recipe with sizes, like a root body, and lands where Fusion
  shows it. If the part was moved by hand, capture its position first (Position, Capture Position); the export asks
  for it. A component used several times exports the copy you picked.
- These stay a fixed shape with a note: a part from a linked design, a place in the assembly that cannot be read, a
  step of another component that changes the body, and a body made in another component and moved in. A step of the
  body that reaches into another component's edges, bodies or curved faces is left out of the copy. An extrude,
  revolve or loft made with the operation New Component makes its body in the new component while its sketch stays
  in the component that was active: the copy of that body places the sketch through the assembly. A sweep made so is
  left out, since its path stays in the other component. A step that uses a sketch of another component is copied
  where Fusion shows it and follows the sizes the probe saw move it; where it could stop meeting the part (a slot that
  no longer reaches its wall, a rail that comes off), the size may give unexpected results, with the reason and the
  value past which it starts.
- A rectangular or circular pattern that spreads copies to both sides of the original is copied as a forward and a
  backward pattern from the original, at the places Fusion measured. Its count and spacing can follow sizes. A count that
  was measured odd and can become even inside its size range follows the sizes for a rectangular pattern (Fusion puts
  the extra copy of an even count ahead of the original, as seen in its exports); a circular one may give unexpected
  results at an even count, and so may a pattern whose tries show the copies elsewhere.
- The add-in looks at the faces of each copy of a pattern only when the pattern repeats holes or one-sided extrudes
  that make a new body, join or cut. For other patterns (a pattern that repeats a Combine, for one) Fusion can close
  when the add-in asks for these faces. Without the faces, a circular pattern whose turn way cannot be told from
  Fusion's other numbers is left out with "Which way this pattern turns its copies could not be read."
- A path pattern is copied when its path is one straight line, one arc or one circle. On a line it becomes a row of
  copies along the line. On an arc or a circle the copies must turn with the path, and it becomes a pattern round the
  centre of the arc. Its count and distance can follow sizes. The copies must stay on the path: when a size can move
  them past an end of the path, its range stops there. The path itself is copied as it is now, so a size that moves
  or turns the path may give unexpected results. For a straight line, only a size that turns the line or changes its
  length is marked; a size that only moves the line is not. These are left out: a path of another curve or of more than one
  curve, copies on both sides of the start point, copies that keep their direction on a round path, copies on a round
  path that start part way along it or run against it (Fusion can put them off the path), and copies past the end of
  the path. A path pattern is not copied to Orca.
- Fusion does not always say correctly where the copies of a pattern are: in Fusion 2706 it gives the copies of a
  circular pattern one step too far round. The add-in places the copies of a circular pattern by their order and
  checks every copy against its faces. A pattern is left out when a copy's faces are not where Fusion says the copy
  is, when two copies have one place, or when a place has no copy and no copy is suppressed. A circular pattern over
  part of a circle in an export from an older add-in version has no faces to tell which way it turns, so it is left
  out: export the design again.
- A mirror plane, pattern or revolve axis, a flat face or plane an extrude starts from or reaches to, a hole on sketch
  points or on a flat face of another component, and a pattern direction taken from one, are copied and follow the
  sizes the tries measured (see above). Where the tries could not measure the place, or it turns, the size that may move
  it is marked "may give unexpected results" with the step named. An origin plane or axis of another component is treated the same way, since it moves with that component. A parameter of a joint, or of a move that places a component, counts as one that may move every such place, and every sketch of the part drawn around another component, since the export cannot tell which component it places. A hole placed
  on an edge of another component, and an extrude that starts from or reaches to a curved face of one, are left out of
  the copy.
- A plane or axis of the part's own component that is built on another component (an offset from the XY plane of the
  root, a plane on a face of another part) belongs to the part. A step that uses it is copied, also when the part
  sits in an assembly. The export cannot tell which sizes move what the plane is built on. For a plane that an
  extrude starts from or reaches to, the tries measure the plane with every size, and a size that the tries could
  not measure is marked "may give unexpected results". The tries measure a sketch on such a plane the same way. For
  a mirror plane or a pattern or revolve axis built so, every ticked size is marked.
- A flat face of another body of the part (a helper body) that an extrude starts from or reaches to follows the sizes
  the tries measured. A face of this body that lies at the same place is never used instead. Where the tries could
  not measure the face, the sizes that the steps before the extrude use are marked "may give unexpected results",
  with the extrude named. When the tries saw a face or plane move in another way than the copied steps say, the copy
  follows what the tries saw.
- A link to another component is found only through the sketch itself: a projected curve or point, a constraint to
  one, or a sketch drawn on that component's face. A sketch that follows another component in another way (through
  a construction plane or axis built on it, or a pattern reaching into it) is not linked; the tries of unticked
  parameters may still name it, and a parameter you tick by hand is tried.
- A recipe covers the picked body only. Parameters made by steps or sketches of other bodies are left out where the
  add-in can match them by name; construction planes, axes and joints are read for the component and the ones above
  it. A size that turns a sketch plane, moves a point along a curve, or changes the shape of an outline may give
  unexpected results.
  These steps are left out of the copy (see "When a step cannot be copied"):
  thin extrudes of an open line with arcs or curves, of several outlines, of an outline with holes, that go two ways,
  reach to a face or have a taper, an extrude of a curved face, of several faces or of a face together with sketch outlines on another plane, a text or spline outline that is too big or too complex (see below), extrudes that start on
  a tilted or curved surface, extrudes that end on a tilted or curved surface with two sides, a taper or an offset
  past it, on such a face of another body or after a left out step, or on such a face that a size may move when no
  copied extrude made it, extrudes that end on a flat face that Fusion joins with the faces next to it (Chain Faces
  on) when the outline does not land on that face alone (the sizes that may move the face or the outline are marked
  when it does; a slot or hole of the face under the outline counts as not landing), extrudes that end on a curved
  face with Chain Faces on, extrudes that end on a curved face with Chain Faces off when the outline reaches past
  that face (the sizes that may move the face or the outline are marked when it does not), extrudes that end on a
  face whose surface could not be read, extrudes that start at a
  distance from a face or plane when Fusion gives no start face that shows which way and the end of the extrude does
  not show it either, extrudes with two sides that
  both end on faces or planes on the same side of the sketch, an extrude whose stored direction Fusion's measured face
  does not confirm when that face is not the end of the extrude and the part it joined does not show the way, a join with one side whose stored direction points
  away from where the part grew, a join
  up to a curved face when Fusion gives no end face and the part after it does not lie wholly on one side of where
  the extrude starts, a quarter turn revolve joined to the part when its ends do not show the way and the material it
  added lies inside the box of the part before it, a cut whose measured end lies short of its side when
  that side ends inside the part, an emboss on a curved face, an emboss that is moved or turned on its face, drawn on a
  plane tilted to its face or set to follow tangent faces that are rounded, threads that are not metric or Unified 60 degree threads, tapered threads, rounds whose radius changes
  along the edge other than the ones above, rounds set by chord length where the faces meet at an angle that changes
  along the edge, rounds with curvature continuity, shells that grow both inward and outward, patterns of faces, patterns
  that spread to both sides of the start when the original sits between two copies or the copies do not follow the
  usual places, mirrors of faces, a chamfer with two different sizes whose sides could not be
  measured, a press pull (offset
  faces) of a curved face other than a whole round face (a pin, a boss or a bore that goes all the way round between
  two flat ends square to its axis; part of a circle, an end on a slope or with a round or chamfer, a round face that
  also moves a face next to it, and one whose new radius would reach another edge of its end faces, at the current
  sizes or anywhere in the size range of its distance, are left out or keep the distance as a number; the whole step is left out, also when it moves flat faces too, so the copy never moves only part of what Fusion moved; the end faces
  are checked as exported, so when other sizes move an edge near the ring, Paramability may refuse the move at those
  sizes), and every
  step type not listed above. A coil is copied when it has a round, square or triangle section, no taper, and its end faces and
  helical edges read back as one plain helix; at most 8 coils, and 100 turns of coils and threads together in timeline order (later ones are left out), never as a tool
  with other steps (a spiral, a taper and a half-turn count of revolutions are left out). A draft is copied when its faces all lie on one side of its plane, with one angle
  under 30 degrees (or the same on both sides; it follows a size only when both sides use the same formula, and the
  size range stays above 0 and below 30 degrees), and the part's volume changes (it tells which way the faces lean).
  A Symmetric draft with faces on both sides of its plane is copied the same way, as two equal angles (recipe version
  17, which needs a Paramability build that opens version 17). A draft with two different angles, and a draft with faces
  on both sides that is not Symmetric, are left out: Fusion does not say which angle leans which side. A step of that kind in a tool body leaves the Combine that
  takes the tool out of the copy, as one missing step. A Remove of another body, a Split Face (the solid stays the same, so picks on its faces may not follow) and steps of
  other bodies that are never joined to the picked body do not stop the copy.
- A sweep is copied when its outline is one closed sketch outline (holes allowed; several outlines become one sweep
  each, along the same path) and its path starts at the outline,
  square to it, and runs one way. A straight path becomes an extrude, one arc or a full circle becomes a revolve, and
  a chain of lines, arcs and spline curves in one plane, or of lines joined by tangent arcs in 3D, becomes a sweep
  step. A path of body edges is copied as measured, and such a step cannot be repeated by a pattern. The outline
  follows sizes like an extrude outline. So does a path of sketch lines and arcs that the size probe measured: a size
  behind a line length, an arc radius or a corner position becomes a formula (the extrude's distance, the revolve's axis
  point and angle, or the points of the flat path, or both corner points of a straight path that twists), the path's rules are tested over the size ranges, and the ranges
  are cut where they stop holding (past that value the path would cross itself, bend tighter than the outline, or turn
  sharply). The path start must stay on the outline's plane: a size that moves one without the other is marked "may
  give unexpected results". A path that stays as measured, with the sizes behind its sketch (or the plane, face or
  projected edges it sits on) marked: one with a spline curve, a full circle, 3D corner points, body edges or a taper,
  and a closed path cut open inside an arc. A twist, a taper, or a parallel orientation on a path that keeps moving away from the
  outline's plane becomes a sweep step too (recipe version 16); a twist or taper is copied with a note to check the
  shape, since Fusion does not document how it measures them. A closed chain of lines, arcs and spline curves in one
  plane becomes a sweep step along a closed flat path (version 16), cut open where the path meets the outline's plane;
  a full circle stays a revolve unless a twist needs the sweep step. Sharp corners between lines of a flat path, closed
  or open, are mitred, as Fusion builds them, unless the sweep twists, tapers or keeps the outline in one direction;
  each line next to such corners needs room for their mitres. On a closed path an outline sitting on such a corner is
  moved to the middle of the next side, where the copied path starts. A twist along a closed path must be whole turns
  and is copied as a number, not as a size. These sweeps are left out of the copy: a twist together
  with a taper or parallel orientation, a taper along spline curves or along a scaled outline, a taper that would close part of the outline
  or a hole, a taper of 45 degrees
  or more, a twist over 3600 degrees, a guide rail, a guide surface (when Fusion does not list the guide surfaces,
  a sweep whose orientation Fusion fails with an InternalValidationError and whose twist and taper it does not give is
  taken as one, "likely"), parallel orientation on a path that turns back (the path's direction
  must keep a rise of 0.05 along the outline's normal at every point, ends and arc points included), several outlines at once that intersect the part or taper, an outline that is a face of the part, a path of
  sketch curves mixed with edges, a closed path that bends in 3D or that tapers or keeps the outline in one direction,
  a twist along a closed path that is not whole turns, a sharp corner in a path that twists, tapers or keeps the
  outline's direction, or next to a curve, or inside a spline curve (a spline drawn as a polyline that turns, or one
  with a corner point), or in a 3D path, corners too close together for the outline, a path that
  crosses itself or bends tighter than the outline allows, a path in 3D with splines or arcs that are not tangent, an
  outline in the middle of the path or not square to it, a sweep along only part of the path, a surface sweep and a
  sweep that makes a new component (its path stays in another component). A new body must have the volume the outline and path give (a parallel outline: its area times the rise of the
  path), or the sweep is left out; so is a tapered one whose volume fits neither an offset nor a scaled outline. A
  twist or taper that follows a size marks the size past the values where it would reach the limits. A twist along a
  closed path turns as Fusion walks the path. A later round or chamfer on all edges of a sweep's start or end cap names
  the step and follows its sizes, as on an extrude. The end cap is placed on a path in one plane, or for an outline
  kept in one direction. After a twist, a taper or a path that leaves one plane only the start cap is placed; a closed
  path or an outline with holes has no cap placed. A pick on part of a cap, or on a side edge at a corner of the
  outline along a path of lines and arcs, keeps its points and marks only the sizes the sweep reads. Any other pick on
  a sweep marks every size written before it.
- A pipe is copied when its section is a circle, solid or hollow, and it runs once along its whole path. It is
  written as the sweep of that circle (a ring when hollow), square to the path where the path starts and centred on
  it, so the sweep rules above hold for its path; sharp corners are mitred, as Fusion builds them. The section size
  follows a size as the circle's diameter, and the wall of a hollow pipe goes inward; the ranges stop where the
  wall would close the hole. A size that moves the start of the path is marked "may give unexpected results", since
  the copy keeps the section where it was measured. These pipes are left out: a square or triangle section (Fusion
  does not say which way the section turns), a pipe along only part of its path, and a closed path that starts on a
  sharp corner (a closed path of lines only always does). The Orca output leaves every pipe out.
- A loft is copied when it joins two closed outlines with free ends and no rails or centre line. An outline is a
  sketch outline, a closed loop of edges in one plane or a flat face; a loop of edges or a face is copied as measured,
  and the sizes that may move it are marked. It is written
  with straight faces between the outlines. Both outlines need the same number of holes, and their planes must not
  cross. Outlines of different shapes are copied with a note, since Fusion may pair the corners differently. These
  lofts are left out: three or more outlines, a point end, a curved face or a loop of edges that is open or not flat,
  tangent or direction
  ends, rails, a centre line, a closed loft and a surface loft. A round or chamfer
  on all edges of an outline of a loft (no holes) names the loft and follows its sizes; a pick on part of an outline
  keeps its points and marks the sizes the loft reads, and a pick on its side marks every size before it.
- A Combine (join, cut or keep only the shared part) is copied with its tool bodies. A tool made only by steps that add
  material (a new body, then extrudes or revolves that join it) is written step by step, each with the Combine's
  operation. Any other tool becomes one tool step that holds all the steps that made the tool: its cuts, rounds,
  chamfers, holes, shells, a Combine of its own, a pasted body, a Move and a pattern of bodies. Sizes and sketches of
  those steps are sizes of the part like any other, and a later round or chamfer on the result follows them. A tool the
  Combine keeps can serve a later Combine, which gets the tool with the steps added since. Tools made from tools are
  followed 3 levels deep. The export reads up to 120 steps and 32 tool bodies in all (a pattern of many copies counts
  as one body). The message after the export names the tool body and the step that stops it (for example "The tool
  body Body3 cannot be copied because of its step Coil1"), so you know what to change in Fusion. A tool may miss only
  rounds, chamfers, drafts and embosses: when any other step of a tool (a Move, an extrude, a cut) cannot be copied,
  the whole Combine is left out, since a tool at the wrong place or with the wrong material would give a wrong part. A tool step that starts from or reaches to a
  face of the part follows that face where the add-in can place it, and marks the sizes it cannot follow.
- Copy Paste Body is copied by writing the steps of the source again, as the source stood at the paste. The pasted
  body must be a new body: a paste that lands on a body that already has steps is left out of the copy. A copy that sits where
  its source sits keeps the sizes; a copy that sits elsewhere gets a plain-number Move, and the sizes that could change
  its place are marked "may give unexpected results". A paste of several bodies is copied when each pasted body can
  be matched to its source by its corners.
- Move of bodies is copied when the body moves as one solid. A Move along X, Y and Z, a Rotate and a free Move follow
  their distances and angles as sizes. The other kinds (point to point, to a position, along an entity) are written
  as the numbers Fusion measured. What they follow can move with any size, so every ticked size is marked or left
  out with the reason. A Move of faces, and a Move that mirrors or
  scales, are left out of the copy. A body with no corners (a sphere, a torus, a closed revolve) is copied when a Move
  along X, Y and Z or a free Move only shifts it; a Rotate, or any other Move that turns such a body, is left out with
  the tip to draw the sketch of the body where the body should be.
- Scale of bodies is copied. The factor, or the three factors of a scale that differs per axis, follow sizes. A factor
  whose formula could go under 0.001 or over 1000 keeps its number, and its sizes are marked. The point that stays in
  place keeps the place Fusion measured: when it is the origin, nothing is marked; when it is a sketch point, a
  construction point or a corner of the part, the sizes that can move it are marked "may give unexpected results".
  The add-in checks the scale on the measured body (its volume and its box): a scale that does not agree is left
  out. A scale that also scales sketches, a scale with factors per axis in a component that is turned at an angle
  that is not a quarter turn, and a scale before the first copied step of the body are left out. When a tool body
  with such a scale is joined or cut into a part that is turned at an angle, the combine is left out. A round, chamfer
  or offset after the scale that picks faces made before it keeps its measured place, and the sizes are marked.
  Export for Orca leaves every scale out: Orca has no step that scales a body.
- A rectangular, circular or mirror pattern of bodies is copied when a Combine takes the copies. When the Combine takes
  the whole pattern (the original and every copy), the pattern is written as a pattern, so its count and spacing follow
  sizes. For a join the original may be the part itself. When the Combine takes only some of the copies, or the layout
  is uneven, or it keeps only the shared part, each copy is written as a tool with its place as numbers, and the sizes
  behind the layout are marked. A count that follows a size is written as if the Combine also takes the new copies.
  Since it is not known whether Fusion does this (hand test B6), that size is marked "may give unexpected results". A mirror of bodies is copied only in a Combine, together
  with its source. A body that is a copy in a pattern is copied by writing its source's steps and a Move.
- A pattern or mirror of features whose sources hold a Combine of the part, together with every step that built its tool
  bodies, repeats the Combine as it was copied, so its count, spacing and skipped copies follow sizes as for any
  pattern. A pattern that holds only some of those steps, the steps of a tool without its Combine, or a Combine that
  keeps only the shared part is left out of the copy.
- Fusion does not say what a keep-only-the-shared-part Combine with several tools keeps (the part and every tool, or
  the part and any tool). The export tries it on temporary copies, which are never added to your design, compares
  the volumes with the result Fusion made, and copies it that way. When the volumes fit neither way, or a tool lives
  in another component, the Combine is left out with "This combine keeps a shared part that the copy could not work out".
  When both ways give the same volume, the export cannot tell which one Fusion used, so the sizes of the tools are
  marked "may give unexpected results".
  A Combine whose result is more than its tool bodies can give (a cut that removes more than the tools hold) is left out too.
- The tool body may be made in another component. The add-in then reads the steps that made it in that component
  (they count in the 120), and writes them where the tool component sits in the assembly, turned and moved as
  Fusion shows it. The sizes of those steps, including sketch dimensions of the tool, are sizes of the part like any
  other. A size that moves the tool's component is followed when the tries can measure it; one they cannot follow
  ("puts its tool at the place of Rod that turns with it") may give unexpected results. The message after the export
  names the step and the component of a tool that cannot be copied. A tool from another component that reaches to a
  face becomes a tool step. A Combine inside such a tool that takes a body from yet another component makes the Combine that takes the tool a left out step.
- A sketch outline that is one full ellipse is written as an ellipse outline. Sketch outlines with a spline edge, an elliptical arc or another free curve are copied as spline segments. The add-in
  reads the Fusion curve as a fine chain of points and picks points for the app's own smooth curve so that it stays
  within 0.005 mm of that chain, also between its points (a long or tight curve is split into several segments). A size that moves a sketch
  holding such a curve cannot be followed: it stays loose with the reason, or is left out of the sizes, because the
  points of the curve are not a formula of the sizes. An outline of more than 1000 points is not copied.
- Sketch text (`Text` in a sketch) is read as outlines and copied by Extrude and Emboss like any other outline: each
  letter shape is one outline step, a hole in a letter (the inside of an "o") is kept. A text with more than 400
  outlines, 1000 points in one outline or 256 holes in one letter is not copied ("This text has too many outline
  points to copy"). A size that moves the sketch of a text, or sets the height of the text, cannot be followed: it stays loose
  or is left out of the sizes, with the reason. An emboss of text must grow or shrink the part by the text area
  times the depth, as for other outlines.
- An Emboss of sketch outlines on a flat face is copied as an extrude that starts on the face: it raises the outline
  when its depth is positive and sinks it when the depth is negative. The depth follows a parameter. The copy checks
  that the part grows or shrinks by the outline area times the depth. An outline that runs past its face (over a hole
  or off an edge) is trimmed to the face by Fusion: the copy then checks the end face area times the depth and limits
  the extrude to the outline of that face, holes included (`within`). That works for one flat face with no flat
  neighbour following it; the face's edges are exact when it is an untapered end of an earlier extrude, else measured
  with the sizes marked loose. Older exports lack the edges and stop the copy. An emboss whose outline is a flat face of the part is copied like an extrude from that face (below).
- An extrude whose outline is a flat face of the part is copied. When the face is the top or bottom face of an earlier
  extrude without a taper, and no round, cut or join changed that face, the copy draws that extrude's outline again
  on the face. The outline and the face then follow the sizes of the earlier extrude (its length, its start and its
  sketch). Any other flat face (the top of a tapered extrude, a face after a round) is copied as Fusion measured it,
  and the sizes of the steps before it are marked "may give unexpected results", since they may change that face. The
  length, taper and operation of the face extrude follow its own parameters in both cases. Sketch outlines on the
  face's plane may come with the face; the face is then copied as measured. Exports made with
  version 0.8.0 or older did not read the face, so export again.
- A thin extrude of one closed outline (a wall along a rectangle or circle, for lids and boxes) is copied with its wall
  thickness as a size. The side of the wall (inside, outside or both ways) is taken from the measured end face, since
  the API does not say which of Fusion's side one and side two is which. Where Fusion keeps the corners of the wall
  sharp, the copy rounds them and says so. A later pick on the wall's faces is placed on earlier steps or its
  sizes may give unexpected results.
- A thin extrude of an open line of straight lines (a fence, a divider, a rib along a plate) is copied with square
  ends and sharp corners, as Fusion builds it. The wall thickness and the sizes that move the line are sizes. The side
  of the wall is checked against the faces that Fusion made, also where a face of the wall merged with a face of the
  part (a wall flush with the edge of a plate). When they do not show one side, the step is left out. Draw
  the lines one after the other, each from the end of the one before. A line drawn the other way, an arc or a curve
  leaves the step out, and so does a corner that turns more than 135 degrees (a V sharper than 45 degrees). A range
  stops before a corner takes a whole line, turns past 135 degrees, or two lines come too near.
- A formula that uses `%` is copied only when its left side stays at or above zero over the size ranges; the app and
  Fusion may disagree on negative values.
- The modeled thread of a tapped hole through all runs to where the hole comes out of the part. The add-in measures
  that point from the wall of the hole, so an export made with an earlier version leaves such a hole out: export
  again. The thread is left out, with the tip to make it cosmetic, when the thread Fusion made does not reach that
  point (for example a hole through two walls with a thread in one wall only). The thread length follows the sizes
  only in a plain part that is equally thick wherever the hole can go; in any other part (a boss or a step near the
  hole) it keeps its length, and the sizes that could move the hole or the part around it are marked "may give
  unexpected results". The Orca copy starts the thread of a
  counterbore hole at the counterbore floor and keeps that start as a number, so a size that changes the counterbore
  depth is followed only in part there; it leaves a tapped hole with a countersink and a modeled thread out.
- Some steps are copied with a note instead: setback corners, a cosmetic thread (cut as a plain hole), a round or
  chamfer with more than 32 edges (picked in groups), a direction or size that Fusion stored two ways, and a step that
  Fusion shows a warning on.
- The export works on the design as it is at the timeline marker. If you drag the marker back, the steps after it
  are left out of the part, and the dialog says so ("Exporting the design as it is at the timeline marker (step 48
  of 120)"). To read the steps, the add-in moves the marker through the design and puts it back where it was.
- In Export size choices, only plain number parameters can be columns. A parameter worked out by a formula cannot, and neither can one in a unit this export cannot convert (units other than mm, cm, m, in, ft, deg, rad or none).
- Paramability opens up to 256 MB per size and 1 GB per file. The export stops with a message above that.
- The design needs history (a parametric design).
- Made for the current Fusion release.
- This is version 0.14.1. It writes recipe version 17 when a step needs it (a scale, an outward or closed shell, a draft with two angles, a press pull of a round face, a thin wall along an open line, or a join through all; a thread then also carries its pitch diameter). Version 17 needs Paramability 1.7.0 or newer. Version 0.13.0-preview.13 is the last version that writes at most recipe version 16. A package with left out steps holds a gaps file of version 3 (each step says whether it only finishes surfaces), which needs a Paramability build that reads version 3. The hand checks in `docs/hand-checks.md` list what was checked in Fusion.
