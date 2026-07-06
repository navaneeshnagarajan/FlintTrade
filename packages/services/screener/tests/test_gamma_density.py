"""Tests for the gamma density analytics module (DP2).

All computation is pure and offline — synthetic snapshots only.
"""

from __future__ import annotations

from flinttrade_screener.gamma_density import (
    GammaDensityResult,
    calculate_gamma_density,
)
from flinttrade_screener.option_chain import OptionChainSnapshot, StrikeData


def _snapshot(spot: float = 24000.0, step: float = 100.0, count: int = 6) -> OptionChainSnapshot:
    """Build a small synthetic snapshot with gamma peaking at ATM."""
    strikes: list[StrikeData] = []
    for i in range(-count, count + 1):
        k = spot + i * step
        dist = abs(i)
        gamma = max(0.0001, 0.005 - dist * 0.0006)
        oi = max(1000, 50000 - dist * 5000)
        iv = 15.0 + dist * 0.5
        strikes.append(StrikeData(
            strike_price=k,
            ce_oi=oi,
            pe_oi=oi,
            ce_iv=iv,
            pe_iv=iv + 0.5,
            ce_gamma=gamma,
            pe_gamma=gamma,
            ce_ltp=100.0,
            pe_ltp=100.0,
        ))
    return OptionChainSnapshot(
        underlying="NIFTY",
        exchange="NFO",
        spot_price=spot,
        atm_strike=spot,
        strikes=strikes,
    )


class TestGammaDensity:
    def test_returns_result_with_all_strikes(self):
        result = calculate_gamma_density(_snapshot(), spot=24000.0, dte_days=7.0)
        assert isinstance(result, GammaDensityResult)
        assert len(result.strikes) == 13
        assert result.underlying == "NIFTY"
        assert result.dte_days == 7.0

    def test_peak_density_at_atm(self):
        # Gamma and OI both peak at ATM (24000), so both horizons peak there.
        result = calculate_gamma_density(_snapshot(), spot=24000.0, dte_days=7.0)
        assert result.peak_expiry_strike == 24000.0
        assert result.peak_intraday_strike == 24000.0

    def test_expected_move_bands_widen_with_horizon(self):
        # To-expiry (7d) 1σ move must exceed the intraday (1d) 1σ move.
        result = calculate_gamma_density(_snapshot(), spot=24000.0, dte_days=7.0)
        assert result.expiry_band.sigma_move > result.intraday_band.sigma_move
        assert result.intraday_band.one_sigma_low < 24000.0 < result.intraday_band.one_sigma_high

    def test_atm_iv_taken_from_atm_strike(self):
        # ATM strike IV = mean(15.0, 15.5) = 15.25%.
        result = calculate_gamma_density(_snapshot(), spot=24000.0, dte_days=7.0)
        assert result.atm_iv == 15.25

    def test_empty_snapshot_returns_empty_result(self):
        result = calculate_gamma_density(OptionChainSnapshot(), spot=0.0, dte_days=7.0)
        assert result.strikes == []
        assert result.peak_expiry_strike is None

    def test_to_dict_is_json_serialisable(self):
        import json

        payload = calculate_gamma_density(_snapshot(), spot=24000.0, dte_days=7.0).to_dict()
        loaded = json.loads(json.dumps(payload))
        assert "intraday_band" in loaded
        assert "expiry_band" in loaded
        assert loaded["strikes"][0]["strike"] > 0
