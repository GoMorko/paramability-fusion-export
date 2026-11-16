"""A Problem: the design cannot be read or placed for some step, in plain words.

The shared layer gives a Problem where it cannot state a fact. Each destination decides what it does with it (a gap,
a step left out, a stop). `code` tells problems apart for code and tests, `words` is the plain sentence for the person,
and `cause` is the `gap_hints` cause of the gap it leads to, when it has one.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class Problem:
    code: str
    words: str
    cause: object = None


def is_problem(found):
    """True when `found` is a Problem."""
    return isinstance(found, Problem)
