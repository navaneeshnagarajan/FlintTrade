"""Adapter layer: the ONLY file that imports OpenAlgo's broker.* modules.

This module translates between FlintTrade's BrokerSession interface and
OpenAlgo's broker-specific modules. All OpenAlgo coupling is confined here.

Design contract:
- No other file in packages/integrations/gateway/ may import OpenAlgo modules directly.
- Shims are installed into sys.modules before any broker module is touched.
- The adapter is lazily loaded; import-time cost is zero until first use.

Path resolution: OpenAlgo is an external test-dep, not bundled with FlintTrade.
For local development it is cloned to ``.local/external/openalgo/`` via
``scripts/setup-test-deps.sh``. The legacy submodule path ``infra/openalgo/``
is kept as a fallback so older checkouts still work during the transition.
"""

from __future__ import annotations

import importlib
import logging
import sys
import inspect
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from .exceptions import BrokerNotFoundError
from .models import AuthFlowType, BrokerInfo

# ---------------------------------------------------------------------------
# Path setup — locate OpenAlgo external test-dep root
# ---------------------------------------------------------------------------

logger = logging.getLogger("flinttrade.gateway.adapter")

_REPO_ROOT = Path(__file__).resolve().parents[5]


def _resolve_openalgo_root() -> Path:
    """Return the OpenAlgo source tree path, preferring the new location.

    OpenAlgo used to be a git submodule under ``infra/openalgo/``; it now
    lives under ``.local/external/openalgo/`` (cloned by
    ``scripts/setup-test-deps.sh``). We check the new location first, fall
    back to the legacy submodule path if present, and finally return the
    new location even when nothing exists so error messages stay accurate.
    """
    new = _REPO_ROOT / ".local" / "external" / "openalgo"
    if (new / "app.py").is_file() or (new / "broker").is_dir():
        return new
    legacy = _REPO_ROOT / "infra" / "openalgo"
    if (legacy / "app.py").is_file() or (legacy / "broker").is_dir():
        return legacy
    return new


_OPENALGO_ROOT = _resolve_openalgo_root()
_OPENALGO_ROOT_STR = str(_OPENALGO_ROOT)


def _split_exchange_symbol(raw: Any, default_exchange: str = "NSE") -> tuple[str, str]:
    """Return ``(exchange, symbol)`` from either ``EXCHANGE:SYMBOL`` or a bare symbol."""
    text = str(raw or "").strip()
    if ":" in text:
        exchange, symbol = text.split(":", 1)
        return exchange.strip().upper() or default_exchange, symbol.strip()
    return default_exchange, text


def _supports_positional_call(method: Any, argc: int) -> bool | None:
    """Whether ``method`` can receive ``argc`` positional args, or ``None`` if unknown."""
    try:
        signature = inspect.signature(method)
    except (TypeError, ValueError):
        return None

    positional = [
        p
        for p in signature.parameters.values()
        if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)
    ]
    if any(p.kind is p.VAR_POSITIONAL for p in signature.parameters.values()):
        return True
    required = [p for p in positional if p.default is p.empty]
    return len(required) <= argc <= len(positional)

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

    # Import shim modules from the installed flinttrade_gateway package.
    from flinttrade_gateway.shims import auth_db_shim, config_shim, logging_shim, token_db_shim

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

    def get_quotes(self, symbols: list[str], auth_token: str = "") -> Any:
        """Fetch live quotes for one or more symbols."""
        ...

    def get_depth(self, symbol: str, auth_token: str = "") -> Any:
        """Fetch market depth (order book levels) for a symbol."""
        ...

    def get_history(self, params: dict[str, Any], auth_token: str = "") -> Any:
        """Fetch OHLCV history for a symbol."""
        ...

    def get_option_chain(self, params: dict[str, Any], auth_token: str = "") -> Any:
        """Fetch option-chain data for an underlying."""
        ...

    def search_symbols(self, query: str, auth_token: str = "") -> Any:
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

    def get_quotes(self, symbols: list[str] | str, auth_token: str = "") -> Any:
        """Delegate to broker data.get_quotes for one or more symbols.

        ``BrokerSession.get_quotes`` passes a list, while OpenAlgo broker modules
        expose a single-symbol ``get_quotes(symbol, exchange, token)`` function.
        Preserve the single-symbol response shape for one item and return a
        keyed mapping for multi-symbol callers.
        """
        raw_symbols = symbols if isinstance(symbols, list) else [symbols]
        if len(raw_symbols) == 1:
            exchange, symbol = _split_exchange_symbol(raw_symbols[0])
            return self._data.get_quotes(symbol, exchange, auth_token)
        quotes: dict[str, Any] = {}
        for raw in raw_symbols:
            exchange, symbol = _split_exchange_symbol(raw)
            quotes[str(raw)] = self._data.get_quotes(symbol, exchange, auth_token)
        return quotes

    def get_depth(self, symbol: str, auth_token: str = "") -> Any:
        """Delegate to broker data.get_depth."""
        exchange, name = _split_exchange_symbol(symbol)
        return self._data.get_depth(name, exchange, auth_token)

    def get_history(
        self,
        params: dict[str, Any] | str,
        exchange: str = "",
        interval: str = "",
        start: str = "",
        end: str = "",
        auth_token: str = "",
    ) -> Any:
        """Delegate to broker data.get_history.

        Legacy callers used the OpenAlgo positional shape directly. The current
        registry/session contract passes a params dict plus auth token. Accept
        both so connected screener routes do not hit a TypeError and silently
        fall back to sample data.
        """
        if isinstance(params, dict):
            token = auth_token or (exchange if not interval and not start and not end else "")
            symbol = str(params.get("symbol") or "")
            exchange_name = str(params.get("exchange") or "NSE")
            interval_name = str(params.get("interval") or "1d")
            start_value = str(params.get("start") or params.get("from") or params.get("start_date") or "")
            end_value = str(params.get("end") or params.get("to") or params.get("end_date") or "")
            return self._data.get_history(symbol, exchange_name, interval_name, start_value, end_value, token)
        return self._data.get_history(params, exchange, interval, start, end, auth_token)

    def get_option_chain(
        self,
        params: dict[str, Any] | str,
        exchange: str = "",
        expiry: str | None = None,
        auth_token: str = "",
    ) -> Any:
        """Delegate to the broker data module's option-chain reader.

        FlintTrade's registry/session contract passes ``(params, token)`` while
        OpenAlgo broker data modules have used a few names and positional
        shapes over time. Keep the adaptation here so screener routes and
        sessions do not learn broker-module naming quirks.
        """
        request: dict[str, Any]
        if isinstance(params, dict):
            token = auth_token or (exchange if expiry in (None, "") else "")
            request = dict(params)
            symbol = str(request.get("symbol") or request.get("underlying") or "")
            exchange_name = str(request.get("exchange") or "NSE_INDEX")
            expiry_value = request.get("expiry") or request.get("expiry_date")
        else:
            token = auth_token
            symbol = str(params)
            exchange_name = exchange or "NSE_INDEX"
            expiry_value = expiry
            request = {"symbol": symbol, "exchange": exchange_name}
            if expiry_value:
                request["expiry"] = expiry_value

        candidates = [
            (request, token),
            (symbol, exchange_name, expiry_value, token),
            (symbol, exchange_name, token),
            (symbol, exchange_name, expiry_value),
            (symbol, exchange_name),
        ]
        for method_name in ("get_option_chain", "option_chain", "optionchain"):
            method = getattr(self._data, method_name, None)
            if not callable(method):
                continue
            unknown_signature_error: TypeError | None = None
            for args in candidates:
                supported = _supports_positional_call(method, len(args))
                if supported is False:
                    continue
                try:
                    return method(*args)
                except TypeError as exc:
                    if supported is True:
                        raise
                    unknown_signature_error = exc
            if unknown_signature_error is not None:
                raise unknown_signature_error
        raise NotImplementedError(
            f"Broker data module for {self._broker!r} does not expose option-chain reads"
        )

    def search_symbols(self, query: str, auth_token: str = "") -> Any:
        """Delegate to broker data.search_symbols."""
        return self._data.search_symbols(query, "NSE", auth_token)


# ---------------------------------------------------------------------------
# Broker catalog — 32 entries (31 live + 1 sandbox).
#
# Exchange lists are sourced from each broker's plugin.json in
# .local/external/openalgo/broker/<name>/plugin.json so the catalog stays
# in lock-step with what upstream actually supports. Re-run the catalogue
# diff helper in scripts/check_absorption_drift.py after every external
# refresh to catch upstream additions.
# ---------------------------------------------------------------------------


# Native login-method schemas, folded here from the former
# flinttrade_core.native_auth_methods (consolidation G40 — one catalogue). Each
# method lists the exact credential fields the native adapter's ``login()`` (or
# OAuth start) consumes, whether they are secret, and the flow ``kind`` so the
# connect UI renders a form ("direct") or launches OAuth ("oauth"). Only methods
# the adapter actually supports today are listed. Attached to the catalogue
# entry below via ``auth_methods=``; Pydantic coerces these dicts to AuthMethod.
def _f(name: str, label: str, *, secret: bool = False, required: bool = True, help_: str = "") -> dict[str, Any]:
    return {"name": name, "label": label, "secret": secret, "required": required, "help": help_}


_NATIVE_AUTH: dict[str, list[dict[str, Any]]] = {
    "dhan": [
        {
            "id": "oauth", "label": "Log in with Dhan (OAuth)", "kind": "oauth",
            "description": (
                "Approve a DhanHQ app-consent login. Register the shown redirect URL in your DhanHQ app; "
                "Dhan redirects back with a tokenId that FlintTrade consumes for a 24h access token."
            ),
            "fields": [_f("api_key", "App ID"), _f("api_secret", "App secret", secret=True)],
        },
        {
            "id": "access_token", "label": "Access token", "kind": "direct",
            "description": "Paste a 24h access token from web.dhan.co → Profile → Access DhanHQ APIs.",
            "fields": [_f("client_id", "Dhan client ID"), _f("access_token", "Access token", secret=True)],
        },
        {
            "id": "pin_totp", "label": "PIN + TOTP", "kind": "direct",
            "description": "Mint a fresh 24h token from your PIN and authenticator code (TOTP must be enabled on the account).",
            "fields": [_f("client_id", "Dhan client ID"), _f("pin", "PIN", secret=True), _f("totp", "6-digit TOTP")],
        },
    ],
    "upstox": [
        {
            "id": "oauth", "label": "Log in with Upstox (OAuth)", "kind": "oauth",
            "description": (
                "Approve access on upstox.com. In Developer → Apps, register the shown redirect URL and your "
                "current outbound public IP under Primary/Secondary IP before using order APIs; changing those "
                "IPs invalidates Upstox access tokens. Leave the optional Notifier Webhook Endpoint blank."
            ),
            "fields": [_f("api_key", "API key (client ID)"), _f("api_secret", "API secret", secret=True)],
        },
        {
            "id": "access_token", "label": "Access token", "kind": "direct",
            "description": "Paste a token you already generated (e.g. via a prior OAuth login or a sandbox app).",
            "fields": [_f("client_id", "Client ID", required=False), _f("access_token", "Access token", secret=True)],
        },
    ],
    "kotakneo": [
        {
            "id": "totp_mpin", "label": "TOTP + MPIN", "kind": "direct",
            "description": (
                "Kotak Neo two-step 2FA. Paste the Trade API access token from NEO → Invest → Trade API "
                "(the Python SDK calls this consumer key), then enter TOTP and MPIN."
            ),
            "fields": [
                _f(
                    "access_token",
                    "Trade API access token",
                    secret=True,
                    help_="Kotak's docs call this the Trade API access token; FlintTrade maps it to the SDK's consumer_key field internally.",
                ),
                _f("mobile_number", "Mobile number (with country code)"),
                _f("ucc", "UCC (client code)"),
                _f("totp", "6-digit TOTP"),
                _f("mpin", "MPIN", secret=True),
                _f("neo_fin_key", "Neo fin key", required=False),
            ],
        },
    ],
    "indmoney": [
        {
            "id": "access_token", "label": "Access token", "kind": "direct",
            "description": (
                "Generate an access token on the INDstocks API dashboard and paste it here. Save your static "
                "outbound IP before live algo orders; INDstocks resets tokens daily at 06:00 IST and allows "
                "up to five active tokens."
            ),
            "fields": [
                _f("user_id", "User ID", required=False),
                _f(
                    "access_token",
                    "Access token",
                    secret=True,
                    help_="Generate a fresh INDstocks token after the daily 06:00 IST reset.",
                ),
            ],
        },
    ],
    "groww": [
        {
            "id": "api_key_totp", "label": "API key + TOTP", "kind": "direct",
            "description": (
                "Enter the Groww Trade API key and the current TOTP code from your authenticator. FlintTrade "
                "mints the daily access token locally before creating the broker session."
            ),
            "fields": [
                _f("user_id", "User ID", required=False),
                _f("api_key", "API key", secret=True),
                _f("totp", "6-digit TOTP"),
            ],
        },
        {
            "id": "api_key_secret", "label": "API key + secret", "kind": "direct",
            "description": (
                "Enter the Groww Trade API key and secret from Groww Cloud/API Keys. FlintTrade mints the "
                "daily access token locally before creating the broker session. Live order placement still "
                "requires static outbound IP setup."
            ),
            "fields": [
                _f("user_id", "User ID", required=False),
                _f("api_key", "API key", secret=True),
                _f("api_secret", "API secret", secret=True),
            ],
        },
        {
            "id": "access_token", "label": "Access token", "kind": "direct",
            "description": (
                "Paste an already minted Groww Trade API access token from Groww Cloud/API Keys. Groww tokens "
                "expire at 06:00 IST and live order placement still requires static outbound IP setup."
            ),
            "fields": [
                _f("user_id", "User ID", required=False),
                _f(
                    "access_token",
                    "Access token",
                    secret=True,
                    help_="Generate a fresh Groww Trade API token after the 06:00 IST expiry window.",
                ),
            ],
        },
    ],
}


_BROKER_MCP: dict[str, dict[str, Any]] = {
    "dhan": {
        "remote_url": "https://mcp.dhan.co/mcp",
        "docs_url": "https://docs.dhanhq.co/mcp/",
        "auth_mode": "Authorize through Dhan's hosted MCP flow from the client.",
        "reauth": "Re-authorize in the MCP client when Dhan prompts for a fresh session.",
        "read_only": False,
        "trading_supported": True,
        "login_steps": [
            "Add the Dhan remote MCP URL to a supported MCP client.",
            "Complete the Dhan browser authorisation and explicit consent flow opened by that client.",
            "Keep FlintTrade live orders on the gated native/OpenAlgo path.",
        ],
        "use_cases": [
            "Portfolio and account review",
            "Order placement, modification, cancellation, and Super Orders in the external MCP client",
            "Market data, historical OHLC, option chain with Greeks, and live-feed lookup",
            "Margin, funds, instruments, alerts, ScanX, options analysis, and backtesting workflows",
        ],
        "cautions": [
            "Broker MCP trade tools are outside FlintTrade's in-process safety gate; FlintTrade automation must still use gate_order or gate_broker_write through BrokerRouter.",
            "Dhan's agent skill pack is reference/setup help; it does not establish a FlintTrade broker session or remove order-confirmation requirements.",
        ],
        "client_configs": [
            {
                "id": "remote_url",
                "label": "Claude / ChatGPT / custom connector",
                "url": "https://mcp.dhan.co/mcp",
                "config": {"url": "https://mcp.dhan.co/mcp"},
            },
            {
                "id": "claude_code",
                "label": "Claude Code CLI",
                "command": "claude",
                "args": ["mcp", "add", "--transport", "http", "dhan", "https://mcp.dhan.co/mcp"],
            },
            {
                "id": "codex_cli",
                "label": "Codex CLI",
                "command": "codex",
                "args": ["mcp", "add", "dhan", "--url", "https://mcp.dhan.co/mcp"],
            },
            {
                "id": "cursor",
                "label": "Cursor direct URL",
                "url": "https://mcp.dhan.co/mcp",
                "config": {
                    "mcpServers": {
                        "dhan": {"url": "https://mcp.dhan.co/mcp"},
                    },
                },
            },
            {
                "id": "vscode_copilot",
                "label": "VS Code direct URL",
                "url": "https://mcp.dhan.co/mcp",
                "config": {
                    "mcp": {
                        "servers": {
                            "dhan": {"url": "https://mcp.dhan.co/mcp"},
                        },
                    },
                },
            },
            {
                "id": "kiro",
                "label": "Kiro direct URL",
                "url": "https://mcp.dhan.co/mcp",
                "config": {
                    "mcpServers": {
                        "dhan": {"url": "https://mcp.dhan.co/mcp"},
                    },
                },
            },
            {
                "id": "opencode",
                "label": "OpenCode remote OAuth",
                "url": "https://mcp.dhan.co/mcp",
                "config": {
                    "name": "dhan",
                    "type": "remote",
                    "url": "https://mcp.dhan.co/mcp",
                    "oauth": True,
                },
            },
            {
                "id": "dhanhq_skill_pack",
                "label": "DhanHQ agent skill pack",
                "command": "skills",
                "args": ["add", "dhan-oss/dhanhq-skills", "--skill", "dhanhq"],
            },
        ],
    },
    "upstox": {
        "remote_url": "https://mcp.upstox.com/mcp",
        "docs_url": "https://upstox.com/developer/api-documentation/mcp-integration/",
        "auth_mode": "Authorize through Upstox's hosted MCP flow from the client.",
        "reauth": "Daily re-authorisation is required.",
        "read_only": True,
        "trading_supported": False,
        "daily_reauthorization": True,
        "login_steps": [
            "Install Node.js, then add the Upstox MCP configuration to Claude Desktop, ChatGPT, Cursor, or VS Code.",
            "Complete the OAuth authorisation opened by that client.",
            "Repeat authorisation daily before relying on account context.",
        ],
        "use_cases": [
            "Read-only holdings, orders, positions, mutual funds, funds, and profile lookup",
            "Account-scoped portfolio composition, performance, risk, and buying-power analysis",
            "Individual stock research in the context of current holdings",
            "Technical indicator, chart, trend, and market-context analysis",
            "Activity summaries, margins, P&L overviews, and portfolio correlation studies",
        ],
        "cautions": [
            "Upstox MCP cannot place, modify, or cancel orders.",
            "Use FlintTrade's native Upstox or OpenAlgo order path for live trading, with the normal safety gate.",
            "Treat AI-generated analysis as research support; verify critical data directly on Upstox before acting.",
        ],
        "client_configs": [
            {
                "id": "remote_url",
                "label": "ChatGPT / custom connector URL",
                "url": "https://mcp.upstox.com/mcp",
                "config": {"name": "Upstox MCP", "url": "https://mcp.upstox.com/mcp", "developer_mode": True},
            },
            {
                "id": "claude_cursor_mcp_remote",
                "label": "Claude Desktop / Cursor mcp-remote",
                "command": "npx",
                "args": ["mcp-remote", "https://mcp.upstox.com/mcp"],
                "config": {
                    "mcpServers": {
                        "Upstox MCP": {
                            "command": "npx",
                            "args": ["mcp-remote", "https://mcp.upstox.com/mcp"],
                        },
                    },
                },
            },
            {
                "id": "vscode_copilot",
                "label": "VS Code GitHub Copilot",
                "url": "https://mcp.upstox.com/mcp",
                "config": {
                    "mcp": {
                        "inputs": [],
                        "servers": {
                            "Upstox MCP": {
                                "url": "https://mcp.upstox.com/mcp",
                            },
                        },
                    },
                },
            },
        ],
    },
    "groww": {
        "remote_url": "https://mcp.groww.in/mcp",
        "docs_url": "https://groww.in/updates/groww-mcp",
        "auth_mode": "Authorize through Groww's hosted MCP flow from the client with explicit account permission.",
        "reauth": "Grant access when the MCP client asks; Groww documents explicit permission rather than background sync.",
        "read_only": False,
        "trading_supported": True,
        "login_steps": [
            "For Claude Pro, add a custom connector named GrowwMCP with the Groww MCP URL.",
            "For Cursor, VS Code, or Windsurf, add the mcp-remote configuration and install Node.js if needed.",
            "Confirm DDPI status before sell-order workflows.",
        ],
        "use_cases": [
            "Portfolio performance, exposure, benchmark, and market-fall analysis",
            "F&O position, candle, expiry, and P&L analysis",
            "Smart order management in the external MCP client",
            "Market context and holdings near 52-week highs",
            "Stocks and F&O today; mutual funds, IPOs, bonds, and fundamental analysis are future broker scope",
        ],
        "cautions": [
            "Sell orders through Groww MCP require DDPI authorisation.",
            "Groww describes MCP as early-stage and not investment advice; verify outputs before trading.",
            "Groww native account reads and margin checks have live proof, but native connect stays disabled until market-data/API permissions, static IP setup, and order-safety verification pass.",
        ],
        "client_configs": [
            {
                "id": "remote_url",
                "label": "Claude Pro custom connector",
                "url": "https://mcp.groww.in/mcp",
                "config": {"name": "GrowwMCP", "url": "https://mcp.groww.in/mcp"},
            },
            {
                "id": "mcp_remote_cursor_vscode",
                "label": "Cursor / VS Code / Windsurf mcp-remote",
                "command": "npx",
                "args": ["mcp-remote@0.1.18", "https://mcp.groww.in/mcp", "52155"],
                "config": {
                    "mcpServers": {
                        "growwmcp": {
                            "command": "npx",
                            "args": ["mcp-remote@0.1.18", "https://mcp.groww.in/mcp", "52155"],
                        },
                    },
                },
            },
        ],
    },
}


BROKER_CATALOG: dict[str, BrokerInfo] = {
    # ---- OAuth redirect flow (10) ----------------------------------------
    "zerodha": BrokerInfo(
        name="zerodha",
        display_name="Zerodha",
        auth_flow=AuthFlowType.oauth_redirect,
        exchanges=[
            "NSE", "BSE", "NFO", "BFO", "CDS", "MCX",
            "NCO", "NSE_INDEX", "BSE_INDEX", "MCX_INDEX", "GLOBAL_INDEX",
        ],
    ),
    "fyers": BrokerInfo(
        name="fyers",
        display_name="Fyers",
        auth_flow=AuthFlowType.oauth_redirect,
        exchanges=["NSE", "BSE", "NFO", "BFO", "CDS", "MCX", "NSE_INDEX", "BSE_INDEX"],
    ),
    "flattrade": BrokerInfo(
        name="flattrade",
        display_name="Flattrade",
        auth_flow=AuthFlowType.oauth_redirect,
        exchanges=["NSE", "BSE", "NFO", "BFO", "CDS", "MCX", "NSE_INDEX", "BSE_INDEX"],
    ),
    "pocketful": BrokerInfo(
        name="pocketful",
        display_name="Pocketful",
        auth_flow=AuthFlowType.oauth_redirect,
        exchanges=["NSE", "BSE", "NFO", "BFO", "MCX", "NSE_INDEX", "BSE_INDEX"],
    ),
    "paytm": BrokerInfo(
        name="paytm",
        display_name="Paytm Money",
        auth_flow=AuthFlowType.oauth_redirect,
        exchanges=["NSE", "BSE", "NFO", "BFO", "NSE_INDEX", "BSE_INDEX"],
    ),
    "dhan": BrokerInfo(
        name="dhan",
        display_name="Dhan",
        auth_flow=AuthFlowType.oauth_redirect,
        exchanges=["NSE", "BSE", "NFO", "BFO", "CDS", "BCD", "MCX", "NSE_INDEX", "BSE_INDEX"],
        native=True,
        connectable=True,  # tried-and-tested against a live account
        auth_methods=_NATIVE_AUTH["dhan"],
        sdk_pin="dhanhq",
        mcp=_BROKER_MCP["dhan"],
    ),
    "aliceblue": BrokerInfo(
        name="aliceblue",
        display_name="AliceBlue",
        auth_flow=AuthFlowType.oauth_redirect,
        exchanges=["NSE", "BSE", "NFO", "BFO", "CDS", "BCD", "MCX", "NSE_INDEX", "BSE_INDEX"],
    ),
    "upstox": BrokerInfo(
        name="upstox",
        display_name="Upstox",
        auth_flow=AuthFlowType.oauth_redirect,
        exchanges=[
            "NSE", "BSE", "NFO", "BFO", "CDS", "BCD", "MCX",
            "NSE_INDEX", "BSE_INDEX", "GLOBAL_INDEX",
        ],
        native=True,
        connectable=True,  # tried-and-tested against a live account
        auth_methods=_NATIVE_AUTH["upstox"],
        sdk_pin="upstox-python-sdk",
        mcp=_BROKER_MCP["upstox"],
    ),
    "compositedge": BrokerInfo(
        name="compositedge",
        display_name="Compositedge",
        auth_flow=AuthFlowType.oauth_redirect,
        exchanges=["NSE", "BSE", "NFO", "BFO", "CDS", "MCX", "NSE_INDEX", "BSE_INDEX"],
    ),
    "rmoney": BrokerInfo(
        name="rmoney",
        display_name="RMoney",
        auth_flow=AuthFlowType.oauth_redirect,
        exchanges=["NSE", "BSE", "NFO", "BFO", "NSE_INDEX", "BSE_INDEX"],
    ),
    # ---- TOTP form flow (10) ---------------------------------------------
    "angel": BrokerInfo(
        name="angel",
        display_name="Angel One",
        auth_flow=AuthFlowType.totp_form,
        exchanges=["NSE", "BSE", "NFO", "BFO", "CDS", "MCX", "NSE_INDEX", "BSE_INDEX", "MCX_INDEX"],
    ),
    "fivepaisa": BrokerInfo(
        name="fivepaisa",
        display_name="5paisa",
        auth_flow=AuthFlowType.totp_form,
        exchanges=["NSE", "BSE", "NFO", "BFO", "CDS", "MCX", "NSE_INDEX", "BSE_INDEX"],
    ),
    "zebu": BrokerInfo(
        name="zebu",
        display_name="Zebu",
        auth_flow=AuthFlowType.totp_form,
        exchanges=["NSE", "BSE", "NFO", "BFO", "CDS", "MCX", "NSE_INDEX"],
    ),
    "shoonya": BrokerInfo(
        name="shoonya",
        display_name="Shoonya",
        auth_flow=AuthFlowType.totp_form,
        exchanges=["NSE", "BSE", "NFO", "BFO", "CDS", "MCX", "NSE_INDEX", "BSE_INDEX"],
    ),
    "firstock": BrokerInfo(
        name="firstock",
        display_name="Firstock",
        auth_flow=AuthFlowType.totp_form,
        exchanges=["NSE", "BSE", "NFO", "BFO", "NSE_INDEX"],
    ),
    "tradejini": BrokerInfo(
        name="tradejini",
        display_name="Tradejini",
        auth_flow=AuthFlowType.totp_form,
        exchanges=["NSE", "BSE", "NFO", "BFO", "CDS", "BCD", "MCX", "NSE_INDEX", "BSE_INDEX"],
    ),
    "mstock": BrokerInfo(
        name="mstock",
        display_name="mStock",
        auth_flow=AuthFlowType.totp_form,
        exchanges=["NSE", "BSE", "NFO", "BFO", "CDS", "NSE_INDEX", "BSE_INDEX"],
    ),
    "kotak": BrokerInfo(
        name="kotak",
        display_name="Kotak Securities",
        # Bridge-only entry: "kotak" is the OpenAlgo Kotak Securities plugin —
        # a DIFFERENT product from the native "kotakneo" (Kotak Neo) entry
        # below. Reachable via the OpenAlgo primary path; no native adapter.
        auth_flow=AuthFlowType.totp_form,
        exchanges=["NSE", "BSE", "NFO", "BFO", "CDS", "MCX", "NSE_INDEX", "BSE_INDEX"],
    ),
    "kotakneo": BrokerInfo(
        name="kotakneo",
        display_name="Kotak Neo",
        # Native FlintTrade adapter (brokers/kotakneo.py). Distinct from the
        # bridge "kotak" (Kotak Securities) above. Built + mock-tested, not yet
        # login/read verified → native but "coming soon" (connectable=False).
        auth_flow=AuthFlowType.totp_form,
        exchanges=["NSE", "BSE", "NFO", "BFO", "CDS", "BCD", "MCX", "NSE_INDEX", "BSE_INDEX"],
        native=True,
        connectable=False,
        auth_methods=_NATIVE_AUTH["kotakneo"],
        sdk_pin="neo-api-client",
    ),
    "motilal": BrokerInfo(
        name="motilal",
        display_name="Motilal Oswal",
        auth_flow=AuthFlowType.totp_form,
        exchanges=["NSE", "BSE", "NFO", "BFO", "CDS", "MCX", "NSE_INDEX", "BSE_INDEX"],
    ),
    "nubra": BrokerInfo(
        name="nubra",
        display_name="Nubra",
        auth_flow=AuthFlowType.totp_form,
        exchanges=["NSE", "BSE", "NFO", "BFO", "NSE_INDEX", "BSE_INDEX"],
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
        exchanges=["NSE", "BSE", "NFO", "BFO", "CDS", "MCX", "NSE_INDEX", "BSE_INDEX"],
        aux_params=["secret_api_key", "primary_ip", "secondary_ip"],
    ),
    # ---- API key direct flow (10) ----------------------------------------
    "deltaexchange": BrokerInfo(
        name="deltaexchange",
        display_name="Delta Exchange",
        auth_flow=AuthFlowType.api_key_direct,
        # Upstream plugin.json declares CRYPTO. FlintTrade-internal
        # naming uses "DELTA" in some constants — those are aliases for
        # this broker, not a different exchange code.
        exchanges=["CRYPTO"],
    ),
    "groww": BrokerInfo(
        name="groww",
        display_name="Groww",
        auth_flow=AuthFlowType.api_key_direct,
        exchanges=["NSE", "BSE", "NFO", "BFO", "NSE_INDEX", "BSE_INDEX"],
        native=True,
        connectable=False,
        auth_methods=_NATIVE_AUTH["groww"],
        sdk_pin="growwapi",
        mcp=_BROKER_MCP["groww"],
    ),
    "wisdom": BrokerInfo(
        name="wisdom",
        display_name="Wisdom Capital (XTS)",
        auth_flow=AuthFlowType.api_key_direct,
        exchanges=["NSE", "BSE", "NFO", "BFO", "CDS", "MCX", "NSE_INDEX", "BSE_INDEX"],
    ),
    "ibulls": BrokerInfo(
        name="ibulls",
        display_name="IBulls",
        auth_flow=AuthFlowType.api_key_direct,
        exchanges=["NSE", "BSE", "NFO", "BFO", "MCX", "NSE_INDEX", "BSE_INDEX"],
    ),
    "iifl": BrokerInfo(
        name="iifl",
        display_name="IIFL",
        auth_flow=AuthFlowType.api_key_direct,
        exchanges=["NSE", "BSE", "NFO", "BFO", "CDS", "MCX", "NSE_INDEX", "BSE_INDEX"],
    ),
    "iiflcapital": BrokerInfo(
        name="iiflcapital",
        display_name="IIFL Capital",
        # IIFL Capital ships its own native MQTT market-data feed and
        # uses a direct API-key flow (added upstream in v2.0.1.1 via
        # commits 3ba5bf08 + 73857264 + 0ad69cf3 + 15179371).
        auth_flow=AuthFlowType.api_key_direct,
        exchanges=["NSE", "BSE", "NFO", "BFO", "CDS", "BCD", "MCX", "NSE_INDEX", "BSE_INDEX"],
    ),
    "jainamxts": BrokerInfo(
        name="jainamxts",
        display_name="Jainam XTS",
        auth_flow=AuthFlowType.api_key_direct,
        exchanges=["NSE", "BSE", "NFO", "BFO", "NSE_INDEX", "BSE_INDEX"],
    ),
    "indmoney": BrokerInfo(
        name="indmoney",
        display_name="INDmoney",
        # ``api_key_direct`` is shorthand for the INDstocks dashboard access
        # token; unlike a persistent API key it expires daily (24 h), so the
        # native adapter (brokers/indmoney.py) treats it as a renewable
        # session credential.
        auth_flow=AuthFlowType.api_key_direct,
        exchanges=["NSE", "BSE", "NFO", "BFO", "NSE_INDEX", "BSE_INDEX"],
        native=True,
        connectable=True,  # login/read verified against INDstocks dashboard token read paths
        auth_methods=_NATIVE_AUTH["indmoney"],
        sdk_pin=None,
    ),
    "fivepaisaxts": BrokerInfo(
        name="fivepaisaxts",
        display_name="5paisa XTS",
        auth_flow=AuthFlowType.api_key_direct,
        exchanges=["NSE", "BSE", "NFO", "BFO", "NSE_INDEX", "BSE_INDEX"],
    ),
    # ---- OTP SMS flow (1) ------------------------------------------------
    "definedge": BrokerInfo(
        name="definedge",
        display_name="DefinedGe Securities",
        auth_flow=AuthFlowType.otp_sms,
        exchanges=["NSE", "BSE", "NFO", "BFO", "CDS", "MCX", "NSE_INDEX", "BSE_INDEX"],
    ),
    # ---- Sandbox (1) -----------------------------------------------------
    "dhan_sandbox": BrokerInfo(
        name="dhan_sandbox",
        display_name="Dhan Sandbox",
        auth_flow=AuthFlowType.oauth_redirect,
        exchanges=["NSE", "BSE", "NFO", "BFO", "CDS", "BCD", "MCX", "NSE_INDEX", "BSE_INDEX"],
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
