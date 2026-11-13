"""Which sizes the probe tries."""
from ...translator.sizes import probed_sizes

# Ticked sizes that nothing ties to a sketch, tried after all the others while rows are left.
MAX_EXTRA_SIZES = 8


def sketch_driven(table):
    """Fusion names of the ticked sizes that reach a model parameter made by a sketch dimension or a construction
    plane (of the body's scope), or a sketch or a measured reference through the geometry of another component
    (`table.links`), in table order (`translator.sizes.probed_sizes`)."""
    return probed_sizes(table)


def extra_sizes(table, kept, limit=MAX_EXTRA_SIZES):
    """Fusion names of the ticked sizes the probe also tries although nothing ties them to a sketch: the person ticked
    them, so they may move a sketch in a way the capture cannot show. At most `limit`, in table order; `kept` are the
    sizes probed anyway."""
    kept = set(kept)
    return [name for name in table.ticked if name not in kept][:limit]


def kept_sizes(table, free_sizes):
    """Fusion names of the sizes to probe: the free sizes of the first translation (recipe names in `free_sizes`),
    plus every ticked size that reaches a sketch dimension, a construction plane or a sketch through another component
    (`sketch_driven`). In table order."""
    free = set(free_sizes)
    driven = set(sketch_driven(table))
    return [n for n in table.ticked if table.size_name(n) in free or n in driven]
