"""Sketch outlines a step takes from another component's sketch.

The reader brings such a profile into the target's coordinates through the assembly (that component's place, then
the inverse of the target's) and keeps the sketch's own frame as `native_frame`. The step is then copied like any
other.

The outline is written as numbers, so every size that moves the borrowed sketch (its dimensions, `sketch_params`)
becomes a fixed number. Edges, faces and bodies of another component stay refused.
"""
from ..params.expressions import referenced_names

BORROWED_KEYS = ("foreign", "placement", "component", "sketch_params", "native_frame")


def _usable(profile):
    placement = profile.get("placement")
    return (profile.get("foreign") is True and isinstance(profile.get("frame"), dict)
            and isinstance(profile.get("native_frame"), dict) and isinstance(placement, dict)
            and isinstance(placement.get("frame"), dict))


def _fix_sizes(ctx, item, profile):
    """Sizes that move the borrowed sketch stay fixed: its outline is written as numbers."""
    if ctx.table is None:
        return
    names = []
    for param in profile.get("sketch_params") or []:
        names += list(param.get("reads") or []) + referenced_names(param.get("expression") or "")
    reads = []
    for name in dict.fromkeys(names):
        reads.extend(ctx.table.depends(name))
    ctx.fix(tuple(dict.fromkeys(reads)), "it changes the sketch %s of %s, which %s copies as fixed numbers"
            % (profile.get("sketch") or "", (profile.get("component") or {}).get("name") or "another component",
               item.get("name", "a step")))


def bring_in(item, ctx):
    """The item with each borrowed profile no longer foreign, or the item itself when it borrows nothing. A profile
    without a usable place stays foreign (and is refused)."""
    data = item.get("data")
    profiles = data.get("profiles") if isinstance(data, dict) else None
    if not isinstance(profiles, list) or not any(isinstance(p, dict) and _usable(p) for p in profiles):
        return item
    out, names = [], []
    for profile in profiles:
        if not (isinstance(profile, dict) and _usable(profile)):
            out.append(profile)
            continue
        component = (profile.get("component") or {}).get("name") or "another component"
        _fix_sizes(ctx, item, profile)
        out.append(dict({k: v for k, v in profile.items() if k not in BORROWED_KEYS}, borrowed=component))
        names.append("%s of %s" % (profile.get("sketch"), component))
    ctx.note("%s uses the sketch %s; its outline is copied in place as fixed numbers."
             % (item.get("name", "This step"), ", ".join(sorted(set(names)))))
    return dict(item, data=dict(data, profiles=out))
