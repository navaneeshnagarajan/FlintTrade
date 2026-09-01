"""Wheel Options Strategy — market-data-driven gated order intent generation.

The Wheel is a systematic premium-income strategy that cycles through two phases:

Phase 1 — Cash-Secured Put (CSP):
    Sell an ATM/near-ATM put option.  Collect premium.
    If the put expires worthless → repeat CSP.
    If assigned (underlying falls below strike at expiry) → enter Phase 2.

Phase 2 — Covered Call (CC):
    After assignment, sell a call above the acquisition cost.
    If expires worthless → repeat CC (continue collecting premium).
    If called away (underlying rises above call strike) → restart from Phase 1.

State machine (WheelPhase):
    WAITING_CSP  → CSP_ACTIVE  → (assigned) ASSIGNED → CC_ACTIVE → (called away) WAITING_CSP
                                ↓ (SL hit or expired)
                               WAITING_CSP

Live execution details:
- Nearest expiry resolved via OpenAlgo ``expiry`` endpoint.
- Premium validity: skip the option if LTP < ₹10.
- SL placed at 30% above entry premium (e.g. sold @ ₹50 → SL BUY @ ₹65).
- Quote and expiry reads may use
  :class:`~flinttrade_core.openalgo_client.OpenAlgoClient`; generated orders are
  queued for FlintTrade's canonical gated strategy runtime and never written
  through that raw client.
- Telegram alerts sent on every state transition via the client's
  ``telegram()`` method.

Usage::

    from flinttrade_core.openalgo_client import OpenAlgoClient
    from flinttrade_engine.strategies.wheel_live import WheelStrategy

    client = OpenAlgoClient(host="http://localhost:5000", api_key="...")
    strategy = WheelStrategy(
        symbol="NIFTY",
        exchange="NFO",
        quantity=50,
        client=client,
    )
    strategy.start()
    await strategy.run_cycle()  # emits intents; the gated runtime submits them
"""

from __future__ import annotations

import logging
from enum import StrEnum
from typing import Any

from flinttrade_core.models import OHLCV, Order, Quote
from flinttrade_core.openalgo_client import OpenAlgoClient
from flinttrade_engine.strategy import BaseStrategy

logger = logging.getLogger("flinttrade.engine.strategies.wheel_live")

#: Minimum option premium (₹) below which the entry is skipped.
MIN_PREMIUM: float = 10.0

#: Stop-loss multiplier above entry premium.
SL_MULTIPLIER: float = 1.30


# ---------------------------------------------------------------------------
# State machine
# ---------------------------------------------------------------------------


class WheelPhase(StrEnum):
    """Wheel strategy phase / state."""

    WAITING_CSP = "WAITING_CSP"
    """Idle — ready to sell the next Cash-Secured Put."""

    CSP_ACTIVE = "CSP_ACTIVE"
    """A put has been sold and is currently live."""

    ASSIGNED = "ASSIGNED"
    """The put was assigned — underlying acquired at the strike price."""

    CC_ACTIVE = "CC_ACTIVE"
    """A covered call has been sold and is currently live."""

    CC_EXPIRED = "CC_EXPIRED"
    """The covered call expired worthless — transitioning back to CC or CSP."""


# ---------------------------------------------------------------------------
# WheelStrategy
# ---------------------------------------------------------------------------


class WheelStrategy(BaseStrategy):
    """Live Wheel options strategy executed via OpenAlgo.

    Manages the full CSP → assignment → CC cycle for a single underlying
    instrument.  All OpenAlgo API calls are async.

    Args:
        symbol:           Underlying symbol (e.g. ``"NIFTY"``).
        exchange:         Options exchange (default ``"NFO"``).
        product:          Order product type (default ``"MIS"``).
        quantity:         Lot size / quantity per leg.
        client:           Read-capable
                          :class:`~flinttrade_core.openalgo_client.OpenAlgoClient`
                          instance for quotes, expiries, and notifications. It
                          is never used for broker mutation.
        put_strike_offset: Distance from ATM to put strike (in points).
                           ``0`` means ATM.  Default ``0``.
        call_strike_offset: Distance above cost-basis to call strike (in points).
                            ``0`` means ATM.  Default ``0``.
        strategy_tag:     OpenAlgo strategy name tag for order tracking.

    State transitions::

        WAITING_CSP ──sell_put()──► CSP_ACTIVE
                                        │ SL hit / EOD exit
                                        ▼
                                    WAITING_CSP
                                        │ assigned (price < strike at expiry)
                                        ▼
                                     ASSIGNED
                                        │ sell_call()
                                        ▼
                                    CC_ACTIVE
                                        │ called away (price > call_strike)
                                        ▼
                                    CC_EXPIRED ──► WAITING_CSP
    """

    def __init__(
        self,
        symbol: str = "NIFTY",
        exchange: str = "NFO",
        product: str = "MIS",
        quantity: int = 50,
        client: OpenAlgoClient | None = None,
        put_strike_offset: float = 0.0,
        call_strike_offset: float = 0.0,
        strategy_tag: str = "wheel",
        **kwargs: Any,
    ) -> None:
        name = kwargs.pop("name", f"WheelStrategy_{symbol}")
        super().__init__(name=name, exchange=exchange, product=product, **kwargs)

        self.symbol = symbol
        self.quantity = quantity
        self._client = client
        self.put_strike_offset = put_strike_offset
        self.call_strike_offset = call_strike_offset
        self.strategy_tag = strategy_tag

        # Current state
        self._phase: WheelPhase = WheelPhase.WAITING_CSP
        self._pending_orders: list[Order] = []

        # Active leg tracking
        self._current_put_symbol: str = ""
        self._current_call_symbol: str = ""
        self._entry_premium: float = 0.0
        self._sl_price: float = 0.0
        self._put_strike: float = 0.0
        self._call_strike: float = 0.0
        self._cost_basis: float = 0.0
        self._current_expiry: str = ""

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def phase(self) -> WheelPhase:
        """Current strategy phase."""
        return self._phase

    # ------------------------------------------------------------------
    # BaseStrategy abstract implementations
    # ------------------------------------------------------------------

    def on_tick(self, quote: Quote) -> None:
        """Not used — this strategy is event-driven, not tick-driven."""

    def on_bar(self, bar: OHLCV) -> None:
        """Not used — wheel runs on daily or scheduled triggers."""

    def on_signal(self, signal: dict[str, Any]) -> None:
        """Not used — wheel is self-contained."""

    def generate_orders(self) -> list[Order]:
        """Return and clear any pending orders.

        Returns:
            List of :class:`~flinttrade_core.models.Order` queued since
            the last call.
        """
        orders = list(self._pending_orders)
        self._pending_orders.clear()
        return orders

    # ------------------------------------------------------------------
    # State persistence
    # ------------------------------------------------------------------

    def get_state_dict(self) -> dict[str, Any]:
        """Serialise wheel state for crash recovery.

        Returns:
            Dict with all phase-tracking fields.
        """
        return {
            "phase": str(self._phase),
            "current_put_symbol": self._current_put_symbol,
            "current_call_symbol": self._current_call_symbol,
            "entry_premium": self._entry_premium,
            "sl_price": self._sl_price,
            "put_strike": self._put_strike,
            "call_strike": self._call_strike,
            "cost_basis": self._cost_basis,
            "current_expiry": self._current_expiry,
        }

    def restore_from_state(self, state: dict[str, Any]) -> None:
        """Restore wheel state from a previously saved dict.

        Args:
            state: Dict returned by :meth:`get_state_dict` (from
                   :meth:`~flinttrade_engine.strategy.BaseStrategy.load_state`).
        """
        self._phase = WheelPhase(state.get("phase", WheelPhase.WAITING_CSP))
        self._current_put_symbol = state.get("current_put_symbol", "")
        self._current_call_symbol = state.get("current_call_symbol", "")
        self._entry_premium = float(state.get("entry_premium", 0.0))
        self._sl_price = float(state.get("sl_price", 0.0))
        self._put_strike = float(state.get("put_strike", 0.0))
        self._call_strike = float(state.get("call_strike", 0.0))
        self._cost_basis = float(state.get("cost_basis", 0.0))
        self._current_expiry = state.get("current_expiry", "")
        logger.info(
            "WheelStrategy: state restored — phase=%s symbol=%s expiry=%s",
            self._phase, self.symbol, self._current_expiry,
        )

    # ------------------------------------------------------------------
    # Primary cycle entry point
    # ------------------------------------------------------------------

    async def run_cycle(self) -> None:
        """Execute one wheel cycle decision.

        Call at market open (or on a scheduled trigger).  Examines the current
        phase and takes the appropriate action:

        - ``WAITING_CSP`` → sell a cash-secured put.
        - ``CSP_ACTIVE`` → check for assignment or SL; if assigned, transition
          to covered-call phase.
        - ``ASSIGNED`` → sell a covered call.
        - ``CC_ACTIVE`` → check for call-away or expiry.
        - ``CC_EXPIRED`` → restart from ``WAITING_CSP``.
        """
        if not self.is_active:
            logger.warning("WheelStrategy.run_cycle called but strategy is not ACTIVE")
            return

        logger.info("WheelStrategy.run_cycle: phase=%s symbol=%s", self._phase, self.symbol)

        if self._phase == WheelPhase.WAITING_CSP:
            await self._enter_csp()
        elif self._phase == WheelPhase.CSP_ACTIVE:
            await self._check_csp_status()
        elif self._phase == WheelPhase.ASSIGNED:
            await self._enter_cc()
        elif self._phase == WheelPhase.CC_ACTIVE:
            await self._check_cc_status()
        elif self._phase == WheelPhase.CC_EXPIRED:
            await self._transition(WheelPhase.WAITING_CSP, "CC expired — restarting wheel")

    # ------------------------------------------------------------------
    # CSP phase
    # ------------------------------------------------------------------

    async def _enter_csp(self) -> None:
        """Resolve expiry, pick put strike, validate premium, place order."""
        if self._client is None:
            logger.warning("WheelStrategy: no client — skipping CSP entry")
            return

        # Step 1 — nearest expiry
        expiry = await self._get_nearest_expiry()
        if not expiry:
            logger.error("WheelStrategy: could not resolve expiry for %s", self.symbol)
            return
        self._current_expiry = expiry

        # Step 2 — spot price & ATM strike
        spot = await self._get_spot()
        if spot <= 0:
            logger.error("WheelStrategy: spot price unavailable for %s", self.symbol)
            return

        rounded_strike = self._round_strike(spot - self.put_strike_offset)
        self._put_strike = rounded_strike

        # Step 3 — build option symbol
        put_sym = self._build_option_symbol(
            self.symbol, expiry, rounded_strike, "PE"
        )
        self._current_put_symbol = put_sym

        # Step 4 — validate premium
        premium = await self._get_option_ltp(put_sym)
        if premium < MIN_PREMIUM:
            msg = (
                f"Skipped {put_sym} — premium ₹{premium:.2f} < ₹{MIN_PREMIUM:.2f} minimum"
            )
            logger.warning("WheelStrategy: %s", msg)
            await self._send_telegram(f"Wheel: {msg}")
            return

        self._entry_premium = premium
        self._sl_price = round(premium * SL_MULTIPLIER, 1)

        # Step 5 — sell the put
        await self._place_sell(put_sym, qty=self.quantity)

        # Step 6 — place protective SL buy
        await self._place_sl_buy(put_sym, sl_price=self._sl_price, qty=self.quantity)

        await self._transition(
            WheelPhase.CSP_ACTIVE,
            f"CSP entered: {put_sym} sold @ ₹{premium:.2f} | SL @ ₹{self._sl_price:.1f}",
        )

    async def _check_csp_status(self) -> None:
        """Check whether the put has been assigned or hit SL."""
        if not self._current_put_symbol or self._client is None:
            return

        spot = await self._get_spot()
        if spot <= 0:
            return

        # Assignment: spot has dropped below put strike
        if spot < self._put_strike:
            self._cost_basis = self._put_strike - self._entry_premium
            await self._transition(
                WheelPhase.ASSIGNED,
                f"CSP assigned: spot={spot:.2f} < strike={self._put_strike:.2f} | "
                f"cost_basis=₹{self._cost_basis:.2f}",
            )
        else:
            logger.debug(
                "WheelStrategy CSP still active: spot=%.2f strike=%.2f",
                spot, self._put_strike,
            )

    # ------------------------------------------------------------------
    # Covered Call phase
    # ------------------------------------------------------------------

    async def _enter_cc(self) -> None:
        """Enter the covered-call phase after put assignment."""
        if self._client is None:
            logger.warning("WheelStrategy: no client — skipping CC entry")
            return

        expiry = await self._get_nearest_expiry()
        if not expiry:
            return
        self._current_expiry = expiry

        call_strike = self._round_strike(self._cost_basis + self.call_strike_offset)
        self._call_strike = call_strike

        call_sym = self._build_option_symbol(self.symbol, expiry, call_strike, "CE")
        self._current_call_symbol = call_sym

        premium = await self._get_option_ltp(call_sym)
        if premium < MIN_PREMIUM:
            msg = (
                f"Skipped {call_sym} — premium ₹{premium:.2f} < ₹{MIN_PREMIUM:.2f} minimum"
            )
            logger.warning("WheelStrategy: %s", msg)
            await self._send_telegram(f"Wheel: {msg}")
            return

        self._entry_premium = premium
        self._sl_price = round(premium * SL_MULTIPLIER, 1)

        await self._place_sell(call_sym, qty=self.quantity)
        await self._place_sl_buy(call_sym, sl_price=self._sl_price, qty=self.quantity)

        await self._transition(
            WheelPhase.CC_ACTIVE,
            f"CC entered: {call_sym} sold @ ₹{premium:.2f} | "
            f"cost_basis=₹{self._cost_basis:.2f} | SL @ ₹{self._sl_price:.1f}",
        )

    async def _check_cc_status(self) -> None:
        """Check whether the covered call has been called away or expired."""
        if not self._current_call_symbol or self._client is None:
            return

        spot = await self._get_spot()
        if spot <= 0:
            return

        # Called away: spot above call strike
        if spot > self._call_strike:
            await self._transition(
                WheelPhase.CC_EXPIRED,
                f"CC called away: spot={spot:.2f} > call_strike={self._call_strike:.2f} — "
                "restarting wheel",
            )
            self._cost_basis = 0.0
            self._call_strike = 0.0
            self._current_call_symbol = ""
        else:
            logger.debug(
                "WheelStrategy CC still active: spot=%.2f call_strike=%.2f",
                spot, self._call_strike,
            )

    # ------------------------------------------------------------------
    # OpenAlgo API helpers
    # ------------------------------------------------------------------

    async def _get_nearest_expiry(self) -> str:
        """Fetch nearest expiry for the underlying via OpenAlgo.

        Returns:
            Nearest expiry date string (e.g. ``"27-Apr-2025"``),
            or empty string on failure.
        """
        if self._client is None:
            return ""
        try:
            data = await self._client.expiry(
                symbol=self.symbol, exchange=self.exchange, instrumenttype="options"
            )
            expiries: list[str] = (
                data.get("data", {}).get("expiry", [])
                if isinstance(data.get("data"), dict)
                else data.get("data", [])
            )
            if expiries:
                return expiries[0]
            logger.warning("WheelStrategy: empty expiry list for %s", self.symbol)
        except Exception as exc:
            logger.error("WheelStrategy: expiry fetch failed: %s", exc)
        return ""

    async def _get_spot(self) -> float:
        """Fetch spot LTP for the underlying.

        Returns:
            LTP as a float, or ``0.0`` on failure.
        """
        if self._client is None:
            return 0.0
        try:
            quote = await self._client.quotes(symbol=self.symbol, exchange="NSE")
            return float(quote.ltp)
        except Exception as exc:
            logger.error("WheelStrategy: spot price fetch failed: %s", exc)
        return 0.0

    async def _get_option_ltp(self, option_symbol: str) -> float:
        """Fetch LTP for a specific option symbol.

        Args:
            option_symbol: Full OpenAlgo option symbol string.

        Returns:
            LTP as float, or ``0.0`` on failure.
        """
        if self._client is None:
            return 0.0
        try:
            quote = await self._client.quotes(symbol=option_symbol, exchange=self.exchange)
            return float(quote.ltp)
        except Exception as exc:
            logger.error(
                "WheelStrategy: LTP fetch failed for %s: %s", option_symbol, exc
            )
        return 0.0

    async def _place_sell(self, symbol: str, qty: int) -> None:
        """Queue a SELL MARKET intent for the canonical gated runtime.

        Args:
            symbol: Option symbol.
            qty:    Quantity.
        """
        self._pending_orders.append(
            Order(
                symbol=symbol,
                action="SELL",
                exchange=self.exchange,
                pricetype="MARKET",
                product=self.product,
                quantity=str(qty),
                strategy=self.strategy_tag,
            )
        )
        logger.info("WheelStrategy: queued SELL intent for %s qty=%d", symbol, qty)

    async def _place_sl_buy(self, symbol: str, sl_price: float, qty: int) -> None:
        """Queue a protective SL BUY intent above the entry premium.

        The trigger is set 0.5 points below the SL price to accommodate the
        SL-M / SL order mechanics of Indian brokers.

        Args:
            symbol:   Option symbol.
            sl_price: Stop-loss price (30% above entry premium).
            qty:      Quantity.
        """
        trigger = round(sl_price - 0.5, 1)

        self._pending_orders.append(
            Order(
                symbol=symbol,
                action="BUY",
                exchange=self.exchange,
                pricetype="SL",
                product=self.product,
                quantity=str(qty),
                price=str(sl_price),
                trigger_price=str(trigger),
                strategy=self.strategy_tag,
            )
        )
        logger.info(
            "WheelStrategy: queued SL BUY intent for %s @ ₹%.1f (trig ₹%.1f)",
            symbol, sl_price, trigger,
        )

    async def _send_telegram(self, message: str) -> None:
        """Send a Telegram alert via the OpenAlgo client.

        Args:
            message: Alert text.
        """
        if self._client is None:
            logger.info("WheelStrategy (no client): Telegram: %s", message)
            return
        try:
            await self._client.telegram(message)
        except Exception as exc:
            logger.warning("WheelStrategy: Telegram alert failed: %s", exc)

    # ------------------------------------------------------------------
    # State transition helper
    # ------------------------------------------------------------------

    async def _transition(self, new_phase: WheelPhase, message: str) -> None:
        """Transition to a new phase and emit a Telegram alert.

        Args:
            new_phase: Target :class:`WheelPhase`.
            message:   Human-readable description of the transition.
        """
        old_phase = self._phase
        self._phase = new_phase
        logger.info(
            "WheelStrategy: %s → %s | %s | symbol=%s",
            old_phase, new_phase, message, self.symbol,
        )
        await self._send_telegram(
            f"Wheel [{self.symbol}]: {old_phase} → {new_phase}\n{message}"
        )
        self.save_state()

    # ------------------------------------------------------------------
    # Symbol & strike helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _round_strike(price: float, rounding: int = 50) -> float:
        """Round price to the nearest *rounding* (default 50 for NIFTY).

        Args:
            price:    Raw strike candidate.
            rounding: Strike interval.  Use 100 for BANKNIFTY, 50 for NIFTY,
                      10 for single stocks.

        Returns:
            Rounded strike price.
        """
        return round(round(price / rounding) * rounding, 2)

    @staticmethod
    def _build_option_symbol(
        underlying: str,
        expiry: str,
        strike: float,
        opt_type: str,
    ) -> str:
        """Build a generic option symbol string.

        This builds a symbol in the format expected by most OpenAlgo broker
        integrations.  Actual symbol formats vary by broker; adjust this
        method if the broker-specific ``optionsymbol`` endpoint is preferred.

        Args:
            underlying: Underlying symbol (e.g. ``"NIFTY"``).
            expiry:     Expiry string from OpenAlgo (e.g. ``"27-Apr-2025"``).
            strike:     Strike price (e.g. ``22000.0``).
            opt_type:   ``"PE"`` or ``"CE"``.

        Returns:
            Symbol string (e.g. ``"NIFTY27APR2500022000PE"``).
        """
        # Normalise expiry: "27-Apr-2025" → "27APR25"
        parts = expiry.replace("-", " ").split()
        if len(parts) == 3:
            day = parts[0].zfill(2)
            month = parts[1][:3].upper()
            year = parts[2][-2:]
            expiry_tag = f"{day}{month}{year}"
        else:
            expiry_tag = expiry.replace("-", "").upper()

        strike_int = int(strike)
        return f"{underlying.upper()}{expiry_tag}{strike_int}{opt_type.upper()}"


__all__ = ["WheelPhase", "WheelStrategy"]
