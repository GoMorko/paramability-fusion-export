"""Patterns and mirrors of bodies whose copies a later Combine takes: which bodies are copies, which body each one
copies, and the rigid move that carries the source to each copy.

A pattern or mirror of bodies makes new bodies (`result_bodies`) and leaves its sources (`source_bodies`) as they
are. Fusion's `PatternElement` does not say which body is which copy, so the copies are matched by their points
(`match`): the move of an element must put every point of a source on the points of one new body. A one-sided
circular pattern places its copies by their ids, turning either way (`pattern_places`), since its element transforms
are not always right; the points of the bodies tell which way.

A Combine takes a pattern whole (`whole`) when its tools hold every copy, each copy is as the pattern made it, and
each source is a tool too, unchanged since the pattern. A source that is the Combine's own target is not checked here:
what such a Combine gives depends on what the destination wrote for the target since the pattern, so each output
decides it. `groups` gives a `Group` or a `Problem` for each body pattern the Combine takes copies of. How the copies
are written stays with the destination. Pure.
"""
from dataclasses import dataclass

from ...capture_model.capture import outside_component, same_body
from ...geometry import vec
from ...geometry.rigid import Move, move_from_frame
from .. import design, roles, tool_chains, words
from ..problem import Problem
from . import pattern_places as places
from .move import FIT_TOL_MM
from .repeat import data_in_component, is_identity, kept_elements, mirror_plane

# Problem codes (`Problem.code`) of a pattern that a Combine does not take whole.
UNMATCHED = "copiesUnmatched"
ELSEWHERE = "copiesElsewhere"
SOURCE_LEFT = "sourceNotTaken"
SOURCE_CHANGED = "sourceChanged"
SOME_COPIES = "someCopies"
COPY_CHANGED = "copyChanged"


@dataclass(frozen=True)
class Copy:
    """One body a pattern made: `result`, the `source` it copies and the `move` (`geometry.rigid.Move`) that carries
    the source to it."""

    result: dict
    source: dict
    move: Move


@dataclass(frozen=True)
class Group:
    """A pattern or mirror item a Combine takes whole: its `sources` and its `copies` (`Copy`)."""

    item: dict
    sources: list
    copies: list

    def holds(self, body):
        return any(same_body(body, other) for other in self.sources + [c.result for c in self.copies])


def of_bodies(data):
    return data.get("entity_type") == "bodies"


def is_mirror(data):
    return "plane" in data


def carries(move, point):
    """Where the rigid `move` puts `point`."""
    return [sum(move.rows[i][k] * point[k] for k in range(3)) + move.offset[i] for i in range(3)]


def mirror_move(origin, normal):
    """The reflection across the plane through `origin` with the normal `normal`."""
    n = vec.unit(normal)
    rows = [[(1.0 if i == j else 0.0) - 2.0 * n[i] * n[j] for j in range(3)] for i in range(3)]
    return Move(rows, vec.scale(n, 2.0 * vec.dot(origin, n)))


def element_moves(data):
    """The choices for the move of each copy a pattern or mirror keeps, the original left out: a list of lists,
    empty when they were not read."""
    if is_mirror(data):
        plane = mirror_plane(data)
        return [] if plane is None else [[mirror_move(plane["origin"], plane["normal"])]]
    kept = kept_elements(data)
    if kept is None:
        return []
    if "axis" in data and (not data.get("symmetric") or places.full_turn(data)):
        choices = [places.id_frames(data, kept, sign) for sign in (1, -1)]
        return [[move_from_frame(frame) for _, frame in found] for found in choices if found is not None]
    return [[move_from_frame(e["frame"]) for e in kept if not is_identity(e["frame"])]]


def lands_on(move, source, result):
    """True when `move` puts every point of `source` on a point of `result`, in any order."""
    before, after = source.get("points") or [], result.get("points") or []
    return bool(before) and len(before) == len(after) and all(
        any(vec.close(carries(move, p), q, FIT_TOL_MM) for q in after) for p in before)


def match(data):
    """A `Copy` for each body the pattern `data` made, or None when the bodies and the copies do not pair up."""
    sources, results = data.get("source_bodies"), data.get("result_bodies")
    if not sources or not isinstance(results, list):
        return None
    for moves in element_moves(data):
        found = _paired(sources, results, moves)
        if found is not None:
            return found
    return None


def _paired(sources, results, moves):
    """A `Copy` for each body in `results` that one of `moves` makes from a source, or None when they do not pair up
    one to one. Two copies on one place, or a place no body sits on, leave a body or a copy without a pair."""
    left = [r for r in results if not any(same_body(r, s) for s in sources)]
    copies = []
    for source in sources:
        for move in moves:
            found = next((r for r in left if lands_on(move, source, r)), None)
            if found is None:
                return None
            left = [r for r in left if r is not found]
            copies.append(Copy(found, source, move))
    return None if left else copies


# ---------------------------------------------------------------- a whole pattern in a Combine


def _listed(body, tools):
    return any(same_body(body, tool) for tool in tools)


def _made_copy(timeline, tool, before, component):
    """The pattern or mirror of bodies whose `result_bodies` list `tool` as a copy, among the items that made it before
    `before`, else None. Fusion may list a pattern's source among its bodies too; a source is no copy of that pattern,
    so a Combine that takes only the source takes it as a plain tool."""
    for item in tool_chains.made_by(timeline, tool, before, component):
        data = design.as_read(item).brought_data
        if (of_bodies(data) and roles.copies_bodies(item) and _listed(tool, data.get("result_bodies") or [])
                and not _listed(tool, data.get("source_bodies") or [])):
            return item
    return None


def pattern_that_made(timeline, tool, before, component=None):
    """The pattern item that made the copy `tool`, when nothing changed the copy since; else None. `component` is the
    token of the component the walk is in, None for the exported body's."""
    chain = tool_chains.made_by(timeline, tool, before, component)
    if len(chain) != 1:
        return None
    data = design.as_read(chain[0]).brought_data
    if not of_bodies(data) or not roles.copies_bodies(chain[0]):
        return None
    if tool_chains.unseen_change(timeline, tool, before, component) is not None:
        return None
    results = data.get("result_bodies") or []
    return chain[0] if _listed(tool, results) else None


def stays_as_copied(timeline, body, pattern, before, component=None):
    """True when no item after the `pattern` and before timeline index `before` changed `body`."""
    chain = tool_chains.made_by(timeline, body, before, component)
    return all(item["index"] <= pattern["index"] for item in chain)


def whole(timeline, combine_item, pattern, tools, component=None, is_target=None, place=None):
    """The `Group` of the `pattern` when the Combine `combine_item` takes it whole with its `tools`, else a
    `Problem`. `is_target(body)` tells a source that is the Combine's target, which need not be a tool (the caller
    decides about it). `place` is the frame of the component the copies are written in (component to assembly), which
    the element frames are carried into, or None to read them as they are."""
    read = design.as_read(pattern)
    data = read.brought_data
    name = pattern.get("name") or "a pattern"
    if outside_component(pattern) or read.foreign:
        return Problem(ELSEWHERE, words.BODY_COPIES_ELSEWHERE % name)
    copies = match(data_in_component(data, place) if place is not None else data)
    if copies is None:
        return Problem(UNMATCHED, words.BODY_COPIES_UNMATCHED % name)
    before = combine_item["index"]
    for source in data["source_bodies"]:
        if is_target is not None and is_target(source):
            continue
        if not _listed(source, tools):
            return Problem(SOURCE_LEFT, words.BODY_COPIES_SOURCE_LEFT % name)
        if not stays_as_copied(timeline, source, pattern, before, component):
            return Problem(SOURCE_CHANGED, words.BODY_COPIES_SOURCE_CHANGED % name)
    if not all(_listed(c.result, tools) for c in copies):
        return Problem(SOME_COPIES, words.BODY_COPIES_SOME % name)
    if not all(pattern_that_made(timeline, c.result, before, component) for c in copies):
        return Problem(COPY_CHANGED, words.BODY_COPIES_CHANGED % name)
    return Group(pattern, list(data["source_bodies"]), copies)


def groups(timeline, combine_item, tools, component=None, is_target=None, place=None):
    """`(pattern item, Group or Problem)` for each pattern or mirror of bodies that made one of `tools`, in the order
    the tools first name them (`whole`). A copy that a later step changed still names its pattern, which is then a
    Problem."""
    patterns = {}
    for tool in tools:
        found = _made_copy(timeline, tool, combine_item["index"], component)
        if found is not None:
            patterns.setdefault(found["index"], found)
    return [(pattern, whole(timeline, combine_item, pattern, tools, component, is_target, place))
            for pattern in patterns.values()]


def overlaps(group, others, tools):
    """True when one of `tools` belongs to `group` and to one of the `others`."""
    return any(group.holds(tool) and other.holds(tool) for other in others for tool in tools)
