"""How a coil combined with the part. Fusion does not say, so it follows from the bodies the reader measured.

A body the coil made that was not there before is a new body, and its volume must be the coil's own. A body that was
there grows by at most the coil's volume for a join. It shrinks for a cut, but a shrink also fits an intersect that
keeps a coil-sized piece, so only a body that stays larger than the coil can be a cut. Anything else is left out.
"""
from ..result import Refusal
from . import coil_limits as limits


def operation_of(data, volume):
    """`newBody`, `join` or `cut` for a coil of `volume` mm3 (what its section and turns give), or a Refusal."""
    made, before = data.get("made"), data.get("volumes_before")
    if not isinstance(made, list) or len(made) != 1 or not isinstance(before, list):
        return Refusal(limits.OPERATION)
    body = made[0]
    after, token = body.get("volume"), body.get("token")
    if not token or not isinstance(after, (int, float)):
        return Refusal(limits.OPERATION)
    known = {entry.get("token"): entry.get("volume") for entry in before if entry.get("token")}
    limit = volume * (1.0 + limits.VOLUME_TOL)
    if token not in known:
        if abs(after - volume) > limits.VOLUME_TOL * volume:
            return Refusal(limits.NOT_FITTING, cause=limits.CAUSE_OTHER)
        return "newBody"
    prior = known[token]
    if not isinstance(prior, (int, float)):
        return Refusal(limits.OPERATION)
    change = after - prior
    smallest = max(1e-3, 1e-6 * prior)
    if 0 < smallest < change <= limit:
        return "join"
    if change < -smallest and -change <= limit and after > limit:
        return "cut"
    return Refusal(limits.OPERATION, cause=limits.CAUSE_PLACE)
