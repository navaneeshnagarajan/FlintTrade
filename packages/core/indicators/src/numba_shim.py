"""Shim that upgrades legacy @jit decorators to modern njit fast paths.

This lets existing code using ``from numba import jit`` automatically gain
caching and nogil without touching every file.  It also adds an easy way to
request parallel loops simply by passing ``parallel=True``.

When numba is not installed the shim provides transparent no-op decorators so
that the indicator code still works (interpreted, slower).

fastmath is deliberately OFF to preserve IEEE 754 NaN semantics.
np.isnan() silently returns wrong results under fastmath=True.

Usage::

    from flinttrade_indicators.numba_shim import jit, njit, prange, HAS_NUMBA

    @jit(nopython=True)
    def my_fast_loop(arr):
        ...
"""

from __future__ import annotations

try:
    from numba import njit, prange  # noqa: F401 — re-exported for callers

    HAS_NUMBA = True

except ImportError:
    HAS_NUMBA = False

    def _noop_decorator(*args, **kwargs):  # type: ignore[misc]
        """Return the function unchanged when numba is absent."""
        if args and callable(args[0]):
            return args[0]
        return lambda fn: fn

    njit = _noop_decorator  # type: ignore[assignment]

    # prange is just range when not using numba
    prange = range  # type: ignore[assignment]


def jit(*args, **kwargs):  # type: ignore[override]
    """Drop-in replacement for ``numba.jit`` with better defaults.

    Ensures:
    - nopython=True  (stay in compiled mode, equivalent to njit)
    - cache=True     (persist compiled kernels to disk)
    - nogil=True     (release the GIL so threads can run concurrently)

    fastmath is deliberately OFF to preserve IEEE 754 NaN semantics.
    np.isnan() silently returns wrong results under fastmath=True.

    When numba is not installed the decorator is a transparent no-op.

    Args:
        *args: Positional arguments forwarded to ``numba.njit``.
        **kwargs: Keyword arguments forwarded to ``numba.njit``.
            ``nopython`` is stripped (njit already implies it).
            ``cache`` defaults to True if not supplied.
            ``nogil`` defaults to True if not supplied.

    Returns:
        Compiled function when numba is available; original function otherwise.

    Example::

        @jit(nopython=True)
        def compute_ema(close, k, seed):
            ...
    """
    if not HAS_NUMBA:
        if args and callable(args[0]):
            return args[0]
        return lambda fn: fn

    # Strip nopython — njit always uses nopython mode
    kwargs.pop("nopython", None)
    kwargs.setdefault("cache", True)
    kwargs.setdefault("nogil", True)
    return njit(*args, **kwargs)
