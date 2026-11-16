"""The translator handler of each capture type: the function that copies one timeline item into recipe steps,
`handle(ctx, step) -> StepResult | Refusal`, where `step` is the item's `design_model.design.ResolvedStep`. A type with no entry has no recipe step (`capture_model.step_kinds`
gives its reason)."""
from . import extrude
from .bodies import move, paste, scale, split
from .coil import step as coil
from .combine import step as combine
from .extrude import emboss
from .finishes import draft, finish, offset
from .hole import step as hole
from .loft import step as loft
from .repeat import body_copies
from .revolve import step as revolve
from .sweep import step as sweep

HANDLERS = {
    "ExtrudeFeature": extrude.handle,
    "RevolveFeature": revolve.handle,
    "HoleFeature": hole.hole,
    "ThreadFeature": hole.thread,
    "CombineFeature": combine.handle,
    "FilletFeature": finish.fillet,
    "ChamferFeature": finish.chamfer,
    "ShellFeature": finish.shell,
    "DraftFeature": draft.handle,
    "OffsetFacesFeature": offset.handle,
    "RectangularPatternFeature": body_copies.rectangular,
    "CircularPatternFeature": body_copies.circular,
    "PathPatternFeature": body_copies.path,
    "MirrorFeature": body_copies.mirror,
    "SplitBodyFeature": split.handle,
    "CopyPasteBody": paste.handle,
    "MoveFeature": move.handle,
    "ScaleFeature": scale.handle,
    "EmbossFeature": emboss.handle,
    "CoilFeature": coil.handle,
    "SweepFeature": sweep.handle,
    "LoftFeature": loft.handle,
}
