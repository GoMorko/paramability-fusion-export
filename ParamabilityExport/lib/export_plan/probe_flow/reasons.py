"""The reasons a size or a parameter gets no try, or could not be compared, as the report words them."""
from ...params.expressions.text import format_number
from ...sketch_values.motion import SHAPE, TURNS, UNREAD

# Why a parameter of another component got no try; kept in the discovery record of `report.json`.
NOT_TRIED = "not tried: the export tries only a limited number of parameters of other components"
NOT_READ_TRY = "not tried: the design could not be read at the value tried"
NOT_TRIED_STOPPED = "not tried: the tries stopped early, after a try left a step worse than before"
NOT_TRIED_TIME = "not tried: the tries ran out of time"
NOT_TRIED_ENDED = "not tried: a try left a step of its component worse than before"
# Why a try that Fusion built is kept as one that did not: a step of the part shows a new warning there.
WARNED_TRY = "Fusion shows a warning on %s at this size"
# Why a try that Fusion built is kept as one that did not: a step of the part in error at the start builds there.
CLEARED_TRY = "%s builds at this size, but it is in error in Fusion now and the copy leaves it out"


def not_built_try(value, step):
    """Why a discovery row gave no answer: Fusion did not rebuild the design at the value tried."""
    at = " at %s" % format_number(value) if isinstance(value, (int, float)) else ""
    return "not tried: the design does not rebuild in Fusion%s%s" % (at, " (%s)" % step if step else "")


UNTRIED = "it changes a sketch and could not be tried at other values"
# Why a sketch could not be compared with its first read after the parameters were put back, by `match` cause.
RESTORE_WHY = {SHAPE: "reads another outline", TURNS: "lies on a turned plane", UNREAD: "could not be read"}
UNREADABLE = "a sketch it changes could not be read at other values"


def watched_why(sketch):
    return "it changes the sketch %s, which could not be followed" % sketch
