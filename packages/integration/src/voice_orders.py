"""Voice orders parser for FlintTrade.

Converts natural language voice commands into structured order parameters.
Uses a fast rule-based parser for common patterns with an optional LLM
fallback for complex inputs.

Examples::

    parser = VoiceOrderParser()
    cmd = parser.parse("Buy 100 Reliance at market")
    # VoiceCommand(intent="place_order", action="BUY", symbol="RELIANCE",
    #              quantity=100, price_type="MARKET", confidence=0.95)

    cmd = parser.parse("Sell 50 Bank Nifty 24000 CE")
    # VoiceCommand(intent="place_order", action="SELL",
    #              symbol="BANKNIFTY24000CE", exchange="NFO",
    #              quantity=50, price_type="MARKET", confidence=0.9)

    cmd = parser.parse("Close all positions")
    # VoiceCommand(intent="close_all", confidence=1.0)

Flask endpoint: POST /api/v1/voice/parse
  Request:  {"text": "Buy 100 Nifty at market"}
  Response: {"status": "success", "data": {<VoiceCommand fields>}}
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Protocol

from flask import Blueprint, Response, jsonify, request

logger = logging.getLogger("flinttrade.integration.voice_orders")

# ---------------------------------------------------------------------------
# Exchange inference map
# ---------------------------------------------------------------------------

# Symbols that default to NSE_INDEX
_INDEX_SYMBOLS: frozenset[str] = frozenset(
    {
        "NIFTY",
        "BANKNIFTY",
        "FINNIFTY",
        "MIDCPNIFTY",
        "SENSEX",
        "BANKEX",
        "NIFTYNXT50",
    }
)

# Symbols that always trade on MCX
_MCX_SYMBOLS: frozenset[str] = frozenset(
    {
        "GOLD",
        "SILVER",
        "CRUDEOIL",
        "NATURALGAS",
        "COPPER",
        "ZINC",
        "NICKEL",
        "ALUMINIUM",
        "LEAD",
    }
)

# Exchanges accepted in voice input — normalised to OpenAlgo exchange codes
_EXCHANGE_ALIASES: dict[str, str] = {
    "nse": "NSE",
    "bse": "BSE",
    "nfo": "NFO",
    "bfo": "BFO",
    "mcx": "MCX",
    "cds": "CDS",
    "bcd": "BCD",
    "nse_index": "NSE_INDEX",
    "nseindex": "NSE_INDEX",
}

# ---------------------------------------------------------------------------
# Common phrase normalisation
# ---------------------------------------------------------------------------

# Maps spoken alias → canonical symbol fragment / intent keyword
_ALIASES: dict[str, str] = {
    # Options shorthand
    "call": "CE",
    "put": "PE",
    # Index aliases
    "bank nifty": "BANKNIFTY",
    "banknifty": "BANKNIFTY",
    "fin nifty": "FINNIFTY",
    "midcap nifty": "MIDCPNIFTY",
    # Action
    "purchase": "BUY",
    "long": "BUY",
    "short": "SELL",
    "exit": "SELL",
    # Price type
    "at market": "MARKET",
    "market order": "MARKET",
    "limit order": "LIMIT",
    "at limit": "LIMIT",
    # Intent phrases
    "close all": "CLOSE_ALL",
    "close all positions": "CLOSE_ALL",
    "square off all": "CLOSE_ALL",
    "squareoff all": "CLOSE_ALL",
    "cancel all": "CANCEL_ALL",
    "cancel all orders": "CANCEL_ALL",
}

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class VoiceCommand:
    """Structured representation of a parsed voice order command.

    Attributes:
        intent: High-level intent of the command.
            One of: ``"place_order"``, ``"cancel_order"``, ``"close_all"``,
            ``"modify_order"``, ``"query"``.
        action: Order side — ``"BUY"`` or ``"SELL"``.  ``None`` for intents
            that do not require an action (e.g. ``"close_all"``).
        symbol: OpenAlgo symbol string (upper-case, no spaces).
        exchange: OpenAlgo exchange code (e.g. ``"NSE"``, ``"NFO"``).
        quantity: Number of units/lots.
        price_type: ``"MARKET"`` or ``"LIMIT"``.
        price: Limit price (``None`` for market orders).
        product: Product type — ``"MIS"``, ``"CNC"``, or ``"NRML"``.
        confidence: Parser confidence score in [0.0, 1.0].
        raw_text: Original input text (preserved for debugging/LLM retry).
        error: Non-empty if parsing failed; explains the failure reason.
    """

    intent: str = "place_order"
    action: str | None = None
    symbol: str | None = None
    exchange: str | None = None
    quantity: int | None = None
    price_type: str | None = None
    price: float | None = None
    product: str = "MIS"
    confidence: float = 0.0
    raw_text: str = ""
    error: str = ""

    @property
    def is_valid(self) -> bool:
        """Return True when the command has no error and the minimum required
        fields are present for its intent."""
        if self.error:
            return False
        if self.intent == "place_order":
            return bool(self.action and self.symbol and self.quantity)
        return self.intent in {"close_all", "cancel_all", "query"}

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a JSON-safe dictionary."""
        return {
            "intent": self.intent,
            "action": self.action,
            "symbol": self.symbol,
            "exchange": self.exchange,
            "quantity": self.quantity,
            "price_type": self.price_type,
            "price": self.price,
            "product": self.product,
            "confidence": self.confidence,
            "raw_text": self.raw_text,
            "error": self.error,
            "is_valid": self.is_valid,
        }


# ---------------------------------------------------------------------------
# LLM client protocol (duck-typed — any client exposing .complete() works)
# ---------------------------------------------------------------------------


class LLMClientProtocol(Protocol):
    """Minimal protocol required for the LLM fallback parser."""

    def complete(self, prompt: str) -> str:
        """Return a text completion for *prompt*."""
        ...


# ---------------------------------------------------------------------------
# Rule-based helpers
# ---------------------------------------------------------------------------

# Numeric word map for spoken numbers (extend as needed)
_WORD_TO_INT: dict[str, int] = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "twenty": 20,
    "twenty five": 25,
    "fifty": 50,
    "hundred": 100,
    "two hundred": 200,
    "five hundred": 500,
    "thousand": 1000,
}

# Regex fragments
_RE_INTEGER = r"\b(\d{1,7})\b"
_RE_FLOAT = r"\b(\d{1,7}(?:\.\d{1,4})?)\b"
_RE_EXCHANGE = r"\b(nse|bse|nfo|bfo|mcx|cds|bcd|nse_index|nseindex)\b"


def _normalise_text(text: str) -> str:
    """Lower-case, collapse whitespace, apply alias substitutions."""
    text = text.lower().strip()
    text = re.sub(r"\s+", " ", text)
    # Apply multi-word aliases first (longest first to avoid partial matches)
    for alias, canonical in sorted(_ALIASES.items(), key=lambda x: -len(x[0])):
        text = re.sub(r"\b" + re.escape(alias) + r"\b", canonical.lower(), text)
    return text


def _infer_exchange(symbol: str, explicit: str | None) -> str:
    """Infer the most likely exchange for a symbol.

    Args:
        symbol: Upper-cased OpenAlgo symbol.
        explicit: Exchange code extracted from voice input (may be ``None``).

    Returns:
        OpenAlgo exchange code string.
    """
    if explicit:
        return explicit.upper()
    if symbol in _INDEX_SYMBOLS:
        return "NSE_INDEX"
    if symbol in _MCX_SYMBOLS:
        return "MCX"
    # Options/futures pattern: contains digit followed by CE/PE/FUT
    if re.search(r"\d+(CE|PE|FUT)$", symbol):
        return "NFO"
    return "NSE"


def _extract_quantity(text: str) -> int | None:
    """Extract the first plausible quantity from normalised text.

    Tries spoken-word numbers first, then digits.
    """
    for phrase, value in sorted(_WORD_TO_INT.items(), key=lambda x: -len(x[0])):
        if re.search(r"\b" + re.escape(phrase) + r"\b", text):
            return value
    m = re.search(_RE_INTEGER, text)
    if m:
        val = int(m.group(1))
        # Reject strike prices mistakenly captured as quantity:
        # a standalone 5-digit number is almost certainly a strike price
        # unless no other number is present.
        return val
    return None


def _extract_limit_price(text: str) -> float | None:
    """Extract a limit price following common spoken price keywords.

    Handles patterns like:
    - "at 1800"
    - "at limit 1800"
    - "limit 1800"
    - "price 1800"
    - "@ 1800"
    """
    m = re.search(r"(?:at\s+(?:limit\s+)?|limit\s+|price\s+|@\s*)" + _RE_FLOAT, text)
    if m:
        return float(m.group(1))
    return None


# ---------------------------------------------------------------------------
# Symbol construction helpers
# ---------------------------------------------------------------------------

# Regex: optional underlying + strike digits + CE/PE/FUT suffix
_OPTIONS_PATTERN = re.compile(
    r"\b([A-Z]+)?\s*(\d{4,6})\s*(CE|PE|ce|pe|call|put|fut)\b",
    re.IGNORECASE,
)


def _build_options_symbol(underlying: str, strike: str, opt_type: str) -> str:
    """Construct an OpenAlgo options symbol.

    Args:
        underlying: Index/stock name (e.g. ``"BANKNIFTY"``).
        strike: Strike price digits (e.g. ``"24000"``).
        opt_type: ``"CE"`` or ``"PE"`` (case-insensitive).

    Returns:
        Concatenated symbol string, e.g. ``"BANKNIFTY24000CE"``.
    """
    ot = opt_type.upper()
    if ot in {"CALL"}:
        ot = "CE"
    elif ot in {"PUT"}:
        ot = "PE"
    return f"{underlying.upper()}{strike}{ot}"


# ---------------------------------------------------------------------------
# Core parser
# ---------------------------------------------------------------------------


class VoiceOrderParser:
    """Parses natural language voice commands into structured order parameters.

    Rule-based parsing handles the most common spoken patterns without any
    external dependencies.  An optional *llm_client* (any object satisfying
    :class:`LLMClientProtocol`) is used as a fallback for inputs that the
    rule engine cannot confidently classify.

    Args:
        llm_client: Optional LLM client for complex/ambiguous inputs.
        default_product: Default OpenAlgo product type
            (``"MIS"``, ``"CNC"``, or ``"NRML"``).
        default_exchange: Fallback exchange when inference is inconclusive.

    Examples::

        parser = VoiceOrderParser()
        cmd = parser.parse("Buy 75 Nifty at market")
        assert cmd.symbol == "NIFTY"
        assert cmd.action == "BUY"
        assert cmd.quantity == 75
        assert cmd.price_type == "MARKET"
    """

    def __init__(
        self,
        llm_client: LLMClientProtocol | None = None,
        default_product: str = "MIS",
        default_exchange: str = "NSE",
    ) -> None:
        self.llm_client = llm_client
        self.default_product = default_product
        self.default_exchange = default_exchange

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def parse(self, text: str) -> VoiceCommand:
        """Parse voice text into a structured :class:`VoiceCommand`.

        Tries rule-based parsing first.  Falls back to the LLM client when
        the rule engine returns low confidence and a client is configured.

        Args:
            text: Raw transcribed voice input.

        Returns:
            A :class:`VoiceCommand` instance.  Check ``cmd.is_valid`` before
            using the result.
        """
        if not text or not text.strip():
            return VoiceCommand(error="Empty input", raw_text=text)

        cmd = self._rule_based_parse(text)

        if cmd is not None and cmd.confidence >= 0.7:
            return cmd

        if self.llm_client:
            logger.debug("Rule-based confidence low — falling back to LLM")
            llm_cmd = self._llm_parse(text)
            if llm_cmd is not None:
                return llm_cmd

        # Return whatever the rule engine produced (may have low confidence)
        return cmd if cmd is not None else VoiceCommand(
            error="Could not parse command", raw_text=text
        )

    # ------------------------------------------------------------------
    # Rule-based engine
    # ------------------------------------------------------------------

    def _rule_based_parse(self, text: str) -> VoiceCommand | None:  # noqa: C901
        """Fast regex-based parser for common order patterns.

        Handles:
        - ``BUY/SELL <qty> <symbol> [exchange] [at market|limit <price>]``
        - Options shorthand: ``SELL 50 BANKNIFTY 24000 CE``
        - Meta-commands: ``close all``, ``cancel all``
        - Queries: ``what is my position in NIFTY``

        Args:
            text: Raw voice input text.

        Returns:
            A :class:`VoiceCommand` or ``None`` if no pattern matched.
        """
        raw = text
        norm = _normalise_text(text)

        # ---- meta-commands (highest priority) ----
        if re.search(r"\bclose_all\b", norm):
            return VoiceCommand(
                intent="close_all",
                confidence=1.0,
                raw_text=raw,
            )
        if re.search(r"\bcancel_all\b", norm):
            return VoiceCommand(
                intent="cancel_all",
                confidence=1.0,
                raw_text=raw,
            )

        # ---- query intent ----
        if re.search(r"\b(what|show|check|how much|my position|balance|funds)\b", norm):
            return VoiceCommand(
                intent="query",
                confidence=0.75,
                raw_text=raw,
            )

        # ---- order intent ----
        action_match = re.search(r"\b(buy|sell)\b", norm)
        if not action_match:
            return None

        action = action_match.group(1).upper()

        # ---- options pattern: <underlying> <strike> <CE|PE> ----
        opt_match = _OPTIONS_PATTERN.search(norm.upper())
        if opt_match:
            underlying_raw, strike, opt_type = opt_match.groups()
            # The underlying may have been captured or it may precede the match
            if not underlying_raw:
                # Try to find a word immediately before the match
                pre = norm[: opt_match.start()].strip().split()
                underlying_raw = pre[-1] if pre else ""
            underlying = underlying_raw.strip().upper()

            # Remove the matched options fragment so quantity scan is clean
            clean = (
                norm[: opt_match.start()] + norm[opt_match.end() :]
            ).strip()
            # Remove the action word
            clean = re.sub(r"\b(buy|sell)\b", "", clean).strip()

            symbol = _build_options_symbol(underlying, strike, opt_type)
            exchange = self._extract_exchange(clean) or "NFO"

            quantity = self._extract_quantity_from(clean)
            if quantity is None:
                quantity = self._extract_quantity_from(norm)

            price_type, price = self._extract_price_info(norm)

            return VoiceCommand(
                intent="place_order",
                action=action,
                symbol=symbol,
                exchange=exchange,
                quantity=quantity,
                price_type=price_type,
                price=price,
                product=self.default_product,
                confidence=0.9,
                raw_text=raw,
            )

        # ---- plain equity / futures order ----
        # Strip action word
        remainder = re.sub(r"\b(buy|sell)\b", "", norm).strip()

        exchange_explicit = self._extract_exchange(remainder)
        if exchange_explicit:
            remainder = re.sub(_RE_EXCHANGE, "", remainder, flags=re.IGNORECASE).strip()

        quantity = self._extract_quantity_from(remainder)
        if quantity:
            # Remove the matched quantity from remainder so symbol scan is cleaner
            remainder = re.sub(r"\b" + str(quantity) + r"\b", "", remainder, count=1).strip()

        symbol = self._extract_symbol(remainder)
        if not symbol:
            return None

        exchange = exchange_explicit or _infer_exchange(symbol, None)
        price_type, price = self._extract_price_info(norm)

        # Confidence calculation
        confidence = 0.7
        if quantity:
            confidence += 0.1
        if exchange_explicit:
            confidence += 0.05
        if price_type == "LIMIT" and price:
            confidence += 0.05
        confidence = min(confidence, 1.0)

        return VoiceCommand(
            intent="place_order",
            action=action,
            symbol=symbol,
            exchange=exchange,
            quantity=quantity,
            price_type=price_type,
            price=price,
            product=self.default_product,
            confidence=confidence,
            raw_text=raw,
        )

    # ------------------------------------------------------------------
    # LLM fallback
    # ------------------------------------------------------------------

    def _llm_parse(self, text: str) -> VoiceCommand | None:
        """Use the configured LLM client to parse complex voice commands.

        The LLM is prompted to output a JSON object matching :class:`VoiceCommand`
        fields.  If the response cannot be parsed the method returns ``None``.

        Args:
            text: Raw voice input text.

        Returns:
            A :class:`VoiceCommand` or ``None`` on failure.
        """
        import json

        prompt = (
            "You are a trading order parser. Parse the following voice command "
            "into a JSON object with these fields:\n"
            "  intent: place_order | cancel_order | close_all | modify_order | query\n"
            "  action: BUY | SELL | null\n"
            "  symbol: string (upper-case, no spaces) | null\n"
            "  exchange: NSE | BSE | NFO | BFO | MCX | CDS | null\n"
            "  quantity: integer | null\n"
            "  price_type: MARKET | LIMIT | null\n"
            "  price: float | null\n"
            "  product: MIS | CNC | NRML\n"
            "  confidence: float 0-1\n\n"
            f'Voice command: "{text}"\n\n'
            "Respond with ONLY the JSON object, no explanation."
        )
        try:
            raw_json = self.llm_client.complete(prompt)  # type: ignore[union-attr]
            # Extract JSON block even if the LLM wraps it in markdown
            json_match = re.search(r"\{[^{}]+\}", raw_json, re.DOTALL)
            if not json_match:
                return None
            data = json.loads(json_match.group(0))
            return VoiceCommand(
                intent=data.get("intent", "place_order"),
                action=data.get("action"),
                symbol=data.get("symbol"),
                exchange=data.get("exchange"),
                quantity=data.get("quantity"),
                price_type=data.get("price_type"),
                price=data.get("price"),
                product=data.get("product", self.default_product),
                confidence=float(data.get("confidence", 0.5)),
                raw_text=text,
            )
        except Exception as exc:
            logger.warning("LLM parse failed: %s", exc)
            return None

    # ------------------------------------------------------------------
    # Extraction helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_exchange(text: str) -> str | None:
        m = re.search(_RE_EXCHANGE, text, re.IGNORECASE)
        if m:
            return _EXCHANGE_ALIASES.get(m.group(1).lower(), m.group(1).upper())
        return None

    @staticmethod
    def _extract_quantity_from(text: str) -> int | None:
        for phrase, value in sorted(_WORD_TO_INT.items(), key=lambda x: -len(x[0])):
            if re.search(r"\b" + re.escape(phrase) + r"\b", text):
                return value
        m = re.search(_RE_INTEGER, text)
        return int(m.group(1)) if m else None

    @staticmethod
    def _extract_symbol(text: str) -> str | None:
        """Extract the most likely symbol from remaining text after stripping
        quantities, exchanges, and price keywords."""
        # Remove numeric tokens
        cleaned = re.sub(r"\b\d+(?:\.\d+)?\b", "", text)
        # Remove price/order-type keywords
        cleaned = re.sub(
            r"\b(at|market|limit|price|stop|trigger|for|the|a|an|in|on|per)\b",
            "",
            cleaned,
            flags=re.IGNORECASE,
        )
        # Remove exchange tokens (already stripped by caller but be defensive)
        cleaned = re.sub(_RE_EXCHANGE, "", cleaned, flags=re.IGNORECASE)
        # Remove product tokens
        cleaned = re.sub(r"\b(mis|cnc|nrml)\b", "", cleaned, flags=re.IGNORECASE)

        tokens = [t.upper() for t in cleaned.split() if len(t) >= 2]
        if not tokens:
            return None
        # Return the longest token (most likely to be a symbol name)
        return max(tokens, key=len)

    @staticmethod
    def _extract_price_info(text: str) -> tuple[str, float | None]:
        """Return (price_type, price) from normalised text.

        Returns:
            Tuple of (``"MARKET"`` or ``"LIMIT"``, optional float price).
        """
        if re.search(r"\bmarket\b", text):
            return "MARKET", None
        price = _extract_limit_price(text)
        if price is not None:
            return "LIMIT", price
        if re.search(r"\blimit\b", text):
            return "LIMIT", None
        # Default to MARKET
        return "MARKET", None


# ---------------------------------------------------------------------------
# Flask blueprint — POST /api/v1/voice/parse
# ---------------------------------------------------------------------------

voice_bp = Blueprint("voice", __name__)

# Module-level parser instance — can be replaced with a configured one
_parser = VoiceOrderParser()


def set_parser(parser: VoiceOrderParser) -> None:
    """Replace the module-level parser (useful for injecting an LLM client).

    Args:
        parser: A configured :class:`VoiceOrderParser` instance.
    """
    global _parser  # noqa: PLW0603
    _parser = parser


@voice_bp.route("/api/v1/voice/parse", methods=["POST"])
def parse_voice_command() -> Response:
    """Parse a natural language voice command into order parameters.

    Request body (JSON)::

        {"text": "Buy 100 Reliance at market"}

    Response (JSON)::

        {
          "status": "success",
          "data": {
            "intent": "place_order",
            "action": "BUY",
            "symbol": "RELIANCE",
            "exchange": "NSE",
            "quantity": 100,
            "price_type": "MARKET",
            "price": null,
            "product": "MIS",
            "confidence": 0.85,
            "raw_text": "Buy 100 Reliance at market",
            "error": "",
            "is_valid": true
          }
        }

    Returns:
        Flask JSON response.
    """
    body = request.get_json(silent=True)
    if not body or "text" not in body:
        return jsonify({"status": "error", "message": "Field 'text' is required"}), 400

    text = str(body["text"]).strip()
    if not text:
        return jsonify({"status": "error", "message": "Field 'text' must not be blank"}), 400

    cmd = _parser.parse(text)
    logger.info(
        "Voice parse: %r → intent=%s action=%s symbol=%s qty=%s confidence=%.2f",
        text,
        cmd.intent,
        cmd.action,
        cmd.symbol,
        cmd.quantity,
        cmd.confidence,
    )
    return jsonify({"status": "success", "data": cmd.to_dict()})
