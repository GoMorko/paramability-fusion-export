"""Extrude feature handler (ExtrudeFeature). Stub: refuses until its unit lands."""
from .result import Refusal

TYPES = ("ExtrudeFeature",)


def handle(item, ctx):
    return Refusal("Steps of this kind are not copied yet.")
