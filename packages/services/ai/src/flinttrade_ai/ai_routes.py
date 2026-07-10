"""AI blueprint - sentiment, regime, optimiser, refinement, and RAG endpoints.

Trading signals are owned by ``signal_routes``. This blueprint provides
sentiment analysis, regime detection, optimiser reports, and RAG queries.
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from flask import Blueprint, current_app, jsonify, request

from .llm_client import LLMConfig
from .sentiment import FiiDiiFlow, MarketSummary, SentimentLabel, sentiment_label_from_score

logger = logging.getLogger("flinttrade")

ai_bp = Blueprint("ai", __name__, url_prefix="/api/v1")

_RICH_SUMMARY_CACHE_TTL_SECONDS = 300.0
_rich_summary_lock = threading.Lock()
_rich_summary_inflight_key: str | None = None


@dataclass(frozen=True)
class _RichSummaryCacheEntry:
    """Completed rich summary keyed to its exact provider snapshot."""

    key: str
    expires_at: float
    summary: MarketSummary


_rich_summary_cache: _RichSummaryCacheEntry | None = None


def _is_llm_configured() -> bool:
    """Check whether the LLM provider is configured."""
    try:
        cfg = LLMConfig.from_env()
        return bool(cfg.provider)
    except Exception:
        return False


@ai_bp.route("/sentiment/analyse", methods=["POST"])
def sentiment_analyze() -> tuple[Any, int]:
    """Analyse sentiment for a text snippet or symbol.

    Request JSON:
        text (str, optional): Raw text to analyse (headline, news).
        symbol (str, optional): Symbol to look up recent sentiment for.
        At least one of ``text`` or ``symbol`` must be provided.

    Returns:
        JSON with ``status`` and ``data`` containing ``score`` (-1 to 1),
        ``label`` (``"bullish"``, ``"bearish"``, or ``"neutral"``), and
        ``confidence`` (0 to 1).
    """
    if not _is_llm_configured():
        return jsonify(
            {
                "status": "error",
                "message": "LLM not configured. Sentiment analysis requires an LLM provider.",
            }
        ), 503

    body = request.get_json(silent=True) or {}
    text: str = body.get("text", "").strip()
    symbol: str = body.get("symbol", "").strip()

    if not text and not symbol:
        return jsonify({"status": "error", "message": "text or symbol is required"}), 400

    analyze_text = text or f"{symbol} stock market performance"

    try:
        from .sentiment import (  # noqa: PLC0415
            NewsArticle,
            score_article_rule_based,
            score_article_with_llm,
        )
        from .llm_client import LLMClient  # noqa: PLC0415

        article = NewsArticle(title=analyze_text, summary="")
        llm_client = None
        try:
            llm_client = LLMClient()
            scored = score_article_with_llm(article, llm_client)
        except Exception as llm_exc:
            logger.warning("LLM sentiment failed, using rule-based: %s", llm_exc)
            scored = score_article_rule_based(article)
        finally:
            if llm_client is not None:
                try:
                    llm_client.close()
                except Exception as close_exc:
                    logger.warning("Failed to close sentiment LLM client: %s", close_exc)

        label_map = {"BULLISH": "bullish", "BEARISH": "bearish", "NEUTRAL": "neutral"}
        label = label_map.get(scored.sentiment.upper(), "neutral")

        # Convert sentiment to numeric score: bullish=+confidence, bearish=-confidence
        if label == "bullish":
            score = scored.confidence
        elif label == "bearish":
            score = -scored.confidence
        else:
            score = 0.0

        return jsonify(
            {
                "status": "success",
                "data": {
                    "score": round(score, 4),
                    "label": label,
                    "confidence": round(scored.confidence, 4),
                    "reasoning": scored.reasoning,
                },
            }
        ), 200
    except Exception:
        logger.exception("sentiment_analyze error")
        return jsonify({"status": "error", "message": "Internal server error"}), 500


def _score_value(score: Any) -> float:
    """Signed numeric value of a SentimentScore (+conf bullish, -conf bearish)."""
    sentiment = str(getattr(score, "sentiment", "NEUTRAL")).upper()
    conf = float(getattr(score, "confidence", 0.0) or 0.0)
    if sentiment == "BULLISH":
        return conf
    if sentiment == "BEARISH":
        return -conf
    return 0.0


def _market_sentiment_data() -> dict[str, Any] | None:
    """Read optional structured market data from the runtime provider hook."""
    provider = current_app.config.get("MARKET_SENTIMENT_DATA_PROVIDER")
    if provider is None:
        return None
    if not callable(provider):
        logger.warning("MARKET_SENTIMENT_DATA_PROVIDER is not callable")
        return None
    try:
        value = provider()
    except Exception as exc:
        logger.info("sentiment/summary: market-data provider unavailable (%s)", exc)
        return None
    if not isinstance(value, Mapping) or not value:
        return None
    return dict(value)


def _generate_rich_market_summary(market_data: dict[str, Any]) -> MarketSummary | None:
    """Generate a typed LLM summary and always close its client."""
    from .sentiment import generate_market_summary, prepare_market_summary_data  # noqa: PLC0415

    snapshot = prepare_market_summary_data(market_data)
    if snapshot is None:
        return None
    if not _is_llm_configured():
        return None

    from .llm_client import LLMClient  # noqa: PLC0415

    llm_client = None
    try:
        llm_client = LLMClient()
        return generate_market_summary(llm_client, snapshot)
    except Exception as exc:
        logger.info("sentiment/summary: rich generation unavailable (%s)", exc)
        return None
    finally:
        if llm_client is not None:
            try:
                llm_client.close()
            except Exception as close_exc:
                logger.warning("Failed to close market-summary LLM client: %s", close_exc)


def _market_data_cache_key(market_data: dict[str, Any]) -> str:
    """Return a deterministic cache key without retaining provider objects."""
    payload = json.dumps(market_data, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _refresh_rich_summary_cache(cache_key: str, market_data: dict[str, Any]) -> None:
    """Generate one rich summary off-request and publish it atomically."""
    global _rich_summary_cache, _rich_summary_inflight_key

    summary: MarketSummary | None = None
    try:
        summary = _generate_rich_market_summary(market_data)
    except Exception:
        logger.exception("sentiment/summary: background rich generation failed")
    finally:
        with _rich_summary_lock:
            if summary is not None:
                _rich_summary_cache = _RichSummaryCacheEntry(
                    key=cache_key,
                    expires_at=time.monotonic() + _RICH_SUMMARY_CACHE_TTL_SECONDS,
                    summary=summary,
                )
            if _rich_summary_inflight_key == cache_key:
                _rich_summary_inflight_key = None


def _cached_or_schedule_rich_summary(market_data: dict[str, Any]) -> MarketSummary | None:
    """Return a fresh cached summary or start one non-blocking refresh."""
    global _rich_summary_cache, _rich_summary_inflight_key

    from .sentiment import prepare_market_summary_data  # noqa: PLC0415

    snapshot = prepare_market_summary_data(market_data)
    if snapshot is None:
        return None
    cache_key = _market_data_cache_key(snapshot)
    should_start = False
    with _rich_summary_lock:
        now = time.monotonic()
        cached = _rich_summary_cache
        if cached is not None and cached.key == cache_key and cached.expires_at > now:
            return cached.summary
        if cached is not None and cached.expires_at <= now:
            _rich_summary_cache = None
        if _rich_summary_inflight_key is None:
            _rich_summary_inflight_key = cache_key
            should_start = True

    if should_start:
        try:
            worker = threading.Thread(
                target=_refresh_rich_summary_cache,
                args=(cache_key, snapshot),
                name="flinttrade-market-summary",
                daemon=True,
            )
            worker.start()
        except Exception as exc:
            with _rich_summary_lock:
                if _rich_summary_inflight_key == cache_key:
                    _rich_summary_inflight_key = None
            logger.warning("sentiment/summary: could not start rich refresh (%s)", exc)
    return None


def _rss_market_summary(scores: list[Any]) -> MarketSummary:
    """Build the typed frontend contract from confidence-weighted RSS scores."""
    values = [_score_value(score) for score in scores]
    net = sum(values) / len(values) if values else 0.0
    sentiment_score = round(net * 10.0, 4)
    label: SentimentLabel = sentiment_label_from_score(sentiment_score)

    if scores:
        bullish = sum(str(getattr(score, "sentiment", "")).upper() == "BULLISH" for score in scores)
        bearish = sum(str(getattr(score, "sentiment", "")).upper() == "BEARISH" for score in scores)
        neutral = len(scores) - bullish - bearish
        label_text = label.value.replace("_", " ").lower()
        key_points = [
            f"Analysed {len(scores)} recent market-news articles.",
            f"Article mix: {bullish} bullish, {bearish} bearish, {neutral} neutral.",
            f"Confidence-weighted news sentiment is {label_text}.",
        ]
    else:
        key_points = [
            "No live news feed is currently available.",
            "Index and sector market data are not connected.",
            "Connect a market-data provider for a structured market summary.",
        ]

    return MarketSummary(
        sentiment_score=sentiment_score,
        market_sentiment=label,
        indices=[],
        sectors=[],
        key_points=key_points,
        fii_dii_flow=FiiDiiFlow(
            fii_net=0.0,
            dii_net=0.0,
            interpretation="FII/DII flow not connected; zero values are placeholders.",
        ),
        risks=[],
        opportunities=[],
    )


@ai_bp.route("/ai/sentiment/summary", methods=["GET"])
def sentiment_summary() -> tuple[Any, int]:
    """Market-wide sentiment summary for the terminal's Market Sentiment panel.

    Aggregates net sentiment from the configured news feeds. Market-structure
    fields (indices, sectors, FII/DII) are returned empty/neutral here — they
    need a connected market-data source — so the panel renders a calm state
    rather than a 404, and never shows fabricated bull/bear numbers.
    """
    market_data = _market_sentiment_data()
    if market_data is not None:
        rich_summary = _cached_or_schedule_rich_summary(market_data)
        if rich_summary is not None:
            return jsonify({"status": "success", "data": rich_summary.to_display_dict()}), 200

    scores: list[Any] = []
    try:
        from .sentiment import SentimentAnalyzer  # noqa: PLC0415

        scores = SentimentAnalyzer().analyze_feeds()
    except Exception as exc:  # no feed / network / LLM — honest neutral fallback
        logger.info("sentiment/summary: no feed data (%s)", exc)

    summary = _rss_market_summary(scores)
    return jsonify({"status": "success", "data": summary.to_display_dict()}), 200


@ai_bp.route("/ai/sentiment/tickers", methods=["GET"])
def sentiment_tickers() -> tuple[Any, int]:
    """Per-ticker sentiment for the Market Sentiment panel.

    Scores sentiment per symbol from the news feeds; returns an empty list when
    no feed data is available (the panel shows a calm empty state, not a 404).
    """
    tickers: list[dict[str, Any]] = []
    try:
        from .sentiment import SentimentAnalyzer, aggregate_sentiment  # noqa: PLC0415

        scores = SentimentAnalyzer().analyze_feeds()
        symbols: set[str] = set()
        for s in scores:
            symbols.update(getattr(s, "symbols", []) or [])
        for sym in sorted(symbols):
            agg = aggregate_sentiment(scores, sym)
            net = float(getattr(agg, "net_score", 0.0) or 0.0)
            label = "positive" if net > 0.15 else "negative" if net < -0.15 else "neutral"
            tickers.append(
                {
                    "ticker": sym,
                    "score": round(net * 10.0, 2),  # -10..+10 scale
                    "label": label,
                    "key_factor": str(getattr(agg, "dominant_sentiment", "")) or "news sentiment",
                }
            )
    except Exception as exc:
        logger.info("sentiment/tickers: no feed data (%s)", exc)

    return jsonify({"status": "success", "data": {"tickers": tickers}}), 200


def _free_daily_ohlcv(
    symbol: str,
    exchange: str = "NSE",
    lookback_days: int = 220,
) -> tuple[list[float], list[float], list[float]]:
    """Free daily OHLCV (OpenChart) for the disconnected / Explore regime fallback.

    Returns ``([], [], [])`` when the source is unavailable (e.g. ``openchart``
    not installed, or no data) so the caller surfaces a clear "not enough
    history" message rather than a 500.
    """
    try:
        from datetime import datetime, timedelta  # noqa: PLC0415

        from flinttrade_historical.free_data import NSEData  # noqa: PLC0415

        end = datetime.now()
        start = end - timedelta(days=lookback_days)
        result = NSEData().historical(
            symbol,
            exchange,
            start.strftime("%Y-%m-%d"),
            end.strftime("%Y-%m-%d"),
            "1d",
        )
        if not result.success:
            return [], [], []
        return (
            [float(b.high) for b in result.bars],
            [float(b.low) for b in result.bars],
            [float(b.close) for b in result.bars],
        )
    except Exception:
        logger.exception("free OHLCV fallback failed for %s", symbol)
        return [], [], []


@ai_bp.route("/ai/regime", methods=["GET"])
def market_regime() -> tuple[Any, int]:
    """Market regime (ADX/ATR/BB) for a symbol — the AI Regime panel.

    Computes the regime from a connected broker's OHLCV when available, otherwise
    falls back to free daily history (OpenChart) so the panel works for
    disconnected / Explore users too. Only returns 503 when NEITHER source can
    supply enough history.
    """
    symbol = (request.args.get("symbol") or "NIFTY").strip()
    registry = current_app.config.get("REGISTRY")
    connected = bool(registry) and bool(getattr(registry, "is_connected", lambda: False)())

    try:
        from .regime_detector import detect_regime_detailed, select_strategy_for_regime  # noqa: PLC0415

        if connected:
            params = {"symbol": symbol, "exchange": "NSE_INDEX", "interval": "D"}
            history = registry.get_history(registry.get_primary_account_id(), params)
            candles = history.get("data") or history.get("candles") or []
            highs = [float(c["high"]) for c in candles]
            lows = [float(c["low"]) for c in candles]
            closes = [float(c["close"]) for c in candles]
            source = "broker"
        else:
            highs, lows, closes = _free_daily_ohlcv(symbol)
            source = "openchart"

        if len(closes) < 20:
            suffix = "" if connected else " — download daily data or connect a broker."
            return jsonify(
                {
                    "status": "error",
                    "message": f"Not enough history for {symbol} to compute a regime{suffix}",
                }
            ), 503

        result = detect_regime_detailed(highs, lows, closes)
        data = result.to_dict()
        # Close the loop: recommend a regime-appropriate strategy style.
        data["suggested_strategy"] = select_strategy_for_regime(result.state).to_dict()
        data["data_source"] = source
        return jsonify({"status": "success", "data": data}), 200
    except Exception:
        logger.exception("market_regime error")
        return jsonify({"status": "error", "message": "Internal server error"}), 500


@ai_bp.route("/ai/optimiser/reports", methods=["GET"])
def optimiser_reports() -> tuple[Any, int]:
    """List overnight optimisation reports, newest first — the Lab Optimise tab.

    Returns an empty list (not an error) when none exist yet, so the UI shows a
    'no reports yet' state rather than a failure.
    """
    store = current_app.config.get("OPTIMISER_REPORT_STORE")
    if store is None:
        return jsonify({"status": "success", "data": {"reports": []}}), 200
    try:
        return jsonify({"status": "success", "data": {"reports": store.list_reports()}}), 200
    except Exception:
        logger.exception("optimiser_reports error")
        return jsonify({"status": "error", "message": "Internal server error"}), 500


@ai_bp.route("/ai/optimiser/reports/latest", methods=["GET"])
def optimiser_report_latest() -> tuple[Any, int]:
    """Return the most recent overnight optimisation report, or ``null`` when none."""
    store = current_app.config.get("OPTIMISER_REPORT_STORE")
    try:
        report = store.latest() if store is not None else None
        return jsonify({"status": "success", "data": {"report": report}}), 200
    except Exception:
        logger.exception("optimiser_report_latest error")
        return jsonify({"status": "error", "message": "Internal server error"}), 500


@ai_bp.route("/ai/refine-strategy", methods=["POST"])
def refine_strategy() -> tuple[Any, int]:
    """Analyse backtest results and suggest parameter improvements.

    Accepts backtest metrics and current strategy parameters, then delegates
    to :class:`~flinttrade_ai.strategy_refiner.StrategyRefiner` — using the
    configured LLM when available, or falling back to rule-based heuristics.

    Request JSON:
        strategy_name (str): Name of the strategy.
        backtest_results (dict): Metrics from the backtest engine.  Expected
            keys: ``sharpe_ratio``, ``max_drawdown``, ``win_rate``,
            ``total_trades``, ``total_return``, ``profit_factor``.
        current_params (dict): Current parameter values for the strategy.

    Returns:
        JSON with ``status`` and ``data`` containing ``analysis``,
        ``suggested_params``, ``reasoning``, ``confidence``, and ``timestamp``.
    """
    body = request.get_json(silent=True) or {}
    strategy_name: str = body.get("strategy_name", "").strip()
    backtest_results: dict = body.get("backtest_results") or {}
    current_params: dict = body.get("current_params") or {}

    if not strategy_name:
        return jsonify({"status": "error", "message": "strategy_name is required"}), 400
    if not backtest_results:
        return jsonify({"status": "error", "message": "backtest_results is required"}), 400

    try:
        from .strategy_refiner import StrategyRefiner  # noqa: PLC0415

        llm_client = None
        if _is_llm_configured():
            from .llm_client import LLMClient  # noqa: PLC0415

            try:
                llm_client = LLMClient()
            except Exception as exc:  # noqa: BLE001
                logger.warning("Could not create LLM client for refiner: %s", exc)

        refiner = StrategyRefiner(llm_client=llm_client)
        suggestion = refiner.refine(strategy_name, backtest_results, current_params)

        if llm_client is not None:
            try:
                llm_client.close()
            except Exception:  # noqa: BLE001
                pass

        return jsonify({"status": "success", "data": suggestion.to_dict()}), 200
    except Exception:
        logger.exception("refine_strategy error")
        return jsonify({"status": "error", "message": "Internal server error"}), 500


@ai_bp.route("/rag/query", methods=["POST"])
def rag_query() -> tuple[Any, int]:
    """Query the RAG knowledge base.

    Request JSON:
        query (str): Natural language query.
        top_k (int, optional): Number of results to return (default 5).

    Returns:
        JSON with ``status``, the generated ``data.answer``, and
        ``data.results`` source objects shaped as ``{content, source, score}``.
    """
    body = request.get_json(silent=True) or {}
    query: str = body.get("query", "").strip()
    try:
        top_k: int = min(max(int(body.get("top_k", 5)), 1), 50)
    except (ValueError, TypeError):
        return jsonify({"status": "error", "message": "top_k must be an integer"}), 400

    if not query:
        return jsonify({"status": "error", "message": "query is required"}), 400

    try:
        rag = current_app.config.get("RAG")
        if rag is None:
            message = (
                "RAG runtime disabled"
                if current_app.config.get("RAG_STATUS") == "disabled"
                else "RAG engine not available"
            )
            return jsonify(
                {
                    "status": "error",
                    "message": message,
                }
            ), 503

        response = rag.query(query, top_k=top_k)

        if response.error == "No relevant documents found":
            return jsonify({"status": "success", "data": {"answer": "", "results": []}}), 200

        if response.error:
            return jsonify({"status": "error", "message": "RAG query failed"}), 502

        results = [
            {
                "content": chunk.content,
                "source": chunk.source,
                "score": round(chunk.score, 4),
            }
            for chunk in response.chunks_used
        ]
        return jsonify({"status": "success", "data": {"answer": response.answer, "results": results}}), 200
    except Exception:
        logger.exception("rag_query error")
        return jsonify({"status": "error", "message": "Internal server error"}), 500
