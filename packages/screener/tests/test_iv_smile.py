"""Tests for IV smile curve extraction module.

All tests use synthetic option chain data — no API calls required.
"""

from __future__ import annotations


from packages.screener.src.option_chain import OptionChainSnapshot, StrikeData


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_strikes(
    spot: float = 24000.0,
    step: float = 100.0,
    count: int = 10,
    iv_base: float = 15.0,
    put_skew_extra: float = 2.0,
) -> list[StrikeData]:
    """Generate synthetic strike data with a put skew."""
    strikes = []
    for i in range(-count, count + 1):
        k = spot + i * step
        dist = abs(i)
        # Wings have higher IV; puts have extra skew premium
        ce_iv = iv_base + dist * 0.6
        pe_iv = iv_base + dist * 0.6 + (put_skew_extra if i < 0 else 0)
        ce_delta = max(0.05, 0.5 - i * 0.05)
        pe_delta = -max(0.05, 0.5 + i * 0.05)
        strikes.append(StrikeData(
            strike_price=k,
            ce_ltp=max(1.0, 200 - max(0, i) * 10),
            pe_ltp=max(1.0, 200 + min(0, i) * 10),
            ce_iv=ce_iv,
            pe_iv=pe_iv,
            ce_delta=ce_delta,
            pe_delta=pe_delta,
        ))
    return strikes


def _make_snapshot(
    spot: float = 24000.0,
    count: int = 10,
    **kwargs,
) -> OptionChainSnapshot:
    strikes = _make_strikes(spot=spot, count=count, **kwargs)
    return OptionChainSnapshot(
        underlying="NIFTY",
        exchange="NFO",
        spot_price=spot,
        atm_strike=spot,
        strikes=strikes,
    )


# ---------------------------------------------------------------------------
# Smile structure
# ---------------------------------------------------------------------------


class TestIVSmileStructure:
    """Verify the IV smile output structure."""

    def test_strikes_list_populated(self):
        from packages.screener.src.iv_smile import calculate_iv_smile
        snap = _make_snapshot()
        result = calculate_iv_smile(snap, spot=24000.0, expiry_date="26MAR26")
        assert len(result.strikes) > 0

    def test_call_and_put_iv_same_length_as_strikes(self):
        from packages.screener.src.iv_smile import calculate_iv_smile
        snap = _make_snapshot(count=5)
        result = calculate_iv_smile(snap, spot=24000.0)
        assert len(result.call_iv) == len(result.strikes)
        assert len(result.put_iv) == len(result.strikes)

    def test_points_populated(self):
        from packages.screener.src.iv_smile import calculate_iv_smile
        snap = _make_snapshot()
        result = calculate_iv_smile(snap, spot=24000.0)
        assert len(result.points) == len(result.strikes)

    def test_strikes_sorted_ascending(self):
        from packages.screener.src.iv_smile import calculate_iv_smile
        snap = _make_snapshot()
        result = calculate_iv_smile(snap, spot=24000.0)
        assert result.strikes == sorted(result.strikes)

    def test_expiry_date_stored(self):
        from packages.screener.src.iv_smile import calculate_iv_smile
        snap = _make_snapshot()
        result = calculate_iv_smile(snap, spot=24000.0, expiry_date="26MAR26")
        assert result.expiry_date == "26MAR26"

    def test_spot_stored(self):
        from packages.screener.src.iv_smile import calculate_iv_smile
        snap = _make_snapshot(spot=23500.0)
        result = calculate_iv_smile(snap, spot=23500.0)
        assert result.spot == 23500.0


# ---------------------------------------------------------------------------
# ATM IV
# ---------------------------------------------------------------------------


class TestATMIV:
    """Verify ATM IV detection."""

    def test_atm_iv_positive(self):
        from packages.screener.src.iv_smile import calculate_iv_smile
        snap = _make_snapshot()
        result = calculate_iv_smile(snap, spot=24000.0)
        assert result.atm_iv > 0

    def test_atm_strike_near_spot(self):
        from packages.screener.src.iv_smile import calculate_iv_smile
        spot = 24000.0
        snap = _make_snapshot(spot=spot)
        result = calculate_iv_smile(snap, spot=spot)
        # ATM strike should be within one step of spot
        assert abs(result.atm_strike - spot) <= 100

    def test_atm_iv_less_than_wing_iv(self):
        """IV smile should be higher at wings than ATM."""
        from packages.screener.src.iv_smile import calculate_iv_smile
        snap = _make_snapshot(count=5)
        result = calculate_iv_smile(snap, spot=24000.0)
        # Wing IVs (at boundaries) should be higher than ATM
        if len(result.call_iv) > 2:
            max_wing_iv = max(result.call_iv[0], result.call_iv[-1])
            assert max_wing_iv >= result.atm_iv


# ---------------------------------------------------------------------------
# Skew calculation
# ---------------------------------------------------------------------------


class TestIVSkew:
    """Verify put skew calculation."""

    def test_positive_put_skew_detected(self):
        """OTM puts more expensive than OTM calls → positive skew."""
        from packages.screener.src.iv_smile import calculate_iv_smile
        # put_skew_extra=2 makes OTM puts more expensive
        snap = _make_snapshot(put_skew_extra=5.0)
        result = calculate_iv_smile(snap, spot=24000.0)
        assert result.skew > 0
        assert result.has_put_skew

    def test_zero_skew_when_symmetric(self):
        """When IV is symmetric, skew should be near zero."""
        from packages.screener.src.iv_smile import calculate_iv_smile
        snap = _make_snapshot(put_skew_extra=0.0)
        result = calculate_iv_smile(snap, spot=24000.0)
        # Symmetric IV profile → skew near zero (may not be exact due to delta-finding)
        assert abs(result.skew) < 5.0  # Reasonable tolerance

    def test_skew_is_float(self):
        from packages.screener.src.iv_smile import calculate_iv_smile
        snap = _make_snapshot()
        result = calculate_iv_smile(snap, spot=24000.0)
        assert isinstance(result.skew, float)


# ---------------------------------------------------------------------------
# Moneyness calculation
# ---------------------------------------------------------------------------


class TestMoneyness:
    """Verify moneyness field in smile points."""

    def test_atm_moneyness_near_zero(self):
        from packages.screener.src.iv_smile import calculate_iv_smile
        spot = 24000.0
        snap = _make_snapshot(spot=spot)
        result = calculate_iv_smile(snap, spot=spot)
        atm_points = [p for p in result.points if abs(p.strike_price - spot) < 50]
        assert len(atm_points) > 0
        assert abs(atm_points[0].moneyness) < 0.5  # Near 0%

    def test_otm_call_positive_moneyness(self):
        from packages.screener.src.iv_smile import calculate_iv_smile
        spot = 24000.0
        snap = _make_snapshot(spot=spot)
        result = calculate_iv_smile(snap, spot=spot)
        otm_calls = [p for p in result.points if p.strike_price > spot]
        for p in otm_calls:
            assert p.moneyness > 0

    def test_otm_put_negative_moneyness(self):
        from packages.screener.src.iv_smile import calculate_iv_smile
        spot = 24000.0
        snap = _make_snapshot(spot=spot)
        result = calculate_iv_smile(snap, spot=spot)
        otm_puts = [p for p in result.points if p.strike_price < spot]
        for p in otm_puts:
            assert p.moneyness < 0


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestIVSmileEdgeCases:
    """Edge case handling for IV smile calculation."""

    def test_empty_chain_returns_empty_result(self):
        from packages.screener.src.iv_smile import calculate_iv_smile
        empty = OptionChainSnapshot()
        result = calculate_iv_smile(empty, spot=24000.0)
        assert result.strikes == []
        assert result.call_iv == []
        assert result.put_iv == []

    def test_zero_spot_returns_empty_result(self):
        from packages.screener.src.iv_smile import calculate_iv_smile
        snap = _make_snapshot()
        result = calculate_iv_smile(snap, spot=0.0)
        assert result.strikes == []

    def test_missing_iv_handled_as_zero(self):
        """Strikes with ce_iv=0 should produce 0.0 in call_iv list."""
        from packages.screener.src.iv_smile import calculate_iv_smile
        strikes = [
            StrikeData(strike_price=24000, ce_iv=0.0, pe_iv=15.0, ce_delta=0.5, pe_delta=-0.5),
        ]
        snap = OptionChainSnapshot(strikes=strikes, spot_price=24000)
        result = calculate_iv_smile(snap, spot=24000.0)
        assert result.call_iv[0] == 0.0
        assert result.put_iv[0] == 15.0

    def test_single_strike_works(self):
        from packages.screener.src.iv_smile import calculate_iv_smile
        strikes = [
            StrikeData(strike_price=24000, ce_iv=16.0, pe_iv=16.5, ce_delta=0.5, pe_delta=-0.5),
        ]
        snap = OptionChainSnapshot(strikes=strikes, spot_price=24000)
        result = calculate_iv_smile(snap, spot=24000.0)
        assert len(result.strikes) == 1
        assert result.atm_iv > 0
