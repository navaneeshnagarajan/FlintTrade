"""Tests for SignalPipeline — init, EMA, fallback, latest signals."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock


class TestSignalPipeline:
    """Test signal pipeline initialisation and helpers."""

    def test_init_defaults(self):
        from flinttrade_ai.pipeline import SignalPipeline

        p = SignalPipeline()
        assert p._broker_client is None
        assert not hasattr(p, "api_key")
        assert p.instruments is not None
        assert len(p.instruments) >= 2
        assert p.interval == "5m"

    def test_init_custom_instruments(self):
        from flinttrade_ai.pipeline import SignalPipeline

        instruments = [{"symbol": "RELIANCE", "exchange": "NSE"}]
        p = SignalPipeline(instruments=instruments)
        assert len(p.instruments) == 1
        assert p.instruments[0]["symbol"] == "RELIANCE"


    def test_fetch_bars_uses_injected_broker_client(self):
        from flinttrade_ai.pipeline import SignalPipeline

        class _Row:
            def model_dump(self):
                return {"timestamp": "2026-07-06", "close": 100.5}

        broker_client = MagicMock()
        broker_client.history = AsyncMock(return_value=[_Row()])
        broker_client.close = AsyncMock()
        p = SignalPipeline(broker_client=broker_client)

        rows = p.fetch_bars("RELIANCE", "NSE")

        assert rows == [{"timestamp": "2026-07-06", "close": 100.5}]
        broker_client.history.assert_awaited_once()
        broker_client.close.assert_not_awaited()

    def test_fetch_bars_sorts_and_deduplicates_for_all_scheduled_consumers(self):
        from flinttrade_ai.pipeline import SignalPipeline

        broker_client = MagicMock()
        broker_client.history = AsyncMock(
            return_value=[
                {"timestamp": "2026-07-10T09:20:00+00:00", "close": 102.0},
                {"timestamp": "2026-07-10T09:15:00+00:00", "close": 100.0},
                {"timestamp": "2026-07-10T09:15:00+00:00", "close": 101.0},
            ]
        )
        broker_client.close = AsyncMock()
        pipeline = SignalPipeline(broker_client=broker_client)

        rows = pipeline.fetch_bars("RELIANCE", "NSE")

        assert rows == [
            {"timestamp": "2026-07-10T09:15:00+00:00", "close": 101.0},
            {"timestamp": "2026-07-10T09:20:00+00:00", "close": 102.0},
        ]

    def test_daily_bar_closes_at_effective_market_session_close(self):
        from flinttrade_ai.pipeline import SignalPipeline

        ist = timezone(timedelta(hours=5, minutes=30))
        now = datetime(2026, 7, 10, 16, 0, tzinfo=ist)
        session_calls: list[tuple[str, str, date]] = []

        def session_for(exchange: str, symbol: str, on: date):
            session_calls.append((exchange, symbol, on))
            return time(9, 15), time(15, 30)

        pipeline = SignalPipeline(interval="1d", clock=lambda: now)
        pipeline.set_market_session_provider(session_for)
        bars = [
            {
                "timestamp": "2026-07-10T09:15:00+05:30",
                "open": 100.0,
                "high": 102.0,
                "low": 99.0,
                "close": 101.0,
                "volume": 10_000.0,
            }
        ]

        assert pipeline._closed_scheduled_bars(
            bars,
            instrument="NSE:RELIANCE",
            exchange="NSE",
            symbol="RELIANCE",
        ) == bars
        assert session_calls == [("NSE", "RELIANCE", date(2026, 7, 10))]

    def test_intraday_closed_bars_require_full_effective_session_membership(self):
        from flinttrade_ai.pipeline import _filter_closed_bars

        ist = timezone(timedelta(hours=5, minutes=30))
        now = datetime(2026, 7, 12, 12, 0, tzinfo=ist)
        rows = [
            {"timestamp": "2026-07-09T10:00:00+05:30", "close": 99.0},
            {"timestamp": "2026-07-10T09:10:00+05:30", "close": 100.0},
            {"timestamp": "2026-07-10T09:15:00+05:30", "close": 101.0},
            {"timestamp": "2026-07-10T15:25:00+05:30", "close": 102.0},
            {"timestamp": "2026-07-10T15:30:00+05:30", "close": 103.0},
            {"timestamp": "2026-07-11T10:00:00+05:30", "close": 104.0},
        ]

        def session_for(_exchange: str, _symbol: str, on: date):
            if on in {date(2026, 7, 9), date(2026, 7, 10)}:
                return time(9, 15), time(15, 30)
            return None

        filtered = _filter_closed_bars(
            rows,
            interval="5m",
            now=now,
            exchange="NSE",
            symbol="RELIANCE",
            market_session_provider=session_for,
        )

        assert [row["close"] for row in filtered] == [99.0, 101.0, 102.0]

    def test_intraday_closed_bars_fail_closed_without_session_provider(self):
        from flinttrade_ai.pipeline import _filter_closed_bars

        bars = [{"timestamp": "2026-07-10T10:00:00+05:30", "close": 100.0}]

        assert _filter_closed_bars(
            bars,
            interval="5m",
            now=datetime(2026, 7, 10, 16, 0, tzinfo=timezone(timedelta(hours=5, minutes=30))),
            exchange="NSE",
            symbol="RELIANCE",
        ) == []

    def test_intraday_closed_bars_fail_closed_for_malformed_session_values(self):
        from flinttrade_ai.pipeline import _filter_closed_bars

        bars = [{"timestamp": "2026-07-10T10:00:00+05:30", "close": 100.0}]

        assert _filter_closed_bars(
            bars,
            interval="5m",
            now=datetime(2026, 7, 10, 16, 0, tzinfo=timezone(timedelta(hours=5, minutes=30))),
            exchange="NSE",
            symbol="RELIANCE",
            market_session_provider=lambda *_args: (
                datetime(2026, 7, 10, 9, 15),
                datetime(2026, 7, 10, 15, 30),
            ),
        ) == []

    def test_intraday_closed_bars_resolve_cross_midnight_rows_to_prior_session(self):
        from flinttrade_ai.pipeline import _filter_closed_bars

        ist = timezone(timedelta(hours=5, minutes=30))
        rows = [
            {"timestamp": "2026-04-17T17:55:00+05:30", "close": 99.0},
            {"timestamp": "2026-04-17T18:00:00+05:30", "close": 100.0},
            {"timestamp": "2026-04-18T00:35:00+05:30", "close": 101.0},
            {"timestamp": "2026-04-18T00:45:00+05:30", "close": 102.0},
        ]

        def session_for(_exchange: str, _symbol: str, on: date):
            if on == date(2026, 4, 17):
                return time(18, 0), time(0, 45)
            return None

        filtered = _filter_closed_bars(
            rows,
            interval="5m",
            now=datetime(2026, 4, 18, 1, 0, tzinfo=ist),
            exchange="MCX",
            symbol="GOLDM",
            market_session_provider=session_for,
        )

        assert [row["close"] for row in filtered] == [100.0, 101.0]

    def test_ema_basic(self):
        from flinttrade_ai.pipeline import SignalPipeline

        data = [1.0, 2.0, 3.0, 4.0, 5.0]
        ema = SignalPipeline._ema(data, 3)
        assert len(ema) == 5
        assert ema[0] == 1.0
        # EMA should trend towards the data
        assert ema[-1] > ema[0]

    def test_ema_empty(self):
        from flinttrade_ai.pipeline import SignalPipeline

        assert SignalPipeline._ema([], 3) == []

    def test_ema_single(self):
        from flinttrade_ai.pipeline import SignalPipeline

        ema = SignalPipeline._ema([42.0], 5)
        assert ema == [42.0]

    def test_ema_crossover_signal_hold(self):
        from flinttrade_ai.pipeline import SignalPipeline

        # Flat data => no crossover => HOLD
        closes = [100.0] * 50
        assert SignalPipeline._ema_crossover_signal(closes) == "HOLD"

    def test_ema_crossover_signal_too_short(self):
        from flinttrade_ai.pipeline import SignalPipeline

        closes = [100.0] * 10
        assert SignalPipeline._ema_crossover_signal(closes) == "HOLD"

    def test_get_latest_signals_empty(self):
        from flinttrade_ai.pipeline import SignalPipeline

        p = SignalPipeline()
        assert p.get_latest_signals() == {}

    def test_get_latest_signals_returns_stored(self):
        from flinttrade_ai.pipeline import SignalPipeline

        p = SignalPipeline()
        p.latest_signals = {"NSE_INDEX:NIFTY": {"signal": "BUY"}}
        assert p.get_latest_signals() == {"NSE_INDEX:NIFTY": {"signal": "BUY"}}

    def test_model_path_default(self, monkeypatch, tmp_path):
        from flinttrade_ai.pipeline import SignalPipeline

        monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(tmp_path))
        p = SignalPipeline()
        assert "signal_model.joblib" in p.model_path
        assert str(tmp_path / "models") in p.model_path

    def test_model_path_custom(self):
        from flinttrade_ai.pipeline import SignalPipeline

        p = SignalPipeline(model_path="/tmp/my_model.joblib")
        assert p.model_path == "/tmp/my_model.joblib"

    def test_export_in_init(self):
        from flinttrade_ai import __all__

        assert "SignalPipeline" in __all__

    def test_import_from_package(self):
        from flinttrade_ai import SignalPipeline

        assert SignalPipeline is not None




class TestLegacyModelMigration:
    """One-shot ~/.flinttrade → workspace_dir() migration for the trained model."""

    def test_legacy_model_copied_into_workspace(self, monkeypatch, tmp_path):
        import flinttrade_ai.pipeline as pipeline_mod
        from flinttrade_ai.pipeline import SignalPipeline

        legacy_home = tmp_path / "legacy-home" / ".flinttrade"
        workspace = tmp_path / "workspace"
        monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(workspace))
        monkeypatch.setattr(pipeline_mod, "_legacy_state_dir", lambda: legacy_home)

        (legacy_home / "models").mkdir(parents=True)
        (legacy_home / "models" / "signal_model.joblib").write_bytes(b"trained-model-bytes")

        p = SignalPipeline()

        migrated = workspace / "models" / "signal_model.joblib"
        assert p.model_path == str(migrated)
        assert migrated.read_bytes() == b"trained-model-bytes"
        # Copy, not move — the legacy file stays behind as a backup.
        assert (legacy_home / "models" / "signal_model.joblib").exists()

    def test_existing_workspace_model_not_clobbered(self, monkeypatch, tmp_path):
        import flinttrade_ai.pipeline as pipeline_mod
        from flinttrade_ai.pipeline import SignalPipeline

        legacy_home = tmp_path / "legacy-home" / ".flinttrade"
        workspace = tmp_path / "workspace"
        monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(workspace))
        monkeypatch.setattr(pipeline_mod, "_legacy_state_dir", lambda: legacy_home)

        (legacy_home / "models").mkdir(parents=True)
        (legacy_home / "models" / "signal_model.joblib").write_bytes(b"legacy")
        (workspace / "models").mkdir(parents=True)
        (workspace / "models" / "signal_model.joblib").write_bytes(b"current")

        SignalPipeline()

        assert (workspace / "models" / "signal_model.joblib").read_bytes() == b"current"

    def test_explicit_model_path_skips_migration(self, monkeypatch, tmp_path):
        import flinttrade_ai.pipeline as pipeline_mod
        from flinttrade_ai.pipeline import SignalPipeline

        legacy_home = tmp_path / "legacy-home" / ".flinttrade"
        workspace = tmp_path / "workspace"
        monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(workspace))
        monkeypatch.setattr(pipeline_mod, "_legacy_state_dir", lambda: legacy_home)

        (legacy_home / "models").mkdir(parents=True)
        (legacy_home / "models" / "signal_model.joblib").write_bytes(b"legacy")

        p = SignalPipeline(model_path=str(tmp_path / "explicit.joblib"))

        assert p.model_path == str(tmp_path / "explicit.joblib")
        assert not (workspace / "models" / "signal_model.joblib").exists()
