"""Limits and refusal texts of the sweep handler. The path code keeps its own in `path_limits`."""
from .path_limits import TURNS_BACK

ZERO_TOL = 1e-6
VOLUME_RELATIVE_TOL = 0.01
VOLUME_ABSOLUTE_TOL = 1e-3
CENTROID_ON_PATH_TOL = 0.01   # the path runs through the outline's centroid when it starts this close to it (mm)
WHOLE_TURN_TOL = 1e-6 / 360.0  # a twist along a closed path is whole turns within this share of a turn, as in the app
MAX_TWIST_DEG = 3600.0        # the recipe takes a twist up to this either way
MAX_TAPER_STATIONS = 65       # the recipe builds a taper through at most this many places along the path

UNREADABLE = "A setting of this sweep could not be read from Fusion."
PATH_UNREADABLE = "The path of this sweep could not be read from Fusion."
MIXED_PATH = "The path of this sweep mixes sketch curves and body edges, which is not copied yet."
SEVERAL_OUTLINES = "Sweeps that intersect the part with several outlines at once are not copied yet."
SEVERAL_TAPERED = "Tapered sweeps of several outlines at once are not copied yet."
FACE_OUTLINE = "The outline of this sweep is a face of the part."
TWIST_AND_TAPER = "Sweeps that both twist and taper are not copied yet."
TAPER_CURVES = "Tapered sweeps along curves are not copied yet."
TAPER_STATIONS = "Tapered sweeps along a path with so many parts are not copied."
TWIST_CLOSED = "The twist of this sweep along a closed path is not whole turns, which is not copied."
TAPER_CLOSES = "The taper of this sweep would close part of its outline, which is not copied."
TAPER_STEEP = "The taper of this sweep is too steep to copy."
TWIST_LONG = "The twist of this sweep is more than ten turns, which is not copied."
SCALED_OUTLINE = "This sweep scales its outline along the path, which is not copied yet."
PARALLEL_AND_SHAPE = "Sweeps that keep their outline in one direction and also twist or taper are not copied."
RAIL = "Sweeps with a guide rail are not copied yet."
GUIDE_SURFACE = "Sweeps with a guide surface are not copied yet."
GUIDE_SURFACE_LIKELY = ("This sweep likely has a guide surface (Fusion did not give its orientation, twist and taper), "
                        "and sweeps with a guide surface are not copied yet.")
RAIL_UNREADABLE = "The guide rail of this sweep could not be read from Fusion."
PATH_TOO_LONG = "The path of this sweep has more parts than can be read, so it is not copied."
OTHER_KIND = "This kind of sweep is not copied yet."
KEEPS_DIRECTION = TURNS_BACK
PART_OF_PATH = "This sweep covers only part of its path, which is not copied yet."
BOTH_WAYS_TWIST = "This sweep runs both ways round its closed path and twists, which is not copied yet."
NOT_MATCHING = "The result of this sweep does not match its outline and path, so it is not copied yet."
