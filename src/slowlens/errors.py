"""Exception types raised by QueryLens.

Every error that should reach the user as ``slowlens: error: <message>`` derives from
:class:`QueryLensError`; anything else is a bug and is allowed to propagate.
"""


class QueryLensError(Exception):
    """Base class for expected, user-facing errors."""


class InputError(QueryLensError):
    """An input file is missing, unreadable, empty or in an unrecognised format."""
