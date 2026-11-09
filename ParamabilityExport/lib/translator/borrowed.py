"""Sketch outlines a step takes from another component's sketch.

The reader brings such a profile into the target's coordinates through the assembly (that component's place, then
the inverse of the target's) and keeps the sketch's own frame as `native_frame`. The step is then copied like any
other.

The sizes that move the sketch come from the probe's motion file when it holds values for the profile: the outline
then follows them like the target's own sketches (`sketch_motion`, same keys). Without such values, the outline is
written as numbers and every size that moves the sketch (its dimensions, `sketch_params`) becomes a fixed number.
Edges, faces and bodies of another component stay refused. Such a step must also keep meeting the part over the size
range (`meets_part.py`, run when the step is added).
"""
from ..params.expressions import referenced_names
from ..sketch_values import keys

BORROWED_KEYS = ("foreign", "placement", "component", "sketch_params", "native_frame")


def usable(profile):
    """True when a foreign profile carries what bringing it in needs: both frames and the place of its component."""
    placement = profile.get("placement")
    return (profile.get("foreign") is True and isinstance(profile.get("frame"), dict)
            and isinstance(profile.get("native_frame"), dict) and isinstance(placement, dict)
            and isinstance(placement.get("frame"), dict))


def _optimistic(ctx):
    """True in the first translation of an export, which fixes no size for sketch values."""
    return bool(getattr(getattr(ctx, "motion", None), "optimistic", False))


def _has_motion(ctx, item, number):
    """True when the probe's motion file holds a value of this profile (the probe read the sketch)."""
    motion = getattr(ctx, "motion", None)
    prefix = keys.profile(item.get("index"), number) + "/"
    return motion is not None and any(key.startswith(prefix) for key in getattr(motion, "values", {}))


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
    ctx.doubt(tuple(dict.fromkeys(reads)), "it changes the sketch %s of %s, which %s copies as fixed numbers"
              % (profile.get("sketch") or "", (profile.get("component") or {}).get("name") or "another component",
               item.get("name", "a step")))


def bring_in(item, ctx):
    """The item with each borrowed profile no longer foreign, or the item itself when it borrows nothing. A profile
    without a usable place stays foreign (and is refused)."""
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
        if not followed and not _optimistic(ctx):
            _fix_sizes(ctx, item, profile)
        out.append(dict({k: v for k, v in profile.items() if k not in BORROWED_KEYS}, borrowed=component))
        names.append("%s of %s" % (profile.get("sketch"), component))
    ctx.note("%s uses the sketch %s; its outline is copied in place%s."
             % (item.get("name", "This step"), ", ".join(sorted(set(names))),
                "" if followed_any else " as fixed numbers"))
    return dict(item, data=dict(data, profiles=out))
