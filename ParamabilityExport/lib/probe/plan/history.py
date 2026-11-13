"""What the states tried so far show for one size set alone: which values built and kept every outline."""
from ..state import as_states
from .rows import SAME_VALUE


def _side(size, value):
    """1 or -1: the side of the size's value `value` lies on (0 for the value itself)."""
    delta = value - size["value"]
    return 0 if abs(delta) <= SAME_VALUE else (1 if delta > 0 else -1)


def fails_by(states, size, value):
    """True when a state that set only this size, on the side of `value` and not farther, did not build or changed
    an outline: a row at `value` would end past the range the size keeps."""
    side, reach = _side(size, value), abs(value - size["value"])
    return side != 0 and any(not ok and _side(size, v) == side and abs(v - size["value"]) <= reach + SAME_VALUE
                             for v, ok in tried_alone(states, size["param"], size["value"]))


def farthest_built(states, size, end):
    """The farthest value toward `end` at which a state that set only this size built and kept every outline, nearer
    than any value that did not, or None."""
    side = _side(size, end)
    if side == 0:
        return None
    tried = [(v, ok) for v, ok in tried_alone(states, size["param"], size["value"]) if _side(size, v) == side]
    bad = min((abs(v - size["value"]) for v, ok in tried if not ok), default=None)
    good = [v for v, ok in tried if ok and (bad is None or abs(v - size["value"]) < bad - SAME_VALUE)]
    return max(good, key=lambda v: abs(v - size["value"])) if good else None


def tried_alone(states, name, value):
    """`(value, kept)` of every state that set only `name` to another value than `value`: `kept` when it built and
    no followed outline changed there (`changed`)."""
    out = []
    for state in as_states(states):
        values = state.values
        if list(values) == [name] and abs(values[name] - value) > SAME_VALUE:
            out.append((values[name], state.built and not state.changed))
    return out


def changed_alone(states, name, value):
    """The values of the states that set only `name` and changed a followed outline (`changed`)."""
    return [v for v in (s.values[name] for s in as_states(states) if list(s.values) == [name] and s.changed)
            if abs(v - value) > SAME_VALUE]
