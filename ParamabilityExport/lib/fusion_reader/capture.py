"""Walks the timeline and returns the capture: one JSON-safe dict the translator reads (docs/capture-format.md).

Per timeline position k the marker is set to k once. At that position the walk finishes item k - 1 (bodies, health,
what the feature produced) and starts item k (its inputs, the target body's box before it). The marker always ends
at the end of the timeline.

Feature readers come in pairs `(before, after)` (see read_solid). Modules read_finish and read_repeat add theirs
through a module level READERS dict; a missing module means those types give `data: {}`.
"""
import importlib

from ..export_plan.temp_copy import require_marker_at_end
from . import read_geometry as geo
from . import read_solid

CAPTURE_VERSION = 1

_OPTIONAL_READER_MODULES = ("read_finish", "read_repeat")


class MarkerError(Exception):
    """The timeline marker could not be put back at the end."""


def _optional_readers():
    readers = {}
    for module in _OPTIONAL_READER_MODULES:
        try:
            loaded = importlib.import_module("%s.%s" % (__package__, module))
        except ModuleNotFoundError as exc:
            if not (exc.name or "").endswith(module):
                raise
            continue
        readers.update(getattr(loaded, "READERS", {}))
    return readers


def _health(state):
    name = geo.enum_name(state, "FeatureHealthStates").lower()
    if "error" in name or state == 2:
        return "error"
    if "warning" in name or state == 1:
        return "warning"
    return "ok"


def _is_group(obj):
    return bool(geo.safe(lambda: obj.isGroup, False)) or geo.type_name(obj).endswith("TimelineGroup")


def _start_item(timeline, ctx, readers, index, items):
    """Marker is at `index`: create the item and read its inputs."""
    obj = timeline.item(index)
    if _is_group(obj):
        return
    entity = geo.safe(lambda: obj.entity, None)
    item = {
        "index": index,
        "name": geo.safe(lambda: obj.name, ""),
        "type": geo.type_name(entity),
        "suppressed": bool(geo.safe(lambda: obj.isSuppressed, False)),
        "health": "ok",
        "message": "",
        "component_root": True,
        "bodies_after": [],
        "data": {},
    }
    items[index] = item
    if entity is None or item["suppressed"]:
        return
    item["component_root"] = geo.safe(
        lambda: entity.parentComponent.entityToken == ctx.root.entityToken, True)
    before = (readers.get(item["type"]) or (None, None))[0]
    if before is not None:
        try:
            item["data"] = before(entity, ctx)
        except Exception as exc:
            item["data"] = {"read_error": str(exc) or type(exc).__name__}


def _finish_item(timeline, ctx, readers, index, items):
    """Marker is just after `index`: read bodies, health and what the feature produced."""
    item = items.get(index)
    if item is None:
        return
    obj = timeline.item(index)
    item["health"] = geo.safe(lambda: _health(obj.healthState), "ok")
    item["message"] = geo.safe(lambda: obj.errorOrWarningMessage or "", "")
    entity = geo.safe(lambda: obj.entity, None)
    if entity is None or item["suppressed"]:
        return
    item["bodies_after"] = geo.safe(lambda: geo.body_refs(entity.bodies), [])
    after = (readers.get(item["type"]) or (None, None))[1]
    if after is not None and "read_error" not in item["data"]:
        try:
            item["data"].update(after(entity, ctx, item["data"]) or {})
        except Exception as exc:
            item["data"] = {"read_error": str(exc) or type(exc).__name__}


def _restore_marker(timeline, count):
    try:
        timeline.moveToEnd()
    except Exception:
        try:
            timeline.markerPosition = count
        except Exception:
            pass
    if timeline.markerPosition != count:
        raise MarkerError("The timeline marker could not be moved back to the end.")


def _app_details():
    """Fusion version, design file name and up axis from the running app; empty defaults outside Fusion."""
    try:
        import adsk.core
        from .design_info import detect_up_axis, document_name, fusion_version
        app = adsk.core.Application.get()
        return fusion_version(app), document_name(app), detect_up_axis(app)
    except Exception:
        return "", "", "z"


def read_capture(design, body, fusion=None, name=None, up_axis=None, extra_readers=None):
    """Capture of `design` for the picked `body`.

    Refuses (StepExportError) unless the marker is at the end. fusion, name and up_axis come from the running app
    when not given. extra_readers adds feature readers (type name to (before, after)).
    """
    timeline = design.timeline
    require_marker_at_end(timeline)
    count = timeline.count
    ctx = geo.ReadContext(design, body)
    readers = dict(read_solid.READERS)
    readers.update(_optional_readers())
    readers.update(extra_readers or {})
    items = {}
    try:
        for k in range(count + 1):
            timeline.markerPosition = k
            if k > 0:
                _finish_item(timeline, ctx, readers, k - 1, items)
            if k < count:
                _start_item(timeline, ctx, readers, k, items)
    finally:
        _restore_marker(timeline, count)
    final = ctx.find_target() or body
    app_fusion, app_name, app_up = _app_details() if None in (fusion, name, up_axis) else ("", "", "z")
    return {
        "capture": CAPTURE_VERSION,
        "fusion": app_fusion if fusion is None else fusion,
        "design": app_name if name is None else name,
        "up_axis": app_up if up_axis is None else up_axis,
        "target": {
            **ctx.target_ref,
            "box": geo.box_of(final),
            "volume_mm3": round(final.volume * 1000.0, 6) + 0.0,
        },
        "items": [items[i] for i in sorted(items)],
    }
