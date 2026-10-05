"""Read-only native capability helper and natural-language intent parsing.

This module does not grant order authority. Parsed order intents are useful to
callers for explanation; execution and write-handler registration are refused.
The native order runtime remains responsible for SafetyContext admission.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Callable

from flinttrade_screener.lot_sizes import FALLBACK_LOT_SIZES

from .llm_client import LLMClient, LLMMessage


@dataclass
class MCPTool:
    name: str
    description: str
    parameters: dict[str, Any]
    handler: Callable[..., Any] | None = None


@dataclass
class MCPToolCall:
    tool_name: str
    arguments: dict[str, Any] = field(default_factory=dict)
    raw_text: str = ""
    confidence: float = 0.0


@dataclass
class MCPResult:
    success: bool = False
    tool_name: str = ""
    result: Any = None
    error: str = ""
    raw_input: str = ""


def _definition(name: str, summary: str, required: tuple[str, ...] = (),
                optional: tuple[str, ...] = ()) -> dict[str, Any]:
    return {"name": name, "description": summary,
            "parameters": {"type": "object", "properties": {key: {"type": "string"} for key in (*required, *optional)},
                           "required": list(required)}}


TOOL_DEFINITIONS = [
    _definition("get_positions", "Read positions from an admitted native account"),
    _definition("get_quotes", "Read an authorised native quote", ("symbol",), ("exchange",)),
    _definition("get_option_chain", "Read an authorised native option-chain snapshot", ("symbol",), ("exchange",)),
    _definition("get_greeks", "Read supplied option sensitivities", ("symbol",), ("exchange",)),
    _definition("run_backtest", "Run a research backtest on supplied historical data", ("strategy", "symbol"),
                ("exchange", "interval", "start_date", "end_date")),
    _definition("get_screener_data", "Read supplied screener analytics", ("symbol", "analysis_type")),
]
_READ_TOOLS = frozenset(tool["name"] for tool in TOOL_DEFINITIONS)
_LOT_MAP = FALLBACK_LOT_SIZES


def parse_order_command(text: str) -> MCPToolCall | None:
    """Parse a display intent only, without granting any execution capability."""
    tokens = text.strip().split()
    if len(tokens) < 2 or tokens[0].casefold() not in {"buy", "sell"}:
        return None
    action, symbol = tokens[0].upper(), tokens[1].upper()
    if re.fullmatch(r"[A-Z0-9._-]+", symbol) is None:
        return None
    quantity, price, price_type = "1", "0", "MARKET"
    trailing = tokens[2:]
    for index, token in enumerate(trailing):
        unit = trailing[index + 1].casefold() if index + 1 < len(trailing) else ""
        if token.isdigit() and unit in {"lot", "lots", "qty", "share", "shares"}:
            amount = int(token)
            if unit in {"lot", "lots"}:
                underlying = next((name for name in sorted(_LOT_MAP, key=len, reverse=True) if name in symbol), None)
                amount *= _LOT_MAP[underlying] if underlying is not None else 1
            quantity = str(amount)
        if token in {"at", "@"} and index + 1 < len(trailing):
            candidate = trailing[index + 1]
            if re.fullmatch(r"[0-9]+(?:\.[0-9]+)?", candidate):
                price = candidate
        if token.casefold() in {"market", "limit", "sl", "sl-m"}:
            price_type = token.upper()
    exchange = "BFO" if symbol in {"SENSEX", "BANKEX"} else "NFO" if symbol.endswith(("CE", "PE", "FUT")) else "NSE"
    return MCPToolCall("place_order", {"symbol": symbol, "action": action, "exchange": exchange,
                                      "quantity": quantity, "price": price, "pricetype": price_type}, text, 0.8)


def parse_with_llm(text: str, llm: LLMClient) -> MCPToolCall:
    """Accept one typed read/research request from the configured model."""
    policy = ("Select one read or research capability from this schema. Return one JSON object with tool and arguments. "
              "Use tool='none' when insufficient information is supplied. Do not propose broker writes.\n" +
              json.dumps(TOOL_DEFINITIONS))
    response = llm.chat([LLMMessage(role="system", content=policy), LLMMessage(role="user", content=text)],
                        temperature=0.1, max_tokens=500)
    if response.success:
        try:
            content = response.content.strip()
            if content.startswith("```"):
                lines = content.splitlines()
                content = "\n".join(lines[1:-1])
            parsed = json.loads(content)
            if type(parsed) is dict and parsed.get("tool") in _READ_TOOLS and type(parsed.get("arguments")) is dict:
                return MCPToolCall(parsed["tool"], parsed["arguments"], text, 0.9)
        except (TypeError, ValueError):
            pass
    return MCPToolCall("none", raw_text=text)


class MCPBridge:
    """Invoke explicitly injected native read/research handlers only."""

    def __init__(self, llm_client: LLMClient | None = None) -> None:
        self._llm, self._handlers = llm_client, {}
        self._tools = {tool["name"]: tool for tool in TOOL_DEFINITIONS}

    def register_handler(self, tool_name: str, handler: Callable[..., Any]) -> None:
        if tool_name not in _READ_TOOLS:
            raise ValueError("Order-capable or unknown tools are unavailable")
        if not callable(handler):
            raise TypeError("Tool handler must be callable")
        self._handlers[tool_name] = handler

    def parse(self, text: str) -> MCPToolCall:
        intent = parse_order_command(text)
        if intent is not None:
            return intent
        return parse_with_llm(text, self._llm) if self._llm is not None else MCPToolCall("none", raw_text=text)

    def execute(self, text: str) -> MCPResult:
        call = self.parse(text)
        if call.tool_name == "place_order":
            return MCPResult(tool_name=call.tool_name, error="Order-capable tools are unavailable", raw_input=text)
        if call.tool_name not in _READ_TOOLS:
            return MCPResult(tool_name="none", error="Could not understand command", raw_input=text)
        handler = self._handlers.get(call.tool_name)
        if handler is None:
            return MCPResult(tool_name=call.tool_name, error=f"No handler registered for tool {call.tool_name!r}", raw_input=text)
        try:
            payload = handler(**call.arguments)
        except Exception as exc:
            return MCPResult(tool_name=call.tool_name, error=str(exc), raw_input=text)
        return MCPResult(True, call.tool_name, payload, raw_input=text)

    @property
    def available_tools(self) -> list[str]:
        return list(self._tools)

    @property
    def registered_handlers(self) -> list[str]:
        return list(self._handlers)
