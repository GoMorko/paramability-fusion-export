"""Walk state handed to every handler."""
from . import meets_part
from .capture import same_body
from .copy_counts import raised_minimums
from .follow import Slab, locate
from .notes import Past
from .offset_faces import MovedFaces
from .picks import face_points
from .shells import Shell
from .values import reads_in

MAX_ID = 64
MAX_LABEL = 120
MAX_REASON = 200


def _number(value):
    return ("%.6f" % value).rstrip("0").rstrip(".")


class Context:
    """State of one translate() run.

    target: the exported body, {token, name, box, volume_mm3}.
    capture: the whole capture (for up_axis and cross item lookups).
    pending_tools: body token (or name) -> recipe steps that build a body other than the target, not yet placed.
      The Combine handler takes them.
    not_repeatable: ids of steps whose length Fusion recomputes per copy (a handler marks a step with a private
      `_adjusts` key, which `add_steps` removes). Pattern and mirror handlers refuse them as sources.
    table: the size table whose sizes the feature values may follow, or None for a recipe with plain
      numbers only.
    depends: Fusion name of a size -> why, for each size that a value written as a number depends on (`fix`).
    must_fix: the same for sizes that must become fixed numbers whatever the mode (`fix_always`). The driver turns
      them into fixed numbers and walks again.
    slabs: the extrude steps written so far (follow.Slab), for picks and reaches that follow sizes. A handler hands
      one over in a step's private `_slab` key: { on, extent, length, profile }. A pattern or mirror step hands over
      `_copies`, one follow.Motion per copy, and the slabs of the steps it repeats are copied with them.
    written_reads: Fusion names of the sizes that the steps written so far read.
    shells: the shell steps written so far (shells.Shell), for picks on their inner walls. The shell handler hands
      one over in the private `_shell` key: { thickness (a Quantity), faces (the capture faces it opens) }.
    moved_faces: the offsetFaces steps written so far (offset_faces.MovedFaces), for picks on the faces they moved.
    minimums: Fusion name of a size -> (smallest value, reason) the picks on pattern copies need (`require`). The
      driver raises those minimums and walks again.
    narrowings: Fusion name of a size -> ((min, max), reason): shorter ranges a step needs (`narrow`). The driver
      applies them and walks again.
    follow: the walk keeps sizes free that some value cannot follow (loose mode); `narrow_or_doubt` then lists a
      shorter range as a doubt on the size instead of applying it.
    plain: ranges are never raised or shortened; `require` and `narrow` list the size as a doubt instead.
    motion: the probe's motion file (`probe.motion.Motion`), `probe.motion.OPTIMISTIC`, or None. With a motion file the
      sketch values follow sizes (sketch_motion.py); otherwise they are written as numbers.
    plain_picks: round or bevel step id -> { near, reads, written }: its edges as measured points, the sizes its pick
      follows and the written points (None when the pick names a step). A handler hands it over in the private
      `_plain` key; patterns and mirrors copy these points.
    """

    def __init__(self, capture, table=None, motion=None, follow=False, plain=False):
        self.capture = capture
        self.follow = follow
        self.plain = plain
        self.table = table
        self.motion = motion
        self.depends = {}
        self.must_fix = {}
        self.slabs = []
        self.shells = []
        self.moved_faces = []
        self._placers = 0
        self.written_reads = ()
        self.plain_picks = {}
        self.target = capture["target"]
        self.steps = []
        self.pending_tools = {}
        self.not_repeatable = set()
        self._ids_by_index = {}
        self._notes = []
        self.current = None
        self.minimums = {}
        self.narrowings = {}

    def is_target(self, body):
        return same_body(body, self.target)

    def note(self, text):
        """Attach a plain sentence to the item being handled; its verdict becomes translatedWithNote."""
        self._notes.append(text)

    def fix(self, names, why):
        """Record that a value cannot follow the sizes `names` (Fusion names): it is written as its number. The driver
        fixes these sizes, or keeps them free with a warning (`translate`, `loose`). `why` ends the reason."""
        for name in names:
            self.depends.setdefault(name, why)

    def fix_always(self, names, why):
        """Like `fix`, for a value that would make the recipe unusable while the sizes stay free."""
        for name in names:
            self.must_fix.setdefault(name, why)

    def require(self, count, least, why):
        """A pick needs the count Quantity `count` to stay at `least` or more. The smallest values of the sizes it reads
        are raised (`minimums`: Fusion name to (number, reason)); when that cannot work, they cannot follow (`fix`)."""
        raised = raised_minimums(self.table, count, least) if self.table is not None else {}
        if self.plain:
            if raised != {}:
                self.fix(count.reads, "%s, and a smaller value would leave that copy out" % why)
            return
        if raised is None:
            self.fix(count.reads, "%s, and a smaller value would leave that copy out" % why)
            return
        for name, value in raised.items():
            if value > self.minimums.get(name, (float("-inf"),))[0]:
                text = "%s starts at %s: %s, which needs at least %d copies." % (name, _number(value), why, least)
                self.minimums[name] = (value, text[:MAX_REASON])

    def narrow(self, found, why, doubt=None):
        """Shorten the ranges of sizes: `found` maps a Fusion name to its new (min, max); `why` ends the reason.
        A plain walk lists each size as a doubt with `doubt` (else `why`) instead."""
        if self.plain:
            self._doubt_past(found, doubt or why)
            return
        for name, (lo, hi) in found.items():
            old = self.narrowings.get(name)
            if old is not None:
                lo, hi = max(lo, old[0][0]), min(hi, old[0][1])
            size = self.table.sizes.get(self.table.size_name(name)) or {}
            if lo > size.get("min", lo) and hi < size.get("max", hi):
                text = "%s stays between %s and %s: %s." % (name, _number(lo), _number(hi), why)
            elif lo > size.get("min", lo):
                text = "%s starts at %s: %s." % (name, _number(lo), why)
            else:
                text = "%s ends at %s: %s." % (name, _number(hi), why)
            self.narrowings[name] = ((lo, hi), text[:MAX_REASON])

    def narrow_or_doubt(self, found, why, doubt):
        """Like `narrow`; in a walk that keeps sizes free (`follow`) the ranges stay and each size in `found` gets
        `doubt` as its reason, with the values past which it holds."""
        if not self.follow:
            self.narrow(found, why, doubt)
            return
        self._doubt_past(found, doubt)

    def _doubt_past(self, found, doubt):
        """Each size in `found` gets `doubt` as its reason, with the values past which it holds."""
        for name, (lo, hi) in found.items():
            size = self.table.sizes.get(self.table.size_name(name)) or {}
            below, past = lo > size.get("min", lo), hi < size.get("max", hi)
            where = ("outside %s to %s" % (_number(lo), _number(hi)) if below and past
                     else "below %s" % _number(lo) if below else "past %s" % _number(hi))
            self.depends.setdefault(name, Past(where, doubt))

    def _add_moved_faces(self, item, step):
        self._placers += 1
        moved = MovedFaces((item.get("data") or {}).get("faces") or [], step["distance"], None, len(self.slabs),
                           self._placers)
        moved.earlier = lambda p, edge: locate(self, p, edge, moved)
        self.moved_faces.append(moved)

    def take_notes(self):
        notes, self._notes = self._notes, []
        return notes

    def steps_of(self, index):
        """Step ids written for the timeline item at `index` (empty when it made none)."""
        return list(self._ids_by_index.get(index, ()))

    def slabs_of(self, step_id):
        """The slabs of the bodies a step makes: an extrude's own, or a repeat's originals and copies."""
        step = next((s for s in self.steps if s.get("id") == step_id), None)
        found = []
        if step is not None and step.get("kind") in ("pattern", "mirror"):
            for of in step.get("of") or []:
                found.extend(self.slabs_of(of))
        found.extend(s for s in self.slabs if s.owner == step_id)
        unique = []
        for slab in found:
            if all(slab is not other for other in unique):
                unique.append(slab)
        return unique

    def add_steps(self, item, steps):
        """Give each step its id and label, append to the recipe, return the ids.

        Ids: `<kind>_<index>`, then `<kind>_<index>_<n>` for the second and later steps of one item.
        """
        ids = []
        label = str(item.get("name", ""))[:MAX_LABEL]
        made = self._ids_by_index.setdefault(item["index"], [])
        for n, step in enumerate(steps, start=len(made) + 1):
            base = "%s_%s" % (step["kind"], item["index"])
            step_id = base if n == 1 else "%s_%d" % (base, n)
            if len(step_id) > MAX_ID:
                step_id = step_id[-MAX_ID:]
            if step.pop("_adjusts", False):
                self.not_repeatable.add(step_id)
            slab = step.pop("_slab", None)
            if slab is not None and slab["profile"].get("borrowed"):
                profile = slab["profile"]
                meets_part.check(self, step_id, slab, step.get("combine", "add"), "%s (drawn on %s of %s)" % (
                    label or "a step", profile.get("sketch") or "a sketch", profile["borrowed"]))
            if slab is not None:
                self.slabs.append(Slab(step_id, slab["on"], slab["extent"], slab["length"], slab["profile"],
                                       combine=step.get("combine", "add"), taper=slab.get("taper"),
                                       outline=slab.get("outline")))
            shell = step.pop("_shell", None)
            if shell is not None:
                opened = [locate(self, p) for p in face_points(shell["faces"])]
                self.shells.append(Shell(shell["thickness"], self.slabs, [o for o in opened if o is not None],
                                         len(self.slabs)))
                self._placers += 1
                self.shells[-1].seq = self._placers
            if step.get("kind") == "offsetFaces":
                self._add_moved_faces(item, step)
            copies = step.pop("_copies", None)
            if copies:
                sources = [s for of in step.get("of") or [] for s in self.slabs_of(of)]
                self.slabs.extend(s.copied(step_id, motion) for motion in copies for s in sources)
            plain = step.pop("_plain", None)
            if plain is not None:
                self.plain_picks[step_id] = plain
            self.written_reads = tuple(dict.fromkeys(self.written_reads + reads_in(step)))
            step["id"] = step_id
            step["label"] = label
            self.steps.append(step)
            ids.append(step_id)
        made.extend(ids)
        return ids
