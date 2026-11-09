"""A short, non-blocking line in the lower-right corner of the Fusion window (UserInterface.statusMessage)."""
import adsk
import adsk.core

from .log import log


def status_notice(text):
    """Show `text` in Fusion's status area. Fusion shares that field, so how long the text stays is not fixed."""
    if not text:
        return
    try:
        adsk.core.Application.get().userInterface.statusMessage = text
        adsk.doEvents()
    except Exception as error:
        log("status message failed: %s" % error)
