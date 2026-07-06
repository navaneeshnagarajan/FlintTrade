"""Index contribution analytics (W7).

Decomposes an index's move into its constituents' point contributions: for a
free-float market-cap-weighted index, each stock's contribution to the index
return is ``weight_i × return_i``, and its contribution in index points is
``index_level × weight_i × return_i``. Ranking constituents this way surfaces
which names are driving the index up or down on the day.

Constituent free-float weights are **indicative** (published NSE weights as of
``_WEIGHTS_AS_OF``) — the bridge quote carries no market cap, so exact live
re-weighting is not available. Weights are normalised to sum to 100 so the
per-constituent contributions stay internally consistent. Callers supply live
per-symbol quotes (LTP + previous close); computation is otherwise pure.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

# As-of date for the indicative free-float weight tables below. Refresh from the
# NSE index factsheets periodically; ranking is robust to small drift.
_WEIGHTS_AS_OF = "2026-06-30"

# Indicative NIFTY 50 free-float weights (percent). Order/keys mirror
# market_scanner._NIFTY50_SYMBOLS. Normalised to 100 at load.
_NIFTY50_WEIGHTS: dict[str, float] = {
    "HDFCBANK": 13.2, "RELIANCE": 9.8, "ICICIBANK": 8.4, "INFY": 5.6,
    "TCS": 4.0, "BHARTIARTL": 4.2, "ITC": 3.8, "SBIN": 3.2,
    "LT": 3.6, "AXISBANK": 3.0, "KOTAKBANK": 2.8, "HINDUNILVR": 2.4,
    "BAJFINANCE": 2.2, "M&M": 2.2, "MARUTI": 1.9, "SUNPHARMA": 1.8,
    "NTPC": 1.6, "TATAMOTORS": 1.7, "HCLTECH": 1.6, "TITAN": 1.4,
    "POWERGRID": 1.2, "ULTRACEMCO": 1.2, "ADANIENT": 1.0, "ONGC": 1.0,
    "BAJAJFINSV": 1.1, "TATASTEEL": 1.1, "ASIANPAINT": 1.2, "COALINDIA": 1.0,
    "WIPRO": 0.9, "NESTLEIND": 0.9, "JSWSTEEL": 0.9, "TECHM": 0.9,
    "GRASIM": 0.8, "SBILIFE": 0.8, "HDFCLIFE": 0.8, "ADANIPORTS": 0.9,
    "DRREDDY": 0.8, "CIPLA": 0.7, "HINDALCO": 0.8, "TATACONSUM": 0.7,
    "BAJAJ-AUTO": 0.8, "EICHERMOT": 0.7, "BRITANNIA": 0.6, "APOLLOHOSP": 0.7,
    "DIVISLAB": 0.6, "HEROMOTOCO": 0.6, "BPCL": 0.6, "INDUSINDBK": 0.7,
    "SHREECEM": 0.5, "UPL": 0.4, "VEDL": 0.5,
}

_NIFTYBANK_WEIGHTS: dict[str, float] = {
    "HDFCBANK": 28.0, "ICICIBANK": 24.0, "SBIN": 10.0, "AXISBANK": 9.5,
    "KOTAKBANK": 9.0, "INDUSINDBK": 5.0, "BANKBARODA": 3.0, "PNB": 2.8,
    "AUBANK": 2.5, "IDFCFIRSTB": 2.2, "FEDERALBNK": 2.5, "BANDHANBNK": 1.5,
}

_INDEX_WEIGHTS: dict[str, dict[str, float]] = {
    "NIFTY": _NIFTY50_WEIGHTS,
    "NIFTY50": _NIFTY50_WEIGHTS,
    "BANKNIFTY": _NIFTYBANK_WEIGHTS,
    "NIFTYBANK": _NIFTYBANK_WEIGHTS,
}


@dataclass
class IndexConstituent:
    """One constituent's contribution to the index move."""

    symbol: str = ""
    weight: float = 0.0  # normalised free-float weight, percent
    ltp: float = 0.0
    prev_close: float = 0.0
    change_pct: float = 0.0
    contribution_pct: float = 0.0  # weight% × return% / 100 → share of index return
    contribution_points: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable dictionary."""
        return asdict(self)


@dataclass
class IndexContributionResult:
    """Ranked index-contribution decomposition."""

    index_name: str = ""
    index_level: float = 0.0
    index_change_pct: float = 0.0
    index_change_points: float = 0.0
    weights_as_of: str = _WEIGHTS_AS_OF
    advancers: int = 0
    decliners: int = 0
    constituents: list[IndexConstituent] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable dictionary."""
        return {
            "index_name": self.index_name,
            "index_level": self.index_level,
            "index_change_pct": self.index_change_pct,
            "index_change_points": self.index_change_points,
            "weights_as_of": self.weights_as_of,
            "advancers": self.advancers,
            "decliners": self.decliners,
            "constituents": [c.to_dict() for c in self.constituents],
        }


def index_weights(index_name: str) -> dict[str, float] | None:
    """Return the normalised (sum-to-100) weight table for an index, or None."""
    raw = _INDEX_WEIGHTS.get(index_name.upper())
    if not raw:
        return None
    total = sum(raw.values())
    if total <= 0:
        return None
    return {sym: round(w / total * 100.0, 4) for sym, w in raw.items()}


def compute_index_contribution(
    index_name: str,
    quotes_by_symbol: dict[str, dict[str, float]],
    index_level: float = 0.0,
) -> IndexContributionResult:
    """Decompose an index move into constituent point contributions.

    Args:
        index_name: Index code (``NIFTY``, ``BANKNIFTY``, …).
        quotes_by_symbol: ``{symbol: {"ltp": float, "prev_close": float}}``.
        index_level: Current index level, used to scale contributions into
            points. When 0 the derived level (weighted prev-close basis) is used
            only for the percentage decomposition.

    Returns:
        An :class:`IndexContributionResult` with constituents ranked by absolute
        contribution (largest mover first). Empty if the index is unknown.
    """
    weights = index_weights(index_name)
    if not weights:
        return IndexContributionResult(index_name=index_name.upper())

    constituents: list[IndexConstituent] = []
    advancers = decliners = 0
    index_return_pct = 0.0

    for symbol, weight in weights.items():
        quote = quotes_by_symbol.get(symbol) or {}
        ltp = float(quote.get("ltp", 0) or 0)
        prev = float(quote.get("prev_close", 0) or 0)
        change_pct = (ltp - prev) / prev * 100.0 if (ltp > 0 and prev > 0) else 0.0
        # Share of index return contributed by this name.
        contribution_pct = weight / 100.0 * change_pct
        index_return_pct += contribution_pct
        if change_pct > 0:
            advancers += 1
        elif change_pct < 0:
            decliners += 1
        constituents.append(IndexConstituent(
            symbol=symbol,
            weight=weight,
            ltp=round(ltp, 2),
            prev_close=round(prev, 2),
            change_pct=round(change_pct, 2),
            contribution_pct=round(contribution_pct, 4),
            contribution_points=0.0,  # filled below once index level is known
        ))

    # Scale to index points if a level is supplied (use prev level = level/(1+ret)).
    level = index_level if index_level > 0 else 0.0
    prev_level = level / (1 + index_return_pct / 100.0) if level > 0 else 0.0
    index_change_points = 0.0
    for c in constituents:
        c.contribution_points = round(prev_level * c.contribution_pct / 100.0, 2) if prev_level > 0 else 0.0
        index_change_points += c.contribution_points

    constituents.sort(key=lambda c: abs(c.contribution_pct), reverse=True)

    return IndexContributionResult(
        index_name=index_name.upper(),
        index_level=round(level, 2),
        index_change_pct=round(index_return_pct, 2),
        index_change_points=round(index_change_points, 2),
        advancers=advancers,
        decliners=decliners,
        constituents=constituents,
    )


def make_sample_index_contribution(index_name: str = "NIFTY") -> IndexContributionResult:
    """Synthetic index-contribution decomposition for demo/disconnected mode."""
    weights = index_weights(index_name) or index_weights("NIFTY") or {}
    # Deterministic pseudo-returns: alternate up/down, scaled by rank, so the
    # heavy names show the largest contributions.
    quotes: dict[str, dict[str, float]] = {}
    for i, symbol in enumerate(weights):
        base = 1000.0 + i * 25.0
        ret = ((-1) ** i) * (1.5 - i * 0.02)
        prev = base
        ltp = round(prev * (1 + ret / 100.0), 2)
        quotes[symbol] = {"ltp": ltp, "prev_close": prev}
    return compute_index_contribution(index_name, quotes, index_level=24000.0)
