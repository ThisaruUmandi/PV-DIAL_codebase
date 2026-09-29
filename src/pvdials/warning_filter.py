"""Suppresses one specific, known-benign warning (scipy's Chandrupatla
solver dividing 0/0 at zero irradiance, where there's no operating point to
solve for) without hiding anything else. Its own module, not folded into
__main__.py, so a Streamlit app can wrap the same call with the same filter.
"""

from __future__ import annotations

import warnings
from typing import Self

_TARGET_MESSAGE = "invalid value encountered in divide"
_TARGET_FILENAME_SUFFIX = "_chandrupatla.py"


class ChandrupatlaWarningFilter:
    """Context manager: suppresses only the known scipy chandrupatla 0/0
    RuntimeWarning, counted in `.count`. Every other warning, including any
    other RuntimeWarning, still prints immediately, exactly as without this
    filter -- matched on category + filename + message together, not line
    number alone, so a scipy version bump can't silently stop matching or
    start over-matching.
    """

    def __init__(self) -> None:
        self.count = 0
        self._catcher = None

    def __enter__(self) -> Self:
        self._catcher = warnings.catch_warnings()
        self._catcher.__enter__()
        warnings.simplefilter("always")
        original_showwarning = warnings.showwarning

        def showwarning(message, category, filename, lineno, file=None, line=None):
            if (
                category is RuntimeWarning
                and str(message) == _TARGET_MESSAGE
                and filename.endswith(_TARGET_FILENAME_SUFFIX)
            ):
                self.count += 1
                return
            original_showwarning(message, category, filename, lineno, file, line)

        warnings.showwarning = showwarning
        return self

    def __exit__(self, *exc_info: object) -> None:
        self._catcher.__exit__(*exc_info)
