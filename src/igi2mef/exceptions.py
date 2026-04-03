"""
igi2mef.exceptions
~~~~~~~~~~~~~~~~~~
All exceptions raised by the igi2mef library.
"""


class MefError(Exception):
    """Base class for all igi2mef errors."""


class MefParseError(MefError):
    """
    Raised when a MEF file cannot be parsed.

    Attributes
    ----------
    path : str
        The file path that caused the error (if available).
    reason : str
        Short human-readable description of what went wrong.
    """

    def __init__(self, reason: str, path: str = ""):
        self.reason = reason
        self.path = path
        msg = f"{reason}"
        if path:
            msg = f"[{path}] {reason}"
        super().__init__(msg)


class MefValidationError(MefError):
    """
    Raised when a file exists but does not pass the ILFF magic check.
    """
