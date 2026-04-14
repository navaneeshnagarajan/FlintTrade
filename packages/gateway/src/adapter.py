"""Adapter layer: the ONLY file that imports from infra.openalgo.broker.*.

This module translates between FlintTrade's BrokerSession interface and
OpenAlgo's broker-specific modules. All OpenAlgo coupling is confined here.

Design contract:
- No other file in packages/gateway/ may import from infra.openalgo directly.
- Shims are installed into sys.modules before any broker module is touched.
- The adapter is lazily loaded; import-time cost is zero until first use.
"""

from __future__ import annotations

import importlib
import logging
import sys
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from .exceptions import BrokerNotFoundError
from .models import AuthFlowType, BrokerInfo

# ---------------------------------------------------------------------------
# Path setup — locate OpenAlgo submodule root
# ---------------------------------------------------------------------------

logger = logging.getLogger("flinttrade.gateway.adapter")

_REPO_ROOT = Path(__file__).resolve().parents[3]
_OPENALGO_ROOT = _REPO_ROOT / "infra" / "openalgo"
_OPENALGO_ROOT_STR = str(_OPENALGO_ROOT)

# ---------------------------------------------------------------------------
# Bootstrap — install shims before any broker module is imported
# ---------------------------------------------------------------------------

_bootstrapped: bool = False


def _bootstrap_openalgo_imports() -> None:
    """Install shims and add OpenAlgo root to sys.path.

    Safe to call multiple times; subsequent calls are no-ops.
    Shims intercept OpenAlgo's internal ``database.*`` and ``utils.*`` imports
    and redirect them to FlintTrade's own implementations.
    """
    global _bootstrapped
    if _bootstrapped:
        return

    # Import shim modules via absolute imports (src/ is on sys.path).
    from shims import auth_db_shim, config_shim, logging_shim, token_db_shim

    # Add OpenAlgo root so broker.<name>.* imports resolve correctly.
    if _OPENALGO_ROOT_STR not in sys.path:
        sys.path.insert(0, _OPENALGO_ROOT_STR)

    # Patch OpenAlgo's internal modules with our shims.  setdefault ensures
    # we never overwrite a module that was already imported (idempotent).
    sys.modules.setdefault("database.token_db", token_db_shim)  # type: ignore[arg-type]
    sys.modules.setdefault("database.auth_db", auth_db_shim)  # type: ignore[arg-type]
    sys.modules.setdefault("utils.logging", logging_shim)  # type: ignore[arg-type]
    sys.modules.setdefault("utils.config", config_shim)  # type: ignore[arg-type]

    _bootstrapped = True


# ---------------------------------------------------------------------------
# BrokerAdapter Protocol — structural typing for all wrapped adapters
# ---------------------------------------------------------------------------


@runtime_checkable
class BrokerAdapter(Protocol):
    """Structural interface satisfied by every _WrappedBrokerAdapter.

    Each method receives ``auth_token`` as its last positional argument so the
    adapter can inject it into OpenAlgo's broker-level API functions without
    mutating global state between concurrent sessions.
    """

    def authenticate(self, *args: Any, auth_token: str = "") -> Any:
        """Initiate or complete broker authentication."""
        ...

    def place_order(self, order: dict[str, Any], auth_token: str = "") -> Any:
        """Place a regular order."""
        ...

    def modify_order(self, order: dict[str, Any], auth_token: str = "") -> Any:
        """Modify an existing open order."""
        ...

    def cancel_order(self, order_id: str, auth_token: str = "") -> Any:
        """Cancel a single order by ID."""
        ...

    def cancel_all_orders(self, auth_token: str = "") -> Any:
        """Cancel all open orders for the account."""
        ...

    def close_position(self, symbol: str, exchange: str, auth_token: str = "") -> Any:
        """Close an open position."""
        ...

    def place_options_order(self, order: dict[str, Any], auth_token: str = "") -> Any:
        """Place an options-specific order."""
        ...

    def get_positions(self, auth_token: str = "") -> Any:
        """Fetch current open positions."""
        ...

    def get_orders(self, auth_token: str = "") -> Any:
        """Fetch the order book."""
        ...

    def get_trades(self, auth_token: str = "") -> Any:
        """Fetch the trade book."""
        ...

    def get_holdings(self, auth_token: str = "") -> Any:
        """Fetch long-term holdings."""
        ...

    def get_funds(self, auth_token: str = "") -> Any:
        """Fetch account funds / margin summary."""
        ...

    def get_margin(self, order: dict[str, Any], auth_token: str = "") -> Any:
        """Calculate margin required for an order."""
        ...

    def get_quotes(self, symbol: str, exchange: str, auth_token: str = "") -> Any:
        """Fetch live quote for a symbol."""
        ...

    def get_depth(self, symbol: str, exchange: str, auth_token: str = "") -> Any:
        """Fetch market depth (order book levels) for a symbol."""
        ...

    def get_history(
        self,
        symbol: str,
        exchange: str,
        interval: str,
        start: str,
        end: str,
        auth_token: str = "",
    ) -> Any:
        """Fetch OHLCV history for a symbol."""
        ...

    def search_symbols(self, query: str, exchange: str, auth_token: str = "") -> Any:
        """Search for symbols matching a query string."""
        ...


# ---------------------------------------------------------------------------
# Internal wrapped adapter
# ---------------------------------------------------------------------------


class _WrappedBrokerAdapter:
    """Concrete adapter wrapping OpenAlgo broker sub-modules.

    Holds lazily-imported references to the four OpenAlgo API modules for a
    single broker and exposes them through the BrokerAdapter interface.

    Args:
        broker_name: Canonical broker identifier (e.g. ``"zerodha"``).
        auth_mod: Imported ``broker.<name>.api.auth_api`` module.
        order_mod: Imported ``broker.<name>.api.order_api`` module.
        data_mod: Imported ``broker.<name>.api.data`` module.
        funds_mod: Imported ``broker.<name>.api.funds`` module.
    """

    def __init__(
        self,
        broker_name: str,
        auth_mod: Any,
        order_mod: Any,
        data_mod: Any,
        funds_mod: Any,
    ) -> None:
        self._broker = broker_name
        self._auth = auth_mod
        self._order = order_mod
        self._data = data_mod
        self._funds = funds_mod

    # -- Auth ----------------------------------------------------------------

    def authenticate(self, *args: Any, auth_token: str = "") -> Any:
        """Delegate to broker auth_api.authenticate_broker."""
        return self._auth.authenticate_broker(*args)

    # -- Orders --------------------------------------------------------------

    def place_order(self, order: dict[str, Any], auth_token: str = "") -> Any:
        """Delegate to broker order_api.place_order."""
        return self._order.place_order(order, auth_token)

    def modify_order(self, order: dict[str, Any], auth_token: str = "") -> Any:
        """Delegate to broker order_api.modify_order."""
        return self._order.modify_order(order, auth_token)

    def cancel_order(self, order_id: str, auth_token: str = "") -> Any:
        """Delegate to broker order_api.cancel_order."""
        return self._order.cancel_order(order_id, auth_token)

    def cancel_all_orders(self, auth_token: str = "") -> Any:
        """Delegate to broker order_api.cancel_all_orders."""
        return self._order.cancel_all_orders(auth_token)

    def close_position(self, symbol: str, exchange: str, auth_token: str = "") -> Any:
        """Delegate to broker order_api.close_position."""
        return self._order.close_position(symbol, exchange, auth_token)

    def place_options_order(self, order: dict[str, Any], auth_token: str = "") -> Any:
        """Delegate to broker order_api.place_options_order."""
        return self._order.place_options_order(order, auth_token)

    # -- Account data --------------------------------------------------------

    def get_positions(self, auth_token: str = "") -> Any:
        """Delegate to broker order_api.get_positions."""
        return self._order.get_positions(auth_token)

    def get_orders(self, auth_token: str = "") -> Any:
        """Delegate to broker order_api.get_orders."""
        return self._order.get_orders(auth_token)

    def get_trades(self, auth_token: str = "") -> Any:
        """Delegate to broker order_api.get_trades."""
        return self._order.get_trades(auth_token)

    def get_holdings(self, auth_token: str = "") -> Any:
        """Delegate to broker order_api.get_holdings."""
        return self._order.get_holdings(auth_token)

    def get_funds(self, auth_token: str = "") -> Any:
        """Delegate to broker funds.get_funds."""
        return self._funds.get_funds(auth_token)

    def get_margin(self, order: dict[str, Any], auth_token: str = "") -> Any:
        """Delegate to broker funds.get_margin."""
        return self._funds.get_margin(order, auth_token)

    # -- Market data ---------------------------------------------------------

    def get_quotes(self, symbol: str, exchange: str, auth_token: str = "") -> Any:
        """Delegate to broker data.get_quotes."""
        return self._data.get_quotes(symbol, exchange, auth_token)

    def get_depth(self, symbol: str, exchange: str, auth_token: str = "") -> Any:
        """Delegate to broker data.get_depth."""
        return self._data.get_depth(symbol, exchange, auth_token)

    def get_history(
        self,
        symbol: str,
        exchange: str,
        interval: str,
        start: str,
        end: str,
        auth_token: str = "",
    ) -> Any:
        """Delegate to broker data.get_history."""
        return self._data.get_history(symbol, exchange, interval, start, end, auth_token)

    def search_symbols(self, query: str, exchange: str, auth_token: str = "") -> Any:
        """Delegate to broker data.search_symbols."""
        return self._data.search_symbols(query, exchange, auth_token)


# ---------------------------------------------------------------------------
# Broker catalog — all 31 entries (30 live + 1 sandbox)
# ---------------------------------------------------------------------------

BROKER_CATALOG: dict[str, BrokerInfo] = {
    # ---- OAuth redirect flow (10) ----------------------------------------
    "zerodha": BrokerInfo(
        name="zerodha",
        display_name="Zerodha",
        auth_flow=AuthFlowType.oauth_redirect,
        exchanges=["NSE", "BSE", "NFO", "BFO", "CDS", "MCX"],
    ),
    "fyers": BrokerInfo(
        name="fyers",
        display_name="Fyers",
        auth_flow=AuthFlowType.oauth_redirect,
        exchanges=["NSE", "BSE", "NFO", "BFO", "CDS", "MCX"],
    ),
    "flattrade": BrokerInfo(
        name="flattrade",
        display_name="Flattrade",
        auth_flow=AuthFlowType.oauth_redirect,
        exchanges=["NSE", "BSE", "NFO", "BFO", "CDS", "MCX"],
    ),
    "pocketful": BrokerInfo(
        name="pocketful",
        display_name="Pocketful",
        auth_flow=AuthFlowType.oauth_redirect,
        exchanges=["NSE", "BSE", "NFO", "BFO", "CDS", "MCX"],
    ),
    "paytm": BrokerInfo(
        name="paytm",
        display_name="Paytm Money",
        auth_flow=AuthFlowType.oauth_redirect,
        exchanges=["NSE", "BSE", "NFO", "CDS"],
    ),
    "dhan": BrokerInfo(
        name="dhan",
        display_name="Dhan",
        auth_flow=AuthFlowType.oauth_redirect,
        exchanges=["NSE", "BSE", "NFO", "BFO", "CDS", "MCX"],
    ),
    "aliceblue": BrokerInfo(
        name="aliceblue",
        display_name="AliceBlue",
        auth_flow=AuthFlowType.oauth_redirect,
        exchanges=["NSE", "BSE", "NFO", "BFO", "CDS", "MCX"],
    ),
    "upstox": BrokerInfo(
        name="upstox",
        display_name="Upstox",
        auth_flow=AuthFlowType.oauth_redirect,
        exchanges=["NSE", "BSE", "NFO", "BFO", "CDS", "MCX"],
    ),
    "compositedge": BrokerInfo(
        name="compositedge",
        display_name="Compositedge",
        auth_flow=AuthFlowType.oauth_redirect,
        exchanges=["NSE", "BSE", "NFO", "BFO", "CDS", "MCX"],
    ),
    "rmoney": BrokerInfo(
        name="rmoney",
        display_name="RMoney",
        auth_flow=AuthFlowType.oauth_redirect,
        exchanges=["NSE", "BSE", "NFO", "BFO", "CDS", "MCX"],
    ),
    # ---- TOTP form flow (10) ---------------------------------------------
    "angel": BrokerInfo(
        name="angel",
        display_name="Angel One",
        auth_flow=AuthFlowType.totp_form,
        exchanges=["NSE", "BSE", "NFO", "BFO", "CDS", "MCX"],
    ),
    "fivepaisa": BrokerInfo(
        name="fivepaisa",
        display_name="5paisa",
        auth_flow=AuthFlowType.totp_form,
        exchanges=["NSE", "BSE", "NFO", "BFO", "CDS", "MCX"],
    ),
    "zebu": BrokerInfo(
        name="zebu",
        display_name="Zebu",
        auth_flow=AuthFlowType.totp_form,
        exchanges=["NSE", "BSE", "NFO", "BFO", "CDS", "MCX"],
    ),
    "shoonya": BrokerInfo(
        name="shoonya",
        display_name="Shoonya",
        auth_flow=AuthFlowType.totp_form,
        exchanges=["NSE", "BSE", "NFO", "BFO", "CDS", "MCX"],
    ),
    "firstock": BrokerInfo(
        name="firstock",
        display_name="Firstock",
        auth_flow=AuthFlowType.totp_form,
        exchanges=["NSE", "BSE", "NFO", "BFO", "CDS", "MCX"],
    ),
    "tradejini": BrokerInfo(
        name="tradejini",
        display_name="Tradejini",
        auth_flow=AuthFlowType.totp_form,
        exchanges=["NSE", "BSE", "NFO", "BFO", "CDS", "MCX"],
    ),
    "mstock": BrokerInfo(
        name="mstock",
        display_name="mStock",
        auth_flow=AuthFlowType.totp_form,
        exchanges=["NSE", "BSE", "NFO", "BFO", "CDS", "MCX"],
    ),
    "kotak": BrokerInfo(
        name="kotak",
        display_name="Kotak Securities",
        auth_flow=AuthFlowType.totp_form,
        exchanges=["NSE", "BSE", "NFO", "BFO", "CDS", "MCX"],
    ),
    "motilal": BrokerInfo(
        name="motilal",
        display_name="Motilal Oswal",
        auth_flow=AuthFlowType.totp_form,
        exchanges=["NSE", "BSE", "NFO", "BFO", "CDS", "MCX"],
    ),
    "nubra": BrokerInfo(
        name="nubra",
        display_name="Nubra",
        auth_flow=AuthFlowType.totp_form,
        exchanges=["NSE", "BSE", "NFO", "BFO", "CDS", "MCX"],
    ),
    # ---- OTP multistep flow (1) ------------------------------------------
    "samco": BrokerInfo(
        name="samco",
        display_name="Samco",
        # Samco uses a 4-step OTP 2FA flow, NOT a TOTP authenticator app:
        #   1. Request OTP → sent to registered mobile
        #   2. Submit OTP → secret API key e-mailed to user (one-time setup)
        #   3. Generate access token from secret key (daily, via secret key)
        #   4. Login with access token + password → session token
        # The secret_api_key and IP registration fields are stored encrypted
        # in the CredentialStore alongside the standard client credentials.
        auth_flow=AuthFlowType.otp_multistep,
        exchanges=["NSE", "BSE", "NFO", "CDS", "MCX"],
        aux_params=["secret_api_key", "primary_ip", "secondary_ip"],
    ),
    # ---- API key direct flow (9) -----------------------------------------
    "deltaexchange": BrokerInfo(
        name="deltaexchange",
        display_name="Delta Exchange",
        auth_flow=AuthFlowType.api_key_direct,
        exchanges=["CRYPTO"],
    ),
    "groww": BrokerInfo(
        name="groww",
        display_name="Groww",
        auth_flow=AuthFlowType.api_key_direct,
        exchanges=["NSE", "BSE", "NFO", "BFO"],
    ),
    "wisdom": BrokerInfo(
        name="wisdom",
        display_name="Wisdom Capital (XTS)",
        auth_flow=AuthFlowType.api_key_direct,
        exchanges=["NSE", "BSE", "NFO", "BFO", "CDS", "MCX"],
    ),
    "ibulls": BrokerInfo(
        name="ibulls",
        display_name="IBulls",
        auth_flow=AuthFlowType.api_key_direct,
        exchanges=["NSE", "BSE", "NFO", "BFO", "CDS", "MCX"],
    ),
    "iifl": BrokerInfo(
        name="iifl",
        display_name="IIFL",
        auth_flow=AuthFlowType.api_key_direct,
        exchanges=["NSE", "BSE", "NFO", "BFO", "CDS", "MCX"],
    ),
    "jainamxts": BrokerInfo(
        name="jainamxts",
        display_name="Jainam XTS",
        auth_flow=AuthFlowType.api_key_direct,
        exchanges=["NSE", "BSE", "NFO", "BFO", "CDS", "MCX"],
    ),
    "indmoney": BrokerInfo(
        name="indmoney",
        display_name="INDmoney",
        auth_flow=AuthFlowType.api_key_direct,
        exchanges=["NSE", "BSE", "NFO", "BFO"],
    ),
    "fivepaisaxts": BrokerInfo(
        name="fivepaisaxts",
        display_name="5paisa XTS",
        auth_flow=AuthFlowType.api_key_direct,
        exchanges=["NSE", "BSE", "NFO", "BFO", "CDS", "MCX"],
    ),
    # ---- OTP SMS flow (1) ------------------------------------------------
    "definedge": BrokerInfo(
        name="definedge",
        display_name="DefinedGe Securities",
        auth_flow=AuthFlowType.otp_sms,
        exchanges=["NSE", "BSE", "NFO", "BFO", "CDS", "MCX"],
    ),
    # ---- Sandbox (1) -----------------------------------------------------
    "dhan_sandbox": BrokerInfo(
        name="dhan_sandbox",
        display_name="Dhan Sandbox",
        auth_flow=AuthFlowType.oauth_redirect,
        exchanges=["NSE", "BSE", "NFO", "BFO", "CDS", "MCX"],
        is_sandbox=True,
    ),
}


# ---------------------------------------------------------------------------
# Public factory functions
# ---------------------------------------------------------------------------


def load_broker_adapter(broker_name: str) -> _WrappedBrokerAdapter:
    """Dynamically load and wrap an OpenAlgo broker adapter.

    This is the sole entry-point that imports from OpenAlgo's broker modules.
    All sys.path manipulation and shim installation happens inside
    ``_bootstrap_openalgo_imports()`` which is always called first.

    Args:
        broker_name: Canonical broker name (must exist in BROKER_CATALOG).

    Returns:
        A :class:`_WrappedBrokerAdapter` satisfying the
        :class:`BrokerAdapter` protocol.

    Raises:
        BrokerNotFoundError: If ``broker_name`` is not in BROKER_CATALOG.
        ImportError: If the broker's OpenAlgo module cannot be imported
            (e.g. submodule not checked out).

    Example::

        adapter = load_broker_adapter("zerodha")
        token, err = adapter.authenticate("request_token_from_oauth_callback")
    """
    if broker_name not in BROKER_CATALOG:
        raise BrokerNotFoundError(
            f"Broker '{broker_name}' not found in catalog. "
            f"Available brokers: {sorted(BROKER_CATALOG)}"
        )

    _bootstrap_openalgo_imports()

    base = f"broker.{broker_name}.api"
    auth_mod = importlib.import_module(f"{base}.auth_api")
    order_mod = importlib.import_module(f"{base}.order_api")
    data_mod = importlib.import_module(f"{base}.data")
    funds_mod = importlib.import_module(f"{base}.funds")

    return _WrappedBrokerAdapter(
        broker_name=broker_name,
        auth_mod=auth_mod,
        order_mod=order_mod,
        data_mod=data_mod,
        funds_mod=funds_mod,
    )


def load_streaming_adapter(broker_name: str) -> Any:
    """Dynamically load the OpenAlgo streaming adapter for a broker.

    Args:
        broker_name: Canonical broker name (must exist in BROKER_CATALOG).

    Returns:
        The imported streaming adapter module.

    Raises:
        BrokerNotFoundError: If ``broker_name`` is not in BROKER_CATALOG.
        ImportError: If the streaming module cannot be imported.

    Example::

        streaming = load_streaming_adapter("zerodha")
        # streaming.zerodha_adapter exposes the adapter class
    """
    if broker_name not in BROKER_CATALOG:
        raise BrokerNotFoundError(
            f"Broker '{broker_name}' not found in catalog. "
            f"Available brokers: {sorted(BROKER_CATALOG)}"
        )

    _bootstrap_openalgo_imports()

    streaming_module = f"broker.{broker_name}.streaming.{broker_name}_adapter"
    return importlib.import_module(streaming_module)
