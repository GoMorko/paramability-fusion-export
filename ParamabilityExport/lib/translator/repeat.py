"""Pattern and mirror handler. Stub: refuses until its unit lands."""
from .result import Refusal

TYPES = ("RectangularPatternFeature", "CircularPatternFeature", "MirrorFeature")


def handle(item, ctx):
    return Refusal("Steps of this kind are not copied yet.")
