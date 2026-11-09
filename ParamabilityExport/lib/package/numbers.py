"""Small number helpers shared by the translator, the probe and the package writer."""


def round9(value):
    """`value` rounded to 9 decimals, with no negative zero."""
    return round(value, 9) + 0.0


def is_number(value):
    """True for an int or float that is not a bool."""
    return isinstance(value, (int, float)) and not isinstance(value, bool)
