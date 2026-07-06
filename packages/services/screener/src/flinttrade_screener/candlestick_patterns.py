"""Candlestick pattern detection (W4).

Stateless detectors for the six candlestick patterns FlintTrade already
backtests, lifted from the geometric conditions in
``flinttrade_backtest.strategies.pattern_*`` into pure functions that scan a
series of OHLCV bars and return pattern markers (with an anchor index, the
bullish/bearish direction and a 0–1 strength). Unlike the backtest strategies
these carry no state, SMA trend filter or position management — they detect the
candle *shape* only, so the terminal can overlay markers on any chart.

Patterns:
  * Doji — small real body relative to range.
  * Hammer / Shooting Star — small body with one dominant wick.
  * Bullish / Bearish Engulfing — current body engulfs the prior body.
  * Morning / Evening Star — three-bar reversal with a small middle star.
  * Three White Soldiers / Three Black Crows — three strong same-direction bars.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

# Detection thresholds mirror the backtest strategy defaults so the overlay and
# the backtests agree on what counts as each pattern.
_DOJI_BODY_MAX = 0.10        # body/range to qualify as a Doji
_HAMMER_BODY_MAX = 0.35      # small-body ceiling for hammer/star
_HAMMER_WICK_MULT = 2.0      # dominant wick >= 2× body
_STAR_BODY_MIN = 0.60        # first/third star candle body/range floor
_STAR_MIDDLE_MAX = 0.30      # middle star candle body/range ceiling
_SOLDIER_BODY_MIN = 0.55     # each soldier/crow body/range floor
_SOLDIER_WICK_MAX = 0.20     # opposite-wick ceiling for soldiers/crows


@dataclass
class PatternMatch:
    """One detected candlestick pattern at a bar index."""

    index: int = 0
    time: str = ""
    pattern: str = ""       # doji | hammer | shooting_star | ...
    label: str = ""         # human-readable
    direction: str = "neutral"  # bullish | bearish | neutral
    strength: float = 0.0   # 0–1

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable dictionary."""
        return asdict(self)


@dataclass
class PatternScanResult:
    """All patterns detected across a bar series."""

    bar_count: int = 0
    matches: list[PatternMatch] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable dictionary."""
        return {
            "bar_count": self.bar_count,
            "matches": [m.to_dict() for m in self.matches],
        }


def _ohlc(bar: dict[str, Any]) -> tuple[float, float, float, float]:
    """Extract (open, high, low, close) as floats."""
    return (
        float(bar.get("open", 0) or 0),
        float(bar.get("high", 0) or 0),
        float(bar.get("low", 0) or 0),
        float(bar.get("close", 0) or 0),
    )


def _range(h: float, lo: float) -> float:
    return h - lo


def _body_ratio(o: float, c: float, h: float, lo: float) -> float:
    r = _range(h, lo)
    return abs(c - o) / r if r > 0 else 0.0


def _is_doji(o: float, h: float, lo: float, c: float) -> bool:
    r = _range(h, lo)
    return r > 0 and abs(c - o) / r <= _DOJI_BODY_MAX


def _hammer_kind(o: float, h: float, lo: float, c: float) -> str | None:
    """Return 'hammer', 'shooting_star', or None."""
    r = _range(h, lo)
    if r <= 0:
        return None
    body = abs(c - o)
    if body <= 0 or body / r > _HAMMER_BODY_MAX:
        return None
    upper_wick = h - max(o, c)
    lower_wick = min(o, c) - lo
    if lower_wick >= _HAMMER_WICK_MULT * body and upper_wick <= body:
        return "hammer"          # bullish
    if upper_wick >= _HAMMER_WICK_MULT * body and lower_wick <= body:
        return "shooting_star"   # bearish
    return None


def _engulfing_kind(prev: tuple[float, float, float, float], cur: tuple[float, float, float, float]) -> str | None:
    """Return 'bullish_engulfing', 'bearish_engulfing', or None."""
    po, _ph, _pl, pc = prev
    co, _ch, _cl, cc = cur
    cur_bullish = cc > co
    cur_bearish = cc < co
    prev_bearish = pc < po
    prev_bullish = pc > po
    if cur_bullish and prev_bearish and co <= pc and cc >= po:
        return "bullish_engulfing"
    if cur_bearish and prev_bullish and co >= pc and cc <= po:
        return "bearish_engulfing"
    return None


def _star_kind(
    b1: tuple[float, float, float, float],
    b2: tuple[float, float, float, float],
    b3: tuple[float, float, float, float],
) -> str | None:
    """Return 'morning_star', 'evening_star', or None."""
    o1, h1, l1, c1 = b1
    o2, h2, l2, c2 = b2
    o3, h3, l3, c3 = b3
    br1 = _body_ratio(o1, c1, h1, l1)
    br2 = _body_ratio(o2, c2, h2, l2)
    br3 = _body_ratio(o3, c3, h3, l3)
    if br1 < _STAR_BODY_MIN or br3 < _STAR_BODY_MIN or br2 > _STAR_MIDDLE_MAX:
        return None
    mid1 = (o1 + c1) / 2.0
    # Morning star: big bearish, gap-down small star, big bullish closing past midpoint.
    if c1 < o1 and c3 > o3 and c2 < c1 and c3 > mid1:
        return "morning_star"
    # Evening star: big bullish, gap-up small star, big bearish closing below midpoint.
    if c1 > o1 and c3 < o3 and c2 > c1 and c3 < mid1:
        return "evening_star"
    return None


def _soldiers_kind(
    b1: tuple[float, float, float, float],
    b2: tuple[float, float, float, float],
    b3: tuple[float, float, float, float],
) -> str | None:
    """Return 'three_white_soldiers', 'three_black_crows', or None."""
    def metrics(bar: tuple[float, float, float, float]) -> tuple[float, float, float]:
        o, h, lo, c = bar
        r = _range(h, lo)
        if r <= 0:
            return 0.0, 1.0, 1.0
        return abs(c - o) / r, (h - max(o, c)) / r, (min(o, c) - lo) / r

    bars = (b1, b2, b3)
    if any(metrics(b)[0] < _SOLDIER_BODY_MIN for b in bars):
        return None
    o1, _, _, c1 = b1
    o2, _, _, c2 = b2
    o3, _, _, c3 = b3
    bull = c1 > o1 and c2 > o2 and c3 > o3 and c3 > c2 > c1
    bear = c1 < o1 and c2 < o2 and c3 < o3 and c3 < c2 < c1
    if bull and all(metrics(b)[1] <= _SOLDIER_WICK_MAX for b in bars):
        return "three_white_soldiers"
    if bear and all(metrics(b)[2] <= _SOLDIER_WICK_MAX for b in bars):
        return "three_black_crows"
    return None


_LABELS: dict[str, tuple[str, str]] = {
    "doji": ("Doji", "neutral"),
    "hammer": ("Hammer", "bullish"),
    "shooting_star": ("Shooting Star", "bearish"),
    "bullish_engulfing": ("Bullish Engulfing", "bullish"),
    "bearish_engulfing": ("Bearish Engulfing", "bearish"),
    "morning_star": ("Morning Star", "bullish"),
    "evening_star": ("Evening Star", "bearish"),
    "three_white_soldiers": ("Three White Soldiers", "bullish"),
    "three_black_crows": ("Three Black Crows", "bearish"),
}


def detect_patterns(bars: list[dict[str, Any]]) -> PatternScanResult:
    """Scan a series of OHLCV bars for all six candlestick patterns.

    Args:
        bars: Ordered list of bars, each ``{open, high, low, close, time?}``.

    Returns:
        A :class:`PatternScanResult` with one :class:`PatternMatch` per detected
        pattern, anchored at the bar that completes it.
    """
    result = PatternScanResult(bar_count=len(bars))
    if not bars:
        return result

    def _emit(index: int, key: str, strength: float) -> None:
        label, direction = _LABELS[key]
        result.matches.append(PatternMatch(
            index=index,
            time=str(bars[index].get("time", "")),
            pattern=key,
            label=label,
            direction=direction,
            strength=round(max(0.0, min(1.0, strength)), 3),
        ))

    for i, bar in enumerate(bars):
        o, h, lo, c = _ohlc(bar)
        r = _range(h, lo)

        # Single-bar patterns.
        hk = _hammer_kind(o, h, lo, c)
        if hk is not None:
            dominant = (min(o, c) - lo) if hk == "hammer" else (h - max(o, c))
            strength = dominant / r if r > 0 else 0.0
            _emit(i, hk, strength)
        elif _is_doji(o, h, lo, c):
            # Weaker signal when the range itself is tiny.
            _emit(i, "doji", 1.0 - (abs(c - o) / r if r > 0 else 1.0))

        # Two-bar engulfing.
        if i >= 1:
            ek = _engulfing_kind(_ohlc(bars[i - 1]), (o, h, lo, c))
            if ek is not None:
                _emit(i, ek, _body_ratio(o, c, h, lo))

        # Three-bar patterns.
        if i >= 2:
            b1, b2, b3 = _ohlc(bars[i - 2]), _ohlc(bars[i - 1]), (o, h, lo, c)
            sk = _star_kind(b1, b2, b3)
            if sk is not None:
                _emit(i, sk, _body_ratio(*(b3[0], b3[3], b3[1], b3[2])))
            ck = _soldiers_kind(b1, b2, b3)
            if ck is not None:
                _emit(i, ck, min(1.0, _body_ratio(*(b3[0], b3[3], b3[1], b3[2]))))

    return result


def make_sample_pattern_scan() -> PatternScanResult:
    """Synthetic bar series exercising several patterns, for demo mode."""
    bars: list[dict[str, Any]] = [
        {"time": "09:15", "open": 100, "high": 101, "low": 99, "close": 100.5},
        # Bullish engulfing (prev bearish, current bullish engulfs).
        {"time": "09:20", "open": 100.5, "high": 101, "low": 99.5, "close": 99.8},
        {"time": "09:25", "open": 99.5, "high": 102, "low": 99.4, "close": 101.8},
        # Doji.
        {"time": "09:30", "open": 101.5, "high": 102.5, "low": 100.5, "close": 101.52},
        # Hammer.
        {"time": "09:35", "open": 101.0, "high": 101.2, "low": 99.0, "close": 100.9},
        # Three white soldiers.
        {"time": "09:40", "open": 100.9, "high": 101.9, "low": 100.85, "close": 101.8},
        {"time": "09:45", "open": 101.4, "high": 102.9, "low": 101.35, "close": 102.8},
        {"time": "09:50", "open": 102.4, "high": 103.9, "low": 102.35, "close": 103.8},
    ]
    return detect_patterns(bars)
