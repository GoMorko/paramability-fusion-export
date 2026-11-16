"""A design that cannot be read or placed: the fact a shared reader gives instead of a record.

A reader of the shared layer returns its record, or a `Problem`. The layer does not refuse a step. Each output turns a
`Problem` into its own answer: the recipe translator into a refusal, the Orca output into a left out step. `words` is
one plain sentence, `cause` the `capture_model.gap_hints` cause that gives the person a tip, or None. `code` names the
problem for a caller that must tell two of them apart.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class Problem:
    code: str
    words: str
    cause: str = None
