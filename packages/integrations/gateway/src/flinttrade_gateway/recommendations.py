"""Broker capability metadata ranking engine.

Ranks the brokers an operator has connected (or all known native brokers) for
specific operator-selected use cases, purely from each broker's advertised
:class:`~flinttrade_gateway.capabilities.Capabilities`, and explains the
ranking. Side-effect-free and deterministic so it can back both the gateway
capability routes and the terminal's multi-broker setup UI: an operator running
several brokers in one account can see, per job, which broker to route to
(e.g. depth/options data vs. low-cost execution metadata).

Scores are normalised to ``0.0..1.0`` *within* a use-case (best broker = 1.0)
and derived only from declared capability fields — no editorial guesses. A
broker with no relevant capability scores ``0.0`` with a plain-language reason.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum

from .brokers.dhan import DHAN_CAPABILITIES
from .brokers.indmoney import INDMONEY_CAPABILITIES
from .brokers.kotakneo import KOTAKNEO_CAPABILITIES
from .brokers.upstox import UPSTOX_CAPABILITIES
from .capabilities import Capabilities

# Native broker capabilities keyed by ``broker_id``. Every full-parity native
# adapter belongs here so the engine and the ``?brokers=`` route filter agree on
# what a valid native broker is. The OpenAlgo bridge is deliberately excluded —
# it is a meta-adapter whose real capabilities depend on the underlying broker,
# so it cannot be ranked as a single broker here.
NATIVE_BROKER_CAPABILITIES: dict[str, Capabilities] = {
    "dhan": DHAN_CAPABILITIES,
    "upstox": UPSTOX_CAPABILITIES,
    "kotakneo": KOTAKNEO_CAPABILITIES,
    "indmoney": INDMONEY_CAPABILITIES,
}


class BrokerUseCase(str, Enum):
    """A job an operator might route to a specific broker."""

    HISTORICAL_DATA = "historical_data"
    MARKET_DEPTH = "market_depth"
    OPTIONS_ANALYTICS = "options_analytics"
    OPTIONS_HISTORY = "options_history"
    LOW_COST_EXECUTION = "low_cost_execution"
    ORDER_THROUGHPUT = "order_throughput"
    STREAMING = "streaming"
    ADVANCED_ORDERS = "advanced_orders"


@dataclass(frozen=True)
class BrokerRecommendation:
    """A single ranked broker for a use-case."""

    broker_id: str
    score: float  # normalised 0.0..1.0 within the use-case (best = 1.0)
    raw_score: float  # un-normalised score (use-case specific units)
    rationale: str


# ---------------------------------------------------------------------------
# Per-use-case scorers: (Capabilities) -> (raw_score, rationale)
# ---------------------------------------------------------------------------


def _score_historical(c: Capabilities) -> tuple[float, str]:
    # Deep fine-resolution intraday lookback is intentionally the dominant term:
    # for historical-data capability metadata the depth of retrievable history is
    # the headline signal, so a broker with years of intraday history (e.g. Dhan,
    # ~5 years) should outrank one with a broader interval menu but only days of
    # depth (e.g. IndMoney). Do NOT flatten lookback toward interval count — that
    # would over-credit breadth and misrepresent the documented depth gap. The
    # candles/1000 term is 0 for every native today (none documents a per-request
    # candle cap); it is retained, not dead, so a broker that later advertises a
    # finite cap is credited — do not delete it.
    intervals = len(c.historical_intraday_intervals_minutes)
    lookback = c.historical_max_lookback_days_intraday or 0
    candles = c.historical_max_candles_per_request or 0
    if not intervals and not lookback and not candles:
        return 0.0, "No historical/OHLC candle API."
    score = intervals * 2.0 + lookback / 30.0 + candles / 1000.0
    bits: list[str] = []
    if intervals:
        bits.append(f"{intervals} intraday intervals")
    if lookback:
        bits.append(f"{lookback}-day intraday lookback")
    if candles:
        bits.append(f"{candles} candles/request")
    return score, "Historical data: " + ", ".join(bits) + "."


def _score_market_depth(c: Capabilities) -> tuple[float, str]:
    level = int(c.depth_levels)
    return float(level), f"{level}-level market depth."


def _score_options(c: Capabilities) -> tuple[float, str]:
    if not c.option_chain_supported:
        return 0.0, "No option-chain API."
    score = 2.0
    bits = ["option chain"]
    if c.option_chain_greeks_supported:
        score += 1.0
        bits.append("Greeks")
    if c.option_chain_rate_limit_seconds:
        # Faster refresh (smaller interval) is better — small bonus.
        score += 1.0 / c.option_chain_rate_limit_seconds
        bits.append(f"{c.option_chain_rate_limit_seconds}s chain refresh")
    return score, "Options analytics: " + ", ".join(bits) + "."


def _score_options_history(c: Capabilities) -> tuple[float, str]:
    if not c.options_history_supported:
        return 0.0, "No historical options-data API."
    score = 2.0
    bits = ["historical options data"]
    if c.options_history_rolling:
        score += 2.0
        bits.append("rolling/continuous expiry series")
    return score, "Options history: " + ", ".join(bits) + "."


def _score_low_cost(c: Capabilities) -> tuple[float, str]:
    score = 0.0
    bits: list[str] = []
    if c.brokerage_free:
        score += 3.0
        bits.append("zero execution brokerage")
    if not c.cost_paid:
        score += 1.0
        bits.append("free API access")
    elif c.cost_inr_per_month:
        bits.append(f"₹{c.cost_inr_per_month}/mo API")
    if not bits:
        return 0.0, "Standard brokerage and paid API."
    rationale = "Low-cost execution: " + ", ".join(bits) + "."
    if c.brokerage_free and c.brokerage_note:
        rationale += f" ({c.brokerage_note})"
    return score, rationale


def _score_throughput(c: Capabilities) -> tuple[float, str]:
    ops = c.rate_limit_orders_per_sec or 0
    if not ops:
        return 0.0, "Order throughput not advertised."
    return float(ops), f"{ops} orders/sec."


def _score_streaming(c: Capabilities) -> tuple[float, str]:
    if not c.streaming_supported:
        return 0.0, "No real-time streaming."
    score = 1.0
    bits = ["live streaming"]
    if c.streaming_max_total_symbols:
        score += c.streaming_max_total_symbols / 1000.0
        bits.append(f"{c.streaming_max_total_symbols:,} symbols")
    if c.streaming_max_connections_per_user:
        score += c.streaming_max_connections_per_user
        bits.append(f"{c.streaming_max_connections_per_user} connections")
    return score, "Streaming: " + ", ".join(bits) + "."


def _score_advanced_orders(c: Capabilities) -> tuple[float, str]:
    score = 0.0
    bits: list[str] = []
    if c.bracket_order_native:
        score += 2.0
        bits.append("bracket")
    if c.cover_order_native:
        score += 1.0
        bits.append("cover")
    if c.gtt_native:
        score += 1.0
        bits.append("GTT")
    if c.iceberg_native:
        score += 1.0
        bits.append("iceberg")
    if not bits:
        return 0.0, "No native advanced order types."
    return score, "Native advanced orders: " + ", ".join(bits) + "."


_SCORERS = {
    BrokerUseCase.HISTORICAL_DATA: _score_historical,
    BrokerUseCase.MARKET_DEPTH: _score_market_depth,
    BrokerUseCase.OPTIONS_ANALYTICS: _score_options,
    BrokerUseCase.OPTIONS_HISTORY: _score_options_history,
    BrokerUseCase.LOW_COST_EXECUTION: _score_low_cost,
    BrokerUseCase.ORDER_THROUGHPUT: _score_throughput,
    BrokerUseCase.STREAMING: _score_streaming,
    BrokerUseCase.ADVANCED_ORDERS: _score_advanced_orders,
}


def recommend(
    use_case: BrokerUseCase,
    capabilities_by_broker: Mapping[str, Capabilities] | None = None,
) -> list[BrokerRecommendation]:
    """Rank brokers for *use_case*, best first.

    Args:
        use_case: The job to rank brokers for.
        capabilities_by_broker: Broker-id → capabilities to rank. Defaults to
            :data:`NATIVE_BROKER_CAPABILITIES` (all known native brokers). Pass
            the operator's connected subset to rank only their brokers.

    Returns:
        Recommendations sorted by ``raw_score`` descending, ties broken by
        ``broker_id`` for determinism. ``score`` is normalised to ``0.0..1.0``
        within this call (best broker = 1.0; all-zero stays 0.0).
    """
    caps = capabilities_by_broker or NATIVE_BROKER_CAPABILITIES
    scorer = _SCORERS[use_case]
    scored = [(bid, *scorer(c)) for bid, c in caps.items()]
    best = max((raw for _, raw, _ in scored), default=0.0)
    norm = best if best > 0 else 1.0
    recs = [
        BrokerRecommendation(
            broker_id=bid,
            score=round(raw / norm, 4),
            raw_score=round(raw, 4),
            rationale=rationale,
        )
        for bid, raw, rationale in scored
    ]
    recs.sort(key=lambda r: (-r.raw_score, r.broker_id))
    return recs


def recommend_all(
    capabilities_by_broker: Mapping[str, Capabilities] | None = None,
) -> dict[str, list[BrokerRecommendation]]:
    """Return rankings for every use-case.

    Args:
        capabilities_by_broker: See :func:`recommend`.

    Returns:
        Mapping of use-case value → ranked recommendations.
    """
    return {uc.value: recommend(uc, capabilities_by_broker) for uc in BrokerUseCase}


def best_broker_for(
    use_case: BrokerUseCase,
    capabilities_by_broker: Mapping[str, Capabilities] | None = None,
) -> BrokerRecommendation | None:
    """Return the single best broker for *use_case*, or ``None`` if none qualify.

    Args:
        use_case: The job to rank brokers for.
        capabilities_by_broker: See :func:`recommend`.

    Returns:
        The top recommendation, or ``None`` when no broker scores above zero.
    """
    ranked = recommend(use_case, capabilities_by_broker)
    if not ranked or ranked[0].raw_score <= 0:
        return None
    return ranked[0]
