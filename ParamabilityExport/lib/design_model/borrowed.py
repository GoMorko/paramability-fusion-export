"""Sketch outlines a step takes from another component's sketch (borrowed outlines).

The reader brings such a profile into the target's coordinates through the assembly (that component's place, then
the inverse of the target's) and keeps the sketch's own frame as `native_frame`. `bring_in` turns it into a profile
the handlers read like the target's own: `foreign` and the place keys go, and `borrowed` names the component. The
sketch name and token stay, so a destination must not take a borrowed outline for one of the part's own sketches of
the same name.

The sizes that move the sketch come from the probe's motion file when it holds values for the profile: the outline
then follows them like the target's own sketches (same keys), and the component is recorded as followed. Without
such values the outline is written as numbers, and every size that may move the sketch (`movers`) is doubted:

- the sizes its dimensions read (`sketch_params`, the model parameters of its dimensions, the `dependents` of a
  user parameter that name the sketch by token, the dimensions of its sketch graph);
- the sizes that act on the sketch's component or on an item that may place an occurrence (`refs.acting_sizes`);
- the sizes that may move the plane the sketch sits on (`reach.borrowed_plane_sizes`);
- the sizes that may move geometry projected into the sketch, from its sketch graph (found by token): for a
  projection of the part, every size the body's component reads before the step; for one of a third component, the
  sizes that act on that component.

When the capture cannot say which sizes act on a component, or the sketch has no graph, the recorder is told
(`movers_unknown`) and each destination decides. The brought in profile keeps the names in `borrowed_movers`, for a
destination that marks them later (a sweep or a loft that cannot check its outline against the part). A profile
without a usable place stays foreign.
"""
from ..params.expressions.reading import referenced_names
from ..sketch_values import keys
from . import reach, refs, words

BORROWED_KEYS = ("foreign", "placement", "component", "sketch_params", "native_frame")
# The key of a brought in profile that lists the sizes that may move its sketch (`movers`).
MOVERS = "borrowed_movers"


def usable(profile):
    """True when a foreign profile carries what bringing it in needs: both frames and the place of its component."""
    placement = profile.get("placement")
    return (profile.get("foreign") is True and isinstance(profile.get("frame"), dict)
            and isinstance(profile.get("native_frame"), dict) and isinstance(placement, dict)
            and isinstance(placement.get("frame"), dict))


def _optimistic(ctx):
    """True in the first translation of an export, which fixes no size for sketch values."""
    return bool(getattr(ctx.motion, "optimistic", False))


def _has_motion(ctx, item, number):
    """True when the probe's motion file holds a value of this profile (the probe read the sketch)."""
    motion = ctx.motion
    prefix = keys.profile(item.get("index"), number) + "/"
    return motion is not None and any(key.startswith(prefix) for key in getattr(motion, "values", {}))


def _in_order(table, names):
    """`names` that are ticked, in table order."""
    return [name for name in table.ticked if name in names]


def _dimension_sizes(ctx, profile):
    """Fusion names of the ticked sizes that the dimensions of the borrowed sketch read: its `sketch_params`, the
    model parameters of the capture made by its dimensions (its name in its component), the user parameters whose
    `dependents` name the sketch by token, and the dimensions of its sketch graph."""
    table, token = ctx.table, profile.get("sketch_token")
    component = (profile.get("component") or {}).get("token") or ""
    names = []
    for param in profile.get("sketch_params") or []:
        names += list(param.get("reads") or []) + referenced_names(param.get("expression") or "")
    for name in reach.sketch_params(table, profile.get("sketch") or ""):
        if component and (table.model_params[name].get("created_by") or {}).get("component") == component:
            names.append(name)
    for user in (ctx.capture.get("parameters") or {}).get("user") or []:
        if token and any(d.get("sketch_token") == token for d in user.get("dependents") or []):
            names.append(user["name"])
    for dimension in (_graph(ctx.capture, profile) or {}).get("dimensions") or []:
        if isinstance(dimension, dict):
            names += [dimension.get("param")] + list(dimension.get("reads") or [])
    found = set()
    for name in dict.fromkeys(n for n in names if n):
        found |= table.depends(name)
    return _in_order(table, found)


def _graph(capture, profile):
    """The sketch graph of the borrowed sketch, found by its token, or None when there is none or it was not read."""
    token = profile.get("sketch_token")
    for graph in capture.get("sketch_graphs") or []:
        if isinstance(graph, dict) and token and graph.get("token") == token:
            return None if graph.get("error") or graph.get("cut") else graph
    return None


def _projected_sizes(ctx, item, profile):
    """`(names, known)`: the ticked sizes that may move geometry projected into the borrowed sketch, and whether the
    capture can say (the sketch has a graph, and the component of each projection is known)."""
    graph = _graph(ctx.capture, profile)
    if graph is None:
        return [], False
    owner = (profile.get("component") or {}).get("token") or ""
    names, known = set(), True
    for entity in list(graph.get("points") or []) + list(graph.get("curves") or []):
        reference = entity.get("reference") if isinstance(entity, dict) else None
        if not isinstance(reference, dict) or reference.get("source") == "none":
            continue
        if reference.get("source") == "own":
            names |= set(reach.any_face_sizes(ctx.table, ctx.capture.get("items") or [], item))
        elif reference.get("source") == "other" and reference.get("component"):
            if reference["component"] != owner:
                found, seen = refs.acting_sizes(ctx, {"component": {"token": reference["component"]}})
                names |= set(found)
                known = known and seen
        else:
            known = False
    return _in_order(ctx.table, names), known


def movers(ctx, item, profile):
    """`(dimensions, others, known)` for a borrowed outline of `item` (`profile` as the capture holds it): the ticked
    sizes its dimensions read, the other ticked sizes that may move or change the sketch (see the module text), and
    whether the capture can say which sizes those are."""
    dimensions = _dimension_sizes(ctx, profile)
    acting, known = refs.acting_sizes(ctx, {"component": profile.get("component")})
    plane = reach.borrowed_plane_sizes(ctx.table, ctx.capture.get("items") or [], item, profile.get("reference"),
                                       profile.get("native_frame"))
    projected, seen = _projected_sizes(ctx, item, profile)
    others = _in_order(ctx.table, (set(acting) | set(plane) | set(projected)) - set(dimensions))
    return dimensions, others, known and seen


def _fix_sizes(ctx, item, profile, found):
    """Sizes that may move the borrowed sketch are doubted: its outline is written as numbers. `found` is `movers`."""
    dimensions, others, known = found
    sketch = profile.get("sketch") or ""
    component = (profile.get("component") or {}).get("name") or "another component"
    step = item.get("name", "a step")
    if dimensions:
        ctx.doubt(tuple(dimensions), words.sketch_fixed(sketch, component, step))
    if others:
        ctx.doubt(tuple(others), words.sketch_may_move(sketch, component, step))
    if not known:
        ctx.movers_unknown(words.sketch_outline(step, sketch, component))


def bring_in(item, ctx):
    """The item with each borrowed profile no longer foreign, or the item itself when it borrows nothing. A profile
    without a usable place stays foreign. `ctx` is a `recorder.Recorder`."""
    data = item.get("data")
    profiles = data.get("profiles") if isinstance(data, dict) else None
    if not isinstance(profiles, list) or not any(isinstance(p, dict) and usable(p) for p in profiles):
        return item
    out, names, followed_any = [], [], False
    for number, profile in enumerate(profiles):
        if not (isinstance(profile, dict) and usable(profile)):
            out.append(profile)
            continue
        component = (profile.get("component") or {}).get("name") or "another component"
        followed = _has_motion(ctx, item, number)
        followed_any = followed_any or followed
        found = movers(ctx, item, profile) if ctx.table is not None else ([], [], True)
        if followed:
            ctx.follow_component(profile.get("component"))
        if not followed and not _optimistic(ctx) and ctx.table is not None:
            _fix_sizes(ctx, item, profile, found)
        brought = dict({k: v for k, v in profile.items() if k not in BORROWED_KEYS}, borrowed=component)
        brought[MOVERS] = list(found[0]) + list(found[1])
        out.append(brought)
        names.append("%s of %s" % (profile.get("sketch"), component))
    ctx.note(words.sketch_copied(item.get("name", "This step"), names, not followed_any))
    return dict(item, data=dict(data, profiles=out))
