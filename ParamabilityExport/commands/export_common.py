"""Pieces both exports share: the writer text, the restore warning and the plain error boxes."""
import os

import adsk.core

from .. import config
from ..lib.export_plan.naming import addin_version, writer_text
from ..lib.fusion_reader import design_info
from ..lib.fusion_ui.log import log, message_box

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


def warn_unrestored(job):
    """Tell the person when a parameter could not be put back. Parameters are the one thing never left changed."""
    if job is None or not job.restore_failures:
        return
    names = ", ".join(job.restore_failures)
    log(f"could not restore: {names}")
    message_box(
        "These parameters could not be set back, please check them: " + names
        + ".\nUse Undo in Fusion if they look wrong.", error=True)


def app():
    return adsk.core.Application.get()
