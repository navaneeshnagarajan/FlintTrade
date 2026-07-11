"""Signal pipeline — scheduled cycle that fetches bars, computes indicators,
runs ML model prediction, and emits trading signals.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import shutil
import tempfile
import threading
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .signal_models import normalise_instrument_identity

logger = logging.getLogger("flinttrade.ai.pipeline")

_IST = timezone(timedelta(hours=5, minutes=30))
_INTERVAL_PATTERN = re.compile(r"(?P<count>[1-9][0-9]*)(?P<unit>[mhd])", re.IGNORECASE)


def _parse_bar_timestamp(value: object) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        text = value.strip()
        try:
            parsed = datetime.fromisoformat(text[:-1] + "+00:00" if text.endswith(("Z", "z")) else text)
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=_IST)
    return parsed.astimezone(timezone.utc)


def _interval_duration(value: str) -> timedelta | None:
    raw_value = value.strip()
    if raw_value == "D":
        return timedelta(days=1)
    match = _INTERVAL_PATTERN.fullmatch(raw_value)
    if match is None:
        return None
    count = int(match.group("count"))
    unit = match.group("unit").lower()
    if unit == "m":
        return timedelta(minutes=count)
    if unit == "h":
        return timedelta(hours=count)
    return timedelta(days=count)


def _temporary_model_path(target: Path) -> Path:
    descriptor, name = tempfile.mkstemp(
        prefix=f"{target.name}.candidate.",
        suffix=target.suffix,
        dir=target.parent,
    )
    os.close(descriptor)
    return Path(name)


def _replace_shared_model_pair(candidate: Path, target: Path) -> None:
    """Replace the checksum then atomically publish the corresponding model file."""
    candidate_checksum = Path(f"{candidate}.sha256")
    target_checksum = Path(f"{target}.sha256")
    if not candidate.exists() or not candidate_checksum.exists():
        raise OSError("candidate persistence did not produce model and checksum files")

    previous_checksum = target_checksum.read_bytes() if target_checksum.exists() else None
    candidate_checksum.replace(target_checksum)
    try:
        candidate.replace(target)
    except BaseException:
        if previous_checksum is None:
            target_checksum.unlink(missing_ok=True)
        else:
            restore_path = _temporary_model_path(target_checksum)
            try:
                restore_path.write_bytes(previous_checksum)
                restore_path.replace(target_checksum)
            finally:
                restore_path.unlink(missing_ok=True)
        raise


def _normalise_scheduled_instruments(
    instruments: list[dict[str, Any] | str],
) -> list[dict[str, str]]:
    """Return a deduplicated scheduled roster from qualified identities."""
    normalised: list[dict[str, str]] = []
    seen: set[str] = set()
    for instrument in instruments:
        if isinstance(instrument, str):
            identity = normalise_instrument_identity(instrument)
        elif isinstance(instrument, dict):
            identity = normalise_instrument_identity(
                f"{instrument.get('exchange', '')}:{instrument.get('symbol', '')}"
            )
        else:
            raise ValueError("scheduled instruments must be mappings or EXCHANGE:SYMBOL strings")
        if identity in seen:
            continue
        seen.add(identity)
        exchange, symbol = identity.split(":", 1)
        normalised.append({"symbol": symbol, "exchange": exchange})
    return normalised


def _legacy_state_dir() -> Path:
    """Pre-workspace_dir() state directory (a fixed ``~/.flinttrade`` on every OS)."""
    return Path.home() / ".flinttrade"


def _migrate_legacy_model_file(legacy: Path, new: Path) -> None:
    """One-shot copy of a pre-``workspace_dir()`` trained model into the workspace.

    The model default moved from ``~/.flinttrade`` to ``workspace_dir()``
    (macOS: ``~/Library/Application Support/flinttrade``; Windows:
    ``%APPDATA%/flinttrade``) without a migration, silently orphaning an
    already-trained model on those platforms. Copy — never move; the legacy
    file stays behind as a backup — when the new path is absent and the legacy
    one exists. Its SHA-256 sidecar is copied only when present; unsigned legacy
    models remain unsigned. No-op on Linux where the two paths coincide.
    Best-effort: a failed copy degrades to the pre-existing "untrained model"
    fallback, never an exception. (Sibling migration:
    ``flinttrade_historical.watchlist_routes`` does the same for
    ``watchlist.db``.)
    """
    try:
        if new.exists() or not legacy.exists():
            return
        if legacy.resolve() == new.resolve():
            return
        new.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(legacy, new)
        legacy_sidecar = legacy.with_suffix(legacy.suffix + ".sha256")
        if legacy_sidecar.exists():
            shutil.copy2(legacy_sidecar, new.with_suffix(new.suffix + ".sha256"))
        logger.info("Migrated legacy signal model from %s to %s", legacy, new)
    except OSError as exc:
        logger.warning("Could not migrate legacy signal model %s -> %s: %s", legacy, new, exc)


def _run_async(coro: Any) -> Any:
    """Run an async OpenAlgo client call from the synchronous signal cycle."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _normalise_history_rows(rows: Any) -> list[dict[str, Any]]:
    """Convert OpenAlgo history models/responses into plain indicator rows."""
    if isinstance(rows, dict):
        rows = rows.get("data", [])
    if not isinstance(rows, list):
        return []

    normalised: list[dict[str, Any]] = []
    for row in rows:
        if isinstance(row, dict):
            normalised.append(row)
        elif hasattr(row, "model_dump"):
            normalised.append(row.model_dump())
        elif hasattr(row, "__dict__"):
            normalised.append(dict(row.__dict__))
    return normalised


class SignalPipeline:
    """Orchestrates: fetch bars -> compute indicators -> predict signal -> emit."""

    def __init__(
        self,
        openalgo_host: str | None = None,
        openalgo_api_key: str | None = None,
        openalgo_client: Any | None = None,
        model_path: str = "",
        instruments: list[dict] | None = None,
        interval: str = "5m",
        turbulence_enabled: bool = False,
        turbulence_threshold: float = 3.0,
        turbulence_window: int = 60,
        signal_sink: Callable[[dict[str, dict[str, Any]]], Any] | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        from flinttrade_core.config import Settings
        from flinttrade_core.workspace import workspace_dir

        settings = Settings.from_env()
        overrides: dict[str, Any] = {}
        if openalgo_host:
            overrides["openalgo_host"] = openalgo_host.rstrip("/")
        if openalgo_api_key is not None:
            overrides["openalgo_api_key"] = openalgo_api_key
        if overrides:
            settings = settings.model_copy(update=overrides)
        # Keep the FULL workspace/env Settings (incl. openalgo_port) — the
        # fallback client in fetch_bars previously rebuilt a partial Settings
        # from host+key only, silently reverting the workspace REST-port
        # override (U20) to :5000.
        self._settings = settings
        self.host = settings.openalgo_host.rstrip("/")
        self.api_key = settings.openalgo_api_key
        self._openalgo_client = openalgo_client
        default_model_path = workspace_dir() / "models" / "signal_model.joblib"
        if not model_path:
            _migrate_legacy_model_file(
                _legacy_state_dir() / "models" / "signal_model.joblib",
                default_model_path,
            )
        self.model_path = model_path or str(default_model_path)
        self._instrument_lock = threading.RLock()
        self._instruments = _normalise_scheduled_instruments(
            instruments
            if instruments is not None
            else [
                {"symbol": "NIFTY", "exchange": "NSE_INDEX"},
                {"symbol": "BANKNIFTY", "exchange": "NSE_INDEX"},
            ]
        )
        self.interval = interval
        self.latest_signals: dict[str, dict[str, Any]] = {}
        self._generator: Any = None
        self._symbol_generators: dict[tuple[str, str], Any] = {}
        self._generator_lock = threading.RLock()
        self._turbulence_enabled: bool = turbulence_enabled
        self._turbulence_threshold: float = turbulence_threshold
        self._turbulence_window: int = turbulence_window
        self._signal_sink = signal_sink
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._emission_lock = threading.Lock()
        self._last_emitted_candles: dict[tuple[str, str], datetime] = {}

    @property
    def instruments(self) -> list[dict[str, str]]:
        """Return an isolated snapshot of the scheduled instrument roster."""
        return self.instrument_snapshot()

    def instrument_snapshot(self) -> list[dict[str, str]]:
        """Return the current roster without exposing live mutable state."""
        with self._instrument_lock:
            return [dict(instrument) for instrument in self._instruments]

    def update_instruments(self, instruments: list[dict[str, Any] | str]) -> list[dict[str, str]]:
        """Atomically replace the scheduled roster from canonical identities."""
        candidate = _normalise_scheduled_instruments(instruments)
        with self._instrument_lock:
            self._instruments = candidate
            snapshot = [dict(instrument) for instrument in candidate]
        allowed = {(instrument["exchange"], instrument["symbol"]) for instrument in snapshot}
        allowed_keys = {f"{exchange}:{symbol}" for exchange, symbol in allowed}
        with self._generator_lock:
            self._symbol_generators = {
                identity: generator
                for identity, generator in self._symbol_generators.items()
                if identity in allowed
            }
        with self._emission_lock:
            self.latest_signals = {
                key: signal
                for key, signal in self.latest_signals.items()
                if key in allowed_keys
            }
        return snapshot

    def _ensure_generator(self) -> None:
        """Lazy-load signal generator with trained model."""
        with self._generator_lock:
            if self._generator is not None:
                return
            from .signals import SignalGenerator

            self._generator = SignalGenerator()
            model_file = Path(self.model_path)
            if model_file.exists():
                try:
                    self._generator.load(self.model_path)
                except Exception as exc:  # noqa: BLE001 - corrupt models must preserve scheduled fallback
                    logger.warning("Could not load signal model from %s; using fallback: %s", model_file, exc)
                else:
                    logger.info("Loaded signal model from %s", model_file)
            else:
                logger.warning("No trained model at %s — signals will use fallback", model_file)

    def _generator_for(self, symbol: str, exchange: str) -> Any:
        """Return the verified per-instrument model, then shared model, then fallback."""
        key = (exchange, symbol)
        display_key = f"{exchange}:{symbol}"
        with self._generator_lock:
            existing = self._symbol_generators.get(key)
            if existing is not None:
                return existing

            from .signal_retraining import load_signal_model_bundle, signal_model_path

            model_file = signal_model_path(Path(self.model_path).parent, symbol, exchange)
            if model_file.exists():
                try:
                    candidate = load_signal_model_bundle(model_file, symbol=symbol, exchange=exchange)
                except Exception as exc:  # noqa: BLE001 - invalid models fall through to shared/fallback
                    logger.warning(
                        "Could not load signal model for %s from %s; using shared fallback: %s",
                        display_key,
                        model_file,
                        exc,
                    )
                else:
                    self._symbol_generators[key] = candidate
                    logger.info("Loaded signal model for %s from %s", display_key, model_file)
                    return candidate

            self._ensure_generator()
            return self._generator

    def install_generator(self, symbol: str, exchange: str, generator: Any) -> None:
        """Atomically publish a persisted generator to future signal cycles."""
        self.publish_generator(symbol, exchange, generator, lambda: None)

    def publish_generator(
        self,
        symbol: str,
        exchange: str,
        generator: Any,
        publish: Callable[[], None],
    ) -> None:
        """Publish disk state and its cache entry under the generator lock."""
        with self._generator_lock:
            publish()
            self._symbol_generators[(exchange, symbol)] = generator

    def fetch_bars(self, symbol: str, exchange: str, lookback_days: int = 30) -> list[dict]:
        """Fetch OHLCV bars from OpenAlgo history API."""
        from flinttrade_core.openalgo_client import OpenAlgoClient

        end = datetime.now()
        start = end - timedelta(days=lookback_days)
        client = self._openalgo_client
        close_client = False
        if client is None:
            # Full Settings (host, key, AND rest/ws ports) from __init__ — a
            # partial rebuild here dropped the workspace openalgo.port override.
            client = OpenAlgoClient(self._settings)
            close_client = True

        # Fetch AND close on ONE loop. Running close on a second fresh loop
        # raised "Event loop is closed" from the finally block AFTER a
        # successful fetch (the keep-alive connection's transport belonged to
        # the first, already-closed loop) — which superseded the return and
        # silently zeroed every AI signal cycle.
        async def _fetch_and_close() -> Any:
            try:
                return await client.history(
                    symbol=symbol,
                    exchange=exchange,
                    interval=self.interval,
                    start_date=start.strftime("%Y-%m-%d"),
                    end_date=end.strftime("%Y-%m-%d"),
                )
            finally:
                if close_client:
                    await client.close()

        try:
            if close_client:
                # Short-lived fallback client: call + close on ONE fresh loop.
                rows = _run_async(_fetch_and_close())
            else:
                # Shared/injected client: marshal onto its owner loop when it
                # is a real OpenAlgoClient (isinstance-guarded inside — test
                # fakes fall back to a plain fresh loop).
                from flinttrade_core.openalgo_client import client_call_sync  # noqa: PLC0415

                rows = client_call_sync(client, _fetch_and_close())
        except Exception as exc:
            logger.error("History fetch failed for %s: %s", symbol, exc)
            return []

        return _normalise_history_rows(rows)

    def run_cycle(
        self,
        *,
        market_is_open: Callable[[str], bool] | None = None,
    ) -> dict[str, dict[str, Any]]:
        """Run one signal cycle for all instruments.

        Args:
            market_is_open: Optional exchange predicate used by scheduled runs.
                Closed exchanges are skipped before any history request.

        Returns a dict keyed by ``exchange:symbol`` with signal details.
        """
        instruments = self.instruments
        if market_is_open is not None:
            eligible: list[dict[str, str]] = []
            for instrument in instruments:
                exchange = instrument["exchange"]
                try:
                    if market_is_open(exchange):
                        eligible.append(instrument)
                except Exception:  # noqa: BLE001 - one bad calendar lookup must fail closed
                    logger.exception("Could not determine market hours for %s", exchange)
            instruments = eligible
            if not instruments:
                return {}

        self._ensure_generator()
        results: dict[str, dict[str, Any]] = {}

        for inst in instruments:
            key = f"{inst['exchange']}:{inst['symbol']}"
            try:
                bars = self.fetch_bars(inst["symbol"], inst["exchange"])
                if len(bars) < 50:
                    logger.warning("Not enough bars for %s (%d)", key, len(bars))
                    continue
                latest_bar_timestamp = self._validated_latest_bar_timestamp(bars, instrument=key)
                if latest_bar_timestamp is None:
                    continue

                # Use ML model if trained, otherwise fall back to EMA crossover
                closes = [float(b.get("close", 0)) for b in bars]
                generator = self._generator_for(inst["symbol"], inst["exchange"])
                if generator is not None and generator.is_trained:
                    signal = generator.predict(bars, symbol=inst["symbol"])
                    if getattr(signal, "error", ""):
                        logger.warning("ML prediction failed for %s; using EMA fallback: %s", key, signal.error)
                        raw_signal = self._ema_crossover_signal(closes)
                        confidence = 0.0
                        method = "ema_crossover_fallback"
                    else:
                        raw_signal = signal.action
                        confidence = signal.confidence
                        method = "ml_model"
                else:
                    # Fallback: simple EMA crossover
                    raw_signal = self._ema_crossover_signal(closes)
                    confidence = 0.0
                    method = "ema_crossover_fallback"

                # Turbulence override — suppress directional signal when market
                # conditions are abnormal (high Mahalanobis distance).
                turbulence_score: float = 0.0
                if self._turbulence_enabled and len(closes) >= self._turbulence_window + 1:
                    from .signals import compute_turbulence

                    # Compute per-bar returns for the last window+1 bars
                    tail = closes[-(self._turbulence_window + 1) :]
                    recent_returns = [
                        (tail[i + 1] - tail[i]) / tail[i] if tail[i] != 0 else 0.0 for i in range(len(tail) - 1)
                    ]
                    turb = compute_turbulence(recent_returns, window=self._turbulence_window)
                    turbulence_score = float(turb[-1]) if len(turb) > 0 else 0.0
                    if turbulence_score > self._turbulence_threshold:
                        logger.info(
                            "Turbulence override for %s: score=%.3f > threshold=%.3f — forcing HOLD",
                            key,
                            turbulence_score,
                            self._turbulence_threshold,
                        )
                        raw_signal = "HOLD"
                        method = f"{method}+turbulence_override"

                result = {
                    "symbol": inst["symbol"],
                    "exchange": inst["exchange"],
                    "signal": raw_signal,
                    "confidence": confidence,
                    "ltp": float(closes[-1]),
                    "timestamp": latest_bar_timestamp,
                    "method": method,
                    "turbulence_score": turbulence_score,
                }
                if not self._claim_source_candle(
                    inst["symbol"],
                    inst["exchange"],
                    latest_bar_timestamp,
                ):
                    logger.debug("Skipping duplicate or regressed source candle for %s at %s", key, latest_bar_timestamp)
                    continue
                results[key] = result
            except Exception:
                logger.exception("Signal cycle error for %s", key)

        if results:
            with self._emission_lock:
                self.latest_signals.update(results)
        if self._signal_sink is not None and results:
            try:
                self._signal_sink(results)
            except Exception:  # noqa: BLE001 - a feed sink cannot discard ML state
                logger.exception("Could not publish scheduled signals to the canonical hub")
        return results

    def _validated_latest_bar_timestamp(
        self,
        bars: list[dict[str, Any]],
        *,
        instrument: str,
    ) -> str | None:
        raw_timestamp = bars[-1].get("timestamp") if bars else None
        parsed = _parse_bar_timestamp(raw_timestamp)
        if parsed is None:
            logger.warning("Skipping %s: latest bar timestamp is missing or invalid", instrument)
            return None

        now = self._clock()
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        now_utc = now.astimezone(timezone.utc)
        interval = _interval_duration(self.interval)
        if interval is None:
            logger.warning("Skipping %s: unsupported bar interval %r", instrument, self.interval)
            return None
        max_age = interval * (4 if interval >= timedelta(days=1) else 2) + timedelta(minutes=1)
        age = now_utc - parsed
        if age > max_age or age < -interval:
            logger.warning(
                "Skipping %s: latest bar timestamp %s is outside the freshness window",
                instrument,
                parsed.isoformat(),
            )
            return None
        return parsed.isoformat()

    def _claim_source_candle(self, symbol: str, exchange: str, timestamp: str) -> bool:
        """Atomically claim a strictly newer source candle for one instrument."""
        parsed = _parse_bar_timestamp(timestamp)
        if parsed is None:
            return False
        identity = (exchange, symbol)
        with self._emission_lock:
            previous = self._last_emitted_candles.get(identity)
            if previous is not None and parsed <= previous:
                return False
            self._last_emitted_candles[identity] = parsed
            return True

    @classmethod
    def _ema_crossover_signal(cls, closes: list[float]) -> str:
        """Return BUY / SELL / HOLD based on EMA-9 / EMA-21 crossover."""
        if len(closes) < 22:
            return "HOLD"
        ema_fast = cls._ema(closes, 9)
        ema_slow = cls._ema(closes, 21)
        if ema_fast[-1] > ema_slow[-1] and ema_fast[-2] <= ema_slow[-2]:
            return "BUY"
        if ema_fast[-1] < ema_slow[-1] and ema_fast[-2] >= ema_slow[-2]:
            return "SELL"
        return "HOLD"

    @staticmethod
    def _ema(data: list[float], period: int) -> list[float]:
        """Simple EMA calculation over a list of floats."""
        if not data:
            return []
        ema = [data[0]]
        k = 2.0 / (period + 1)
        for i in range(1, len(data)):
            ema.append(data[i] * k + ema[-1] * (1 - k))
        return ema

    def train_model(self, bars_list: list[list[dict]], lookahead: int = 5) -> bool:
        """Train the signal model on multiple sets of historical bars.

        Each element in *bars_list* is a list of OHLCV bar dicts for one
        instrument / date range.  After training the model is persisted to
        ``self.model_path``.
        """
        try:
            from .signals import SignalGenerator

            gen = SignalGenerator()

            # Concatenate all bars for training
            all_bars: list[dict[str, Any]] = []
            for bars in bars_list:
                if len(bars) >= 100:
                    all_bars.extend(bars)

            if len(all_bars) < 100:
                logger.warning("Not enough training data (%d bars, need 100+)", len(all_bars))
                return False

            metrics = gen.train(all_bars, lookahead=lookahead)
            logger.info(
                "Signal model trained — train_acc=%.2f, test_acc=%.2f",
                metrics.get("train_accuracy", 0),
                metrics.get("test_accuracy", 0),
            )

            model_file = Path(self.model_path)
            model_file.parent.mkdir(parents=True, exist_ok=True)
            candidate_path = _temporary_model_path(model_file)
            candidate_checksum = Path(f"{candidate_path}.sha256")
            try:
                gen.save(str(candidate_path))
                with self._generator_lock:
                    previous_shared = self._generator
                    _replace_shared_model_pair(candidate_path, model_file)
                    self._generator = gen
                    if previous_shared is not None:
                        self._symbol_generators = {
                            key: cached
                            for key, cached in self._symbol_generators.items()
                            if cached is not previous_shared
                        }
            finally:
                candidate_path.unlink(missing_ok=True)
                candidate_checksum.unlink(missing_ok=True)
            logger.info("Signal model saved to %s", self.model_path)
            return True
        except Exception:
            logger.exception("Model training failed")
            return False

    def get_latest_signals(self) -> dict[str, dict[str, Any]]:
        """Return the most recent signal results."""
        with self._emission_lock:
            return {
                key: dict(signal)
                for key, signal in self.latest_signals.items()
            }
