"""Boxes around the material of written steps, in model space, for checks that need to know where material may lie
(faces/floating.py, faces/added_bounds.py). A box is `(min, max)`, two [x, y, z] lists in mm. `UNKNOWN` stands for
material whose box cannot be told.
"""
from ...geometry import vec
from ...geometry.footprint import polyline
from .end_caps import EndCaps
from .moved_placer import MovedPlacer
from .offset_faces import MovedFaces
from .shells import OutsideShell, Shell
from .slabs import Slab
from .thin_wall import ThinWall
from .tool_placer import ToolPlacer

UNKNOWN = object()


def footprint_box(slab):
    points = [p for curve in slab.footprint.curves for p in polyline(curve)]
    if not points:
        return None
    return (min(p[0] for p in points), min(p[1] for p in points), max(p[0] for p in points), max(p[1] for p in points))


def model_point(slab, uv, h):
    """The point at sketch position `uv` and height `h` above the slab's base, in model space."""
    flat = vec.frame_apply(slab.frame, [uv[0], uv[1], 0.0])
    dz = vec.dot(slab.frame["z"], slab.axis)
    return vec.frame_apply(slab.frame, [uv[0], uv[1], (h + slab.base - vec.dot(flat, slab.axis)) / dz])


def slab_lean(slab):
    """How far the walls of a tapered slab lean out over its length, in mm."""
    low, high = slab.span
    return abs(math.tan(math.radians(slab.taper.n))) * (high - low) if slab.taper is not None else 0.0


def box_of(points):
    if not points:
        return None
    return ([min(p[i] for p in points) for i in range(3)], [max(p[i] for p in points) for i in range(3)])


def union(boxes):
    if not boxes or any(box is None for box in boxes):
        return None
    return ([min(b[0][i] for b in boxes) for i in range(3)], [max(b[1][i] for b in boxes) for i in range(3)])


def grown(box, by):
    return None if box is None else ([c - by for c in box[0]], [c + by for c in box[1]])


def meets(a, b):
    return all(a[0][i] <= b[1][i] and b[0][i] <= a[1][i] for i in range(3))


def overlap(a, b):
    return ([max(a[0][i], b[0][i]) for i in range(3)], [min(a[1][i], b[1][i]) for i in range(3)])


def slab_box(slab, grow=0.0):
    """The box of a slab's solid in model space (a copy where its motion carries it), its sides moved out by `grow`."""
    box = footprint_box(slab)
    if box is None:
        return None
    low, high = slab.span
    lean = slab_lean(slab) + grow
    corners = [model_point(slab, [u, v], h) for u in (box[0] - lean, box[2] + lean)
               for v in (box[1] - lean, box[3] + lean) for h in (low, high)]
    if slab.is_copy:
        corners = [slab.motion.numbers(p) for p in corners]
    return box_of(corners)


def slab_corners(slab):
    """The corners of a slab's outline at both ends, in model space (a copy where its motion carries it)."""
    low, high = slab.span
    flat = [p for curve in slab.footprint.curves for p in polyline(curve)]
    out = [model_point(slab, uv, h) for uv in flat for h in (low, high)]
    return [slab.motion.numbers(p) for p in out] if slab.is_copy else out


def face_box(frame, footprint, distance):
    """The box of the prism an offsetFaces step sweeps a face through."""
    flat = [p for curve in footprint.curves for p in polyline(curve)]
    return box_of([vec.frame_apply(frame, [p[0], p[1], h]) for p in flat for h in (0.0, distance)])


def material_boxes(placers, motion=None):
    """`[(box, corners)]` of the material the placers may add, a slab's outline corners in `corners` ([] for another
    step), or UNKNOWN when the box of one cannot be told. `motion` carries the boxes of a moved step's placers."""
    found = []
    for placer in placers:
        if isinstance(placer, (Shell, OutsideShell, EndCaps)):
            continue
        if isinstance(placer, Slab):
            if placer.combine not in ("new", "add"):
                continue
            box, corners = slab_box(placer), slab_corners(placer)
        elif isinstance(placer, ThinWall):
            if placer.combine not in ("new", "add"):
                continue
            box, corners = slab_box(placer.slab, max(abs(b) for b in placer.band)), []
        elif isinstance(placer, MovedFaces):
            if placer.distance.n <= 0:
                continue
            boxes = [face_box(frame, footprint, placer.distance.n) for frame, footprint in placer.faces]
            boxes += [ring.box(max(ring.radius, ring.moved_radius(placer.distance.n))) for ring in placer.rings]
            box, corners = (union(boxes) if boxes else None), []
        elif isinstance(placer, (ToolPlacer, MovedPlacer)):
            inner = placer.placers if isinstance(placer, ToolPlacer) else [placer.inner]
            if isinstance(placer, ToolPlacer) and placer.combine == "cut":
                continue
            more = material_boxes(inner, placer.motion if isinstance(placer, MovedPlacer) else None)
            if more is UNKNOWN:
                return UNKNOWN
            found += [(b, c) for b, c in more] if motion is None else [moved(motion, b, c) for b, c in more]
            continue
        else:
            return UNKNOWN
        if box is None:
            return UNKNOWN
        found.append((box, corners) if motion is None else moved(motion, box, corners))
    return found


def moved(motion, box, corners):
    """A box and corners carried by `motion` (`slabs.Motion`)."""
    ends = [[box[k][0], box[j][1], box[i][2]] for k in (0, 1) for j in (0, 1) for i in (0, 1)]
    return box_of([motion.numbers(p) for p in ends]), [motion.numbers(p) for p in corners]
