"""Signal pipeline — scheduled cycle that fetches bars, computes indicators,
runs ML model prediction, and emits trading signals.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

logger = logging.getLogger("flinttrade.ai.pipeline")


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
    ) -> None:
        from flinttrade_core.config import Settings
        from flinttrade_core.workspace import workspace_dir

        settings = Settings.from_env()
        self.host = (openalgo_host or settings.openalgo_host).rstrip("/")
        self.api_key = openalgo_api_key if openalgo_api_key is not None else settings.openalgo_api_key
        self._openalgo_client = openalgo_client
        self.model_path = model_path or str(
            workspace_dir() / "models" / "signal_model.joblib"
        )
        self.instruments = instruments or [
            {"symbol": "NIFTY", "exchange": "NSE_INDEX"},
            {"symbol": "BANKNIFTY", "exchange": "NSE_INDEX"},
        ]
        self.interval = interval
        self.latest_signals: dict[str, dict[str, Any]] = {}
        self._generator: Any = None
        self._turbulence_enabled: bool = turbulence_enabled
        self._turbulence_threshold: float = turbulence_threshold
        self._turbulence_window: int = turbulence_window

    def _ensure_generator(self) -> None:
        """Lazy-load signal generator with trained model."""
        if self._generator is not None:
            return
        from .signals import SignalGenerator

        self._generator = SignalGenerator()
        model_file = Path(self.model_path)
        if model_file.exists():
            self._generator.load(self.model_path)
            logger.info("Loaded signal model from %s", model_file)
        else:
            logger.warning(
                "No trained model at %s — signals will use fallback", model_file
            )

    def fetch_bars(self, symbol: str, exchange: str, count: int = 200) -> list[dict]:
        """Fetch OHLCV bars from OpenAlgo history API."""
        from flinttrade_core.config import Settings
        from flinttrade_core.openalgo_client import OpenAlgoClient

        end = datetime.now()
        start = end - timedelta(days=30)
        client = self._openalgo_client
        close_client = False
        if client is None:
            client = OpenAlgoClient(
                Settings(openalgo_host=self.host, openalgo_api_key=self.api_key)
            )
            close_client = True

        try:
            rows = _run_async(
                client.history(
                    symbol=symbol,
                    exchange=exchange,
                    interval=self.interval,
                    start_date=start.strftime("%Y-%m-%d"),
                    end_date=end.strftime("%Y-%m-%d"),
                )
            )
        except Exception as exc:
            logger.error("History fetch failed for %s: %s", symbol, exc)
            return []
        finally:
            if close_client:
                _run_async(client.close())

        return _normalise_history_rows(rows)

    def run_cycle(self) -> dict[str, dict[str, Any]]:
        """Run one signal cycle for all instruments.

        Returns a dict keyed by ``exchange:symbol`` with signal details.
        """
        self._ensure_generator()
        results: dict[str, dict[str, Any]] = {}

        for inst in self.instruments:
            key = f"{inst['exchange']}:{inst['symbol']}"
            try:
                bars = self.fetch_bars(inst["symbol"], inst["exchange"])
                if len(bars) < 50:
                    logger.warning("Not enough bars for %s (%d)", key, len(bars))
                    continue

                # Use ML model if trained, otherwise fall back to EMA crossover
                closes = [float(b.get("close", 0)) for b in bars]
                if self._generator is not None and self._generator.is_trained:
                    signal = self._generator.predict(bars, symbol=inst["symbol"])
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
                    tail = closes[-(self._turbulence_window + 1):]
                    recent_returns = [
                        (tail[i + 1] - tail[i]) / tail[i] if tail[i] != 0 else 0.0
                        for i in range(len(tail) - 1)
                    ]
                    turb = compute_turbulence(recent_returns, window=self._turbulence_window)
                    turbulence_score = float(turb[-1]) if len(turb) > 0 else 0.0
                    if turbulence_score > self._turbulence_threshold:
                        logger.info(
                            "Turbulence override for %s: score=%.3f > threshold=%.3f — forcing HOLD",
                            key, turbulence_score, self._turbulence_threshold,
                        )
                        raw_signal = "HOLD"
                        method = f"{method}+turbulence_override"

                results[key] = {
                    "symbol": inst["symbol"],
                    "exchange": inst["exchange"],
                    "signal": raw_signal,
                    "confidence": confidence,
                    "ltp": float(closes[-1]),
                    "timestamp": datetime.now().isoformat(),
                    "method": method,
                    "turbulence_score": turbulence_score,
                }
            except Exception:
                logger.exception("Signal cycle error for %s", key)

        self.latest_signals = results
        return results

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

    def train_model(
        self, bars_list: list[list[dict]], lookahead: int = 5
    ) -> bool:
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
                logger.warning(
                    "Not enough training data (%d bars, need 100+)", len(all_bars)
                )
                return False

            metrics = gen.train(all_bars, lookahead=lookahead)
            logger.info(
                "Signal model trained — train_acc=%.2f, test_acc=%.2f",
                metrics.get("train_accuracy", 0),
                metrics.get("test_accuracy", 0),
            )

            # Persist
            model_dir = Path(self.model_path).parent
            model_dir.mkdir(parents=True, exist_ok=True)
            gen.save(self.model_path)
            logger.info("Signal model saved to %s", self.model_path)

            self._generator = gen
            return True
        except Exception:
            logger.exception("Model training failed")
            return False

    def get_latest_signals(self) -> dict[str, dict[str, Any]]:
        """Return the most recent signal results."""
        return self.latest_signals
