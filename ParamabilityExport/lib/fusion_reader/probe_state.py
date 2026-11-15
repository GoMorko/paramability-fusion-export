"""One probe state of the design: the sketch geometry, points, lines, parameter values and target box that the size
probe compares across size settings (docs/capture-format.md, "Probe states").

Everything is read by token from the native objects of the target's component, so values are in component
coordinates (mm), like the capture. A sketch of another component (one a step of the target borrows) is read native
too, and its frame is brought into the target's coordinates through that component's place at this state. `params` stay in Fusion's own units (cm, radians). The
measured references of other components (planes, axes, directions, points) are read again too, in the target's
coordinates as the target sits at this state (`probe_refs`), and the flat faces steps use as outlines, each with the
timeline marker before its step (`read_face.read_faces`; the marker goes back after, unless the request asks to `park`
it). A part that cannot be read is left out of the result and reads as "unread" to the fit; nothing here raises, and
the design is left as it was found. No adsk import.
"""
from ..timing.timer import span_on
from . import placement, probe_refs
from . import read_geometry as geo
from .read_sketch import into_target, read_profile
from .probe_patterns import read_patterns
from .read_face import read_faces
from .read_solid import line_axis
from .read_sweep import flat_record

MAX_PROFILES = 200
# Other solid bodies of the target's component read for `pieces`; a component with more leaves `others` out.
MAX_OTHER_BODIES = 64


def _read_sketch(sketch, ctx):
    """{ frame, profiles } of a sketch, or None when it has too many profiles or one cannot be read well."""
    items = geo.collection_items(geo.safe(lambda: sketch.profiles, None))
    if len(items) > MAX_PROFILES:
        return None
    profiles = [read_profile(p, ctx) for p in items]
    if any(p.get("space") == "ambiguous" for p in profiles):
        return None
    return {"frame": geo.frame_of(sketch.transform), "profiles": profiles}


def _read_curves(sketch, wanted):
    """{ curve token: the curve in the sketch's own plane } for the sketch curves named in `wanted`, as the capture
    holds them for a sweep path (`flat`); a curve that is missing or cannot be read is left out."""
    out = {}
    for curve in geo.collection_items(geo.safe(lambda: sketch.sketchCurves, None)):
        token = geo.safe(lambda: curve.entityToken, "")
        found = flat_record(curve) if token in wanted else None
        if found is not None:
            out[token] = found
    return out


def _read_borrowed(sketch, ctx, path_name):
    """(record, reason) of a sketch of another component: the sketch read as `_read_sketch` does, its `frame` moved
    into the target's coordinates through the component's place as it is now, `native_frame` kept. The place is read
    again at every state, since a size can move that component. No record gives a reason for the person."""
    base = _read_sketch(sketch, ctx)
    if base is None:
        return None, "The sketch could not be read."
    path = placement.find_occurrence(ctx.root, geo.safe(lambda: sketch.parentComponent, None), path_name)
    if path is None:
        return None, "The place of the sketch's component could not be found."
    found = placement.sketch_placement_at(path, sketch)
    if "frame" not in found:
        return None, found.get("error") or "The place of the sketch could not be read."
    moved = into_target(base["frame"], found["frame"], ctx)
    if moved is None:
        return None, "The place of the part could not be read."
    return dict(base, frame=moved, native_frame=base["frame"],
                placement={"path": found.get("path", ""), "source": found.get("source", "")}), ""


def _read_pieces(body, ctx):
    """`{ lumps, others }` of the target: how many solids (lumps) it holds and the boxes of the other solid bodies of
    its component (`probe.pieces`); `others` is left out when they cannot be read or there are more than
    `MAX_OTHER_BODIES`. None when the lumps cannot be read. Reads what Fusion has built; nothing is recomputed."""
    lumps = geo.safe(lambda: body.lumps.count, None)
    if not isinstance(lumps, int) or isinstance(lumps, bool):
        return None
    out = {"lumps": lumps}
    bodies = geo.collection_items(geo.safe(lambda: ctx.component.bRepBodies, None))
    if len(bodies) <= MAX_OTHER_BODIES + 1:
        others = [b for b in bodies if not geo.same_entity(b, body) and geo.safe(lambda: b.isSolid, False)]
        boxes = [geo.safe(lambda: geo.box_of(b), None) for b in others]
        if all(box is not None for box in boxes):
            out["others"] = boxes
    return out


def _is_borrowed(sketch, ctx):
    component = geo.safe(lambda: sketch.parentComponent, None)
    return component is not None and not geo.same_entity(component, ctx.component)


def _number(parameter):
    value = geo.safe(lambda: parameter.value, None)
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _param_value(design, ctx, name):
    for read in (lambda: design.userParameters.itemByName(name),
                 lambda: ctx.component.modelParameters.itemByName(name)):
        value = _number(geo.safe(read, None))
        if value is not None:
            return value
    return None


def _each(tokens, read):
    """{ token: read(token) } for the tokens that read; one that fails or gives None is left out."""
    out = {}
    for token in tokens or []:
        value = geo.safe(lambda: read(token), None)
        if value is not None:
            out[token] = value
    return out


def read_state(design, request, ctx):
    """The state asked for by `request`: { sketches, points, lines, params, box }, plus `refs` and `unread` when needed.

    `request` has `sketches`, `points`, `lines` (entity tokens), `params` (Fusion parameter names), `target`
    (true to read the target body's box) and optionally `curves`: { sketch token: [curve token] } for the curves of
    sweep paths to read, and `borrowed`: { sketch token: { path } } for sketches of other
    components, with the occurrence path the capture recorded, `native`: sketch tokens of tool bodies from other
    components, read in their own component's frame like the target's sketches, `refs`: { reference key: { token,
    path, shape } }, `faces`: { key: { token, before } } of flat faces steps use as outlines, `patterns`:
    { key: { index, kind } } of patterns whose copies to read, and `park`: true to leave the marker at the last face's
    position after the face reads (the caller's next parameter change or `keep_marker` brings it back, so Fusion
    rebuilds the later items once, with those values).

    `sketches` maps a token to { frame, profiles } (profiles as in the capture, each curve with `entity`) and, for a
    sketch in `curves`, `curves`: { curve token: flat curve }; a borrowed one also has `native_frame` and `placement`.
    `points` maps a token to [x, y, z] mm; `lines` to { point, dir };
    `params` a name to its value in cm or radians; `box` is the target's { min, max } and absent when it cannot be
    read; with it, `pieces` is { lumps, others } of the target (`_read_pieces`). `refs` maps a reference key to its
    place in the target's coordinates, in mm: { point, normal }, { point, dir }, { dir } or { point }. `faces` maps a face key to { frame, loops } as the capture holds a face used
    as an outline; it is read last, since it moves the timeline marker for a while. `patterns` maps a key to
    { count, elements }, the copies a pattern makes at this state (`probe_patterns`). `unread` gives a reason per
    borrowed sketch token that could not be read or placed, and per reference, face or pattern key that could not be
    read.
    """
    request = request or {}
    hints = request.get("borrowed") if isinstance(request.get("borrowed"), dict) else {}
    native = set(request.get("native") or ())
    unread = {}

    def entity(token, read):
        found = geo.find_native(design, token)
        if found is None and token in hints:
            unread[token] = "The sketch was not found."
        return None if found is None else read(found)

    def sketch(found, token):
        if token in native or not _is_borrowed(found, ctx):
            return _read_sketch(found, ctx)
        record, reason = _read_borrowed(found, ctx, (hints.get(token) or {}).get("path") or "")
        if record is None:
            unread[token] = reason
        return record

    wanted = request.get("curves") if isinstance(request.get("curves"), dict) else {}

    def sketch_with_curves(found, token):
        record = sketch(found, token)
        if record is not None and token in wanted:
            record = dict(record, curves=_read_curves(found, set(wanted[token] or ())))
        return record

    # Each part is timed on `ctx.timer` when the read has one (`read_<part>`), so the export says where a read goes.
    state = {}
    with span_on(ctx, "read_sketches"):
        state["sketches"] = _each(request.get("sketches"), lambda t: entity(t, lambda e: sketch_with_curves(e, t)))
    with span_on(ctx, "read_points"):
        state["points"] = _each(request.get("points"), lambda t: entity(t, lambda e: geo.point(e.worldGeometry)))
        state["lines"] = _each(request.get("lines"), lambda t: entity(t, lambda e: line_axis(e.worldGeometry)))
    if request.get("params"):
        with span_on(ctx, "read_params"):
            state["params"] = _each(request.get("params"), lambda n: _param_value(design, ctx, n))
    else:
        state["params"] = {}
    followed = request.get("refs") if isinstance(request.get("refs"), dict) else {}
    if followed:
        with span_on(ctx, "read_refs"):
            state["refs"], missed = probe_refs.read_refs(design, ctx, followed)
        unread.update(missed)
    if request.get("target"):
        with span_on(ctx, "read_box"):
            body = geo.safe(ctx.find_target, None)
            box = geo.safe(lambda: geo.box_of(body), None) if body is not None else None
        if box is not None:
            state["box"] = box
            with span_on(ctx, "read_pieces"):
                pieces = _read_pieces(body, ctx)
            if pieces is not None:
                state["pieces"] = pieces
    patterns = request.get("patterns") if isinstance(request.get("patterns"), dict) else {}
    if patterns:
        with span_on(ctx, "read_patterns"):
            state["patterns"], missed = read_patterns(design, patterns)
        unread.update(missed)
    faces = request.get("faces") if isinstance(request.get("faces"), dict) else {}
    if faces:
        with span_on(ctx, "read_faces"):
            state["faces"], missed = read_faces(design, ctx, faces, stay=bool(request.get("park")))
        unread.update(missed)
    if unread:
        state["unread"] = unread
    return state
