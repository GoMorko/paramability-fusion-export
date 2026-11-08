"""Combine feature handler (CombineFeature); places pending tool body steps. Stub: refuses until its unit lands."""
from .result import Refusal

TYPES = ("CombineFeature",)


def handle(item, ctx):
    return Refusal("Steps of this kind are not copied yet.")
