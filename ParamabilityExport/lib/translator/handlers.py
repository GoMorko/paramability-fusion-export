"""The translator handler of each capture type: the function that copies one timeline item into recipe steps,
`handle(item, ctx) -> StepResult | Refusal`. A type with no entry has no recipe step (`capture_model.step_kinds`
gives its reason)."""
from . import extrude
from .bodies import move, paste, split
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
    "MirrorFeature": body_copies.mirror,
    "SplitBodyFeature": split.handle,
    "CopyPasteBody": paste.handle,
    "MoveFeature": move.handle,
    "EmbossFeature": emboss.handle,
    "SweepFeature": sweep.handle,
    "LoftFeature": loft.handle,
}
