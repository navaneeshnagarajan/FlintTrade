"""Enhanced portfolio-level Greeks with P&L attribution, IV analytics, and PCR.

Extends the core ``greeks.py`` module with:
- Per-position Greeks with lot-size weighting
- Net Greek exposure across all positions
- Greeks P&L attribution (delta P&L, gamma P&L, theta decay, vega P&L)
- IV percentile and IV rank over a rolling history window
- Put-Call ratio derived from portfolio positions
- Enhanced max pain calculation (full pain surface, not just minimum)

Adapts patterns from openalgo-portfoliogreeks:
- rho calculation via Black-Scholes
- lot-size lookup via OpenAlgo API (with fallback to LOT_SIZES map)
- position-aware sign rules (BUY CE = +delta, SELL PE = +delta, etc.)
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import NamedTuple

import numpy as np
from numpy.typing import NDArray

from flinttrade_core.models import OptionGreek

from .greeks import (
    OptionPosition,
    PortfolioGreeks,
    PortfolioGreeksResult,
    PositionGreeks,
)

logger = logging.getLogger("flinttrade.screener.portfolio_greeks")


# ---------------------------------------------------------------------------
# Extended position Greeks with rho
# ---------------------------------------------------------------------------


@dataclass
class PositionGreeksEx(PositionGreeks):
    """Extended Greeks for a single position — adds rho."""

    rho: float = 0.0


@dataclass
class PortfolioGreeksResultEx(PortfolioGreeksResult):
    """Extended aggregate Greeks — adds rho and attribution."""

    net_rho: float = 0.0
    positions: list[PositionGreeksEx] = field(default_factory=list)  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# IV analytics
# ---------------------------------------------------------------------------


def iv_percentile(iv_history: NDArray[np.float64]) -> float:
    """Compute IV Percentile over a rolling IV history.

    IV Percentile measures the fraction of past IV values that are BELOW the
    current IV.  A value of 0.80 means current IV is higher than 80 % of all
    readings in the history window.

    Formula::

        IVP = count(iv_history[:-1] < iv_history[-1]) / len(iv_history[:-1])

    Args:
        iv_history: Array of daily IV values (as decimals or percentages, must
            be consistent), length >= 2.  The LAST element is treated as the
            current IV.

    Returns:
        IV Percentile in [0.0, 1.0].  Returns 0.0 if history has fewer than
        2 elements.
    """
    if len(iv_history) < 2:
        return 0.0
    current_iv = float(iv_history[-1])
    hist = iv_history[:-1].astype(np.float64)
    return float(np.sum(hist < current_iv) / len(hist))


def iv_rank(iv_history: NDArray[np.float64]) -> float:
    """Compute IV Rank (IVR) over a rolling IV history.

    IV Rank normalises the current IV against the historical high and low of
    the window::

        IVR = (current_iv - iv_52w_low) / (iv_52w_high - iv_52w_low)

    A value of 0.0 means current IV is at its historical low; 1.0 means it is
    at its historical high.

    Args:
        iv_history: Array of daily IV values, length >= 2.  The LAST element
            is treated as the current IV.

    Returns:
        IV Rank in [0.0, 1.0].  Returns 0.0 if high == low (no range) or
        fewer than 2 elements.
    """
    if len(iv_history) < 2:
        return 0.0
    current_iv = float(iv_history[-1])
    iv_min = float(np.min(iv_history))
    iv_max = float(np.max(iv_history))
    iv_range = iv_max - iv_min
    if iv_range == 0.0:
        return 0.0
    return float(np.clip((current_iv - iv_min) / iv_range, 0.0, 1.0))


# ---------------------------------------------------------------------------
# Greeks P&L attribution
# ---------------------------------------------------------------------------


class GreeksPnlAttribution(NamedTuple):
    """Breakdown of P&L contribution from each Greek source.

    All values are in points (multiply by lot_size for rupees).

    Attributes:
        delta_pnl:     P&L from underlying price move (delta * spot_move).
        gamma_pnl:     Second-order P&L from underlying move
                       (0.5 * gamma * spot_move^2).
        theta_pnl:     P&L from time decay over ``days`` days
                       (theta * days).
        vega_pnl:      P&L from IV change (vega * iv_change).
        total_greek_pnl: Sum of all four attribution components.
    """

    delta_pnl: float
    gamma_pnl: float
    theta_pnl: float
    vega_pnl: float
    total_greek_pnl: float


def greeks_pnl_attribution(
    net_delta: float,
    net_gamma: float,
    net_theta: float,
    net_vega: float,
    spot_move: float,
    iv_change: float,
    days: float = 1.0,
) -> GreeksPnlAttribution:
    """Attribute P&L to individual Greek sources.

    Uses the standard first/second-order Taylor expansion of the options
    pricing function::

        P&L ≈ delta * dS + 0.5 * gamma * dS^2 + theta * dt + vega * dIV

    This gives a quick estimate of how much each Greek contributed to the
    portfolio's P&L over a period.

    Args:
        net_delta:  Aggregate portfolio delta (quantity-adjusted).
        net_gamma:  Aggregate portfolio gamma.
        net_theta:  Aggregate portfolio theta (per day, already sign-adjusted).
        net_vega:   Aggregate portfolio vega.
        spot_move:  Change in underlying price (dS).  Positive = market up.
        iv_change:  Change in implied volatility in percentage points
                    (e.g. 0.5 means IV increased by 0.5%).
        days:       Number of trading days elapsed (default 1.0).

    Returns:
        :class:`GreeksPnlAttribution` named tuple with delta, gamma, theta,
        vega, and total Greek P&L.
    """
    delta_pnl = net_delta * spot_move
    gamma_pnl = 0.5 * net_gamma * spot_move ** 2
    theta_pnl = net_theta * days
    vega_pnl = net_vega * iv_change
    total = delta_pnl + gamma_pnl + theta_pnl + vega_pnl
    return GreeksPnlAttribution(
        delta_pnl=round(delta_pnl, 2),
        gamma_pnl=round(gamma_pnl, 4),
        theta_pnl=round(theta_pnl, 2),
        vega_pnl=round(vega_pnl, 2),
        total_greek_pnl=round(total, 2),
    )


# ---------------------------------------------------------------------------
# Portfolio PCR from positions
# ---------------------------------------------------------------------------


def portfolio_pcr(positions: list[OptionPosition]) -> float:
    """Compute Put-Call ratio from portfolio option positions.

    PCR is calculated as total PE lots / total CE lots.  Only BUY positions
    are counted (SELL positions are excluded as they represent short exposure).

    For a balanced portfolio the PCR is 1.0.  Values > 1 indicate a higher
    proportion of puts (bearish lean); values < 1 indicate call dominance.

    Args:
        positions: List of :class:`~flinttrade_screener.greeks.OptionPosition`.

    Returns:
        Put-Call Ratio.  Returns 0.0 when there are no call positions or the
        list is empty.
    """
    total_pe_lots = sum(
        p.lots for p in positions
        if p.option_type.upper() == "PE" and p.action.upper() == "BUY"
    )
    total_ce_lots = sum(
        p.lots for p in positions
        if p.option_type.upper() == "CE" and p.action.upper() == "BUY"
    )
    if total_ce_lots == 0:
        return 0.0
    return round(total_pe_lots / total_ce_lots, 4)


# ---------------------------------------------------------------------------
# Max pain (enhanced)
# ---------------------------------------------------------------------------


class MaxPainResult(NamedTuple):
    """Output from :func:`max_pain_enhanced`.

    Attributes:
        max_pain_strike:  Strike where total option buyers' loss is maximised
                          (writers' gain).
        pain_by_strike:   Dict mapping each strike price to the total open
                          interest loss imposed on buyers at that expiry price.
        min_pain_strike:  Strike where buyers lose the least (rarely used but
                          useful for reference).
    """

    max_pain_strike: float
    pain_by_strike: dict[float, float]
    min_pain_strike: float


def max_pain_enhanced(
    strikes: list[float],
    ce_oi: list[int],
    pe_oi: list[int],
    lot_size: int = 1,
) -> MaxPainResult:
    """Calculate max pain with full pain surface across all strikes.

    For each candidate expiry price (every strike), we compute the total
    intrinsic value that all open options would lose::

        CE pain at price P = sum(max(P - K, 0) * CE_OI[K] for all K)
        PE pain at price P = sum(max(K - P, 0) * PE_OI[K] for all K)
        Total pain at P    = CE pain + PE pain

    The max pain strike is the expiry price that maximises total writer gains
    (i.e. the price where total option buyer losses are greatest).

    Args:
        strikes:   List of strike prices in ascending order, length n.
        ce_oi:     Call open interest per strike, same length as strikes.
        pe_oi:     Put open interest per strike, same length as strikes.
        lot_size:  Lot size for the underlying (default 1 — leave as 1 to
                   get pain values in contract units; multiply externally).

    Returns:
        :class:`MaxPainResult` with the max pain strike, the full pain
        surface dict, and the min pain strike.

    Raises:
        ValueError: If strikes, ce_oi, and pe_oi have different lengths or
                    any list is empty.
    """
    if not strikes:
        raise ValueError("strikes list must not be empty")
    if len(strikes) != len(ce_oi) or len(strikes) != len(pe_oi):
        raise ValueError(
            f"Length mismatch: strikes={len(strikes)}, ce_oi={len(ce_oi)}, pe_oi={len(pe_oi)}"
        )

    strikes_arr = np.array(strikes, dtype=np.float64)
    ce_arr = np.array(ce_oi, dtype=np.float64) * lot_size
    pe_arr = np.array(pe_oi, dtype=np.float64) * lot_size

    pain_by_strike: dict[float, float] = {}

    for price in strikes:
        price_f = float(price)
        ce_pain = float(np.sum(np.maximum(price_f - strikes_arr, 0.0) * ce_arr))
        pe_pain = float(np.sum(np.maximum(strikes_arr - price_f, 0.0) * pe_arr))
        pain_by_strike[price_f] = round(ce_pain + pe_pain, 2)

    max_pain_strike = max(pain_by_strike, key=lambda k: pain_by_strike[k])
    min_pain_strike = min(pain_by_strike, key=lambda k: pain_by_strike[k])

    return MaxPainResult(
        max_pain_strike=max_pain_strike,
        pain_by_strike=pain_by_strike,
        min_pain_strike=min_pain_strike,
    )


# ---------------------------------------------------------------------------
# Enhanced PortfolioGreeks class with rho and attribution
# ---------------------------------------------------------------------------


def _bs_rho(
    flag: str,
    S: float,
    K: float,
    T: float,
    r: float,
    sigma: float,
) -> float:
    """Black-Scholes rho (per 1% change in risk-free rate).

    Args:
        flag:  "c" for call, "p" for put.
        S:     Spot price.
        K:     Strike price.
        T:     Time to expiry in years.
        r:     Risk-free rate (annual decimal).
        sigma: Implied volatility (annual decimal).

    Returns:
        Rho value scaled to 1% rate change.
    """
    if T <= 0 or sigma <= 0 or S <= 0:
        return 0.0

    d2 = (math.log(S / K) + (r - 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))

    def _ncdf(x: float) -> float:
        return 0.5 * (1 + math.erf(x / math.sqrt(2)))

    if flag == "c":
        rho = K * T * math.exp(-r * T) * _ncdf(d2) / 100
    else:
        rho = -K * T * math.exp(-r * T) * _ncdf(-d2) / 100

    return round(rho, 4)


class EnhancedPortfolioGreeks(PortfolioGreeks):
    """Extended portfolio Greeks aggregator with rho and attribution.

    Inherits from :class:`~flinttrade_screener.greeks.PortfolioGreeks`.
    Adds:
    - Rho aggregation across all positions
    - :meth:`attribute_pnl` for post-hoc P&L decomposition
    - :meth:`pcr` property for quick Put-Call ratio

    Usage::

        epg = EnhancedPortfolioGreeks(client)
        positions = [
            OptionPosition(symbol="NIFTY26MAR2524000CE", action="SELL",
                           lots=2, lot_size=75, option_type="CE"),
            OptionPosition(symbol="NIFTY26MAR2524000PE", action="SELL",
                           lots=2, lot_size=75, option_type="PE"),
        ]
        result = epg.calculate_enhanced(positions, spot=24000, time_to_expiry=7/365)
        print(f"Net delta: {result.net_delta}")
        attr = epg.attribute_pnl(result, spot_move=50, iv_change=0.5)
        print(f"Delta P&L: {attr.delta_pnl}")
    """

    def calculate_enhanced(
        self,
        positions: list[OptionPosition],
        spot: float | None = None,
        time_to_expiry: float | None = None,
        risk_free_rate: float = 0.07,
        greeks_override: dict[str, OptionGreek] | None = None,
    ) -> PortfolioGreeksResultEx:
        """Calculate aggregate Greeks including rho.

        If ``spot`` and ``time_to_expiry`` are provided, rho is computed via
        local Black-Scholes.  Otherwise rho is set to 0 (OpenAlgo API does not
        currently return rho).

        Args:
            positions:       List of option positions.
            spot:            Current underlying spot price (for local rho).
            time_to_expiry:  Years to expiry (for local rho).
            risk_free_rate:  Annual risk-free rate (default 7% for India).
            greeks_override: Optional pre-fetched Greeks keyed by symbol.

        Returns:
            :class:`PortfolioGreeksResultEx` with net delta, gamma, theta,
            vega, rho, and per-position details.
        """
        base_result = self.calculate(positions, greeks_override=greeks_override)

        result = PortfolioGreeksResultEx(
            net_delta=base_result.net_delta,
            net_gamma=base_result.net_gamma,
            net_theta=base_result.net_theta,
            net_vega=base_result.net_vega,
        )

        for pg in base_result.positions:
            pgex = PositionGreeksEx(
                symbol=pg.symbol,
                option_type=pg.option_type,
                action=pg.action,
                lots=pg.lots,
                quantity=pg.quantity,
                delta=pg.delta,
                gamma=pg.gamma,
                theta=pg.theta,
                vega=pg.vega,
                iv=pg.iv,
                rho=0.0,
            )

            # Compute local rho when spot/time_to_expiry available
            if spot is not None and time_to_expiry is not None:
                flag = "c" if pg.option_type.upper() == "CE" else "p"
                sign = 1 if pg.action.upper() == "BUY" else -1
                # Extract strike from symbol.
                # Format: UNDERLYING DD MON YY STRIKE CE|PE
                # e.g. NIFTY26MAR2524000CE → base=NIFTY, day=26, mon=MAR, yr=25, strike=24000
                try:
                    import re as _re
                    # Pattern: letters + 2-digit day + 3-letter month + 2-digit year + strike + CE/PE
                    m = _re.match(
                        r"([A-Z]+)(\d{2})([A-Z]{3})(\d{2})(\d+)(CE|PE)$",
                        pg.symbol,
                    )
                    if m:
                        strike = float(m.group(5))
                        iv_decimal = (pg.iv / 100.0) if pg.iv > 0 else 0.2
                        raw_rho = _bs_rho(
                            flag, spot, strike, time_to_expiry,
                            risk_free_rate, iv_decimal,
                        )
                        pgex.rho = raw_rho * pg.quantity * sign
                except Exception as exc:
                    logger.debug("Rho calculation skipped for %s: %s", pg.symbol, exc)

            result.positions.append(pgex)
            result.net_rho += pgex.rho

        result.net_rho = round(result.net_rho, 4)
        return result

    @staticmethod
    def attribute_pnl(
        result: PortfolioGreeksResult | PortfolioGreeksResultEx,
        spot_move: float,
        iv_change: float = 0.0,
        days: float = 1.0,
    ) -> GreeksPnlAttribution:
        """Decompose portfolio P&L into Greek contributions.

        Args:
            result:     Aggregate Greeks result from :meth:`calculate` or
                        :meth:`calculate_enhanced`.
            spot_move:  Change in underlying price (dS).
            iv_change:  Change in IV in percentage points (default 0.0).
            days:       Elapsed trading days (default 1.0).

        Returns:
            :class:`GreeksPnlAttribution` with per-source P&L breakdown.
        """
        return greeks_pnl_attribution(
            net_delta=result.net_delta,
            net_gamma=result.net_gamma,
            net_theta=result.net_theta,
            net_vega=result.net_vega,
            spot_move=spot_move,
            iv_change=iv_change,
            days=days,
        )

    @staticmethod
    def pcr(positions: list[OptionPosition]) -> float:
        """Compute Put-Call ratio from positions.

        Args:
            positions: List of option positions.

        Returns:
            PCR value.  See :func:`portfolio_pcr` for full documentation.
        """
        return portfolio_pcr(positions)
