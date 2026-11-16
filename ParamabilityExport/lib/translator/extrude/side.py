"""The recipe side of an extrude: its extent, direction, length and taper as the recipe writes them."""
from dataclasses import dataclass
from typing import Optional


@dataclass
class RecipeSide:
    """One side of an extrude as the recipe writes it. `extent` is oneSide, symmetric, through or through-one (a cut
    through all to one side, whose distance is set later). `sign` is the travel along the sketch normal, `distance` the
    length (None for through) and `taper` the lean in degrees, positive leaning the walls in (the opposite of Fusion's
    sign). `q` and `taper_q` are the same length and lean as `Quantity` objects that follow a size; `adjusts` marks a
    side whose length follows the part, `reaches` one that ends on a face. `read` is the side as the shared reader
    gives it (`design_model.steps.extrude.SidePlan`), for the measured checks."""
    extent: str
    sign: int
    distance: Optional[float]
    taper: float
    q: Optional[object] = None
    taper_q: Optional[object] = None
    adjusts: bool = False
    reaches: bool = False
    read: Optional[object] = None
