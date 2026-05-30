"""Indicator utilities — validation, common helpers."""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray


def validate_series(data: NDArray[np.float64], min_length: int = 1) -> None:
    """Validate a numeric input series.

    Args:
        data: Input array to validate.
        min_length: Minimum number of elements required.

    Raises:
        TypeError: If data is not a numpy ndarray.
        ValueError: If the series is shorter than min_length.
    """
    if not isinstance(data, np.ndarray):
        raise TypeError(f"Expected numpy array, got {type(data).__name__}")
    if len(data) < min_length:
        raise ValueError(f"Series length {len(data)} < minimum required {min_length}")


def validate_ohlcv(
    high: NDArray[np.float64],
    low: NDArray[np.float64],
    close: NDArray[np.float64],
    min_length: int = 1,
) -> None:
    """Validate high, low, close arrays have matching lengths.

    Args:
        high: High prices array.
        low: Low prices array.
        close: Close prices array.
        min_length: Minimum number of elements required.

    Raises:
        TypeError: If any input is not a numpy ndarray.
        ValueError: If arrays have different lengths or are shorter than min_length.
    """
    validate_series(high, min_length)
    validate_series(low, min_length)
    validate_series(close, min_length)
    if not (len(high) == len(low) == len(close)):
        raise ValueError(
            f"Array length mismatch: high={len(high)}, low={len(low)}, close={len(close)}"
        )


def as_float64(data: NDArray[np.floating]) -> NDArray[np.float64]:
    """Ensure array is float64 dtype without copying if already correct.

    Args:
        data: Input numeric array.

    Returns:
        Array guaranteed to be float64.
    """
    return data.astype(np.float64, copy=False)
