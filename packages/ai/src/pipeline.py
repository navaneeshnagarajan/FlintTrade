"""Signal pipeline — scheduled cycle that fetches bars, computes indicators,
runs ML model prediction, and emits trading signals.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

logger = logging.getLogger("flinttrade.ai.pipeline")


class SignalPipeline:
    """Orchestrates: fetch bars -> compute indicators -> predict signal -> emit."""

    def __init__(
        self,
        openalgo_host: str = "http://127.0.0.1:5000",
        openalgo_api_key: str = "",
        model_path: str = "",
        instruments: list[dict] | None = None,
        interval: str = "5m",
    ) -> None:
        self.host = openalgo_host
        self.api_key = openalgo_api_key
        self.model_path = model_path or str(
            Path.home() / ".flinttrade" / "models" / "signal_model.joblib"
        )
        self.instruments = instruments or [
            {"symbol": "NIFTY", "exchange": "NSE_INDEX"},
            {"symbol": "BANKNIFTY", "exchange": "NSE_INDEX"},
        ]
        self.interval = interval
        self.latest_signals: dict[str, dict[str, Any]] = {}
        self._generator: Any = None

    def _ensure_generator(self) -> None:
        """Lazy-load signal generator with trained model."""
        if self._generator is not None:
            return
        from packages.ai.src.signals import SignalGenerator

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
        import httpx

        end = datetime.now()
        start = end - timedelta(days=30)
        try:
            resp = httpx.post(
                f"{self.host}/api/v1/history",
                json={
                    "apikey": self.api_key,
                    "symbol": symbol,
                    "exchange": exchange,
                    "interval": self.interval,
                    "start_date": start.strftime("%Y-%m-%d"),
                    "end_date": end.strftime("%Y-%m-%d"),
                },
                timeout=15,
            )
        except httpx.HTTPError as exc:
            logger.error("HTTP error fetching bars for %s: %s", symbol, exc)
            return []

        if resp.status_code != 200:
            logger.error("History API error for %s: %s", symbol, resp.status_code)
            return []
        data = resp.json()
        if data.get("status") == "error":
            logger.error(
                "History API error for %s: %s", symbol, data.get("message")
            )
            return []
        return data.get("data", [])

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
                if self._generator is not None and self._generator.is_trained:
                    signal = self._generator.predict(bars, symbol=inst["symbol"])
                    results[key] = {
                        "symbol": inst["symbol"],
                        "exchange": inst["exchange"],
                        "signal": signal.action,
                        "confidence": signal.confidence,
                        "ltp": float(bars[-1].get("close", 0)),
                        "timestamp": datetime.now().isoformat(),
                        "method": "ml_model",
                    }
                else:
                    # Fallback: simple EMA crossover
                    closes = [float(b.get("close", 0)) for b in bars]
                    sig = self._ema_crossover_signal(closes)
                    results[key] = {
                        "symbol": inst["symbol"],
                        "exchange": inst["exchange"],
                        "signal": sig,
                        "confidence": 0.0,
                        "ltp": float(closes[-1]),
                        "timestamp": datetime.now().isoformat(),
                        "method": "ema_crossover_fallback",
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
            from packages.ai.src.signals import SignalGenerator

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
