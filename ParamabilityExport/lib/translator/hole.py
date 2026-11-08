"""Hole and thread handler (HoleFeature, ThreadFeature). Stub: refuses until its unit lands."""
from .result import Refusal

TYPES = ("HoleFeature", "ThreadFeature")


def handle(item, ctx):
    return Refusal("Steps of this kind are not copied yet.")
