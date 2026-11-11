"""The keys of the motion file: the one place that writes them, for the probe (which fills them) and the translator
(which looks them up). Pure.

    <item>/p<profile>                     a profile record: the prefix of the keys below
    <prefix>/l<loop>/<field path>         a number of a written loop (`l0` is the outer loop)
    <prefix>/plane                        the position of the sketch plane along its normal
    <prefix>/c<loop>.<curve>/<field>      a sketch curve of the profile (a line's `offset` and `turn`, an arc's
                                          `center.0`, `center.1` and `radius`)
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


def item_of(key):
    """The timeline item a key belongs to."""
    return key.split("/", 1)[0]


def is_curve(key):
    """True for a key of a sketch curve (`<prefix>/c<loop>.<curve>/<field>`)."""
    parts = key.split("/")
    return len(parts) == 4 and parts[1].startswith("p") and parts[2].startswith("c")
