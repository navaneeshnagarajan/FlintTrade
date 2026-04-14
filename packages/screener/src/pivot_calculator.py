"""Pivot point calculator supporting five classic methods.

Computes support and resistance levels from a prior session's high, low,
and close (and optionally open) using the Standard, Fibonacci, Woodie,
Camarilla, and DeMark methods.

Endpoint (registered via pivot_routes.py):
    POST /ft-api/v1/pivots/calculate

Usage::

    from .pivot_calculator import PivotCalculator, PivotMethod

    levels = PivotCalculator.calculate(high=18500, low=18200, close=18400)
    all_methods = PivotCalculator.all_methods(high=18500, low=18200, close=18400)
"""

from __future__ import annotations

import logging
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, model_validator

logger = logging.getLogger("flinttrade.screener.pivot_calculator")

# ---------------------------------------------------------------------------
# Enums and models
# ---------------------------------------------------------------------------


class PivotMethod(StrEnum):
    """Supported pivot point calculation methods."""

    STANDARD = "standard"
    FIBONACCI = "fibonacci"
    WOODIE = "woodie"
    CAMARILLA = "camarilla"
    DEMARK = "demark"


class PivotLevels(BaseModel):
    """Pivot support and resistance levels for a single method.

    Attributes:
        method: The calculation method used.
        pivot: Central pivot point.
        r1: First resistance level.
        r2: Second resistance level.
        r3: Third resistance level.
        r4: Fourth resistance level (Camarilla only).
        s1: First support level.
        s2: Second support level.
        s3: Third support level.
        s4: Fourth support level (Camarilla only).
    """

    method: PivotMethod
    pivot: float
    r1: float
    r2: float
    r3: float
    r4: float | None = None
    s1: float
    s2: float
    s3: float
    s4: float | None = None

    @model_validator(mode="after")
    def _round_levels(self) -> "PivotLevels":
        """Round all float fields to 2 decimal places for display consistency."""
        for field in ("pivot", "r1", "r2", "r3", "r4", "s1", "s2", "s3", "s4"):
            val = getattr(self, field)
            if val is not None:
                object.__setattr__(self, field, round(val, 2))
        return self

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a JSON-compatible dictionary.

        Returns:
            Dict with ``method`` as a plain string.
        """
        d = self.model_dump()
        d["method"] = str(self.method)
        return d


# ---------------------------------------------------------------------------
# Calculator
# ---------------------------------------------------------------------------


class PivotCalculator:
    """Stateless pivot point calculator.

    All public methods are static — no instance state is required.

    Supported methods
    -----------------
    Standard (classical floor trader pivots):
        P  = (H + L + C) / 3
        R1 = 2P - L,    S1 = 2P - H
        R2 = P + (H-L), S2 = P - (H-L)
        R3 = H + 2(P-L),S3 = L - 2(H-P)

    Fibonacci:
        P  = (H + L + C) / 3
        R1 = P + 0.382*(H-L), S1 = P - 0.382*(H-L)
        R2 = P + 0.618*(H-L), S2 = P - 0.618*(H-L)
        R3 = P + (H-L),       S3 = P - (H-L)

    Woodie (weighted towards close):
        P  = (H + L + 2C) / 4
        R1 = 2P - L,    S1 = 2P - H
        R2 = P + (H-L), S2 = P - (H-L)
        R3 = R1 + (H-L),S3 = S1 - (H-L)   [derived extension]

    Camarilla (intraday mean-reversion bands):
        P         = (H + L + C) / 3
        range     = H - L
        R1 = C + range * (1.1/12)
        R2 = C + range * (1.1/6)
        R3 = C + range * (1.1/4)
        R4 = C + range * (1.1/2)
        S1 = C - range * (1.1/12)
        S2 = C - range * (1.1/6)
        S3 = C - range * (1.1/4)
        S4 = C - range * (1.1/2)

    DeMark (open-price conditional):
        If C < O:  X = H + 2L + C
        If C > O:  X = 2H + L + C
        If C == O: X = H + L + 2C
        P = X / 4
        R1 = X/2 - L
        S1 = X/2 - H
        R2/R3 use standard extensions from P.
        S2/S3 use standard extensions from P.
    """

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @staticmethod
    def calculate(
        high: float,
        low: float,
        close: float,
        open_price: float | None = None,
        method: PivotMethod = PivotMethod.STANDARD,
    ) -> PivotLevels:
        """Calculate pivot points using the specified method.

        Args:
            high: Session high price.
            low: Session low price.
            close: Session close price.
            open_price: Session open price (required for DeMark; defaults to
                ``close`` when ``None`` and DeMark is requested).
            method: Pivot calculation method (default: Standard).

        Returns:
            :class:`PivotLevels` populated for the requested method.

        Raises:
            ValueError: If ``high < low``.
        """
        if high < low:
            raise ValueError(
                f"high ({high}) must be greater than or equal to low ({low})"
            )

        dispatch = {
            PivotMethod.STANDARD: PivotCalculator._standard,
            PivotMethod.FIBONACCI: PivotCalculator._fibonacci,
            PivotMethod.WOODIE: PivotCalculator._woodie,
            PivotMethod.CAMARILLA: PivotCalculator._camarilla,
            PivotMethod.DEMARK: PivotCalculator._demark,
        }
        fn = dispatch[method]
        return fn(high, low, close, open_price)

    @staticmethod
    def all_methods(
        high: float,
        low: float,
        close: float,
        open_price: float | None = None,
    ) -> dict[str, PivotLevels]:
        """Calculate pivot levels for all five methods simultaneously.

        Args:
            high: Session high price.
            low: Session low price.
            close: Session close price.
            open_price: Session open price (used by DeMark).

        Returns:
            Dict mapping method name string to :class:`PivotLevels`.
        """
        return {
            method.value: PivotCalculator.calculate(
                high, low, close, open_price, method
            )
            for method in PivotMethod
        }

    # ------------------------------------------------------------------
    # Private method implementations
    # ------------------------------------------------------------------

    @staticmethod
    def _standard(
        high: float, low: float, close: float, _open: float | None
    ) -> PivotLevels:
        """Compute Standard (floor trader) pivot levels."""
        pivot = (high + low + close) / 3
        rng = high - low
        r1 = 2 * pivot - low
        r2 = pivot + rng
        r3 = high + 2 * (pivot - low)
        s1 = 2 * pivot - high
        s2 = pivot - rng
        s3 = low - 2 * (high - pivot)
        return PivotLevels(
            method=PivotMethod.STANDARD,
            pivot=pivot,
            r1=r1, r2=r2, r3=r3,
            s1=s1, s2=s2, s3=s3,
        )

    @staticmethod
    def _fibonacci(
        high: float, low: float, close: float, _open: float | None
    ) -> PivotLevels:
        """Compute Fibonacci pivot levels."""
        pivot = (high + low + close) / 3
        rng = high - low
        r1 = pivot + 0.382 * rng
        r2 = pivot + 0.618 * rng
        r3 = pivot + rng
        s1 = pivot - 0.382 * rng
        s2 = pivot - 0.618 * rng
        s3 = pivot - rng
        return PivotLevels(
            method=PivotMethod.FIBONACCI,
            pivot=pivot,
            r1=r1, r2=r2, r3=r3,
            s1=s1, s2=s2, s3=s3,
        )

    @staticmethod
    def _woodie(
        high: float, low: float, close: float, _open: float | None
    ) -> PivotLevels:
        """Compute Woodie pivot levels (close-weighted)."""
        pivot = (high + low + 2 * close) / 4
        rng = high - low
        r1 = 2 * pivot - low
        r2 = pivot + rng
        r3 = r1 + rng
        s1 = 2 * pivot - high
        s2 = pivot - rng
        s3 = s1 - rng
        return PivotLevels(
            method=PivotMethod.WOODIE,
            pivot=pivot,
            r1=r1, r2=r2, r3=r3,
            s1=s1, s2=s2, s3=s3,
        )

    @staticmethod
    def _camarilla(
        high: float, low: float, close: float, _open: float | None
    ) -> PivotLevels:
        """Compute Camarilla pivot levels (4 levels each side)."""
        pivot = (high + low + close) / 3
        rng = high - low
        r1 = close + rng * (1.1 / 12)
        r2 = close + rng * (1.1 / 6)
        r3 = close + rng * (1.1 / 4)
        r4 = close + rng * (1.1 / 2)
        s1 = close - rng * (1.1 / 12)
        s2 = close - rng * (1.1 / 6)
        s3 = close - rng * (1.1 / 4)
        s4 = close - rng * (1.1 / 2)
        return PivotLevels(
            method=PivotMethod.CAMARILLA,
            pivot=pivot,
            r1=r1, r2=r2, r3=r3, r4=r4,
            s1=s1, s2=s2, s3=s3, s4=s4,
        )

    @staticmethod
    def _demark(
        high: float, low: float, close: float, open_price: float | None
    ) -> PivotLevels:
        """Compute DeMark pivot levels (open-price conditional).

        If ``open_price`` is not supplied it defaults to ``close``, which
        triggers the ``C == O`` branch (``X = H + L + 2C``).
        """
        op = open_price if open_price is not None else close

        if close < op:
            x = high + 2 * low + close
        elif close > op:
            x = 2 * high + low + close
        else:
            x = high + low + 2 * close

        pivot = x / 4
        half_x = x / 2
        r1 = half_x - low
        s1 = half_x - high
        rng = high - low
        # Extensions use the standard formula from the DeMark pivot
        r2 = pivot + rng
        r3 = r1 + rng
        s2 = pivot - rng
        s3 = s1 - rng
        return PivotLevels(
            method=PivotMethod.DEMARK,
            pivot=pivot,
            r1=r1, r2=r2, r3=r3,
            s1=s1, s2=s2, s3=s3,
        )
