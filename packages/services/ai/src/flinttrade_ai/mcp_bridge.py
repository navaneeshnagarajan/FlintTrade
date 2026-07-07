"""MCP (Model Context Protocol) bridge for natural language trading.

Adapts openalgo-mcp patterns. Exposes FlintTrade functions as MCP tools
that can be invoked via natural language commands parsed by the LLM.

Safety: ALL orders go through the engine's safety layers. Never bypass.

Example: "Sell NIFTY 25000 CE 2 lots" → parsed → validated → routed through
engine OrderRouter → placed via OpenAlgo.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Callable

from flinttrade_screener.lot_sizes import FALLBACK_LOT_SIZES

from .llm_client import LLMClient, LLMMessage

logger = logging.getLogger("flinttrade.ai.mcp_bridge")


# ---------------------------------------------------------------------------
# Tool definitions
# ---------------------------------------------------------------------------


@dataclass
class MCPTool:
    """A registered MCP tool that maps to a FlintTrade function."""

    name: str
    description: str
    parameters: dict[str, Any]  # JSON Schema for parameters
    handler: Callable[..., Any] | None = None


@dataclass
class MCPToolCall:
    """A parsed tool invocation from natural language."""

    tool_name: str
    arguments: dict[str, Any] = field(default_factory=dict)
    raw_text: str = ""
    confidence: float = 0.0


@dataclass
class MCPResult:
    """Result from executing an MCP tool call."""

    success: bool = False
    tool_name: str = ""
    result: Any = None
    error: str = ""
    raw_input: str = ""


# Standard tool definitions matching FlintTrade capabilities
TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "name": "place_order",
        "description": "Place a trading order. Supports equity, F&O, commodity, and currency.",
        "parameters": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string", "description": "Trading symbol (e.g. RELIANCE, NIFTY26MAR2524000CE)"},
                "action": {"type": "string", "enum": ["BUY", "SELL"]},
                "exchange": {"type": "string", "enum": ["NSE", "BSE", "NFO", "BFO", "MCX", "CDS"], "default": "NSE"},
                "quantity": {"type": "string", "description": "Number of shares/lots"},
                "pricetype": {"type": "string", "enum": ["MARKET", "LIMIT", "SL", "SL-M"], "default": "MARKET"},
                "product": {"type": "string", "enum": ["MIS", "CNC", "NRML"], "default": "MIS"},
                "price": {"type": "string", "default": "0"},
            },
            "required": ["symbol", "action", "quantity"],
        },
    },
    {
        "name": "get_positions",
        "description": "Get current open positions from the broker.",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "get_quotes",
        "description": "Get current price quote for a symbol.",
        "parameters": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string"},
                "exchange": {"type": "string", "default": "NSE"},
            },
            "required": ["symbol"],
        },
    },
    {
        "name": "get_option_chain",
        "description": "Get the option chain for an underlying symbol.",
        "parameters": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string", "description": "Underlying (e.g. NIFTY, BANKNIFTY)"},
                "exchange": {"type": "string", "default": "NFO"},
            },
            "required": ["symbol"],
        },
    },
    {
        "name": "get_greeks",
        "description": "Get option Greeks (delta, gamma, theta, vega) for a symbol.",
        "parameters": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string"},
                "exchange": {"type": "string", "default": "NFO"},
            },
            "required": ["symbol"],
        },
    },
    {
        "name": "run_backtest",
        "description": "Run a backtest for a strategy on historical data.",
        "parameters": {
            "type": "object",
            "properties": {
                "strategy": {"type": "string", "description": "Strategy name (e.g. EMACrossover)"},
                "symbol": {"type": "string"},
                "exchange": {"type": "string", "default": "NSE"},
                "interval": {"type": "string", "default": "1d"},
                "start_date": {"type": "string"},
                "end_date": {"type": "string"},
            },
            "required": ["strategy", "symbol"],
        },
    },
    {
        "name": "get_screener_data",
        "description": "Get screener data: PCR, max pain, OI analysis, support/resistance.",
        "parameters": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string"},
                "analysis_type": {"type": "string", "enum": ["pcr", "max_pain", "support_resistance", "oi_spurt"]},
            },
            "required": ["symbol", "analysis_type"],
        },
    },
]


# ---------------------------------------------------------------------------
# Natural language command parsing
# ---------------------------------------------------------------------------

_ORDER_PATTERN = re.compile(
    r"(buy|sell)\s+"
    r"(\w+)"
    r"(?:\s+(\d+)\s*(lots?|qty|shares?))?"
    r"(?:\s+(?:at|@)\s+(\d+(?:\.\d+)?))?"
    r"(?:\s+(market|limit|sl))?",
    re.IGNORECASE,
)

# Lot sizes for quick parsing — sourced from the screener's contract-size
# table (this module's stale private copy sized FINNIFTY at 40 vs the current
# 65, so "buy 1 lot" commands produced wrong quantities).
_LOT_MAP = FALLBACK_LOT_SIZES


def parse_order_command(text: str) -> MCPToolCall | None:
    """Try to parse a direct order command from text.

    Examples:
    - "Buy RELIANCE 100 shares"
    - "Sell NIFTY 25000 CE 2 lots"
    - "Buy BANKNIFTY 30 qty at 51000 limit"
    """
    match = _ORDER_PATTERN.search(text)
    if not match:
        return None

    action = match.group(1).upper()
    symbol = match.group(2).upper()
    quantity_raw = match.group(3)
    unit = (match.group(4) or "").lower()
    price = match.group(5) or "0"
    pricetype = (match.group(6) or "MARKET").upper()

    # Determine exchange and quantity
    exchange = "NSE"
    if any(x in symbol for x in ("CE", "PE", "FUT")):
        exchange = "NFO"
    elif symbol in ("SENSEX", "BANKEX"):
        exchange = "BFO"

    quantity = "1"
    if quantity_raw:
        if "lot" in unit:
            # Resolve lot size from the LONGEST matching underlying — a plain
            # first-match walk resolved BANKNIFTY commands to NIFTY's lot
            # ("NIFTY" is a substring of every *NIFTY symbol).
            matches = [u for u in _LOT_MAP if u in symbol]
            lot_size = _LOT_MAP[max(matches, key=len)] if matches else 1
            quantity = str(int(quantity_raw) * lot_size)
        else:
            quantity = quantity_raw

    return MCPToolCall(
        tool_name="place_order",
        arguments={
            "symbol": symbol,
            "action": action,
            "exchange": exchange,
            "quantity": quantity,
            "price": price,
            "pricetype": pricetype,
        },
        raw_text=text,
        confidence=0.8,
    )


_SYSTEM_PROMPT = """You are a FlintTrade trading assistant with access to these tools:

{tools_json}

The user will ask you to perform trading operations in natural language.
Respond with EXACTLY one JSON object in this format:
{{"tool": "tool_name", "arguments": {{...}}}}

If the request is unclear or you need more information, respond with:
{{"tool": "none", "arguments": {{}}, "message": "Your question or clarification"}}

IMPORTANT: Never fabricate data. If asked for market data, use the appropriate tool.
All order placements go through safety validation — you cannot bypass this."""


def parse_with_llm(
    text: str,
    llm: LLMClient,
) -> MCPToolCall:
    """Use LLM to parse a natural language command into a tool call."""
    tools_json = json.dumps(TOOL_DEFINITIONS, indent=2)
    system = _SYSTEM_PROMPT.format(tools_json=tools_json)

    response = llm.chat([
        LLMMessage(role="system", content=system),
        LLMMessage(role="user", content=text),
    ], temperature=0.1, max_tokens=500)

    if not response.success:
        return MCPToolCall(tool_name="none", raw_text=text, confidence=0.0)

    try:
        content = response.content.strip()
        if "```" in content:
            content = content.split("```")[1].strip()
            if content.startswith("json"):
                content = content[4:].strip()

        data = json.loads(content)
        return MCPToolCall(
            tool_name=data.get("tool", "none"),
            arguments=data.get("arguments", {}),
            raw_text=text,
            confidence=0.9,
        )
    except (json.JSONDecodeError, KeyError):
        return MCPToolCall(tool_name="none", raw_text=text, confidence=0.0)


# ---------------------------------------------------------------------------
# MCP Bridge
# ---------------------------------------------------------------------------


class MCPBridge:
    """MCP bridge for natural language trading commands.

    Usage::

        bridge = MCPBridge(llm_client=llm)
        bridge.register_handler("place_order", my_order_handler)
        bridge.register_handler("get_positions", my_positions_handler)

        result = bridge.execute("Buy NIFTY 25000 CE 2 lots")
        if result.success:
            print(f"Order placed: {result.result}")
    """

    def __init__(self, llm_client: LLMClient | None = None) -> None:
        self._llm = llm_client
        self._handlers: dict[str, Callable[..., Any]] = {}
        self._tools = {t["name"]: t for t in TOOL_DEFINITIONS}

    def register_handler(self, tool_name: str, handler: Callable[..., Any]) -> None:
        """Register a handler function for a tool."""
        self._handlers[tool_name] = handler
        logger.info("MCP handler registered: %s", tool_name)

    def parse(self, text: str) -> MCPToolCall:
        """Parse natural language into a tool call.

        Tries regex-based order parsing first, then falls back to LLM.
        """
        # Try direct order parsing first (faster, no LLM needed)
        direct = parse_order_command(text)
        if direct:
            return direct

        # Fall back to LLM parsing
        if self._llm:
            return parse_with_llm(text, self._llm)

        return MCPToolCall(tool_name="none", raw_text=text, confidence=0.0)

    def execute(self, text: str) -> MCPResult:
        """Parse and execute a natural language trading command."""
        tool_call = self.parse(text)

        if tool_call.tool_name == "none" or not tool_call.tool_name:
            return MCPResult(
                tool_name="none",
                raw_input=text,
                error="Could not understand command",
            )

        handler = self._handlers.get(tool_call.tool_name)
        if not handler:
            return MCPResult(
                tool_name=tool_call.tool_name,
                raw_input=text,
                error=f"No handler registered for tool '{tool_call.tool_name}'",
            )

        try:
            result = handler(**tool_call.arguments)
            logger.info("MCP executed: %s(%s)", tool_call.tool_name, tool_call.arguments)
            return MCPResult(
                success=True,
                tool_name=tool_call.tool_name,
                result=result,
                raw_input=text,
            )
        except Exception as exc:
            logger.error("MCP execution error: %s — %s", tool_call.tool_name, exc)
            return MCPResult(
                tool_name=tool_call.tool_name,
                raw_input=text,
                error=str(exc),
            )

    @property
    def available_tools(self) -> list[str]:
        return list(self._tools.keys())

    @property
    def registered_handlers(self) -> list[str]:
        return list(self._handlers.keys())
