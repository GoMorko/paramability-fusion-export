"""Which sketches the probe measured. Pure.

For one sketch and one size the motion file gives one of three answers:

- `STILL`: the sketch was measured and the size did not move it (its values have no key in the motion file);
- `MOVED`: it was measured and the size moved it (the keys with their `Affine` or `Stuck` say how);
- `NOT_MEASURED`: the probe could not measure the sketch (`Motion.unmeasured` gives a reason), so nothing is known
  about what the size does to it.

A motion file keeps the reason for each sketch (by name) that was not measured. A sketch that is missing there was
measured, or is not used by a step the probe looks at.
"""
STILL, MOVED, NOT_MEASURED = "still", "moved", "not measured"

NOT_FOLLOWABLE = "a step uses it in a way the probe cannot follow"
NOT_MATCHED = "its first read did not match the capture"
NOT_TRIED = "the sketch could not be tried for this size"
NOT_READ = "the design could not be read at its current sizes"


class Answer:
    """One of the three answers. `keys` are the motion keys that the size moves (for `MOVED`), `reason` says why a
    sketch was not measured (for `NOT_MEASURED`)."""

    def __init__(self, kind, keys=(), reason=""):
        self.kind = kind
        self.keys = tuple(keys)
        self.reason = reason

    def __repr__(self):
        return "Answer(%r, %r, %r)" % (self.kind, self.keys, self.reason)


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
