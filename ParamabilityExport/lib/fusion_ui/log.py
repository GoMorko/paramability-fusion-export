"""Log line and message boxes."""
import traceback

import adsk.core

TITLE = "Paramability export"


def _app():
    return adsk.core.Application.get()


def log(text):
    try:
        _app().log(f"{TITLE}: {text}")
    except Exception:
        pass


def message_box(text, error=False):
    try:
        icon = adsk.core.MessageBoxIconTypes.CriticalIconType if error else adsk.core.MessageBoxIconTypes.InformationIconType
        _app().userInterface.messageBox(
            text, TITLE, adsk.core.MessageBoxButtonTypes.OKButtonType, icon)
    except Exception:
        pass


def error_box(prefix):
    """Show prefix plus the current exception's trace, and log it."""
    detail = traceback.format_exc()
    log(detail)
    message_box(f"{prefix}\n\n{detail}", error=True)
