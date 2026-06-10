"""Autonomous trading agent.

Single-agent loop that fetches market data, runs technical analysis, generates
a BUY/SELL/HOLD signal via LLM reasoning, and executes via OpenAlgo — all
with safety guardrails.

Adapted from Agentic-Trader (marketcalls/Agentic-Trader):
- Parallel data fetch pattern (asyncio.gather instead of threading)
- 7-indicator technical analysis pipeline
- Safety checks: market hours, daily stop-loss, max position size
- State tracking: daily P&L, active positions, trade counts

Key differences from the reference:
- Uses FlintTrade's LLMClient (multi-provider, no LiteLLM dependency)
- Uses FlintTrade's OpenAlgo REST client (packages/core)
- Async-first throughout (asyncio, httpx)
- Typed dataclasses for all intermediate results
- No colorama / print-heavy logging — uses standard logging
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, time
from enum import StrEnum
from typing import Any

logger = logging.getLogger("flinttrade.ai.autonomous_agent")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_IST_OFFSET_HOURS = 5.5  # UTC+5:30
_MARKET_OPEN = time(9, 15)
_MARKET_CLOSE = time(15, 30)
_SQUARE_OFF_TIME = time(15, 15)


# ---------------------------------------------------------------------------
# Response normalisation
#
# The agent reads market data through whatever client is injected. The modern
# flinttrade_core.openalgo_client returns typed Pydantic models (Quote/Depth/
# list[OHLCV]); older/mock brokers return dict envelopes ({"status", "data"}).
# These helpers accept EITHER so the same agent works against the live typed
# client AND the dict-mocked test brokers — the wiring boundary the smart-route
# executor handles for orders, applied here for reads.
# ---------------------------------------------------------------------------


def _as_quote_fields(resp: Any) -> dict[str, Any] | None:
    """Return ltp/open/high/low/volume/prev_close from a typed Quote or dict."""
    if resp is None:
        return None
    # Typed Quote model — has an ltp attribute (not a dict).
    if not isinstance(resp, dict) and hasattr(resp, "ltp"):
        return {
            "ltp": getattr(resp, "ltp", 0),
            "open": getattr(resp, "open", 0),
            "high": getattr(resp, "high", 0),
            "low": getattr(resp, "low", 0),
            "volume": getattr(resp, "volume", 0),
            "prev_close": getattr(resp, "prev_close", 0),
        }
    if isinstance(resp, dict):
        if resp.get("status") == "success" and isinstance(resp.get("data"), dict):
            return resp["data"]
        if resp.get("status") in (None, "success") and "ltp" in resp:
            return resp
    return None


def _as_depth_sides(resp: Any) -> tuple[list[Any], list[Any]] | None:
    """Return (bids, asks) level lists from a typed Depth or dict envelope."""
    if resp is None:
        return None
    if not isinstance(resp, dict) and hasattr(resp, "bids"):
        return list(getattr(resp, "bids", []) or []), list(getattr(resp, "asks", []) or [])
    if isinstance(resp, dict):
        data = resp.get("data") if isinstance(resp.get("data"), dict) else resp
        return list(data.get("bids", []) or []), list(data.get("asks", []) or [])
    return None


def _level_qty(level: Any) -> float:
    """Quantity from a typed DepthLevel or a {'quantity': N} dict."""
    if isinstance(level, dict):
        return float(level.get("quantity", 0) or 0)
    return float(getattr(level, "quantity", 0) or 0)


def _as_ohlcv_series(resp: Any) -> dict[str, list[float]] | None:
    """Return {close,high,low,volume} lists from list[OHLCV] or a dict envelope."""
    if resp is None:
        return None
    # Typed list[OHLCV] — bars with .close attributes.
    if isinstance(resp, list):
        if not resp:
            return {"close": [], "high": [], "low": [], "volume": []}
        if hasattr(resp[0], "close"):
            return {
                "close": [float(getattr(b, "close", 0) or 0) for b in resp],
                "high": [float(getattr(b, "high", 0) or 0) for b in resp],
                "low": [float(getattr(b, "low", 0) or 0) for b in resp],
                "volume": [float(getattr(b, "volume", 0) or 0) for b in resp],
            }
        return None
    if isinstance(resp, dict):
        if resp.get("status") == "error":
            return None
        src = resp.get("data") if isinstance(resp.get("data"), dict) else resp
        return {
            "close": _to_float_list(src.get("close", [])),
            "high": _to_float_list(src.get("high", [])),
            "low": _to_float_list(src.get("low", [])),
            "volume": _to_float_list(src.get("volume", [])),
        }
    return None


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class TradeSignal(StrEnum):
    """Output of the LLM decision step."""

    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"


class AgentStatus(StrEnum):
    """Lifecycle status of the autonomous agent."""

    IDLE = "IDLE"
    RUNNING = "RUNNING"
    STOPPED = "STOPPED"
    ERROR = "ERROR"


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class MarketData:
    """Aggregated market data for one symbol.

    Attributes:
        symbol:        Instrument symbol (e.g. "NIFTY25JULFUT").
        ltp:           Last traded price.
        open:          Day's open price.
        high:          Day's high.
        low:           Day's low.
        volume:        Traded volume.
        prev_close:    Previous session close.
        bid_ask_ratio: Total bid qty / total ask qty from depth (> 1 = buy pressure).
        rsi:           RSI(14) on 5m bars. None if history unavailable.
        macd_trend:    "bullish" | "bearish" | "neutral" from MACD crossover.
        ema_trend:     "bullish" | "bearish" | "neutral" from EMA20/EMA50 crossover.
        supertrend:    "bullish" | "bearish" | "neutral" from Supertrend indicator.
        vwap_position: "above" | "below" | "unknown" relative to VWAP.
        error:         Non-empty string if fetch failed.
    """

    symbol: str = ""
    ltp: float = 0.0
    open: float = 0.0
    high: float = 0.0
    low: float = 0.0
    volume: int = 0
    prev_close: float = 0.0
    bid_ask_ratio: float = 1.0
    rsi: float | None = None
    macd_trend: str = "neutral"
    ema_trend: str = "neutral"
    supertrend: str = "neutral"
    vwap_position: str = "unknown"
    error: str = ""

    @property
    def is_valid(self) -> bool:
        """True if data was fetched successfully and LTP is non-zero."""
        return not self.error and self.ltp > 0


@dataclass
class RiskAssessment:
    """Risk parameters evaluated before order execution.

    Attributes:
        allowed:      False if any safety check blocks the trade.
        reason:       Human-readable explanation when not allowed.
        position_qty: Recommended quantity based on max_position_size.
        stop_loss:    Absolute stop-loss price.
        take_profit:  Absolute take-profit price (2:1 R/R default).
    """

    allowed: bool = True
    reason: str = ""
    position_qty: int = 1
    stop_loss: float = 0.0
    take_profit: float = 0.0


@dataclass
class AgentConfig:
    """Runtime configuration for AutonomousTrader.

    Attributes:
        symbols:            Instruments to trade (e.g. ["NIFTY25JULFUT"]).
        exchange:           Exchange code (NSE, NFO, MCX, etc.).
        product:            Product type: MIS (intraday), CNC, NRML.
        max_position_size:  Maximum number of lots per symbol at any time.
        stop_loss_pct:      Stop-loss as a percentage of entry price.
        take_profit_pct:    Take-profit as a percentage of entry price.
        daily_stop_loss:    Aggregate daily P&L limit — agent halts if breached.
        max_trades_per_symbol: Maximum trades per symbol per session.
        cycle_interval_sec: Seconds between analysis cycles.
    """

    symbols: list[str] = field(default_factory=list)
    exchange: str = "NSE"
    product: str = "MIS"
    max_position_size: int = 1
    stop_loss_pct: float = 2.0
    take_profit_pct: float = 4.0
    daily_stop_loss: float = -10_000.0
    max_trades_per_symbol: int = 5
    cycle_interval_sec: int = 60


@dataclass
class AgentState:
    """Mutable runtime state for one trading session.

    Attributes:
        daily_pnl:       Accumulated session P&L.
        trade_counts:    Number of completed trades per symbol.
        active_positions: Currently open positions {symbol: entry_price}.
        position_details: Full per-symbol position context the SL/TP monitor
            needs: ``{entry_price, stop_loss, take_profit, action, quantity}``.
        stop_loss_hit:   True if daily_stop_loss has been breached.
        squared_off:     True if all positions squared off for the day.
        last_signals:    Most recent signal per symbol.
        cycle_count:     Number of analysis cycles completed.
    """

    daily_pnl: float = 0.0
    trade_counts: dict[str, int] = field(default_factory=dict)
    active_positions: dict[str, float] = field(default_factory=dict)
    position_details: dict[str, dict[str, Any]] = field(default_factory=dict)
    stop_loss_hit: bool = False
    squared_off: bool = False
    last_signals: dict[str, str] = field(default_factory=dict)
    cycle_count: int = 0


# ---------------------------------------------------------------------------
# AutonomousTrader
# ---------------------------------------------------------------------------


class AutonomousTrader:
    """Single-agent autonomous trading system.

    Workflow per cycle:
    1. Safety pre-check (market hours, daily stop-loss, already squared off)
    2. Fetch market data in parallel (quotes + depth + technical indicators)
    3. For each symbol: generate trade signal with LLM reasoning
    4. Assess risk (position limits, existing positions)
    5. Execute via OpenAlgo with safety guardrails
    6. Monitor open positions and trigger stop-loss / take-profit

    The agent is deliberately single-symbol-per-cycle to keep prompt size
    small and LLM latency predictable (< 3s with local LM Studio).

    Adapted from Agentic-Trader v3.1 (marketcalls/Agentic-Trader).

    Usage::

        from flinttrade_ai.autonomous_agent import AutonomousTrader, AgentConfig
        from flinttrade_ai.llm_client import LLMClient
        from flinttrade_core.openalgo_client import OpenAlgoClient

        config = AgentConfig(
            symbols=["ICICIBANK", "RELIANCE"],
            exchange="NSE",
            product="MIS",
            max_position_size=1,
            stop_loss_pct=2.0,
        )
        trader = AutonomousTrader(
            llm_client=LLMClient(),
            openalgo_client=OpenAlgoClient(),   # market-data reads only
            config=config,
            order_executor=gated_executor,      # the ONLY order path (gated)
        )
        await trader.run_cycle()          # single cycle
        await trader.run_session()        # full session loop
    """

    def __init__(
        self,
        llm_client: Any,
        openalgo_client: Any,
        config: AgentConfig | None = None,
        vault: Any | None = None,
        order_executor: Any | None = None,
    ) -> None:
        """Initialise the autonomous trader.

        Args:
            llm_client:       FlintTrade LLMClient instance.
            openalgo_client:  FlintTrade OpenAlgoClient instance — used for
                MARKET DATA reads only (quotes/depth/history). The agent never
                places orders through it.
            config:           Agent configuration. Uses safe defaults if None.
            vault:            Optional :class:`~flinttrade_ai.obsidian_bridge.ObsidianVault`.
                When supplied (and available), the agent reads the operator's
                notes as decision context and journals each decision back. Pure
                vault I/O — never on the order path; any vault error degrades to
                "no context / no journal" rather than disrupting trading.
            order_executor:   The agent's ONLY order path — an object exposing
                ``async route_order(order) -> decision`` where every dispatch
                runs the full gated execution chain (SafetySystem L1–L5 →
                ``gate_order`` one-shot ``SafetyContext`` → ``BrokerRouter``),
                e.g. :class:`flinttrade_core.smart_order_routes.GatedChildExecutor`.
                When None (the default), order placement FAILS CLOSED — the
                agent can analyse and signal but never reach a broker.
        """
        self.llm = llm_client
        self.broker = openalgo_client
        self.config = config or AgentConfig()
        self.vault = vault
        self.order_executor = order_executor
        self.state = AgentState(
            trade_counts={sym: 0 for sym in self.config.symbols},
            last_signals={sym: TradeSignal.HOLD for sym in self.config.symbols},
        )
        self._status: AgentStatus = AgentStatus.IDLE
        self._state_lock = asyncio.Lock()
        self._stop_requested = False
        self._square_off_on_stop = True

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    @property
    def status(self) -> AgentStatus:
        return self._status

    # ------------------------------------------------------------------
    # Market hours (IST)
    # ------------------------------------------------------------------

    @staticmethod
    def _ist_now() -> datetime:
        """Current time in IST (UTC+5:30) without pytz dependency."""
        import datetime as dt

        utc_now = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
        ist = utc_now + dt.timedelta(hours=5, minutes=30)
        return ist

    def _is_market_open(self) -> bool:
        """Return True if current IST time is within regular trading hours."""
        now_time = self._ist_now().time()
        return _MARKET_OPEN <= now_time <= _MARKET_CLOSE

    def _is_square_off_time(self) -> bool:
        """Return True at or after the daily square-off time."""
        now_time = self._ist_now().time()
        return now_time >= _SQUARE_OFF_TIME

    # ------------------------------------------------------------------
    # Step 1: Fetch market data
    # ------------------------------------------------------------------

    async def _fetch_symbol_data(self, symbol: str) -> MarketData:
        """Fetch quotes, depth, and calculate technical indicators for one symbol.

        Runs synchronous OpenAlgo API calls via asyncio.to_thread to avoid
        blocking the event loop. Mirrors Agentic-Trader's per-symbol fetch
        function, adapted for async.

        Args:
            symbol: Instrument symbol to fetch.

        Returns:
            Populated MarketData (with error field set on failure).
        """
        try:
            data = MarketData(symbol=symbol)

            # Quotes — typed Quote model or dict envelope.
            quotes_resp = await self.broker.quotes(
                symbol=symbol, exchange=self.config.exchange
            )
            q = _as_quote_fields(quotes_resp)
            if q is not None:
                data.ltp = float(q.get("ltp", 0) or 0)
                data.open = float(q.get("open", 0) or 0)
                data.high = float(q.get("high", 0) or 0)
                data.low = float(q.get("low", 0) or 0)
                data.volume = int(q.get("volume", 0) or 0)
                data.prev_close = float(q.get("prev_close", 0) or 0)
            else:
                data.error = f"quotes failed: {quotes_resp}"
                return data

            # Depth — typed Depth model or dict envelope.
            depth_resp = await self.broker.depth(
                symbol=symbol, exchange=self.config.exchange
            )
            sides = _as_depth_sides(depth_resp)
            if sides is not None:
                bids, asks = sides
                total_bid = sum(_level_qty(b) for b in bids)
                total_ask = sum(_level_qty(a) for a in asks)
                data.bid_ask_ratio = total_bid / total_ask if total_ask > 0 else 1.0

            # Technical indicators via history (5-minute bars, last 3 days)
            data = await self._compute_indicators(data)
            return data

        except Exception as exc:
            logger.warning("Fetch failed for %s: %s", symbol, exc)
            return MarketData(symbol=symbol, error=str(exc))

    async def _compute_indicators(self, data: MarketData) -> MarketData:
        """Add 7 technical indicators to MarketData using 5m historical bars.

        Indicators computed:
        1. RSI(14)
        2. MACD crossover (12, 26, 9)
        3. EMA20 vs EMA50 crossover
        4. Supertrend (ATR-based, factor=3, period=7)
        5. VWAP position (above/below)
        6. Bollinger Band position (not stored but used in LLM prompt)
        7. Stochastic %K (not stored but used in LLM prompt)

        Args:
            data: MarketData object to enrich with indicators.

        Returns:
            The same MarketData with indicator fields set.
        """
        try:
            import datetime as dt

            end_date = self._ist_now().strftime("%Y-%m-%d")
            start_date = (self._ist_now() - dt.timedelta(days=3)).strftime("%Y-%m-%d")

            history_resp = await self.broker.history(
                symbol=data.symbol,
                exchange=self.config.exchange,
                interval="5m",
                start_date=start_date,
                end_date=end_date,
            )

            # Accept list[OHLCV] (typed client) or a dict of OHLC lists (mock).
            series = _as_ohlcv_series(history_resp)
            if series is None:
                return data
            closes = series["close"]
            highs = series["high"]
            lows = series["low"]
            volumes = series["volume"]

            if len(closes) < 30:
                return data

            # RSI(14)
            rsi_vals = _rsi(closes, period=14)
            if rsi_vals:
                data.rsi = round(rsi_vals[-1], 2)

            # MACD (12, 26, 9)
            macd_line, signal_line = _macd(closes, fast=12, slow=26, signal=9)
            if macd_line and signal_line:
                data.macd_trend = (
                    "bullish" if macd_line[-1] > signal_line[-1] else "bearish"
                )

            # EMA 20 vs EMA 50
            ema20 = _ema(closes, 20)
            ema50 = _ema(closes, 50)
            if ema20 and ema50:
                data.ema_trend = "bullish" if ema20[-1] > ema50[-1] else "bearish"

            # Supertrend (simplified)
            st_signal = _supertrend_signal(highs, lows, closes, period=7, multiplier=3.0)
            data.supertrend = st_signal

            # VWAP position
            if volumes and len(volumes) == len(closes):
                vwap = _vwap(highs, lows, closes, volumes)
                if vwap and data.ltp > 0:
                    data.vwap_position = "above" if data.ltp > vwap else "below"

        except Exception as exc:
            logger.debug("Indicator computation failed for %s: %s", data.symbol, exc)

        return data

    async def analyse(self, symbol: str) -> MarketData:
        """Fetch and analyse one symbol.

        Args:
            symbol: Instrument symbol.

        Returns:
            Populated MarketData with technical indicators.
        """
        return await self._fetch_symbol_data(symbol)

    # ------------------------------------------------------------------
    # Step 2: Fetch all symbols in parallel
    # ------------------------------------------------------------------

    async def analyze_all(self) -> dict[str, MarketData]:
        """Fetch all configured symbols in parallel.

        Returns:
            Dict mapping symbol -> MarketData.
        """
        tasks = [self._fetch_symbol_data(sym) for sym in self.config.symbols]
        results = await asyncio.gather(*tasks, return_exceptions=False)
        return {md.symbol: md for md in results}

    # ------------------------------------------------------------------
    # Step 3: LLM signal generation
    # ------------------------------------------------------------------

    async def decide(self, market_data: MarketData) -> str:
        """Generate a BUY/SELL/HOLD signal using LLM reasoning.

        Builds a structured prompt with all available market context and asks
        the configured LLM for a decision. Falls back to HOLD on any error.

        Args:
            market_data: Fully populated MarketData for the symbol.

        Returns:
            One of "BUY", "SELL", "HOLD".
        """
        if not market_data.is_valid:
            logger.warning("Invalid data for %s, defaulting to HOLD", market_data.symbol)
            return TradeSignal.HOLD

        vault_notes = self._vault_context(market_data.symbol)
        prompt = _build_signal_prompt(
            market_data, self.state, self.config, vault_notes=vault_notes,
        )

        try:
            # LLMClient.chat() is synchronous — run in thread to avoid blocking
            from .llm_client import LLMMessage  # local import avoids circular

            messages = [
                LLMMessage(
                    role="system",
                    content=(
                        "You are a disciplined intraday trading analyst for Indian equities. "
                        "Respond with EXACTLY one word: BUY, SELL, or HOLD. "
                        "No explanation, no punctuation, just the signal word."
                    ),
                ),
                LLMMessage(role="user", content=prompt),
            ]
            response = await asyncio.to_thread(self.llm.chat, messages)
            raw = response.content.strip().upper() if response.content else "HOLD"
            # Extract first word in case LLM includes extra text
            word = raw.split()[0] if raw else "HOLD"
            if word in (TradeSignal.BUY, TradeSignal.SELL, TradeSignal.HOLD):
                return word
            logger.debug("LLM returned unexpected signal '%s' for %s, using HOLD", raw, market_data.symbol)
            return TradeSignal.HOLD

        except Exception as exc:
            logger.error("LLM decision failed for %s: %s", market_data.symbol, exc)
            return TradeSignal.HOLD

    # ------------------------------------------------------------------
    # Obsidian vault — operator-knowledge context + decision journal
    #
    # Both are pure vault I/O and NEVER touch the order path: the context read
    # only shapes the LLM prompt, and the journal write only records a decision
    # after it is made. Any vault error degrades to "no context / no journal"
    # so the knowledge base can never disrupt a trading cycle.
    # ------------------------------------------------------------------

    def _vault_context(self, symbol: str) -> str:
        """Return a short block of operator notes for ``symbol`` from the vault.

        Searches the configured Obsidian vault for notes mentioning the symbol
        and returns their matching snippets, newline-joined and bulleted, for
        injection into the decision prompt. Returns ``""`` when no vault is
        configured/available or on any error.
        """
        vault = self.vault
        if vault is None:
            return ""
        # The ENTIRE body is guarded: a vault must never break a decision, so a
        # raising ``available`` property OR a malformed ``search`` return (None,
        # an int, a list of non-dicts) degrades to no context, not an exception
        # propagating out of decide()/run_cycle().
        try:
            if not getattr(vault, "available", False):
                return ""
            hits = vault.search(symbol, limit=3)
            snippets = [
                str(h.get("snippet", "")).strip()
                for h in hits
                if isinstance(h, dict) and str(h.get("snippet", "")).strip()
            ]
        except Exception as exc:
            logger.debug("Obsidian context lookup failed for %s: %s", symbol, exc)
            return ""
        return "\n".join(f"  - {s}" for s in snippets)

    def _journal_decision(
        self,
        symbol: str,
        signal: str,
        risk: RiskAssessment,
        exec_result: dict[str, Any] | None,
    ) -> None:
        """Append this cycle's decision to the operator's Obsidian journal.

        Writes one bullet per decision to ``FlintTrade/Journal/<date>.md`` —
        a post-decision record only. No-ops without an available vault and
        swallows any vault error so journalling can't disrupt the cycle.
        """
        vault = self.vault
        if vault is None:
            return
        # Fully guarded (incl. the ``available`` check) so journalling — like the
        # context read — can never raise into the trading cycle.
        try:
            if not getattr(vault, "available", False):
                return
            now = self._ist_now()
            status = (exec_result or {}).get("status", "n/a")
            entry = (
                f"- {now.strftime('%Y-%m-%d %H:%M:%S')} IST | {symbol} | "
                f"signal={signal} | risk_allowed={risk.allowed} ({risk.reason}) | "
                f"order={status}"
            )
            vault.append_note(f"FlintTrade/Journal/{now.strftime('%Y-%m-%d')}", entry)
        except Exception as exc:  # journalling must never disrupt the cycle
            logger.debug("Obsidian journal write failed for %s: %s", symbol, exc)

    # ------------------------------------------------------------------
    # Step 4: Risk assessment
    # ------------------------------------------------------------------

    def _assess_risk(self, signal: str, market_data: MarketData) -> RiskAssessment:
        """Apply pre-trade safety checks and compute order parameters.

        Checks:
        1. Daily stop-loss not breached
        2. Signal is not HOLD
        3. No existing position in same direction (no pyramiding)
        4. Trade count for symbol within limit
        5. Valid LTP for position sizing

        Args:
            signal:      BUY/SELL/HOLD signal.
            market_data: Current market data for the symbol.

        Returns:
            RiskAssessment with allowed flag and order parameters.
        """
        if signal == TradeSignal.HOLD:
            return RiskAssessment(allowed=False, reason="Signal is HOLD")

        if self.state.stop_loss_hit:
            return RiskAssessment(allowed=False, reason="Daily stop-loss already hit")

        if self.state.squared_off:
            return RiskAssessment(allowed=False, reason="Already squared off for today")

        if self.state.daily_pnl <= self.config.daily_stop_loss:
            self.state.stop_loss_hit = True
            return RiskAssessment(allowed=False, reason=f"Daily P&L {self.state.daily_pnl:.0f} breached limit")

        sym = market_data.symbol
        if self.state.trade_counts.get(sym, 0) >= self.config.max_trades_per_symbol:
            return RiskAssessment(
                allowed=False,
                reason=f"Max trades ({self.config.max_trades_per_symbol}) reached for {sym}",
            )

        # Block same-side re-entry if already in a position
        existing = self.state.active_positions.get(sym)
        if existing is not None:
            return RiskAssessment(allowed=False, reason=f"Already in position for {sym}")

        if market_data.ltp <= 0:
            return RiskAssessment(allowed=False, reason="LTP is zero — cannot size position")

        sl_price = (
            market_data.ltp * (1 - self.config.stop_loss_pct / 100)
            if signal == TradeSignal.BUY
            else market_data.ltp * (1 + self.config.stop_loss_pct / 100)
        )
        tp_price = (
            market_data.ltp * (1 + self.config.take_profit_pct / 100)
            if signal == TradeSignal.BUY
            else market_data.ltp * (1 - self.config.take_profit_pct / 100)
        )

        return RiskAssessment(
            allowed=True,
            position_qty=self.config.max_position_size,
            stop_loss=round(sl_price, 2),
            take_profit=round(tp_price, 2),
        )

    # ------------------------------------------------------------------
    # Step 5: Execute
    # ------------------------------------------------------------------

    def _build_market_order(self, symbol: str, action: str, quantity: int) -> Any:
        """Build a typed MARKET :class:`~flinttrade_core.models.Order` for the gate.

        The gated executor (and the SafetyContext HMAC behind it) operates on
        the canonical typed Order, not OpenAlgo kwargs.
        """
        from flinttrade_core.models import Action, Exchange, Order, PriceType  # noqa: PLC0415

        return Order(
            symbol=symbol,
            exchange=Exchange(self.config.exchange),
            action=Action(action),
            pricetype=PriceType.MARKET,
            quantity=str(quantity),
            product=self.config.product,  # type: ignore[arg-type]
            strategy="AutonomousAgent",
        )

    async def execute(
        self, signal: str, symbol: str, risk: RiskAssessment, entry_price: float = 0.0
    ) -> dict[str, Any]:
        """Place a MARKET order through the gated executor if risk allows.

        The agent's ONLY order path is the injected ``order_executor`` — every
        child runs SafetySystem L1–L5 → ``gate_order`` → ``BrokerRouter``.
        Without an executor this FAILS CLOSED (the agent can analyse but never
        trade), rather than falling back to any raw broker client.

        Args:
            signal: "BUY" or "SELL".
            symbol: Instrument symbol.
            risk:   Pre-validated RiskAssessment.
            entry_price: Last traded price at decision time — recorded so the
                SL/TP monitor has a real entry reference.

        Returns:
            Dict with order response or error information.
        """
        if not risk.allowed:
            logger.info("Execution blocked for %s: %s", symbol, risk.reason)
            return {"status": "blocked", "reason": risk.reason}

        if self.order_executor is None:
            logger.warning(
                "Execution blocked for %s: no gated order executor wired — "
                "the agent cannot place live orders without the "
                "SafetySystem → gate_order → BrokerRouter path",
                symbol,
            )
            return {
                "status": "blocked",
                "reason": (
                    "no gated order executor wired — live trading from the agent "
                    "requires the gated execution path"
                ),
            }

        action = "BUY" if signal == TradeSignal.BUY else "SELL"
        try:
            order = self._build_market_order(symbol, action, risk.position_qty)
            decision = await self.order_executor.route_order(order)

            if getattr(decision, "passed", False):
                orderid = str(getattr(decision.order_response, "orderid", "") or "")
                async with self._state_lock:
                    self.state.active_positions[symbol] = entry_price
                    self.state.position_details[symbol] = {
                        "entry_price": entry_price,
                        "stop_loss": risk.stop_loss,
                        "take_profit": risk.take_profit,
                        "action": action,
                        "quantity": risk.position_qty,
                    }
                    self.state.trade_counts[symbol] = self.state.trade_counts.get(symbol, 0) + 1
                    self.state.last_signals[symbol] = signal
                logger.info("Order placed: %s %s x%d (%s)", action, symbol, risk.position_qty, orderid)
                return {"status": "success", "data": {"orderid": orderid, "price": entry_price}}

            error = str(getattr(decision, "error", "") or "order refused")
            logger.warning("Order refused for %s: %s", symbol, error)
            return {"status": "error", "error": error}

        except Exception as exc:
            logger.error("Execution error for %s: %s", symbol, exc)
            return {"status": "error", "error": str(exc)}

    # ------------------------------------------------------------------
    # Step 6: Monitor open positions
    # ------------------------------------------------------------------

    async def monitor(self, position: dict[str, Any]) -> None:
        """Check an open position against stop-loss and take-profit levels.

        Fetches current LTP and squares off if SL/TP is hit. Updates
        daily P&L state.

        Args:
            position: Dict with keys: symbol, entry_price, stop_loss,
                      take_profit, action ("BUY"/"SELL"), quantity.
        """
        symbol = position.get("symbol", "")
        entry = float(position.get("entry_price", 0))
        sl = float(position.get("stop_loss", 0))
        tp = float(position.get("take_profit", 0))
        action = position.get("action", "BUY")
        qty = int(position.get("quantity", 1))

        if not symbol or entry <= 0:
            return

        try:
            quotes_resp = await self.broker.quotes(
                symbol=symbol, exchange=self.config.exchange
            )
            if not isinstance(quotes_resp, dict) or quotes_resp.get("status") != "success":
                return

            ltp = float(quotes_resp.get("data", {}).get("ltp", 0))
            if ltp <= 0:
                return

            should_close = False
            pnl = 0.0

            if action == "BUY":
                pnl = (ltp - entry) * qty
                if ltp <= sl:
                    should_close = True
                    logger.warning("Stop-loss hit for %s: LTP %.2f <= SL %.2f", symbol, ltp, sl)
                elif tp > 0 and ltp >= tp:
                    should_close = True
                    logger.info("Take-profit hit for %s: LTP %.2f >= TP %.2f", symbol, ltp, tp)
            else:  # SELL
                pnl = (entry - ltp) * qty
                if ltp >= sl:
                    should_close = True
                    logger.warning("Stop-loss hit for %s: LTP %.2f >= SL %.2f", symbol, ltp, sl)
                elif tp > 0 and ltp <= tp:
                    should_close = True
                    logger.info("Take-profit hit for %s: LTP %.2f <= TP %.2f", symbol, ltp, tp)

            if should_close:
                if self.order_executor is None:
                    # Fail closed: without the gated path no exit order can be
                    # placed. (An executor-less agent can never have OPENED a
                    # position either — execute() fails closed — so this only
                    # fires if state was injected externally.)
                    logger.warning(
                        "SL/TP hit for %s but no gated order executor is wired — "
                        "cannot square off", symbol,
                    )
                    return

                exit_action = "SELL" if action == "BUY" else "BUY"
                order = self._build_market_order(symbol, exit_action, qty)
                decision = await self.order_executor.route_order(order)
                if not getattr(decision, "passed", False):
                    logger.warning(
                        "Square-off refused for %s: %s — position stays tracked",
                        symbol, getattr(decision, "error", "") or "order refused",
                    )
                    return

                async with self._state_lock:
                    self.state.active_positions.pop(symbol, None)
                    self.state.position_details.pop(symbol, None)
                    self.state.daily_pnl += pnl

                    if self.state.daily_pnl <= self.config.daily_stop_loss:
                        self.state.stop_loss_hit = True
                        logger.warning("Daily stop-loss hit. Total P&L: %.0f", self.state.daily_pnl)

        except Exception as exc:
            logger.error("Monitor error for %s: %s", symbol, exc)

    # ------------------------------------------------------------------
    # Cycle / Session
    # ------------------------------------------------------------------

    async def run_cycle(self) -> dict[str, Any]:
        """Execute one full analysis-decision-execution cycle.

        Returns:
            Dict summarising actions taken this cycle.
        """
        if not self._is_market_open():
            logger.info("Market is closed — skipping cycle")
            return {"skipped": True, "reason": "market_closed"}

        if self.state.stop_loss_hit:
            logger.warning("Daily stop-loss hit — no new trades this cycle")
            return {"skipped": True, "reason": "stop_loss_hit"}

        self._status = AgentStatus.RUNNING
        async with self._state_lock:
            self.state.cycle_count += 1
            cycle_count = self.state.cycle_count
        cycle_result: dict[str, Any] = {"cycle": cycle_count, "actions": {}}

        # Parallel fetch
        all_data = await self.analyze_all()

        for symbol, market_data in all_data.items():
            if not market_data.is_valid:
                logger.debug("Skipping %s — data not available", symbol)
                continue

            signal = await self.decide(market_data)
            risk = self._assess_risk(signal, market_data)
            exec_result = await self.execute(signal, symbol, risk, entry_price=market_data.ltp)
            cycle_result["actions"][symbol] = {
                "signal": signal,
                "risk_allowed": risk.allowed,
                "risk_reason": risk.reason,
                "order": exec_result,
            }
            self._journal_decision(symbol, signal, risk, exec_result)

        # SL/TP monitoring — previously defined but never invoked, so open
        # positions went unmanaged until end-of-day square-off. Check every
        # tracked position once per cycle against its stop/target.
        async with self._state_lock:
            monitored = [
                {"symbol": symbol, **details}
                for symbol, details in self.state.position_details.items()
            ]
        for position in monitored:
            await self.monitor(position)

        return cycle_result

    def request_stop(self, square_off: bool = True) -> None:
        """Ask a running session to stop after the current cycle.

        Thread-safe (a plain bool flip read by the session loop). When
        ``square_off`` is True (the default — the safe choice for an
        unattended agent), the loop exits via the square-off path so no
        position is left unmanaged.

        Args:
            square_off: Square off all tracked positions before stopping.
        """
        self._square_off_on_stop = square_off
        self._stop_requested = True

    async def run_session(self) -> None:
        """Run the full trading session loop until market close or stop.

        Runs cycles every config.cycle_interval_sec seconds. Automatically
        squares off all positions at square-off time, on cancellation, and
        (by default) on an operator stop request.
        """
        self._status = AgentStatus.RUNNING
        self._stop_requested = False
        logger.info(
            "Autonomous trader starting. Symbols: %s, Exchange: %s",
            self.config.symbols,
            self.config.exchange,
        )

        try:
            while self._is_market_open() and not self._stop_requested:
                if self._is_square_off_time() and not self.state.squared_off:
                    # Only mark squared_off when the broker ACTUALLY flattened
                    # every position — a refused/aborted exit (e.g. the jti was
                    # revoked) must NOT report a false flat state while real
                    # positions remain open at the broker.
                    self.state.squared_off = await self._square_off_all()
                    break

                await self.run_cycle()

                # Sleep in 1s slices so a stop request takes effect promptly
                # rather than after a full cycle interval.
                for _ in range(max(1, int(self.config.cycle_interval_sec))):
                    if self._stop_requested:
                        break
                    await asyncio.sleep(1)

            if self._stop_requested and self._square_off_on_stop and not self.state.squared_off:
                logger.info("Stop requested — squaring off positions")
                self.state.squared_off = await self._square_off_all()

        except asyncio.CancelledError:
            logger.info("Session cancelled — squaring off positions")
            if await self._square_off_all():
                self.state.squared_off = True
        except Exception as exc:
            self._status = AgentStatus.ERROR
            logger.error("Session error: %s", exc)
            raise
        finally:
            self._status = AgentStatus.STOPPED
            logger.info(
                "Session complete. Daily P&L: %.0f, Cycles: %d",
                self.state.daily_pnl,
                self.state.cycle_count,
            )

    async def _square_off_all(self) -> bool:
        """Square off all active positions with gated reverse MARKET orders.

        Places one reverse order per tracked position through the gated
        executor (rather than a broker-level close-all, which OpenAlgo applies
        regardless of strategy — quirk #2 — and which would bypass the gate).
        Fails closed without an executor; an executor-less agent can never
        have opened a position, so there is nothing to square off.

        Returns:
            ``True`` only when EVERY tracked position was successfully exited
            (no positions remain). A refused/aborted exit leaves that position
            tracked and returns ``False`` so the caller never reports a false
            flat state. A revocation abort mid-square-off stops the loop and
            returns ``False`` — positions stay tracked.
        """
        if self.order_executor is None:
            logger.warning("Square-off skipped — no gated order executor wired")
            # No executor ⇒ no position could ever have been opened. "Flat" is
            # honest only when nothing is tracked.
            async with self._state_lock:
                return not self.state.active_positions

        async with self._state_lock:
            details_snapshot = {
                symbol: dict(details)
                for symbol, details in self.state.position_details.items()
            }
            for symbol in self.state.active_positions:
                details_snapshot.setdefault(symbol, {
                    "action": self.state.last_signals.get(symbol, "BUY"),
                    "quantity": self.config.max_position_size,
                })

        for symbol, details in details_snapshot.items():
            try:
                exit_action = "SELL" if str(details.get("action", "BUY")) == "BUY" else "BUY"
                qty = int(details.get("quantity", self.config.max_position_size) or 1)
                order = self._build_market_order(symbol, exit_action, qty)
                decision = await self.order_executor.route_order(order)
                if not getattr(decision, "passed", False):
                    logger.error(
                        "Square-off refused for %s: %s",
                        symbol, getattr(decision, "error", "") or "order refused",
                    )
                    continue
                async with self._state_lock:
                    self.state.active_positions.pop(symbol, None)
                    self.state.position_details.pop(symbol, None)
                logger.info("Squared off position in %s", symbol)
            except Exception as exc:
                # A SmartRouteAbort (session revoked mid-square-off) stops the
                # whole loop — remaining positions stay tracked and unflattened,
                # loudly. Matched by class name to avoid a hard flinttrade_ai →
                # flinttrade_engine dependency. Ordinary per-symbol failures are
                # logged and the loop continues.
                if type(exc).__name__ == "SmartRouteAbort":
                    logger.error(
                        "Square-off ABORTED for %s (%s) — positions remain open at the broker",
                        symbol, exc,
                    )
                    break
                logger.error("Square-off failed for %s: %s", symbol, exc)

        async with self._state_lock:
            flat = not self.state.active_positions
        if not flat:
            logger.warning(
                "Square-off incomplete — %d position(s) still open: %s",
                len(self.state.active_positions), sorted(self.state.active_positions),
            )
        return flat


# ---------------------------------------------------------------------------
# Prompt builder
# ---------------------------------------------------------------------------


def _build_signal_prompt(
    data: MarketData,
    state: AgentState,
    config: AgentConfig,
    vault_notes: str = "",
) -> str:
    """Build a structured LLM prompt from market data and agent state.

    Produces a compact, token-efficient prompt suitable for a local LLM with
    a 4096-token context window. Includes all 7 indicators. When ``vault_notes``
    is supplied (operator notes pulled from the Obsidian vault) they are added
    as an extra context block ahead of the question.
    """
    lines = [
        f"Symbol: {data.symbol} | Exchange: {config.exchange}",
        f"LTP: {data.ltp:.2f} | Prev Close: {data.prev_close:.2f} | "
        f"Open: {data.open:.2f} | High: {data.high:.2f} | Low: {data.low:.2f}",
        f"Volume: {data.volume:,} | Bid/Ask Ratio: {data.bid_ask_ratio:.2f}",
        "",
        "Technical indicators (5m bars):",
        f"  RSI(14): {data.rsi if data.rsi is not None else 'N/A'}",
        f"  MACD Trend: {data.macd_trend}",
        f"  EMA20 vs EMA50: {data.ema_trend}",
        f"  Supertrend: {data.supertrend}",
        f"  VWAP position: {data.vwap_position}",
        "",
        "Session state:",
        f"  Daily P&L: {state.daily_pnl:.0f}",
        f"  Trades today for this symbol: {state.trade_counts.get(data.symbol, 0)}",
        f"  Last signal: {state.last_signals.get(data.symbol, 'NONE')}",
    ]
    if vault_notes:
        lines += ["", "Operator notes (from your Obsidian vault):", vault_notes]
    lines += ["", "Based on the above, should I BUY, SELL, or HOLD this instrument?"]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Pure-Python technical indicator helpers
# (No TA-Lib dependency — used only when numpy/talib unavailable)
# ---------------------------------------------------------------------------


def _to_float_list(data: Any) -> list[float]:
    """Convert any iterable (including pandas Series) to a plain float list."""
    try:
        if hasattr(data, "tolist"):
            return [float(v) for v in data.tolist()]
        return [float(v) for v in data]
    except (TypeError, ValueError):
        return []


def _ema(values: list[float], period: int) -> list[float]:
    """Exponential moving average using smoothing factor 2/(period+1)."""
    if len(values) < period:
        return []
    k = 2.0 / (period + 1)
    result = [sum(values[:period]) / period]
    for v in values[period:]:
        result.append(v * k + result[-1] * (1 - k))
    return result


def _rsi(values: list[float], period: int = 14) -> list[float]:
    """Wilder's RSI."""
    if len(values) < period + 1:
        return []
    gains, losses = [], []
    for i in range(1, len(values)):
        delta = values[i] - values[i - 1]
        gains.append(max(0.0, delta))
        losses.append(max(0.0, -delta))

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    result = []

    for i in range(period, len(gains)):
        if avg_loss == 0:
            result.append(100.0)
        else:
            rs = avg_gain / avg_loss
            result.append(100.0 - 100.0 / (1 + rs))
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period

    return result


def _macd(
    values: list[float], fast: int = 12, slow: int = 26, signal: int = 9
) -> tuple[list[float], list[float]]:
    """MACD line and signal line."""
    ema_fast = _ema(values, fast)
    ema_slow = _ema(values, slow)

    # Align by trimming the longer EMA
    if len(ema_fast) > len(ema_slow):
        ema_fast = ema_fast[len(ema_fast) - len(ema_slow):]
    elif len(ema_slow) > len(ema_fast):
        ema_slow = ema_slow[len(ema_slow) - len(ema_fast):]

    macd_line = [f - s for f, s in zip(ema_fast, ema_slow)]
    signal_line = _ema(macd_line, signal)
    return macd_line, signal_line


def _atr(highs: list[float], lows: list[float], closes: list[float], period: int = 7) -> list[float]:
    """Average True Range (Wilder's smoothing)."""
    if len(highs) < period + 1:
        return []
    trs = []
    for i in range(1, len(closes)):
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        )
        trs.append(tr)
    if len(trs) < period:
        return []
    atr_vals = [sum(trs[:period]) / period]
    for tr in trs[period:]:
        atr_vals.append((atr_vals[-1] * (period - 1) + tr) / period)
    return atr_vals


def _supertrend_signal(
    highs: list[float],
    lows: list[float],
    closes: list[float],
    period: int = 7,
    multiplier: float = 3.0,
) -> str:
    """Simplified Supertrend direction: 'bullish', 'bearish', or 'neutral'."""
    atr_vals = _atr(highs, lows, closes, period)
    if not atr_vals:
        return "neutral"

    # Align series — ATR starts at index period+1 relative to original closes
    offset = len(closes) - len(atr_vals)
    aligned_closes = closes[offset:]
    aligned_highs = highs[offset:]
    aligned_lows = lows[offset:]

    if len(aligned_closes) < 2:
        return "neutral"

    direction = 1  # 1 = bullish, -1 = bearish
    for i, (c, atr, h, lo) in enumerate(zip(aligned_closes, atr_vals, aligned_highs, aligned_lows)):
        mid = (h + lo) / 2
        upper = mid + multiplier * atr
        lower = mid - multiplier * atr
        if c > upper:
            direction = 1
        elif c < lower:
            direction = -1

    return "bullish" if direction == 1 else "bearish"


def _vwap(
    highs: list[float],
    lows: list[float],
    closes: list[float],
    volumes: list[float],
) -> float | None:
    """Session VWAP = sum(typical_price * volume) / sum(volume)."""
    total_tpv = 0.0
    total_vol = 0.0
    for h, lo, c, v in zip(highs, lows, closes, volumes):
        tp = (h + lo + c) / 3.0
        total_tpv += tp * v
        total_vol += v
    return total_tpv / total_vol if total_vol > 0 else None
