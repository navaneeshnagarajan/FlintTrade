"""Contract tests for the canonical mixed-source trading-signal hub."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from flask import Flask


def _bars(
    count: int = 60,
    *,
    end: datetime | None = None,
) -> list[dict[str, object]]:
    """Return enough deterministic OHLCV rows for one scheduled cycle."""
    final_stamp = end or datetime.now(timezone.utc) - timedelta(minutes=5)
    first_stamp = final_stamp - timedelta(minutes=5 * (count - 1))
    return [
        {
            "timestamp": (first_stamp + timedelta(minutes=5 * index)).isoformat(),
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


def test_scheduled_pipeline_skips_each_closed_exchange_independently() -> None:
    from flinttrade_ai.pipeline import SignalPipeline

    pipeline = SignalPipeline(
        instruments=[
            {"symbol": "RELIANCE", "exchange": "NSE"},
            {"symbol": "GOLDM", "exchange": "MCX"},
        ],
    )
    pipeline.fetch_bars = MagicMock(return_value=_bars())
    pipeline._generator_for = MagicMock(return_value=MagicMock(is_trained=False))

    results = pipeline.run_cycle(market_is_open=lambda exchange: exchange == "MCX")

    assert list(results) == ["MCX:GOLDM"]
    pipeline.fetch_bars.assert_called_once_with("GOLDM", "MCX")


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


def test_scheduled_pipeline_rejects_stale_bar_batch() -> None:
    from flinttrade_ai.pipeline import SignalPipeline

    pipeline = SignalPipeline(instruments=[{"symbol": "NIFTY", "exchange": "NSE_INDEX"}])
    generator = MagicMock(is_trained=True)
    pipeline.fetch_bars = MagicMock(
        return_value=_bars(end=datetime.now(timezone.utc) - timedelta(days=1)),
    )
    pipeline._generator_for = MagicMock(return_value=generator)

    assert pipeline.run_cycle() == {}
    generator.predict.assert_not_called()


def test_scheduled_pipeline_rejects_invalid_latest_bar_stamp() -> None:
    from flinttrade_ai.pipeline import SignalPipeline

    bars = _bars()
    bars[-1]["timestamp"] = "not-a-timestamp"
    pipeline = SignalPipeline(instruments=[{"symbol": "NIFTY", "exchange": "NSE_INDEX"}])
    generator = MagicMock(is_trained=True)
    pipeline.fetch_bars = MagicMock(return_value=bars)
    pipeline._generator_for = MagicMock(return_value=generator)

    assert pipeline.run_cycle() == {}
    generator.predict.assert_not_called()


def test_failed_ml_prediction_uses_fallback_provenance() -> None:
    from flinttrade_ai.pipeline import SignalPipeline
    from flinttrade_ai.signals import MLSignal

    pipeline = SignalPipeline(instruments=[{"symbol": "NIFTY", "exchange": "NSE_INDEX"}])
    generator = MagicMock(is_trained=True)
    generator.predict.return_value = MLSignal(error="model exploded")
    pipeline.fetch_bars = MagicMock(return_value=_bars())
    pipeline._generator_for = MagicMock(return_value=generator)

    result = pipeline.run_cycle()["NSE_INDEX:NIFTY"]

    assert result["method"] == "ema_crossover_fallback"
    assert result["confidence"] == 0.0


def test_scheduled_pipeline_preserves_validated_latest_bar_timestamp() -> None:
    from flinttrade_ai.pipeline import SignalPipeline

    bars = _bars()
    pipeline = SignalPipeline(instruments=[{"symbol": "NIFTY", "exchange": "NSE_INDEX"}])
    pipeline.fetch_bars = MagicMock(return_value=bars)
    pipeline._generator_for = MagicMock(return_value=MagicMock(is_trained=False))

    result = pipeline.run_cycle()["NSE_INDEX:NIFTY"]

    assert result["timestamp"] == bars[-1]["timestamp"]


def test_scheduled_pipeline_accepts_openalgo_daily_interval() -> None:
    from flinttrade_ai.pipeline import SignalPipeline

    now = datetime(2026, 7, 13, 5, 0, tzinfo=timezone.utc)
    bars = _bars(end=datetime(2026, 7, 10, 10, 0, tzinfo=timezone.utc))
    pipeline = SignalPipeline(
        instruments=[{"symbol": "NIFTY", "exchange": "NSE_INDEX"}],
        interval="D",
        clock=lambda: now,
    )
    pipeline.fetch_bars = MagicMock(return_value=bars)
    pipeline._generator_for = MagicMock(return_value=MagicMock(is_trained=False))

    assert "NSE_INDEX:NIFTY" in pipeline.run_cycle()


def test_scheduled_pipeline_preserves_explicitly_empty_instruments() -> None:
    from flinttrade_ai.pipeline import SignalPipeline

    pipeline = SignalPipeline(instruments=[])
    pipeline.fetch_bars = MagicMock()

    assert pipeline.instruments == []
    assert pipeline.run_cycle() == {}
    pipeline.fetch_bars.assert_not_called()


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
    assert event is not published[0]
    assert event.to_dict() == published[0].to_dict()
    assert event.event_id == 1
    assert event.source == "ml"
    assert event.signal_type == "BUY"
    assert event.indicator == "LightGBM"
    assert event.metadata["turbulence_score"] == 0.2


def test_recent_rule_events_preserve_exchange_qualified_identities() -> None:
    from flinttrade_ai.signal_models import SignalEvent
    from flinttrade_ai.signal_pipeline import LiveSignalPipeline

    hub = LiveSignalPipeline()
    hub.publish_signal(SignalEvent(exchange="NSE", symbol="RELIANCE", source="rule"))
    hub.publish_signal(SignalEvent(exchange="BSE", symbol="RELIANCE", source="rule"))

    assert [(event.exchange, event.symbol) for event in hub.get_recent_signals()] == [
        ("BSE", "RELIANCE"),
        ("NSE", "RELIANCE"),
    ]


def test_rule_events_replay_both_exchange_qualified_identities() -> None:
    from flinttrade_ai.signal_pipeline import LiveSignalPipeline
    from flinttrade_ai.signal_routes import _sse_generator

    hub = LiveSignalPipeline(
        instruments=["NSE:RELIANCE", "BSE:RELIANCE"],
        indicators=[{"name": "RSI", "params": {"period": 1}}],
        thresholds={"rsi_oversold": 30.0, "rsi_overbought": 70.0},
    )
    for ltp in (1_400.0, 1_401.0, 1_405.0):
        hub.process_tick("NSE", "RELIANCE", ltp)
    for ltp in (1_500.0, 1_499.0, 1_495.0):
        hub.process_tick("BSE", "RELIANCE", ltp)

    replay = _sse_generator(hub, last_event_id=0)
    payloads = [json.loads(next(replay).split("data: ", 1)[1]) for _ in range(hub.latest_event_id)]

    assert [
        (payload["event_id"], payload["exchange"], payload["symbol"], payload["signal_type"]) for payload in payloads
    ] == [
        (1, "NSE", "RELIANCE", "SELL"),
        (2, "BSE", "RELIANCE", "BUY"),
    ]


def test_hub_labels_scheduled_ema_fallback_without_claiming_ml() -> None:
    from flinttrade_ai.signal_pipeline import LiveSignalPipeline

    hub = LiveSignalPipeline()
    published = hub.ingest_ml_cycle(
        {
            "NSE_INDEX:NIFTY": {
                "symbol": "NIFTY",
                "exchange": "NSE_INDEX",
                "signal": "HOLD",
                "confidence": 0.5,
                "ltp": 24_500.0,
                "method": "ema_crossover_fallback",
            }
        }
    )

    assert published[0].source == "fallback"
    assert published[0].indicator == "EMA_Cross"


def test_hub_keeps_turbulence_override_on_the_fallback_source() -> None:
    from flinttrade_ai.signal_pipeline import LiveSignalPipeline

    hub = LiveSignalPipeline()
    published = hub.ingest_ml_cycle(
        {
            "NSE_INDEX:NIFTY": {
                "symbol": "NIFTY",
                "exchange": "NSE_INDEX",
                "signal": "HOLD",
                "confidence": 0.5,
                "ltp": 24_500.0,
                "method": "ema_crossover_fallback+turbulence_override",
            }
        }
    )

    assert published[0].source == "fallback"
    assert published[0].method == "ema_crossover_fallback+turbulence_override"


def test_hub_rejects_unknown_scheduled_methods_instead_of_mislabelling_them(
    caplog,
) -> None:
    from flinttrade_ai.signal_pipeline import LiveSignalPipeline

    hub = LiveSignalPipeline()
    published = hub.ingest_ml_cycle(
        {
            "NSE_INDEX:NIFTY": {
                "symbol": "NIFTY",
                "exchange": "NSE_INDEX",
                "signal": "BUY",
                "confidence": 0.8,
                "ltp": 24_500.0,
                "method": "future_manual_method",
            }
        }
    )

    assert published == []
    assert hub.get_recent_signals() == []
    assert "Unknown scheduled signal method" in caplog.text


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
    assert [event.event_id for event in retained] == list(range(_MAX_SIGNALS + 1, _MAX_SIGNALS + 6))


def test_sse_uses_monotonic_ids_after_deque_is_full() -> None:
    from flinttrade_ai.signal_models import SignalEvent
    from flinttrade_ai.signal_pipeline import LiveSignalPipeline, _MAX_SIGNALS
    from flinttrade_ai.signal_routes import _sse_generator

    hub = LiveSignalPipeline()
    for index in range(_MAX_SIGNALS + 1):
        hub.publish_signal(SignalEvent(symbol=f"TEST{index}", source="rule", signal_type="ALERT"))

    frame = next(_sse_generator(hub, last_event_id=_MAX_SIGNALS))
    lines = frame.splitlines()
    payload = json.loads(next(line[6:] for line in lines if line.startswith("data: ")))

    assert f"id: {hub.sse_event_id(_MAX_SIGNALS + 1)}" in lines
    assert payload["event_id"] == _MAX_SIGNALS + 1


def test_sse_cursor_from_prior_process_replays_every_current_process_event() -> None:
    from flinttrade_ai.signal_models import SignalEvent
    from flinttrade_ai.signal_pipeline import LiveSignalPipeline
    from flinttrade_ai.signal_routes import _sse_generator

    prior = LiveSignalPipeline(stream_id="prior-process")
    prior.publish_signal(SignalEvent(symbol="OLD", source="rule", signal_type="ALERT"))
    stale_cursor = prior.sse_event_id(prior.latest_event_id)

    current = LiveSignalPipeline(stream_id="current-process")
    current.publish_signal(SignalEvent(symbol="CURRENT-1", source="rule", signal_type="ALERT"))
    current.publish_signal(SignalEvent(symbol="CURRENT-2", source="rule", signal_type="ALERT"))

    replay = _sse_generator(current, last_event_id=stale_cursor, heartbeat_interval=0.0)
    control = next(replay)
    control_payload = json.loads(control.split("data: ", 1)[1])
    frames = [next(replay), next(replay)]

    assert control_payload["reason"] == "stream_changed"
    assert control_payload["requested_event_id"] == 1
    assert [json.loads(frame.split("data: ", 1)[1])["event_id"] for frame in frames] == [1, 2]
    assert [frame.splitlines()[0] for frame in frames] == [
        "id: current-process:1",
        "id: current-process:2",
    ]

    legacy_replay = _sse_generator(current, last_event_id="1", heartbeat_interval=0.0)
    legacy_control = json.loads(next(legacy_replay).split("data: ", 1)[1])
    assert legacy_control["reason"] == "legacy_cursor"
    assert [
        json.loads(next(legacy_replay).split("data: ", 1)[1])["event_id"]
        for _ in range(2)
    ] == [1, 2]

    same_process_replay = _sse_generator(
        current,
        last_event_id=current.sse_event_id(1),
        heartbeat_interval=0.0,
    )
    assert json.loads(next(same_process_replay).split("data: ", 1)[1])["event_id"] == 2


def test_sse_signals_replay_loss_then_replays_retained_ring() -> None:
    from flinttrade_ai.signal_models import SignalEvent
    from flinttrade_ai.signal_pipeline import LiveSignalPipeline, _MAX_SIGNALS
    from flinttrade_ai.signal_routes import _sse_generator

    hub = LiveSignalPipeline()
    for index in range(_MAX_SIGNALS + 2):
        hub.publish_signal(SignalEvent(symbol=f"TEST{index}", source="rule", signal_type="ALERT"))

    replay = _sse_generator(hub, last_event_id=0, heartbeat_interval=0.0)
    control = next(replay)
    control_payload = json.loads(control.split("data: ", 1)[1])

    assert control.startswith("event: replay-loss\n")
    assert "id:" not in control
    assert control_payload == {
        "reason": "cursor_before_retained",
        "requested_event_id": 0,
        "oldest_available_event_id": 3,
        "newest_available_event_id": _MAX_SIGNALS + 2,
    }
    replayed_ids = [
        json.loads(next(replay).split("data: ", 1)[1])["event_id"] for _ in range(_MAX_SIGNALS)
    ]
    assert replayed_ids == list(range(3, _MAX_SIGNALS + 3))


def test_sse_signals_restart_cursor_loss_then_replays_current_process() -> None:
    from flinttrade_ai.signal_models import SignalEvent
    from flinttrade_ai.signal_pipeline import LiveSignalPipeline
    from flinttrade_ai.signal_routes import _sse_generator

    hub = LiveSignalPipeline()
    hub.publish_signal(SignalEvent(symbol="CURRENT-1", source="rule", signal_type="ALERT"))
    hub.publish_signal(SignalEvent(symbol="CURRENT-2", source="rule", signal_type="ALERT"))

    replay = _sse_generator(hub, last_event_id=500, heartbeat_interval=0.0)
    control = next(replay)
    control_payload = json.loads(control.split("data: ", 1)[1])

    assert control.startswith("event: replay-loss\n")
    assert "id:" not in control
    assert control_payload == {
        "reason": "cursor_ahead_of_process",
        "requested_event_id": 500,
        "oldest_available_event_id": 1,
        "newest_available_event_id": 2,
    }
    replayed_ids = [json.loads(next(replay).split("data: ", 1)[1])["event_id"] for _ in range(2)]
    assert replayed_ids == [1, 2]


def test_sse_signals_replay_loss_after_live_ring_overflow() -> None:
    from flinttrade_ai.signal_models import SignalEvent
    from flinttrade_ai.signal_pipeline import LiveSignalPipeline, _MAX_SIGNALS
    from flinttrade_ai.signal_routes import _sse_generator

    hub = LiveSignalPipeline()
    stream = _sse_generator(hub, heartbeat_interval=0.0)
    assert next(stream) == ": heartbeat\n\n"

    for index in range(_MAX_SIGNALS + 2):
        hub.publish_signal(SignalEvent(symbol=f"LIVE{index}", source="rule", signal_type="ALERT"))

    control = next(stream)
    control_payload = json.loads(control.split("data: ", 1)[1])

    assert control.startswith("event: replay-loss\n")
    assert "id:" not in control
    assert control_payload == {
        "reason": "cursor_before_retained",
        "requested_event_id": 0,
        "oldest_available_event_id": 3,
        "newest_available_event_id": _MAX_SIGNALS + 2,
    }
    assert json.loads(next(stream).split("data: ", 1)[1])["event_id"] == 3


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
    assert ml_pipeline.update_instruments.call_count == 2
    ml_pipeline.update_instruments.assert_called_with(first_hub.get_config().instruments)


def test_non_default_live_roster_drives_the_installed_ml_job(monkeypatch, tmp_path) -> None:
    from flinttrade_ai.signal_routes import configure_signal_sources, make_ml_signal_job

    monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(tmp_path))
    app = Flask(__name__)
    hub, ml_pipeline = configure_signal_sources(app, MagicMock())
    assert ml_pipeline is not None
    hub.update_config(instruments=["NSE:RELIANCE"])
    ml_pipeline.fetch_bars = MagicMock(return_value=_bars())
    ml_pipeline._generator_for = MagicMock(return_value=MagicMock(is_trained=False))

    results = make_ml_signal_job(ml_pipeline, lambda _exchange: True)()

    assert list(results) == ["NSE:RELIANCE"]
    ml_pipeline.fetch_bars.assert_called_once_with("RELIANCE", "NSE")


def test_ml_signal_job_runs_only_when_market_is_open() -> None:
    from flinttrade_ai.signal_routes import make_ml_signal_job

    ml_pipeline = MagicMock()
    ml_pipeline.instruments = [{"symbol": "NIFTY", "exchange": "NSE_INDEX"}]
    market_is_open = MagicMock(return_value=False)
    job = make_ml_signal_job(ml_pipeline, market_is_open)

    assert job() == {}
    ml_pipeline.run_cycle.assert_not_called()

    market_is_open.return_value = True
    ml_pipeline.run_cycle.return_value = {"NSE_INDEX:NIFTY": {"signal": "BUY"}}

    assert job() == {"NSE_INDEX:NIFTY": {"signal": "BUY"}}
    ml_pipeline.run_cycle.assert_called_once()
    predicate = ml_pipeline.run_cycle.call_args.kwargs["market_is_open"]
    assert predicate("NSE_INDEX") is True


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
    rules = {rule.rule for rule in app.url_map.iter_rules()}
    assert "/api/v1/signals/recent" in rules
    assert "/api/v1/signals/active" not in rules
    assert "/api/v1/signals" not in rules


def test_runtime_registers_five_minute_per_exchange_market_hours_ml_job(tmp_path) -> None:
    from flinttrade_core.app import _wire_ml_signal_runtime

    app = Flask(__name__)
    pipeline = MagicMock()
    pipeline.model_path = str(tmp_path / "signal_model.joblib")
    pipeline.instruments = [
        {"symbol": "NIFTY", "exchange": "NSE_INDEX"},
        {"symbol": "GOLDM", "exchange": "MCX"},
    ]
    app.config["ML_SIGNAL_PIPELINE"] = pipeline
    cron = MagicMock()
    time_scheduler = MagicMock()
    time_scheduler.is_market_open.side_effect = lambda exchange: exchange == "MCX"

    assert _wire_ml_signal_runtime(app, cron, time_scheduler) is True

    calls = {call.args[0]: call for call in cron.register.call_args_list}
    call = calls["ml_signal_cycle"]
    assert call.args[0] == "ml_signal_cycle"
    assert call.kwargs["trigger_type"] == "interval"
    assert call.kwargs["trigger_args"] == {"minutes": 5}

    handler = call.kwargs["handler"]
    pipeline.run_cycle.return_value = {"MCX:GOLDM": {"signal": "BUY"}}
    assert handler() == {"MCX:GOLDM": {"signal": "BUY"}}
    assert [call.args[0] for call in time_scheduler.is_market_open.call_args_list] == [
        "NSE_INDEX",
        "MCX",
    ]
    predicate = pipeline.run_cycle.call_args.kwargs["market_is_open"]
    assert predicate("NSE_INDEX") is False
    assert predicate("MCX") is True


def test_new_signal_model_names_are_exported() -> None:
    import flinttrade_ai
    import flinttrade_backtest

    assert flinttrade_ai.SignalEvent is not flinttrade_ai.MLSignal
    assert flinttrade_ai.LiveSignal is flinttrade_ai.SignalEvent
    assert flinttrade_backtest.Signal is flinttrade_backtest.StrategySignal
