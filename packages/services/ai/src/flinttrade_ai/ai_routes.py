"""AI blueprint — /api/v1/signals/active, /sentiment/analyse, /rag/query endpoints.

Active signal pipeline polling, sentiment analysis via LLM or rule-based
fallback, and RAG knowledge-base query.
"""

from __future__ import annotations

import logging
from typing import Any

from flask import Blueprint, current_app, jsonify, request

from .llm_client import LLMConfig

logger = logging.getLogger("flinttrade")

ai_bp = Blueprint("ai", __name__, url_prefix="/api/v1")


def _is_llm_configured() -> bool:
    """Check whether the LLM provider is configured."""
    try:
        cfg = LLMConfig.from_env()
        return bool(cfg.provider)
    except Exception:
        return False


@ai_bp.route("/signals/active", methods=["GET"])
def signals_active() -> tuple[Any, int]:
    """Return currently active trading signals from the signal pipeline.

    Returns:
        JSON with ``status`` and ``data.signals`` — a list of signal
        objects with ``symbol``, ``exchange``, ``signal_type``,
        ``confidence``, ``timestamp``, and ``indicators`` fields.
        Returns an empty list if the pipeline has not yet produced signals.
    """
    try:
        from .pipeline import SignalPipeline  # noqa: PLC0415

        # Use a module-level singleton if already running, otherwise return empty
        pipeline: SignalPipeline | None = getattr(current_app, "_signal_pipeline", None)
        if pipeline is None:
            return jsonify({"status": "success", "data": {"signals": []}}), 200

        raw_signals = pipeline.latest_signals
        signals = [
            {
                "symbol": info.get("symbol", key.split(":")[-1]),
                "exchange": info.get("exchange", key.split(":")[0]),
                "signal_type": info.get("signal", "NEUTRAL"),
                "confidence": info.get("confidence", 0.0),
                "timestamp": info.get("timestamp", ""),
                "indicators": {k: v for k, v in info.items()
                               if k not in ("symbol", "exchange", "signal", "confidence", "timestamp")},
            }
            for key, info in raw_signals.items()
        ]
        return jsonify({"status": "success", "data": {"signals": signals}}), 200
    except Exception:
        logger.exception("signals_active error")
        return jsonify({"status": "error", "message": "Internal server error"}), 500


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
        return jsonify({
            "status": "error",
            "message": "LLM not configured. Sentiment analysis requires an LLM provider.",
        }), 503

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
        try:
            llm_client = LLMClient()
            scored = score_article_with_llm(article, llm_client)
            llm_client.close()
        except Exception as llm_exc:
            logger.warning("LLM sentiment failed, using rule-based: %s", llm_exc)
            scored = score_article_rule_based(article)

        label_map = {"BULLISH": "bullish", "BEARISH": "bearish", "NEUTRAL": "neutral"}
        label = label_map.get(scored.sentiment.upper(), "neutral")

        # Convert sentiment to numeric score: bullish=+confidence, bearish=-confidence
        if label == "bullish":
            score = scored.confidence
        elif label == "bearish":
            score = -scored.confidence
        else:
            score = 0.0

        return jsonify({
            "status": "success",
            "data": {
                "score": round(score, 4),
                "label": label,
                "confidence": round(scored.confidence, 4),
                "reasoning": scored.reasoning,
            },
        }), 200
    except Exception:
        logger.exception("sentiment_analyze error")
        return jsonify({"status": "error", "message": "Internal server error"}), 500


def _net_to_label(net: float) -> str:
    """Map a net sentiment score (-1..1) to a bullish/bearish/neutral label."""
    return "bullish" if net > 0.15 else "bearish" if net < -0.15 else "neutral"


def _score_value(score: Any) -> float:
    """Signed numeric value of a SentimentScore (+conf bullish, -conf bearish)."""
    sentiment = str(getattr(score, "sentiment", "NEUTRAL")).upper()
    conf = float(getattr(score, "confidence", 0.0) or 0.0)
    if sentiment == "BULLISH":
        return conf
    if sentiment == "BEARISH":
        return -conf
    return 0.0


@ai_bp.route("/ai/sentiment/summary", methods=["GET"])
def sentiment_summary() -> tuple[Any, int]:
    """Market-wide sentiment summary for the terminal's Market Sentiment panel.

    Aggregates net sentiment from the configured news feeds. Market-structure
    fields (indices, sectors, FII/DII) are returned empty/neutral here — they
    need a connected market-data source — so the panel renders a calm state
    rather than a 404, and never shows fabricated bull/bear numbers.
    """
    scores: list[Any] = []
    try:
        from .sentiment import SentimentAnalyzer  # noqa: PLC0415

        scores = SentimentAnalyzer().analyze_feeds()
    except Exception as exc:  # no feed / network / LLM — honest neutral fallback
        logger.info("sentiment/summary: no feed data (%s)", exc)

    nums = [_score_value(s) for s in scores]
    net = sum(nums) / len(nums) if nums else 0.0
    key_points = (
        []
        if scores
        else ["No live news feed available — connect a data source for full market sentiment."]
    )

    return jsonify({
        "status": "success",
        "data": {
            "sentiment_score": round(net, 4),
            "market_sentiment": _net_to_label(net),
            "indices": [],
            "sectors": [],
            "key_points": key_points,
            "fii_dii_flow": {
                "fii_net": 0.0,
                "dii_net": 0.0,
                "interpretation": "FII/DII flow not connected.",
            },
            "risks": [],
            "opportunities": [],
        },
    }), 200


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
            tickers.append({
                "ticker": sym,
                "score": round(net * 10.0, 2),  # -10..+10 scale
                "label": label,
                "key_factor": str(getattr(agg, "dominant_sentiment", "")) or "news sentiment",
            })
    except Exception as exc:
        logger.info("sentiment/tickers: no feed data (%s)", exc)

    return jsonify({"status": "success", "data": {"tickers": tickers}}), 200


def _free_daily_ohlcv(
    symbol: str, exchange: str = "NSE", lookback_days: int = 220,
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
            symbol, exchange, start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"), "1d",
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
            return jsonify({
                "status": "error",
                "message": f"Not enough history for {symbol} to compute a regime{suffix}",
            }), 503

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
        JSON with ``status`` and ``data.results`` — a list of
        ``{content, source, score}`` objects.
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
            return jsonify({
                "status": "error",
                "message": "RAG engine not available",
            }), 503

        response = rag.query(query, n_results=top_k)

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
        return jsonify({"status": "success", "data": {"results": results}}), 200
    except Exception:
        logger.exception("rag_query error")
        return jsonify({"status": "error", "message": "Internal server error"}), 500
