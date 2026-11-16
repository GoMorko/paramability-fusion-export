"""The recorder: what the shared design layer asks of the translation that calls it.

Both translation contexts have every member (`translator.context.Context` and `orca_translate.context.Context`).
`tests/test_interfaces.py` checks that, and that `design_model` asks a recorder only for these members.
"""
from typing import Protocol


class Recorder(Protocol):
    """The state of one translation as the shared layer sees it.

    table: the export's size table (`params.size_table.SizeTable`), or None when no size is ticked.
    capture: the capture dict being translated.
    cache: a dict that lives as long as the translation, for values worked out once (keyed by module).
    motion: the probe's motion file of sketch values and measured references, or None (always None for Orca).
    doubt(names, why): these Fusion names of sizes move something the copy keeps where it is, for `why`.
    note(text): a plain sentence about the step being copied.
    follow_component(component): a value follows the sizes of another component (`{ token, name }` or its name).
    """

    table: object
    capture: dict
    cache: dict
    motion: object

    def doubt(self, names, why): ...

    def note(self, text): ...

    def follow_component(self, component): ...
