"""Walk state handed to every handler.

A handler reports what it cannot follow in one way: `doubt(names, why)` for sizes a value of its steps cannot follow,
and `note(text)` for a plain remark on its item. Both land in the handler's StepResult (`recording`), so they count
only when the walk writes its steps.
"""
from contextlib import contextmanager

from .gaps import gap_measures, stops as gap_records
from ..capture_model import lineage as body_lineage, tool_items
from ..capture_model.capture import same_body
from .result import Doubt, StepResult
from ..capture_model.step_kinds import recipe_kind
from .values import reads_in

MAX_ID = 64
MAX_LABEL = 120


class Context:
    """State of one translate() run.

    target: the body this walk builds, {token, name, box, volume_mm3}: the exported body, or a tool body in a child.
    capture: the capture this walk reads (for up_axis and cross item lookups). In a child, `items` are the items that
      made the tool.
    timeline: every item of the design, also in a child.
    handlers: capture type -> handler.
    component: the token of the component a child's body lives in, when a tool from another component led to it; None
      while the walk is in the exported body's component.
    depth: how many tools deep this walk is, 0 for the exported body.
    outer: the context of the walk that holds this tool, None for the exported body. A tool step can reach to a face
      only that walk knows.
    id_prefix: starts the id of every step of this walk.
    used_tools: keys (`tool_key`) of the tool bodies an earlier Combine used up. Fusion removes such a body.
    entries_by_index: timeline index -> the `Entry` records written for that item.
    not_repeatable: ids of steps whose length Fusion recomputes per copy (`Entry.repeatable`). Pattern and mirror
      handlers refuse them as sources.
    table: the size table whose sizes the feature values may follow, or None for a recipe with plain
      numbers only.
    doubts: the `result.Doubt` records that count for the walk, in order (`doubt`, `commit`). `depends` and
      `must_fix` read them by size; the driver turns the sizes of `must_fix` into fixed numbers and walks again.
    copied_items: the capture items whose steps are part of the recipe (the audit reads the sizes behind them).
    follows: `(token, name)` of the other components whose sizes the written steps follow (`follow_component`).
    asked: `(item index, params path)` of every value the handlers of the copied items dealt with (`ask`).
    placers: the placers of the steps written so far, in the order they were made (faces/placer.py), for picks and reaches
      that follow sizes. The placer makers of each step's `Entry` add them (`add_placer`).
    slabs: the extrude slabs among them (slabs.Slab), the originals and the pattern or mirror copies (`add_slab`).
    written_reads: Fusion names of the sizes that the steps written so far read.
    motion: the probe's motion file (`sketch_values.motion.Motion`), `sketch_values.motion.OPTIMISTIC`, or None. With a motion file the
      sketch values follow sizes (sketch/sketch_motion.py); otherwise they are written as numbers.
    plain_picks: round or bevel step id -> `Entry.picks`; patterns and mirrors copy these points.
    gaps: the steps this walk left out (`stops.Gap`), in order, with those of the tools it wrote (`commit`).
    cache: results that depend on the capture alone, shared by every walk of one translation (one translation walks
      the capture many times). Handlers keep their own entry under their module name.
    lineage: `[(index, parent)]` of the splits the target comes through (lineage.py), for the walk of the exported
      body only: before each split the walk builds the body it split.
    """

    def __init__(self, capture, table=None, motion=None, cache=None, handlers=None):
        self.capture = capture
        self.timeline = capture["items"]
        self.handlers = handlers or {}
        self.component = None
        self.depth = 0
        self.outer = None
        # A walk that only names the steps the copy cannot hold: its stops become gaps and it has no gap cap.
        self.diagnose = False
        self.id_prefix = ""
        self.cache = {} if cache is None else cache
        self.table = table
        self.motion = motion
        self.doubts = []
        self.gaps = []
        self._recordings = []
        self.placers = []
        self.slabs = []
        self.written_reads = ()
        self.plain_picks = {}
        self.target = capture["target"]
        self.lineage = []
        self.steps = []
        self.used_tools = set()
        self.entries_by_index = {}
        self.copied_items = []
        self.follows = set()
        self.asked = set()
        self.not_repeatable = set()
        # item index of a round drawn into an earlier extrude's outline (`finish._slot_outline`) -> that step's id
        self.folded = {}
        self._ids_by_index = {}
        self._tool_ids_by_index = {}
        self._written_at = []
        self.current = None

    def child(self, body, id_prefix, items=(), depth=None):
        """The context of a walk that builds the tool `body` from `items` on its own. It has its own steps, placers
        and doubts, and shares the table, the motion file, the cache and the handlers."""
        found = Context(dict(self.capture, target=body, items=list(items)), self.table, self.motion, self.cache,
                        self.handlers)
        found.timeline = self.timeline
        found.outer = self
        found.diagnose = self.diagnose
        found.id_prefix = id_prefix
        found.depth = self.depth + 1 if depth is None else depth
        found.component = tool_items.component_token(body) if tool_items.is_foreign_tool(body) else self.component
        return found

    def enter(self, item):
        """The walk reaches `item`: remember what is written so far, for `as_of`."""
        self.current = item
        self._written_at.append((item.get("index"), self.placers[:], self.slabs[:], self.written_reads))

    @contextmanager
    def as_of(self, item):
        """Inside the block, `item` is the current item and the placers, slabs and sizes read are those written before
        the walk reached it."""
        saved = self.current, self.placers, self.slabs, self.written_reads
        placers, slabs, reads = next(((p, s, r) for index, p, s, r in self._written_at if index >= item["index"]),
                                     (self.placers, self.slabs, self.written_reads))
        self.current, self.placers, self.slabs, self.written_reads = item, placers[:], slabs[:], reads
        try:
            yield
        finally:
            self.current, self.placers, self.slabs, self.written_reads = saved

    def is_target(self, body):
        """`body` is the body this walk builds: the target, or at the current item the body of the lineage."""
        if same_body(body, self.target):
            return True
        if not self.lineage or self.current is None:
            return False
        return any(same_body(body, held) for held in self.lineage_at(self.current.get("index", 0)))

    def lineage_at(self, index):
        """`(before, after)`: the body this walk builds just before and just after the item at `index`."""
        return body_lineage.at(self.lineage, self.target, index)

    def doubt(self, names, why, fixed=False, cut=None):
        """Record that a value cannot follow the sizes `names` (Fusion names), so it is written as its number. `why`
        ends the reason. The driver keeps these sizes free with a warning (`translate`); with `fixed` the value would
        make the recipe unusable while they stay free, so they become fixed numbers.

        While a handler runs, the doubt goes to its StepResult (`recording`); otherwise it counts for the walk."""
        record = Doubt(names, why, self.current.get("index") if self.current else None, fixed, cut)
        (self._recordings[-1] if self._recordings else self).doubts.append(record)

    def follow_component(self, component):
        """Record that a value follows the sizes of another component: `component` is its `{ token, name }` record or
        its name. Recorded like `doubt`, so it counts only when the handler's steps are written."""
        if isinstance(component, str):
            component = {"name": component}
        if isinstance(component, dict) and (component.get("name") or component.get("token")):
            (self._recordings[-1] if self._recordings else self).follows.add(
                (component.get("token") or "", component.get("name") or ""))

    def doubted(self):
        """Fusion names of the sizes marked so far (a doubt without a cut), in this handler and in the walk."""
        records = self.doubts + (self._recordings[-1].doubts if self._recordings else [])
        return {name for record in records if not record.cut for name in record.names}

    def cut(self, ranges, why):
        """Record that a value works only while the sizes stay inside `ranges` ({Fusion name: (min, max)}): the driver
        cuts their ranges to those values (`cuts`). Recorded like `doubt`."""
        self.doubt(list(ranges), why, cut=ranges)

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

    def replay(self, recorded, doubts=True):
        """Record again what a `recording` block kept apart: the values it dealt with and, with `doubts`, its doubts
        and notes. A handler tries one way to follow a value this way and keeps it only when it worked."""
        here = self._recordings[-1] if self._recordings else self
        here.asked |= recorded.asked
        here.follows |= recorded.follows
        if doubts:
            here.doubts.extend(recorded.doubts)
            if self._recordings:
                here.notes.extend(recorded.notes)

    def commit(self, result):
        """The steps of `result` are part of the recipe: its doubts and the items of other bodies it carries count."""
        self.doubts.extend(result.doubts)
        self.asked |= result.asked
        self.follows |= result.follows
        self.copied_items.extend(result.items)
        self.gaps.extend(result.gaps)

    def leave_out(self, item, reason, depends_on=(), picks=False, cause=None):
        """Record `item` as a gap of this walk, after the steps written so far; returns the `gaps.stops.Gap`. `picks`
        says it is a gap only because it picks, or may pick, faces of earlier gaps. `cause` is its `gap_hints` cause."""
        before, after = gap_measures.measures(self, item)
        gap = gap_records.Gap(gap_records.gap_id(self, item), item, reason, depends_on,
                              [step["id"] for step in self.steps], before, after, picks, cause)
        self.gaps.append(gap)
        return gap

    def gap_of(self, index):
        """The gap of this walk recorded for the timeline item at `index`, or None."""
        return next((gap for gap in self.gaps if gap.index == index), None)

    @property
    def depends(self):
        """Fusion name of a size -> why, for each size a value written as a number depends on (the first reason)."""
        return self._reasons(False)

    @property
    def must_fix(self):
        """The same for the sizes that must become fixed numbers."""
        return self._reasons(True)

    @property
    def cuts(self):
        """Fusion name of a size -> (min, max) its range is cut to (`cut`), the narrowest of all records."""
        found = {}
        for record in self.doubts:
            for name, (low, high) in (record.cut or {}).items():
                was = found.get(name, (low, high))
                found[name] = (max(low, was[0]), min(high, was[1]))
        return found

    @property
    def cut_causes(self):
        """Fusion name of a size -> {(min, max) it was cut to: why} for each `cut` record that names it."""
        found = {}
        for record in self.doubts:
            for name, ends in (record.cut or {}).items():
                found.setdefault(name, {})[tuple(ends)] = record.why
        return found

    def _reasons(self, fixed):
        found = {}
        for record in self.doubts:
            if record.fixed == fixed and not record.cut:
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

    def written_for(self, index):
        """Step ids written for the timeline item at `index` at any depth, also inside tool steps."""
        return self.steps_of(index) + self._tool_ids_by_index.get(index, [])

    def item_of_step(self, step_id):
        """The timeline item that wrote the step `step_id` in this walk or inside one of its tool steps, or None."""
        for index, ids in list(self._ids_by_index.items()) + list(self._tool_ids_by_index.items()):
            if step_id in ids:
                return next((item for item in self.timeline if item.get("index") == index), None)
        return None

    def wrote_after(self, index):
        """True when a timeline item after `index` wrote steps in this walk."""
        return any(at > index and ids for at, ids in self._ids_by_index.items())

    def credit(self, index, step_id):
        """The step `step_id` carries the values of the timeline item at `index`, though another item wrote it."""
        self._tool_ids_by_index.setdefault(index, []).append(step_id)

    def set_aside(self):
        """A child walk that takes over everything written so far; this walk starts again with nothing written."""
        held = self.child(self.target, self.id_prefix, depth=self.depth + 1)
        held.steps, self.steps = self.steps, []
        held.placers, self.placers = self.placers, []
        held.slabs, self.slabs = self.slabs, []
        held.plain_picks, self.plain_picks = self.plain_picks, {}
        held.not_repeatable, self.not_repeatable = self.not_repeatable, set()
        held.entries_by_index, self.entries_by_index = self.entries_by_index, {}
        held._ids_by_index, self._ids_by_index = self._ids_by_index, {}
        held._tool_ids_by_index, self._tool_ids_by_index = self._tool_ids_by_index, {}
        return held

    def join_walk(self, child):
        """A tool step of the walk `child` is written: the ids of its steps count for the items that made them."""
        for index in set(child._ids_by_index) | set(child._tool_ids_by_index):
            self._tool_ids_by_index.setdefault(index, []).extend(child.written_for(index))

    def placers_of(self, step_id):
        """The placers of the bodies a step makes: an extrude's slab, a tool's placer, or a repeat's originals and
        copies."""
        step = next((s for s in self.steps if s.get("id") == step_id), None)
        found = []
        if step is not None and recipe_kind(step.get("kind")).repeats:
            for of in step.get("of") or []:
                found.extend(self.placers_of(of))
        found.extend(p for p in self.placers if getattr(p, "owner", None) == step_id)
        unique = []
        for placer in found:
            if all(placer is not other for other in unique):
                unique.append(placer)
        return unique

    def add_steps(self, item, result):
        """Write the steps of a StepResult: give each step its id and label, append it to the recipe, make its
        placers, and return the ids.

        Ids: `<kind>_<index>`, then `<kind>_<index>_<n>` for the second and later steps of one item. An `Entry` with an
        id keeps it: other steps may name it already. A written entry keeps its id and label when it is written again.
        """
        if result.wraps_body is not None:
            result.entries.insert(0, result.wraps_body(self))
            result.wraps_body = None
        ids = []
        name = str(item.get("name", ""))
        made = self._ids_by_index.setdefault(item["index"], [])
        self.entries_by_index.setdefault(item["index"], []).extend(result.entries)
        for n, entry in enumerate(result.entries, start=len(made) + 1):
            step = entry.step
            base = "%s%s_%s" % (self.id_prefix, step["kind"], item["index"])
            step_id = entry.step_id or (base if n == 1 else "%s_%d" % (base, n))
            if len(step_id) > MAX_ID:
                step_id = step_id[-MAX_ID:]
            if not entry.repeatable:
                self.not_repeatable.add(step_id)
            step["id"] = step_id
            step["label"] = (entry.label or name)[:MAX_LABEL]
            entry.step_id, entry.label = step_id, step["label"]
            for maker in entry.placers:
                maker.make(self, step_id, step)
            if entry.picks is not None:
                self.plain_picks[step_id] = entry.picks
            self.written_reads = tuple(dict.fromkeys(self.written_reads + reads_in(step)))
            self.steps.append(step)
            ids.append(step_id)
        made.extend(ids)
        return ids
