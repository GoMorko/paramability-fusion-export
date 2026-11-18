"""Emboss feature handler (EmbossFeature) for an outline on a flat face.

An emboss of sketch outlines on a flat face is an extrude of those outlines that starts on the face: it joins the
part when the depth is positive (raised) and cuts it when the depth is negative (sunk). A flat face used as an outline
goes the way of an extrude from a face (sketch/face_outline.py). The handler checks what the
copy relies on, rewrites the item as such an extrude and passes it to `extrude.handle`, so outline merging, size
formulas, slabs and picks work as for any extrude. Fusion keeps one signed depth and no emboss or deboss flag.

Sketch text arrives as ordinary outline profiles (`text_outlines.py`) whose areas come from the outlines themselves,
so the volume check below also confirms that the text outlines have the area the feature used.

An outline that runs past its face (over a hole of it or off its edge) is trimmed to the face by Fusion: the end
face then holds the whole change, which is the end face area times the depth. The step is then written with `within`,
the outline of the face with its holes, so the extrude acts only on the face. The face is drawn like the outline of an
extrude from a face (sketch/face_outline.py).

Refused, with the part then saved as a fixed shape: curved input faces, an outline moved or turned on its face (the
frame of those settings is not documented), a text whose outlines could not be read, a sketch plane tilted to the
face, a result whose measured volume does not match the outline area times the depth (or, for a trimmed outline,
the end face area times the depth), and a trimmed outline whose face cannot be copied (several input faces, edges not
read, flat faces following it by Tangent Chain).
"""
import copy

from ...design_model import design
from ...design_model.steps import emboss as shared
from ...design_model.values import Quantity
from .. import extrude, placement, values
from ..result import Refusal, StepResult
from ..sketch import face_outline, loops


def _refusal(problem):
    return None if problem is None else Refusal(problem.words)


def _limit(ctx, item, data, face):
    """The `FaceOutline` of the face a trimmed emboss sits on, or a Refusal when that face cannot be the limit."""
    reason = "This emboss reaches past the face it sits on, and Fusion trims it there; %s, so it is not copied."
    if len(data.get("faces") or []) > 1:
        return Refusal(reason % "it lands on several faces")
    neighbours = data.get("tangent_faces")
    if data.get("tangent_chain") is not False and isinstance(neighbours, list) and neighbours:
        return Refusal(reason % "it also follows the faces next to its face (Tangent Chain)")
    outline = face.get("outline")
    if not isinstance(outline, dict):
        return Refusal(reason % "the edges of the face could not be read")
    found = face_outline.prepare(ctx, item, [outline])
    if isinstance(found, Refusal):
        return Refusal(reason % "the edges of the face cannot be written")
    return found


def _within(ctx, limit):
    """The limit as a recipe sketch: the face's outline with its holes, on the face's plane."""
    on = placement.from_frame(limit.profile["frame"])
    if limit.drawn is not None:
        on["origin"] = limit.drawn.origin(ctx, Quantity(0.0))
        outer, inner = limit.drawn.written(ctx)
    else:
        outer, inner = copy.deepcopy(limit.loops[0]), copy.deepcopy(limit.loops[1])
    sketch = {"on": on, "outer": outer}
    if inner:
        sketch["inner"] = inner
    return sketch


def handle(ctx, step):
    item, data = step.brought, step.brought_data
    faces = shared.flat_faces(data.get("faces"))
    if not isinstance(faces, list):
        return _refusal(faces)
    refusal = _refusal(shared.settings_problem(data))
    if refusal is not None:
        return refusal
    depth = data["depth"]
    profiles = data["profiles"]
    for profile in profiles:
        refusal = None if profile.get("face") else loops.outline_refusal(profile)
        if refusal is not None:
            return refusal
    face = faces[0]
    if shared.tilted(profiles, face["outward"]):
        return _refusal(shared.TILTED)
    problem, trimmed = shared.volume_check(data, depth)
    if problem is not None:
        return _refusal(problem)
    limit = _limit(ctx, item, data, face) if trimmed else None
    if isinstance(limit, Refusal):
        return limit
    refusal = _refusal(shared.tangent_problem(data, face))
    if refusal is not None:
        return refusal
    for path in shared.PLACE_SETTINGS:
        values.pin(ctx, item, path, "it sets how far %s moves its outline" % item.get("name", "an emboss"))
    built = shared.as_extrude(data, face, depth)
    outcome = extrude.handle(ctx, design.as_read(dict(item, data=built)))
    values.handled(ctx, item, "depth", same_as="side_one.distance")
    if limit is not None and isinstance(outcome, StepResult):
        for entry in outcome.entries:
            entry.step["within"] = _within(ctx, limit)
    return outcome
