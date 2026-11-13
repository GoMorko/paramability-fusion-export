"""The plan of one extrude side: how it ends, which way it goes and how long it is."""
from dataclasses import dataclass
from typing import Optional


@dataclass
class SidePlan:
    """One side of an extrude. `extent` is oneSide, symmetric, through or through-one (a cut through all to one side,
    whose distance is set later). `sign` is the travel along the sketch normal, `distance` the length (None for
    through) and `taper` the lean in degrees. `q` and `taper_q` are the same length and lean as `values.Quantity`
    objects that follow a size; `adjusts` marks a side whose length follows the part, `reaches` one that ends on a face."""
    extent: str
    sign: int
    distance: Optional[float]
    taper: float
    q: Optional[object] = None
    taper_q: Optional[object] = None
    adjusts: bool = False
    reaches: bool = False
