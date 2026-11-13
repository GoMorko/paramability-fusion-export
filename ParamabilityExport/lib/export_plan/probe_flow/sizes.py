"""Which sizes the probe tries: the one place that decides it."""
from ...translator.sizes import probed_sizes
from ..size_offers import probe_sizes

# Ticked sizes that nothing ties to a sketch, tried after all the others while rows are left.
MAX_EXTRA_SIZES = 8


def kept_sizes(table, free_sizes):
    """Fusion names of the sizes to probe: the free sizes of the first translation (recipe names in `free_sizes`),
    plus every ticked size that reaches a sketch dimension, a construction plane or a sketch through another component
    (`translator.sizes.probed_sizes`). In table order."""
    free = set(free_sizes)
    driven = set(probed_sizes(table))
    return [n for n in table.ticked if table.size_name(n) in free or n in driven]


def extra_sizes(table, kept, limit=MAX_EXTRA_SIZES):
    """Fusion names of the ticked sizes the probe also tries although nothing ties them to a sketch: the person ticked
    them, so they may move a sketch in a way the capture cannot show. At most `limit`, in table order; `kept` are the
    sizes probed anyway."""
    kept = set(kept)
    return [name for name in table.ticked if name not in kept][:limit]


def sizes_to_try(table, parameters, free_sizes):
    """`(sizes, extra)` for the probe of a first translation whose free sizes (recipe names) are `free_sizes`: `sizes`
    are the probe size dicts (`size_offers.probe_sizes`) of the kept sizes and the guessed ones, `extra` the Fusion
    names of the guessed ones, which have no sketch to follow and are tried while rows are left."""
    kept = kept_sizes(table, free_sizes)
    extra = extra_sizes(table, kept)
    keep = {table.size_name(n) for n in (*kept, *extra)} - {None, ""}
    return probe_sizes(table, parameters, keep=keep), extra
