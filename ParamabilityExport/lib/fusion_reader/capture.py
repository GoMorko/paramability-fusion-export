"""Walks the timeline and returns the capture: one JSON-safe dict the translator reads (docs/capture-format.md).

The walk covers the items before the timeline marker as the person left it: the design as it is at the marker. Items
after the marker are left out. Per position k the marker is set to k once. At that position the walk finishes item
k - 1 (bodies, health, what the feature produced, whether the target changed) and starts item k (its inputs). The
marker always goes back to where it was.

The target is the native body of its component, so every value is in component coordinates; `placement` says where
the component sits in the assembly. Feature readers run only for items of the target's component, and then for the steps of tool bodies from other
components (`helper_pass`).

Feature readers come in pairs `(before, after)` (see read_solid). Each reader module registers its pairs in a module
level READERS dict keyed by capture type, and the step kind table (`translator/step_kinds.py`) names the module for
each type.
"""
import importlib

from ..design_edit.marker import put_back, read_marker
from ..translator import step_kinds
from . import helper_pass
from . import read_geometry as geo
from .parameters import list_model_parameters, list_user_parameters
from .placement import occurrence_path, read_placement
from .read_constraints import sketch_graphs
from .read_links import sketch_inputs, sketch_links

CAPTURE_VERSION = 3

# A target counts as changed by an item when its box moves by more than this (mm) or its volume by more than the
# larger of VOLUME_TOLERANCE_MM3 and VOLUME_RELATIVE of it.
BOX_TOLERANCE_MM = 1e-4
VOLUME_TOLERANCE_MM3 = 1e-4
VOLUME_RELATIVE = 1e-9


class CaptureReadError(Exception):
    """The timeline cannot be read completely; the export falls back to a fixed shape."""


class MarkerError(CaptureReadError):
    """The timeline marker could not be put back where it was."""


def _health(state):
    name = geo.enum_name(state, "FeatureHealthStates").lower()
    if "error" in name or state == 2:
        return "error"
    if "warning" in name or state == 1:
        return "warning"
    return "ok"


def _is_group(obj):
    return bool(geo.safe(lambda: obj.isGroup, False)) or geo.type_name(obj).endswith("TimelineGroup")


def _component_bodies(ctx):
    """Bodies of the target's component at the current marker position (an unreadable list raises)."""
    bodies = ctx.component.bRepBodies
    return [geo.body_ref(bodies.item(i)) for i in range(bodies.count)]


def _native_entity(obj):
    """(entity, is_proxy): the timeline entity made native when Fusion hands it over as an occurrence proxy."""
    entity = geo.safe(lambda: obj.entity, None)
    if entity is not None and geo.safe(lambda: entity.assemblyContext, None) is not None:
        native = geo.safe(lambda: entity.nativeObject, None)
        return (native or entity), True
    return entity, False


def _owner_component(raw, entity, type_name):
    """The component an item lives in, or None when unreadable.

    An occurrence sits in the component of its assembly context, or in its `sourceComponent`; its own `component` is
    the one it shows. Other entities name theirs through `parentComponent` or `component` (construction geometry).
    """
    if type_name == "Occurrence":
        context = geo.safe(lambda: raw.assemblyContext, None)
        if context is not None:
            return geo.safe(lambda: context.component, None)
        return geo.safe(lambda: entity.sourceComponent, None)
    return geo.component_of(entity)


def _target_state(ctx):
    """(exists, { box, volume_mm3 } or None): the target at the current marker position; None when unreadable."""
    body = ctx.find_target()
    if body is None:
        return False, None
    state = geo.safe(lambda: {"box": geo.box_of(body), "volume_mm3": round(body.volume * 1000.0, 6) + 0.0}, None)
    return True, state


def _measure(state):
    """{ box, volume_mm3 } of a target state (`_target_state`), or None when the target did not exist or could not be
    read."""
    return state[1] if state[0] else None


def _box_numbers(box):
    return box["min"] + box["max"]


def _target_changed(before, after):
    """True or False, or None when either side is unreadable or the target exists on neither side."""
    if not before[0] and not after[0]:
        return None
    if before[0] != after[0]:
        return True
    a, b = before[1], after[1]
    if a is None or b is None:
        return None
    if any(abs(x - y) > BOX_TOLERANCE_MM for x, y in zip(_box_numbers(a["box"]), _box_numbers(b["box"]))):
        return True
    tolerance = max(VOLUME_TOLERANCE_MM3, VOLUME_RELATIVE * abs(a["volume_mm3"]))
    return abs(a["volume_mm3"] - b["volume_mm3"]) > tolerance


def _start_item(timeline, ctx, readers, index, items, group_indices):
    """Marker is at `index`: create the item and read its inputs."""
    obj = timeline.item(index)
    if _is_group(obj):
        group_indices.add(index)
        return
    entity, is_proxy = _native_entity(obj)
    item = {
        "index": index,
        "name": geo.safe(lambda: obj.name, ""),
        "type": geo.type_name(entity),
        "suppressed": bool(geo.safe(lambda: obj.isSuppressed, False)),
        "health": "ok",
        "message": "",
        "component": "",
        "in_target_component": True,
        "bodies_after": [],
        "target_changed": None,
        "target_before": None,
        "target_after": None,
        "data": {},
    }
    if is_proxy:
        item["entity_context"] = "proxy"
    items[index] = item
    if entity is None:
        return
    component = _owner_component(geo.safe(lambda: obj.entity, None), entity, item["type"])
    if component is not None:
        item["component"] = geo.safe(lambda: component.entityToken, "") or ""
        item["in_target_component"] = geo.same_entity(component, ctx.component)
    else:
        # An unreadable feature stays the target's, so the translator refuses it if it touches the part.
        item["in_target_component"] = not step_kinds.makes_no_body(item["type"])
    if item["suppressed"]:
        return
    if item["type"] != "Sketch":
        inputs = geo.safe(lambda: sketch_inputs(entity), [])
        if inputs:
            item["sketch_inputs"] = inputs
    bodies_before = geo.safe(lambda: _component_bodies(ctx), None)
    if bodies_before is not None:
        item["bodies_before"] = bodies_before
    before = (readers.get(item["type"]) or (None, None))[0]
    if before is not None and item["in_target_component"]:
        try:
            item["data"] = before(entity, ctx)
        except Exception as exc:
            item["data"] = {"read_error": str(exc) or type(exc).__name__}


def _bodies_after(item, entity):
    """Bodies of the feature, or None (with item["read_error"]) when they cannot be read.

    None is not an empty list: an empty list says the item makes no body, None says it is unknown.
    """
    try:
        bodies = entity.bodies
        if bodies is None:
            raise ValueError("The feature has no bodies.")
        return [geo.body_ref(b) for b in (bodies.item(i) for i in range(bodies.count))]
    except Exception as exc:
        item["read_error"] = "bodies: " + (str(exc) or type(exc).__name__)
        return None


def _finish_item(timeline, ctx, readers, index, items, states):
    """Marker is just after `index`: read bodies, health, whether the target changed and what the feature produced.

    `states` is the target state before and after the item (see `_target_state`). They also go to the item as
    `target_before` and `target_after`, so a step with no reader still says where it changed the part.
    """
    item = items.get(index)
    if item is None:
        return
    obj = timeline.item(index)
    item["health"] = geo.safe(lambda: _health(obj.healthState), "ok")
    item["message"] = geo.safe(lambda: obj.errorOrWarningMessage or "", "")
    entity, _ = _native_entity(obj)
    if entity is None or item["suppressed"]:
        return
    item["target_changed"] = _target_changed(*states)
    item["target_before"], item["target_after"] = _measure(states[0]), _measure(states[1])
    item["bodies_after"] = [] if step_kinds.makes_no_body(item["type"]) else _bodies_after(item, entity)
    after = (readers.get(item["type"]) or (None, None))[1]
    if after is not None and item["in_target_component"] and "read_error" not in item["data"]:
        try:
            item["data"].update(after(entity, ctx, item["data"]) or {})
        except Exception as exc:
            item["data"] = {"read_error": str(exc) or type(exc).__name__}


def _check_groups(timeline, end, count, items, group_indices):
    """Refuse when a timeline group lists children before the marker (`end`) that the walk did not reach."""
    try:
        groups = [timeline.timelineGroups.item(i) for i in range(timeline.timelineGroups.count)]
    except Exception:
        return
    for group in groups:
        try:
            first, last = group.startIndex, group.endIndex
        except Exception:
            continue
        if first >= end:
            continue
        missing = [i for i in range(first, min(last, end - 1) + 1) if i not in items and i not in group_indices]
        if last >= count or missing:
            raise CaptureReadError("The timeline groups hide steps that could not be read.")


def restore_marker(timeline, marker):
    """Moves the marker back to `marker` (a position or a `read_marker` dict); raises MarkerError when it does not
    read there after."""
    if not put_back(timeline, marker):
        raise MarkerError("The timeline marker could not be moved back to where it was.")


def _app_details():
    """Fusion version, design file name and up axis from the running app; empty defaults outside Fusion."""
    try:
        import adsk.core
        from .design_info import detect_up_axis, document_name, fusion_version
        app = adsk.core.Application.get()
        return fusion_version(app), document_name(app), detect_up_axis(app)
    except Exception:
        return "", "", "z"


def _path_components(ctx):
    """The target's component, then the component of each occurrence out to the top, then the root (no repeats)."""
    components = [ctx.component]
    for occurrence in occurrence_path(ctx.picked):
        components.append(geo.safe(lambda: occurrence.component, None))
    components.append(ctx.root)
    found, seen = [], set()
    for component in components:
        token = geo.safe(lambda: component.entityToken, None)
        if component is not None and token not in seen:
            seen.add(token)
            found.append(component)
    return found


def _model_parameters(ctx):
    """Model parameters of the components on the target's path, merged by name (the nearest component wins)."""
    merged = {}
    for component in _path_components(ctx):
        for parameter in geo.safe(lambda: list_model_parameters(component), []):
            merged.setdefault(parameter["name"], parameter)
    return list(merged.values())


def _parameters(design, ctx):
    """{ user, model } parameters (Fusion internal units) and the design's default length unit; empty when unreadable."""
    user = geo.safe(lambda: list_user_parameters(design), [])
    model = geo.safe(lambda: _model_parameters(ctx), [])
    unit = geo.safe(lambda: str(design.fusionUnitsManager.defaultLengthUnits).strip(), "") or "mm"
    return {"user": user, "model": model}, unit


def _add_tool_parameters(parameters, components):
    """Adds the model parameters of the components that tool bodies of other components live in (merged by name; the
    names already listed win)."""
    known = {p["name"] for p in parameters["model"]}
    parameters["model"].extend(p for p in helper_pass.model_parameters(components) if p["name"] not in known)


def _target_record(ctx, final):
    """The TARGET of the envelope: the native body, its component and its place in the assembly."""
    return {
        **ctx.target_ref,
        "box": geo.box_of(final),
        "volume_mm3": round(final.volume * 1000.0, 6) + 0.0,
        "component": {
            "token": ctx.component_token,
            "name": geo.safe(lambda: ctx.component.name, "") or "",
            "root": ctx.is_root_component,
        },
        "placement": read_placement(ctx.picked, ctx.root, ctx.component),
    }


def feature_readers():
    """Capture type -> (before, after) reader pair, for every type the step kind table gives a reader module."""
    readers = {}
    for spec in step_kinds.STEP_TYPES:
        if spec.reader:
            module = importlib.import_module("." + spec.reader, __package__)
            readers[spec.name] = module.READERS[spec.name]
    return readers


def read_capture(design, body, fusion=None, name=None, up_axis=None, extra_readers=None):
    """Capture of `design` for the picked `body` (the occurrence proxy of a body inside a component, or a root body).

    Only the items before the timeline marker are read; `marker` records where it was. fusion, name and up_axis
    come from the running app when not given. extra_readers adds feature readers (type name to (before, after)).
    """
    timeline = design.timeline
    marker = read_marker(timeline)
    count = timeline.count
    end = count if marker is None else min(marker["position"], count)
    ctx = geo.ReadContext(design, body)
    readers = feature_readers()
    readers.update(extra_readers or {})
    items = {}
    group_indices = set()
    previous = (False, None)
    try:
        for k in range(end + 1):
            timeline.markerPosition = k
            state = _target_state(ctx)
            if k > 0:
                _finish_item(timeline, ctx, readers, k - 1, items, (previous, state))
            previous = state
            if k < end:
                _start_item(timeline, ctx, readers, k, items, group_indices)
        tool_components = geo.safe(
            lambda: helper_pass.read_helpers(design, ctx, timeline, items, readers, _native_entity, _component_bodies),
            [])
    finally:
        restore_marker(timeline, end)
    _check_groups(timeline, end, count, items, group_indices)
    final = ctx.find_target() or ctx.target
    parameters, design_units = _parameters(design, ctx)
    _add_tool_parameters(parameters, tool_components)
    target = _target_record(ctx, final)
    ordered = [items[i] for i in sorted(items)]
    links = geo.safe(lambda: sketch_links(design, ctx, ordered), [])
    graphs = geo.safe(lambda: sketch_graphs(design, ctx, ordered), [])
    app_fusion, app_name, app_up = _app_details() if None in (fusion, name, up_axis) else ("", "", "z")
    return {
        "capture": CAPTURE_VERSION,
        "fusion": app_fusion if fusion is None else fusion,
        "design": app_name if name is None else name,
        "up_axis": app_up if up_axis is None else up_axis,
        "design_units": design_units,
        "parameters": parameters,
        "targets": [target],
        "target": target,
        "items": ordered,
        "sketch_links": links,
        "sketch_graphs": graphs,
        "marker": {"position": end, "count": count},
    }
