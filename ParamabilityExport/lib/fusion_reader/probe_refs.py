"""One probe state of the measured references (agent-docs/capture-format.md, "Measured references" and "Probe states").

A reference is a plane, axis, direction or point of another component that a step uses. It is found again by the
token of its native entity, shown through the occurrence it was captured through as that occurrence sits now, and
brought into the target's coordinates by the target's own place as it is now (a size can move either component). A
face or plane of the part itself (`own`) is read natively, in the part's coordinates like the capture.
Everything is plain data in mm. A reference that cannot be read is left out with a reason; nothing here raises, and
nothing here changes the design. No adsk import.
"""
from . import placement
from . import read_geometry as geo
from .read_repeat import direction_of
from .read_solid import axis_of
from ..geometry.rigid import IDENTITY_ROWS, Move, move_from_frame

NOT_FOUND = "It was not found."
NO_OCCURRENCE = "The place of its component could not be found."
NO_PROXY = "It could not be shown through its component's place."
NO_GEOMETRY = "Its geometry could not be read."
NO_TARGET_PLACE = "The place of the part could not be read."


def _apply(move, v, offset):
    return [round(sum(move.rows[i][k] * v[k] for k in range(3)) + (move.offset[i] if offset else 0.0), 9) + 0.0
            for i in range(3)]


def _target_back(ctx):
    """`(move, reason)`: the move from root coordinates into the target's as the target sits now. The picked body is
    shown again through its occurrence, since the one picked at the start may be stale after a recompute."""
    picked = ctx.picked
    occurrence = geo.safe(lambda: picked.assemblyContext, None)
    body = picked
    if occurrence is not None:
        native = ctx.find_target()
        body = geo.safe(lambda: native.createForAssemblyContext(occurrence), None) if native is not None else None
    record = geo.safe(lambda: placement.read_placement(body, ctx.root, ctx.component), {}) if body is not None else {}
    if record is None:
        return Move(IDENTITY_ROWS), ""
    if "frame" in record:
        return move_from_frame(record["frame"]).inverse(), ""
    return None, record.get("error") or NO_TARGET_PLACE


def _point_of(entity):
    for member in ("worldGeometry", "geometry"):
        found = geo.safe(lambda: geo.point(getattr(entity, member)), None)
        if found is not None:
            return found
    return None


def _geometry(entity, shape):
    """The entity's place in the coordinates the entity is shown in: `{ point, normal }`, `{ point, dir }`,
    `{ dir }` or `{ point }`; None when it cannot be read."""
    if shape == "plane":
        found = geo.safe(lambda: geo.plane_of(entity), None)
    elif shape == "axis":
        found = geo.safe(lambda: axis_of(entity), None)
        found = {"point": found["point"], "dir": found["dir"]} if isinstance(found, dict) and (
            "point" in found and "dir" in found) else None
    elif shape == "direction":
        direction = geo.safe(lambda: direction_of(entity), None)
        found = {"dir": direction} if direction is not None else None
    else:
        point = _point_of(entity)
        found = {"point": point} if point is not None else None
    return found


class _Occurrences:
    """The occurrence path of each component and path name asked for, found once per read."""

    def __init__(self, root):
        self.root, self.found = root, {}

    def path(self, native, name):
        component = geo.component_of(native)
        key = (id(component), name)
        if key not in self.found:
            self.found[key] = placement.find_occurrence(self.root, component, name) if component is not None else None
        return self.found[key]


def _read_one(design, hint, back, occurrences):
    """`(geometry, reason)` of one reference in the target's coordinates."""
    native = geo.find_native(design, hint.get("token") or "")
    if native is None:
        return None, NOT_FOUND
    entity = native
    if hint.get("own"):
        back = Move(IDENTITY_ROWS)
    elif hint.get("path"):
        path = occurrences.path(native, hint["path"])
        if not path:
            return None, NO_OCCURRENCE
        entity = geo.safe(lambda: native.createForAssemblyContext(path[0]), None)
        if entity is None:
            return None, NO_PROXY
    found = _geometry(entity, hint.get("shape") or "")
    if found is None:
        return None, NO_GEOMETRY
    return {key: _apply(back, value, key == "point") for key, value in found.items()}, ""


def read_refs(design, ctx, wanted):
    """`(found, unread)` for `wanted` ({ key: { token, path, shape, own } }): `found` maps a key to the reference's
    place in the target's coordinates, `unread` a key to why it was left out."""
    found, unread = {}, {}
    if not wanted:
        return found, unread
    back, reason = _target_back(ctx)
    occurrences = _Occurrences(ctx.root)
    for key, hint in wanted.items():
        if back is None and not hint.get("own"):
            unread[key] = reason
            continue
        place, why = geo.safe(lambda: _read_one(design, hint, back, occurrences), (None, NO_GEOMETRY))
        if place is None:
            unread[key] = why
        else:
            found[key] = place
    return found, unread
