"""Which other components the target's sketches are tied to through geometry, and where each user parameter acts.

A sketch can follow another component without a parameter of its own: a circle projected from a pipe (a reference
entity, `SketchEntity.isReference` and `referencedEntity`), an arc constrained to such a projection, or a sketch
drawn on a face of another component (`Sketch.referencePlane`). `sketch_links` lists those components per sketch.
With `dependent_components` of each user parameter (`parameters.py`) they tell which user parameter may reach the
exported body through another component (`params.geometry_links`).

No adsk import; every Fusion call is guarded, so an unreadable member leaves its part out and nothing raises.
"""
from . import read_geometry as geo

# Upper bounds that keep one read short on a large design.
MAX_SKETCHES = 200
MAX_ENTITIES = 5000
MAX_CONSTRAINTS = 5000
# Members of the geometric constraint types that name sketch entities (CoincidentConstraint.point and entity,
# ConcentricConstraint.entityOne and entityTwo, EqualConstraint and TangentConstraint curveOne and curveTwo, ...).
CONSTRAINT_MEMBERS = ("point", "entity", "entityOne", "entityTwo", "curveOne", "curveTwo", "lineOne", "lineTwo",
                      "line", "curve")


def _owner(entity):
    """The component that owns an entity: the component of the occurrence it is seen through, else its own."""
    context = geo.safe(lambda: entity.assemblyContext, None)
    if context is not None:
        found = geo.safe(lambda: context.component, None)
        if found is not None:
            return found
    native = geo.safe(lambda: entity.nativeObject, None)
    return geo.component_of(native if native is not None else entity)


def _component_record(component):
    return {"token": geo.safe(lambda: component.entityToken, "") or "",
            "name": geo.safe(lambda: component.name, "") or ""}


class _Links:
    """The other components of one sketch, counted as they are met."""

    def __init__(self, ctx):
        self.ctx = ctx
        self.found = []  # (component, record)

    def record(self, component):
        """The record of `component`, or None when it is the target's own component."""
        if component is None or geo.same_entity(component, self.ctx.component):
            return None
        for known, record in self.found:
            if geo.same_entity(known, component):
                return record
        record = dict(_component_record(component), references=0, constrained=0, plane=False)
        self.found.append((component, record))
        return record


def _entities(sketch):
    """The curves and points of a sketch, at most MAX_ENTITIES."""
    out = []
    for members in ("sketchCurves", "sketchPoints"):
        out.extend(geo.collection_items(geo.safe(lambda: getattr(sketch, members), None)))
    return out[:MAX_ENTITIES]


def _is_reference(entity):
    return bool(geo.safe(lambda: entity.isReference, False))


def _read_sketch(sketch, ctx):
    """{ links, unknown } of one sketch: the other components it is tied to, and how many reference entities did not
    say what they reference (a reference that is not parametric)."""
    links = _Links(ctx)
    references = []  # (entity, record) of the reference entities tied to another component
    unknown = 0
    for entity in _entities(sketch):
        if not _is_reference(entity):
            continue
        source = geo.safe(lambda: entity.referencedEntity, None)
        if source is None:
            unknown += 1
            continue
        record = links.record(_owner(source))
        if record is not None:
            record["references"] += 1
            references.append((entity, record))
    if references:
        constraints = geo.collection_items(geo.safe(lambda: sketch.geometricConstraints, None))
        for constraint in constraints[:MAX_CONSTRAINTS]:
            members = [geo.safe(lambda: getattr(constraint, name), None) for name in CONSTRAINT_MEMBERS]
            members = [m for m in members if m is not None]
            if all(_is_reference(m) for m in members):
                continue
            tied = {id(record): record for entity, record in references
                    if any(geo.same_entity(entity, m) for m in members)}
            for record in tied.values():
                record["constrained"] += 1
    plane = geo.safe(lambda: sketch.referencePlane, None)
    if plane is not None and geo.foreign(plane, ctx):
        record = links.record(_owner(plane))
        if record is not None:
            record["plane"] = True
    return {"links": [record for _, record in links.found], "unknown": unknown}


def _sketch_tokens(node, found):
    """{ sketch token: name } of the target's own sketches a step's data names; records of another component are
    skipped."""
    if isinstance(node, dict):
        if node.get("foreign") is True:
            return found
        token = node.get("sketch_token")
        if isinstance(token, str) and token:
            found.setdefault(token, node.get("sketch") or "")
        for value in node.values():
            _sketch_tokens(value, found)
    elif isinstance(node, list):
        for value in node:
            _sketch_tokens(value, found)
    return found


def sketch_links(design, ctx, items):
    """One record per sketch of the target's component that a step of that component uses:
    `{ sketch, token, links: [{ token, name, references, constrained, plane }], unknown }`, or `{ sketch, token,
    error }` when the sketch cannot be found. `items` are the capture items."""
    tokens = {}
    for item in items:
        if item.get("in_target_component") and not item.get("suppressed"):
            _sketch_tokens(item.get("data") or {}, tokens)
    out = []
    for token, name in list(tokens.items())[:MAX_SKETCHES]:
        sketch = geo.find_native(design, token)
        if sketch is None:
            out.append({"sketch": name, "token": token, "error": "The sketch could not be found."})
            continue
        read = geo.safe(lambda: _read_sketch(sketch, ctx), None)
        if read is None:
            out.append({"sketch": name, "token": token, "error": "The sketch could not be read."})
            continue
        out.append({"sketch": name or geo.safe(lambda: sketch.name, "") or "", "token": token, **read})
    return out
