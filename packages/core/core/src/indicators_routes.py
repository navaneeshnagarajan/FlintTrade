"""Indicators blueprint — /api/v1/indicators/* endpoints.

Computes technical indicators (EMA, SMA, MACD, Bollinger Bands, etc.) over
OHLCV bar series supplied by the frontend.
"""

from __future__ import annotations

import logging
import math
from typing import Any

import numpy as np
from flask import Blueprint, jsonify, request

logger = logging.getLogger("flinttrade")

indicators_bp = Blueprint("indicators", __name__, url_prefix="/api/v1")


@indicators_bp.route("/indicators/compute", methods=["POST"])
def indicators_compute() -> tuple[Any, int]:
    """Compute one or more technical indicators over a OHLCV bar series.

    Request JSON:
        bars (list[dict]): OHLCV bars, each with keys
            ``time`` (int, Unix seconds), ``open``, ``high``, ``low``,
            ``close`` (float), ``volume`` (float, optional).
        indicators (list[str]): Indicator names such as ``"ema_20"``,
            ``"macd"``, ``"bollinger_bands_20"``, ``"atr_14"``.

    Returns:
        JSON with ``status`` and ``data`` mapping each indicator name to
        its computed values on success, or ``status`` and ``message``
        on error.  Arrays contain ``null`` for bars with insufficient
        history.  Multi-line indicators (MACD, Bollinger Bands, Keltner
        Channels) return a dict of named sub-arrays.
    """
    from flinttrade_indicators import (  # noqa: PLC0415
        atr,
        bollinger_bands,
        cci,
        dema,
        ema,
        hull,
        keltner_channels,
        macd,
        obv,
        parabolic_sar,
        rsi,
        sma,
        supertrend,
        vwap,
        vwma,
        williams_r,
        wma,
    )

    body = request.get_json(silent=True) or {}
    raw_bars = body.get("bars")
    raw_indicators = body.get("indicators")

    if not isinstance(raw_bars, list) or len(raw_bars) == 0:
        return jsonify({
            "status": "error",
            "message": "bars must be a non-empty list.",
        }), 400

    if not isinstance(raw_indicators, list) or len(raw_indicators) == 0:
        return jsonify({
            "status": "error",
            "message": "indicators must be a non-empty list of strings.",
        }), 400

    if len(raw_bars) > 2000:
        return jsonify({
            "status": "error",
            "message": "Maximum 2000 bars per request.",
        }), 400

    # Validate and unpack bars
    try:
        # opens is validated for presence but not needed for indicator calcs
        _ = [float(b["open"]) for b in raw_bars]
        highs   = np.array([float(b["high"])   for b in raw_bars], dtype=np.float64)
        lows    = np.array([float(b["low"])    for b in raw_bars], dtype=np.float64)
        closes  = np.array([float(b["close"])  for b in raw_bars], dtype=np.float64)
        volumes = np.array(
            [float(b.get("volume", 0) or 0) for b in raw_bars], dtype=np.float64
        )
        _ = [int(b["time"]) for b in raw_bars]  # validate time field exists
    except (KeyError, TypeError, ValueError) as exc:
        logger.debug("Invalid bar data in indicators/compute: %s", exc)
        return jsonify({
            "status": "error",
            "message": "Invalid bar data. Ensure each bar has numeric open/high/low/close and int time fields.",
        }), 400

    def _to_list(arr: "np.ndarray") -> list:
        """Convert numpy array to JSON-serialisable list (NaN -> None)."""
        return [None if math.isnan(v) else float(v) for v in arr]

    def _parse_period(name: str, default: int) -> int:
        parts = name.rsplit("_", 1)
        if len(parts) == 2:
            try:
                return int(parts[1])
            except ValueError:
                pass
        return default

    result: dict[str, object] = {}

    for ind_name in raw_indicators:
        if not isinstance(ind_name, str):
            result[str(ind_name)] = {"error": "indicator name must be a string"}
            continue

        key = ind_name.lower().strip()
        try:
            # --- trend ---
            if key.startswith("ema"):
                period = _parse_period(key, 20)
                result[ind_name] = _to_list(ema(closes, period))

            elif key.startswith("sma"):
                period = _parse_period(key, 20)
                result[ind_name] = _to_list(sma(closes, period))

            elif key.startswith("dema"):
                period = _parse_period(key, 20)
                result[ind_name] = _to_list(dema(closes, period))

            elif key.startswith("wma"):
                period = _parse_period(key, 20)
                result[ind_name] = _to_list(wma(closes, period))

            elif key.startswith("hull"):
                period = _parse_period(key, 20)
                result[ind_name] = _to_list(hull(closes, period))

            elif key.startswith("vwap"):
                result[ind_name] = _to_list(
                    vwap(highs, lows, closes, volumes)
                )

            elif key.startswith("supertrend"):
                st_vals, st_dir = supertrend(highs, lows, closes)
                # Split into up (uptrend values) and down (downtrend values)
                up_arr = np.where(st_dir, st_vals, np.nan)
                down_arr = np.where(~st_dir, st_vals, np.nan)
                result[ind_name] = {
                    "up": _to_list(up_arr),
                    "down": _to_list(down_arr),
                }

            elif key.startswith("parabolic_sar"):
                result[ind_name] = _to_list(parabolic_sar(highs, lows))

            # --- momentum ---
            elif key.startswith("rsi"):
                period = _parse_period(key, 14)
                result[ind_name] = _to_list(rsi(closes, period))

            elif key == "macd":
                m_line, m_signal, m_hist = macd(closes)
                result[ind_name] = {
                    "line": _to_list(m_line),
                    "signal": _to_list(m_signal),
                    "histogram": _to_list(m_hist),
                }

            elif key.startswith("williams_r"):
                period = _parse_period(key, 14)
                result[ind_name] = _to_list(williams_r(highs, lows, closes, period))

            elif key.startswith("cci"):
                period = _parse_period(key, 20)
                result[ind_name] = _to_list(cci(highs, lows, closes, period))

            # --- volatility ---
            elif key.startswith("bollinger_bands"):
                period = _parse_period(key, 20)
                upper, middle, lower = bollinger_bands(closes, period)
                result[ind_name] = {
                    "upper": _to_list(upper),
                    "middle": _to_list(middle),
                    "lower": _to_list(lower),
                }

            elif key.startswith("atr"):
                period = _parse_period(key, 14)
                result[ind_name] = _to_list(atr(highs, lows, closes, period))

            elif key.startswith("keltner_channels"):
                period = _parse_period(key, 20)
                upper, middle, lower = keltner_channels(
                    highs, lows, closes, ema_period=period
                )
                result[ind_name] = {
                    "upper": _to_list(upper),
                    "middle": _to_list(middle),
                    "lower": _to_list(lower),
                }

            # --- volume ---
            elif key == "obv":
                result[ind_name] = _to_list(obv(closes, volumes))

            elif key.startswith("vwma"):
                period = _parse_period(key, 20)
                result[ind_name] = _to_list(vwma(closes, volumes, period))

            else:
                result[ind_name] = {"error": f"unknown indicator: {ind_name!r}"}

        except Exception as exc:  # noqa: BLE001
            logger.warning("Indicator %r error: %s", ind_name, exc)
            result[ind_name] = {"error": str(exc)}

    return jsonify({"status": "success", "data": result}), 200


# ---------------------------------------------------------------------------
# Pine Script → Python compilation endpoint
# ---------------------------------------------------------------------------

# Banned identifiers that must never appear in Pine-converted code
_PINE_BANNED_NAMES = {
    "exec", "eval", "compile", "__import__", "open", "os", "sys",
    "subprocess", "shutil", "pathlib", "importlib", "pickle",
    "globals", "locals", "getattr", "setattr", "delattr",
    "__builtins__", "__class__", "__subclasses__",
}


@indicators_bp.route("/indicators/pine/compile", methods=["POST"])
def pine_compile() -> tuple[Any, int]:
    """Compile Pine Script text to Python indicator code.

    Request JSON:
        code (str): Pine Script source text.

    Returns:
        JSON with ``status`` and ``data`` containing:
        - ``python_code`` (str): Converted Python code.
        - ``imports`` (list[str]): Required indicator imports.
        - ``warnings`` (list[str]): Non-fatal conversion notes.
        - ``unsupported`` (list[str]): Unrecognised Pine functions.
        - ``supported_functions`` (list[str]): All supported function names.

        Or ``status: "error"`` with ``message`` on failure.
    """
    import ast  # noqa: PLC0415

    from flinttrade_indicators.pine_converter import (  # noqa: PLC0415
        PineConverter,
    )

    body = request.get_json(silent=True) or {}
    code = body.get("code")

    if not isinstance(code, str) or not code.strip():
        return jsonify({
            "status": "error",
            "message": "code must be a non-empty string.",
        }), 400

    # Length guard — reject scripts that are unreasonably large
    if len(code) > 50_000:
        return jsonify({
            "status": "error",
            "message": "Script too large. Maximum 50,000 characters.",
        }), 400

    try:
        converter = PineConverter()
        result = converter.convert(code)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Pine converter error: %s", exc)
        return jsonify({
            "status": "error",
            "message": f"Conversion failed: {exc}",
        }), 400

    # AST-based safety validation — ensure the generated Python does not
    # contain dangerous constructs (imports of os/sys, exec, eval, etc.)
    safety_errors: list[str] = []
    try:
        tree = ast.parse(result.python_code)
        for node in ast.walk(tree):
            # Check for banned function calls
            if isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Name) and func.id in _PINE_BANNED_NAMES:
                    safety_errors.append(
                        f"Unsafe function call: {func.id}()"
                    )
                elif (
                    isinstance(func, ast.Attribute)
                    and func.attr in _PINE_BANNED_NAMES
                ):
                    safety_errors.append(
                        f"Unsafe method call: .{func.attr}()"
                    )
            # Check for banned name references
            if isinstance(node, ast.Name) and node.id in _PINE_BANNED_NAMES:
                safety_errors.append(f"Unsafe identifier: {node.id}")
    except SyntaxError:
        # If the converted code doesn't parse as Python, that's OK —
        # it may contain comments or partial conversions.
        pass

    if safety_errors:
        return jsonify({
            "status": "error",
            "message": "Generated code contains unsafe constructs.",
            "data": {"safety_errors": safety_errors},
        }), 400

    return jsonify({
        "status": "success",
        "data": {
            "python_code": result.python_code,
            "imports": result.imports,
            "warnings": result.warnings,
            "unsupported": result.unsupported,
            "supported_functions": converter.get_supported_functions(),
        },
    }), 200
