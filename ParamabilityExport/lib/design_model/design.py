"""The design as both walks read it: one `ResolvedStep` per timeline item.

`read(capture, table, motion)` resolves every item of a capture for the body that a walk builds (`capture["target"]`,
through the splits of `chain`). A resolved step holds what any output needs to know about the item before a handler
copies it:

- `raw`: the item as the capture holds it, and `item`: the item with the measures of the body that the walk builds
  before the split that made the target (`roles.seen_before_split`), else the same item;
- `role`: what the item is for that body (`roles.Role`), with the body before and after it;
- `outside`, `helper`: the item is of another component, and it was read in that component's coordinates for the tool
  body of a Combine (`helper_of`);
- `problems`: what about the item cannot be read (`UNREAD`, `FAILS`, `BODIES_UNREAD`), each a `problem.Problem`;
- `brought`: the item with the geometry of other components that it can use as its own brought in
  (`borrowed.bring_in`, then `refs.bring_in`), and `foreign`, `old_export`, `why_foreign` about what stays foreign;
- `facts`: what the shared reader of the step's kind (`step_kinds.StepType.facts`) reads from the brought in data
  alone (`FACT_READERS`), else None. A handler reads its step's facts from its own reader call, since a handler also
  runs on items that no walk resolved (the sources of a pattern, the steps of a tool body);
- `events`: the doubts, notes and followed components that bringing in recorded. They are not on any translation
  yet: a walk that copies the step replays them (`replay`) where it brings the step in, so a step that is left out
  keeps none of them. `error` is the exception that bringing in raised, if any; `replay` raises it again.

These are facts only. Each output decides from them whether a step is copied, left out or stops the copy, and words
its own answer. Pure: it reads capture dicts only.
"""
from ..capture_model import lineage, step_kinds
from ..capture_model.capture import outside_component
from . import borrowed, refs, roles, words
from .problem import Problem
from .steps import finish

# What about an item cannot be read.
UNREAD, FAILS, BODIES_UNREAD = "unread", "failsInFusion", "bodiesUnread"
_PROBLEMS = {UNREAD: words.STEP_UNREAD, FAILS: words.STEP_FAILS, BODIES_UNREAD: words.BODIES_UNREAD}
# The roles of the steps of the body's component: only these are brought in.
_OWN = (roles.BUILDS, roles.HELPER)
_DOUBT, _NOTE, _FOLLOW = "doubt", "note", "follow"
# The shared step readers that give facts from the data of a step alone, by `step_kinds.StepType.facts`.
FACT_READERS = {step_kinds.ROUND_SETS: finish.round_sets, step_kinds.CHAMFER_SETS: finish.chamfer_sets}
_NOT_YET = object()


class Tally:
    """A `recorder.Recorder` that keeps what is recorded on it as events, in order, for a later `replay`."""

    def __init__(self, capture, table=None, motion=None, cache=None):
        self.capture, self.table, self.motion = capture, table, motion
        self.cache = {} if cache is None else cache
        self.events = []

    def doubt(self, names, why):
        self.events.append((_DOUBT, (names, why)))

    def note(self, text):
        self.events.append((_NOTE, (text,)))

    def follow_component(self, component):
        self.events.append((_FOLLOW, (component,)))


class ResolvedStep:
    """One timeline item as the shared layer resolves it (see the module text). `index`, `name` and `type` are the
    item's. `role` is None for an item resolved without a body (`resolve` with no role)."""

    __slots__ = ("index", "name", "type", "raw", "item", "role", "outside", "helper", "problems", "brought", "foreign",
                 "old_export", "why_foreign", "events", "error", "_facts")

    def __init__(self, raw, item, role, brought, events, error):
        self.index, self.name, self.type = item.get("index"), item.get("name", ""), item.get("type", "")
        self.raw, self.item, self.role = raw, item, role
        self.outside = outside_component(item)
        self.helper = bool(item.get("helper_of"))
        self.problems = tuple(Problem(code, _PROBLEMS[code]) for code in _problem_codes(item))
        self.brought, self.events, self.error = brought, tuple(events), error
        data = data_of(brought)
        self.foreign = refs.is_foreign(data)
        self.old_export = self.foreign and refs.from_old_export(brought)
        self.why_foreign = refs.why_foreign(brought) if self.foreign else None
        self._facts = _NOT_YET

    @property
    def facts(self):
        """The facts of the step's kind (`FACT_READERS`) from the brought in data, read once; None for a kind
        without such a reader."""
        if self._facts is _NOT_YET:
            spec = step_kinds.step_type(self.type)
            reader = FACT_READERS.get(spec.facts) if spec is not None else None
            self._facts = None if reader is None else reader(data_of(self.brought))
        return self._facts

    @property
    def data(self):
        """The data of the item as the walk reads it, {} when it has none."""
        return data_of(self.item)

    def problem(self, code):
        """The `Problem` of `code` the item has, else None."""
        return next((p for p in self.problems if p.code == code), None)

    def has(self, code):
        return self.problem(code) is not None


def data_of(item):
    """The data dict of an item, {} when it has none."""
    data = item.get("data")
    return data if isinstance(data, dict) else {}


def _problem_codes(item):
    found = []
    if data_of(item).get("read_error"):
        found.append(UNREAD)
    if item.get("health") == "error":
        found.append(FAILS)
    if item.get("bodies_after") is None:
        found.append(BODIES_UNREAD)
    return found


def _bring_in(item, tally):
    """`(brought item, error)`: the item with the geometry of other components brought in, recorded on `tally`."""
    try:
        return refs.bring_in(borrowed.bring_in(item, tally)), None
    except Exception as error:  # raised again where the walk brings the step in (`replay`)
        del tally.events[:]
        return item, error


def resolve(item, ctx, role=None, raw=None):
    """The `ResolvedStep` of `item`. Bringing in reads the table, the capture, the motion file and the cache of `ctx`
    (a `recorder.Recorder`) and records nothing on it: the doubts and notes wait in `events`. `role` is the item's
    `roles.Role`; with None the item is a step of the body's component (a step of a tool body), and it is brought
    in. `raw` is the item as the capture holds it, when `item` is a view of it with the measures of another body."""
    tally = Tally(ctx.capture, ctx.table, ctx.motion, ctx.cache)
    if role is None or role.kind in _OWN:
        brought, error = _bring_in(item, tally)
    else:
        brought, error = item, None
    return ResolvedStep(item if raw is None else raw, item, role, brought, tally.events, error)


def read(capture, table=None, motion=None, chain=None, cache=None):
    """The `ResolvedStep` of each item of `capture`, in timeline order, for a walk that builds `capture["target"]`.
    `chain` is the `lineage` chain the target comes through (None: `lineage.of(capture)`; a walk of a tool body
    gives its own). `table`, `motion` and `cache` are those of the translation (`recorder.Recorder`)."""
    target = capture.get("target")
    chain = lineage.of(capture) if chain is None else chain
    tally = Tally(capture, table, motion, cache)
    found = []
    for raw in capture.get("items") or []:
        item = roles.seen_before_split(raw, target, chain)
        found.append(resolve(item, tally, roles.role_of(item, target, chain), raw))
    return found


def replay(step, ctx):
    """Record on `ctx` (a `recorder.Recorder`) the doubts, notes and followed components that bringing `step` in
    recorded, in order. Raises the error that bringing in raised."""
    if step.error is not None:
        raise step.error
    for kind, args in step.events:
        if kind == _DOUBT:
            ctx.doubt(*args)
        elif kind == _NOTE:
            ctx.note(*args)
        else:
            ctx.follow_component(*args)
