"""Flask blueprint for VWAP bands, pair correlation, and multi-timeframe endpoints.

External URLs (frontend calls these via /ft-api/v1/*; the WSGI prefix stripper
in app.py rewrites to /v1/* before Flask dispatch):

    POST /ft-api/v1/indicators/vwap    — VWAP with ±1σ/2σ/3σ bands
    POST /ft-api/v1/analytics/pairs   — Pair correlation and z-score signals
    POST /ft-api/v1/analytics/mtf     — Multi-timeframe signal confluence
    POST /ft-api/v1/analytics/seasonality — Monthly/weekday/day-of-month return patterns

Blueprint registered at ``/v1`` (post-strip form).

All endpoints:
1. Extract parameters from the JSON request body.
2. Validate required fields and types; return HTTP 400 on bad input.
3. Delegate computation to the relevant engine class.
4. Return JSON with a consistent ``{"status": "success", "data": {...}}`` envelope.
5. Fall back to sample/synthetic data in dev mode (no broker connection required).

Pattern follows payoff_routes.py in this package.
"""

from __future__ import annotations

import logging
import math
from dataclasses import asdict
from typing import TYPE_CHECKING, Any

from flask import Blueprint, jsonify, request

from .multi_timeframe import MultiTimeframeAnalyser, make_sample_mtf_data
from .pair_correlation import PairCorrelationEngine, make_sample_pair_data

if TYPE_CHECKING:
    import pandas as pd

logger = logging.getLogger("flinttrade.screener.analytics_routes")

analytics_bp = Blueprint("analytics_ext", __name__, url_prefix="/v1")

# Engine singletons (created once per process)
_pair_engine = PairCorrelationEngine()
_mtf_analyser = MultiTimeframeAnalyser()


# ---------------------------------------------------------------------------
# POST /ft-api/v1/indicators/vwap
# ---------------------------------------------------------------------------


@analytics_bp.route("/indicators/vwap", methods=["POST"])
def indicators_vwap() -> Any:
    """Calculate intraday VWAP with ±1σ / ±2σ / ±3σ standard deviation bands.

    Request JSON:
        bars (list[dict]): OHLCV bars, sorted oldest-first.  Each bar must
            contain: ``timestamp`` (str, ISO), ``high`` (float), ``low``
            (float), ``close`` (float), ``volume`` (float).
            ``open`` is accepted but not used for VWAP.
        session_reset (bool, optional): Reset VWAP accumulator at each new
            calendar date (default ``true``).

    Returns:
        JSON::

            {
              "status": "success",
              "data": {
                "timestamps": ["2025-01-15T09:15:00", ...],
                "vwap":    [24012.3, ...],
                "upper_1": [24050.1, ...],
                "upper_2": [24088.0, ...],
                "upper_3": [24125.8, ...],
                "lower_1": [23974.5, ...],
                "lower_2": [23936.6, ...],
                "lower_3": [23898.8, ...]
              }
            }

        On error::

            {"status": "error", "message": "..."}
    """
    from flinttrade_indicators.vwap_bands import calculate_vwap_bands  # noqa: PLC0415

    body = request.get_json(silent=True) or {}
    bars = body.get("bars")
    session_reset = bool(body.get("session_reset", True))

    if not bars:
        # Dev fallback — generate sample intraday data
        logger.debug("VWAP endpoint: no bars provided, using sample data")
        bars = _make_sample_vwap_bars()

    if not isinstance(bars, list) or len(bars) == 0:
        return jsonify({"status": "error", "message": "'bars' must be a non-empty list"}), 400

    try:
        result = calculate_vwap_bands(bars, session_reset=session_reset)
    except ValueError:
        return jsonify({"status": "error", "message": "Invalid request"}), 400
    except Exception as exc:
        logger.exception("VWAP calculation failed: %s", exc)
        return jsonify({"status": "error", "message": "VWAP calculation failed"}), 500

    # An all-zero-volume session (index symbols) makes VWAP undefined —
    # NaN would serialise as literal ``NaN``, which is invalid JSON that
    # browsers reject. Sanitise to null so callers can fall back honestly.
    data = result.model_dump()
    for key, values in data.items():
        if isinstance(values, list):
            data[key] = [
                None if isinstance(v, float) and math.isnan(v) else v for v in values
            ]

    return jsonify({"status": "success", "data": data})


# ---------------------------------------------------------------------------
# POST /ft-api/v1/analytics/pairs
# ---------------------------------------------------------------------------


@analytics_bp.route("/analytics/pairs", methods=["POST"])
def analytics_pairs() -> Any:
    """Analyse correlated instrument pairs for spread divergence.

    Request JSON (two modes):

    Mode 1 — explicit pairs::

        {
          "pairs": [
            {
              "symbol_a": "TCS",
              "symbol_b": "INFY",
              "returns_a": [...],
              "returns_b": [...],
              "prices_a":  [...],
              "prices_b":  [...]
            }
          ]
        }

    Mode 2 — preset pairs (pass data for each symbol)::

        {
          "preset": true,
          "data": {
            "TCS":  {"returns": [...], "prices": [...]},
            "INFY": {"returns": [...], "prices": [...]}
          }
        }

    Returns:
        JSON::

            {
              "status": "success",
              "data": {
                "signals": [
                  {
                    "pair": ["TCS", "INFY"],
                    "correlation": 0.87,
                    "current_spread": 2100.0,
                    "mean_spread": 2050.3,
                    "std_spread": 120.5,
                    "z_score": 0.41,
                    "signal": "converging"
                  },
                  ...
                ]
              }
            }
    """
    body = request.get_json(silent=True) or {}
    use_preset = bool(body.get("preset", False))

    if use_preset:
        data = body.get("data")
        if not data:
            # Dev fallback
            logger.debug("Pairs endpoint: no data provided, using sample data")
            data = make_sample_pair_data()

        if not isinstance(data, dict):
            return jsonify({"status": "error", "message": "'data' must be an object"}), 400

        try:
            signals = _pair_engine.analyse_all_presets(data)
        except Exception as exc:
            logger.exception("Pair preset analysis failed: %s", exc)
            return jsonify({"status": "error", "message": "Pair analysis failed"}), 500

    else:
        raw_pairs = body.get("pairs")
        if not raw_pairs:
            # Dev fallback with preset
            logger.debug("Pairs endpoint: no pairs provided, using sample data")
            data = make_sample_pair_data()
            signals = _pair_engine.analyse_all_presets(data)
        else:
            if not isinstance(raw_pairs, list):
                return jsonify({"status": "error", "message": "'pairs' must be a list"}), 400

            signals = []
            for i, entry in enumerate(raw_pairs):
                if not isinstance(entry, dict):
                    return jsonify({
                        "status": "error",
                        "message": f"pairs[{i}] must be an object",
                    }), 400

                sym_a = str(entry.get("symbol_a", "A"))
                sym_b = str(entry.get("symbol_b", "B"))
                try:
                    sig = _pair_engine.analyse_pair(
                        returns_a=list(entry.get("returns_a", [])),
                        returns_b=list(entry.get("returns_b", [])),
                        prices_a=list(entry.get("prices_a", [])),
                        prices_b=list(entry.get("prices_b", [])),
                        pair=(sym_a, sym_b),
                    )
                    signals.append(sig)
                except Exception as exc:
                    logger.exception("Pair analysis failed for %s/%s: %s", sym_a, sym_b, exc)
                    return jsonify({
                        "status": "error",
                        "message": f"Analysis failed for pair {sym_a}/{sym_b}",
                    }), 500

    return jsonify({
        "status": "success",
        "data": {"signals": [s.model_dump() for s in signals]},
    })


# ---------------------------------------------------------------------------
# POST /ft-api/v1/analytics/mtf
# ---------------------------------------------------------------------------


@analytics_bp.route("/analytics/mtf", methods=["POST"])
def analytics_mtf() -> Any:
    """Analyse signal alignment across multiple timeframes for a symbol.

    Request JSON::

        {
          "symbol": "NIFTY",
          "data": {
            "5m":  [{"timestamp": "...", "open": f, "high": f,
                     "low": f, "close": f, "volume": f}, ...],
            "15m": [...],
            "1h":  [...],
            "1D":  [...]
          }
        }

    Returns:
        JSON::

            {
              "status": "success",
              "data": {
                "symbol": "NIFTY",
                "signals": [
                  {
                    "timeframe": "5m",
                    "trend": "bullish",
                    "rsi": 58.3,
                    "macd_histogram": 12.5,
                    "ema_position": "above",
                    "strength": 0.72
                  },
                  ...
                ],
                "confluence": 0.75,
                "overall": "bullish"
              }
            }
    """
    body = request.get_json(silent=True) or {}
    symbol = str(body.get("symbol", "NIFTY"))
    data_by_tf = body.get("data")

    if not data_by_tf:
        # Dev fallback
        logger.debug("MTF endpoint: no data provided, using sample data for %s", symbol)
        data_by_tf = make_sample_mtf_data()

    if not isinstance(data_by_tf, dict):
        return jsonify({"status": "error", "message": "'data' must be an object"}), 400

    try:
        result = _mtf_analyser.analyse(symbol=symbol, data_by_tf=data_by_tf)
    except Exception as exc:
        logger.exception("MTF analysis failed for %s: %s", symbol, exc)
        return jsonify({"status": "error", "message": "Multi-timeframe analysis failed"}), 500

    return jsonify({"status": "success", "data": result.model_dump()})


# ---------------------------------------------------------------------------
# POST /ft-api/v1/analytics/seasonality
# ---------------------------------------------------------------------------


@analytics_bp.route("/analytics/seasonality", methods=["POST"])
def analytics_seasonality() -> Any:
    """Compute monthly/weekday/day-of-month return seasonality from daily bars.

    Wires the previously-unconsumed ``flinttrade_indicators.seasonality``
    module. Callers supply daily OHLCV bars for one symbol (typically fetched
    via the shared ``/api/v1/history`` path, matching how the MTF endpoint is
    fed); the endpoint aggregates them into calendar-pattern statistics.

    Request JSON:
        symbol (str, optional): Label echoed back in the response
            (default ``"NIFTY"``).
        exchange (str, optional): Label echoed back in the response
            (default ``"NSE_INDEX"``).
        bars (list[dict], optional): Daily bars, oldest-first. Each bar needs
            ``close`` (float) and one of ``timestamp``/``time``/``date`` —
            epoch seconds, epoch milliseconds, or an ISO date string. When
            absent, a deterministic synthetic series is used (dev fallback)
            and ``is_sample_data`` is ``true``.

    Returns:
        JSON::

            {
              "status": "success",
              "data": {
                "symbol": "NIFTY",
                "exchange": "NSE_INDEX",
                "is_sample_data": false,
                "monthly": [
                  {"month": 1, "month_name": "January",
                   "avg_return_pct": 1.2, "median_return_pct": 0.9,
                   "std_pct": 3.1, "positive_rate": 0.6, "years_count": 10,
                   "best_year": [2021, 6.2], "worst_year": [2020, -4.8]},
                  ...
                ],
                "weekday": [
                  {"weekday": 0, "weekday_name": "Monday",
                   "avg_return_pct": -0.03, "std_pct": 1.1,
                   "positive_rate": 0.49, "sample_count": 512},
                  ...
                ],
                "day_of_month": [{"day": 1, "avg_return_pct": 0.12}, ...],
                "matrix": {
                  "years": [2016, ...],
                  "months": [1, ..., 12],
                  "returns": [[1.2, null, ...], ...]
                }
              }
            }

    Errors:
        400: ``bars`` is not a list, or no bar could be parsed.
        422: Series too short to compute any seasonality statistics.
    """
    import pandas as pd  # noqa: PLC0415
    from flinttrade_indicators.seasonality import (  # noqa: PLC0415
        build_seasonality_matrix,
        compute_day_of_month_seasonality,
        compute_monthly_seasonality,
        compute_weekday_seasonality,
    )

    body = request.get_json(silent=True) or {}
    symbol = str(body.get("symbol", "NIFTY"))
    exchange = str(body.get("exchange", "NSE_INDEX"))
    bars = body.get("bars")

    is_sample_data = False
    if not bars:
        # Dev fallback — deterministic synthetic daily series, honestly flagged
        logger.debug("Seasonality endpoint: no bars provided, using sample data for %s", symbol)
        bars = _make_sample_seasonality_bars()
        is_sample_data = True

    if not isinstance(bars, list):
        return jsonify({"status": "error", "message": "'bars' must be a non-empty list"}), 400

    try:
        ohlc = _bars_to_close_frame(bars)
    except ValueError as exc:
        return jsonify({"status": "error", "message": str(exc)}), 400

    try:
        monthly = compute_monthly_seasonality(ohlc)
        weekday = compute_weekday_seasonality(ohlc)
        day_of_month = compute_day_of_month_seasonality(ohlc)
        matrix = build_seasonality_matrix(ohlc)
    except Exception as exc:
        logger.exception("Seasonality calculation failed for %s: %s", symbol, exc)
        return jsonify({"status": "error", "message": "Seasonality calculation failed"}), 500

    if not monthly and not weekday and not day_of_month:
        return jsonify({
            "status": "error",
            "message": "Bar series too short to compute any seasonality statistics. "
                       "Supply at least two daily closes (ideally several years).",
        }), 422

    matrix_years = [int(year) for year in matrix.index]
    matrix_returns = [
        [None if pd.isna(value) else round(float(value), 4) for value in row]
        for row in matrix.to_numpy()
    ]

    return jsonify({
        "status": "success",
        "data": {
            "symbol": symbol,
            "exchange": exchange,
            "is_sample_data": is_sample_data,
            "monthly": [asdict(stats) for stats in monthly],
            "weekday": [asdict(stats) for stats in weekday],
            "day_of_month": [
                {"day": day, "avg_return_pct": value}
                for day, value in sorted(day_of_month.items())
            ],
            "matrix": {
                "years": matrix_years,
                "months": list(range(1, 13)),
                "returns": matrix_returns,
            },
        },
    })


_EPOCH_MILLIS_THRESHOLD = 4_102_444_800  # beyond 2100 in seconds → millisecond stamp


def _bars_to_close_frame(bars: list[Any]) -> pd.DataFrame:
    """Convert request bars into the close-price DataFrame the indicators expect.

    Args:
        bars: Bar dicts, each with ``close`` and one of ``timestamp``/``time``/
            ``date`` (epoch seconds, epoch milliseconds, or ISO string).

    Returns:
        DataFrame with a sorted ``DatetimeIndex`` and a single ``close`` column.

    Raises:
        ValueError: If no bar could be parsed into a dated close.
    """
    import pandas as pd  # noqa: PLC0415

    stamps: list[Any] = []
    closes: list[float] = []
    for bar in bars:
        if not isinstance(bar, dict):
            continue
        raw_ts = bar.get("timestamp", bar.get("time", bar.get("date")))
        raw_close = bar.get("close")
        if raw_ts is None or raw_close is None:
            continue
        try:
            close = float(raw_close)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(close) or close <= 0:
            continue
        try:
            if isinstance(raw_ts, bool):
                continue
            if isinstance(raw_ts, (int, float)):
                seconds = float(raw_ts)
                if seconds > _EPOCH_MILLIS_THRESHOLD:
                    seconds /= 1000.0
                stamp = pd.Timestamp(seconds, unit="s")
            else:
                stamp = pd.Timestamp(str(raw_ts))
        except (TypeError, ValueError):
            continue
        if pd.isna(stamp):
            continue
        stamps.append(stamp)
        closes.append(close)

    if not stamps:
        raise ValueError(
            "No usable bars: each bar needs a 'close' and a 'timestamp'/'time'/'date'"
        )

    frame = pd.DataFrame({"close": closes}, index=pd.DatetimeIndex(stamps))
    return frame.sort_index()


# ---------------------------------------------------------------------------
# Private sample-data helpers
# ---------------------------------------------------------------------------


def _make_sample_seasonality_bars(years: int = 6, seed: int = 7) -> list[dict]:
    """Generate synthetic daily close bars for seasonality dev/fallback mode.

    Weekday-only bars covering ``years`` calendar years (ending 2025-12-31)
    with a mild upward drift plus deterministic noise, so every calendar view
    (monthly, weekday, day-of-month) has plausible non-zero statistics.

    Args:
        years: Number of calendar years to generate.
        seed:  Random seed for reproducibility.

    Returns:
        List of bar dicts with keys ``timestamp`` (ISO date) and ``close``.
    """
    import random  # noqa: PLC0415
    from datetime import date, timedelta  # noqa: PLC0415

    rng = random.Random(seed)
    end = date(2025, 12, 31)
    start = date(end.year - max(years, 1) + 1, 1, 1)
    close = 20_000.0
    bars: list[dict] = []
    day = start
    while day <= end:
        if day.weekday() < 5:  # Monday–Friday trading days only
            close = max(close * (1.0 + rng.gauss(0.0004, 0.009)), 100.0)
            bars.append({"timestamp": day.isoformat(), "close": round(close, 2)})
        day += timedelta(days=1)
    return bars


def _make_sample_vwap_bars(n: int = 75, seed: int = 0) -> list[dict]:
    """Generate synthetic intraday OHLCV bars for VWAP dev/fallback mode.

    Args:
        n:    Number of bars to generate.
        seed: Random seed for reproducibility.

    Returns:
        List of OHLCV bar dicts with keys
        ``timestamp``, ``open``, ``high``, ``low``, ``close``, ``volume``.
    """
    import random

    rng = random.Random(seed)
    close = 24000.0
    bars = []
    for i in range(n):
        ret = rng.gauss(0.0, 0.002)
        close = max(close * (1.0 + ret), 1.0)
        spread = close * 0.001
        open_ = close + rng.uniform(-spread, spread)
        high = max(open_, close) + abs(rng.gauss(0, spread * 0.5))
        low = min(open_, close) - abs(rng.gauss(0, spread * 0.5))
        minute = i % 375   # NSE trading minutes (9:15 to 15:30)
        hour = 9 + minute // 60
        minute_of_hour = 15 + minute % 60
        if minute_of_hour >= 60:
            hour += 1
            minute_of_hour -= 60
        ts = f"2025-01-15T{hour:02d}:{minute_of_hour:02d}:00"
        bars.append({
            "timestamp": ts,
            "open": round(open_, 2),
            "high": round(high, 2),
            "low": round(low, 2),
            "close": round(close, 2),
            "volume": round(rng.uniform(1000, 30000), 0),
        })
    return bars
