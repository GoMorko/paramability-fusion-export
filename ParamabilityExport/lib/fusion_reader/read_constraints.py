"""The dimensions and geometric constraints of a sketch as plain data: its points and curves with stable ids, what each
dimension measures, what each constraint ties together. Nothing is solved or evaluated here; a later step turns the
graph into formulas and may refuse any part it does not understand.

Entities are wired by object identity (`read_geometry.same_entity`), not by token text: Fusion can give one entity
different tokens, and every read of a collection can hand out a new wrapper. A token index only speeds the match up.
Lengths leave in mm and angles in degrees, points in the sketch's own 2D frame.

No adsk import. Every Fusion member is read through `_Read`: a member that raises (or does not exist) is listed in the
record's `unread` and the read goes on. A dimension or constraint of a type not in the tables below is kept with its
type name and `unknown: true`, so nothing is silently dropped. A reader must refuse a record with `unread`, `unknown`
or a null in `on`.
"""
from . import read_geometry as geo

MAX_SKETCHES = 200
MAX_ENTITIES = 2000
MAX_DIMENSIONS = 2000
MAX_CONSTRAINTS = 2000

_MISSING = object()

_CURVE_KINDS = {
    "SketchLine": "line", "SketchArc": "arc", "SketchCircle": "circle", "SketchEllipse": "ellipse",
    "SketchEllipticalArc": "elliptical_arc", "SketchConicCurve": "conic", "SketchFittedSpline": "spline",
    "SketchFixedSpline": "spline", "SketchControlPointSpline": "spline",
}
_NAMED_CURVES = ("line", "arc", "circle")
_SURFACES = ("BRepFace", "ConstructionPlane")

# Class name -> (type, members that name the measured entities). `SketchOffsetCurvesDimension` names no entity: its
# offset constraint is linked through `offset_constraint`.
_DIMENSIONS = {
    "SketchLinearDimension": ("linear", ("entityOne", "entityTwo")),
    "SketchOffsetDimension": ("offset", ("line", "entityTwo")),
    "SketchAngularDimension": ("angular", ("lineOne", "lineTwo")),
    "SketchDiameterDimension": ("diameter", ("entity",)),
    "SketchRadialDimension": ("radial", ("entity",)),
    "SketchConcentricCircleDimension": ("concentric_circles", ("circleOne", "circleTwo")),
    "SketchLinearDiameterDimension": ("linear_diameter", ("line", "entityTwo")),
    "SketchTangentDistanceDimension": ("tangent_distance", ("entityOne", "circleOrArc")),
    "SketchOffsetCurvesDimension": ("offset_curves", ()),
    "SketchEllipseMajorRadiusDimension": ("ellipse_major_radius", ("ellipse",)),
    "SketchEllipseMinorRadiusDimension": ("ellipse_minor_radius", ("ellipse",)),
    "SketchDistanceBetweenPointAndSurfaceDimension": ("point_surface", ("point", "surface")),
    "SketchDistanceBetweenLineAndPlanarSurfaceDimension": ("line_surface", ("line", "planarSurface")),
}
_ANGLE_DIMENSIONS = ("angular",)

# A member entry is a name, or a tuple of names tried in order (current member, then its retired name).
_CONSTRAINTS = {
    "CoincidentConstraint": ("coincident", ("point", "entity")),
    "HorizontalConstraint": ("horizontal", ("line",)),
    "VerticalConstraint": ("vertical", ("line",)),
    "HorizontalPointsConstraint": ("horizontal_points", ("pointOne", "pointTwo")),
    "VerticalPointsConstraint": ("vertical_points", ("pointOne", "pointTwo")),
    "ParallelConstraint": ("parallel", ("lineOne", "lineTwo")),
    "CollinearConstraint": ("collinear", ("lineOne", "lineTwo")),
    "PerpendicularConstraint": ("perpendicular", (("line", "lineOne"), ("curve", "lineTwo"))),
    "EqualConstraint": ("equal", ("curveOne", "curveTwo")),
    "TangentConstraint": ("tangent", ("curveOne", "curveTwo")),
    "SmoothConstraint": ("smooth", ("curveOne", "curveTwo")),
    "ConcentricConstraint": ("concentric", ("entityOne", "entityTwo")),
    "MidPointConstraint": ("midpoint", ("point", "midPointCurve")),
    "SymmetryConstraint": ("symmetry", ("entityOne", "entityTwo", "symmetryLine")),
    "CoincidentToSurfaceConstraint": ("coincident_surface", ("point", "surface")),
    "LineOnPlanarSurfaceConstraint": ("line_on_surface", ("line", "planarSurface")),
}
# Constraints whose members may hold lists or be empty; their entities are listed flat in `on`.
_LISTED_CONSTRAINTS = {
    "OffsetConstraint": ("offset", ("parentCurves", "childCurves")),
    "PolygonConstraint": ("polygon", ("centerPoint", "points")),
    "RectangularPatternConstraint": ("rectangular_pattern", ("entities", "createdEntities", "directionOneEntity",
                                                              "directionTwoEntity")),
    "CircularPatternConstraint": ("circular_pattern", ("entities", "createdEntities", "centerPoint")),
}
# Members tried on a type the tables do not know, to still list every entity it names.
_GENERIC_MEMBERS = ("point", "pointOne", "pointTwo", "entity", "entityOne", "entityTwo", "curve", "curveOne",
                    "curveTwo", "line", "lineOne", "lineTwo", "circleOne", "circleTwo", "circleOrArc", "ellipse",
                    "midPointCurve", "symmetryLine", "surface", "planarSurface", "centerPoint", "points",
                    "parentCurves", "childCurves", "entities", "createdEntities")
_ORIENTATIONS = {0: "aligned", 1: "horizontal", 2: "vertical"}


class _Read:
    """Reads members of one Fusion object; a member that raises is noted in `unread` and gives the default."""

    def __init__(self, obj):
        self.obj = obj
        self.unread = []

    def get(self, name, convert=None, default=None):
        try:
            value = getattr(self.obj, name)
            if convert is not None and value is not None:
                value = convert(value)
        except Exception:
            self.unread.append(name)
            return default
        return value

    def first(self, names):
        """The first member of a name or a tuple of names that can be read; noted unread only when none can."""
        names = names if isinstance(names, tuple) else (names,)
        for name in names:
            try:
                return getattr(self.obj, name)
            except Exception:
                continue
        self.unread.append(names[0])
        return None

    def done(self, record):
        if self.unread:
            record["unread"] = list(self.unread)
        return record


def _items_of(value):
    """The entries of a list, a Fusion collection or vector, or one entity; empty for None."""
    if value is None:
        return []
    return geo.collection_items(value) if geo.is_sequence(value) else [value]


def _dependency_names(parameter, limit=256):
    """Names of every parameter `parameter` reads, directly or through others."""
    found, stack = [], [parameter]
    while stack and len(found) < limit:
        current = stack.pop()
        for other in geo.collection_items(geo.safe(lambda: current.dependencyParameters, None)):
            name = geo.safe(lambda: other.name, None)
            if name and name not in found:
                found.append(name)
                stack.append(other)
    return found


def _owner(entity):
    """The component that owns an entity: the component of the occurrence it is seen through, else its own."""
    context = geo.safe(lambda: entity.assemblyContext, None)
    if context is not None:
        found = geo.safe(lambda: context.component, None)
        if found is not None:
            return found
    native = geo.safe(lambda: entity.nativeObject, None)
    return geo.component_of(native if native is not None else entity)


class _Graph:
    """The points and curves of one sketch, found again by identity when a dimension or constraint names them."""

    def __init__(self, sketch, ctx):
        self.ctx = ctx
        self.origin = geo.safe(lambda: sketch.originPoint, None)
        self.points, self.curves = [], []
        self._known = []  # (object, ref)
        self._by_token = {}

    def _remember(self, obj, ref, token):
        self._known.append((obj, ref))
        if token:
            self._by_token.setdefault(token, []).append((obj, ref))

    def find(self, obj):
        token = geo.safe(lambda: obj.entityToken, "") or ""
        for known, ref in self._by_token.get(token, []):
            if geo.same_entity(known, obj):
                return ref
        for known, ref in self._known:
            if geo.same_entity(known, obj):
                return ref
        return None

    def ref(self, obj):
        """`[kind, id]` of a sketch point or curve (added as `implicit` when the sketch's lists did not hold it), or
        `["surface" | "other", type name]` for anything else; None for None."""
        if obj is None:
            return None
        found = self.find(obj)
        if found is not None:
            return found
        name = geo.type_name(obj)
        if name == "SketchPoint":
            return self.add_point(obj, implicit=True)
        if name in _CURVE_KINDS:
            return self.add_curve(obj, implicit=True)
        return ["surface" if name in _SURFACES else "other", name]

    def _entity_fields(self, rd, record):
        record["token"] = rd.get("entityToken", default="") or ""
        record["fixed"] = rd.get("isFixed", bool)
        constrained = rd.get("isFullyConstrained", bool)
        record["free"] = None if constrained is None else not constrained
        record["linked"] = rd.get("isLinked", bool)
        record["reference"] = self._reference(rd)

    def _reference(self, rd):
        """None for own geometry, else where a projected entity comes from."""
        if not rd.get("isReference", bool, False):
            return None
        source = rd.get("referencedEntity")
        if source is None:
            return {"source": "none", "component": "", "token": ""}
        component = _owner(source)
        token = geo.safe(lambda: component.entityToken, "") if component is not None else ""
        return {"source": "own" if geo.same_entity(component, self.ctx.component) else "other",
                "component": token or "", "token": geo.safe(lambda: source.entityToken, "") or ""}

    def add_point(self, obj, implicit=False):
        rd = _Read(obj)
        record = {"id": len(self.points), "xy": rd.get("geometry", geo.point2),
                  "origin": geo.same_entity(obj, self.origin)}
        self._entity_fields(rd, record)
        if implicit:
            record["implicit"] = True
        self.points.append(rd.done(record))
        ref = ["point", record["id"]]
        self._remember(obj, ref, record["token"])
        return ref

    def _point_id(self, rd, name):
        ref = self.ref(rd.get(name))
        return ref[1] if ref and ref[0] == "point" else None

    def add_curve(self, obj, implicit=False):
        name = geo.type_name(obj)
        kind = _CURVE_KINDS.get(name, "other")
        rd = _Read(obj)
        record = {"id": len(self.curves), "kind": kind}
        if kind == "other":
            record["name"] = name
        record["construction"] = rd.get("isConstruction", bool)
        self._entity_fields(rd, record)
        self.curves.append(record)
        ref = [kind if kind in _NAMED_CURVES else "curve", record["id"]]
        self._remember(obj, ref, record["token"])
        if kind == "line":
            record["points"] = [self._point_id(rd, "startSketchPoint"), self._point_id(rd, "endSketchPoint")]
            record["center_line"] = rd.get("isCenterLine", bool)
        elif kind == "arc":
            record["center"] = self._point_id(rd, "centerSketchPoint")
            record["points"] = [self._point_id(rd, "startSketchPoint"), self._point_id(rd, "endSketchPoint")]
            record["radius"] = rd.get("radius", geo.length)
        elif kind == "circle":
            record["center"] = self._point_id(rd, "centerSketchPoint")
            record["radius"] = rd.get("radius", geo.length)
        if implicit:
            record["implicit"] = True
        rd.done(record)
        return ref

    def add_unreadable(self, table, kind):
        """A placeholder for a listed entity that could not be fetched, so later ids keep their place."""
        record = {"id": len(table), "kind": kind, "unread": ["item"]}
        table.append(record)

    def single_refs(self, rd, names):
        """One ref per member, in order; a member that is null (or cannot be read) leaves a null place."""
        return [self.ref(rd.first(name)) for name in names]

    def listed_refs(self, rd, names):
        """The refs of every entity in members that hold one entity, a list or nothing; no null places."""
        return [self.ref(e) for name in names for e in _items_of(rd.first(name))]

    def generic_refs(self, obj):
        """Refs of every entity a member of unknown meaning names; members that are absent or raise add nothing."""
        out = []
        for name in _GENERIC_MEMBERS:
            value = geo.safe(lambda: getattr(obj, name), None)
            out.extend(self.ref(e) for e in _items_of(value))
        return out


def _orientation(raw):
    if isinstance(raw, int) and not isinstance(raw, bool):
        return _ORIENTATIONS.get(raw, "other")
    name = geo.enum_name(raw, "DimensionOrientations") or str(raw)
    return geo.pick_by_text(name, (("horizontal", "horizontal"), ("vertical", "vertical"), ("aligned", "aligned")),
                            "other")


def _dimension_record(graph, dimension, index):
    name = geo.type_name(dimension)
    known = _DIMENSIONS.get(name)
    rd = _Read(dimension)
    record = {"id": index, "type": known[0] if known else "other"}
    if known:
        record["on"] = graph.single_refs(rd, known[1])
        if known[0] == "linear":
            record["orientation"] = rd.get("orientation", _orientation, None)
    else:
        record.update(name=geo.safe(lambda: dimension.objectType, "") or name, unknown=True,
                      on=graph.generic_refs(dimension))
    parameter = rd.get("parameter")
    record["param"] = geo.safe(lambda: parameter.name, None) if parameter is not None else None
    record["expression"] = geo.safe(lambda: parameter.expression, None) if parameter is not None else None
    record["reads"] = _dependency_names(parameter) if parameter is not None else []
    if known:
        record["value"] = rd.get("value", geo.angle if known[0] in _ANGLE_DIMENSIONS else geo.length)
    else:
        record["value"] = None
    record["driving"] = rd.get("isDriving", bool)
    record["text"] = rd.get("textPosition", geo.point2)
    record["token"] = rd.get("entityToken", default="") or ""
    if known and known[0] == "offset_curves":
        record["_offset"] = rd.get("offsetConstraint")
    return rd.done(record)


def _constraint_record(graph, constraint, index):
    name = geo.type_name(constraint)
    rd = _Read(constraint)
    record = {"id": index}
    if name in _CONSTRAINTS:
        kind, members = _CONSTRAINTS[name]
        record.update(type=kind, on=graph.single_refs(rd, members))
    elif name in _LISTED_CONSTRAINTS:
        kind, members = _LISTED_CONSTRAINTS[name]
        record.update(type=kind)
        if kind == "offset":
            parents = graph.listed_refs(rd, ("parentCurves",))
            children = graph.listed_refs(rd, ("childCurves",))
            record.update(on=parents + children, parents=parents, children=children,
                          distance=rd.get("distance", geo.length), topology_matched=rd.get("isTopologyMatched", bool),
                          _dimension=rd.get("dimension"))
        else:
            record["on"] = graph.listed_refs(rd, members)
            record["suppressed"] = rd.get("isSuppressed", bool)
    else:
        record.update(type="other", name=geo.safe(lambda: constraint.objectType, "") or name, unknown=True,
                      on=graph.generic_refs(constraint))
    record["token"] = rd.get("entityToken", default="") or ""
    return rd.done(record)


def _index_of(objects, target):
    for i, obj in enumerate(objects):
        if geo.same_entity(obj, target):
            return i
    return None


def _link_offsets(dimensions, constraints, dimension_objects, constraint_objects):
    """Replaces the hidden object keys of offset dimensions and constraints with the id of the other side."""
    for record in dimensions:
        target = record.pop("_offset", None)
        if "type" in record and record["type"] == "offset_curves":
            record["offset_constraint"] = _index_of(constraint_objects, target) if target is not None else None
    for record in constraints:
        target = record.pop("_dimension", None)
        if record.get("type") == "offset":
            record["dimension"] = _index_of(dimension_objects, target) if target is not None else None


def _collection(rd, name):
    """(count, collection) of a sketch member; count None and the name noted unread when it cannot be read."""
    coll = rd.get(name)
    count = geo.safe(lambda: coll.count, None) if coll is not None else 0
    if count is None:
        rd.unread.append(name)
    return count, coll


def _fetch(coll, count):
    return [geo.safe(lambda: coll.item(i), _MISSING) for i in range(count or 0)] if coll is not None else []


def read_sketch_graph(sketch, ctx):
    """The graph of one sketch (see docs/capture-format.md, "Sketch graphs"); `cut` names a limit that stopped the
    read, then the lists are empty."""
    rd = _Read(sketch)
    graph = _Graph(sketch, ctx)
    record = {"fully_constrained": rd.get("isFullyConstrained", bool), "origin": None, "points": [], "curves": [],
              "dimensions": [], "constraints": [], "cut": ""}
    counts = {name: _collection(rd, name) for name in
              ("sketchPoints", "sketchCurves", "sketchDimensions", "geometricConstraints")}
    cut = ("entities" if (counts["sketchPoints"][0] or 0) + (counts["sketchCurves"][0] or 0) > MAX_ENTITIES else
           "dimensions" if (counts["sketchDimensions"][0] or 0) > MAX_DIMENSIONS else
           "constraints" if (counts["geometricConstraints"][0] or 0) > MAX_CONSTRAINTS else "")
    if cut:
        record["cut"] = cut
        return rd.done(record)
    for obj in _fetch(counts["sketchPoints"][1], counts["sketchPoints"][0]):
        if obj is _MISSING:
            graph.add_unreadable(graph.points, "point")
        else:
            graph.add_point(obj)
    origin = graph.ref(graph.origin) if graph.origin is not None else None
    record["origin"] = origin[1] if origin and origin[0] == "point" else None
    for obj in _fetch(counts["sketchCurves"][1], counts["sketchCurves"][0]):
        if obj is _MISSING:
            graph.add_unreadable(graph.curves, "other")
        else:
            graph.add_curve(obj)
    dimension_objects = _fetch(counts["sketchDimensions"][1], counts["sketchDimensions"][0])
    constraint_objects = _fetch(counts["geometricConstraints"][1], counts["geometricConstraints"][0])
    dimensions = [_guarded(_dimension_record, graph, obj, i) for i, obj in enumerate(dimension_objects)]
    constraints = [_guarded(_constraint_record, graph, obj, i) for i, obj in enumerate(constraint_objects)]
    _link_offsets(dimensions, constraints, dimension_objects, constraint_objects)
    record.update(points=graph.points, curves=graph.curves, dimensions=dimensions, constraints=constraints)
    return rd.done(record)


def _guarded(make, graph, obj, index):
    """One record; an object that cannot be read at all becomes an unknown record, never an exception."""
    if obj is not _MISSING:
        try:
            return make(graph, obj, index)
        except Exception:
            pass
    return {"id": index, "type": "other", "name": "", "unknown": True, "on": [], "unread": ["item"]}


def _sketch_tokens(node, found, borrowed=False):
    """{ token: (name, borrowed) } of the sketches a step's data names. A record marked `foreign` (and everything
    under it) names another component's sketch: borrowed. A sketch named only by foreign records stays borrowed."""
    if isinstance(node, dict):
        borrowed = borrowed or node.get("foreign") is True
        token = node.get("sketch_token")
        if isinstance(token, str) and token:
            name, was = found.get(token, ("", True))
            found[token] = (name or node.get("sketch") or "", was and borrowed)
        for value in node.values():
            _sketch_tokens(value, found, borrowed)
    elif isinstance(node, list):
        for value in node:
            _sketch_tokens(value, found, borrowed)
    return found


def sketch_graphs(design, ctx, items):
    """One record per sketch a step of the target's component uses, the target's own and borrowed ones:
    `{ sketch, token, borrowed?, component, fully_constrained, origin, points, curves, dimensions, constraints, cut,
    unread? }`, or `{ sketch, token, error }` when the sketch cannot be found or read. `items` are the capture items.
    Past MAX_SKETCHES the rest are `{ sketch, token, cut: "sketches" }`."""
    tokens = {}
    for item in items:
        if item.get("in_target_component") and not item.get("suppressed"):
            _sketch_tokens(item.get("data") or {}, tokens)
    out = []
    for number, (token, (name, borrowed)) in enumerate(tokens.items()):
        if number >= MAX_SKETCHES:
            out.append({"sketch": name, "token": token, "cut": "sketches"})
            continue
        sketch = geo.find_native(design, token)
        if sketch is None:
            out.append({"sketch": name, "token": token, "error": "The sketch could not be found."})
            continue
        graph = geo.safe(lambda: read_sketch_graph(sketch, ctx), None)
        if graph is None:
            out.append({"sketch": name, "token": token, "error": "The sketch could not be read."})
            continue
        head = {"sketch": name or geo.safe(lambda: sketch.name, "") or "", "token": token}
        if borrowed:
            head["borrowed"] = True
        component = geo.safe(lambda: sketch.parentComponent, None)
        head["component"] = {"token": geo.safe(lambda: component.entityToken, "") or "",
                             "name": geo.safe(lambda: component.name, "") or ""}
        out.append({**head, **graph})
    return out
