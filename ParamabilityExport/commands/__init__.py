"""Command folders. Each one exposes start() and stop()."""
from .ExportForParamability import entry as export_for_paramability
from .ExportForOrca import entry as export_for_orca
from .ExportSizeChoices import entry as export_size_choices

COMMANDS = [export_for_paramability, export_size_choices, export_for_orca]


def start():
    for command in COMMANDS:
        command.start()


def stop():
    for command in reversed(COMMANDS):
        command.stop()
