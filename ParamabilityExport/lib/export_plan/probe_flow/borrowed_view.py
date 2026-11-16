"""The borrowed sketches of a capture and the view of it the probe works on."""
from ...probe import plan
from ...design_model import borrowed


def _profile_lists(capture):
    """(item, profiles) of each item that has a profile list."""
    for item in capture.get("items") or []:
        data = item.get("data")
        if isinstance(data, dict) and isinstance(data.get("profiles"), list):
            yield item, data["profiles"]


def _is_borrowed(profile):
    return isinstance(profile, dict) and borrowed.usable(profile) and bool(profile.get("sketch_token"))


def borrowed_sketches(capture):
    """Sketch token to { path, sketch, component } of the borrowed sketches of a capture: the occurrence path the
    capture recorded, and the names for a reason."""
    out = {}
    for _, profiles in _profile_lists(capture):
        for profile in filter(_is_borrowed, profiles):
            out.setdefault(profile["sketch_token"], {
                "path": (profile.get("placement") or {}).get("path") or "", "sketch": profile.get("sketch") or "",
                "component": (profile.get("component") or {}).get("name") or ""})
    return out


def _as_own(profile):
    """A borrowed profile written as an own one: its `frame` is already in the target's coordinates. The sketch name
    also names the component, so a reason can say whose sketch it is."""
    component = (profile.get("component") or {}).get("name")
    name = profile.get("sketch") or "a sketch"
    own = {k: v for k, v in profile.items() if k not in borrowed.BORROWED_KEYS}
    return dict(own, sketch="%s of %s" % (name, component) if component else name)


def probe_view(capture):
    """The capture with each borrowed profile written as an own one, so the probe plans and fits it like the rest.
    The capture itself when nothing is borrowed."""
    if not borrowed_sketches(capture):
        return capture
    items = []
    for item in capture.get("items") or []:
        data = item.get("data")
        if isinstance(data, dict) and isinstance(data.get("profiles"), list) and any(
                map(_is_borrowed, data["profiles"])):
            profiles = [_as_own(p) if _is_borrowed(p) else p for p in data["profiles"]]
            item = dict(item, data=dict(data, profiles=profiles))
        items.append(item)
    return dict(capture, items=items)


def covers_a_sketch(capture):
    """True when the probe can follow or watch at least one sketch, or follow a measured reference or a face used as an
    outline, of the capture."""
    found = plan.scan(probe_view(capture))
    return (bool(found.covered) or bool(found.faces) or bool(borrowed_sketches(capture))
            or any(r["shape"] for r in plan.refs(capture)))


def with_borrowed(request, hints, watch):
    """`request` with the watched sketches added and the occurrence paths of its borrowed sketches."""
    sketches = list(request["sketches"]) + [t for t in watch if t not in request["sketches"]]
    out = dict(request, sketches=sketches)
    paths = {t: {"path": hints[t]["path"]} for t in sketches if t in hints}
    if paths:
        out["borrowed"] = paths
    return out
