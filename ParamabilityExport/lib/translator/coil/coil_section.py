"""The wire's section: a flat end face of the coil read as a recipe loop, with its outline, area and centre.

Only the shapes the recipe can sweep with a formula or as measured are taken: a circle, a rectangle (a square wire)
and a polygon (a triangle wire).
"""
import math

from ...geometry import vec
from ..result import Refusal
from ..sketch import loops
from . import coil_limits as limits

ROUND_STEPS = 48
KINDS = ("circle", "rect", "polygon")


def outline(loop):
    """The closed outline of a recipe loop as 2D points (a circle as ROUND_STEPS points)."""
    if loop["kind"] == "circle":
        cx, cy = loop["center"]
        r = loop["radius"]
        return [[cx + r * math.cos(2 * math.pi * n / ROUND_STEPS), cy + r * math.sin(2 * math.pi * n / ROUND_STEPS)]
                for n in range(ROUND_STEPS)]
    if loop["kind"] == "rect":
        cx, cy = loop["center"]
        w, h = loop["width"] / 2.0, loop["height"] / 2.0
        a = math.radians(loop.get("angleDeg", 0.0))
        c, s = math.cos(a), math.sin(a)
        return [[cx + x * c - y * s, cy + x * s + y * c] for x, y in ((-w, -h), (w, -h), (w, h), (-w, h))]
    return [list(p) for p in loop["points"]]


def moments(loop):
    """`(area, centre)` of a recipe loop; a circle and a rectangle exactly, a polygon from its corners."""
    if loop["kind"] == "circle":
        return math.pi * loop["radius"] ** 2, list(loop["center"])
    if loop["kind"] == "rect":
        return loop["width"] * loop["height"], list(loop["center"])
    points = outline(loop)
    twice = cx = cy = 0.0
    for a, b in zip(points, points[1:] + points[:1]):
        cross = a[0] * b[1] - b[0] * a[1]
        twice += cross
        cx += (a[0] + b[0]) * cross
        cy += (a[1] + b[1]) * cross
    if abs(twice) < 1e-12:
        return 0.0, [0.0, 0.0]
    return abs(twice) / 2.0, [cx / (3.0 * twice), cy / (3.0 * twice)]


def cap_of(record):
    """The flat end face `record` (the reader's `faces.flat` entry) as `{ frame, loop, area, centre }`, `centre` being
    the section's centre in model coordinates; or a Refusal. The face must be one outline without holes that fills the
    face (Fusion's own area agrees with the outline)."""
    frame, drawn = record.get("frame"), record.get("loops")
    if not isinstance(frame, dict) or not isinstance(drawn, list) or len(drawn) != 1 or not drawn[0].get("outer"):
        return Refusal(limits.SECTION)
    loop = loops.loop_of(drawn[0].get("curves") or [])
    if isinstance(loop, Refusal) or loop["kind"] not in KINDS:
        return Refusal(limits.SECTION)
    area, centre = moments(loop)
    if not area > 0 or abs(area - record.get("area", -1.0)) > limits.AREA_TOL * area:
        return Refusal(limits.PLACE)
    return {"frame": frame, "loop": loop, "area": area, "centre": vec.frame_apply(frame, [centre[0], centre[1], 0.0])}


def outline_3d(cap):
    """The outline of a cap in model coordinates."""
    return [vec.frame_apply(cap["frame"], [p[0], p[1], 0.0]) for p in outline(cap["loop"])]
