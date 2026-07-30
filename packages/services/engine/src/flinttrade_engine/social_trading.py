"""Social trading — leaderboard, strategy sharing, copy trading foundation.

Provides:
- TraderProfile: dataclass representing a trader's public profile + metrics
- SharedStrategy: dataclass representing a published/shared strategy
- Leaderboard: ranks traders by various performance metrics
- StrategyMarketplace: browse, publish, and copy shared strategies

This module is the foundation for social/copy trading in FlintTrade.
No external dependencies beyond the standard library.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal

# ── Data classes ──────────────────────────────────────────────────────────────

StrategyCategory = Literal[
    "intraday", "swing", "options", "investment",
    "trend", "momentum", "mean_reversion", "volatility", "volume",
    "pattern", "scalping", "crypto", "commodity", "event",
    "ml", "portfolio", "pairs", "statistical",
]

VALID_CATEGORIES: set[str] = {
    "intraday", "swing", "options", "investment",
    "trend", "momentum", "mean_reversion", "volatility", "volume",
    "pattern", "scalping", "crypto", "commodity", "event",
    "ml", "portfolio", "pairs", "statistical",
}

VALID_SORT_METRICS: set[str] = {
    "total_return_pct",
    "win_rate",
    "sharpe_ratio",
    "follower_count",
    "trades_count",
}

VALID_STRATEGY_SORT: set[str] = {
    "follower_count",
    "backtest_return_pct",
    "backtest_sharpe",
    "live_return_pct",
    "created_at",
}


@dataclass
class TraderProfile:
    """Public profile of a trader on the leaderboard."""

    user_id: str
    display_name: str
    strategy_count: int = 0
    win_rate: float = 0.0
    total_return_pct: float = 0.0
    max_drawdown_pct: float = 0.0
    sharpe_ratio: float = 0.0
    follower_count: int = 0
    trades_count: int = 0
    active_since: str = ""
    risk_score: int = 3  # 1-5 scale


@dataclass
class SharedStrategy:
    """A strategy published to the marketplace."""

    strategy_id: str
    creator_id: str
    name: str
    description: str
    category: str  # one of StrategyCategory values
    instruments: list[str] = field(default_factory=list)
    backtest_sharpe: float = 0.0
    backtest_return_pct: float = 0.0
    backtest_max_dd_pct: float = 0.0
    live_return_pct: float = 0.0
    follower_count: int = 0
    is_public: bool = True
    created_at: str = ""


# ── Leaderboard ──────────────────────────────────────────────────────────────


class Leaderboard:
    """Ranks traders by performance metrics.

    Stores trader profiles in-memory and provides ranked retrieval by
    any numeric metric on TraderProfile.
    """

    def __init__(self) -> None:
        self._profiles: dict[str, TraderProfile] = {}
        self._lock = threading.Lock()

    @property
    def count(self) -> int:
        """Number of profiles on the leaderboard."""
        return len(self._profiles)

    def update_profile(self, profile: TraderProfile) -> None:
        """Add or update a trader profile.

        Args:
            profile: TraderProfile to upsert.

        Raises:
            ValueError: If user_id or display_name is empty.
        """
        if not profile.user_id:
            raise ValueError("user_id must not be empty")
        if not profile.display_name:
            raise ValueError("display_name must not be empty")
        if not 1 <= profile.risk_score <= 5:
            raise ValueError("risk_score must be between 1 and 5")
        with self._lock:
            self._profiles[profile.user_id] = profile

    def get_top_traders(
        self,
        metric: str = "total_return_pct",
        limit: int = 20,
    ) -> list[TraderProfile]:
        """Return traders sorted by the given metric (descending).

        Args:
            metric: Name of a numeric field on TraderProfile to sort by.
                    Must be one of VALID_SORT_METRICS.
            limit: Maximum number of results.

        Returns:
            List of TraderProfile instances, highest metric first.

        Raises:
            ValueError: If metric is not a valid sortable field.
        """
        if metric not in VALID_SORT_METRICS:
            raise ValueError(
                f"Invalid metric '{metric}'. Must be one of: {sorted(VALID_SORT_METRICS)}"
            )
        with self._lock:
            profiles = list(self._profiles.values())
        profiles.sort(key=lambda p: getattr(p, metric, 0), reverse=True)
        return profiles[:limit]

    def get_profile(self, user_id: str) -> TraderProfile | None:
        """Retrieve a single trader profile by user_id.

        Args:
            user_id: The trader's unique identifier.

        Returns:
            TraderProfile if found, else None.
        """
        with self._lock:
            return self._profiles.get(user_id)

    def remove_profile(self, user_id: str) -> bool:
        """Remove a trader profile from the leaderboard.

        Args:
            user_id: The trader's unique identifier.

        Returns:
            True if the profile was removed, False if it didn't exist.
        """
        with self._lock:
            if user_id in self._profiles:
                del self._profiles[user_id]
                return True
        return False


# ── Strategy Marketplace ─────────────────────────────────────────────────────


class StrategyMarketplace:
    """Browse, share, and copy strategies.

    Stores shared strategies in-memory and provides browsing, publishing,
    and copy functionality.
    """

    def __init__(self) -> None:
        self._strategies: dict[str, SharedStrategy] = {}
        self._copies: dict[str, list[str]] = {}  # strategy_id -> [user_ids]
        self._lock = threading.Lock()

    @property
    def count(self) -> int:
        """Number of strategies in the marketplace."""
        return len(self._strategies)

    def publish(self, strategy: SharedStrategy) -> None:
        """Publish a strategy to the marketplace.

        Args:
            strategy: SharedStrategy to publish.

        Raises:
            ValueError: If required fields are missing or category is invalid.
        """
        if not strategy.strategy_id:
            raise ValueError("strategy_id must not be empty")
        if not strategy.creator_id:
            raise ValueError("creator_id must not be empty")
        if not strategy.name:
            raise ValueError("name must not be empty")
        if strategy.category not in VALID_CATEGORIES:
            raise ValueError(
                f"Invalid category '{strategy.category}'. "
                f"Must be one of: {sorted(VALID_CATEGORIES)}"
            )
        if not strategy.created_at:
            strategy.created_at = datetime.now(UTC).isoformat()
        with self._lock:
            self._strategies[strategy.strategy_id] = strategy

    def browse(
        self,
        category: str | None = None,
        sort_by: str = "follower_count",
        limit: int = 50,
    ) -> list[SharedStrategy]:
        """Browse public strategies with optional category filter and sorting.

        Args:
            category: Filter by category (None = all categories).
            sort_by: Field to sort by (descending). Must be in VALID_STRATEGY_SORT.
            limit: Maximum number of results.

        Returns:
            List of SharedStrategy instances matching the criteria.

        Raises:
            ValueError: If sort_by is not a valid field or category is invalid.
        """
        if sort_by not in VALID_STRATEGY_SORT:
            raise ValueError(
                f"Invalid sort_by '{sort_by}'. Must be one of: {sorted(VALID_STRATEGY_SORT)}"
            )
        if category is not None and category not in VALID_CATEGORIES:
            raise ValueError(
                f"Invalid category '{category}'. Must be one of: {sorted(VALID_CATEGORIES)}"
            )

        with self._lock:
            strategies = [s for s in self._strategies.values() if s.is_public]
        if category:
            strategies = [s for s in strategies if s.category == category]
        strategies.sort(key=lambda s: getattr(s, sort_by, 0), reverse=True)
        return strategies[:limit]

    def get_strategy(self, strategy_id: str) -> SharedStrategy | None:
        """Retrieve a single strategy by ID.

        Args:
            strategy_id: Unique strategy identifier.

        Returns:
            SharedStrategy if found, else None.
        """
        with self._lock:
            return self._strategies.get(strategy_id)

    def copy(self, strategy_id: str, user_id: str) -> dict[str, str]:
        """Copy a strategy to a user's account.

        Increments the strategy's follower_count and records the copy.

        Args:
            strategy_id: The strategy to copy.
            user_id: The user copying the strategy.

        Returns:
            Dict with status and copy details.

        Raises:
            ValueError: If strategy_id is not found or user_id is empty.
        """
        if not user_id:
            raise ValueError("user_id must not be empty")

        with self._lock:
            strategy = self._strategies.get(strategy_id)
            if strategy is None:
                raise ValueError(f"Strategy '{strategy_id}' not found")

            if strategy.creator_id == user_id:
                raise ValueError("Cannot copy your own strategy")

            # Track copies
            if strategy_id not in self._copies:
                self._copies[strategy_id] = []

            if user_id in self._copies[strategy_id]:
                return {
                    "status": "already_copied",
                    "strategy_id": strategy_id,
                    "message": "You have already copied this strategy",
                }

            self._copies[strategy_id].append(user_id)
            strategy.follower_count += 1

        return {
            "status": "success",
            "strategy_id": strategy_id,
            "strategy_name": strategy.name,
            "message": f"Strategy '{strategy.name}' copied to your account",
        }

    def get_copies(self, strategy_id: str) -> list[str]:
        """Get the list of user_ids who copied a strategy.

        Args:
            strategy_id: The strategy to look up.

        Returns:
            List of user_ids who copied this strategy.
        """
        with self._lock:
            return list(self._copies.get(strategy_id, []))

    def remove_strategy(self, strategy_id: str) -> bool:
        """Remove a strategy from the marketplace.

        Args:
            strategy_id: The strategy to remove.

        Returns:
            True if removed, False if it didn't exist.
        """
        with self._lock:
            if strategy_id in self._strategies:
                del self._strategies[strategy_id]
                self._copies.pop(strategy_id, None)
                return True
        return False


# ── Seed data ────────────────────────────────────────────────────────────────


def seed_leaderboard() -> Leaderboard:
    """Create a leaderboard seeded with 15 realistic Indian trader profiles.

    Returns:
        Leaderboard with pre-populated profiles.
    """
    leaderboard = Leaderboard()

    profiles = [
        TraderProfile(
            user_id="trader_001", display_name="Arjun Mehta",
            strategy_count=5, win_rate=68.2, total_return_pct=142.5,
            max_drawdown_pct=12.3, sharpe_ratio=2.15, follower_count=1247,
            trades_count=3420, active_since="2022-01-15", risk_score=3,
        ),
        TraderProfile(
            user_id="trader_002", display_name="Priya Sharma",
            strategy_count=3, win_rate=72.1, total_return_pct=98.7,
            max_drawdown_pct=8.5, sharpe_ratio=2.45, follower_count=892,
            trades_count=1856, active_since="2022-06-20", risk_score=2,
        ),
        TraderProfile(
            user_id="trader_003", display_name="Vikram Patel",
            strategy_count=8, win_rate=61.4, total_return_pct=215.3,
            max_drawdown_pct=18.7, sharpe_ratio=1.87, follower_count=2103,
            trades_count=5672, active_since="2021-03-10", risk_score=4,
        ),
        TraderProfile(
            user_id="trader_004", display_name="Ananya Reddy",
            strategy_count=2, win_rate=75.8, total_return_pct=67.4,
            max_drawdown_pct=6.2, sharpe_ratio=2.78, follower_count=634,
            trades_count=945, active_since="2023-02-01", risk_score=1,
        ),
        TraderProfile(
            user_id="trader_005", display_name="Rahul Desai",
            strategy_count=6, win_rate=64.9, total_return_pct=178.2,
            max_drawdown_pct=15.4, sharpe_ratio=1.95, follower_count=1589,
            trades_count=4231, active_since="2021-08-25", risk_score=4,
        ),
        TraderProfile(
            user_id="trader_006", display_name="Sneha Iyer",
            strategy_count=4, win_rate=69.3, total_return_pct=112.8,
            max_drawdown_pct=10.1, sharpe_ratio=2.22, follower_count=1034,
            trades_count=2678, active_since="2022-04-12", risk_score=3,
        ),
        TraderProfile(
            user_id="trader_007", display_name="Karthik Nair",
            strategy_count=7, win_rate=58.6, total_return_pct=256.1,
            max_drawdown_pct=22.3, sharpe_ratio=1.72, follower_count=1876,
            trades_count=6893, active_since="2020-11-05", risk_score=5,
        ),
        TraderProfile(
            user_id="trader_008", display_name="Deepika Joshi",
            strategy_count=3, win_rate=71.5, total_return_pct=89.6,
            max_drawdown_pct=7.8, sharpe_ratio=2.51, follower_count=756,
            trades_count=1534, active_since="2023-01-10", risk_score=2,
        ),
        TraderProfile(
            user_id="trader_009", display_name="Aditya Kulkarni",
            strategy_count=5, win_rate=66.7, total_return_pct=134.9,
            max_drawdown_pct=13.6, sharpe_ratio=2.08, follower_count=1123,
            trades_count=3087, active_since="2022-07-18", risk_score=3,
        ),
        TraderProfile(
            user_id="trader_010", display_name="Meera Gupta",
            strategy_count=4, win_rate=73.2, total_return_pct=76.5,
            max_drawdown_pct=5.9, sharpe_ratio=2.63, follower_count=543,
            trades_count=1267, active_since="2023-05-22", risk_score=1,
        ),
        TraderProfile(
            user_id="trader_011", display_name="Rohan Kapoor",
            strategy_count=9, win_rate=62.8, total_return_pct=198.7,
            max_drawdown_pct=19.2, sharpe_ratio=1.83, follower_count=1678,
            trades_count=5124, active_since="2021-06-14", risk_score=4,
        ),
        TraderProfile(
            user_id="trader_012", display_name="Kavitha Menon",
            strategy_count=2, win_rate=77.4, total_return_pct=54.3,
            max_drawdown_pct=4.8, sharpe_ratio=2.91, follower_count=412,
            trades_count=723, active_since="2023-09-01", risk_score=1,
        ),
        TraderProfile(
            user_id="trader_013", display_name="Sanjay Rao",
            strategy_count=6, win_rate=65.1, total_return_pct=167.8,
            max_drawdown_pct=16.5, sharpe_ratio=1.92, follower_count=1345,
            trades_count=4567, active_since="2021-12-03", risk_score=4,
        ),
        TraderProfile(
            user_id="trader_014", display_name="Nisha Agarwal",
            strategy_count=3, win_rate=70.9, total_return_pct=105.2,
            max_drawdown_pct=9.4, sharpe_ratio=2.34, follower_count=867,
            trades_count=2134, active_since="2022-10-08", risk_score=2,
        ),
        TraderProfile(
            user_id="trader_015", display_name="Amit Thakur",
            strategy_count=5, win_rate=67.5, total_return_pct=148.9,
            max_drawdown_pct=14.1, sharpe_ratio=2.11, follower_count=1198,
            trades_count=3789, active_since="2022-03-25", risk_score=3,
        ),
    ]

    for profile in profiles:
        leaderboard.update_profile(profile)

    return leaderboard


def seed_marketplace() -> StrategyMarketplace:
    """Create a marketplace seeded with 10 realistic sample strategies.

    Returns:
        StrategyMarketplace with pre-populated strategies.
    """
    marketplace = StrategyMarketplace()

    strategies = [
        SharedStrategy(
            strategy_id="strat_001", creator_id="trader_001",
            name="NIFTY Momentum Scalper",
            description="Intraday NIFTY futures scalping using 5-min EMA crossover with RSI confirmation. Targets 20-30 point moves.",
            category="intraday", instruments=["NIFTY", "BANKNIFTY"],
            backtest_sharpe=1.85, backtest_return_pct=87.4, backtest_max_dd_pct=9.2,
            live_return_pct=62.3, follower_count=342, created_at="2024-06-15T10:00:00Z",
        ),
        SharedStrategy(
            strategy_id="strat_002", creator_id="trader_002",
            name="Iron Condor Weekly",
            description="Weekly NIFTY iron condor with 200-point wings. Sells OTM puts and calls, buys further OTM for protection. 70% win rate target.",
            category="options", instruments=["NIFTY"],
            backtest_sharpe=2.12, backtest_return_pct=45.6, backtest_max_dd_pct=5.8,
            live_return_pct=38.9, follower_count=567, created_at="2024-04-20T10:00:00Z",
        ),
        SharedStrategy(
            strategy_id="strat_003", creator_id="trader_003",
            name="Swing Breakout Master",
            description="Multi-stock swing trading on daily charts. Enters on volume breakout above 20-day high, trails with SuperTrend.",
            category="swing", instruments=["RELIANCE", "TCS", "HDFC", "INFY", "ICICI"],
            backtest_sharpe=1.65, backtest_return_pct=124.8, backtest_max_dd_pct=14.3,
            live_return_pct=98.5, follower_count=891, created_at="2024-02-10T10:00:00Z",
        ),
        SharedStrategy(
            strategy_id="strat_004", creator_id="trader_004",
            name="SIP Value Allocator",
            description="Systematic monthly allocation across large-cap, mid-cap, and debt funds based on PE ratio valuation bands.",
            category="investment", instruments=["NIFTYBEES", "JUNIORBEES", "LIQUIDBEES"],
            backtest_sharpe=1.42, backtest_return_pct=18.9, backtest_max_dd_pct=3.2,
            live_return_pct=15.7, follower_count=1234, created_at="2024-01-05T10:00:00Z",
        ),
        SharedStrategy(
            strategy_id="strat_005", creator_id="trader_005",
            name="BANKNIFTY Straddle Adjuster",
            description="Sells ATM BANKNIFTY straddle at open, adjusts legs when delta exceeds 0.3. Targets theta decay with controlled gamma risk.",
            category="options", instruments=["BANKNIFTY"],
            backtest_sharpe=1.98, backtest_return_pct=56.7, backtest_max_dd_pct=11.5,
            live_return_pct=42.1, follower_count=423, created_at="2024-05-12T10:00:00Z",
        ),
        SharedStrategy(
            strategy_id="strat_006", creator_id="trader_006",
            name="Gap and Go Opener",
            description="Intraday strategy that trades opening gaps on NIFTY 50 stocks. Enters within first 15 minutes, exits by 11:30 AM.",
            category="intraday", instruments=["NIFTY50"],
            backtest_sharpe=1.73, backtest_return_pct=72.3, backtest_max_dd_pct=8.7,
            live_return_pct=54.8, follower_count=278, created_at="2024-07-01T10:00:00Z",
        ),
        SharedStrategy(
            strategy_id="strat_007", creator_id="trader_007",
            name="Sector Rotation Quarterly",
            description="Rotates capital across top 3 performing sectors every quarter. Uses relative strength ranking with 6-month lookback.",
            category="investment", instruments=["SECTORAL_ETFS"],
            backtest_sharpe=1.55, backtest_return_pct=34.2, backtest_max_dd_pct=7.6,
            live_return_pct=28.4, follower_count=654, created_at="2024-03-18T10:00:00Z",
        ),
        SharedStrategy(
            strategy_id="strat_008", creator_id="trader_009",
            name="VWAP Reversion Trader",
            description="Mean reversion intraday strategy. Enters when price deviates >1.5% from VWAP, targets reversion to mean.",
            category="intraday", instruments=["NIFTY", "BANKNIFTY", "FINNIFTY"],
            backtest_sharpe=1.91, backtest_return_pct=65.8, backtest_max_dd_pct=7.1,
            live_return_pct=48.2, follower_count=312, created_at="2024-08-05T10:00:00Z",
        ),
        SharedStrategy(
            strategy_id="strat_009", creator_id="trader_011",
            name="Dividend Yield Harvester",
            description="Long-term portfolio of top 15 dividend yield stocks on NSE. Rebalances semi-annually after ex-dividend dates.",
            category="investment", instruments=["ITC", "COAL", "ONGC", "POWERGRID", "NTPC"],
            backtest_sharpe=1.38, backtest_return_pct=22.4, backtest_max_dd_pct=4.5,
            live_return_pct=19.1, follower_count=876, created_at="2024-01-20T10:00:00Z",
        ),
        SharedStrategy(
            strategy_id="strat_010", creator_id="trader_013",
            name="OI Surge Swing",
            description="Swing trading based on unusual OI buildup patterns. Enters when OI increases >20% with price confirmation on daily timeframe.",
            category="swing", instruments=["NFO_STOCKS"],
            backtest_sharpe=1.78, backtest_return_pct=95.6, backtest_max_dd_pct=12.8,
            live_return_pct=71.3, follower_count=534, created_at="2024-06-28T10:00:00Z",
        ),
    ]

    for strategy in strategies:
        marketplace.publish(strategy)

    return marketplace


# ── Registry sync ───────────────────────────────────────────────────────────


# Map strategy key prefix → category used in the marketplace.
_PREFIX_TO_CATEGORY: dict[str, str] = {
    "mtf": "swing",
    "intraday": "intraday",
    "options": "options",
    "trend": "trend",
    "momentum": "momentum",
    "mean_reversion": "mean_reversion",
    "volatility": "volatility",
    "volume": "volume",
    "pattern": "pattern",
    "scalp": "scalping",
    "crypto": "crypto",
    "commodity": "commodity",
    "event": "event",
    "ml": "ml",
    "portfolio": "portfolio",
    "pairs": "pairs",
    "stat": "statistical",
}

# Legacy strategies (from strategies.py) that don't follow prefix naming.
_LEGACY_CATEGORY_MAP: dict[str, str] = {
    "EMACrossover": "trend",
    "Supertrend": "trend",
    "MACD_RSI": "momentum",
    "BollingerMR": "mean_reversion",
    "VWAPDev": "mean_reversion",
    "StraddleSell": "options",
    "StrangleSell": "options",
    "IronCondor": "options",
    "BullPutSpread": "options",
    "BearCallSpread": "options",
    "MomentumBreakout": "momentum",
    "ORB": "intraday",
}


def _classify_strategy(key: str) -> str:
    """Determine the marketplace category for a strategy registry key.

    Checks the legacy map first, then tries prefix matching.
    Falls back to 'swing' for unrecognised keys.

    Args:
        key: The strategy key from ALL_STRATEGIES (e.g. 'MTFRSITrend').

    Returns:
        A string from VALID_CATEGORIES.
    """
    if key in _LEGACY_CATEGORY_MAP:
        return _LEGACY_CATEGORY_MAP[key]

    # Convert CamelCase key to a lowercase, underscore-separated form
    # for prefix matching (e.g. "IntradayGapFill" → "intraday_gap_fill").
    import re

    snake = re.sub(r"(?<=[a-z0-9])([A-Z])", r"_\1", key).lower()

    for prefix, category in _PREFIX_TO_CATEGORY.items():
        if snake.startswith(prefix):
            return category

    return "swing"  # safe default


def _humanise_name(key: str) -> str:
    """Convert a PascalCase strategy key to a human-readable name.

    Examples:
        'IntradayGapFill' → 'Intraday Gap Fill'
        'EMACrossover'    → 'EMA Crossover'
        'MTFRSITrend'     → 'MTFRSI Trend'

    Args:
        key: PascalCase strategy name.

    Returns:
        Space-separated human name.
    """
    import re

    # Insert space between a run of uppercase and an uppercase+lowercase
    spaced = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", key)
    # Insert space before an uppercase letter preceded by lowercase/digit
    spaced = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", spaced)
    return spaced


def _instruments_for_category(category: str) -> list[str]:
    """Return a sensible default instrument list for a given category.

    Args:
        category: A value from VALID_CATEGORIES.

    Returns:
        List of instrument identifiers.
    """
    instruments_map: dict[str, list[str]] = {
        "intraday": ["NIFTY", "BANKNIFTY"],
        "swing": ["NIFTY", "RELIANCE", "TCS", "HDFC"],
        "options": ["NIFTY", "BANKNIFTY"],
        "investment": ["NIFTYBEES", "JUNIORBEES"],
        "trend": ["NIFTY", "BANKNIFTY", "RELIANCE"],
        "momentum": ["NIFTY", "BANKNIFTY"],
        "mean_reversion": ["NIFTY", "RELIANCE"],
        "volatility": ["NIFTY", "BANKNIFTY", "INDIAVIX"],
        "volume": ["NIFTY", "RELIANCE", "TCS"],
        "pattern": ["NIFTY", "RELIANCE", "INFY"],
        "scalping": ["NIFTY", "BANKNIFTY"],
        "crypto": ["BTCUSDT", "ETHUSDT"],
        "commodity": ["GOLD", "SILVER", "CRUDEOIL"],
        "event": ["NIFTY", "BANKNIFTY"],
        "ml": ["NIFTY", "BANKNIFTY"],
        "portfolio": ["NIFTY50"],
        "pairs": ["RELIANCE", "TCS"],
        "statistical": ["NIFTY", "BANKNIFTY"],
    }
    return instruments_map.get(category, ["NIFTY"])


def sync_from_registry(
    marketplace: StrategyMarketplace | None = None,
) -> StrategyMarketplace:
    """Populate a marketplace with entries derived from backtest-engine strategies.

    Reads ALL_STRATEGIES from the backtest-engine's strategy registry and
    creates a SharedStrategy for each, categorised by module prefix.

    If ``marketplace`` is None a fresh one is created (with seed data already
    loaded).  Existing strategies in the marketplace are preserved; only new
    strategy IDs are added.

    Args:
        marketplace: Optional existing marketplace to populate.

    Returns:
        The marketplace with registry strategies added.
    """
    if marketplace is None:
        marketplace = seed_marketplace()

    try:
        from flinttrade_backtest.strategies import ALL_STRATEGIES  # type: ignore[import-untyped]
    except Exception:  # pragma: no cover — import may fail in isolated tests
        return marketplace

    existing_ids = {s.strategy_id for s in marketplace.browse(limit=10_000)}

    for key in sorted(ALL_STRATEGIES.keys()):
        strategy_id = f"registry_{key.lower()}"
        if strategy_id in existing_ids:
            continue

        category = _classify_strategy(key)
        name = _humanise_name(key)
        instruments = _instruments_for_category(category)

        strategy = SharedStrategy(
            strategy_id=strategy_id,
            creator_id="flinttrade_registry",
            name=name,
            description=f"Built-in {category} strategy from the FlintTrade backtest engine.",
            category=category,
            instruments=instruments,
            is_public=True,
        )
        marketplace.publish(strategy)

    return marketplace
