"""The sizes the outline sketches of a step follow, and those that keep their numbers in Orca, with the reasons.

`sketch_formulas` solves the sketch of a profile once per translation (`Context.sketch_formulas`). `sketch_doubts`
marks the sizes that move a written outline but that no bound field of that outline follows (each outline judged
on its own), and `projection_doubts` the sizes that may move geometry projected into a sketch. Shared by the
handlers that write outlines: extrudes (`steps`), sweeps and lofts.
"""
from ..translator.sizes import reach_sizes
from .sketches import UNCONFIRMED, SketchFormulas, graph_for


def _label(item):
    return item.get("name") or "the step"


def sketch_formulas(ctx, profile):
    """The `SketchFormulas` of a profile's sketch, or None when its graph is missing or cannot be solved. Each sketch
    is solved once per translation (`Context.sketch_formulas`)."""
    if ctx.table is None:
        return None
    record = graph_for(ctx.capture, profile)
    if record is None:
        return None
    if id(record) not in ctx.sketch_formulas:
        try:
            ctx.sketch_formulas[id(record)] = SketchFormulas(ctx.table, record)
        except Exception:  # a sketch that cannot be solved keeps its numbers
            ctx.sketch_formulas[id(record)] = None
    found = ctx.sketch_formulas[id(record)]
    if found is not None:
        found.why = ""
        ctx.doubt(found.unconfirmed, UNCONFIRMED % (profile.get("sketch") or "a sketch"))
    return found


def sketch_doubts(ctx, item, parts, written):
    """Record the sizes that move the outlines of a step but that no bound field of the same outline follows, with
    the reason. `parts` are the step's `(profile, outline)` pairs, `written` the `(made, piece, profile)` of each
    outline written: `made` a `sketches.SketchOut` or an `outline_cuts.Planned`, `piece` the `Outline` it was made
    from.

    Each written outline is judged on its own: a size that one outline follows (its cuts, a rectangle's width) still
    moves another outline of the same sketch drawn with numbers (a hole of lines), which then stays where it is in
    Orca. The sizes of a sketch that move none of its written outlines are marked too, since they move other lines
    of the sketch, which may change the outline in Fusion."""
    for profile, outline in parts:
        projection_doubts(ctx, item, profile, outline)
    reached = set()
    for made, piece, profile in written:
        own = {name for _, reads in made.bound.values() for name in reads} | set(made.moves)
        sizes = _piece_sizes(ctx, profile, piece)
        reached.update(sizes)
        # The cuts of an outline (`outline_cuts`) give its whole shape from their bound fields: a size its corners
        # read and no cut reads does not change it.
        loose = [n for n in sizes if n not in own] if made.shape != "cuts" else []
        if loose:
            ctx.doubt(loose, _drawn_reason(ctx, item, made, piece, profile))
    seen = set()
    for profile, _ in parts:
        sketch = profile.get("sketch") or "the sketch"
        if sketch in seen:
            continue
        seen.add(sketch)
        rest = [n for n in _sketch_sizes(ctx, profile) if n not in reached]
        if rest:
            ctx.doubt(rest, "%s: it moves other lines of %s, which may change this outline in Fusion, and the Orca "
                      "copy does not follow that" % (_label(item), sketch))
    for made, _, _ in written:
        if made.moves and made.shape == "rectangle":
            ctx.doubt(made.moves, "%s: in Orca the rectangle grows about its centre, while Fusion also moves it"
                      % made.feature.name)
        elif made.moves:
            ctx.doubt(made.moves, "%s: the %s keeps its place in Orca, while Fusion moves it"
                      % (made.feature.name, "circle" if made.shape == "circle" else "outline"))


def _piece_sizes(ctx, profile, piece):
    """Fusion names of the free sizes that move one outline: those its corners, centres and radii read, or every
    size of its sketch when one of them has no formula."""
    formulas = sketch_formulas(ctx, profile) if piece is not None else None
    found = formulas.outline_sizes(piece) if formulas is not None else None
    return found if found is not None else _sketch_sizes(ctx, profile)


def _drawn_reason(ctx, item, made, piece, profile):
    """Why an outline written with numbers does not follow the sizes that move it: its own notes, else a plain
    reason by what the outline is."""
    if made.notes:
        return "; ".join(note.rstrip(".") for note in made.notes)
    name = made.feature.name if made.feature is not None else "%s outline" % _label(item)
    if sketch_formulas(ctx, profile) is None:
        why = "the export does not tell how the dimensions of %s place its lines" % (profile.get("sketch") or
                                                                                    "its sketch")
    elif piece is not None and piece.holes:
        why = "Orca follows the corners of an outline only when it has no holes inside"
    elif piece is not None and any(c.get("kind") != "line" for c in piece.outer):
        why = "Orca follows the corners of an outline only when all its sides are straight lines"
    else:
        why = "here Orca can tie only the size of a plain rectangle or circle to a variable"
    return "%s keeps its drawn numbers: %s" % (name, why)


def projection_doubts(ctx, item, profile, outline):
    """Mark every size read before the step when a corner or centre of the outline is placed by geometry projected
    into its sketch (`SketchFormulas.follows_projection`): the capture does not tell which sizes move that geometry,
    and the copy writes it where it is now."""
    formulas = sketch_formulas(ctx, profile) if outline is not None else None
    if formulas is None or not formulas.follows_projection(outline):
        return
    items = ctx.capture.get("items") or []
    # The sketch takes its projections where it sits in the timeline, so the steps before it may move them.
    sketch = [i for i in items if i.get("type") == "Sketch" and i.get("name") == profile.get("sketch")
              and isinstance(i.get("index"), int) and i["index"] < item.get("index", 0)]
    ctx.doubt(reach_sizes(ctx.table, items, sketch[-1] if sketch else item, {"entity_type": "BRepFace"}),
              "%s: its outline is placed by geometry projected into %s, and Orca keeps that geometry where it is now"
              % (_label(item), profile.get("sketch") or "its sketch"))


def _sketch_sizes(ctx, profile):
    """Fusion names of the free sizes that move a profile's sketch: its dimensions, from the graph when there is one,
    else from the model parameters made by that sketch."""
    if ctx.table is None:
        return ()
    record = graph_for(ctx.capture, profile)
    names = []
    if record is not None:
        names = [d.get("param") for d in record.get("dimensions") or [] if isinstance(d, dict) and d.get("param")]
    else:
        sketch = profile.get("sketch")
        for m in ctx.table.model_params.values():
            made = m.get("created_by") or {}
            if made.get("kind") == "sketchDimension" and made.get("sketch") == sketch:
                names.append(m["name"])
    return ctx.depends(names)
