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
            return jsonify({"status": "error", "message": response.error}), 502

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
