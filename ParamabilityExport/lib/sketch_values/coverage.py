"""Which sketches the probe measured. Pure.

For one sketch and one size the motion file gives one of three answers:

- `STILL`: the sketch was measured and the size did not move it (its values have no key in the motion file);
- `MOVED`: it was measured and the size moved it (the keys with their `Affine` or `Stuck` say how);
- `NOT_MEASURED`: the probe could not measure the sketch (`Motion.unmeasured` gives a reason), so nothing is known
  about what the size does to it.

A motion file keeps the reason for each sketch (by name) that was not measured. A sketch that is missing there was
measured, or is not used by a step the probe looks at.

A measured reference (a plane, axis or point of another component that a step uses) has the same three answers
(`ref_answer`): `Motion.refs` lists every reference the probe looked at, with the reason when it could not measure it.
"""
from . import keys
from .motion import Affine, Stuck, Terms

STILL, MOVED, NOT_MEASURED = "still", "moved", "not measured"

NOT_FOLLOWABLE = "a step uses it in a way the probe cannot follow"
NOT_MATCHED = "its first read did not match the capture"
NOT_TRIED = "the sketch could not be tried for this size"
NOT_READ = "the design could not be read at its current sizes"
NOT_LOOKED = "the probe did not look at it"


class Answer:
    """One of the three answers. `keys` are the motion keys that the size moves (for `MOVED`), `reason` says why a
    sketch was not measured (for `NOT_MEASURED`)."""

    def __init__(self, kind, keys=(), reason=""):
        self.kind = kind
        self.keys = tuple(keys)
        self.reason = reason

    def __repr__(self):
        return "Answer(%r, %r, %r)" % (self.kind, self.keys, self.reason)


def span(motion, size):
    """`{ low, high, failed }` of a size the probe set to other values (`Motion.spans`), or None."""
    if motion is None or getattr(motion, "optimistic", False):
        return None
    found = (getattr(motion, "spans", None) or {}).get(size)
    return found if isinstance(found, dict) else None


def not_built(motion, size):
    """True when the probe set the size to other values and Fusion rebuilt the design at none of them, or only in
    several pieces: nothing was measured for it."""
    found = span(motion, size)
    return bool(found and (found.get("failed") or found.get("split")) and abs(found["high"] - found["low"]) <= 1e-9)


def kept_only_now(motion, size):
    """True when the probe found no value but the value now at which Fusion rebuilt and every followed sketch kept its
    outline (`Motion.spans` `kept` is the value now at both ends): the copy cannot follow the size."""
    found = span(motion, size)
    kept = (found or {}).get("kept")
    return bool(kept and None not in kept and abs(kept[1] - kept[0]) <= 1e-9)


def unmeasured(found, readable, read):
    """{ sketch name: reason } of the sketches of a `plan.Scan` that the probe could not measure.

    `readable` holds the tokens of the covered sketches whose first read matches the capture, `read` is whether that
    first read exists. A sketch no record gives a name for cannot be told apart from others and is left out."""
    out = {}
    for token, name in found.named.items():
        if token in found.uncovered:
            reason = NOT_FOLLOWABLE
        elif token in found.covered and not read:
            reason = NOT_READ
        elif token in found.covered and token not in readable:
            reason = NOT_MATCHED
        else:
            continue
        out.setdefault(name, reason)
    return out


def _driven(table, value):
    """Fusion names of the free sizes behind a motion value (an Affine's terms, a Stuck's movers and its rest)."""
    if isinstance(value, Stuck):
        names = set(value.movers) | (set(value.rest.terms) if value.rest is not None else set())
    elif isinstance(value, Affine):
        names = set(value.terms)
    elif isinstance(value, Terms):
        names = set(value.names())
    else:
        names = set()
    out = set()
    for name in names:
        out |= table.depends(name)
    return out


def ref_answer(table, motion, ref_key, size):
    """What the motion file says about size `size` (a Fusion name of a size that acts on the component owning the
    reference) and the measured reference `ref_key` (`<item>.<slot>`): an `Answer` of `STILL`, `MOVED` (with the keys
    of the reference the size moves) or `NOT_MEASURED`."""
    refs = getattr(motion, "refs", {})
    if ref_key not in refs:
        return Answer(NOT_MEASURED, reason=NOT_LOOKED)
    if refs[ref_key]:
        return Answer(NOT_MEASURED, reason=refs[ref_key])
    if size in getattr(motion, "untried", ()):
        return Answer(NOT_MEASURED, reason=NOT_TRIED)
    item, _, slot = ref_key.partition(".")
    prefix = keys.reference(item, slot) + "/"
    moved = [key for key, value in motion.values.items() if key.startswith(prefix) and size in _driven(table, value)]
    return Answer(MOVED, moved) if moved else Answer(STILL)
