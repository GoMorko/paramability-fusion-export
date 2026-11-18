"""Coils (CoilFeature) in the Orca copy: every coil is left out, with the reason and the cause `causes.COIL_SHAPE`.

Fusion's coil carries the wire's section on a plane through the coil's axis, and keeps it so along the helix (a
screw motion): the two flat end faces lie on planes through the axis (`translator/coil/coil_fit.py`). Orca 2.5.1
can sweep a sketch along its Helix feature only with `BRepOffsetAPI_MakePipe` (`SketchEngine::make_sweep`), which
carries the section with a frame that turns about the path:
- a circle drawn square to the helix at its start gives a round tube. Its end faces are square to the helix, so they
  lean by the helix angle against Fusion's, and the rim of an end lies up to the wire radius times the slope
  (pitch over the length of one turn) away: 0.08 mm for a wire of 2 on a coil of 20 with a pitch of 5. The wire is
  also wider along the axis than Fusion's by the wire radius times (1 / cos(helix angle) - 1);
- a circle drawn on the plane through the axis does not stay on such planes: the frame turns about the path by
  about 2 pi times the turns times the sine of the helix angle (Orca's own thread code uses `MakePipeShell` with the
  axis as its fixed binormal for this reason).
Neither is Fusion's coil within 0.02 mm, so no coil is copied.
"""
from . import causes
from .skip import Skip

REASON = ("Orca cannot make this coil the same shape yet: Orca keeps the wire square to its turns, but Fusion keeps "
          "it upright along the middle of the coil, so the ends and the thickness of the wire would differ.")


def coil(ctx, step):
    return Skip(REASON, causes.COIL_SHAPE)


HANDLERS = {"CoilFeature": coil}
