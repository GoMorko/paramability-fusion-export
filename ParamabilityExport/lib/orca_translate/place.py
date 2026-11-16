"""Where the copy sits in Orca: the map from the capture's coordinates to Orca's plate, and the sketch planes.

Capture values are in the coordinates of the body's component (mm). They go to the root of the design
(`target.placement`), turn so the design's up axis is Orca's Z, then move so the part's box is centred on the bed
centre and its lowest point lies on the bed. The bed centre is also the recipe's modeling origin: Orca draws its
base planes through it. The plate mesh, read in root coordinates, takes the same turn and move.

The box is the Fusion part's, unless steps are left out and what the copy builds has another box (`copy_box`, from
`solid.Solid.box`): then the copy is placed by its own box. The mesh is the real Fusion body, so it keeps the same
turn and move across the bed, and `orca_export` lowers or raises it alone onto the bed.
"""
from ..geometry import rigid, vec
from ..orca_recipe.sketch import SketchPlane

# The centre of a 256 mm bed, where Orca's Design tab puts its modeling origin for such a printer.
BED_CENTRE = (128.0, 128.0, 0.0)
# The copy is placed by its own box when that differs from the Fusion part's box by more than this (mm).
OWN_BOX_TOL = 0.01


def apply(move, point):
    """A position through a rigid move."""
    return tuple(sum(move.rows[i][k] * point[k] for k in range(3)) + move.offset[i] for i in range(3))


def turn(move, direction):
    """A direction through a rigid move (rotation only)."""
    return tuple(sum(move.rows[i][k] * direction[k] for k in range(3)) for i in range(3))


def _corners(box):
    lo, hi = box["min"], box["max"]
    return [(x, y, z) for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])]


def box_of(points):
    """`{min, max}` of points, or None when there are none."""
    points = list(points)
    if not points:
        return None
    return {"min": [min(p[i] for p in points) for i in range(3)], "max": [max(p[i] for p in points) for i in range(3)]}


def moved_box(move, box):
    """The box around the eight corners of `box` after `move`."""
    return box_of(apply(move, c) for c in _corners(box))


def copy_box(ctx):
    """The box of what the copy builds (`solid.Solid.box`, capture coordinates) when steps are left out and that box
    differs from the Fusion part's, else None: the part is then placed by the copy's own box, so it neither floats
    above the bed nor sinks into it."""
    if not ctx.left_out or not ctx.part.has_body:
        return None
    box = ctx.part.solid.box()
    target = (ctx.capture.get("target") or {}).get("box")
    if box is None:
        return None
    if _valid_box(target) and max(abs(box[k][i] - target[k][i]) for k in ("min", "max") for i in range(3)) \
            <= OWN_BOX_TOL:
        return None
    return box


def _valid_box(box):
    try:
        return all(len(box[k]) == 3 and all(isinstance(v, (int, float)) for v in box[k]) for k in ("min", "max"))
    except (KeyError, TypeError):
        return False


class Placement:
    """The maps of one capture: `to_orca` for capture values (component coordinates) and `root_to_orca` for the
    mesh (root coordinates). `shift` is the move that puts the part on the bed centre; `bed` the bed centre."""

    def __init__(self, capture, bed=BED_CENTRE, box=None):
        self.bed = tuple(float(c) for c in bed)
        # Component to root, then the up axis turn (`rigid.move_for`).
        turned = rigid.move_for(capture)
        up = rigid.TURN_Z_UP if capture.get("up_axis") == "y" else rigid.Move(rigid.IDENTITY_ROWS)
        target_box = box if box is not None else (capture.get("target") or {}).get("box")
        if _valid_box(target_box):
            seen = moved_box(turned, target_box)
            centre = [(seen["min"][i] + seen["max"][i]) / 2.0 for i in range(3)]
            self.shift = (self.bed[0] - centre[0], self.bed[1] - centre[1], self.bed[2] - seen["min"][2])
        else:
            self.shift = self.bed
        move = rigid.Move(rigid.IDENTITY_ROWS, self.shift)
        self.to_orca = turned.then(move)
        self.root_to_orca = up.then(move)

    def point(self, p):
        return apply(self.to_orca, p)

    def direction(self, d):
        return turn(self.to_orca, d)

    def plane(self, origin, x_axis, y_axis, normal):
        """An Orca sketch plane from a frame in capture coordinates; the axes are made unit length."""
        return SketchPlane(self.point(origin), tuple(vec.unit(list(self.direction(normal)))),
                           tuple(vec.unit(list(self.direction(x_axis)))), tuple(vec.unit(list(self.direction(y_axis)))))


def plane_point(plane, xy):
    """A point of an Orca sketch plane in world millimetres, as Orca's `SketchPlane::to_world` gives it."""
    return tuple(plane.origin[i] + plane.x_axis[i] * xy[0] + plane.y_axis[i] * xy[1] for i in range(3))
