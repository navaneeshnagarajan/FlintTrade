"""Data models for the live market signals pipeline.

Defines the ``SignalEvent`` dataclass emitted by the canonical signal hub and the
``SignalConfig`` used to configure which instruments, indicators,
and thresholds are active.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal, TypeAlias


@dataclass
class SignalEvent:
    """One source-tagged event in the canonical trading-signal feed."""

    event_id: int = 0
    timestamp: str = ""
    symbol: str = ""
    exchange: str = ""
    signal_type: str = "ALERT"  # "BUY" | "SELL" | "HOLD" | "ALERT"
    source: str = "rule"  # "rule" | "ml" | "fallback"
    method: str = ""
    indicator: str = ""  # "RSI" | "MACD" | "Supertrend" | "EMA_Cross" | etc.
    value: float = 0.0  # indicator value that triggered the signal
    threshold: float = 0.0  # threshold that was crossed
    confidence: float = 0.0  # 0.0 - 1.0
    message: str = ""  # human-readable description
    metadata: dict[str, object] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        """Serialise to a JSON-safe dictionary."""
        return {
            "event_id": self.event_id,
            "timestamp": self.timestamp,
            "symbol": self.symbol,
            "exchange": self.exchange,
            "signal_type": self.signal_type,
            "source": self.source,
            "method": self.method,
            "indicator": self.indicator,
            "value": round(self.value, 4),
            "threshold": round(self.threshold, 4),
            "confidence": round(self.confidence, 4),
            "message": self.message,
            "metadata": dict(self.metadata),
        }


SignalType: TypeAlias = Literal["BUY", "SELL", "HOLD", "ALERT"]
SignalSource: TypeAlias = Literal["rule", "ml", "fallback"]

# Historical names remain import-compatible while callers migrate to the
# explicit cross-source name.
LiveSignal = SignalEvent
Signal = SignalEvent


def normalise_instrument_identity(identity: str) -> str:
    """Validate and uppercase one ``EXCHANGE:SYMBOL`` instrument identity."""
    if not isinstance(identity, str) or any(character.isspace() for character in identity):
        raise ValueError("instruments must contain EXCHANGE:SYMBOL identities")
    parts = identity.split(":")
    if len(parts) != 2:
        raise ValueError("instruments must contain EXCHANGE:SYMBOL identities")
    exchange, symbol = (part.upper() for part in parts)
    if not exchange or not symbol:
        raise ValueError("instruments must contain EXCHANGE:SYMBOL identities")
    return f"{exchange}:{symbol}"


@dataclass
class SignalConfig:
    """Configuration for the live signal pipeline."""

    instruments: list[str] = field(default_factory=lambda: ["NSE_INDEX:NIFTY", "NSE_INDEX:BANKNIFTY"])
    indicators: list[dict[str, object]] = field(
        default_factory=lambda: [
            {"name": "RSI", "params": {"period": 14}},
            {"name": "EMA_Cross", "params": {"fast": 9, "slow": 21}},
            {"name": "MACD", "params": {"fast": 12, "slow": 26, "signal": 9}},
        ]
    )
    thresholds: dict[str, float] = field(
        default_factory=lambda: {
            "rsi_oversold": 30.0,
            "rsi_overbought": 70.0,
            "macd_crossover_min": 0.0,
            "ema_cross_min_pct": 0.0,
        }
    )

    def __post_init__(self) -> None:
        """Keep the live rule allowlist in one canonical identity format."""
        if not isinstance(self.instruments, list):
            raise ValueError("instruments must be a list of EXCHANGE:SYMBOL identities")
        self.instruments = [normalise_instrument_identity(identity) for identity in self.instruments]

    def to_dict(self) -> dict[str, object]:
        """Serialise to a JSON-safe dictionary."""
        return {
            "instruments": self.instruments,
            "indicators": self.indicators,
            "thresholds": self.thresholds,
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> SignalConfig:
        """Create a config from a dictionary (e.g. JSON request body)."""
        return cls(
            instruments=list(data.get("instruments", [])),  # type: ignore[arg-type]
            indicators=list(data.get("indicators", [])),  # type: ignore[arg-type]
            thresholds=dict(data.get("thresholds", {})),  # type: ignore[arg-type]
        )


def now_iso() -> str:
    """Return current UTC time as an ISO-8601 string."""
    return datetime.now(timezone.utc).isoformat()
