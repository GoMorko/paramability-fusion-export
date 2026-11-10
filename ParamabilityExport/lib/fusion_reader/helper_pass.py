"""The second reading pass: the steps behind the tool bodies of a Combine.

The main walk reads feature data only for items of the target's component, and only for the exported body. A Combine
there can take tool bodies made by other steps, in its own component or another, and the steps that made a tool can
take bodies from further steps (a Paste of a body, a pattern of bodies, a Combine on the tool). `translator/tool_items.py`
picks the items that made those bodies. This pass rolls the timeline to each of them and records, for every body an item
serves, `body_states[token]`: its box and volume before the item, its volume after. A step of another component is also
read with the same feature readers, in the tool component's own frame: a `ReadContext` whose target is the body, so that
component's sketches, planes and faces are not foreign. A body of another component gets `place`
(`placement.tool_place`), read with the marker just before the item that holds it.

Reading comes in rounds: each round reads what the plan names, and the steps it reads name the next bodies. At most
`tool_items.MAX_ITEMS` steps are read. Nothing here raises: a body that cannot be found gets `place.error`, an item that
cannot be read keeps `read_error`, and items past a limit keep `helper_unread` with the reason. The caller restores the
timeline marker.
"""
from ..translator import tool_items
from . import read_geometry as geo
from .parameters import list_model_parameters
from .placement import find_occurrence, tool_place

UNREADABLE = "the tool body or the place of its component could not be read"


def _tool_context(design, timeline, anchor, tool):
    """`(ReadContext, body)` of the tool body with the marker just before its `anchor` item, or `(None, reason)`."""
    timeline.markerPosition = anchor["index"]
    body = geo.safe(lambda: geo.find_native(design, tool.get("token") or ""), None)
    if body is None:
        return None, "The tool body could not be found."
    ctx = geo.safe(lambda: geo.ReadContext(design, body), None)
    if ctx is None or ctx.component is None:
        return None, "The component of the tool body could not be read."
    return ctx, body


def _entity(timeline, native_entity, index):
    """The native entity of timeline item `index`, or None when it cannot be read."""
    return geo.safe(lambda: native_entity(timeline.item(index))[0], None)


def _state_before(design, token):
    body = geo.safe(lambda: geo.find_native(design, token), None)
    if body is None:
        return {"box_before": None, "volume_before": None, "volume_after": None}
    return {"box_before": geo.safe(lambda: geo.box_of(body), None), "volume_before": geo.volume_mm3(body),
            "volume_after": None}


def _state_after(design, token):
    body = geo.safe(lambda: geo.find_native(design, token), None)
    return geo.volume_mm3(body) if body is not None else None


def _read_start(entity, item, hctx, readers, component_bodies):
    item["helper_of"] = hctx.target_ref["token"]
    bodies = geo.safe(lambda: component_bodies(hctx), None)
    if bodies is not None:
        item["bodies_before"] = bodies
    before = (readers.get(item["type"]) or (None, None))[0]
    if before is None:
        return
    try:
        item["data"] = before(entity, hctx)
    except Exception as exc:
        item["data"] = {"read_error": str(exc) or type(exc).__name__}


def _read_finish(entity, item, hctx, readers):
    after = (readers.get(item["type"]) or (None, None))[1]
    if after is None or "read_error" in item["data"]:
        return
    try:
        item["data"].update(after(entity, hctx, item["data"]) or {})
    except Exception as exc:
        item["data"] = {"read_error": str(exc) or type(exc).__name__}


class _Pass:
    """The state of one run of `read_helpers`."""

    def __init__(self, design, ctx, timeline, items, readers, native_entity, component_bodies):
        self.design, self.ctx, self.timeline, self.items = design, ctx, timeline, items
        self.readers, self.native_entity, self.component_bodies = readers, native_entity, component_bodies
        self.contexts = {}    # id(body record) -> ReadContext of that body, for bodies of other components
        self.placed = set()   # id(body record) of the records followed already
        self.done = set()     # (item index, token) whose states were read
        self.components = []  # components whose model parameters the size table needs

    def follow(self, source):
        """Reads the place of a body of another component, and the context its steps are read in."""
        record, anchor = source.record, source.anchor
        self.placed.add(id(record))
        foreign = tool_items.is_foreign_tool(record)
        if not foreign and anchor.get("in_target_component") is not False:
            return
        hctx, body = _tool_context(self.design, self.timeline, anchor, record)
        if hctx is None:
            if foreign:
                record["place"] = {"error": body}
            return
        self.contexts[id(record)] = hctx
        if not foreign:
            return
        path = record.get("path") or ""
        record["place"] = geo.safe(lambda: tool_place(self.ctx, hctx.component, path, source.number),
                                   {"error": "The place of the tool's component could not be read."})
        self.components.append(hctx.component)
        self.components.extend(_above(self.ctx, hctx.component, path))

    def job(self, item, records):
        """`(hctx, tokens)` for an item: the context to read its feature in (None when it needs none or was read), and
        the tokens whose states are new. None when the item cannot be read."""
        tokens = [t for t in dict.fromkeys(r.get("token") for r in records) if t and (item["index"], t) not in self.done]
        if item.get("in_target_component") is not False or item.get("helper_of"):
            return None, tokens
        for record in records:
            hctx = self.contexts.get(id(record))
            if hctx is not None and "error" not in (record.get("place") or {}):
                return hctx, tokens
        item["helper_unread"] = UNREADABLE
        return False, []

    def read(self, jobs):
        """Rolls to each item once and reads its feature (steps of other components) and the states of its bodies."""
        starts = set(jobs)
        for position in sorted(starts | {i + 1 for i in starts}):
            self.timeline.markerPosition = position
            if position - 1 in jobs:
                self._finish(*jobs[position - 1])
            if position in jobs:
                self._start(*jobs[position])

    def _start(self, item, hctx, tokens):
        if hctx is not None:
            entity = _entity(self.timeline, self.native_entity, item["index"])
            if entity is None:
                item["data"] = {"read_error": "The step could not be read."}
            else:
                _read_start(entity, item, hctx, self.readers, self.component_bodies)
        for token in tokens:
            item.setdefault("body_states", {})[token] = _state_before(self.design, token)
            self.done.add((item["index"], token))

    def _finish(self, item, hctx, tokens):
        if hctx is not None:
            entity = _entity(self.timeline, self.native_entity, item["index"])
            if entity is not None:
                _read_finish(entity, item, hctx, self.readers)
        for token in tokens:
            item["body_states"][token]["volume_after"] = _state_after(self.design, token)


def read_helpers(design, ctx, timeline, items, readers, native_entity, component_bodies):
    """Read the steps behind the tool bodies of the Combines of the exported body. `items` maps a timeline index to its
    item dict (changed in place: `body_states` on every step that made a tool body, and for steps of other components
    `data`, `helper_of`, `bodies_before`; `helper_unread` on a step that was not read). Each tool body, Paste source
    and pattern source of another component gets `place` (`placement.tool_place`). Returns the components whose model
    parameters the size table needs (the components of those bodies and those above them)."""
    run = _Pass(design, ctx, timeline, items, readers, native_entity, component_bodies)
    plan = None
    for _ in range(tool_items.MAX_DEPTH + 1):
        plan = tool_items.plan([items[i] for i in sorted(items)], ctx.target_ref)
        fresh = [s for s in plan.sources if id(s.record) not in run.placed]
        for source in fresh:
            run.follow(source)
        jobs = {}
        for item, records in sorted(plan.wanted, key=lambda pair: pair[0]["index"]):
            hctx, tokens = run.job(item, records)
            if hctx is not False and (hctx is not None or tokens):
                jobs[item["index"]] = (item, hctx, tokens)
        if not fresh and not jobs:
            break
        run.read(jobs)
    _mark_limits(plan)
    return run.components


def _mark_limits(plan):
    """Records what a limit left unread: `helper_unread` on the steps, `place.error` on bodies of other components."""
    for item, reason in plan.left:
        if "body_states" not in item and not item.get("helper_of"):
            item["helper_unread"] = reason
    for record, reason in plan.refused:
        if tool_items.is_foreign_tool(record) and "place" not in record:
            record["place"] = {"error": reason}


def _above(ctx, component, path_name):
    """Components of the occurrences above the one that shows `component` (its parents out to the root's children)."""
    path = geo.safe(lambda: find_occurrence(ctx.root, component, path_name), None) or []
    return [c for c in (geo.safe(lambda: o.component, None) for o in path[1:]) if c is not None]


def model_parameters(components):
    """Model parameters of `components`, merged by name (the first wins)."""
    merged = {}
    for component in components:
        for parameter in geo.safe(lambda: list_model_parameters(component), []):
            merged.setdefault(parameter["name"], parameter)
    return list(merged.values())
