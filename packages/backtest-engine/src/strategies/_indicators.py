"""Pure-Python indicator helpers for backtest strategy sub-modules.

All functions are dependency-free (no numpy, no TA-Lib) and work on
plain Python lists. These are the same implementations as in strategies.py
but made importable from within the strategies sub-package without
triggering circular imports.
"""

from __future__ import annotations


def ema(values: list[float], period: int) -> list[float]:
    """Exponential Moving Average.

    Args:
        values: Price series.
        period: EMA period.

    Returns:
        EMA series of the same length.
    """
    if not values or period <= 0:
        return []
    result: list[float] = []
    k = 2 / (period + 1)
    prev = values[0]
    for v in values:
        prev = v * k + prev * (1 - k)
        result.append(prev)
    return result


def sma(values: list[float], period: int) -> list[float]:
    """Simple Moving Average.

    Args:
        values: Price series.
        period: SMA period.

    Returns:
        SMA series; leading values are 0.0.
    """
    if len(values) < period:
        return [0.0] * len(values)
    result: list[float] = [0.0] * (period - 1)
    for i in range(period - 1, len(values)):
        result.append(sum(values[i - period + 1: i + 1]) / period)
    return result


def rsi(closes: list[float], period: int = 14) -> list[float]:
    """Relative Strength Index.

    Args:
        closes: Close price series.
        period: RSI period (default 14).

    Returns:
        RSI series; leading values are 50.0.
    """
    if len(closes) < period + 1:
        return [50.0] * len(closes)
    deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    gains = [max(0, d) for d in deltas]
    losses = [max(0, -d) for d in deltas]
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    result = [50.0] * (period + 1)
    for i in range(period, len(deltas)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        if avg_loss == 0:
            result.append(100.0)
        else:
            rs = avg_gain / avg_loss
            result.append(100 - 100 / (1 + rs))
    return result


def bollinger_bands(
    closes: list[float],
    period: int = 20,
    std_mult: float = 2.0,
) -> tuple[list[float], list[float], list[float]]:
    """Bollinger Bands.

    Args:
        closes: Close prices.
        period: Band period (default 20).
        std_mult: Standard deviation multiplier (default 2.0).

    Returns:
        Tuple of (upper, middle, lower) bands.
    """
    mid = sma(closes, period)
    upper: list[float] = []
    lower: list[float] = []
    for i in range(len(closes)):
        if i < period - 1:
            upper.append(0.0)
            lower.append(0.0)
            continue
        window = closes[i - period + 1: i + 1]
        m = sum(window) / period
        std = (sum((v - m) ** 2 for v in window) / period) ** 0.5
        upper.append(m + std_mult * std)
        lower.append(m - std_mult * std)
    return upper, mid, lower


def macd(
    closes: list[float],
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> tuple[list[float], list[float], list[float]]:
    """MACD — returns (macd_line, signal_line, histogram).

    Args:
        closes: Close prices.
        fast: Fast EMA period (default 12).
        slow: Slow EMA period (default 26).
        signal: Signal EMA period (default 9).

    Returns:
        Tuple of (macd_line, signal_line, histogram).
    """
    ema_fast = ema(closes, fast)
    ema_slow = ema(closes, slow)
    macd_line = [f - s for f, s in zip(ema_fast, ema_slow)]
    signal_line = ema(macd_line, signal)
    hist = [m - s for m, s in zip(macd_line, signal_line)]
    return macd_line, signal_line, hist


def supertrend(
    highs: list[float],
    lows: list[float],
    closes: list[float],
    period: int = 10,
    multiplier: float = 3.0,
) -> tuple[list[float], list[bool]]:
    """Supertrend indicator.

    Args:
        highs: High prices.
        lows: Low prices.
        closes: Close prices.
        period: ATR period (default 10).
        multiplier: ATR multiplier (default 3.0).

    Returns:
        Tuple of (supertrend_values, is_uptrend) lists.
    """
    n = len(closes)
    if n < period:
        return [0.0] * n, [True] * n

    tr: list[float] = [highs[0] - lows[0]]
    for i in range(1, n):
        tr.append(max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        ))
    atr = sma(tr, period)

    st: list[float] = [0.0] * n
    uptrend: list[bool] = [True] * n

    for i in range(period, n):
        basic_upper = (highs[i] + lows[i]) / 2 + multiplier * atr[i]
        basic_lower = (highs[i] + lows[i]) / 2 - multiplier * atr[i]

        if i == period:
            st[i] = basic_lower if closes[i] > basic_lower else basic_upper
            uptrend[i] = closes[i] > basic_lower
            continue

        if uptrend[i - 1]:
            st[i] = max(basic_lower, st[i - 1]) if closes[i] > st[i - 1] else basic_upper
            uptrend[i] = closes[i] > st[i]
        else:
            st[i] = min(basic_upper, st[i - 1]) if closes[i] < st[i - 1] else basic_lower
            uptrend[i] = closes[i] > st[i]

    return st, uptrend


def atr(
    highs: list[float],
    lows: list[float],
    closes: list[float],
    period: int = 14,
) -> list[float]:
    """Average True Range (ATR).

    Computes the Wilder-smoothed ATR using the standard True Range definition:

        TR = max(high - low, |high - prev_close|, |low - prev_close|)
        ATR[period] = SMA(TR, period)
        ATR[i]      = (ATR[i-1] * (period - 1) + TR[i]) / period  (Wilder)

    The first ``period`` values use SMA seeding. Values before ``period``
    bars are returned as 0.0 to maintain list length parity.

    Args:
        highs: High price series.
        lows: Low price series.
        closes: Close price series.
        period: Smoothing period (default 14).

    Returns:
        ATR series of the same length as the inputs. Leading values are 0.0.
    """
    n = len(closes)
    if n == 0 or period <= 0:
        return []
    if n < 2:
        return [0.0] * n

    # True Range series (length == n, index 0 uses high - low only)
    tr: list[float] = [highs[0] - lows[0]]
    for i in range(1, n):
        tr.append(max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        ))

    result: list[float] = [0.0] * n

    if n < period:
        return result

    # Seed: SMA of first `period` TR values
    seed = sum(tr[:period]) / period
    result[period - 1] = seed

    # Wilder smoothing for subsequent bars
    prev_atr = seed
    for i in range(period, n):
        prev_atr = (prev_atr * (period - 1) + tr[i]) / period
        result[i] = prev_atr

    return result


def laguerre_rsi(closes: list[float], gamma: float = 0.5) -> list[float]:
    """Laguerre RSI — smooth RSI oscillator bounded in [0, 1].

    Applies a 4-pole Laguerre filter to derive an RSI-like momentum oscillator.
    The gamma parameter controls smoothing: higher gamma = more smoothing.

    Args:
        closes: Close price series.
        gamma: Damping factor in (0, 1). Default 0.5.

    Returns:
        Laguerre RSI series in range [0, 1]; same length as closes.
        Leading values where the filter has not yet seeded are 0.5.
    """
    n = len(closes)
    if n < 2:
        return [0.5] * n

    result: list[float] = []
    l0_prev = l1_prev = l2_prev = l3_prev = closes[0]

    for price in closes:
        l0 = (1 - gamma) * price + gamma * l0_prev
        l1 = -gamma * l0 + l0_prev + gamma * l1_prev
        l2 = -gamma * l1 + l1_prev + gamma * l2_prev
        l3 = -gamma * l2 + l2_prev + gamma * l3_prev

        cu = 0.0
        cd = 0.0
        if l0 >= l1:
            cu += l0 - l1
        else:
            cd += l1 - l0
        if l1 >= l2:
            cu += l1 - l2
        else:
            cd += l2 - l1
        if l2 >= l3:
            cu += l2 - l3
        else:
            cd += l3 - l2

        denom = cu + cd
        result.append(cu / denom if denom != 0 else 0.5)

        l0_prev, l1_prev, l2_prev, l3_prev = l0, l1, l2, l3

    return result


def pivot_points(
    highs: list[float],
    lows: list[float],
    closes: list[float],
) -> tuple[float, float, float, float, float]:
    """Classic floor-trader pivot points (single period).

    Computes pivot levels from a window of H/L/C values (usually 1 bar, but
    any window is accepted — the max/min/last are used).

        P  = (H + L + C) / 3
        R1 = 2 * P - L
        S1 = 2 * P - H
        R2 = P + (H - L)
        S2 = P - (H - L)

    Args:
        highs: High prices for the pivot period.
        lows: Low prices for the pivot period.
        closes: Close prices for the pivot period.

    Returns:
        Tuple of (P, R1, S1, R2, S2).
    """
    if not highs or not lows or not closes:
        return 0.0, 0.0, 0.0, 0.0, 0.0
    h = max(highs)
    lo = min(lows)
    c = closes[-1]
    p = (h + lo + c) / 3
    r1 = 2 * p - lo
    s1 = 2 * p - h
    r2 = p + (h - lo)
    s2 = p - (h - lo)
    return p, r1, s1, r2, s2


def heikin_ashi(
    opens: list[float],
    highs: list[float],
    lows: list[float],
    closes: list[float],
) -> tuple[list[float], list[float], list[float], list[float]]:
    """Heikin-Ashi candle conversion.

    Transforms standard OHLCV candles into Heikin-Ashi candles which
    smooth price action and make trends easier to identify.

        HA_close = (O + H + L + C) / 4
        HA_open  = (prev_HA_open + prev_HA_close) / 2   (seed: (O[0] + C[0]) / 2)
        HA_high  = max(H, HA_open, HA_close)
        HA_low   = min(L, HA_open, HA_close)

    Args:
        opens: Open prices.
        highs: High prices.
        lows: Low prices.
        closes: Close prices.

    Returns:
        Tuple of (ha_opens, ha_highs, ha_lows, ha_closes) lists.
    """
    n = len(closes)
    if n == 0:
        return [], [], [], []

    ha_opens: list[float] = [0.0] * n
    ha_highs: list[float] = [0.0] * n
    ha_lows: list[float] = [0.0] * n
    ha_closes: list[float] = [0.0] * n

    # Seed first bar
    ha_closes[0] = (opens[0] + highs[0] + lows[0] + closes[0]) / 4
    ha_opens[0] = (opens[0] + closes[0]) / 2
    ha_highs[0] = max(highs[0], ha_opens[0], ha_closes[0])
    ha_lows[0] = min(lows[0], ha_opens[0], ha_closes[0])

    for i in range(1, n):
        ha_closes[i] = (opens[i] + highs[i] + lows[i] + closes[i]) / 4
        ha_opens[i] = (ha_opens[i - 1] + ha_closes[i - 1]) / 2
        ha_highs[i] = max(highs[i], ha_opens[i], ha_closes[i])
        ha_lows[i] = min(lows[i], ha_opens[i], ha_closes[i])

    return ha_opens, ha_highs, ha_lows, ha_closes


__all__ = [
    "ema",
    "sma",
    "rsi",
    "bollinger_bands",
    "macd",
    "supertrend",
    "atr",
    "laguerre_rsi",
    "pivot_points",
    "heikin_ashi",
]
