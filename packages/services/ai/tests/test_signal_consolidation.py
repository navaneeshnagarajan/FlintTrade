"""Contract tests for the canonical mixed-source trading-signal hub."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from flask import Flask


def _bars(count: int = 60) -> list[dict[str, object]]:
    """Return enough deterministic OHLCV rows for one scheduled cycle."""
    return [
        {
            "timestamp": f"2026-07-10T09:{index:02d}:00+05:30",
            "open": 24_000.0 + index,
            "high": 24_010.0 + index,
            "low": 23_990.0 + index,
            "close": 24_000.0 + index,
            "volume": 1_000 + index,
        }
        for index in range(count)
    ]


def test_signal_models_have_explicit_names_and_legacy_aliases() -> None:
    """The three unrelated models remain distinct without breaking old imports."""
    from flinttrade_ai.signal_models import LiveSignal, Signal as LegacyLiveSignal, SignalEvent
    from flinttrade_ai.signals import MLSignal, Signal as LegacyMLSignal
    from flinttrade_backtest.base_strategy import Signal as LegacyStrategySignal
    from flinttrade_backtest.base_strategy import StrategySignal

    assert LiveSignal is SignalEvent
    assert LegacyLiveSignal is SignalEvent
    assert LegacyMLSignal is MLSignal
    assert LegacyStrategySignal is StrategySignal
    assert len({SignalEvent, MLSignal, StrategySignal}) == 3


def test_signal_event_serialises_source_identity() -> None:
    from flinttrade_ai.signal_models import SignalEvent

    event = SignalEvent(
        event_id=7,
        timestamp="2026-07-10T09:20:00+05:30",
        symbol="NIFTY",
        exchange="NSE_INDEX",
        signal_type="BUY",
        source="ml",
        method="ml_model",
        indicator="LightGBM",
        value=24_500.125,
        confidence=0.81234,
        message="NIFTY ML model: BUY",
        metadata={"turbulence_score": 0.25},
    )

    payload = event.to_dict()

    assert payload["event_id"] == 7
    assert payload["source"] == "ml"
    assert payload["exchange"] == "NSE_INDEX"
    assert payload["method"] == "ml_model"
    assert payload["metadata"] == {"turbulence_score": 0.25}


def test_scheduled_pipeline_publishes_completed_cycle() -> None:
    from flinttrade_ai.pipeline import SignalPipeline

    sink = MagicMock()
    pipeline = SignalPipeline(
        instruments=[{"symbol": "NIFTY", "exchange": "NSE_INDEX"}],
        signal_sink=sink,
    )
    pipeline._generator = MagicMock(is_trained=False)
    pipeline.fetch_bars = MagicMock(return_value=_bars())

    results = pipeline.run_cycle()

    assert results["NSE_INDEX:NIFTY"]["method"] == "ema_crossover_fallback"
    sink.assert_called_once_with(results)


def test_sink_failure_does_not_discard_latest_ml_results() -> None:
    from flinttrade_ai.pipeline import SignalPipeline

    sink = MagicMock(side_effect=RuntimeError("hub unavailable"))
    pipeline = SignalPipeline(
        instruments=[{"symbol": "NIFTY", "exchange": "NSE_INDEX"}],
        signal_sink=sink,
    )
    pipeline._generator = MagicMock(is_trained=False)
    pipeline.fetch_bars = MagicMock(return_value=_bars())

    results = pipeline.run_cycle()

    assert pipeline.get_latest_signals() == results
    assert results["NSE_INDEX:NIFTY"]["signal"] == "HOLD"


def test_hub_ingests_ml_cycle_into_recent_feed() -> None:
    from flinttrade_ai.signal_pipeline import LiveSignalPipeline

    hub = LiveSignalPipeline()
    published = hub.ingest_ml_cycle(
        {
            "NSE_INDEX:NIFTY": {
                "symbol": "NIFTY",
                "exchange": "NSE_INDEX",
                "signal": "BUY",
                "confidence": 0.81,
                "ltp": 24_500.0,
                "timestamp": "2026-07-10T09:20:00+05:30",
                "method": "ml_model",
                "turbulence_score": 0.2,
            }
        }
    )

    assert len(published) == 1
    event = hub.get_recent_signals(limit=1)[0]
    assert event is published[0]
    assert event.event_id == 1
    assert event.source == "ml"
    assert event.signal_type == "BUY"
    assert event.indicator == "LightGBM"
    assert event.metadata["turbulence_score"] == 0.2


def test_hub_event_ids_survive_ring_buffer_rollover() -> None:
    from flinttrade_ai.signal_models import SignalEvent
    from flinttrade_ai.signal_pipeline import LiveSignalPipeline, _MAX_SIGNALS

    hub = LiveSignalPipeline()
    for index in range(_MAX_SIGNALS + 5):
        hub.publish_signal(
            SignalEvent(
                symbol=f"TEST{index}",
                source="rule",
                signal_type="ALERT",
            )
        )

    retained = hub.get_signals_after(_MAX_SIGNALS)

    assert len(hub.signals) == _MAX_SIGNALS
    assert hub.latest_event_id == _MAX_SIGNALS + 5
    assert [event.event_id for event in retained] == list(
        range(_MAX_SIGNALS + 1, _MAX_SIGNALS + 6)
    )


def test_sse_uses_monotonic_ids_after_deque_is_full() -> None:
    from flinttrade_ai.signal_models import SignalEvent
    from flinttrade_ai.signal_pipeline import LiveSignalPipeline, _MAX_SIGNALS
    from flinttrade_ai.signal_routes import _sse_generator

    hub = LiveSignalPipeline()
    for index in range(_MAX_SIGNALS + 1):
        hub.publish_signal(
            SignalEvent(symbol=f"TEST{index}", source="rule", signal_type="ALERT")
        )

    frame = next(_sse_generator(hub, last_event_id=_MAX_SIGNALS))
    lines = frame.splitlines()
    payload = json.loads(next(line[6:] for line in lines if line.startswith("data: ")))

    assert f"id: {_MAX_SIGNALS + 1}" in lines
    assert payload["event_id"] == _MAX_SIGNALS + 1


def test_configure_signal_sources_wires_one_hub_and_ml_sink() -> None:
    from flinttrade_ai.signal_routes import configure_signal_sources

    app = Flask(__name__)
    openalgo_client = MagicMock()
    ml_pipeline = MagicMock()

    with patch("flinttrade_ai.signal_routes.SignalPipeline", return_value=ml_pipeline) as constructor:
        first_hub, first_ml = configure_signal_sources(app, openalgo_client)
        second_hub, second_ml = configure_signal_sources(app, openalgo_client)

    assert first_hub is second_hub
    assert first_ml is second_ml is ml_pipeline
    assert app.config["SIGNAL_HUB"] is first_hub
    assert app.config["ML_SIGNAL_PIPELINE"] is ml_pipeline
    constructor.assert_called_once_with(
        openalgo_client=openalgo_client,
        signal_sink=first_hub.ingest_ml_cycle,
    )


def test_ml_signal_job_runs_only_when_market_is_open() -> None:
    from flinttrade_ai.signal_routes import make_ml_signal_job

    ml_pipeline = MagicMock()
    market_is_open = MagicMock(return_value=False)
    job = make_ml_signal_job(ml_pipeline, market_is_open)

    assert job() == {}
    ml_pipeline.run_cycle.assert_not_called()

    market_is_open.return_value = True
    ml_pipeline.run_cycle.return_value = {"NSE_INDEX:NIFTY": {"signal": "BUY"}}

    assert job() == {"NSE_INDEX:NIFTY": {"signal": "BUY"}}
    ml_pipeline.run_cycle.assert_called_once_with()


def test_flask_factory_installs_signal_hub_and_ml_source(monkeypatch, tmp_path) -> None:
    from flinttrade_ai.pipeline import SignalPipeline
    from flinttrade_ai.signal_pipeline import LiveSignalPipeline
    from flinttrade_core.app import create_flask_app

    monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(tmp_path))
    master_password = tmp_path / "master_password"
    master_password.write_text("signal-test-master-password\n", encoding="utf-8")
    master_password.chmod(0o600)
    openalgo_client = MagicMock()
    app = create_flask_app(client=openalgo_client)

    hub = app.config["SIGNAL_HUB"]
    ml_pipeline = app.config["ML_SIGNAL_PIPELINE"]
    assert isinstance(hub, LiveSignalPipeline)
    assert isinstance(ml_pipeline, SignalPipeline)
    assert ml_pipeline._openalgo_client is openalgo_client
    assert ml_pipeline._signal_sink.__self__ is hub
    assert ml_pipeline._signal_sink.__func__ is hub.ingest_ml_cycle.__func__


def test_runtime_registers_five_minute_market_hours_ml_job() -> None:
    from flinttrade_core.app import _wire_ml_signal_runtime

    app = Flask(__name__)
    pipeline = MagicMock()
    app.config["ML_SIGNAL_PIPELINE"] = pipeline
    cron = MagicMock()
    time_scheduler = MagicMock()
    time_scheduler.is_market_open.return_value = False

    assert _wire_ml_signal_runtime(app, cron, time_scheduler) is True

    cron.register.assert_called_once()
    call = cron.register.call_args
    assert call.args[0] == "ml_signal_cycle"
    assert call.kwargs["trigger_type"] == "interval"
    assert call.kwargs["trigger_args"] == {"minutes": 5}

    handler = call.kwargs["handler"]
    assert handler() == {}
    pipeline.run_cycle.assert_not_called()
    time_scheduler.is_market_open.assert_called_with("NSE")

    time_scheduler.is_market_open.return_value = True
    pipeline.run_cycle.return_value = {"NSE_INDEX:NIFTY": {"signal": "BUY"}}
    assert handler() == {"NSE_INDEX:NIFTY": {"signal": "BUY"}}


def test_new_signal_model_names_are_exported() -> None:
    import flinttrade_ai
    import flinttrade_backtest

    assert flinttrade_ai.SignalEvent is not flinttrade_ai.MLSignal
    assert flinttrade_ai.LiveSignal is flinttrade_ai.SignalEvent
    assert flinttrade_backtest.Signal is flinttrade_backtest.StrategySignal
