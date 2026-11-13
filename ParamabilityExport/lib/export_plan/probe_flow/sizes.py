"""Which sizes the probe tries."""
from ...probe import plan


def kept_size_names(table, free_sizes):
    """Recipe names of the sizes to probe: the free sizes of the first translation and every ticked size that
    reaches a sketch dimension, a construction plane or a sketch through the geometry of another component."""
    names = plan.kept_sizes(table, free_sizes)
    return {table.size_name(n) for n in names if table.size_name(n)}


def extra_size_params(table, free_sizes):
    """Fusion names of the ticked sizes tried on a guess (`plan.extra_sizes`): nothing ties them to a sketch, but
    the person ticked them, so a sketch may follow them in a way the capture cannot show."""
    return plan.extra_sizes(table, plan.kept_sizes(table, free_sizes))
