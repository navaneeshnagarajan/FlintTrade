"""Tests for OI Profile with butterfly calculation module.

All tests use synthetic option chain data — no API calls required.
"""

from __future__ import annotations


from flinttrade_screener.option_chain import OptionChainSnapshot, StrikeData


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_strikes(
    spot: float = 24000.0,
    step: float = 100.0,
    count: int = 5,
    ce_oi_base: int = 50000,
    pe_oi_base: int = 40000,
) -> list[StrikeData]:
    strikes = []
    for i in range(-count, count + 1):
        k = spot + i * step
        dist = abs(i)
        ce_oi = max(1000, ce_oi_base - dist * 4000)
        pe_oi = max(1000, pe_oi_base - dist * 3500)
        strikes.append(StrikeData(
            strike_price=k,
            ce_oi=ce_oi,
            pe_oi=pe_oi,
            ce_volume=ce_oi // 10,
            pe_volume=pe_oi // 10,
        ))
    return strikes


def _make_snapshot(spot: float = 24000.0, **kwargs) -> OptionChainSnapshot:
    strikes = _make_strikes(spot=spot, **kwargs)
    return OptionChainSnapshot(
        underlying="NIFTY",
        exchange="NFO",
        spot_price=spot,
        atm_strike=spot,
        strikes=strikes,
    )


def _make_candles(
    spot: float = 24000.0,
    n: int = 10,
    base_ts: int = 1711900000,
) -> list[dict]:
    candles = []
    for i in range(n):
        candles.append({
            "time": base_ts + i * 300,
            "open": spot + i * 5,
            "high": spot + i * 5 + 20,
            "low": spot + i * 5 - 10,
            "close": spot + i * 5 + 10,
            "volume": 5000,
            "oi": 100000 + i * 1000,
        })
    return candles


# ---------------------------------------------------------------------------
# OI butterfly
# ---------------------------------------------------------------------------


class TestOIButterfly:
    """Verify OI butterfly calculation."""

    def test_butterfly_equals_ce_minus_pe(self):
        from flinttrade_screener.oi_profile import calculate_oi_profile
        snap = _make_snapshot()
        result = calculate_oi_profile(snap, futures_candles=[])
        for i, ps in enumerate(result.profile_strikes):
            expected = ps.ce_oi - ps.pe_oi
            assert ps.oi_butterfly == expected

    def test_butterfly_positive_when_ce_heavy(self):
        """Strikes where CE OI > PE OI should have positive butterfly."""
        from flinttrade_screener.oi_profile import calculate_oi_profile
        snap = _make_snapshot(ce_oi_base=100000, pe_oi_base=10000)
        result = calculate_oi_profile(snap, futures_candles=[])
        # At ATM, ce_oi >> pe_oi → positive butterfly
        atm_strikes = [ps for ps in result.profile_strikes if ps.strike_price == 24000]
        assert len(atm_strikes) == 1
        assert atm_strikes[0].oi_butterfly > 0
        assert atm_strikes[0].is_call_heavy

    def test_butterfly_negative_when_pe_heavy(self):
        """Strikes where PE OI > CE OI should have negative butterfly."""
        from flinttrade_screener.oi_profile import calculate_oi_profile
        snap = _make_snapshot(ce_oi_base=10000, pe_oi_base=100000)
        result = calculate_oi_profile(snap, futures_candles=[])
        atm_strikes = [ps for ps in result.profile_strikes if ps.strike_price == 24000]
        assert len(atm_strikes) == 1
        assert atm_strikes[0].oi_butterfly < 0
        assert atm_strikes[0].is_put_heavy

    def test_oi_butterfly_list_matches_strikes(self):
        from flinttrade_screener.oi_profile import calculate_oi_profile
        snap = _make_snapshot()
        result = calculate_oi_profile(snap, futures_candles=[])
        assert len(result.oi_butterfly) == len(result.strikes)
        # Verify values are consistent with profile_strikes
        for i, (butterfly, ps) in enumerate(zip(result.oi_butterfly, result.profile_strikes)):
            assert butterfly == ps.oi_butterfly


# ---------------------------------------------------------------------------
# OI change
# ---------------------------------------------------------------------------


class TestOIChange:
    """Verify OI change calculation when previous snapshot provided."""

    def test_oi_change_is_unavailable_without_previous_snapshot(self):
        """A current-only snapshot must not invent change from a zero baseline."""
        from flinttrade_screener.oi_profile import calculate_oi_profile
        snap = _make_snapshot()
        result = calculate_oi_profile(snap, futures_candles=[], previous_snapshot=None)

        assert result.oi_change_available is False
        assert result.oi_change == [None] * len(result.strikes)
        assert result.ce_oi_change == [None] * len(result.strikes)
        assert result.pe_oi_change == [None] * len(result.strikes)
        assert all(strike.ce_oi_change is None for strike in result.profile_strikes)
        assert all(strike.pe_oi_change is None for strike in result.profile_strikes)

    def test_new_strike_does_not_infer_change_from_zero(self):
        """A strike absent from the prior snapshot has no comparable OI delta."""
        from flinttrade_screener.oi_profile import calculate_oi_profile

        prev = _make_snapshot()
        curr = _make_snapshot()
        curr.strikes.append(StrikeData(strike_price=24600, ce_oi=12345, pe_oi=23456))

        result = calculate_oi_profile(curr, futures_candles=[], previous_snapshot=prev)
        new_idx = result.strikes.index(24600.0)

        assert result.oi_change_available is True
        assert result.ce_oi_change[new_idx] is None
        assert result.pe_oi_change[new_idx] is None
        assert result.oi_change[new_idx] is None

    def test_previous_snapshot_without_matching_strikes_does_not_claim_change_availability(self):
        from flinttrade_screener.oi_profile import calculate_oi_profile

        curr = _make_snapshot()
        prev = OptionChainSnapshot(
            underlying="NIFTY",
            exchange="NFO",
            spot_price=25000.0,
            atm_strike=25000.0,
            strikes=[StrikeData(strike_price=26000.0, ce_oi=100, pe_oi=200)],
        )

        result = calculate_oi_profile(curr, futures_candles=[], previous_snapshot=prev)

        assert result.oi_change_available is False
        assert all(change is None for change in result.oi_change)

    def test_oi_change_detects_increase(self):
        from flinttrade_screener.oi_profile import calculate_oi_profile
        prev = _make_snapshot(ce_oi_base=50000, pe_oi_base=40000)
        curr = _make_snapshot(ce_oi_base=50000, pe_oi_base=40000)
        # Manually increase OI at ATM strike in curr
        for s in curr.strikes:
            if s.strike_price == 24000:
                s.ce_oi += 10000
        result = calculate_oi_profile(curr, futures_candles=[], previous_snapshot=prev)
        atm_idx = result.strikes.index(24000.0)
        assert result.ce_oi_change[atm_idx] == 10000

    def test_oi_change_detects_decrease(self):
        from flinttrade_screener.oi_profile import calculate_oi_profile
        prev = _make_snapshot(pe_oi_base=40000)
        curr = _make_snapshot(pe_oi_base=40000)
        for s in curr.strikes:
            if s.strike_price == 24000:
                s.pe_oi -= 5000
        result = calculate_oi_profile(curr, futures_candles=[], previous_snapshot=prev)
        atm_idx = result.strikes.index(24000.0)
        assert result.pe_oi_change[atm_idx] == -5000

    def test_oi_change_list_length(self):
        from flinttrade_screener.oi_profile import calculate_oi_profile
        prev = _make_snapshot()
        curr = _make_snapshot()
        result = calculate_oi_profile(curr, futures_candles=[], previous_snapshot=prev)
        assert len(result.oi_change) == len(result.strikes)
        assert len(result.ce_oi_change) == len(result.strikes)
        assert len(result.pe_oi_change) == len(result.strikes)


# ---------------------------------------------------------------------------
# Futures OHLCV
# ---------------------------------------------------------------------------


class TestFuturesOverlay:
    """Verify futures candle parsing."""

    def test_futures_candles_parsed(self):
        from flinttrade_screener.oi_profile import calculate_oi_profile
        snap = _make_snapshot()
        candles = _make_candles(n=5)
        result = calculate_oi_profile(snap, futures_candles=candles)
        assert len(result.futures_ohlcv) == 5

    def test_futures_candle_fields(self):
        from flinttrade_screener.oi_profile import calculate_oi_profile
        snap = _make_snapshot()
        candles = _make_candles(n=3)
        result = calculate_oi_profile(snap, futures_candles=candles)
        first = result.futures_ohlcv[0]
        assert first.timestamp > 0
        assert first.open > 0
        assert first.high >= first.low
        assert first.close > 0

    def test_empty_candles_ok(self):
        from flinttrade_screener.oi_profile import calculate_oi_profile
        snap = _make_snapshot()
        result = calculate_oi_profile(snap, futures_candles=[])
        assert result.futures_ohlcv == []


# ---------------------------------------------------------------------------
# Key levels
# ---------------------------------------------------------------------------


class TestKeyLevels:
    """Verify max CE / PE strike detection."""

    def test_max_ce_strike_populated(self):
        from flinttrade_screener.oi_profile import calculate_oi_profile
        snap = _make_snapshot()
        result = calculate_oi_profile(snap, futures_candles=[])
        assert result.max_ce_strike > 0

    def test_max_pe_strike_populated(self):
        from flinttrade_screener.oi_profile import calculate_oi_profile
        snap = _make_snapshot()
        result = calculate_oi_profile(snap, futures_candles=[])
        assert result.max_pe_strike > 0

    def test_max_ce_strike_has_highest_ce_oi(self):
        from flinttrade_screener.oi_profile import calculate_oi_profile
        snap = _make_snapshot()
        result = calculate_oi_profile(snap, futures_candles=[])
        ce_at_max = next(
            (ps.ce_oi for ps in result.profile_strikes if ps.strike_price == result.max_ce_strike),
            0,
        )
        for ps in result.profile_strikes:
            assert ce_at_max >= ps.ce_oi

    def test_all_zero_oi_has_no_max_strikes(self):
        from flinttrade_screener.oi_profile import calculate_oi_profile

        snap = _make_snapshot()
        for strike in snap.strikes:
            strike.ce_oi = 0
            strike.pe_oi = 0

        result = calculate_oi_profile(snap, futures_candles=[])

        assert result.max_ce_strike is None
        assert result.max_pe_strike is None


# ---------------------------------------------------------------------------
# Total OI property
# ---------------------------------------------------------------------------


class TestTotalOI:
    """Verify OIProfileStrike computed properties."""

    def test_total_oi_equals_ce_plus_pe(self):
        from flinttrade_screener.oi_profile import OIProfileStrike
        ps = OIProfileStrike(strike_price=24000, ce_oi=30000, pe_oi=25000, oi_butterfly=5000)
        assert ps.total_oi == 55000


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestOIProfileEdgeCases:
    """Edge case handling."""

    def test_empty_chain_returns_empty(self):
        from flinttrade_screener.oi_profile import calculate_oi_profile
        empty = OptionChainSnapshot()
        result = calculate_oi_profile(empty, futures_candles=[])
        assert result.strikes == []
        assert result.oi_butterfly == []

    def test_strikes_sorted_ascending(self):
        from flinttrade_screener.oi_profile import calculate_oi_profile
        snap = _make_snapshot()
        result = calculate_oi_profile(snap, futures_candles=[])
        assert result.strikes == sorted(result.strikes)
