"""The export trail: a short line for each thing an export does in Fusion, written to a file at once, so that the
file still tells the last step when Fusion crashes in the middle of an export.

The file is `<temp folder>/ParamabilityExport/export-trail.log` (`path()`). An export, and the dialog's read of a
picked body, run inside `session(title)`: the outermost session empties the file first, so the file holds only the
last one, and turns on `faulthandler`, which writes the Python stack of every thread to the same file when the
process crashes. `stage(name)` wraps a slow part with a start line and an end line with its seconds. `line(text)` adds one line, with the time, and pushes it to the disk before it returns. A line
outside a session is added to the file of the last session. Nothing here raises: when the file cannot be written, the
trail is dropped and the export goes on.

The trail is one file per process, so its state is kept at module level, unlike the timers of this package.
"""
import contextlib
import faulthandler
import functools
import os
import tempfile
import time

FOLDER = "ParamabilityExport"
NAME = "export-trail.log"
# The folder that holds FOLDER; None for the system's temp folder (`tempfile.gettempdir`). Tests set their own.
ROOT = None
# A line longer than this is cut, so one large value cannot slow the export down.
MAX_LINE = 2000

_state = {"file": None, "depth": 0, "faults_before": False}


def path():
    """The path of the trail file."""
    return os.path.join(ROOT or tempfile.gettempdir(), FOLDER, NAME)


def _stamp():
    now = time.time()
    return time.strftime("%H:%M:%S", time.localtime(now)) + ".%03d" % int((now % 1) * 1000)


def _write(handle, text):
    handle.write("%s %s\n" % (_stamp(), text[:MAX_LINE]))
    handle.flush()
    os.fsync(handle.fileno())


def line(text):
    """Add `text` as one line of the trail. Line breaks in it are kept, as further lines."""
    try:
        text = str(text)
        handle = _state["file"]
        if handle is not None:
            _write(handle, text)
            return
        with open(path(), "a", encoding="utf-8") as handle:
            _write(handle, text)
    except Exception:
        pass


def start(title):
    """Begin a session named `title`. The outermost one empties the file and turns on `faulthandler`."""
    try:
        if _state["depth"] == 0:
            os.makedirs(os.path.dirname(path()), exist_ok=True)
            _state["file"] = open(path(), "w", encoding="utf-8")
            _state["faults_before"] = faulthandler.is_enabled()
            faulthandler.enable(file=_state["file"])
    except Exception:
        _close()
    _state["depth"] += 1
    line("start: %s" % title)


def end(title):
    """End the session `start(title)` began. The outermost one turns `faulthandler` back as it was and closes the
    file."""
    line("end: %s" % title)
    _state["depth"] = max(0, _state["depth"] - 1)
    if _state["depth"] == 0:
        _close()


def _close():
    handle, _state["file"] = _state["file"], None
    try:
        if faulthandler.is_enabled():
            faulthandler.disable()
        if _state["faults_before"]:
            faulthandler.enable()
    except Exception:
        pass
    try:
        if handle is not None:
            handle.close()
    except Exception:
        pass


@contextlib.contextmanager
def stage(name):
    """A slow part of the export: the line "`name`: start" before the block and "`name`: end, N.N s" after it (also
    when it raises), so the file tells where the time went when a part is slow."""
    line("%s: start" % name)
    began = time.monotonic()
    try:
        yield
    finally:
        line("%s: end, %.1f s" % (name, time.monotonic() - began))


def staged(name):
    """A decorator that runs the function in `stage(name)`."""
    def wrap(function):
        @functools.wraps(function)
        def run(*args, **kwargs):
            with stage(name):
                return function(*args, **kwargs)
        return run
    return wrap


@contextlib.contextmanager
def session(title):
    """`start(title)` before the block and `end(title)` after it, also when it raises."""
    start(title)
    try:
        yield
    finally:
        end(title)
