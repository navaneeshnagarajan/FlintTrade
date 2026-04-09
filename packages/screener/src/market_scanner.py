"""Declarative market scanner engine.

Provides a condition-based scanner that evaluates a set of named indicator
conditions against OHLCV data and returns matching symbols with a composite
score.  Conditions are expressed as :class:`ScanCondition` instances; a
collection of conditions plus a universe of symbols forms a
:class:`ScanConfig`.

Contrast with ``scanner.py`` (code-execution based, fluxscan pattern): this
module uses typed, serialisable Pydantic models that can be stored, transmitted
as JSON, and edited in the UI without writing Python code.

Supported indicators
--------------------
- ``rsi``             — Relative Strength Index (14-period default)
- ``macd_crossover``  — MACD line crosses signal line
- ``volume_spike``    — Current volume > N × 20-bar average
- ``ema_cross``       — Fast EMA crosses slow EMA (default 20/50)
- ``price_breakout``  — New N-day high (above) or low (below)
- ``bb_squeeze``      — Bollinger Band width below threshold
- ``gap_up``          — Open > prev close by N %
- ``gap_down``        — Open < prev close by N %
- ``atr_expansion``   — ATR > N × 20-bar average ATR
- ``near_support``    — Price within N % of highest-PE-OI strike
- ``near_resistance`` — Price within N % of highest-CE-OI strike

Usage::

    from packages.screener.src.market_scanner import (
        MarketScanner, ScanConfig, ScanCondition, PREBUILT_SCANS,
    )

    scanner = MarketScanner()
    results = scanner.scan(PREBUILT_SCANS["rsi_oversold"], data_fetcher=my_fetch)
    for r in results:
        print(r.symbol, r.score, r.matched_conditions)
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Callable

import numpy as np
from pydantic import BaseModel, Field, model_validator

logger = logging.getLogger("flinttrade.screener.market_scanner")

# ---------------------------------------------------------------------------
# Universe definitions
# ---------------------------------------------------------------------------

_NIFTY50_SYMBOLS: list[str] = [
    "RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK",
    "BHARTIARTL", "SBIN", "ITC", "HINDUNILVR", "LT",
    "BAJFINANCE", "KOTAKBANK", "MARUTI", "HCLTECH", "SUNPHARMA",
    "TITAN", "TATAMOTORS", "AXISBANK", "ADANIENT", "NTPC",
    "ONGC", "WIPRO", "POWERGRID", "TATASTEEL", "COALINDIA",
    "DRREDDY", "NESTLEIND", "ULTRACEMCO", "JSWSTEEL", "TECHM",
    "BAJAJFINSV", "DIVISLAB", "CIPLA", "BPCL", "HEROMOTOCO",
    "EICHERMOT", "TATACONSUM", "APOLLOHOSP", "BRITANNIA", "GRASIM",
    "HINDALCO", "INDUSINDBK", "M&M", "SBILIFE", "BAJAJ-AUTO",
    "HDFCLIFE", "SHREECEM", "ADANIPORTS", "UPL", "VEDL",
]

_NIFTYBANK_SYMBOLS: list[str] = [
    "HDFCBANK", "ICICIBANK", "KOTAKBANK", "SBIN", "AXISBANK",
    "INDUSINDBK", "BANDHANBNK", "IDFCFIRSTB", "FEDERALBNK", "AUBANK",
    "PNB", "BANKBARODA",
]

_NIFTY200_SYMBOLS: list[str] = _NIFTY50_SYMBOLS + [
    "ABB", "ACC", "ADANIGREEN", "ADANITRANS", "AIAENG",
    "ALKEM", "AMBUJACEM", "APLLTD", "ASTRAL", "ATUL",
    "AUROBINDO", "AUROPHARMA", "BALKRISIND", "BATAINDIA", "BERGERPAINTS",
    "BIOCON", "BOSCHLTD", "CANBK", "CHOLAFIN", "COLPAL",
    "CONCOR", "CROMPTON", "DALBHARAT", "DEEPAKNTR", "DELTACORP",
    "DMART", "ELGIEQUIP", "EMAMILTD", "ESCORTS", "FLUOROCHEM",
    "FORTIS", "GAIL", "GLENMARK", "GODREJCP", "GODREJPROP",
    "HAVELLS", "IEX", "INDHOTEL", "INDUSTOWER", "IRCTC",
    "JUBLFOOD", "LAURUSLABS", "LICHSGFIN", "LUPIN", "MANAPPURAM",
    "MARICO", "MCDOWELL-N", "METROPOLIS", "MFSL", "MINDTREE",
    "MPHASIS", "MRF", "MUTHOOTFIN", "NMDC", "OFSS",
    "PAGEIND", "PERSISTENT", "PETRONET", "PIDILITIND", "PIIND",
    "POLYCAB", "RBLBANK", "SAIL", "SBICARD", "SIEMENS",
    "SRF", "STAR", "SUNDARMFIN", "SUPREMEIND", "SYNGENE",
    "TORNTPHARM", "TRENT", "TVSMOTOR", "VOLTAS", "WHIRLPOOL",
    "YESBANK", "ZOMATO", "NYKAA", "PAYTM", "POLICYBZR",
    "DELHIVERY", "CAMPUS", "HARIOMTILE", "LATENTVIEW", "MAPMYINDIA",
    "MEDPLUS", "METRO", "NUVAMA", "RVNL", "SJVN",
    "GPIL", "GESHIP", "ITI", "NBCC", "RITES",
    "RAILVIKAS", "IRFC", "HUDCO", "RECLTD", "PFC",
    "NHPC", "NLCINDIA", "CPCL", "MRPL", "CHENNPETRO",
    "IPCALAB", "TORNTPOWER", "TATAPOWER", "JSL", "HINDZINC",
    "NATIONALUM", "HINDCOPPER", "MOIL", "GMRINFRA", "AARTIIND",
    "BASF", "BAYERCROP", "CLEAN", "COROMANDEL", "DHARMASHIP",
    "FINPIPE", "FINEORG", "GHCL", "GNFC", "GSFC",
    "IDFCFIRSTB", "IL&FSTRANS", "INDIAMART", "INDIGRID", "INKIA",
    "IOB", "IOBL", "JBCHEPHARM", "JKPAPER", "JSWENERGY",
    "KAJARIACER", "KPIT", "KPRMILL", "LALPATHLAB", "LINDEINDIA",
    "LUXIND", "MAHINDCIE", "MAITHANALL", "MAZDOCK", "MIDHANI",
]

_ALL_FNO_SYMBOLS: list[str] = list({*_NIFTY200_SYMBOLS, *_NIFTYBANK_SYMBOLS})

_UNIVERSES: dict[str, list[str]] = {
    "nifty50": _NIFTY50_SYMBOLS,
    "niftybank": _NIFTYBANK_SYMBOLS,
    "nifty200": _NIFTY200_SYMBOLS,
    "all_fno": _ALL_FNO_SYMBOLS,
}

# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

_VALID_INDICATORS = frozenset({
    "rsi", "macd_crossover", "volume_spike", "ema_cross",
    "price_breakout", "bb_squeeze", "gap_up", "gap_down",
    "atr_expansion", "near_support", "near_resistance",
})

_VALID_OPERATORS = frozenset({
    "above", "below", "crosses_above", "crosses_below", "between",
})


class ScanCondition(BaseModel):
    """A single named condition for a scan.

    Attributes:
        indicator: Indicator key (e.g. "rsi", "volume_spike").
        operator:  Comparison operator ("above", "below", "crosses_above",
                   "crosses_below", "between").
        value:     Threshold value, or a (low, high) tuple for "between".
        params:    Optional extra parameters forwarded to the indicator
                   calculator (e.g. ``{"period": 14}`` for RSI).
    """

    indicator: str
    operator: str
    value: float | tuple[float, float]
    params: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_fields(self) -> "ScanCondition":
        if self.indicator not in _VALID_INDICATORS:
            raise ValueError(
                f"Unknown indicator '{self.indicator}'. "
                f"Valid indicators: {sorted(_VALID_INDICATORS)}"
            )
        if self.operator not in _VALID_OPERATORS:
            raise ValueError(
                f"Unknown operator '{self.operator}'. "
                f"Valid operators: {sorted(_VALID_OPERATORS)}"
            )
        if self.operator == "between":
            if not (
                isinstance(self.value, (tuple, list))
                and len(self.value) == 2
            ):
                raise ValueError(
                    "Operator 'between' requires value to be a (low, high) tuple."
                )
        return self

    @property
    def label(self) -> str:
        """Human-readable condition label.

        Returns:
            Descriptive string, e.g. "rsi below 30".
        """
        if self.operator == "between":
            lo, hi = self.value  # type: ignore[misc]
            return f"{self.indicator} between {lo} and {hi}"
        return f"{self.indicator} {self.operator} {self.value}"

    model_config = {"arbitrary_types_allowed": True}


class ScanConfig(BaseModel):
    """Configuration for a single market scan.

    Attributes:
        name:            Display name shown in the UI.
        conditions:      List of conditions that must ALL match (AND logic).
        universe:        Named universe or "custom".
        custom_symbols:  Symbols to scan when universe == "custom".
        timeframe:       Candle timeframe passed to the data fetcher.
    """

    name: str
    conditions: list[ScanCondition]
    universe: str = "nifty50"
    custom_symbols: list[str] = Field(default_factory=list)
    timeframe: str = "1D"

    def get_symbols(self) -> list[str]:
        """Resolve the universe to a concrete list of symbols.

        Returns:
            List of exchange symbols to scan.

        Raises:
            ValueError: If universe is "custom" and no custom_symbols provided.
        """
        if self.universe == "custom":
            if not self.custom_symbols:
                raise ValueError("Universe is 'custom' but custom_symbols is empty.")
            return list(self.custom_symbols)
        return list(_UNIVERSES.get(self.universe, _NIFTY50_SYMBOLS))


class ScanResult(BaseModel):
    """Result for a single symbol that matched a scan.

    Attributes:
        symbol:             NSE/BSE symbol string.
        exchange:           Exchange code (e.g. "NSE").
        ltp:                Last traded price at scan time.
        change_pct:         Day change percentage.
        matched_conditions: Labels of conditions that matched.
        scan_time:          UTC timestamp of the scan.
        score:              Composite match strength in [0, 1].
    """

    symbol: str
    exchange: str
    ltp: float
    change_pct: float
    matched_conditions: list[str]
    scan_time: datetime
    score: float = Field(ge=0.0, le=1.0)

    model_config = {"arbitrary_types_allowed": True}


# ---------------------------------------------------------------------------
# Indicator calculators
# ---------------------------------------------------------------------------


def _rsi(closes: np.ndarray, period: int = 14) -> float:
    """Calculate RSI for the last bar from a close-price array.

    Args:
        closes: 1-D array of close prices, oldest first.
        period: RSI period (default 14).

    Returns:
        RSI value in [0, 100], or 50.0 if insufficient data.
    """
    if len(closes) < period + 1:
        return 50.0
    deltas = np.diff(closes[-(period + 1):])
    gains = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)
    avg_gain = float(np.mean(gains))
    avg_loss = float(np.mean(losses))
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def _ema(values: np.ndarray, period: int) -> np.ndarray:
    """Exponential moving average array (same length as input).

    Args:
        values: 1-D price array, oldest first.
        period: EMA period.

    Returns:
        EMA array; first ``period - 1`` values are NaN.
    """
    result = np.full_like(values, np.nan, dtype=float)
    if len(values) < period:
        return result
    k = 2.0 / (period + 1)
    result[period - 1] = float(np.mean(values[:period]))
    for i in range(period, len(values)):
        result[i] = values[i] * k + result[i - 1] * (1.0 - k)
    return result


def _macd(closes: np.ndarray, fast: int = 12, slow: int = 26, signal: int = 9) -> tuple[float, float, float, float]:
    """Calculate MACD line and signal line (last two bars).

    Args:
        closes: Close price array, oldest first.
        fast:   Fast EMA period (default 12).
        slow:   Slow EMA period (default 26).
        signal: Signal EMA period (default 9).

    Returns:
        Tuple of (macd_now, signal_now, macd_prev, signal_prev).
        Returns (0, 0, 0, 0) on insufficient data.
    """
    if len(closes) < slow + signal:
        return 0.0, 0.0, 0.0, 0.0
    fast_ema = _ema(closes, fast)
    slow_ema = _ema(closes, slow)
    macd_line = fast_ema - slow_ema
    valid = macd_line[~np.isnan(macd_line)]
    if len(valid) < signal:
        return 0.0, 0.0, 0.0, 0.0
    # Re-build EMA on valid macd values only for signal line
    signal_line = _ema(valid, signal)
    if np.isnan(signal_line[-1]) or len(signal_line) < 2:
        return 0.0, 0.0, 0.0, 0.0
    return float(valid[-1]), float(signal_line[-1]), float(valid[-2]), float(signal_line[-2])


def _atr(highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, period: int = 14) -> float:
    """Calculate Average True Range for the most recent bar.

    Args:
        highs:  High price array.
        lows:   Low price array.
        closes: Close price array.
        period: ATR period (default 14).

    Returns:
        Current ATR value, or 0.0 on insufficient data.
    """
    if len(closes) < period + 1:
        return 0.0
    tr = np.maximum(
        highs[1:] - lows[1:],
        np.maximum(
            np.abs(highs[1:] - closes[:-1]),
            np.abs(lows[1:] - closes[:-1]),
        ),
    )
    return float(np.mean(tr[-period:]))


def _bollinger_width(closes: np.ndarray, period: int = 20, num_std: float = 2.0) -> float:
    """Bollinger Band width as a fraction of the middle band.

    Args:
        closes:  Close price array.
        period:  Bollinger period (default 20).
        num_std: Standard deviation multiplier (default 2).

    Returns:
        Band width (upper - lower) / middle.  0.0 on insufficient data.
    """
    if len(closes) < period:
        return 0.0
    window = closes[-period:]
    mid = float(np.mean(window))
    if mid == 0:
        return 0.0
    std = float(np.std(window, ddof=1))
    return (2.0 * num_std * std) / mid


# ---------------------------------------------------------------------------
# Condition evaluator
# ---------------------------------------------------------------------------


def _evaluate_single(
    condition: ScanCondition,
    ohlcv: list[dict[str, Any]],
) -> bool:
    """Evaluate one condition against OHLCV history.

    Args:
        condition: The condition to evaluate.
        ohlcv:     List of OHLCV dicts ordered oldest-to-newest.  Each dict
                   must have keys "open", "high", "low", "close", "volume".

    Returns:
        True if the condition is satisfied for the most recent bar.
    """
    if not ohlcv:
        return False

    closes = np.array([float(c["close"]) for c in ohlcv], dtype=float)
    highs = np.array([float(c["high"]) for c in ohlcv], dtype=float)
    lows = np.array([float(c["low"]) for c in ohlcv], dtype=float)
    opens = np.array([float(c["open"]) for c in ohlcv], dtype=float)
    volumes = np.array([float(c.get("volume", 0)) for c in ohlcv], dtype=float)

    ind = condition.indicator
    op = condition.operator
    val = condition.value
    p = condition.params  # extra params

    # ---- RSI ----
    if ind == "rsi":
        period = int(p.get("period", 14))
        current = _rsi(closes, period=period)
        if op == "above":
            return current > float(val)  # type: ignore[arg-type]
        if op == "below":
            return current < float(val)  # type: ignore[arg-type]
        if op == "between":
            lo, hi = val  # type: ignore[misc]
            return float(lo) <= current <= float(hi)

    # ---- MACD crossover ----
    elif ind == "macd_crossover":
        fast = int(p.get("fast", 12))
        slow = int(p.get("slow", 26))
        signal = int(p.get("signal", 9))
        m_now, s_now, m_prev, s_prev = _macd(closes, fast, slow, signal)
        if op == "crosses_above":
            return m_prev <= s_prev and m_now > s_now
        if op == "crosses_below":
            return m_prev >= s_prev and m_now < s_now
        if op == "above":
            return m_now > s_now
        if op == "below":
            return m_now < s_now

    # ---- Volume spike ----
    elif ind == "volume_spike":
        avg_period = int(p.get("avg_period", 20))
        if len(volumes) < avg_period + 1:
            return False
        avg_vol = float(np.mean(volumes[-(avg_period + 1):-1]))
        if avg_vol == 0:
            return False
        multiplier = volumes[-1] / avg_vol
        if op == "above":
            return multiplier > float(val)  # type: ignore[arg-type]
        if op == "below":
            return multiplier < float(val)  # type: ignore[arg-type]
        if op == "between":
            lo, hi = val  # type: ignore[misc]
            return float(lo) <= multiplier <= float(hi)

    # ---- EMA cross ----
    elif ind == "ema_cross":
        fast_p = int(p.get("fast", 20))
        slow_p = int(p.get("slow", 50))
        fast_arr = _ema(closes, fast_p)
        slow_arr = _ema(closes, slow_p)
        if np.isnan(fast_arr[-1]) or np.isnan(slow_arr[-1]):
            return False
        if len(fast_arr) < 2 or np.isnan(fast_arr[-2]) or np.isnan(slow_arr[-2]):
            return False
        if op == "crosses_above":
            return fast_arr[-2] <= slow_arr[-2] and fast_arr[-1] > slow_arr[-1]
        if op == "crosses_below":
            return fast_arr[-2] >= slow_arr[-2] and fast_arr[-1] < slow_arr[-1]
        if op == "above":
            return fast_arr[-1] > slow_arr[-1]
        if op == "below":
            return fast_arr[-1] < slow_arr[-1]

    # ---- Price breakout ----
    elif ind == "price_breakout":
        n_days = int(p.get("days", 52))
        if len(closes) < n_days + 1:
            return False
        window = closes[-(n_days + 1):-1]
        current_close = closes[-1]
        if op == "above":
            return current_close > float(np.max(window))
        if op == "below":
            return current_close < float(np.min(window))

    # ---- Bollinger squeeze ----
    elif ind == "bb_squeeze":
        period = int(p.get("period", 20))
        squeeze_window = int(p.get("squeeze_window", 120))
        width_now = _bollinger_width(closes, period)
        if len(closes) < squeeze_window:
            return False
        widths_hist = np.array([
            _bollinger_width(closes[:i], period)
            for i in range(max(period, len(closes) - squeeze_window), len(closes))
        ])
        widths_hist = widths_hist[widths_hist > 0]
        if len(widths_hist) == 0:
            return False
        min_width = float(np.min(widths_hist))
        threshold = float(val) if not isinstance(val, (tuple, list)) else min_width * 1.05
        if op in ("below", "crosses_below"):
            return width_now <= threshold
        if op in ("above", "crosses_above"):
            return width_now >= threshold

    # ---- Gap up ----
    elif ind == "gap_up":
        if len(closes) < 2:
            return False
        prev_close = closes[-2]
        current_open = opens[-1]
        if prev_close == 0:
            return False
        gap_pct = ((current_open - prev_close) / prev_close) * 100.0
        if op == "above":
            return gap_pct > float(val)  # type: ignore[arg-type]
        if op == "between":
            lo, hi = val  # type: ignore[misc]
            return float(lo) <= gap_pct <= float(hi)

    # ---- Gap down ----
    elif ind == "gap_down":
        if len(closes) < 2:
            return False
        prev_close = closes[-2]
        current_open = opens[-1]
        if prev_close == 0:
            return False
        gap_pct = ((prev_close - current_open) / prev_close) * 100.0
        if op == "above":
            return gap_pct > float(val)  # type: ignore[arg-type]
        if op == "between":
            lo, hi = val  # type: ignore[misc]
            return float(lo) <= gap_pct <= float(hi)

    # ---- ATR expansion ----
    elif ind == "atr_expansion":
        period = int(p.get("period", 14))
        avg_period = int(p.get("avg_period", 20))
        if len(closes) < period + avg_period + 1:
            return False
        current_atr = _atr(highs, lows, closes, period)
        # ATR values over past avg_period bars (shift by 1 each bar)
        atr_history = np.array([
            _atr(highs[:i], lows[:i], closes[:i], period)
            for i in range(
                max(period + 1, len(closes) - avg_period),
                len(closes),
            )
        ])
        atr_history = atr_history[atr_history > 0]
        if len(atr_history) == 0:
            return False
        avg_atr = float(np.mean(atr_history))
        if avg_atr == 0:
            return False
        ratio = current_atr / avg_atr
        if op == "above":
            return ratio > float(val)  # type: ignore[arg-type]
        if op == "below":
            return ratio < float(val)  # type: ignore[arg-type]

    # ---- Near support / resistance ----
    elif ind in ("near_support", "near_resistance"):
        # value is interpreted as the level price; params["pct"] is the band
        level = float(val) if not isinstance(val, (tuple, list)) else float(val[0])  # type: ignore[index]
        pct = float(p.get("pct", 1.0))
        current_close = closes[-1]
        if level == 0:
            return False
        distance_pct = abs(current_close - level) / level * 100.0
        if op in ("below", "above"):
            return distance_pct <= pct
        if op == "between":
            lo_pct, hi_pct = val  # type: ignore[misc]
            return float(lo_pct) <= distance_pct <= float(hi_pct)

    return False


# ---------------------------------------------------------------------------
# MarketScanner
# ---------------------------------------------------------------------------


class MarketScanner:
    """Declarative market scanner engine.

    Runs a :class:`ScanConfig` across a universe of symbols by fetching OHLCV
    data for each symbol via a caller-supplied ``data_fetcher`` callable and
    evaluating all conditions.

    All conditions in a config use AND logic — a symbol must satisfy every
    condition to appear in results.  The composite score is the fraction of
    conditions matched (so a symbol that matches 3 of 3 conditions scores 1.0).

    Args:
        exchange: Default exchange for all symbols (default "NSE").
    """

    def __init__(self, exchange: str = "NSE") -> None:
        self._exchange = exchange
        self._predefined_universes: dict[str, list[str]] = _UNIVERSES

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def scan(
        self,
        config: ScanConfig,
        data_fetcher: Callable[[str, str, str], list[dict[str, Any]]],
    ) -> list[ScanResult]:
        """Run a scan across the configured universe.

        Args:
            config:       :class:`ScanConfig` defining conditions and universe.
            data_fetcher: Callable with signature
                          ``(symbol: str, exchange: str, timeframe: str) → list[dict]``
                          where each dict is an OHLCV bar
                          ``{"open": f, "high": f, "low": f, "close": f, "volume": i}``.
                          May return an empty list on error; that symbol is skipped.

        Returns:
            List of :class:`ScanResult` objects for matching symbols, sorted by
            score descending then symbol ascending.
        """
        symbols = config.get_symbols()
        results: list[ScanResult] = []
        now = datetime.now(timezone.utc)

        for symbol in symbols:
            try:
                ohlcv = data_fetcher(symbol, self._exchange, config.timeframe)
            except Exception as exc:
                logger.debug("data_fetcher error for %s: %s", symbol, exc)
                continue

            if not ohlcv:
                continue

            matched, matched_names, score = self.evaluate_conditions(ohlcv, config.conditions)
            if not matched:
                continue

            ltp = float(ohlcv[-1]["close"])
            prev_close = float(ohlcv[-2]["close"]) if len(ohlcv) >= 2 else ltp
            change_pct = ((ltp - prev_close) / prev_close * 100.0) if prev_close != 0 else 0.0

            results.append(ScanResult(
                symbol=symbol,
                exchange=self._exchange,
                ltp=round(ltp, 2),
                change_pct=round(change_pct, 2),
                matched_conditions=matched_names,
                scan_time=now,
                score=round(score, 4),
            ))

        results.sort(key=lambda r: (-r.score, r.symbol))
        logger.info(
            "Scan '%s' completed: %d/%d symbols matched",
            config.name, len(results), len(symbols),
        )
        return results

    def evaluate_conditions(
        self,
        ohlcv: list[dict[str, Any]],
        conditions: list[ScanCondition],
    ) -> tuple[bool, list[str], float]:
        """Evaluate all conditions against OHLCV history for a single symbol.

        Args:
            ohlcv:      OHLCV list, oldest bar first.
            conditions: List of conditions to evaluate.

        Returns:
            Tuple of:
            - ``matched`` (bool): True only if ALL conditions are satisfied.
            - ``matched_names`` (list[str]): Labels of satisfied conditions.
            - ``score`` (float): Fraction of conditions satisfied in [0, 1].
        """
        if not conditions:
            return False, [], 0.0

        matched_names: list[str] = []
        for cond in conditions:
            try:
                if _evaluate_single(cond, ohlcv):
                    matched_names.append(cond.label)
            except Exception as exc:
                logger.debug("Condition evaluation error (%s): %s", cond.label, exc)

        score = len(matched_names) / len(conditions)
        all_matched = len(matched_names) == len(conditions)
        return all_matched, matched_names, score


# ---------------------------------------------------------------------------
# Pre-built scans
# ---------------------------------------------------------------------------

PREBUILT_SCANS: dict[str, ScanConfig] = {
    "rsi_oversold": ScanConfig(
        name="RSI Oversold",
        conditions=[
            ScanCondition(indicator="rsi", operator="below", value=30.0),
        ],
        universe="nifty50",
    ),
    "rsi_overbought": ScanConfig(
        name="RSI Overbought",
        conditions=[
            ScanCondition(indicator="rsi", operator="above", value=70.0),
        ],
        universe="nifty50",
    ),
    "volume_breakout": ScanConfig(
        name="Volume Breakout",
        conditions=[
            ScanCondition(indicator="volume_spike", operator="above", value=2.0),
            ScanCondition(indicator="price_breakout", operator="above", value=0.0,
                          params={"days": 20}),
        ],
        universe="nifty50",
    ),
    "bullish_momentum": ScanConfig(
        name="Bullish Momentum",
        conditions=[
            ScanCondition(indicator="ema_cross", operator="above", value=0.0),
            ScanCondition(indicator="rsi", operator="above", value=50.0),
            ScanCondition(indicator="volume_spike", operator="above", value=1.5),
        ],
        universe="nifty50",
    ),
    "bearish_reversal": ScanConfig(
        name="Bearish Reversal",
        conditions=[
            ScanCondition(indicator="rsi", operator="above", value=65.0),
            ScanCondition(indicator="macd_crossover", operator="crosses_below", value=0.0),
        ],
        universe="nifty50",
    ),
    "pre_market_movers": ScanConfig(
        name="Pre-Market Movers",
        conditions=[
            ScanCondition(indicator="gap_up", operator="above", value=0.5),
            ScanCondition(indicator="volume_spike", operator="above", value=1.5),
        ],
        universe="nifty50",
    ),
    "volatility_expansion": ScanConfig(
        name="Volatility Expansion",
        conditions=[
            ScanCondition(indicator="atr_expansion", operator="above", value=1.5),
        ],
        universe="nifty50",
    ),
    "52_week_breakout": ScanConfig(
        name="52-Week Breakout",
        conditions=[
            ScanCondition(indicator="price_breakout", operator="above", value=0.0,
                          params={"days": 252}),
        ],
        universe="nifty50",
    ),
}
