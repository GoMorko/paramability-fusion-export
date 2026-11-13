"""The reasons a size or a parameter gets no try, or could not be compared, as the report words them."""
from ...params.expressions.text import format_number
from ...sketch_values.motion import SHAPE, TURNS, UNREAD

# Why a parameter of another component got no try; kept in the discovery record of `report.json`.
NOT_TRIED = "not tried: the export tries only a limited number of parameters of other components"
NOT_READ_TRY = "not tried: the design could not be read at the value tried"
NOT_TRIED_STOPPED = "not tried: the tries stopped early, after a try left a step in error"


def not_built_try(value, step):
    """Why a discovery row gave no answer: Fusion did not rebuild the design at the value tried."""
    at = " at %s" % format_number(value) if isinstance(value, (int, float)) else ""
    return "not tried: the design does not rebuild in Fusion%s%s" % (at, " (%s)" % step if step else "")


_UNTRIED = "it changes a sketch and could not be tried at other values"
# Why a sketch could not be compared with its first read after the parameters were put back, by `match` cause.
_RESTORE_WHY = {SHAPE: "reads another outline", TURNS: "lies on a turned plane", UNREAD: "could not be read"}
_UNREADABLE = "a sketch it changes could not be read at other values"


def _watched_why(sketch):
    return "it changes the sketch %s, which could not be followed" % sketch
