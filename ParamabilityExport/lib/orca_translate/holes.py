"""Hole steps of the capture as Orca Hole features. The handler returns the features it wrote, or a `Skip` with the
reason the step is left out of the copy.

Simple, counterbore and countersink holes; a depth or through all; one Orca hole per position, on a plane whose normal
is the drilling direction (Orca drills along the normal): the sketch plane with the centre's sketch coordinates when
they are known (`hole_place`), else a plane at the centre. A tapped hole is drilled at the drill size of a cosmetic
thread, or at the minor diameter of a modeled one with an Orca thread after it (`threads`). A hole that does not meet
the part the copy built (`solid.Solid`) is left out: Orca stops the whole rebuild on a hole that removes nothing. A
through all hole with no measured bottom goes to the side where it meets that part when Fusion's stored direction
meets none (`steps.toward_material`).
"""
import math

from ..capture_model import gap_hints
from ..geometry import vec
from ..orca_recipe.enums import FeatureType
from ..orca_recipe.feature import CadFeature
from . import causes, finish_body, hole_place, threads
from ..design_model.values import Quantity
from .skip import Skip
from .solid import CUT, Prism
from .steps import LONG, SIDE_TOL, behind, misses_reason, toward_material
from .tools import data_of, label


def _perpendicular(n):
    """A unit vector at right angles to `n`."""
    helper = [0.0, 0.0, 1.0] if abs(n[2]) < 0.9 else [1.0, 0.0, 0.0]
    return vec.unit(vec.cross(helper, n))


def hole(ctx, item):
    """The Orca hole features of a hole step (one per position, and a thread after each tapped one), or a Skip."""
    data = data_of(item)
    if not ctx.has_body:
        return Skip("The part this hole is drilled into is not in the copy.", gap_hints.AFTER_GAP)
    kind = data.get("hole_type")
    if kind not in ("simple", "counterbore", "countersink"):
        return Skip("This kind of hole is not copied yet.")
    if data.get("tap_type") not in ("simple", "clearance", "tapped", "taperTapped", None):
        return Skip("This kind of hole is not copied yet.")
    if data.get("foreign"):
        return Skip("This hole is placed on another component, which is not copied yet.",
                    gap_hints.OTHER_COMPONENT)
    direction = data.get("direction")
    positions = data.get("positions") or []
    if not isinstance(direction, (list, tuple)) or not positions or not isinstance(data.get("diameter"),
                                                                                       (int, float)):
        return Skip("This hole could not be read.")
    extent = data.get("extent") or {}
    if extent.get("kind") not in ("distance", "throughAll"):
        return Skip("This hole goes up to a face, which the Orca copy does not follow yet.",
                    gap_hints.EXTRUDE_END_FACE)
    spec, tapped = None, data.get("tap_type") in ("tapped", "taperTapped")
    if tapped:
        found = threads.tapped(item, data)
        if isinstance(found, Skip):
            return found
        bore, spec = found
        held = ctx.quantity(item, "diameter", float(data["diameter"]))
        ctx.doubt(held.reads, "%s: the thread size stays as drawn in Orca" % label(item))
        diameter = Quantity(bore)
    else:
        diameter = ctx.quantity(item, "diameter", float(data["diameter"]))
    normal = vec.unit(list(direction))
    ends = [p for p in data.get("end_points") or [] if isinstance(p, (list, tuple))]
    if ends and len(ends) == len(positions) and vec.dot(vec.sub(list(ends[0]), list(positions[0])), normal) < -SIDE_TOL:
        normal = vec.scale(normal, -1.0)  # the measured bottom wins over the stored direction
    depth = None
    if extent["kind"] == "distance":
        depth = ctx.quantity(item, "extent.depth", float(extent["depth"]))
        if "cone" in (data.get("end_face_types") or []):
            ctx.notes.append("%s: the drill point at the bottom is left flat in Orca." % label(item))
    box = (item.get("target_before") or {}).get("box") or data.get("target_box_before")
    style, extra = 0, []
    if kind == "counterbore" and isinstance(data.get("counterbore"), dict):
        style = 1
        cb = data["counterbore"]
        extra = [("hole_cbore_diameter", "counterbore diameter",
                  ctx.quantity(item, "counterbore.diameter", float(cb["diameter"]))),
                 ("hole_cbore_depth", "counterbore depth", ctx.quantity(item, "counterbore.depth", float(cb["depth"])))]
    elif kind == "countersink" and isinstance(data.get("countersink"), dict):
        style = 2
        cs = data["countersink"]
        extra = [("hole_csink_diameter", "countersink diameter",
                  ctx.quantity(item, "countersink.diameter", float(cs["diameter"]))),
                 ("hole_csink_angle", "countersink angle",
                  ctx.quantity(item, "countersink.angle_deg", float(cs["angle_deg"]), "angle"))]
    elif kind != "simple":
        return Skip("This hole could not be read.")
    if spec is not None and style:
        return Skip("This tapped hole has a %s, and the copy cannot tell where Fusion starts its thread then, so it is "
                    "left out." % ("counterbore" if style == 1 else "countersink"), causes.TAPPED_RECESS)
    radius = diameter.n / 2.0
    if depth is None and not (ends and len(ends) == len(positions)):
        if toward_material(ctx, item, lambda low, high: [_bore(p, normal, radius, low, high) for p in positions],
                            1) < 0:
            normal = vec.scale(normal, -1.0)
    lengths = None
    if spec is not None:
        lengths = threads.hole_lengths(item, data, spec, positions, normal, depth, ctx)
        if isinstance(lengths, Skip):
            return lengths
    drilled, measured = [], []
    for n, position in enumerate(positions):
        if depth is not None:
            reach = (0.0, depth.n)
        elif behind(box, position, normal, 1):
            reach = (0.0, LONG)
        else:
            reach = (-math.inf, math.inf)
        tools = [_bore(position, normal, radius, *reach)]
        if style == 1:
            tools.append(_bore(position, normal, float(cb["diameter"]) / 2.0, 0.0, float(cb["depth"])))
        measured.append((n, tools))
        if any(ctx.solid.meets(t) for t in tools):
            drilled.append((n, position, tools))
    if not drilled:
        if any(finish_body.only_rounded(ctx.solid, t) for _, tools in measured for t in tools):
            return Skip("This hole meets the part only next to edges that an earlier round or chamfer took, where "
                        "Orca may find no material, and Orca stops the whole rebuild on a hole that removes nothing, "
                        "so it is left out.", causes.NEAR_ROUND)
        return Skip(*misses_reason(ctx, "hole"))
    if len(drilled) < len(positions):
        ctx.notes.append("%s: %d of its holes do not meet the part as the Orca copy builds it and are left out."
                         % (label(item), len(positions) - len(drilled)))
    found = hole_place.places(ctx, item, data, normal, positions)
    ends = {}
    for n, _, _ in drilled if spec is not None else ():
        ends[n] = threads.hole_ends(ctx, found[n], spec, lengths[n], label(item))
        if isinstance(ends[n], Skip):
            return ends[n]

    out = []
    for number, (n, position, tools) in enumerate(drilled, start=1):
        for tool in tools:
            ctx.solid.add(CUT, tool)
        name = label(item) if len(drilled) == 1 else "%s (%d)" % (label(item), number)
        where = found[n]
        plane = where.plane(ctx.place)
        feature = CadFeature(type=FeatureType.HOLE, name=name, plane=plane, hole_style=style,
                             thread_major_nominal=True, pattern_inclusive=True)
        ctx.bind(feature, "hole_x", where.x_value, "%s place" % name)
        ctx.bind(feature, "hole_y", where.y_value, "%s place" % name)
        ctx.bind(feature, "hole_diameter", diameter, "%s diameter" % name)
        if depth is not None:
            feature.hole_through = False
            ctx.bind(feature, "hole_depth", depth, "%s depth" % name)
        elif behind(box, position, normal, 1):
            feature.hole_through = False
            ctx.bind(feature, "hole_depth", Quantity(LONG), name)
        else:
            feature.hole_through = True
        for field, words, value in extra:
            ctx.bind(feature, field, value, "%s %s" % (name, words))
        ctx.add(feature)
        out.append(feature)
        if spec is not None:
            out += threads.hole_thread(ctx, name, where, spec, lengths[n], ends[n])
    if spec is not None:
        ctx.notes.append(threads.note(label(item), True, any(e.open for e in ends.values())))
    elif tapped:
        ctx.notes.append(threads.COSMETIC_NOTE % label(item))
    return out


def _bore(position, normal, radius, low, high):
    """The prism of a round hole of `radius` at `position`, drilled along `normal` between two heights."""
    x_axis = _perpendicular(normal)
    frame = {"origin": list(position), "x": x_axis, "y": vec.cross(normal, x_axis), "z": list(normal)}
    return Prism(frame, [[{"kind": "circle", "center": [0.0, 0.0], "radius": radius}]], low, high)


HANDLERS = {"HoleFeature": hole}
