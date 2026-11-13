"""Telling the person what could not be put back after the export."""
from .. import health as health_module
from .settle import deferred_left, settle_steps, undo_dropped


def warn_left_off(port, timeline, settled=None, undo=False):
    """Tell the person about timeline items that would not turn back on after the tries (`TryTimeline.left_off`),
    leaving out the steps the end check (`settle_steps`) still lists as changed: its own lines name them. `undo` is
    True when Fusion forgot Undo data during the export (`undo_dropped`)."""
    told = {c["name"] for c in settled.changed} if settled is not None else set()
    names = [name for name in (timeline.left_off if timeline is not None else []) if name not in told]
    if names:
        port.warn_left_off(names, undo)


def warn_steps(owner):
    """Tell the person, when the export stopped, which timeline steps differ from the start (`settle_steps`). Never
    raises: it runs while the export stops for another reason."""
    try:
        lines = health_module.steps_lines(settle_steps(owner), deferred_left(owner), undo_dropped(owner))
        if lines:
            owner.port.warn_steps(lines)
    except Exception as exc:
        owner.port.log(f"checking the timeline steps after the export failed: {exc!r}")
