"""Round faces of an offset (press pull) in the recipe: a whole pin, boss or bore whose radius changes by the distance.

The facts and checks of such a face are in the shared layer (`design_model/steps/offset_round.py`): the face goes
all the way round, both its ends meet flat faces square to its axis, and the ring stays clear of the other edges of
its end faces. The app (recipe version 17) moves such a face. Here a shared problem becomes a refusal, and a distance
that follows a size is checked over the size range against the same room (`clear_over_range`).
"""
import math

from ...design_model import words
from ...design_model.steps import offset_round as facts
from ...design_model.values import Quantity
from ..result import Refusal
from ..values import stays_positive

# The recipe version whose app moves a round face.
VERSION = 17

UNREADABLE = words.OFFSET_ROUND_UNREAD
NOT_WHOLE = words.OFFSET_ROUND_NOT_WHOLE
MEETS = words.OFFSET_ROUND_MEETS
CLOSES = words.OFFSET_ROUND_CLOSES
RUNS_INTO = words.OFFSET_ROUND_RUNS_INTO
NOT_MEASURED = words.OFFSET_NOT_MEASURED

is_round = facts.is_round
near_point = facts.near_point


def refusal(face, distance, after):
    """The Refusal for a round face the recipe cannot move by `distance`, or None. `after` holds the cylinders Fusion
    left after the step (`rounds_after`). Each refusal has the cause of a curved face that is not copied."""
    found = facts.problem(face, distance, after)
    return None if found is None else Refusal(found.words, cause=found.cause)


def clear_over_range(table, faces, q):
    """True when the radius of every round face moved by the sized distance `q` stays clear of the other edges of its
    end faces (and above zero) over the size range."""
    for face in faces:
        found = facts.whole(face)
        low, high = facts.room(found)
        radius = Quantity(face["radius"]).plus(q.scaled(found.ring.sign))
        if not stays_positive(table, radius.plus(-low)):
            return False
        if math.isfinite(high) and not stays_positive(table, radius.scaled(-1).plus(high)):
            return False
    return True
