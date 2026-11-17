"""Draft handler (DraftFeature): the picked faces lean about the neutral plane, the recipe's `draft` step.

The recipe step leans faces about where they meet the neutral plane, and a positive angle takes material off the side
the pull direction points to. Fusion's API does not say which way its angle and its flip turn a face, so the copy
reads it from the part: with every face on one side of the plane, a draft that removes material leans the way that
takes material off there. The part's volume must change.

A Symmetric draft with faces on both sides of the plane leans each side away from the plane by the same angle, so both
sides take material off together or both add it, and the volume change tells which. The step then carries the angle
twice, `angleDeg` and `angleTwoDeg`, with one sign. Two Sides drafts with different angles are left out: the API does
not say which angle belongs to the side the pull direction points to, and one volume cannot tell it. So are a draft
with faces on both sides that is not Symmetric, and an angle at the recipe's cap.

The angle follows its sizes, and the size ranges are cut where it would reach zero or the recipe's cap; a draft with two angles
follows them only when both come from the same formula. The faces are picked by points on them, like the open faces of a shell, and the plane
follows sizes like a mirror plane.
"""
from ...capture_model import gap_hints
from ...design_model.values import Quantity
from ...geometry import vec
from .. import values
from ..bodies.split import SIDE_TOL_MM
from ..extrude import keep_angle_within
from ..faces import follow, picks
from ..repeat.repeat_build import round_vec
from ..result import Refusal, StepResult

# The recipe refuses a draft angle at or past this, either way.
MAX_ANGLE_DEG = 30.0
# A smaller change of the part's volume (mm3) does not tell which way the faces lean.
VOLUME_TOL_MM3 = 1e-3


def _faces_side(faces, point, normal):
    """The side of the plane every face lies on, or 0."""
    if any(not isinstance(face.get("box"), dict) for face in faces):
        return 0
    # A face in the plane counts as on its front side: it leans with the faces beside it.
    sides = {vec.box_side(face["box"], point, normal, SIDE_TOL_MM, flat=1) for face in faces}
    return sides.pop() if len(sides) == 1 else 0


def _angle(ctx, item, data, angle):
    """The angle's size as a Quantity of its magnitude. Two angles from different formulas stay a number, since the
    copy leans every face by one of them, and the sizes behind both are marked."""
    params = data.get("params") or {}
    expressions = [(params.get(path) or {}).get("expression") for path in ("angle_deg", "angle_two_deg")]
    if data.get("two_angles") and expressions[0] != expressions[1]:
        why = "%s leans the two sides of its plane by two values, and the copy follows one angle" % (
            item.get("name") or "A draft")
        for path in ("angle_deg", "angle_two_deg"):
            values.pin(ctx, item, path, why)
        return Quantity(abs(angle))
    size = values.quantity(ctx, item, "angle_deg", abs(angle), dim="angle", sign=1 if angle > 0 else -1,
                           absolute=True)
    if size.sized:
        keep_angle_within(ctx, item, size, MAX_ANGLE_DEG, "lean its faces %g degrees or more" % MAX_ANGLE_DEG)
    return size


def handle(ctx, step):
    item, data = step.brought, step.brought_data
    faces = [face for face in data.get("faces") or [] if isinstance(face, dict)]
    points = picks.face_points(faces)
    if not points or len(points) != len(faces):
        return Refusal("The faces of this draft could not be read.")
    if len(points) > picks.MAX_NEAR_POINTS:
        return Refusal("This draft leans more than %d faces." % picks.MAX_NEAR_POINTS)
    plane = data.get("plane") or {}
    point, normal = plane.get("point"), plane.get("normal")
    if not (isinstance(point, list) and isinstance(normal, list) and vec.length(normal) > 1e-9):
        return Refusal("The plane of this draft could not be read.")
    normal = vec.unit(normal)
    angle, second = data.get("angle_deg"), data.get("angle_two_deg")
    if not isinstance(angle, (int, float)) or angle == 0:
        return Refusal("The angle of this draft could not be read.")
    if data.get("two_angles") and not (isinstance(second, (int, float)) and abs(abs(second) - abs(angle)) < 1e-9):
        return Refusal("This draft gives each side of its plane its own angle, and the copy cannot tell which angle "
                       "leans which side.")
    if abs(angle) >= MAX_ANGLE_DEG:
        return Refusal("Drafts of %g degrees or more are not copied." % MAX_ANGLE_DEG, cause=gap_hints.DRAFT_STEEP)
    side = _faces_side(faces, point, normal)
    # Both halves of a Symmetric draft lean the same way from the plane, so its sign needs no side.
    both = not side and data.get("symmetric") is True and not data.get("two_angles")
    if not side and not both:
        return Refusal("This draft leans faces on both sides of its plane, so the way it leans cannot be checked.")
    before, after = data.get("volume_before"), data.get("volume_after")
    if not isinstance(before, (int, float)) or not isinstance(after, (int, float)):
        return Refusal("The part was not measured around this draft, so the way it leans cannot be checked.")
    if abs(after - before) <= VOLUME_TOL_MM3:
        return Refusal("This draft does not change the part's volume, so the way it leans cannot be checked.")
    lean = (1 if after < before else -1) if both else (side if after < before else -side)
    size = _angle(ctx, item, data, angle)
    shift = follow.place_plane(ctx, item, plane, normal, "leans faces about")
    origin = follow.shifted_origin(round_vec(point), normal, shift)
    step = {"kind": "draft", "faces": follow.faces(ctx, item, faces), "angleDeg": size.scaled(lean).json(),
            "neutral": {"origin": origin, "normal": round_vec(normal)}}
    if both:
        step["angleTwoDeg"] = size.scaled(lean).json()
    out = StepResult()
    out.add(step)
    return out
