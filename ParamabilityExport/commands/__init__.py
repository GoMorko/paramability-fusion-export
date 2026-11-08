"""Command folders. Each one exposes start() and stop()."""
from .ExportForParamability import entry as export_for_paramability

COMMANDS = [export_for_paramability]


def start():
    for command in COMMANDS:
        command.start()


def stop():
    for command in reversed(COMMANDS):
        command.stop()
