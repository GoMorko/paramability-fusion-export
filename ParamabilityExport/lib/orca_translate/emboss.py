"""Emboss steps on a flat face as Orca features: the extrude the emboss stands for (`design_model.steps.emboss`), its
outlines extruded from the face by the depth, joined when raised and cut when sunk. The extrude handler (`steps`)
writes it, so sketch text goes to Orca's imported regions (`text_regions`) and other outlines are drawn as for any
extrude. Only the depth follows variables.

Left out: an emboss on a curved face or on faces of more than one plane, an outline moved or turned on its face, a
sketch plane tilted to the face, a measured change that does not match the outline and depth, an outline that Fusion
trims to its face (Orca has no step that keeps an extrude within a face), and an outline that may follow tangent faces.
"""
from ..capture_model import gap_hints
from ..design_model import design
from ..design_model.steps import emboss as shared
from ..design_model.loops import outline_problem
from . import causes
from .skip import Skip
from .steps import extrude

_TRIMMED = ("This emboss reaches past the face it sits on, and Fusion trims it there, which is not copied to Orca "
            "yet.")
_FACE_CAUSES = {shared.CURVED.code: causes.EMBOSS_FACE, shared.PLANES.code: causes.EMBOSS_FACE,
                shared.TANGENT.code: causes.EMBOSS_FACE}


def _skip(problem):
    return Skip(problem.words, _FACE_CAUSES.get(problem.code, problem.cause or gap_hints.REFUSED))


def emboss(ctx, step):
    """The Orca features of an emboss (`step`, a `design.ResolvedStep`), or a Skip."""
    item, data = step.brought, step.brought_data
    faces = shared.flat_faces(data.get("faces"))
    if not isinstance(faces, list):
        return _skip(faces)
    problem = shared.settings_problem(data)
    if problem is not None:
        return _skip(problem)
    depth, profiles = data["depth"], data["profiles"]
    for profile in profiles:
        found = None if profile.get("face") else outline_problem(profile)
        if found is not None:
            return Skip.of(found)
    face = faces[0]
    if shared.tilted(profiles, face["outward"]):
        return _skip(shared.TILTED)
    problem, trimmed = shared.volume_check(data, depth)
    if problem is not None:
        return _skip(problem)
    if trimmed:
        return Skip(_TRIMMED, causes.EMBOSS_TRIMMED)
    problem = shared.tangent_problem(data, face)
    if problem is not None:
        return _skip(problem)
    for path in shared.PLACE_SETTINGS:
        ctx.doubt(ctx.quantity(item, path, 0.0, "angle" if path == "rotation_deg" else "length").reads,
                  "%s: it moves the outline on its face, and the Orca copy keeps the outline where it is now"
                  % (item.get("name") or "the emboss"))
    return extrude(ctx, design.as_read(dict(item, data=shared.as_extrude(data, face, depth))))


HANDLERS = {"EmbossFeature": emboss}
