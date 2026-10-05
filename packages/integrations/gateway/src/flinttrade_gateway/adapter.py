"""Static catalogue for built-in native broker adapters."""

from __future__ import annotations

from typing import Any

from .models import AuthFlowType, BrokerInfo


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
            "description": (
                "Paste a trading-capable token you already generated, such as a prior OAuth login or sandbox app token. "
                "Use the Analytics token method below for Upstox Developer → Apps analytics tokens."
            ),
            "fields": [_f("client_id", "Client ID", required=False), _f("access_token", "Access token", secret=True)],
        },
        {
            "id": "analytics_access_token", "label": "Analytics access token (read-only)", "kind": "direct",
            "description": (
                "Paste the one-year Analytics Access Token from Upstox Developer → Apps. Upstox documents this token "
                "as read-only: market data/streaming, plus portfolio/account/funds reads only when static IP is configured. "
                "FlintTrade will block place/modify/cancel through this session."
            ),
            "fields": [_f("client_id", "Client ID", required=False), _f("access_token", "Analytics access token", secret=True)],
            "credential_defaults": {"read_only": "true", "token_scope": "analytics"},
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
                "daily access token locally before creating the broker session. Live account reads have "
                "passed with an approved key; live order placement still requires static outbound IP setup."
            ),
            "fields": [
                _f("user_id", "User ID", required=False),
                _f("api_key", "API key", secret=True),
                _f(
                    "api_secret",
                    "API secret",
                    secret=True,
                    help_="If Groww says session approval is required, approve the API-key session in Groww Cloud/API Keys and retry.",
                ),
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
    "deltaexchange": [
        {
            "id": "api_key",
            "label": "API key + secret",
            "kind": "direct",
            "description": (
                "Paste a Delta Exchange API key and secret for one venue. India and Global keys are not "
                "interchangeable, and the environment has no default."
            ),
            "fields": [
                _f("api_key", "API key", secret=True),
                _f("api_secret", "API secret", secret=True),
                _f(
                    "environment",
                    "Venue",
                    help_="One of india_prod, india_testnet, global_prod, global_testnet. A key from another venue is rejected.",
                ),
                _f("user_id", "User ID", required=False, help_="Required only for close-all."),
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
            "Dhan's documented skill guardrails require explicit confirmation before place/modify/cancel, use LIMIT defaults, and validate F&O lot sizes.",
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
            "Use an active, non-dormant Upstox account; dormant accounts cannot complete MCP authorisation.",
            "Complete the OAuth authorisation opened by that client.",
            "Repeat authorisation daily before relying on account context.",
        ],
        "use_cases": [
            "Read-only holdings, orders, positions, mutual funds, funds, and profile lookup",
            "Account-scoped portfolio composition, performance, risk, and buying-power analysis",
            "Individual stock research in the context of current holdings",
            "Technical indicator, chart, trend, market-quote, and market-context analysis",
            "Activity summaries, margins, historical trading information, and P&L overviews",
            "Portfolio beta and correlation studies against NIFTY over multi-year windows",
            "Professional investment-model reviews over the operator's current portfolio",
            "Board-meeting, AGM/EGM, corporate-governance, and hold-or-sell context checks",
        ],
        "cautions": [
            "Upstox MCP cannot place, modify, or cancel orders.",
            "Treat AI-generated analysis as research support; verify critical data directly on Upstox before acting.",
            "If the MCP client starts the wrong Node.js/npx binary, configure full node and npx paths instead of relying on PATH.",
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
            "Groww documents explicit permission, no background syncing, and no AI-server data storage for MCP access.",
            "Groww native token minting may require approving the API-key session in Groww Cloud before FlintTrade can log in.",
            "Groww native account reads and margin checks have passed with an approved key, but native connect stays disabled until market-data/API permissions, static IP setup, and order-safety verification pass.",
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
    "deltaexchange": {
        "remote_url": "https://mcp.delta.exchange",
        "docs_url": "https://mcp.delta.exchange/docs",
        "auth_mode": "Local stdio server. FlintTrade does not proxy Delta MCP orders.",
        "reauth": "Rotate the API key in the MCP client. FlintTrade orders still go through the router.",
        "read_only": True,
        "trading_supported": False,
        "login_steps": [
            "Install the official server with uvx delta-exchange-mcp.",
            "Set DELTA_API_KEY, DELTA_API_SECRET, and DELTA_MCP_ENV to one venue.",
            "Leave DELTA_MCP_MODE unset. Do not enable trade mode for FlintTrade orders.",
        ],
        "use_cases": [
            "Read products, tickers, positions, and wallet state from an external MCP client",
        ],
        "cautions": [
            "India and Global keys are not interchangeable.",
            "DELTA_MCP_MODE=trade must not drive FlintTrade orders. Writes stay behind the router.",
            "Native connect stays disabled until live order-safety proof and a deadman runtime proof exist.",
        ],
        "client_configs": [
            {
                "id": "stdio_uvx",
                "label": "Local stdio via uvx",
                "command": "uvx",
                "args": ["delta-exchange-mcp"],
                "config": {
                    "mcpServers": {
                        "delta-exchange": {
                            "command": "uvx",
                            "args": ["delta-exchange-mcp"],
                        },
                    },
                },
            },
        ],
    },
}

# MCP server is the FIRST-preference MCP surface (maintainer, 2026-07-06):
# 30+ bridged brokers through one server. Served ahead of the broker-hosted
# instance (local stdio `python -m mcp.mcpserver <api_key> <host>`, or the
# install/Remote-MCP-readme.md + docs/mcp-tool-reference.md.


BROKER_CATALOG: dict[str, BrokerInfo] = {
    "dhan": BrokerInfo(
        name="dhan",
        display_name="Dhan",
        auth_flow=AuthFlowType.oauth_redirect,
        exchanges=["NSE", "BSE", "NFO", "BFO", "CDS", "BCD", "MCX", "NSE_INDEX", "BSE_INDEX"],
        native=True,
        connectable=True,  # tried-and-tested against a live account
        requires_static_ip=True,
        auth_methods=_NATIVE_AUTH["dhan"],
        sdk_pin="dhanhq",
        mcp=_BROKER_MCP["dhan"],
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
        requires_static_ip=True,
        auth_methods=_NATIVE_AUTH["upstox"],
        sdk_pin="upstox-python-sdk",
        mcp=_BROKER_MCP["upstox"],
    ),
    "kotakneo": BrokerInfo(
        name="kotakneo",
        display_name="Kotak Neo",
        # Native FlintTrade adapter (brokers/kotakneo.py). Distinct from the
        # bridge "kotak" (Kotak Securities) above. FT-MONDAY-002: connectable
        # for non-funded Connected (read) / API smoke. Live place stays
        # fail-closed. Neo has no sandbox.
        auth_flow=AuthFlowType.totp_form,
        exchanges=["NSE", "BSE", "NFO", "BFO", "MCX", "NSE_INDEX", "BSE_INDEX"],
        native=True,
        connectable=True,
        requires_static_ip=True,
        native_connect_blockers=[],
        auth_methods=_NATIVE_AUTH["kotakneo"],
        sdk_pin="kotakneoapi",
    ),
    "groww": BrokerInfo(
        name="groww",
        display_name="Groww",
        auth_flow=AuthFlowType.api_key_direct,
        exchanges=["NSE", "BSE", "NFO", "BFO", "MCX", "NSE_INDEX", "BSE_INDEX"],
        native=True,
        connectable=False,
        requires_static_ip=True,
        native_connect_blockers=[
            "Broker-side market-data/API permission",
            "Live order-safety proof",
        ],
        auth_methods=_NATIVE_AUTH["groww"],
        sdk_pin="growwapi",
        mcp=_BROKER_MCP["groww"],
    ),
    "indmoney": BrokerInfo(
        name="indmoney",
        display_name="INDmoney",
        # ``api_key_direct`` is shorthand for the INDstocks dashboard access
        # token; unlike a persistent API key it resets at the daily 06:00 IST
        # dashboard cycle, so the native adapter (brokers/indmoney.py) treats
        # it as a renewable session credential.
        auth_flow=AuthFlowType.api_key_direct,
        exchanges=["NSE", "BSE", "NFO", "BFO", "NSE_INDEX", "BSE_INDEX"],
        native=True,
        # Login/read paths and the fail-closed emergency planner are locally
        # verified. INDstocks does not expose a durable order-family discriminator
        # or a broker-atomic reduce-only close primitive, so cancellation and
        # flattening cannot yet satisfy the activation safety contract.
        connectable=False,
        native_connect_blockers=[
            "Authoritative smart-parent cancellation discriminator",
            "Broker-native atomic reduce-only close primitive",
            "Live order-safety proof",
        ],
        requires_static_ip=True,
        auth_methods=_NATIVE_AUTH["indmoney"],
        sdk_pin=None,
    ),
    "deltaexchange": BrokerInfo(
        name="deltaexchange",
        display_name="Delta Exchange",
        auth_flow=AuthFlowType.api_key_direct,
        exchanges=["CRYPTO"],
        native=True,
        connectable=False,
        requires_static_ip=False,
        native_connect_blockers=[
            "Live order-safety proof",
            "Deadman heartbeat runtime proof for unattended flatten",
        ],
        auth_methods=_NATIVE_AUTH["deltaexchange"],
        sdk_pin=None,
        mcp=_BROKER_MCP["deltaexchange"],
    ),
}
