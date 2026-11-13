"""Tolerances, caps and refusal texts of the sweep path code. Pure: no Fusion imports."""

PLANE_TOL = 1e-4          # the path start must lie this close to the outline's plane (mm), as in the app
SQUARE_TOL_DEG = 0.1      # the path must leave the outline's plane at a right angle within this
STRAIGHT_DEG = 0.01       # a turn below this (degrees) is straight on: the app's own limit for a straight continuation
SMOOTH_JOIN_DEG = 2.0     # the app takes a join next to a curve as smooth up to this turn (degrees)
CORNER_MATCH_TOL = 1e-3   # where the legs of a bend meet, the two ways of finding the corner agree within this (mm)
TOUCH_TOL = 1e-4          # parts of a path closer than this (mm) touch
MAX_SEGMENTS = 64         # segments of a flat path (recipe cap)
MAX_POINTS = 64           # points of a corners path (recipe cap)
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

TURNS_BACK = "The outline keeps one direction along a path that turns back past its plane, which cannot be built."
UNREADABLE = "A curve of the path of this sweep could not be read closely enough to copy."
UNKNOWN_CURVE = "The path of this sweep uses a kind of curve that is not copied yet."
NOT_ONE_CHAIN = "The curves of the path of this sweep do not join end to end into one line."
CLOSED = "The path of this sweep is closed, but its curves do not make one closed line."
CLOSED_3D = "Sweeps along a closed path that bends in 3D are not copied yet."
CLOSED_AT_CORNER = "The outline of this sweep sits on a sharp corner of its closed path."
CLOSED_NOT_SMOOTH = ("The closed path of this sweep cannot be copied closely enough to run smoothly through the "
                     "place where its outline sits.")
CLOSED_TAPER = "Tapered sweeps along a closed path are not copied."
CLOSED_PARALLEL = "Sweeps that keep their outline in one direction along a closed path are not copied."
BOTH_SIDES = "This sweep runs to both sides of its outline, which is not copied yet."
OFF_PLANE = "The path of this sweep does not start on the plane of its outline."
NOT_SQUARE = "The outline is not square to the path at its start."
TURNED_ROUND = "The path of this sweep would leave its outline the other way round."
SHARP_CORNER = "The path of this sweep has a sharp corner."
CORNER_TOO_TIGHT = ("A sharp corner of the path of this sweep is too close to the next one for its outline: the "
                    "outline needs %.2f mm of straight path there and has %.2f mm.")
BENDS_3D = "The path of this sweep bends in 3D in a way that is not copied yet."
TOO_MANY = "The path of this sweep has too many parts to copy."
CROSSES = "The path of this sweep crosses itself."
OVERLAP = ("Two parts of the path pass %.2f mm apart, but the outline reaches %.2f mm from the path, "
           "so the sweep would run into itself.")
TOO_COMPLEX = "The path of this sweep has a curve that is too complex to copy closely enough."
NOT_SKETCH = "The path of this sweep is not made of sketch lines or edges."
