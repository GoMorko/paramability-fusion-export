"""Walk state handed to every handler."""
from .capture import same_body

MAX_ID = 64
MAX_LABEL = 120


class Context:
    """State of one translate() run.

    target: the exported body, {token, name, box, volume_mm3}.
    capture: the whole capture (for up_axis and cross item lookups).
    pending_tools: body token (or name) -> recipe steps that build a body other than the target, not yet placed.
      The Combine handler takes them.
    not_repeatable: ids of steps whose length Fusion recomputes per copy (a handler marks a step with a private
      `_adjusts` key, which `add_steps` removes). Pattern and mirror handlers refuse them as sources.
    """

    def __init__(self, capture):
        self.capture = capture
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
            step["id"] = step_id
            step["label"] = label
            self.steps.append(step)
            ids.append(step_id)
        made.extend(ids)
        return ids
