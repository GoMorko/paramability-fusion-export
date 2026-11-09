"""Walk state handed to every handler.

A handler reports what it cannot follow in one way: `doubt(names, why)` for sizes a value of its steps cannot follow,
and `note(text)` for a plain remark on its item. Both land in the handler's StepResult (`recording`), so they count
only when the walk writes its steps.
"""
from contextlib import contextmanager

from .capture import same_body
from .result import Doubt, StepResult
from .step_kinds import recipe_kind
from .values import reads_in

MAX_ID = 64
MAX_LABEL = 120


class Context:
    """State of one translate() run.

    target: the exported body, {token, name, box, volume_mm3}.
    capture: the whole capture (for up_axis and cross item lookups).
    pending_tools: body token (or name) -> the StepResult of the steps that build a body other than the target, not
      yet placed, with the doubts their handlers recorded and the capture items that made them. The Combine handler
      takes them (`StepResult.join`), so these count only once the body joins the exported one.
    not_repeatable: ids of steps whose length Fusion recomputes per copy (`Entry.repeatable`). Pattern and mirror
      handlers refuse them as sources.
    table: the size table whose sizes the feature values may follow, or None for a recipe with plain
      numbers only.
    doubts: the `result.Doubt` records that count for the walk, in order (`doubt`, `commit`). `depends` and
      `must_fix` read them by size; the driver turns the sizes of `must_fix` into fixed numbers and walks again.
    copied_items: the capture items whose steps are part of the recipe (the audit reads the sizes behind them).
    asked: `(item index, params path)` of every value the handlers of the copied items dealt with (`ask`).
    placers: the placers of the steps written so far, in the order they were made (placer.py), for picks and reaches
      that follow sizes. The placer makers of each step's `Entry` add them (`add_placer`).
    slabs: the extrude slabs among them (slabs.Slab), the originals and the pattern or mirror copies (`add_slab`).
    written_reads: Fusion names of the sizes that the steps written so far read.
    motion: the probe's motion file (`sketch_values.motion.Motion`), `sketch_values.motion.OPTIMISTIC`, or None. With a motion file the
      sketch values follow sizes (sketch_motion.py); otherwise they are written as numbers.
    plain_picks: round or bevel step id -> `Entry.picks`; patterns and mirrors copy these points.
    cache: results that depend on the capture alone, shared by every walk of one translation (one translation walks
      the capture many times). Handlers keep their own entry under their module name.
    """

    def __init__(self, capture, table=None, motion=None, cache=None):
        self.capture = capture
        self.cache = {} if cache is None else cache
        self.table = table
        self.motion = motion
        self.doubts = []
        self._recordings = []
        self.placers = []
        self.slabs = []
        self.written_reads = ()
        self.plain_picks = {}
        self.target = capture["target"]
        self.steps = []
        self.pending_tools = {}
        self.copied_items = []
        self.asked = set()
        self.not_repeatable = set()
        self._ids_by_index = {}
        self.current = None

    def is_target(self, body):
        return same_body(body, self.target)

    def doubt(self, names, why, fixed=False):
        """Record that a value cannot follow the sizes `names` (Fusion names), so it is written as its number. `why`
        ends the reason. The driver keeps these sizes free with a warning (`translate`); with `fixed` the value would
        make the recipe unusable while they stay free, so they become fixed numbers.

        While a handler runs, the doubt goes to its StepResult (`recording`); otherwise it counts for the walk."""
        record = Doubt(names, why, self.current.get("index") if self.current else None, fixed)
        (self._recordings[-1] if self._recordings else self).doubts.append(record)

    def _key(self, item, path):
        index = item.get("index") if isinstance(item, dict) else None
        if index is None and self.current is not None:
            index = self.current.get("index")
        return index, path

    def ask(self, item, path, same_as=None):
        """Record that a handler dealt with the value at `path` of `item`: followed, pinned or left out on purpose.
        With `same_as`, only when the handler dealt with that other path of the item (a rewritten item names its
        values differently). Like doubts, it counts only when the handler's steps are written."""
        here = self._recordings[-1] if self._recordings else self
        if same_as is None or self._key(item, same_as) in here.asked:
            here.asked.add(self._key(item, path))

    def note(self, text):
        """Attach a plain sentence to the item being handled (it goes to the handler's StepResult, `recording`); its
        verdict becomes translatedWithNote."""
        self._recordings[-1].notes.append(text)

    @contextmanager
    def recording(self):
        """Doubts and notes recorded inside the block go to the yielded StepResult instead of the walk. The walk runs
        every handler in one, so a handler's doubts count only when its steps are written."""
        self._recordings.append(StepResult())
        try:
            yield self._recordings[-1]
        finally:
            self._recordings.pop()

    def commit(self, result):
        """The steps of `result` are part of the recipe: its doubts and the items of other bodies it carries count."""
        self.doubts.extend(result.doubts)
        self.asked |= result.asked
        self.copied_items.extend(result.items)

    @property
    def depends(self):
        """Fusion name of a size -> why, for each size a value written as a number depends on (the first reason)."""
        return self._reasons(False)

    @property
    def must_fix(self):
        """The same for the sizes that must become fixed numbers."""
        return self._reasons(True)

    def _reasons(self, fixed):
        found = {}
        for record in self.doubts:
            if record.fixed == fixed:
                for name in record.names:
                    found.setdefault(name, record.why)
        return found

    def add_placer(self, placer):
        """Register the placer of a step being written; it comes after every placer made before it."""
        placer.order = len(self.placers)
        self.placers.append(placer)

    def add_slab(self, slab):
        self.add_placer(slab)
        self.slabs.append(slab)

    def steps_of(self, index):
        """Step ids written for the timeline item at `index` (empty when it made none)."""
        return list(self._ids_by_index.get(index, ()))

    def slabs_of(self, step_id):
        """The slabs of the bodies a step makes: an extrude's own, or a repeat's originals and copies."""
        step = next((s for s in self.steps if s.get("id") == step_id), None)
        found = []
        if step is not None and recipe_kind(step.get("kind")).repeats:
            for of in step.get("of") or []:
                found.extend(self.slabs_of(of))
        found.extend(s for s in self.slabs if s.owner == step_id)
        unique = []
        for slab in found:
            if all(slab is not other for other in unique):
                unique.append(slab)
        return unique

    def add_steps(self, item, result):
        """Write the steps of a StepResult: give each step its id and label, append it to the recipe, make its
        placers, and return the ids.

        Ids: `<kind>_<index>`, then `<kind>_<index>_<n>` for the second and later steps of one item.
        """
        ids = []
        label = str(item.get("name", ""))[:MAX_LABEL]
        made = self._ids_by_index.setdefault(item["index"], [])
        for n, entry in enumerate(result.entries, start=len(made) + 1):
            step = entry.step
            base = "%s_%s" % (step["kind"], item["index"])
            step_id = base if n == 1 else "%s_%d" % (base, n)
            if len(step_id) > MAX_ID:
                step_id = step_id[-MAX_ID:]
            if not entry.repeatable:
                self.not_repeatable.add(step_id)
            step["id"] = step_id
            step["label"] = label
            for maker in entry.placers:
                maker.make(self, step_id, step)
            if entry.picks is not None:
                self.plain_picks[step_id] = entry.picks
            self.written_reads = tuple(dict.fromkeys(self.written_reads + reads_in(step)))
            self.steps.append(step)
            ids.append(step_id)
        made.extend(ids)
        return ids
