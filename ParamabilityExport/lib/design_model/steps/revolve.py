"""Which side each angle of a revolve to two sides turns to, read from its measured start face.

Fusion turns a two sided revolve by `angle one` to one side of the sketch and by `angle two` to the other, and does not
say which side is which. The result covers one turn of `angle one + angle two` that starts a number of degrees back
from the sketch: `angle two` back when side one is the right hand turn about the axis, `angle one` back when it is the
other. The start face of the revolve is one of the two end faces of that turn, so the way the material leaves it
(`travel`) tells the two apart. How the travel is measured, and how the result is written, stay with the destination.
"""
from ...geometry import vec

# How far apart (unit vectors) the measured and the expected travel may be and still count as the same.
TRAVEL_TOL = 1e-3


def back_sides(travel, turn, axis, angle_one, angle_two):
    """The sides (1 for `angle one`, 2 for `angle two`) whose angle the turn may start back from the sketch.

    `travel` is the unit direction the material leaves the start face in, `turn` the unit direction the outline moves
    in at the start of a right hand turn about the unit `axis`, both in one frame. The answer is empty when no end face
    of either turn matches the start face, and holds both sides when the start face fits both turns (equal angles, or
    an angle of a quarter turn). The turn then covers from `back` degrees back to `angle one + angle two - back`
    degrees ahead, by the right hand rule about `axis`.
    """
    angles = {1: float(angle_one), 2: float(angle_two)}
    found = set()
    for sense in (1.0, -1.0):
        for side, back in angles.items():
            expected = vec.rotate(vec.scale(turn, sense), axis, -sense * back)
            if vec.length(vec.sub(expected, travel)) < TRAVEL_TOL:
                # Turning the other way from `back` ahead covers the same turn as the right hand way from the other
                # angle back.
                found.add(side if sense > 0 else 3 - side)
    return sorted(found)
