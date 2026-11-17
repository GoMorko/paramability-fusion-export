"""Pieces both exports share: the writer text, the restore warning and the guard that turns every way an export can
stop into a plain message."""
import os

import adsk.core

from .. import config
from ..lib.design_edit.apply import RowBuildError
from ..lib.design_edit.errors import StepExportError
from ..lib.design_edit.marker import not_put_back_message, put_back
from ..lib.design_edit.timeline_health import settle_timeline
from ..lib.export_plan import rollback
from ..lib.export_plan.health import HealthInputs, left_off_line, make_health, steps_lines
from ..lib.package.naming import addin_version, writer_text
from ..lib.design_edit.runner import ExportCancelled
from ..lib.export_plan import messages
from ..lib.fusion_reader import design_info
from ..lib.fusion_reader.capture import MarkerError
from ..lib.fusion_ui.log import error_box, log, message_box
from ..lib.fusion_ui.progress import ProgressDialog
from ..lib.package.caps import PackageCapError
from ..lib.timing import trail

_ADDIN_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def writer_for(app):
    return writer_text(addin_release(), design_info.fusion_version(app))


def addin_release():
    """The version of this add-in, from its .manifest file ("unknown" when it cannot be read)."""
    return addin_version(_manifest_path())


def _manifest_path():
    """The add-in's .manifest file, found by its extension so a renamed folder still reads it."""
    named = os.path.join(_ADDIN_DIR, config.ADDIN_NAME + ".manifest")
    if os.path.exists(named):
        return named
    found = sorted(n for n in os.listdir(_ADDIN_DIR) if n.endswith(".manifest"))
    return os.path.join(_ADDIN_DIR, found[0]) if found else named


def progress_dialog(verb):
    """The progress window of an export step. The sketch tries get an explanation that stays and a line per try."""
    if verb == messages.TRY_VERB:
        return ProgressDialog("Export for Paramability", intro=messages.TRY_INTRO, line=messages.try_line,
                              shown="Try %v of %m")
    return ProgressDialog("Export for Paramability", verb=verb)


def warn_unrestored(names):
    """Tell the person when parameters could not be put back. Parameters are the one thing never left changed."""
    if not names:
        return
    names = ", ".join(names)
    log(f"could not restore: {names}")
    message_box(
        "These parameters could not be set back, please check them: " + names
        + ".\nUse Undo in Fusion if they look wrong, or reopen the design from its last save.", error=True)


def warn_left_off(names, undo_dropped=False):
    """Tell the person when timeline steps turned off for the faster tries could not be turned back on. With
    `undo_dropped` (Lighter on memory) Undo is not offered, as in the health lines."""
    if not names:
        return
    log("could not turn back on: " + ", ".join(names))
    message_box(left_off_line(names, undo_dropped), error=True)


def warn_steps(lines):
    """Tell the person which timeline steps differ from before the export (`export_plan.health.steps_lines`)."""
    if not lines:
        return
    log("timeline steps after the export: " + " ".join(lines))
    message_box("\n\n".join(lines), error=True)


def settle_steps(store, start, saved, outcome=None, unrestored=lambda: ()):
    """For an export that keeps no health record of its own: compare the timeline steps with `start`, rebuild when one
    differs (`timeline_health.settle_timeline`) and tell the person what is still changed. Never raises.

    With an `outcome` (`rollback.ExportOutcome`) its health is made here from the steps and `unrestored()`, the names
    of the parameters that did not go back. When the check fails the outcome keeps no health, which counts as a
    design that is not confirmed back."""
    try:
        settled = settle_timeline(store, start, saved, log)
        if outcome is not None:
            outcome.health = make_health(HealthInputs(unrestored=unrestored(), steps=settled))
        warn_steps(steps_lines(settled))
    except Exception as exc:
        log(f"checking the timeline steps after the export failed: {exc!r}")


def contained(outcome, run):
    """Run `run()` and return `outcome`. An exception that no guard caught is shown and logged, not raised: an export
    never raises into the handler of the command, which must still tell Fusion to undo it (`rollback.ExecuteGate`)."""
    try:
        run()
    except Exception:
        error_box("The export stopped.")
    return outcome


def tell_undone(undo):
    """Tell the person that Fusion undoes the export, or that it could not be undone (`rollback.lines`), for an export
    that saved no file."""
    message_box("\n\n".join(rollback.lines(undo)), error=True)


def run_guarded(design, marker, work, unrestored=lambda: (), settle=None, outcome=None):
    """Run `work()` and return its value, or None when the export stopped. Each way it stops gets a plain message,
    and the timeline marker is moved back to `marker` at the end. `unrestored()` names the parameters that could not be
    put back, for an export that does not check this itself; `settle()`, when given, runs once the parameters are back
    (`settle_steps`). A marker that does not go back marks `outcome` (`rollback.ExportOutcome`) as not confirmed, so
    Fusion undoes the export (`rollback.decide`). The export trail (`timing.trail`) covers the whole run."""
    trail.start("export")
    try:
        return work()
    except ExportCancelled:
        message_box("Export cancelled. Your parameters are back to their values.")
    except (RowBuildError, StepExportError, PackageCapError, MarkerError) as exc:
        message_box(f"{exc}\n\nNothing was saved. Your parameters are back to their values.", error=True)
    except Exception:
        error_box("The export stopped. Nothing was saved.")
    finally:
        warn_unrestored(unrestored())
        if settle is not None:
            settle()
        if marker is not None and not put_back(design.timeline, marker):
            if outcome is not None:
                outcome.unconfirmed = True
            message_box(not_put_back_message(marker), error=True)
        trail.end("export")
    return None


def app():
    return adsk.core.Application.get()
