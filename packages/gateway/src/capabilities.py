"""Broker capability registry for FlintTrade.

Provides a structured record of what each Indian broker supports so that
the UI, order router, and screener can make runtime decisions without
hardcoding broker-specific conditionals throughout the codebase.

Usage::

    from capabilities import CapabilityRegistry, REGISTRY

    caps = REGISTRY.get("zerodha")
    if caps and caps.supports_bracket_orders:
        ...

    for caps in REGISTRY.all():
        print(caps.broker_name, caps.supports_websocket)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import ClassVar


@dataclass
class BrokerCapabilities:
    """Declares what a single broker supports.

    All boolean fields default to ``False`` so that adding a new capability
    field does not silently break existing broker entries — they simply
    advertise ``False`` until explicitly set.

    Args:
        broker_name: Canonical lower-case broker identifier.
        supports_market_orders: Broker accepts MARKET order type.
        supports_limit_orders: Broker accepts LIMIT order type.
        supports_sl_orders: Broker accepts SL (stop-loss limit) order type.
        supports_sl_m_orders: Broker accepts SL-M (stop-loss market) order type.
        supports_bracket_orders: Broker accepts BO (bracket order) type.
        supports_cover_orders: Broker accepts CO (cover order) type.
        supports_basket_orders: Broker accepts multi-leg basket orders.
        supports_options: Broker supports options (NFO/BFO) trading.
        supports_futures: Broker supports futures (NFO/BFO/MCX) trading.
        supports_commodities: Broker supports MCX commodity trading.
        supports_currency: Broker supports CDS currency derivatives.
        supports_equity: Broker supports equity (NSE/BSE) trading.
        supports_mis: Broker supports MIS (intraday) product type.
        supports_cnc: Broker supports CNC (delivery) product type.
        supports_nrml: Broker supports NRML (carry-forward) product type.
        supports_websocket: Broker provides a real-time WebSocket feed.
        supports_multi_quote: Broker returns multiple symbol quotes in one call.
        supports_multi_option_greeks: Broker provides batch option greeks.
        order_rate_limit_per_sec: Maximum order requests per second.
        quote_rate_limit_per_sec: Maximum quote requests per second.
    """

    broker_name: str
    supports_market_orders: bool = False
    supports_limit_orders: bool = False
    supports_sl_orders: bool = False
    supports_sl_m_orders: bool = False
    supports_bracket_orders: bool = False
    supports_cover_orders: bool = False
    supports_basket_orders: bool = False
    supports_options: bool = False
    supports_futures: bool = False
    supports_commodities: bool = False
    supports_currency: bool = False
    supports_equity: bool = False
    supports_mis: bool = False
    supports_cnc: bool = False
    supports_nrml: bool = False
    supports_websocket: bool = False
    supports_multi_quote: bool = False
    supports_multi_option_greeks: bool = False
    order_rate_limit_per_sec: int = 10
    quote_rate_limit_per_sec: int = 50


class CapabilityRegistry:
    """Lookup broker capabilities by name.

    The registry is pre-seeded with entries for all supported Indian brokers.
    Additional or overriding entries can be added at runtime via
    :meth:`register`.

    Example::

        registry = CapabilityRegistry()
        caps = registry.get("zerodha")
        all_caps = registry.all()
    """

    _instance: ClassVar[CapabilityRegistry | None] = None

    def __init__(self) -> None:
        self._store: dict[str, BrokerCapabilities] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def register(self, caps: BrokerCapabilities) -> None:
        """Add or replace the capabilities entry for a broker.

        Args:
            caps: :class:`BrokerCapabilities` instance to register.
        """
        self._store[caps.broker_name] = caps

    def get(self, broker_name: str) -> BrokerCapabilities | None:
        """Return the capabilities for *broker_name*, or ``None``.

        Args:
            broker_name: Canonical lower-case broker identifier.

        Returns:
            :class:`BrokerCapabilities` or ``None`` if not found.
        """
        return self._store.get(broker_name)

    def all(self) -> list[BrokerCapabilities]:
        """Return all registered capability entries.

        Returns:
            List of :class:`BrokerCapabilities` sorted by broker name.
        """
        return sorted(self._store.values(), key=lambda c: c.broker_name)

    def broker_names(self) -> list[str]:
        """Return a sorted list of all registered broker names.

        Returns:
            List of broker name strings.
        """
        return sorted(self._store.keys())


# ---------------------------------------------------------------------------
# Pre-seeded registry — 11 Indian brokers
# ---------------------------------------------------------------------------


def _build_default_registry() -> CapabilityRegistry:
    """Build and return the default capability registry seeded with 11 brokers.

    Returns:
        :class:`CapabilityRegistry` pre-populated with known Indian brokers.
    """
    reg = CapabilityRegistry()

    # -- Zerodha (Kite) ---------------------------------------------------
    reg.register(BrokerCapabilities(
        broker_name="zerodha",
        supports_market_orders=True,
        supports_limit_orders=True,
        supports_sl_orders=True,
        supports_sl_m_orders=True,
        supports_bracket_orders=True,
        supports_cover_orders=True,
        supports_basket_orders=True,
        supports_options=True,
        supports_futures=True,
        supports_commodities=True,
        supports_currency=True,
        supports_equity=True,
        supports_mis=True,
        supports_cnc=True,
        supports_nrml=True,
        supports_websocket=True,
        supports_multi_quote=True,
        supports_multi_option_greeks=False,
        order_rate_limit_per_sec=10,
        quote_rate_limit_per_sec=50,
    ))

    # -- Angel One (SmartAPI) ---------------------------------------------
    reg.register(BrokerCapabilities(
        broker_name="angel",
        supports_market_orders=True,
        supports_limit_orders=True,
        supports_sl_orders=True,
        supports_sl_m_orders=True,
        supports_bracket_orders=False,
        supports_cover_orders=False,
        supports_basket_orders=True,
        supports_options=True,
        supports_futures=True,
        supports_commodities=True,
        supports_currency=True,
        supports_equity=True,
        supports_mis=True,
        supports_cnc=True,
        supports_nrml=True,
        supports_websocket=True,
        supports_multi_quote=True,
        supports_multi_option_greeks=True,
        order_rate_limit_per_sec=10,
        quote_rate_limit_per_sec=50,
    ))

    # -- Upstox -----------------------------------------------------------
    reg.register(BrokerCapabilities(
        broker_name="upstox",
        supports_market_orders=True,
        supports_limit_orders=True,
        supports_sl_orders=True,
        supports_sl_m_orders=True,
        supports_bracket_orders=False,
        supports_cover_orders=False,
        supports_basket_orders=True,
        supports_options=True,
        supports_futures=True,
        supports_commodities=True,
        supports_currency=True,
        supports_equity=True,
        supports_mis=True,
        supports_cnc=True,
        supports_nrml=True,
        supports_websocket=True,
        supports_multi_quote=True,
        supports_multi_option_greeks=True,
        order_rate_limit_per_sec=10,
        quote_rate_limit_per_sec=50,
    ))

    # -- ICICI Direct (Breeze) --------------------------------------------
    reg.register(BrokerCapabilities(
        broker_name="icici",
        supports_market_orders=True,
        supports_limit_orders=True,
        supports_sl_orders=True,
        supports_sl_m_orders=False,
        supports_bracket_orders=False,
        supports_cover_orders=False,
        supports_basket_orders=False,
        supports_options=True,
        supports_futures=True,
        supports_commodities=True,
        supports_currency=True,
        supports_equity=True,
        supports_mis=True,
        supports_cnc=True,
        supports_nrml=True,
        supports_websocket=True,
        supports_multi_quote=False,
        supports_multi_option_greeks=False,
        order_rate_limit_per_sec=5,
        quote_rate_limit_per_sec=20,
    ))

    # -- Fyers ------------------------------------------------------------
    reg.register(BrokerCapabilities(
        broker_name="fyers",
        supports_market_orders=True,
        supports_limit_orders=True,
        supports_sl_orders=True,
        supports_sl_m_orders=True,
        supports_bracket_orders=True,
        supports_cover_orders=True,
        supports_basket_orders=True,
        supports_options=True,
        supports_futures=True,
        supports_commodities=True,
        supports_currency=True,
        supports_equity=True,
        supports_mis=True,
        supports_cnc=True,
        supports_nrml=True,
        supports_websocket=True,
        supports_multi_quote=True,
        supports_multi_option_greeks=False,
        order_rate_limit_per_sec=10,
        quote_rate_limit_per_sec=50,
    ))

    # -- Dhan -------------------------------------------------------------
    reg.register(BrokerCapabilities(
        broker_name="dhan",
        supports_market_orders=True,
        supports_limit_orders=True,
        supports_sl_orders=True,
        supports_sl_m_orders=True,
        supports_bracket_orders=False,
        supports_cover_orders=False,
        supports_basket_orders=True,
        supports_options=True,
        supports_futures=True,
        supports_commodities=True,
        supports_currency=True,
        supports_equity=True,
        supports_mis=True,
        supports_cnc=True,
        supports_nrml=True,
        supports_websocket=True,
        supports_multi_quote=True,
        supports_multi_option_greeks=True,
        order_rate_limit_per_sec=10,
        quote_rate_limit_per_sec=50,
    ))

    # -- Motilal Oswal (MO Investor / MOSL) -------------------------------
    reg.register(BrokerCapabilities(
        broker_name="motilal",
        supports_market_orders=True,
        supports_limit_orders=True,
        supports_sl_orders=True,
        supports_sl_m_orders=True,
        supports_bracket_orders=False,
        supports_cover_orders=False,
        supports_basket_orders=True,
        supports_options=True,
        supports_futures=True,
        supports_commodities=True,
        supports_currency=False,
        supports_equity=True,
        supports_mis=True,
        supports_cnc=True,
        supports_nrml=True,
        supports_websocket=True,
        supports_multi_quote=False,
        supports_multi_option_greeks=False,
        order_rate_limit_per_sec=5,
        quote_rate_limit_per_sec=20,
    ))

    # -- IIFL Securities --------------------------------------------------
    reg.register(BrokerCapabilities(
        broker_name="iifl",
        supports_market_orders=True,
        supports_limit_orders=True,
        supports_sl_orders=True,
        supports_sl_m_orders=False,
        supports_bracket_orders=False,
        supports_cover_orders=False,
        supports_basket_orders=False,
        supports_options=True,
        supports_futures=True,
        supports_commodities=True,
        supports_currency=True,
        supports_equity=True,
        supports_mis=True,
        supports_cnc=True,
        supports_nrml=True,
        supports_websocket=False,
        supports_multi_quote=False,
        supports_multi_option_greeks=False,
        order_rate_limit_per_sec=5,
        quote_rate_limit_per_sec=20,
    ))

    # -- Samco (StockNote) ------------------------------------------------
    reg.register(BrokerCapabilities(
        broker_name="samco",
        supports_market_orders=True,
        supports_limit_orders=True,
        supports_sl_orders=True,
        supports_sl_m_orders=True,
        supports_bracket_orders=True,
        supports_cover_orders=True,
        supports_basket_orders=False,
        supports_options=True,
        supports_futures=True,
        supports_commodities=True,
        supports_currency=True,
        supports_equity=True,
        supports_mis=True,
        supports_cnc=True,
        supports_nrml=True,
        supports_websocket=True,
        supports_multi_quote=False,
        supports_multi_option_greeks=False,
        order_rate_limit_per_sec=5,
        quote_rate_limit_per_sec=20,
    ))

    # -- Shoonya (Finvasia) -----------------------------------------------
    reg.register(BrokerCapabilities(
        broker_name="shoonya",
        supports_market_orders=True,
        supports_limit_orders=True,
        supports_sl_orders=True,
        supports_sl_m_orders=True,
        supports_bracket_orders=False,
        supports_cover_orders=False,
        supports_basket_orders=True,
        supports_options=True,
        supports_futures=True,
        supports_commodities=True,
        supports_currency=True,
        supports_equity=True,
        supports_mis=True,
        supports_cnc=True,
        supports_nrml=True,
        supports_websocket=True,
        supports_multi_quote=True,
        supports_multi_option_greeks=False,
        order_rate_limit_per_sec=10,
        quote_rate_limit_per_sec=50,
    ))

    # -- Tradejini --------------------------------------------------------
    reg.register(BrokerCapabilities(
        broker_name="tradejini",
        supports_market_orders=True,
        supports_limit_orders=True,
        supports_sl_orders=True,
        supports_sl_m_orders=True,
        supports_bracket_orders=True,
        supports_cover_orders=True,
        supports_basket_orders=False,
        supports_options=True,
        supports_futures=True,
        supports_commodities=True,
        supports_currency=True,
        supports_equity=True,
        supports_mis=True,
        supports_cnc=True,
        supports_nrml=True,
        supports_websocket=True,
        supports_multi_quote=False,
        supports_multi_option_greeks=False,
        order_rate_limit_per_sec=5,
        quote_rate_limit_per_sec=20,
    ))

    return reg


#: Module-level default registry — import and use directly.
REGISTRY: CapabilityRegistry = _build_default_registry()
