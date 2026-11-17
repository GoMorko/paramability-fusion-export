"""What the export code asks of the parameter store: the members every store has, and the timeline controls a store
for a design with a timeline adds. `fusion_reader.rows.DesignParameterStore` is the Fusion store; tests use fakes."""
from typing import Protocol

# The timeline controls. A store that works on a design with no timeline leaves them out, and the code that uses
# one goes on without it (see `timeline_control`).
TIMELINE_CONTROLS = (
    "timeline_health", "turn_on", "keep_marker", "roll_marker", "unroll_marker", "suppress_items", "unsuppress_items",
    "warning_entries")


class ParameterStore(Protocol):
    """The user parameters of one design, as the export code reads and changes them. Expressions are text; values are
    Fusion's own units (cm, rad).

    saved_expressions() / current_expressions(): {name: expression} now; the first is taken before any change.
    set_expression(name, text): set one parameter; raises when Fusion refuses it.
    set_expressions({name: text}): set all in one change with one rebuild (`apply.set_all`); True when it took them
      all, False with nothing changed when it cannot or Fusion refused one.
    recompute(): rebuild the design; False when Fusion reports it failed.
    read_value(name): the value of one parameter.
    error_items(): names of the timeline items in error.
    error_entries(): {key: name} of the same items; the key tells apart items that share a name. The Fusion store
      keys an item by its timeline position (`apply.position`), the `index` of its capture item.
    return_marker(): put the timeline marker back where the store keeps it: "" when it was there or cannot be read,
      "moved" when it went back, "lost" when it would not.
    marker_holds(): False when the marker sits before the position the tries need (a read would miss items).

    The timeline controls (`TIMELINE_CONTROLS`) are optional, so a fake without a timeline stays small:
    timeline_health(): `{ index, name, type, health, message, suppressed }` of each step before the marker; raises
      when the timeline cannot be read. Without it the end check lists only the steps in error.
    turn_on(steps): turn back on the (index, name) steps that read suppressed; the names that stayed off.
    keep_marker(): move the marker back where the store holds it after a read left it earlier; True when it is there.
      Without it a row read cannot leave the marker before an outline face's step (`ProbeRun`).
    roll_marker(position) / unroll_marker(): hold the marker at `position` for the tries, then put it back. Without
      it the marker is not rolled.
    suppress_items(items) / unsuppress_items(): turn timeline items off for the tries and on again. Without it
      nothing is suppressed.
    warning_entries(): {key: name} of the timeline items before the marker whose health is warning, keyed as
      `error_entries`. Without it no warning is read.
    """

    def saved_expressions(self): ...

    def current_expressions(self): ...

    def set_expression(self, name, expression): ...

    def set_expressions(self, expressions): ...

    def recompute(self): ...

    def read_value(self, name): ...

    def error_items(self): ...

    def error_entries(self): ...

    def return_marker(self): ...

    def marker_holds(self): ...


def timeline_control(store, name):
    """The method `name` (one of `TIMELINE_CONTROLS`) of `store`, or None when the store has no timeline controls."""
    if name not in TIMELINE_CONTROLS:
        raise ValueError(f"{name} is not a timeline control of the parameter store")
    member = getattr(store, name, None)
    return member if callable(member) else None
