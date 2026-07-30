"""Data models for the live market signals pipeline.

Defines the ``SignalEvent`` dataclass emitted by the canonical signal hub and the
``SignalConfig`` used to configure which instruments, indicators,
and thresholds are active.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import UTC, datetime
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
            "metadata": deepcopy(self.metadata),
        }


SignalType: TypeAlias = Literal["BUY", "SELL", "HOLD", "ALERT"]
SignalSource: TypeAlias = Literal["rule", "ml", "fallback"]

# Historical names remain import-compatible while callers migrate to the
# explicit cross-source name.
LiveSignal = SignalEvent
Signal = SignalEvent

_INDICATOR_DEFAULT_PARAMS: dict[str, dict[str, int]] = {
    "RSI": {"period": 14},
    "EMA_Cross": {"fast": 9, "slow": 21},
    "MACD": {"fast": 12, "slow": 26, "signal": 9},
}
_DEFAULT_RSI_OVERSOLD = 30.0
_DEFAULT_RSI_OVERBOUGHT = 70.0
_SUPPORTED_THRESHOLDS = {
    "rsi_oversold",
    "rsi_overbought",
    "macd_crossover_min",
    "ema_cross_min_pct",
}
_MINIMUM_THRESHOLDS = {"macd_crossover_min", "ema_cross_min_pct"}
_MAX_INDICATOR_PERIOD = 10_000


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


def _normalise_period(value: object, *, field_name: str) -> int:
    """Validate one finite, positive whole-number indicator period."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field_name} must be a finite positive integer")
    if isinstance(value, float):
        if not math.isfinite(value) or not value.is_integer():
            raise ValueError(f"{field_name} must be a finite positive integer")
        period = int(value)
    else:
        period = value
    if period <= 0:
        raise ValueError(f"{field_name} must be a finite positive integer")
    if period > _MAX_INDICATOR_PERIOD:
        raise ValueError(f"{field_name} must be at most {_MAX_INDICATOR_PERIOD}")
    return period


def _normalise_threshold(value: object) -> float:
    """Convert one numeric threshold without leaking integer overflow."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("threshold values must be numeric")
    try:
        threshold = float(value)
    except OverflowError:
        raise ValueError("threshold values must be finite") from None
    if not math.isfinite(threshold):
        raise ValueError("threshold values must be finite")
    return threshold


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
        """Validate and copy the complete live-rule configuration."""
        if not isinstance(self.instruments, list):
            raise ValueError("instruments must be a list of EXCHANGE:SYMBOL identities")
        self.instruments = list(
            dict.fromkeys(normalise_instrument_identity(identity) for identity in self.instruments)
        )

        if not isinstance(self.indicators, list):
            raise ValueError("indicators must be a list of mappings")
        normalised_indicators: list[dict[str, object]] = []
        for indicator in self.indicators:
            if not isinstance(indicator, Mapping):
                raise ValueError("indicators must contain mappings")
            name = indicator.get("name")
            if not isinstance(name, str) or name not in _INDICATOR_DEFAULT_PARAMS:
                raise ValueError("indicators must use supported names: RSI, EMA_Cross, MACD")
            raw_params = indicator.get("params", {})
            if not isinstance(raw_params, Mapping):
                raise ValueError("indicator params must be a mapping")

            defaults = _INDICATOR_DEFAULT_PARAMS[name]
            unexpected_params = set(raw_params) - set(defaults)
            if unexpected_params:
                raise ValueError(f"unsupported {name} params: {', '.join(sorted(map(str, unexpected_params)))}")
            params = {
                param: _normalise_period(raw_params.get(param, default), field_name=f"{name} {param}")
                for param, default in defaults.items()
            }
            if name in {"EMA_Cross", "MACD"} and params["fast"] >= params["slow"]:
                raise ValueError(f"{name} fast period must be less than slow period")
            normalised_indicators.append({"name": name, "params": params})
        self.indicators = normalised_indicators

        if not isinstance(self.thresholds, Mapping):
            raise ValueError("thresholds must be a mapping")
        normalised_thresholds: dict[str, float] = {}
        for name, value in self.thresholds.items():
            if not isinstance(name, str):
                raise ValueError("threshold names must be strings")
            if name not in _SUPPORTED_THRESHOLDS:
                raise ValueError(f"unsupported threshold name: {name}")
            normalised_thresholds[name] = _normalise_threshold(value)
        oversold = normalised_thresholds.get("rsi_oversold", _DEFAULT_RSI_OVERSOLD)
        overbought = normalised_thresholds.get("rsi_overbought", _DEFAULT_RSI_OVERBOUGHT)
        if not 0 < oversold < 100:
            raise ValueError("rsi_oversold must be between 0 and 100")
        if not 0 < overbought < 100:
            raise ValueError("rsi_overbought must be between 0 and 100")
        if oversold >= overbought:
            raise ValueError("rsi_oversold must be lower than rsi_overbought")
        for name in _MINIMUM_THRESHOLDS:
            if normalised_thresholds.get(name, 0.0) < 0:
                raise ValueError(f"{name} must be non-negative")
        self.thresholds = normalised_thresholds

    def to_dict(self) -> dict[str, object]:
        """Serialise to a JSON-safe dictionary."""
        return deepcopy(
            {
                "instruments": self.instruments,
                "indicators": self.indicators,
                "thresholds": self.thresholds,
            }
        )

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> SignalConfig:
        """Create a config from a dictionary (e.g. JSON request body)."""
        return cls(
            instruments=data.get("instruments", []),  # type: ignore[arg-type]
            indicators=data.get("indicators", []),  # type: ignore[arg-type]
            thresholds=data.get("thresholds", {}),  # type: ignore[arg-type]
        )


def now_iso() -> str:
    """Return current UTC time as an ISO-8601 string."""
    return datetime.now(UTC).isoformat()
