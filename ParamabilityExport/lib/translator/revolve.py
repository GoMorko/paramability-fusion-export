"""Revolve feature handler (RevolveFeature). Stub: refuses until its unit lands."""
from .result import Refusal

TYPES = ("RevolveFeature",)


def handle(item, ctx):
    return Refusal("Steps of this kind are not copied yet.")
