"""A problem: the design cannot be read, placed or built the way a reader of the shared layer needs. It is a fact, not
a refusal. Each destination turns a problem into its own answer (a gap of the recipe, a step left out of the Orca
copy)."""
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class Problem:
    """code: a short name of the problem, for a destination that treats one problem in its own way.
    words: one plain sentence that says what is wrong, for the person who reads the result.
    cause: the gap cause of `capture_model.gap_hints` that gives the person a tip, or None."""

    code: str
    words: str
    cause: Optional[str] = None


def is_problem(found):
    return isinstance(found, Problem)
