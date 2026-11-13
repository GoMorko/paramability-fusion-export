"""Measured references (a plane, axis, direction or point of another component that a step uses) over the probe
states. Pure.

The reader gives each state's place of a reference in the part's coordinates (`refs` of a probe state, see
`fusion_reader.probe_refs`). Here the move of that place from where the capture has it is fitted like a sketch value:
as an exact formula of the sizes (`series.fit_series`), or not at all.

- a plane moves along its captured normal: one value, `offset`;
- an axis moves across its direction, a point anywhere: three values, `point/0` to `point/2`;
- a direction cannot move: one that turns is stuck on the key `dir`.

A reference that turns (its normal or direction changes, or flips), cannot be read at a state, or did not read back as
the capture has it at the start gets no formula, never a guess: a turn or an unread state is a `Stuck` with the
sizes behind it, a start that does not match is kept in `Measured.notes` with its reason, and the reference is not
read again.
"""
import math

from . import plan
from .series import fit_series
from ..geometry import vec
from ..sketch_values import keys
from ..sketch_values.motion import TURNS, UNREAD

POINT_TOLERANCE = 1e-4
TURN_TOLERANCE = 1e-6
NOT_MATCHED = "its first read did not match the capture"
NOT_READ = "it could not be read at the current sizes"
NOT_LOOKED_AT = "the design could not be read at its current sizes"


def _turned(now, was):
    """True when the unit vector `now` is not the unit vector `was` (a change, or the opposite way)."""
    cross = vec.cross(now, was)
    return math.sqrt(vec.dot(cross, cross)) > TURN_TOLERANCE or vec.dot(now, was) < 0


def key_names(ref):
    """The motion keys of a reference, in order."""
    item, slot, shape = ref["item"], ref["slot"], ref["shape"]
    if shape == plan.SHAPE_PLANE:
        return [keys.reference_offset(item, slot)]
    if shape == plan.SHAPE_DIRECTION:
        return [keys.reference_dir(item, slot)]
    return [keys.reference_point(item, slot, c) for c in range(3)]


def captured_values(ref):
    """The values of a reference at the place the capture has it: zero moves, by key."""
    return {key: 0.0 for key in key_names(ref)}


def state_values(ref, read):
    """`(values, cause)` of a reference in a state read: its move from the captured place by key, or None with the
    cause (`TURNS`, `UNREAD`)."""
    got = ((read or {}).get("refs") or {}).get(ref["key"])
    if not isinstance(got, dict):
        return None, UNREAD
    want, shape = ref["ref"], ref["shape"]
    point, normal, direction = got.get("point"), got.get("normal"), got.get("dir")
    if shape in (plan.SHAPE_PLANE, plan.SHAPE_AXIS, plan.SHAPE_POINT) and not plan.is_vector(point):
        return None, UNREAD
    names = key_names(ref)
    if shape == plan.SHAPE_PLANE:
        if not plan.is_vector(normal):
            return None, UNREAD
        if _turned(normal, want["normal"]):
            return None, TURNS
        return {names[0]: vec.dot(vec.sub(point, want["point"]), want["normal"])}, None
    if shape in (plan.SHAPE_AXIS, plan.SHAPE_DIRECTION):
        if not plan.is_vector(direction):
            return None, UNREAD
        if _turned(direction, want["dir"]):
            return None, TURNS
        if shape == plan.SHAPE_DIRECTION:
            return {names[0]: 0.0}, None
        move = vec.sub(point, want["point"])
        along = vec.dot(move, want["dir"])
        move = [m - along * d for m, d in zip(move, want["dir"])]
    else:
        move = vec.sub(point, want["point"])
    return dict(zip(names, move)), None


class Measured:
    """`usable`: the references to fit (their first read matched the capture). `notes`: reference key to "" for a
    usable reference, else why it is not measured."""

    def __init__(self):
        self.usable = []
        self.notes = {}


def check_start(ref, read):
    """"" when the first read gives the reference back as the capture has it (within 1e-4 mm), else why not."""
    if not isinstance(read, dict):
        return NOT_LOOKED_AT
    values, cause = state_values(ref, read)
    if values is None:
        reason = ((read.get("unread") or {}).get(ref["key"]))
        return reason if cause == UNREAD and isinstance(reason, str) and reason else (
            NOT_READ if cause == UNREAD else NOT_MATCHED)
    return "" if all(abs(v) <= POINT_TOLERANCE for v in values.values()) else NOT_MATCHED


def measurable(refs, first):
    """The `Measured` of the references `refs` (`plan.refs`) given the first read `first` (None when there is none)."""
    out = Measured()
    for ref in refs:
        reason = ref["reason"] or (check_start(ref, first) if ref["shape"] else "")
        out.notes[ref["key"]] = reason
        if not reason:
            out.usable.append(ref)
    return out


def moved_in(ref, read):
    """True when the reference reads differently in `read` than in the capture: it moved, turned or cannot be read."""
    values, _ = state_values(ref, read)
    return values is None or any(abs(v) > POINT_TOLERANCE for v in values.values())


def fit_ref(out, ref, reads, built, shared, models, varied):
    """Fit the move of one usable reference over the states and write it into `out` (a `Motion`).

    `reads` and `built` are per state, index 0 the first read (`built[at]` is false for a state Fusion could not
    build: it is left out); `shared` and `models` are the parameter columns (`columns.user_columns`, `model_columns`);
    `varied(at)` gives the Fusion names state `at` changes."""
    series = {key: [value] for key, value in captured_values(ref).items()}
    problems = []
    for at in range(1, len(reads)):
        if not built[at]:
            values, cause = None, None
        else:
            values, cause = state_values(ref, reads[at])
        for key in series:
            series[key].append(None if values is None else values[key])
        if values is None and cause:
            problems.append((cause, varied(at)))
    token = ref["ref"].get("token") or ""
    candidates = shared + [m.ranked("", token) for m in models]
    fit_series(out.values, series, problems, candidates, varied)
