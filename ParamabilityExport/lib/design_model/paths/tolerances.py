"""Tolerances of the sweep path code: how close is on a plane, square, straight, smooth or touching, and the
limits of a shape that can be built (a mitre, a bend, an overlap). Pure. The caps of a destination (how many parts
its path may have) are not here: the destination gives them in `model.PathOptions`."""

PLANE_TOL = 1e-4          # the path start must lie this close to the outline's plane (mm), as in the app
SQUARE_TOL_DEG = 0.1      # the path must leave the outline's plane at a right angle within this
STRAIGHT_DEG = 0.01       # a turn below this (degrees) is straight on: the app's own limit for a straight continuation
SMOOTH_JOIN_DEG = 2.0     # the app takes a join next to a curve as smooth up to this turn (degrees)
CORNER_MATCH_TOL = 1e-3   # where the legs of a bend meet, the two ways of finding the corner agree within this (mm)
TOUCH_TOL = 1e-4          # parts of a path closer than this (mm) touch
MAX_TURN_DEG = 179.5      # a bend turning more than this cannot be a rounded corner
MAX_MITRE_DEG = 160.0     # a sharp corner between two lines turning more than this has no usable mitre, as in the app
ARC_SAMPLE_DEG = 3.0
MAX_OVERLAP_SAMPLES = 1500   # samples along a path when two far apart parts are checked for coming close
OVERLAP_STEP_SHARE = 0.5     # samples are at most this share of the outline's reach apart
OVERLAP_CORNER_DEG = 5.0     # a turn above this (degrees) at a vertex is a corner, whose mitre overlaps its arms
OVERLAP_MAX_CORNER_DEG = 160.0
OVERLAP_CLEAR_SHARE = 0.95   # parts closer than this share of twice the reach overlap
CURVATURE_SAMPLES = 129   # readings along a fitted spline when its tightest bend is looked for
REACH_SHARE = 1 - 1e-6    # an outline reaching this share of a bend's radius reaches its centre
MIN_RISE = 0.05           # an outline kept in one direction needs the path to move along its normal at least this much
LINE_BEND_RADIUS = 1.0    # the (unused) bend radius written for a corners path of two points
