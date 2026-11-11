"""The keys of the motion file: the one place that writes them, for the probe (which fills them) and the translator
(which looks them up). Pure.

    <item>/p<profile>                     a profile record: the prefix of the keys below
    <prefix>/l<loop>/<field path>         a number of a written loop (`l0` is the outer loop)
    <prefix>/plane                        the position of the sketch plane along its normal
    <prefix>/c<loop>.<curve>/<field>      a sketch curve of the profile (a line's `offset` and `turn`, an arc's
                                          `center.0`, `center.1` and `radius`)
    <item>/path                           a sweep path record: the prefix of the keys below
    <item>/path/c<n>/<field>              a curve of the sweep path (`n` counts the path entities as captured): a
                                          line's `start.0`, `start.1`, `end.0`, `end.1`; an arc's also `mid.0`,
                                          `mid.1`, `center.0`, `center.1`, `radius` and `turn` (degrees swept); a
                                          circle's `center.0`, `center.1` and `radius`. Coordinates are in the path
                                          sketch's own plane.
    <item>/path/plane                     the position of the path sketch plane along its normal
    <item>/positions/<n>/<0|1|2>          a coordinate of a hole point
    <item>/axis/point/<0|1|2>             a coordinate of a revolve axis point
    <item>/r/<slot>/offset                how far a measured reference plane moved along its captured normal
    <item>/r/<slot>/point/<0|1|2>         how far a measured reference axis (across its direction) or point moved,
                                          per coordinate
    <item>/r/<slot>/dir                   a measured reference direction (only ever stuck: it turned)

A key of a sketch belongs to one sketch; the sketch is named by the record the key stands for, not by the key. A
reference key belongs to the reference `<item>.<slot>` of the capture (`params.geometry_links.ref_key`); its values are
moves from the captured place, so they are zero at the sizes the capture was read at.
"""


def profile(item, number):
    """The prefix of profile `number` of timeline item `item`."""
    return "%s/p%d" % (item, number)


def loop_field(prefix, loop, path):
    return "%s/l%d/%s" % (prefix, loop, path)


def plane(prefix):
    return prefix + "/plane"


def curve(prefix, loop, number):
    """The prefix of a sketch curve's keys, ending in a slash: add the field name."""
    return "%s/c%d.%d/" % (prefix, loop, number)


def path(item):
    """The prefix of the keys of the sweep path of timeline item `item`."""
    return "%s/path" % item


def path_curve(item, number):
    """The prefix of path entity `number`'s keys, ending in a slash: add the field name."""
    return "%s/c%d/" % (path(item), number)


def path_plane(item):
    return path(item) + "/plane"


def positions(item):
    """The prefix of the hole point keys of an item."""
    return "%s/positions" % item


def hole_point(item, number, coordinate):
    return "%s/%d/%d" % (positions(item), number, coordinate)


def axis(item):
    """The prefix of the revolve axis point keys of an item."""
    return "%s/axis/point" % item


def axis_point(item, coordinate):
    return "%s/%d" % (axis(item), coordinate)


def reference(item, slot):
    """The prefix of the keys of a measured reference: the step's timeline index and the reference slot."""
    return "%s/r/%s" % (item, slot)


def reference_offset(item, slot):
    return reference(item, slot) + "/offset"


def reference_point(item, slot, coordinate):
    return "%s/point/%d" % (reference(item, slot), coordinate)


def reference_dir(item, slot):
    return reference(item, slot) + "/dir"
