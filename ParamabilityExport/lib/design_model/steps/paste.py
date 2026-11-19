"""A Copy Paste Body step, from its data: the body it made that a walk builds, the body it copied for it, and where
that copy sits against its source.

The reader gives the bodies the paste copied (`sources`) and the bodies it made (`result_bodies`), each with its first
vertices (`fusion_reader/read_paste.py`). The steps of a pasted body are those of its source up to the paste. A
result pairs with one source: the only one, else the one at its place, else the one of its shape (one rigid move
apart). A result with no single source, or lists of a different length, have no pair. The place is the rigid move from
the source's vertices to the result's, the identity for a paste in place. These are facts only: each destination
decides what to write from them. Pure.
"""
from dataclasses import dataclass

from ...geometry.rigid import IDENTITY_ROWS, Move
from .. import words
from ..problem import Problem, is_problem
from .move import carries, fit

# The codes of the problems of a paste.
SOURCE_UNREAD = "pasteSourceUnread"
RESULT_UNREAD = "pasteResultUnread"
NOT_PAIRED = "pasteNotPaired"
CORNERS_UNREAD = "pasteCornersUnread"
NO_MATCH = "pasteNoMatch"


@dataclass(frozen=True)
class Pasted:
    """The source of one pasted body: `source`, its body record with points, and `move`, the
    `geometry.rigid.Move` that carries the source onto the pasted body (the identity for a paste in place)."""

    source: dict
    move: Move


def result_of(data, is_body):
    """The record of the pasted body for which `is_body(record)` is true, or a Problem when the paste's sources or
    results cannot be read."""
    if not data.get("sources"):
        return Problem(SOURCE_UNREAD, words.PASTE_SOURCE_UNREAD)
    results = data.get("result_bodies")
    found = next((r for r in results if isinstance(r, dict) and is_body(r)), None) \
        if isinstance(results, list) else None
    return found if found is not None else Problem(RESULT_UNREAD, words.PASTE_RESULT_UNREAD)


def pair(data, result):
    """The `Pasted` of the pasted body `result` (a record of `data["result_bodies"]`), or a Problem."""
    source = source_of(result, data.get("sources") or [], data.get("result_bodies") or [])
    if source is None:
        return Problem(NOT_PAIRED, words.PASTE_NOT_PAIRED)
    move = place_of(source, result)
    return move if is_problem(move) else Pasted(source, move)


def place_of(source, result):
    """The rigid `Move` from the body `source` to the body `result`, by their first vertices, or a Problem."""
    before, after = source.get("points") or [], result.get("points") or []
    if not before or len(before) != len(after):
        return Problem(CORNERS_UNREAD, words.PASTE_CORNERS_UNREAD)
    if carries(Move(IDENTITY_ROWS), before, after):
        return Move(IDENTITY_ROWS)
    found = fit(before, after)
    return found if found is not None else Problem(NO_MATCH, words.PASTE_NO_MATCH)


def source_of(result, sources, results):
    """The source of the pasted body `result`, or None when sources and results do not pair up one to one. A source at
    the same place wins over one that only has the same shape."""
    if len(sources) != len(results):
        return None
    if len(sources) == 1:
        return sources[0]
    paired = [(r, _candidates(r, sources)) for r in results]
    if any(len(found) != 1 for _, found in paired) or len({id(found[0]) for _, found in paired}) != len(paired):
        return None
    return next(found[0] for r, found in paired if r is result)


def _candidates(result, sources):
    """The sources `result` can be a copy of: those at its place, else those of its shape."""
    places = [(source, place_of(source, result)) for source in sources]
    fitting = [(source, place) for source, place in places if not is_problem(place)]
    return [source for source, place in fitting if place.is_identity] or [source for source, _ in fitting]
