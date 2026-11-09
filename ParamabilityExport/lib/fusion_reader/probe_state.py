"""One probe state of the design: the sketch geometry, points, lines, parameter values and target box that the size
probe compares across size settings (docs/capture-format.md, "Probe states").

Everything is read by token from the native objects of the target's component, so values are in component
coordinates (mm), like the capture. `params` stay in Fusion's own units (cm, radians). A part that cannot be read is
left out of the result and reads as "unread" to the fit; nothing here raises. No adsk import.
"""
from . import read_geometry as geo
from .read_sketch import read_profile
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
    """The state asked for by `request`: { sketches, points, lines, params, box }.

    `request` has `sketches`, `points`, `lines` (entity tokens), `params` (Fusion parameter names) and `target`
    (true to read the target body's box). `sketches` maps a token to { frame, profiles } (profiles as in the capture,
    each curve with `entity`); `points` a token to [x, y, z] mm; `lines` a token to { point, dir }; `params` a
    name to its value in cm or radians; `box` is the target's { min, max } and absent when it cannot be read.
    """
    request = request or {}

    def entity(token, read):
        found = _find(design, token)
        return None if found is None else read(found)

    state = {
        "sketches": _each(request.get("sketches"), lambda t: entity(t, lambda e: _read_sketch(e, ctx))),
        "points": _each(request.get("points"), lambda t: entity(t, lambda e: geo.point(e.worldGeometry))),
        "lines": _each(request.get("lines"), lambda t: entity(t, lambda e: line_axis(e.worldGeometry))),
        "params": _each(request.get("params"), lambda n: _param_value(design, ctx, n)),
    }
    if request.get("target"):
        box = geo.safe(ctx.target_box, None)
        if box is not None:
            state["box"] = box
    return state
