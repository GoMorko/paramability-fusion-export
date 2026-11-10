"""Pieces both exports share: the writer text, the restore warning and the guard that turns every way an export can
stop into a plain message."""
import os

import adsk.core

from .. import config
from ..lib.design_edit.apply import RowBuildError
from ..lib.design_edit.errors import StepExportError
from ..lib.design_edit.marker import not_put_back_message, put_back
from ..lib.package.naming import addin_version, writer_text
from ..lib.design_edit.runner import ExportCancelled
from ..lib.export_plan import messages
from ..lib.fusion_reader import design_info
from ..lib.fusion_reader.capture import MarkerError
from ..lib.fusion_ui.log import error_box, log, message_box
from ..lib.fusion_ui.progress import ProgressDialog
from ..lib.package.caps import PackageCapError

_ADDIN_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def writer_for(app):
    return writer_text(
        addin_version(_manifest_path()), design_info.fusion_version(app))


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


def run_guarded(design, marker, work, unrestored=lambda: ()):
    """Run `work()` and return its value, or None when the export stopped. Each way it stops gets a plain message,
    and the timeline marker is moved back to `marker` at the end. `unrestored()` names the parameters that could not be
    put back, for an export that does not check this itself."""
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
        if marker is not None and not put_back(design.timeline, marker):
            message_box(not_put_back_message(marker), error=True)
    return None


def app():
    return adsk.core.Application.get()
