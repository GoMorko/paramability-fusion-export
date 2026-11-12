"""Loft feature handler (LoftFeature): a solid through two closed sketch outlines with free ends.

Fusion joins two outlines with free ends by straight faces, so the copy is a recipe `loft` with `ruled` set. Each
outline is written like an extrude outline (outline loops, the plane position that follows sizes). Openings are paired
between the two outlines by the nearest centre and share a key, so the kernel lofts each through both sections.

Refused, with the step left out as a gap: more than two outlines, a section that is a point, a face or not a closed
outline, end conditions other than free, rails, a centre line, a closed loft, outlines with different numbers of
openings, and outlines whose planes cross or touch (the kernel needs the sections in order along the loft).

Two parallel outlines of straight lines make a ruled loft whose volume follows from the way the kernel pairs the
corners (`loft_volume`). A new body that has another volume is refused, since Fusion paired the corners another way.
Where the volume cannot be told, outlines of the same corners that are turned against each other get a note.
"""
from . import borrowed, loft_volume, loops, placement, sketch_motion, vec
from .extrude import COMBINE
from .footprint import polyline
from .placer_makers import EndCapsMaker
from .result import Refusal, StepResult
from .sweep_volume import made_volume
from .values import Quantity

PLANE_TOL = 1e-6

UNREADABLE = "A setting of this loft could not be read from Fusion."
KIND_REASONS = {
    "point": "Lofts that start or end in a point are not copied yet.",
    "face": "A loft section that is a face of the part is not copied yet.",
}
NOT_AN_OUTLINE = "A loft section is not a closed sketch outline."
CORNERS_PAIRED = ("Fusion joins the corners of the two outlines of this loft another way than the copy does, so it is "
                  "not copied yet.")


def _settings_refusal(data):
    """A Refusal for a loft setting the copy does not follow, else None."""
    operation = data.get("operation")
    if operation == "newComponent":
        return Refusal("Lofts that make a new component are not copied.")
    if operation not in COMBINE:
        return Refusal("This loft combines with the part in a way that is not copied yet.")
    if data.get("solid") is False:
        return Refusal("Surface lofts are not copied.")
    flags = (data.get("solid"), data.get("closed"), data.get("rails"), data.get("sections"), data.get("profiles"))
    if any(flag is None for flag in flags):
        return Refusal(UNREADABLE)
    if data["closed"]:
        return Refusal("Closed lofts are not copied yet.")
    if data.get("centerline"):
        return Refusal("Lofts along a centre line are not copied yet.")
    if data["rails"]:
        return Refusal("Lofts with rails are not copied yet.")
    return None


def _sections_refusal(sections):
    """A Refusal for a section that is not a sketch outline with a free end, or a loft of other than two, else None."""
    for section in sections:
        if not isinstance(section, dict):
            return Refusal(UNREADABLE)
        kind = section.get("kind")
        if kind in KIND_REASONS:
            return Refusal(KIND_REASONS[kind])
        if kind != "profile":
            return Refusal(NOT_AN_OUTLINE)
    for section in sections:
        if section.get("end") is None:
            return Refusal(UNREADABLE)
        if section["end"] != "free":
            return Refusal("This loft shapes its ends (tangent or direction), which is not copied yet.")
    if len(sections) > 2:
        return Refusal("Lofts through more than two outlines are not copied yet.")
    if len(sections) < 2:
        return Refusal("This loft has fewer than two outlines.")
    return None


def _outer_points(profile):
    """Points along the outer loop of a profile, in model space."""
    return [vec.frame_apply(profile["frame"], [p[0], p[1], 0.0]) for loop in profile["loops"] if loop.get("outer")
            for curve in loop["curves"] for p in polyline(curve)]


def _side(profile, points):
    """1 or -1 when all `points` lie on one side of the profile's plane, else 0 (they cross or touch it)."""
    frame = profile["frame"]
    z = vec.unit(frame["z"])
    heights = [vec.dot(vec.sub(p, frame["origin"]), z) for p in points]
    if all(h > PLANE_TOL for h in heights):
        return 1
    if all(h < -PLANE_TOL for h in heights):
        return -1
    return 0


def _out_of_order(first, second):
    """True when one outline reaches the plane of the other, as the kernel refuses."""
    return not (_side(first, _outer_points(second)) and _side(second, _outer_points(first)))


def _centre(loop):
    """A point inside a recipe loop that stands for it: its centre, or the average of its corner points."""
    kind = loop["kind"]
    if kind in ("circle", "ellipse", "rect"):
        return loop["center"]
    if kind == "polygon":
        points = loop["points"]
    else:
        points = [loop["start"]]
        for segment in loop["segments"]:
            points += list(segment.get("through") or []) if segment["kind"] == "spline" else []
            points.append(segment["to"])
    return [sum(p[i] for p in points) / len(points) for i in range(2)]


def _centre_on(frame, loop, plane):
    """The centre of a hole in model space, dropped onto `plane` (a frame) along its normal."""
    u, v = _centre(loop)
    point = vec.frame_apply(frame, [u, v, 0.0])
    z = vec.unit(plane["z"])
    return vec.sub(point, vec.scale(z, vec.dot(vec.sub(point, plane["origin"]), z)))


def _pairing(first, second):
    """For each hole of the first outline, the index of the hole of the second outline nearest to it (closest pairs
    first, each hole used once). Each argument is (frame, hole loops)."""
    centres = [[_centre_on(f, loop, first[0]) for loop in holes] for f, holes in (first, second)]
    pairs = sorted((vec.length(vec.sub(a, b)), i, j) for i, a in enumerate(centres[0]) for j, b in enumerate(centres[1]))
    taken, used, match = set(), set(), {}
    for _, i, j in pairs:
        if i not in taken and j not in used:
            taken.add(i)
            used.add(j)
            match[i] = j
    return [match[i] for i in range(len(centres[0]))]


def _shape_of(loop):
    """What the corners of a loop look like: smooth, or this many corners. Loops with equal marks join cleanly."""
    kind = loop["kind"]
    if kind in ("circle", "ellipse"):
        return ("round", 0)
    if kind == "rect":
        return ("corners", 4)
    if kind == "polygon":
        return ("corners", len(loop["points"]))
    return ("profile", len(loop["segments"]))


def _pairing_check(item, data, profiles):
    """A Refusal when a new body does not have the volume of the loft the copy builds from the outlines; True when it
    does; False when that cannot be told (not a new body, no measured volume, outlines of other kinds)."""
    if data["operation"] != "newBody":
        return False
    made = made_volume(item, data)
    volumes = loft_volume.ruled_volumes(profiles)
    if made is None or volumes is None:
        return False
    return True if loft_volume.matches(volumes, made) else Refusal(CORNERS_PAIRED)


def _turned_corners(profiles, built):
    """True when both outlines are corner outlines (squares, polygons) of the same count whose sketch frames are
    turned against each other."""
    kinds = [_shape_of(outer) for outer, _ in built]
    if kinds[0] != kinds[1] or kinds[0][0] != "corners":
        return False
    first, second = (vec.unit(p["frame"]["x"]) for p in profiles)
    return vec.length(vec.sub(first, second)) > 1e-6


def handle(item, ctx):
    data = item.get("data") or {}
    refusal = _settings_refusal(data)
    if refusal is None:
        refusal = _sections_refusal(data["sections"])
    if refusal is not None:
        return refusal
    profiles = data["profiles"]
    if len(profiles) != 2 or any(not isinstance(p, dict) for p in profiles):
        return Refusal(UNREADABLE)
    for profile in profiles:
        refusal = loops.outline_refusal(profile)
        if refusal is not None:
            return refusal
        if not isinstance(profile.get("frame"), dict):
            return Refusal("A sketch outline has no readable position.")
    built = []
    for profile in profiles:
        outcome = loops.profile_loops(profile)
        if isinstance(outcome, Refusal):
            return outcome
        built.append(outcome)
    if len(built[0][1]) != len(built[1][1]):
        return Refusal("The outlines of this loft have different numbers of openings.")
    if _out_of_order(*profiles):
        return Refusal("The outlines of this loft cross each other.")

    checked = _pairing_check(item, data, profiles)
    if isinstance(checked, Refusal):
        return checked

    keys = [[None] * len(inners) for _, inners in built]
    keys[0] = ["h%d" % n for n in range(len(built[0][1]))]
    for first_hole, second_hole in enumerate(_pairing(*[(p["frame"], b[1]) for p, b in zip(profiles, built)])):
        keys[1][second_hole] = keys[0][first_hole]

    sections = []
    for number, (profile, (outer, inners)) in enumerate(zip(profiles, built)):
        borrowed.mark_unchecked(ctx, item, profile)
        drawn = sketch_motion.outline(ctx, item, profile, outer, inners, [(number, profile)])
        if drawn is not None:
            outer, inners = drawn.written(ctx)
        on = placement.from_frame(profile["frame"])
        on["origin"] = drawn.origin(ctx, Quantity(0.0)) if drawn is not None else on["origin"]
        section = {"on": on, "outer": outer}
        if inners:
            section["holes"] = [{"key": key, "loop": loop} for key, loop in zip(keys[number], inners)]
        sections.append(section)
    if _shape_of(built[0][0]) != _shape_of(built[1][0]):
        ctx.note("The two outlines of %s have different shapes. The copy joins them with straight faces, which can "
                 "differ from Fusion between the outlines." % item.get("name", "this loft"))
    elif not checked and _turned_corners(profiles, built):
        ctx.note("The two outlines of %s are turned against each other. Fusion and the copy may join their corners in "
                 "different ways, so check the shape." % item.get("name", "this loft"))
    if data.get("merge_tangent") is False:
        ctx.note("Merge tangent edges is off in %s. This only changes how Fusion splits the faces, so the copy has the "
                 "same shape." % item.get("name", "this loft"))
    out = StepResult()
    # A section with openings leaves no end faces to name.
    faces = None if any(inners for _, inners in built) else {
        "start": (profiles[0]["frame"], profiles[0]), "end": (profiles[1]["frame"], profiles[1])}
    out.add({"kind": "loft", "sections": sections, "ruled": True, "combine": COMBINE[data["operation"]]},
            [EndCapsMaker(faces)] if faces else [])
    return out
