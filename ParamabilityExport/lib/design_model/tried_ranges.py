"""The ranges the size probe's tries keep: where Fusion did not rebuild the design at a value it tried, where a sketch
the copy follows makes a different outline, and where the part came apart into several separate pieces.

`built_ranges` cuts a free size's range on each side to the farthest value that built, kept the outline and stayed in
one piece, since a form should not offer a value the design cannot take. Only a failure in a step the part is built
from counts (`part_step`, by the step's timeline position, since names repeat across components). A try where such a
step showed a new warning counts as one that did not build (the probe keeps it in `Motion.spans` `failed`, and in
`warned` too): Fusion may have built another shape there than the copy. So does a try where such a step that is in
error at the start built (`failed`, and `cleared` too): the copy leaves that step out, so it lacks what the step makes
there. Where a sketch the copy follows makes a
different outline (`Motion.spans` `kept`, `probe.build.outline_windows`), the range stops at the farthest value tried
that kept it, and where Fusion built the part in several separate pieces (`Motion.spans` `split`, `probe.pieces`), at
the farthest value tried that kept it in one. These are facts of the tries, so the recipe translator and the probe both
read them here. An end the person typed is kept.
"""
from ..geometry.tolerances import SAME_SIZE
from ..params.size_table import Cut
from ..sketch_values import coverage


def part_step(capture):
    """A test `mine(step)` for a step that failed or showed a new warning in a try (`Motion.spans` `failed`): True when
    it is a timeline item the part is built from: an item of the target's component, a step that made a tool body of
    a Combine, or an item with `body_states`. `step` is `(position, name)`, or a name alone as records written before
    positions were kept give it.

    Fusion names steps per component, so a name such as "Chamfer1" can belong to the part and to another component
    at once. A step with a timeline position is judged by that position (the capture item `index`). A name alone, or
    a position that no capture item has, counts as the part's when an item the part is built from has that name, also
    when an item outside the part has it too: a doubt cuts the range, it never keeps a value Fusion could not build. A
    failure with no step (the design did not recompute at all), or without a capture, counts for the part."""
    if capture is None:
        return lambda step: True
    mine_at, known_at, mine_names = set(), set(), set()
    for item in capture.get("items") or ():
        owned = item.get("in_target_component") or item.get("helper_of") or item.get("body_states")
        at = item.get("index")
        if type(at) is int:
            known_at.add(at)
            if owned:
                mine_at.add(at)
        if owned:
            mine_names.add(item.get("name"))

    def mine(step):
        at, name = step if isinstance(step, (list, tuple)) else (None, step)
        if not name and at is None:
            return True
        if type(at) is int and at in known_at:
            return at in mine_at
        return name in mine_names
    return mine


def tried_step(entry):
    """`(position, name)` of the step of a `Motion.spans` `failed` entry: `[value, name]`, or `[value, name,
    position]` when the try gave the step's timeline position."""
    return (entry[2] if len(entry) > 2 else None, entry[1])


def _cut_past(table, entry, span, tries):
    """`(low, high, found)`: the range of a free size cut on each side where one of `tries` (`(value, what)` each) lies
    past the farthest value that built (`span` as `Motion.spans`), with `(value, what)` of the nearest one behind each
    cut end. An end the person typed is kept."""
    size = table.sizes[entry.size_name]
    typed_low, typed_high = table.typed_ends(entry.name)
    low, high, found = size["min"], size["max"], {}
    below = [f for f in tries if f[0] < span["low"] - SAME_SIZE]
    past = [f for f in tries if f[0] > span["high"] + SAME_SIZE]
    if not typed_low and below:
        low, found["low"] = max(low, span["low"]), max(below, key=lambda f: f[0])
    if not typed_high and past:
        high, found["high"] = min(high, span["high"]), min(past, key=lambda f: f[0])
    return low, high, found


def failure_cut(table, entry, span, mine):
    """`(low, high, found)`: the range of a free size cut on each side where Fusion did not rebuild with only that
    size changed (`span` as `Motion.spans`), past the farthest value that built; `mine(step)` says whether a failed
    step counts (`part_step`). An end the person typed is kept; `found` holds `(value, step)` of the nearest failure
    behind each cut end."""
    return _cut_past(table, entry, span, [(f[0], f[1]) for f in span.get("failed") or () if mine(tried_step(f))])


def split_cut(table, entry, span):
    """`(low, high, found)`: the range of a free size cut on each side where Fusion built the part in several separate
    pieces with only that size changed (`span` `split`), past the farthest value that built in one piece. The app
    builds a part only in one piece. An end the person typed is kept; `found` holds `(value, pieces)` of the nearest
    such try behind each cut end."""
    return _cut_past(table, entry, span, [(value, count) for value, count in span.get("split") or ()])


def outline_cut(table, entry, span):
    """`(low, high, changed)`: the range cut to the values a sketch the copy follows kept its outline at (`span`
    `kept`, an end None where nothing changed), with `(value, sketch)` of the nearest different outline behind each
    cut end. An end the person typed is kept."""
    size = table.sizes[entry.size_name]
    kept, changed = span.get("kept") or (None, None), span.get("changed") or ()
    typed = table.typed_ends(entry.name)
    low, high, found = size["min"], size["max"], {}
    now = size["value"]
    for side, at, sign in (("low", 0, -1), ("high", 1, 1)):
        if kept[at] is None or typed[at]:
            continue
        past = [(v, s) for v, s in changed if (v - kept[at]) * sign > SAME_SIZE]
        if not past:
            continue
        found[side] = min(past, key=lambda c: abs(c[0] - now))
        if side == "low":
            low = max(low, kept[at])
        else:
            high = min(high, kept[at])
    return low, high, found


def _marked(found, span, key):
    """The ends of `found` (side to `(value, step)` of `failure_cut`) whose try is listed under `key` of the span
    (`warned` or `cleared`)."""
    listed = {(f[0], f[1]) for f in span.get(key) or ()}
    return {side: f for side, f in found.items() if tuple(f) in listed}


def built_ranges(table, motion, capture=None):
    """`{Fusion name: Cut}` of the free sizes whose range goes past a value at which Fusion did not rebuild the design
    (`Motion.spans`: a value tried with only that size changed), at which a followed sketch makes a different outline
    (`outline_cut`), or at which the part came apart into several pieces (`split_cut`). On that side the range stops at
    the farthest value that built in one piece and kept the outline. An end
    the person typed is kept, and a range that would shrink to the value now is left as it is (the size could not be
    measured). A failure in a step the part is not built from (`capture` items of other components) cuts nothing: the
    part itself may rebuild there."""
    out = {}
    mine = part_step(capture)
    for e in table.entries:
        span = coverage.span(motion, e.name)
        size = table.sizes.get(e.size_name) if e.size_name else None
        if not span or not size or "min" not in size:
            continue
        low, high, found = failure_cut(table, e, span, mine)
        warned, cleared = (_marked(found, span, key) for key in ("warned", "cleared"))
        found = {side: f for side, f in found.items() if side not in warned and side not in cleared}
        kept_low, kept_high, changed = outline_cut(table, e, span)
        split_low, split_high, split = split_cut(table, e, span)
        cut = (Cut(low, high, found, warned=warned, cleared=cleared).meet(Cut(kept_low, kept_high, changed=changed))
               .meet(Cut(split_low, split_high, split=split)))
        if (cut[0], cut[1]) != (size["min"], size["max"]) and cut[1] - cut[0] > SAME_SIZE:
            out[e.name] = cut
    return out
