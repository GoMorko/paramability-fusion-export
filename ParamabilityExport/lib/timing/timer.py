"""A small stopwatch that keeps named totals. A timer never raises: when the clock or the bookkeeping fails, the
measurement is dropped and the caller goes on as if nothing was timed.

A timer belongs to one export (or one capture read); it is passed down, never kept in a module level variable.
"""
import contextlib
import time

DIGITS = 2


def rounded(seconds):
    """Seconds rounded to 0.01."""
    return round(seconds + 0.0, DIGITS)


class _Span:
    """`with timer.span(name):` adds the time of the block to `name`. A name that is already open is not counted
    again, so a call that nests another call of the same kind counts once."""

    def __init__(self, timer, name):
        self.timer, self.name, self.started = timer, name, None

    def __enter__(self):
        try:
            if self.name in self.timer.open:
                return self
            started = self.timer.clock()
            self.timer.open.add(self.name)
            self.started = started
        except Exception:
            self.started = None
        return self

    def __exit__(self, *exc):
        if self.started is not None:
            try:
                self.timer.open.discard(self.name)
                self.timer.add(self.name, self.timer.clock() - self.started)
            except Exception:
                pass
        return False


class Timer:
    """Totals of seconds and counts by name."""

    def __init__(self, clock=time.perf_counter):
        self.clock = clock
        self.open = set()
        self._seconds = {}
        self._counts = {}

    def span(self, name):
        return _Span(self, name)

    def add(self, name, seconds, count=1):
        try:
            self._seconds[name] = self._seconds.get(name, 0.0) + seconds
            self._counts[name] = self._counts.get(name, 0) + count
        except Exception:
            pass

    def is_open(self, name):
        return name in self.open

    def seconds(self, name):
        return self._seconds.get(name, 0.0)

    def count(self, name):
        return self._counts.get(name, 0)

    def names(self, prefix=""):
        """The names that have a count, in the order they were first added, that start with `prefix`."""
        return [name for name in self._counts if name.startswith(prefix)]

    def entry(self, name):
        """`{ count, seconds }` of a name."""
        return {"count": self.count(name), "seconds": rounded(self.seconds(name))}


def span_on(owner, name):
    """The span `name` of `owner.timer` (or of `owner` itself when it is a timer), or a block that times nothing when
    `owner` has no timer. Never raises."""
    try:
        timer = owner if isinstance(owner, Timer) else getattr(owner, "timer", None)
        if isinstance(timer, Timer):
            return timer.span(name)
    except Exception:
        pass
    return contextlib.nullcontext()
