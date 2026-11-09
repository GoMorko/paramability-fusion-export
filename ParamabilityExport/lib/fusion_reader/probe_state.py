"""One probe state of the design: the sketch geometry, points, lines, parameter values and target box that the size
probe compares across size settings (docs/capture-format.md, "Probe states").

Everything is read by token from the native objects of the target's component, so values are in component
coordinates (mm), like the capture. A sketch of another component (one a step of the target borrows) is read native
too, and its frame is brought into the target's coordinates through that component's place at this state. `params` stay in Fusion's own units (cm, radians). A part that cannot be read is
left out of the result and reads as "unread" to the fit; nothing here raises. No adsk import.
"""
from . import placement
from . import read_geometry as geo
from .read_sketch import into_target, read_profile
from .read_solid import line_axis

MAX_PROFILES = 200


def _find(design, token):
    """The native entity for a token: the match without an assembly context, else the native object of the first."""
    raw = geo.safe(lambda: design.findEntityByToken(token), None)
    found = list(raw) if raw else []
    for entity in found:
        if geo.safe(lambda: entity.assemblyContext, None) is None:
            return entity
    if found:
        return geo.safe(lambda: found[0].nativeObject, None)
    return None


def _read_sketch(sketch, ctx):
    """{ frame, profiles } of a sketch, or None when it has too many profiles or one cannot be read well."""
    items = geo.collection_items(geo.safe(lambda: sketch.profiles, None))
    if len(items) > MAX_PROFILES:
        return None
    profiles = [read_profile(p, ctx) for p in items]
    if any(p.get("space") == "ambiguous" for p in profiles):
        return None
    return {"frame": geo.frame_of(sketch.transform), "profiles": profiles}


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
    """The state asked for by `request`: { sketches, points, lines, params, box }, plus `unread` when needed.

    `request` has `sketches`, `points`, `lines` (entity tokens), `params` (Fusion parameter names), `target`
    (true to read the target body's box) and optionally `borrowed`: { sketch token: { path } } for sketches of other
    components, with the occurrence path the capture recorded.

    `sketches` maps a token to { frame, profiles } (profiles as in the capture, each curve with `entity`); a borrowed
    one also has `native_frame` and `placement`. `points` maps a token to [x, y, z] mm; `lines` to { point, dir };
    `params` a name to its value in cm or radians; `box` is the target's { min, max } and absent when it cannot be
    read. `unread` gives a reason per borrowed sketch token that could not be read or placed.
    """
    request = request or {}
    hints = request.get("borrowed") if isinstance(request.get("borrowed"), dict) else {}
    unread = {}

    def entity(token, read):
        found = _find(design, token)
        if found is None and token in hints:
            unread[token] = "The sketch was not found."
        return None if found is None else read(found)

    def sketch(found, token):
        if not _is_borrowed(found, ctx):
            return _read_sketch(found, ctx)
        record, reason = _read_borrowed(found, ctx, (hints.get(token) or {}).get("path") or "")
        if record is None:
            unread[token] = reason
        return record

    state = {
        "sketches": _each(request.get("sketches"), lambda t: entity(t, lambda e: sketch(e, t))),
        "points": _each(request.get("points"), lambda t: entity(t, lambda e: geo.point(e.worldGeometry))),
        "lines": _each(request.get("lines"), lambda t: entity(t, lambda e: line_axis(e.worldGeometry))),
        "params": _each(request.get("params"), lambda n: _param_value(design, ctx, n)),
    }
    if unread:
        state["unread"] = unread
    if request.get("target"):
        box = geo.safe(ctx.target_box, None)
        if box is not None:
            state["box"] = box
    return state
