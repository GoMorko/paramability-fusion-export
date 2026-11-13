"""The error every expression step raises when a formula cannot be copied."""


class ExpressionError(Exception):
    """The expression cannot be written as an app formula; the message is plain words for the person."""
