"""Fusion add-in entry: run(context) and stop(context)."""
import traceback

import adsk.core

from . import commands

_app = None


def _show(text):
    try:
        ui = adsk.core.Application.get().userInterface
        ui.messageBox(text)
    except Exception:
        pass


def run(context):
    global _app
    try:
        _app = adsk.core.Application.get()
        commands.start()
    except Exception:
        _show("Paramability export could not start.\n\n" + traceback.format_exc())


def stop(context):
    try:
        commands.stop()
    except Exception:
        _show("Paramability export could not stop cleanly.\n\n" + traceback.format_exc())
