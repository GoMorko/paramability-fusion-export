"""The answer of a handler that leaves its step out of the Orca copy. `steps` gives the same name to the other
handlers."""
from ..capture_model import gap_hints


class Skip:
    """A step left out of the copy: `reason` is one plain sentence, `cause` a `gap_hints` cause."""

    def __init__(self, reason, cause=gap_hints.REFUSED):
        self.reason = reason
        self.cause = cause
