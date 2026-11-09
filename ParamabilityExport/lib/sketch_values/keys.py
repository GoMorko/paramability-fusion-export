"""The keys of the motion file: the one place that writes them, for the probe (which fills them) and the translator
(which looks them up). Pure.

    <item>/p<profile>                     a profile record: the prefix of the keys below
    <prefix>/l<loop>/<field path>         a number of a written loop (`l0` is the outer loop)
    <prefix>/plane                        the position of the sketch plane along its normal
    <prefix>/c<loop>.<curve>/<field>      a sketch curve of the profile (a line's `offset` and `turn`, an arc's
                                          `center.0`, `center.1` and `radius`)
    <item>/positions/<n>/<0|1|2>          a coordinate of a hole point
    <item>/axis/point/<0|1|2>             a coordinate of a revolve axis point

A key belongs to one sketch; the sketch is named by the record the key stands for, not by the key.
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
