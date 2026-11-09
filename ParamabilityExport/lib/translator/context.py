"""Walk state handed to every handler."""
from .capture import same_body
from .follow import Slab
from .values import reads_in

MAX_ID = 64
MAX_LABEL = 120
MAX_REASON = 200


class Context:
    """State of one translate() run.

    target: the exported body, {token, name, box, volume_mm3}.
    capture: the whole capture (for up_axis and cross item lookups).
    pending_tools: body token (or name) -> recipe steps that build a body other than the target, not yet placed.
      The Combine handler takes them.
    not_repeatable: ids of steps whose length Fusion recomputes per copy (a handler marks a step with a private
      `_adjusts` key, which `add_steps` removes). Pattern and mirror handlers refuse them as sources.
    table: the size table (lib/params) whose sizes the feature values may follow, or None for a recipe with plain
      numbers only.
    depends: Fusion name of a size -> plain reason, for each size that a value written as a number depends on.
      The driver turns these sizes into fixed numbers and walks again.
    slabs: the extrude steps written so far (follow.Slab), for picks and reaches that follow sizes. A handler hands
      one over in a step's private `_slab` key: { on, extent, length, profile }.
    written_reads: Fusion names of the sizes that the steps written so far read.
    plain_picks: round or bevel step id -> { near, reads }: its edges as measured points and the sizes its pick
      follows. A handler hands it over in the private `_plain` key; patterns and mirrors copy these points.
    """

    def __init__(self, capture, table=None):
        self.capture = capture
        self.table = table
        self.depends = {}
        self.slabs = []
        self.written_reads = ()
        self.plain_picks = {}
        self.target = capture["target"]
        self.steps = []
        self.pending_tools = {}
        self.not_repeatable = set()
        self._ids_by_index = {}
        self._notes = []
        self.current = None

    def is_target(self, body):
        return same_body(body, self.target)

    def note(self, text):
        """Attach a plain sentence to the item being handled; its verdict becomes translatedWithNote."""
        self._notes.append(text)

    def fix(self, names, why):
        """Record that the sizes `names` (Fusion names) cannot follow: a value that reads them stays a number."""
        for name in names:
            if name not in self.depends:
                self.depends[name] = ("%s stays fixed: %s." % (name, why))[:MAX_REASON]

    def take_notes(self):
        notes, self._notes = self._notes, []
        return notes

    def steps_of(self, index):
        """Step ids written for the timeline item at `index` (empty when it made none)."""
        return list(self._ids_by_index.get(index, ()))

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
            if slab is not None:
                self.slabs.append(Slab(step_id, slab["on"], slab["extent"], slab["length"], slab["profile"]))
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
