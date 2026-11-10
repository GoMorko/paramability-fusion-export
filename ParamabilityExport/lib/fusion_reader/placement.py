"""Where a body sits in the assembly: the frame that maps its component coordinates to the root's.

A picked body inside a component is an occurrence proxy; its native body lives in component coordinates. Two
candidate frames are tried (the occurrence's own transform, and the product of the native occurrence transforms along
the path). A candidate counts only when a few native vertices, mapped by it, land on the same vertices of the proxy.
No adsk import: it works on the objects it is given. Frames are `{ origin, x, y, z }` in mm, like the capture's.
"""
import math

from ..package.units import cm_to_mm
from ..translator.place import IDENTITY_ROWS, RIGID_TOLERANCE, Move, move_from_frame
from . import read_geometry as geo

POINT_TOLERANCE_MM = 1e-3
POINTS_TO_CHECK = 3
_MAX_DEPTH = 64


def occurrence_path(body):
    """Occurrences from the body's own one out to the top, as seen from the root (empty for a root body)."""
    path, occurrence = [], geo.safe(lambda: body.assemblyContext, None)
    while occurrence is not None and len(path) < _MAX_DEPTH:
        path.append(occurrence)
        occurrence = geo.safe(lambda: occurrence.assemblyContext, None)
    return path


def _native(occurrence):
    return geo.safe(lambda: occurrence.nativeObject, None) or occurrence


def _raw_frame(matrix):
    """Matrix3D to a frame with raw axes (not normalized) and the origin in mm."""
    origin, x, y, z = matrix.getAsCoordinateSystem()
    return {
        "origin": [cm_to_mm(origin.x), cm_to_mm(origin.y), cm_to_mm(origin.z)],
        "x": [x.x, x.y, x.z],
        "y": [y.x, y.y, y.z],
        "z": [z.x, z.y, z.z],
    }


_MEMBERS = ("transform2", "transform")


def _matrix(occurrence, members=_MEMBERS):
    """(raw frame, member used): the first of `members` that reads; (None, "") when none does."""
    for member in members:
        matrix = geo.safe(lambda: getattr(occurrence, member), None)
        frame = geo.safe(lambda: _raw_frame(matrix), None) if matrix is not None else None
        if frame is not None:
            return frame, member
    return None, ""


def _map(frame, p):
    return [frame["origin"][i] + p[0] * frame["x"][i] + p[1] * frame["y"][i] + p[2] * frame["z"][i] for i in range(3)]


def _turn(frame, d):
    return [d[0] * frame["x"][i] + d[1] * frame["y"][i] + d[2] * frame["z"][i] for i in range(3)]


def _compose(outer, inner):
    """The frame that applies `inner` first, then `outer`."""
    return {
        "origin": _map(outer, inner["origin"]),
        "x": _turn(outer, inner["x"]),
        "y": _turn(outer, inner["y"]),
        "z": _turn(outer, inner["z"]),
    }


def _dot(a, b):
    return sum(u * v for u, v in zip(a, b))


def _rigid(frame):
    """True for a rotation plus a move: unit, perpendicular axes, right handed (no scale, no mirror)."""
    axes = [frame["x"], frame["y"], frame["z"]]
    if any(abs(_dot(a, a) - 1.0) > RIGID_TOLERANCE for a in axes):
        return False
    if any(abs(_dot(axes[i], axes[j])) > RIGID_TOLERANCE for i, j in ((0, 1), (0, 2), (1, 2))):
        return False
    cross = [frame["x"][1] * frame["y"][2] - frame["x"][2] * frame["y"][1],
             frame["x"][2] * frame["y"][0] - frame["x"][0] * frame["y"][2],
             frame["x"][0] * frame["y"][1] - frame["x"][1] * frame["y"][0]]
    return _dot(cross, frame["z"]) > 0


def _rounded(frame):
    """The capture form: origin to 6 digits, unit axes to 9."""
    def unit(v):
        n = math.sqrt(_dot(v, v)) or 1.0
        return [round(c / n, 9) + 0.0 for c in v]
    return {"origin": [round(c, 6) + 0.0 for c in frame["origin"]],
            "x": unit(frame["x"]), "y": unit(frame["y"]), "z": unit(frame["z"])}


def _direct(path, members=_MEMBERS):
    """Candidate A: the transform of the body's own occurrence."""
    return _matrix(path[0], members)


def _along_path(path, members=_MEMBERS):
    """Candidate B: the native occurrence transforms from the top occurrence down, multiplied."""
    total, used = None, set()
    for occurrence in path:  # inner to outer
        frame, member = _matrix(_native(occurrence), members)
        if frame is None:
            return None, ""
        used.add(member)
        total = frame if total is None else _compose(frame, total)
    return total, "path_" + ("transform2" if used == {"transform2"} else "transform")


def _sample_points(body):
    """Up to POINTS_TO_CHECK points in mm: vertices first, then points on faces when there are too few vertices."""
    points = []
    for vertex in geo.collection_items(geo.safe(lambda: body.vertices, None)):
        p = geo.safe(lambda: geo.point(vertex.geometry), None)
        if p is not None:
            points.append(p)
        if len(points) == POINTS_TO_CHECK:
            return points
    for face in geo.collection_items(geo.safe(lambda: body.faces, None)):
        p = geo.safe(lambda: geo.point(face.pointOnFace), None)
        if p is not None:
            points.append(p)
        if len(points) == POINTS_TO_CHECK:
            break
    return points


def _lands_on(frame, native_points, proxy_points):
    return all(max(abs(a - b) for a, b in zip(_map(frame, n), q)) <= POINT_TOLERANCE_MM
               for n, q in zip(native_points, proxy_points))


def _names(path):
    return "+".join(geo.safe(lambda: o.name, "") or "?" for o in reversed(path))


def _failed(path, reason, uses, linked):
    return {"path": path, "error": reason, "uses": uses, "linked": linked}


def read_placement(body, root, component=None):
    """The placement record of a picked body (docs/capture-format.md), or None for a body of the root itself.

    `component` is the body's native component. A failure is not raised: the record then holds `error` and no
    `frame`, and the export lands a fixed shape.
    """
    path = occurrence_path(body)
    if component is None:
        component = geo.safe(lambda: body.parentComponent, None)
    if not path:
        if component is None or geo.same_entity(component, root):
            return None
        return _failed("", "The body was not picked through its place in the assembly.", 1, False)
    name = geo.safe(lambda: path[0].fullPathName, "") or _names(path)
    uses = geo.safe(lambda: int(root.allOccurrencesByComponent(component).count), 1) if component is not None else 1
    linked = any(geo.safe(lambda: bool(o.isReferencedComponent), False) or
                 geo.safe(lambda: bool(_native(o).isReferencedComponent), False) for o in path)
    native = geo.safe(lambda: body.nativeObject, None)
    if native is None:
        return _failed(name, "The body in its component could not be read.", uses, linked)
    native_points, proxy_points = _sample_points(native), _sample_points(body)
    if not native_points or len(native_points) != len(proxy_points):
        return _failed(name, "No points of the body could be compared.", uses, linked)
    found = _checked_frame(path, native_points, proxy_points, "part", "body")
    if "error" in found:
        return _failed(name, found["error"], uses, linked)
    return dict({"path": name}, **found, uses=uses, linked=linked)


def _checked_frame(path, native_points, proxy_points, what, shown):
    """{ frame, source, checked_points } of the first candidate whose frame maps the native points onto the proxy
    points, or { error }. `what` and `shown` word the reason."""
    reason = "The place of the %s could not be read." % what
    for candidate in (_direct, _along_path):
        raw, used = candidate(path)
        if raw is None:
            continue
        if not _rigid(raw):
            reason = "The place of the %s is scaled or mirrored." % what
            continue
        frame = _rounded(raw)
        if not _lands_on(frame, native_points, proxy_points):
            reason = "The place of the %s does not match the %s in the assembly." % (what, shown)
            continue
        return {"frame": frame, "source": used, "checked_points": len(native_points)}
    return {"error": reason}


def _sketch_points(sketch, occurrence):
    """Up to POINTS_TO_CHECK (native, proxy) point pairs of a sketch: in its component's coordinates, and as the
    assembly shows them through `occurrence`."""
    native, proxy = [], []
    for point in geo.collection_items(geo.safe(lambda: sketch.sketchPoints, None)):
        a = geo.safe(lambda: geo.point(point.worldGeometry), None)
        b = geo.safe(lambda: geo.point(point.createForAssemblyContext(occurrence).worldGeometry), None)
        if a is not None and b is not None:
            native.append(a)
            proxy.append(b)
        if len(native) == POINTS_TO_CHECK:
            break
    return native, proxy


def read_sketch_placement(proxy, sketch):
    """Where another component's sketch sits in the assembly: `proxy` is the entity a feature got (seen through an
    occurrence), `sketch` the native sketch. A record like the target's placement, or one with `error`."""
    return sketch_placement_at(occurrence_path(proxy), sketch)


def sketch_placement_at(path, sketch):
    """`read_sketch_placement` for an occurrence path (innermost first) instead of a proxy entity."""
    if not path:
        return {"path": "", "error": "The sketch was not reached through its place in the assembly."}
    name = geo.safe(lambda: path[0].fullPathName, "") or _names(path)
    native_points, proxy_points = _sketch_points(sketch, path[0])
    if not native_points:
        return {"path": name, "error": "No points of the sketch could be compared."}
    return dict({"path": name}, **_checked_frame(path, native_points, proxy_points, "sketch", "sketch"))


def find_occurrence(root, component, path_name=""):
    """The occurrence of `component` to read a borrowed sketch through, as the occurrence path (innermost first), or
    None. `path_name` is the `fullPathName` the capture recorded; without a match, a component with a single
    occurrence is used."""
    found = geo.collection_items(geo.safe(lambda: root.allOccurrencesByComponent(component), None))
    if path_name:
        found = [o for o in found if geo.safe(lambda: o.fullPathName, "") == path_name] or (
            found if len(found) == 1 else [])
    elif len(found) != 1:
        found = []
    if not found:
        return None
    return [found[0]] + occurrence_path(found[0])


_UNREAD = object()


def target_move(ctx):
    """The move from the target's component coordinates to the root's (identity for a root body), or None when the
    target's place cannot be read. Read once per capture."""
    found = getattr(ctx, "_target_move", _UNREAD)
    if found is _UNREAD:
        record = geo.safe(lambda: read_placement(ctx.picked, ctx.root, ctx.component), {})
        if record is None:
            found = Move(IDENTITY_ROWS)
        else:
            found = move_from_frame(record["frame"]) if "frame" in record else None
        ctx._target_move = found
    return found


def _turned(move, v, offset):
    return [round(sum(move.rows[i][k] * v[k] for k in range(3)) + (move.offset[i] if offset else 0.0), 9) + 0.0
            for i in range(3)]


# Members of a component that hold its origin planes and axes (they stay where the component sits).
ORIGIN_MEMBERS = {
    "ConstructionPlane": ("xYConstructionPlane", "xZConstructionPlane", "yZConstructionPlane"),
    "ConstructionAxis": ("xConstructionAxis", "yConstructionAxis", "zConstructionAxis"),
}
# Keys of an axis record that name a sketch line of the target's own sketch. The size probe follows the line natively,
# so a line of another component must not carry them.
_OWN_SKETCH_KEYS = ("entity", "sketch_token", "sketch")


def owner_component(entity):
    """The component that owns an entity: the component of the occurrence it is seen through, else its own."""
    context = geo.safe(lambda: entity.assemblyContext, None)
    if context is not None:
        found = geo.safe(lambda: context.component, None)
        if found is not None:
            return found
    native = geo.safe(lambda: entity.nativeObject, None)
    return geo.component_of(native if native is not None else entity)


def _native_of(entity):
    """The native object of an entity seen through an occurrence, else the entity."""
    if geo.safe(lambda: entity.assemblyContext, None) is None:
        return entity
    return geo.safe(lambda: entity.nativeObject, None) or entity


def _named(entity):
    return {"token": geo.safe(lambda: entity.entityToken, "") or "", "name": geo.safe(lambda: entity.name, "") or ""}


def _is_origin_of(native, component):
    return any(geo.same_entity(native, geo.safe(lambda: getattr(component, member), None))
               for member in ORIGIN_MEMBERS.get(geo.type_name(native), ()))


def _back_move(entity, ctx):
    """The move from root coordinates into the target's, for an entity whose geometry is in root coordinates (seen
    through an occurrence, or owned by the root); None when it is not, or the target's place cannot be read."""
    in_root = geo.safe(lambda: entity.assemblyContext, None) is not None or geo.same_entity(
        geo.component_of(entity), geo.safe(lambda: ctx.root, None))
    move = target_move(ctx) if in_root else None
    return move.inverse() if move is not None else None


def ref_record(entity, ctx, slot, geometry=None):
    """The measured reference to an entity of another component (docs/capture-format.md "Measured references").

    `slot` says where the step uses it (`start`, `side_one`, `side_two`, `plane`, `axis`, `positions.<n>`). The
    record names the entity the way the sketch scan can find it again (`token` of the native entity, its `type`, the
    owning `component`, the `body` or `sketch` it belongs to, the occurrence `path`) and holds its geometry brought
    into the target's coordinates: `point` and `normal` or `dir`, and `face_point` for a face. `geometry` is the entity's
    own plane or axis as read in root coordinates (`point`, `normal`, `dir`); without it a flat face or construction
    plane gives its plane. The geometry is left out when the entity is not in root coordinates or the target's place
    cannot be read. `origin` is true for an origin plane or axis of the owner: it only moves with the occurrence.
    """
    native = _native_of(entity)
    kind = geo.type_name(native)
    owner = owner_component(entity)
    out = {"slot": slot, "type": kind, "token": geo.safe(lambda: native.entityToken, "") or "",
           "component": _named(owner) if owner is not None else {"token": "", "name": ""},
           "path": geo.safe(lambda: entity.assemblyContext.fullPathName, "") or ""}
    for key, member in (("body", "body"), ("sketch", "parentSketch")):
        found = geo.safe(lambda: _native_of(getattr(native, member)), None)
        if found is not None and _named(found)["token"]:
            out[key] = _named(found)
    if owner is not None and _is_origin_of(native, owner):
        out["origin"] = True
    back = _back_move(entity, ctx)
    if back is None:
        return out
    if geometry is None:
        geometry = geo.safe(lambda: geo.plane_of(entity), None) or {}
    if kind == "BRepFace":
        geometry = dict(geometry, face_point=geo.safe(lambda: geo.point(entity.pointOnFace), None))
    for key, value in geometry.items():
        if value is not None:
            out[key] = _turned(back, value, key in ("point", "face_point"))
    return out


def from_assembly(record, entity, ctx, point="point", direction="normal", slot=None):
    """A plane or axis record of another component brought into the target's coordinates.

    Such an entity is seen through an occurrence or belongs to the root, so its geometry is in the root's
    coordinates. The record then carries `assembly: true` instead of `foreign`; when the target's place is unknown,
    or the entity is neither, it stays foreign. With `slot` the record also gets its measured reference (`ref`).
    """
    if not isinstance(record, dict) or not record.get("foreign") or point not in record or direction not in record:
        return record
    back = _back_move(entity, ctx)
    if back is None:
        return record
    out = {k: v for k, v in record.items() if k != "foreign" and k not in _OWN_SKETCH_KEYS}
    out[point] = _turned(back, record[point], True)
    out[direction] = _turned(back, record[direction], False)
    out["assembly"] = True
    if slot is not None:
        out["ref"] = ref_record(entity, ctx, slot, {point: record[point], direction: record[direction]})
    return out


def foreign_target_ref(record, entity, ctx, slot):
    """Adds the measured reference (`ref`) to the extent or start record `record` of a face or plane of another
    component. The record itself stays foreign: the walk refuses the step."""
    plane = record.get("plane") if isinstance(record, dict) else None
    ref = geo.safe(lambda: ref_record(entity, ctx, slot, plane or {}), None)
    if ref is not None:
        record["ref"] = ref
    return record


# ---- bodies of other components used as tools ---------------------------------------------------------------------

# The origin planes of a component, by the slot name of their reference: they move only with the component's place.
PLANE_SLOTS = (("xy", "xYConstructionPlane"), ("xz", "xZConstructionPlane"), ("yz", "yZConstructionPlane"))
_PROBE_LENGTH_MM = 10.0
ROOT_FRAME = {"origin": [0.0, 0.0, 0.0], "x": [1.0, 0.0, 0.0], "y": [0.0, 1.0, 0.0], "z": [0.0, 0.0, 1.0]}


def tool_identity(body):
    """What a Combine's tool body of another component needs to be found and read again: the native `token` and
    `name`, the owning `component` and the `path` of the occurrence it is seen through (empty for the root)."""
    native = _native_of(body)
    owner = owner_component(body)
    return {"token": geo.safe(lambda: native.entityToken, "") or "", "name": geo.safe(lambda: native.name, "") or "",
            "component": _named(owner) if owner is not None else {"token": "", "name": ""},
            "path": geo.safe(lambda: body.assemblyContext.fullPathName, "") or ""}


def _origin_planes(component, occurrence):
    """`{ slot: (native plane, plane seen through occurrence) }` for the origin planes that can be shown through the
    occurrence."""
    out = {}
    for slot, member in PLANE_SLOTS:
        native = geo.safe(lambda: getattr(component, member), None)
        proxy = geo.safe(lambda: native.createForAssemblyContext(occurrence), None) if native is not None else None
        if native is not None and proxy is not None:
            out[slot] = (native, proxy)
    return out


def _tip(plane):
    """The point 10 mm out along the normal of a plane, in the coordinates the plane is shown in."""
    found = geo.safe(lambda: geo.plane_of(plane), None)
    if not found:
        return None
    return [found["point"][i] + _PROBE_LENGTH_MM * found["normal"][i] for i in range(3)]


def component_place(root, component, path_name=""):
    """`(record, planes)`: where a component sits in the assembly, as `read_placement` records a body's place, and its
    origin planes seen through the occurrence. The record is None for the root. The frame is checked by the three
    origin planes (the point 10 mm along each normal, native against shown), since only they can be shown through an
    occurrence without a body. A failure is `{ "path", "error" }`."""
    if component is None:
        return {"path": path_name, "error": "The component could not be read."}, {}
    if geo.same_entity(component, root):
        return None, {}
    path = find_occurrence(root, component, path_name)
    if not path:
        return {"path": path_name, "error": "The place of the component could not be found."}, {}
    name = geo.safe(lambda: path[0].fullPathName, "") or _names(path)
    planes = _origin_planes(component, path[0])
    native_points = [_tip(n) for n, _ in planes.values()]
    proxy_points = [_tip(p) for _, p in planes.values()]
    if len(planes) < POINTS_TO_CHECK or None in native_points or None in proxy_points:
        return {"path": name, "error": "No planes of the component could be compared."}, planes
    found = _checked_frame(path, native_points, proxy_points, "component", "origin planes")
    if "error" in found:
        return {"path": name, "error": found["error"]}, planes
    return dict({"path": name}, **found), planes


def target_place_now(ctx):
    """The place of the target's component as it is at the current marker position: a record of `component_place`,
    or None for a body of the root."""
    context = geo.safe(lambda: ctx.picked.assemblyContext, None)
    if context is None:
        return None
    return component_place(ctx.root, ctx.component, geo.safe(lambda: context.fullPathName, "") or "")[0]


def tool_place(ctx, component, path_name, number):
    """The place of a tool body's component relative to the target, with the marker at the Combine: the component's
    `frame` in the root's coordinates, the target's own (`target_frame`, or `target_error`), and for each origin plane
    of the component a measured reference (`xy`, `xz`, `yz`, slot `tool<number>.<plane>`) that the size probe reads
    again at other sizes. A tool in the root has the identity frame and no references."""
    record, planes = component_place(ctx.root, component, path_name)
    if record is None:
        record = {"path": "", "frame": dict(ROOT_FRAME), "source": "root", "checked_points": 0}
    if "error" in record:
        return record
    target = target_place_now(ctx)
    if target is None:
        record["target_frame"] = None
    elif "frame" in target:
        record["target_frame"] = target["frame"]
    else:
        record["target_error"] = target.get("error") or "The place of the part could not be read."
    for slot, (_, proxy) in planes.items():
        ref = geo.safe(lambda: ref_record(proxy, ctx, "tool%d.%s" % (number, slot)), None)
        if ref is not None:
            record[slot] = {"ref": ref}
    return record
