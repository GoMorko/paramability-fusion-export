"""Fusion add-in entry: run(context) and stop(context)."""
import sys
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


def _forget_modules():
    """Drop this add-in's modules from Python's cache, so Run after Stop loads the files on disk again."""
    prefix = (__package__ or "") + "."
    if prefix == ".":
        return
    for name in [n for n in sys.modules if n.startswith(prefix)]:
        del sys.modules[name]


def stop(context):
    try:
        commands.stop()
    except Exception:
        _show("Paramability export could not stop cleanly.\n\n" + traceback.format_exc())
    _forget_modules()
