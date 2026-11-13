"""What the sweep options ask of a path (`PathOptions`) and the path the planner found (`PathPlan`). Pure."""
import math
from dataclasses import dataclass
from typing import Optional


@dataclass
class PathOptions:
    """What the sweep's options ask of the path.

    as_step: a line or an arc is written as a `sweep` step path, not left to an extrude or a revolve.
    twisted: the outline turns about the path, so all of its reach counts at a bend.
    tapered: the outline's walls lean along the path.
    growth: the most the outline's walls can lean out, per mm of path (tangent of the taper angle times the outline's
      corner factor; 0 without a taper).
    fixed: the outline keeps its direction; the path must keep moving along its normal (no bend or overlap checks).
    """

    as_step: bool = False
    twisted: bool = False
    tapered: bool = False
    growth: float = 0.0
    fixed: bool = False


@dataclass
class PathPlan:
    """A path ready for the sweep handler.

    kind: `line`, `arc`, `circle`, `flat` or `corners`.
    curves: the chained curves, oriented along the path, the first one starting on the outline's plane.
    start, end: the path ends (3D). For a circle both are the point of the circle on the outline's plane.
    direction: unit direction of travel at `start`.
    length: path length in mm.
    reversed: the capture listed the path from the far end, so the chain was turned round.
    recipe: the `flat` or `corners` path of the sweep step, else None. `corners` points are 3D in capture
      coordinates, `bendRadius` one number when every bend has it, else one per inner point.
    axis: for an arc or circle, `{ "point": centre, "dir": unit }` with the path turning positively about `dir`.
    radius, angle_deg: for an arc or circle (360).
    tightest: for a `flat` or `corners` path, the radius of its tightest bend (infinity when it has none).
    closed: a flat path that ends where it starts (`end` is `start`, there are no end faces).
    winding: for a closed path, 1 when it runs counter clockwise about the normal of its plane, else -1.
    """

    kind: str
    curves: list
    start: list
    end: list
    direction: list
    length: float
    reversed: bool = False
    recipe: Optional[dict] = None
    axis: Optional[dict] = None
    radius: Optional[float] = None
    angle_deg: Optional[float] = None
    tightest: float = math.inf
    closed: bool = False
    winding: int = 0
