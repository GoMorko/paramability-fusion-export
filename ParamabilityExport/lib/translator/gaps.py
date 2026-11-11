"""Steps the walk leaves out of the copy (gaps), and when a gap stops the copy instead.

A gap is a step that the copy cannot hold but whose effect stays on the body: the rest of the timeline still reads
right without it. The record names the step, says why it is missing and where it belongs in the recipe, and keeps the
step's Fusion data, so the missing step can be added to the copy later.

The walk records a `Gap` with the ids of the steps it wrote before it. The rest of the gap's handling sits in
`gap_picks.py` (which gaps a step picks faces of), `gap_measures.py` (the body around a gap), `gap_place.py` (where a
gap belongs once the recipe is final) and `gap_file.py` (the gap as written for the package).
"""
from ..package.text import clip
from . import notes as wording
from .words import type_words

# The app refuses a whole gaps file that breaks one of these (`RECIPE_GAPS_CAPS` in the app's recipe package); the
# caps of the gaps file's own fields are in `gap_file.py`.
MAX_GAPS = 16
MAX_ID = 64
MAX_NAME = 120


class Gap:
    """A step left out of the copy.

    item: the capture item as the walk saw it. reason: why it is missing. depends_on: ids of the earlier gaps whose
    faces it picks or repeats. written_before: ids of the steps of its walk's list written before it. before, after:
    `{ box, volume }` of the walk's body around the step, in the capture's coordinates, or None when not measured.
    picks: True when the step is a gap only because it picks, or may pick, faces of earlier gaps.
    """

    def __init__(self, gap_id, item, reason, depends_on, written_before, before=None, after=None, picks=False):
        self.id = gap_id
        self.item = item
        self.reason = clip(reason, wording.MAX_NOTE) or "This step cannot be copied."
        self.depends_on = list(dict.fromkeys(depends_on))
        self.written_before = list(written_before)
        self.before, self.after = before, after
        self.picks = picks
        self.place = None  # (after, before, list) once placed in the final recipe

    @property
    def index(self):
        return self.item.get("index")

    @property
    def name(self):
        """The item's name, or its type in words when the name is empty or only spaces."""
        return (str(self.item.get("name") or "").strip()[:MAX_NAME].strip()
                or type_words(self.item.get("type") or "").strip() or "A step")


def gap_id(ctx, item):
    """`gap_<timeline index>`, after the walk's id prefix, as step ids are made."""
    found = "%sgap_%s" % (ctx.id_prefix, item.get("index"))
    return found[-MAX_ID:]


def _first_body_stop(ctx):
    return not ctx.steps or ctx.component is not None


def at_cap(ctx):
    """True when a gap at the walk's current place stops the copy because the part already holds MAX_GAPS gaps,
    counting those of the walks that hold this one. A tool walk that stops this way stops the whole copy."""
    if _first_body_stop(ctx):
        return False
    count, walk = 0, ctx
    while walk is not None:
        count += len(walk.gaps)
        walk = walk.outer
    return count >= MAX_GAPS


def stop_reason(ctx, reason):
    """The reason that stops the copy instead of a gap at the walk's current place, or None when a gap is kept.

    A gap needs a body to add to, so one before the walk's first step stops it with its own reason. So does a gap in a
    walk of another component's body, whose data is not in the part's coordinates. A part with too many gaps stops
    too."""
    if _first_body_stop(ctx):
        return reason
    if at_cap(ctx):
        return wording.too_many_gaps_reason(MAX_GAPS)
    return None
