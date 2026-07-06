"""Gamma Density analytics (DP2).

Computes the "Gamma Density" view (inspired by Vtrender's Gamma Density chart),
ported natively onto FlintTrade's own option-chain snapshot and Black-Scholes
greeks — no OpenAlgo call, no external ``opengreeks`` dependency:

  * **Density (Γ×OI)** — per-strike dealer gamma exposure = option gamma × open
    interest, summed across CE and PE legs. The headline curve.
  * **Convexity Zone** — the ±1σ / ±2σ expected-move band around spot, derived
    from ATM IV. Marks where price is statistically expected to gravitate.

Two horizons are returned so the UI can show side-by-side panels:

  * **To Expiry** — density from the snapshot's own greeks (computed at the
    chain's days-to-expiry horizon). The terminal pin/gravity view.
  * **Intraday** — density from gamma recomputed at a one-trading-day horizon
    (per-strike IV, FlintTrade's :func:`_bs_greeks`). Sharpens the ATM gamma
    wall — today's hedging pressure.

Reuses :class:`OptionChainSnapshot` (already carries per-strike OI, IV and
gamma) so there is no extra broker fetch beyond the single option-chain call the
GEX endpoint already makes.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from typing import Any

from .greeks import _bs_greeks

# Calendar days per year — the standard expected-move annualisation factor, so
# ``spot * iv * sqrt(1/365)`` is the 1-day 1σ move.
_DAYS_PER_YEAR = 365.0

# Intraday gamma horizon: one calendar day in years (capped at real DTE).
_INTRADAY_T_YEARS = 1.0 / _DAYS_PER_YEAR

# Fallback IV (decimal) used only if no strike carries a usable IV.
_FALLBACK_IV = 0.15


@dataclass
class GammaDensityStrike:
    """Per-strike gamma density at both horizons."""

    strike: float = 0.0
    ce_oi: int = 0
    pe_oi: int = 0
    iv: float = 0.0  # blended strike IV, percent
    density_intraday: float = 0.0
    density_expiry: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable dictionary."""
        return asdict(self)


@dataclass
class ExpectedMoveBand:
    """±1σ / ±2σ expected-move levels around spot (the convexity zone)."""

    sigma_move: float = 0.0
    one_sigma_low: float = 0.0
    one_sigma_high: float = 0.0
    two_sigma_low: float = 0.0
    two_sigma_high: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable dictionary."""
        return asdict(self)


@dataclass
class GammaDensityResult:
    """Full gamma density payload for an underlying / expiry."""

    underlying: str = ""
    exchange: str = ""
    spot_price: float = 0.0
    atm_strike: float = 0.0
    atm_iv: float = 0.0  # percent
    dte_days: float = 0.0
    peak_intraday_strike: float | None = None
    peak_expiry_strike: float | None = None
    intraday_band: ExpectedMoveBand = field(default_factory=ExpectedMoveBand)
    expiry_band: ExpectedMoveBand = field(default_factory=ExpectedMoveBand)
    strikes: list[GammaDensityStrike] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable dictionary."""
        return {
            "underlying": self.underlying,
            "exchange": self.exchange,
            "spot_price": self.spot_price,
            "atm_strike": self.atm_strike,
            "atm_iv": self.atm_iv,
            "dte_days": self.dte_days,
            "peak_intraday_strike": self.peak_intraday_strike,
            "peak_expiry_strike": self.peak_expiry_strike,
            "intraday_band": self.intraday_band.to_dict(),
            "expiry_band": self.expiry_band.to_dict(),
            "strikes": [s.to_dict() for s in self.strikes],
        }


def _blended_iv_decimal(ce_iv: float, pe_iv: float) -> float | None:
    """Average of the usable CE/PE IVs (percent → decimal), or None."""
    sides = [v for v in (ce_iv, pe_iv) if v and v > 0]
    if not sides:
        return None
    return (sum(sides) / len(sides)) / 100.0


def _expected_move_band(spot: float, atm_iv_dec: float, t_years: float) -> ExpectedMoveBand:
    """Build a ±1σ / ±2σ band from spot, ATM IV (decimal) and horizon."""
    sigma = spot * atm_iv_dec * math.sqrt(max(t_years, 1e-9))
    return ExpectedMoveBand(
        sigma_move=round(sigma, 2),
        one_sigma_low=round(spot - sigma, 2),
        one_sigma_high=round(spot + sigma, 2),
        two_sigma_low=round(spot - 2 * sigma, 2),
        two_sigma_high=round(spot + 2 * sigma, 2),
    )


def calculate_gamma_density(
    snapshot: Any,
    spot: float,
    dte_days: float,
    risk_free_rate: float = 0.0,
) -> GammaDensityResult:
    """Calculate the gamma density surface from an option-chain snapshot.

    Args:
        snapshot: An :class:`OptionChainSnapshot` carrying per-strike OI, IV and
            gamma (the same object the GEX endpoint builds).
        spot: Current spot price of the underlying.
        dte_days: Calendar days to expiry (used for the to-expiry horizon and
            both expected-move bands).
        risk_free_rate: Annualised risk-free rate as a decimal (e.g. 0.065).

    Returns:
        A :class:`GammaDensityResult` with per-strike density at both horizons,
        the convexity-zone bands, and the peak-density strikes. Returns an empty
        result if the snapshot has no strikes or spot is non-positive.
    """
    strikes = getattr(snapshot, "strikes", None) or []
    if not strikes or spot <= 0:
        return GammaDensityResult(
            underlying=getattr(snapshot, "underlying", ""),
            exchange=getattr(snapshot, "exchange", ""),
            spot_price=round(spot, 2) if spot > 0 else 0.0,
            dte_days=round(dte_days, 2),
        )

    atm_strike = float(getattr(snapshot, "atm_strike", 0.0) or 0.0)
    t_years = max(dte_days / _DAYS_PER_YEAR, 0.0)
    t_intraday = min(t_years, _INTRADAY_T_YEARS) if t_years > 0 else _INTRADAY_T_YEARS

    # ATM IV (decimal): the ATM strike's blended IV, else the median usable IV.
    atm_iv_dec: float | None = None
    usable_ivs: list[float] = []
    for s in strikes:
        blended = _blended_iv_decimal(getattr(s, "ce_iv", 0.0), getattr(s, "pe_iv", 0.0))
        if blended is not None:
            usable_ivs.append(blended)
            if atm_strike and float(getattr(s, "strike_price", 0.0)) == atm_strike:
                atm_iv_dec = blended
    if atm_iv_dec is None:
        atm_iv_dec = sorted(usable_ivs)[len(usable_ivs) // 2] if usable_ivs else _FALLBACK_IV

    density_strikes: list[GammaDensityStrike] = []
    max_intraday = 0.0
    max_expiry = 0.0
    peak_intraday_strike: float | None = None
    peak_expiry_strike: float | None = None

    for s in strikes:
        k = float(getattr(s, "strike_price", 0.0))
        if k <= 0:
            continue
        ce_oi = int(getattr(s, "ce_oi", 0) or 0)
        pe_oi = int(getattr(s, "pe_oi", 0) or 0)
        ce_gamma = float(getattr(s, "ce_gamma", 0.0) or 0.0)
        pe_gamma = float(getattr(s, "pe_gamma", 0.0) or 0.0)

        # To-expiry density from the snapshot's own greeks.
        density_expiry = ce_gamma * ce_oi + pe_gamma * pe_oi

        # Intraday density: recompute gamma at a 1-day horizon with strike IV.
        ce_iv_dec = (getattr(s, "ce_iv", 0.0) or 0.0) / 100.0 or atm_iv_dec
        pe_iv_dec = (getattr(s, "pe_iv", 0.0) or 0.0) / 100.0 or atm_iv_dec
        ce_g_intra = _bs_greeks("c", spot, k, t_intraday, risk_free_rate, ce_iv_dec).gamma
        pe_g_intra = _bs_greeks("p", spot, k, t_intraday, risk_free_rate, pe_iv_dec).gamma
        density_intraday = ce_g_intra * ce_oi + pe_g_intra * pe_oi

        if density_expiry > max_expiry:
            max_expiry = density_expiry
            peak_expiry_strike = k
        if density_intraday > max_intraday:
            max_intraday = density_intraday
            peak_intraday_strike = k

        blended_pct = _blended_iv_decimal(
            getattr(s, "ce_iv", 0.0), getattr(s, "pe_iv", 0.0)
        )
        density_strikes.append(GammaDensityStrike(
            strike=k,
            ce_oi=ce_oi,
            pe_oi=pe_oi,
            iv=round(blended_pct * 100, 2) if blended_pct is not None else 0.0,
            density_intraday=round(density_intraday, 4),
            density_expiry=round(density_expiry, 4),
        ))

    return GammaDensityResult(
        underlying=getattr(snapshot, "underlying", ""),
        exchange=getattr(snapshot, "exchange", ""),
        spot_price=round(spot, 2),
        atm_strike=atm_strike,
        atm_iv=round(atm_iv_dec * 100, 2),
        dte_days=round(dte_days, 2),
        peak_intraday_strike=peak_intraday_strike,
        peak_expiry_strike=peak_expiry_strike,
        intraday_band=_expected_move_band(spot, atm_iv_dec, _INTRADAY_T_YEARS),
        expiry_band=_expected_move_band(spot, atm_iv_dec, t_years),
        strikes=density_strikes,
    )
