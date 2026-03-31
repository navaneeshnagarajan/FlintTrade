"""Signal generation — crossover detection, pivot highs/lows.

All functions:
- Accept numpy float64 arrays
- Return numpy bool_ or float64 arrays
- Fill NaN / False for bars where insufficient history exists
- Do NOT forward-fill
"""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray

from packages.indicators.src.utils import validate_series


def crossover(
    s1: NDArray[np.float64],
    s2: NDArray[np.float64],
) -> NDArray[np.bool_]:
    """Crossover detector — True where s1 crosses above s2.

    A crossover at bar ``i`` means:
        s1[i] > s2[i]  AND  s1[i-1] <= s2[i-1]

    The first bar is always False (no prior bar to compare).

    Args:
        s1: First series, shape (n,).
        s2: Second series, shape (n,). Must have the same length as s1.

    Returns:
        Boolean array, shape (n,). True where s1 crosses above s2.

    Raises:
        TypeError: If either input is not a numpy ndarray.
        ValueError: If arrays have different lengths or length < 1.
    """
    validate_series(s1, min_length=1)
    validate_series(s2, min_length=1)
    if len(s1) != len(s2):
        raise ValueError(
            f"Array length mismatch: s1={len(s1)}, s2={len(s2)}"
        )

    n = len(s1)
    result = np.zeros(n, dtype=np.bool_)
    for i in range(1, n):
        if np.isnan(s1[i]) or np.isnan(s2[i]) or np.isnan(s1[i - 1]) or np.isnan(s2[i - 1]):
            continue
        if s1[i] > s2[i] and s1[i - 1] <= s2[i - 1]:
            result[i] = True
    return result


def crossunder(
    s1: NDArray[np.float64],
    s2: NDArray[np.float64],
) -> NDArray[np.bool_]:
    """Crossunder detector — True where s1 crosses below s2.

    A crossunder at bar ``i`` means:
        s1[i] < s2[i]  AND  s1[i-1] >= s2[i-1]

    The first bar is always False (no prior bar to compare).

    Args:
        s1: First series, shape (n,).
        s2: Second series, shape (n,). Must have the same length as s1.

    Returns:
        Boolean array, shape (n,). True where s1 crosses below s2.

    Raises:
        TypeError: If either input is not a numpy ndarray.
        ValueError: If arrays have different lengths or length < 1.
    """
    validate_series(s1, min_length=1)
    validate_series(s2, min_length=1)
    if len(s1) != len(s2):
        raise ValueError(
            f"Array length mismatch: s1={len(s1)}, s2={len(s2)}"
        )

    n = len(s1)
    result = np.zeros(n, dtype=np.bool_)
    for i in range(1, n):
        if np.isnan(s1[i]) or np.isnan(s2[i]) or np.isnan(s1[i - 1]) or np.isnan(s2[i - 1]):
            continue
        if s1[i] < s2[i] and s1[i - 1] >= s2[i - 1]:
            result[i] = True
    return result


def pivothigh(
    source: NDArray[np.float64],
    left: int,
    right: int,
) -> NDArray[np.float64]:
    """Detect local pivot highs.

    Bar ``i`` is a pivot high if ``source[i]`` is the strict maximum in the
    window ``[i - left, i + right]``.  Because the right-side bars must exist,
    results for the last ``right`` bars are always NaN.  Results for the first
    ``left`` bars are also NaN.

    The returned value at a pivot bar is ``source[i]``; non-pivot bars are NaN.

    Args:
        source: Price series (typically high prices), shape (n,).
        left:   Number of bars to the left of the candidate bar (>= 1).
        right:  Number of bars to the right of the candidate bar (>= 1).

    Returns:
        Array of pivot high values, shape (n,). NaN where no pivot.

    Raises:
        ValueError: If left < 1 or right < 1.
    """
    validate_series(source, min_length=1)
    if left < 1:
        raise ValueError(f"pivothigh left must be >= 1, got {left}")
    if right < 1:
        raise ValueError(f"pivothigh right must be >= 1, got {right}")

    n = len(source)
    result = np.full(n, np.nan, dtype=np.float64)

    for i in range(left, n - right):
        candidate = source[i]
        if np.isnan(candidate):
            continue
        window = source[i - left : i + right + 1]
        if np.any(np.isnan(window)):
            continue
        # Strict maximum: candidate must be greater than ALL other bars in window
        if candidate == float(np.max(window)) and np.sum(window == candidate) == 1:
            result[i] = candidate

    return result


def exrem(
    primary: NDArray[np.bool_],
    secondary: NDArray[np.bool_],
) -> NDArray[np.bool_]:
    """Remove excessive signals — keep only the first primary signal.

    After a primary signal fires, all subsequent primary signals are suppressed
    until a secondary signal resets the latch.  Inspired by AmiBroker's ExRem.

    This is essential for strategy signal cleanup: ensures only one entry signal
    fires between each exit signal (and vice versa).

    Args:
        primary:   Boolean array of raw entry signals, shape (n,).
        secondary: Boolean array of reset signals (exits), shape (n,).

    Returns:
        Boolean array, shape (n,). True only at the FIRST primary signal after
        the most recent secondary signal.

    Raises:
        TypeError: If either input is not a numpy ndarray.
        ValueError: If arrays have different lengths or length < 1.

    Example:
        >>> buy  = np.array([False, True, True, False, True, True])
        >>> sell = np.array([False, False, False, True, False, False])
        >>> exrem(buy, sell)
        array([False, True, False, False, True, False])
    """
    validate_series(primary, min_length=1)
    validate_series(secondary, min_length=1)
    if len(primary) != len(secondary):
        raise ValueError(
            f"Array length mismatch: primary={len(primary)}, secondary={len(secondary)}"
        )

    n = len(primary)
    result = np.zeros(n, dtype=np.bool_)
    armed = True  # Ready to fire on next primary signal
    for i in range(n):
        if armed and primary[i]:
            result[i] = True
            armed = False
        elif secondary[i]:
            armed = True
    return result


def flip(
    set_signal: NDArray[np.bool_],
    reset_signal: NDArray[np.bool_],
) -> NDArray[np.bool_]:
    """Flip-flop state latch — True while set, False after reset.

    Once a set_signal fires, the output stays True until a reset_signal fires.
    Inspired by AmiBroker's Flip function.

    Useful for tracking whether a position is currently active between
    entry and exit signals.

    Args:
        set_signal:   Boolean array of set (entry) events, shape (n,).
        reset_signal: Boolean array of reset (exit) events, shape (n,).

    Returns:
        Boolean array, shape (n,). True while latched on, False when off.

    Raises:
        TypeError: If either input is not a numpy ndarray.
        ValueError: If arrays have different lengths or length < 1.

    Example:
        >>> entry = np.array([False, True, False, False, False, True])
        >>> exit_ = np.array([False, False, False, True, False, False])
        >>> flip(entry, exit_)
        array([False, True, True, False, False, True])
    """
    validate_series(set_signal, min_length=1)
    validate_series(reset_signal, min_length=1)
    if len(set_signal) != len(reset_signal):
        raise ValueError(
            f"Array length mismatch: set_signal={len(set_signal)}, reset_signal={len(reset_signal)}"
        )

    n = len(set_signal)
    result = np.zeros(n, dtype=np.bool_)
    active = False
    for i in range(n):
        if set_signal[i]:
            active = True
        elif reset_signal[i]:
            active = False
        result[i] = active
    return result


def valuewhen(
    condition: NDArray[np.bool_],
    source: NDArray[np.float64],
    occurrence: int = 1,
) -> NDArray[np.float64]:
    """Value of source when condition was True, N occurrences ago.

    At each bar, looks back for the Nth most recent True in condition
    and returns the corresponding source value. Inspired by AmiBroker's
    ValueWhen function.

    Useful for getting the price at the last crossover, the last pivot,
    or the entry price of the current position.

    Args:
        condition:  Boolean array of trigger events, shape (n,).
        source:     Value array to sample from, shape (n,).
        occurrence: Which occurrence to return (1 = most recent, 2 = second
                    most recent, etc.). Must be >= 1.

    Returns:
        Float64 array, shape (n,). NaN where fewer than ``occurrence``
        triggers have occurred so far.

    Raises:
        TypeError: If inputs are not numpy ndarrays.
        ValueError: If arrays have different lengths, length < 1, or
                    occurrence < 1.

    Example:
        >>> cond = np.array([False, True, False, True, False])
        >>> vals = np.array([10.0, 20.0, 30.0, 40.0, 50.0])
        >>> valuewhen(cond, vals, 1)
        array([nan, 20., 20., 40., 40.])
    """
    validate_series(condition, min_length=1)
    validate_series(source, min_length=1)
    if len(condition) != len(source):
        raise ValueError(
            f"Array length mismatch: condition={len(condition)}, source={len(source)}"
        )
    if occurrence < 1:
        raise ValueError(f"occurrence must be >= 1, got {occurrence}")

    n = len(condition)
    result = np.full(n, np.nan, dtype=np.float64)
    true_indices: list[int] = []

    for i in range(n):
        if condition[i]:
            true_indices.append(i)
        if len(true_indices) >= occurrence:
            target_idx = true_indices[-occurrence]
            result[i] = source[target_idx]

    return result


def pivotlow(
    source: NDArray[np.float64],
    left: int,
    right: int,
) -> NDArray[np.float64]:
    """Detect local pivot lows.

    Bar ``i`` is a pivot low if ``source[i]`` is the strict minimum in the
    window ``[i - left, i + right]``.  Because the right-side bars must exist,
    results for the last ``right`` bars are always NaN.  Results for the first
    ``left`` bars are also NaN.

    The returned value at a pivot bar is ``source[i]``; non-pivot bars are NaN.

    Args:
        source: Price series (typically low prices), shape (n,).
        left:   Number of bars to the left of the candidate bar (>= 1).
        right:  Number of bars to the right of the candidate bar (>= 1).

    Returns:
        Array of pivot low values, shape (n,). NaN where no pivot.

    Raises:
        ValueError: If left < 1 or right < 1.
    """
    validate_series(source, min_length=1)
    if left < 1:
        raise ValueError(f"pivotlow left must be >= 1, got {left}")
    if right < 1:
        raise ValueError(f"pivotlow right must be >= 1, got {right}")

    n = len(source)
    result = np.full(n, np.nan, dtype=np.float64)

    for i in range(left, n - right):
        candidate = source[i]
        if np.isnan(candidate):
            continue
        window = source[i - left : i + right + 1]
        if np.any(np.isnan(window)):
            continue
        # Strict minimum: candidate must be less than ALL other bars in window
        if candidate == float(np.min(window)) and np.sum(window == candidate) == 1:
            result[i] = candidate

    return result
