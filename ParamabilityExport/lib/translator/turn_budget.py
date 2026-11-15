"""The turns of the thread and coil steps written so far. The recipe caps them together (`threadTurnsTotal`), so a
handler that writes one reads what the others already used, in the order the walk writes them."""
from . import values
from .step_walk import all_steps

MAX_TURNS_TOTAL = 100


def turns_of(step):
    """The turns of one written step: a coil's `turns`, a thread's length over its pitch, else 0."""
    if step.get("kind") == "coil":
        return float(values.number(step["turns"]))
    if step.get("kind") == "thread":
        return float(values.number(step["length"])) / float(step["pitch"])
    return 0.0


def used(ctx):
    """The turns of every thread and coil written in this walk and the walks around it."""
    total, level = 0.0, ctx
    while level is not None:
        total += sum(turns_of(step) for step in all_steps(level.steps))
        level = level.outer
    return total


def left(ctx):
    """The turns the recipe can still take."""
    return MAX_TURNS_TOTAL - used(ctx)
