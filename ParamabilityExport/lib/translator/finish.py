"""Fillet, chamfer and shell handler. Stub: refuses until its unit lands."""
from .result import Refusal

TYPES = ("FilletFeature", "ChamferFeature", "ShellFeature")


def handle(item, ctx):
    return Refusal("Steps of this kind are not copied yet.")
