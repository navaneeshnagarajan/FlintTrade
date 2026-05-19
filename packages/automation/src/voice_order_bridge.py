"""Voice Order Bridge — natural language to order placement.

Parses free-text or transcribed voice commands into structured trading intents
using the existing LLM client, then executes them through the order router.

Examples::

    bridge = VoiceOrderBridge(llm_client, order_router, position_tracker)
    intent = bridge.parse("buy 100 reliance at market")
    result = await bridge.execute(intent, confirm=False)

High-risk actions (CANCEL ALL, EXIT, large quantity) require explicit approval
via the /admin/action-center before execution when ``confirm=True``.

Whisper transcription is optional — if ``openai-whisper`` is not installed,
``transcribe_audio`` raises ``TranscribeUnavailableError``.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Literal

logger = logging.getLogger("flinttrade.automation.voice_order_bridge")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_HIGH_RISK_ACTIONS: frozenset[str] = frozenset({"CANCEL", "EXIT"})
_HIGH_RISK_QUANTITY_THRESHOLD = 500

_EXCHANGE_ALIASES: dict[str, str] = {
    "nse": "NSE",
    "bse": "BSE",
    "nfo": "NFO",
    "bfo": "BFO",
    "mcx": "MCX",
    "cds": "CDS",
    "bcd": "BCD",
    "ncdex": "NCDEX",
}

# LLM system prompt — instructs model to return strict JSON only.
_SYSTEM_PROMPT = """You are a trading assistant that extracts structured order intents from natural language.

IMPORTANT RULES:
1. Always respond with valid JSON only. No prose, no markdown, no explanation.
2. Use the exact schema defined below.
3. If you cannot extract a required field with high confidence, set it to null.
4. For symbols, return the stock ticker (e.g., "RELIANCE", "TCS", "NIFTY").
5. Infer exchange from context: equity → NSE, futures/options → NFO, commodity → MCX.
6. If the command is ambiguous or unsafe, add a warning message.

OUTPUT SCHEMA:
{
  "action": "BUY" | "SELL" | "CANCEL" | "MODIFY" | "STATUS" | "EXIT",
  "symbol": string | null,
  "exchange": "NSE" | "BSE" | "NFO" | "BFO" | "MCX" | "CDS" | "BCD" | "NCDEX" | null,
  "quantity": integer | null,
  "order_type": "MARKET" | "LIMIT" | null,
  "price": number | null,
  "confidence": float between 0.0 and 1.0,
  "warnings": [string]
}

EXAMPLES:
Input: "buy 100 reliance at market"
Output: {"action":"BUY","symbol":"RELIANCE","exchange":"NSE","quantity":100,"order_type":"MARKET","price":null,"confidence":0.95,"warnings":[]}

Input: "sell 50 shares of TCS at 3850 limit"
Output: {"action":"SELL","symbol":"TCS","exchange":"NSE","quantity":50,"order_type":"LIMIT","price":3850.0,"confidence":0.97,"warnings":[]}

Input: "cancel my last order"
Output: {"action":"CANCEL","symbol":null,"exchange":null,"quantity":null,"order_type":null,"price":null,"confidence":0.80,"warnings":["No specific order ID mentioned — will cancel most recent open order"]}

Input: "show my positions"
Output: {"action":"STATUS","symbol":null,"exchange":null,"quantity":null,"order_type":null,"price":null,"confidence":0.99,"warnings":[]}

Input: "exit all nifty"
Output: {"action":"EXIT","symbol":"NIFTY","exchange":"NFO","quantity":null,"order_type":"MARKET","price":null,"confidence":0.85,"warnings":["EXIT will close all open positions for this symbol"]}
"""

_USER_PROMPT_TEMPLATE = 'Parse this trading command and return JSON only:\n"{text}"'


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class VoiceOrderError(Exception):
    """Base exception for voice order bridge errors."""


class ParseError(VoiceOrderError):
    """Raised when the LLM returns unparseable output."""


class LowConfidenceError(VoiceOrderError):
    """Raised when parsed intent confidence is below the safety threshold."""


class TranscribeUnavailableError(VoiceOrderError):
    """Raised when Whisper is not installed and transcription is requested."""


class PendingApprovalError(VoiceOrderError):
    """Raised when a high-risk action requires confirmation before execution."""

    def __init__(self, intent: "VoiceOrderIntent") -> None:
        self.intent = intent
        super().__init__(
            f"High-risk action '{intent.action}' requires approval via /admin/action-center"
        )


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class VoiceOrderIntent:
    """Parsed intent from a voice or text command.

    Attributes:
        action: Trading action to perform.
        symbol: Instrument ticker symbol (e.g., "RELIANCE", "NIFTY").
        exchange: Exchange code (e.g., "NSE", "NFO").
        quantity: Number of shares/lots. None means not specified.
        order_type: MARKET or LIMIT. None means not specified.
        price: Limit price. Only relevant when order_type is LIMIT.
        confidence: LLM confidence score from 0.0 to 1.0.
        raw_text: Original input text before parsing.
        warnings: Non-fatal issues identified during parsing.
    """

    action: Literal["BUY", "SELL", "CANCEL", "MODIFY", "STATUS", "EXIT"]
    symbol: str | None
    exchange: str | None
    quantity: int | None
    order_type: Literal["MARKET", "LIMIT"] | None
    price: float | None
    confidence: float
    raw_text: str
    warnings: list[str] = field(default_factory=list)

    @property
    def is_high_risk(self) -> bool:
        """Return True if this intent requires human confirmation."""
        if self.action in _HIGH_RISK_ACTIONS:
            return True
        if self.quantity is not None and self.quantity >= _HIGH_RISK_QUANTITY_THRESHOLD:
            return True
        return False

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a plain dict suitable for JSON responses."""
        return {
            "action": self.action,
            "symbol": self.symbol,
            "exchange": self.exchange,
            "quantity": self.quantity,
            "order_type": self.order_type,
            "price": self.price,
            "confidence": self.confidence,
            "raw_text": self.raw_text,
            "warnings": self.warnings,
            "is_high_risk": self.is_high_risk,
        }


# ---------------------------------------------------------------------------
# Bridge
# ---------------------------------------------------------------------------


class VoiceOrderBridge:
    """Parse natural language trading commands and execute with confirmation.

    Wraps the existing :class:`~packages.ai.src.llm_client.LLMClient` for intent
    parsing and delegates order execution to the provided order router.

    Args:
        llm_client: An initialised ``LLMClient`` instance.
        order_router: Object with a ``place_order(intent)`` method.
        position_tracker: Object with a ``get_positions()`` method.
        min_confidence: Minimum LLM confidence required to execute (default 0.7).

    Example::

        bridge = VoiceOrderBridge(llm_client, order_router, position_tracker)
        intent = bridge.parse("buy 50 INFY at market")
        result = await bridge.execute(intent, confirm=False)
    """

    def __init__(
        self,
        llm_client: Any,
        order_router: Any,
        position_tracker: Any,
        min_confidence: float = 0.70,
    ) -> None:
        self._llm = llm_client
        self._router = order_router
        self._tracker = position_tracker
        self._min_confidence = min_confidence

    # ------------------------------------------------------------------
    # Parsing
    # ------------------------------------------------------------------

    def parse(self, text: str) -> VoiceOrderIntent:
        """Parse a free-text trading command into a structured intent.

        Uses the LLM with a strict JSON response format. Falls back to a
        regex-based parser if the LLM is unavailable or returns invalid JSON.

        Args:
            text: Raw trading command (typed or transcribed).

        Returns:
            A :class:`VoiceOrderIntent` with extracted fields.

        Raises:
            ParseError: If neither the LLM nor the fallback parser can extract
                a valid intent from the input.
        """
        text = text.strip()
        if not text:
            raise ParseError("Input text is empty")

        try:
            return self._parse_with_llm(text)
        except Exception as exc:
            logger.warning("LLM parse failed (%s), trying regex fallback", exc)

        try:
            return self._parse_with_regex(text)
        except Exception as exc2:
            raise ParseError(f"Both LLM and regex parsers failed: {exc2}") from exc2

    def _parse_with_llm(self, text: str) -> VoiceOrderIntent:
        """Invoke the LLM client and deserialise the JSON response."""
        from packages.ai.src.llm_client import LLMMessage

        messages = [
            LLMMessage(role="system", content=_SYSTEM_PROMPT),
            LLMMessage(role="user", content=_USER_PROMPT_TEMPLATE.format(text=text)),
        ]

        # Request JSON output when provider supports response_format
        response = self._llm.chat(
            messages,
            temperature=0.0,
            max_tokens=256,
        )

        if not response.success:
            raise ParseError(f"LLM returned error: {response.error}")

        raw_content = response.content.strip()

        # Strip markdown code fences if present
        raw_content = re.sub(r"^```(?:json)?\s*", "", raw_content, flags=re.MULTILINE)
        raw_content = re.sub(r"\s*```$", "", raw_content, flags=re.MULTILINE)
        raw_content = raw_content.strip()

        try:
            data = json.loads(raw_content)
        except json.JSONDecodeError as exc:
            raise ParseError(f"LLM returned non-JSON: {raw_content[:200]}") from exc

        return self._dict_to_intent(data, raw_text=text)

    def _parse_with_regex(self, text: str) -> VoiceOrderIntent:
        """Simple regex fallback parser for common BUY/SELL patterns.

        Handles patterns like:
        - "buy 100 reliance"
        - "sell 50 TCS at 3850"
        - "buy 25 nifty 22000 call"

        Args:
            text: Raw command text.

        Returns:
            A best-effort :class:`VoiceOrderIntent`.
        """
        upper = text.upper().strip()
        warnings: list[str] = ["Parsed via regex fallback — LLM unavailable"]

        # Detect action
        action: Literal["BUY", "SELL", "CANCEL", "MODIFY", "STATUS", "EXIT"]
        if re.search(r"\bBUY\b", upper):
            action = "BUY"
        elif re.search(r"\bSELL\b", upper):
            action = "SELL"
        elif re.search(r"\bCANCEL\b", upper):
            action = "CANCEL"
        elif re.search(r"\bEXIT\b", upper):
            action = "EXIT"
        elif re.search(r"\bSTATUS\b|\bPOSITIONS?\b|\bPNL\b|\bSHOW\b|\bWATCH\b", upper):
            action = "STATUS"
        elif re.search(r"\bMODIFY\b|\bCHANGE\b", upper):
            action = "MODIFY"
        else:
            raise ParseError(f"Cannot detect action in: {text!r}")

        # Detect quantity — first standalone integer
        quantity: int | None = None
        qty_match = re.search(r"\b(\d{1,6})\b", upper)
        if qty_match:
            quantity = int(qty_match.group(1))

        # Detect price after "AT" keyword
        price: float | None = None
        order_type: Literal["MARKET", "LIMIT"] | None = None
        price_match = re.search(r"\bAT\s+(\d+(?:\.\d+)?)\b", upper)
        if price_match:
            price = float(price_match.group(1))
            order_type = "LIMIT"
        elif re.search(r"\bMARKET\b", upper):
            order_type = "MARKET"

        # Detect symbol — capitalised word after quantity or action
        symbol: str | None = None
        sym_match = re.search(
            r"\b(?:BUY|SELL|EXIT)\s+(?:\d+\s+)?(?:SHARES?\s+OF\s+)?([A-Z]{2,20})\b",
            upper,
        )
        if sym_match:
            symbol = sym_match.group(1)

        # Detect exchange
        exchange: str | None = None
        for alias, code in _EXCHANGE_ALIASES.items():
            if re.search(rf"\b{alias.upper()}\b", upper):
                exchange = code
                break
        if exchange is None and symbol is not None:
            # Default equity assumption
            exchange = "NSE"

        return VoiceOrderIntent(
            action=action,
            symbol=symbol,
            exchange=exchange,
            quantity=quantity,
            order_type=order_type,
            price=price,
            confidence=0.55,
            raw_text=text,
            warnings=warnings,
        )

    @staticmethod
    def _dict_to_intent(data: dict[str, Any], raw_text: str) -> VoiceOrderIntent:
        """Convert a parsed JSON dict to a VoiceOrderIntent.

        Args:
            data: Dictionary from LLM JSON output.
            raw_text: Original input text.

        Returns:
            Validated :class:`VoiceOrderIntent`.

        Raises:
            ParseError: If the ``action`` field is missing or invalid.
        """
        valid_actions = {"BUY", "SELL", "CANCEL", "MODIFY", "STATUS", "EXIT"}
        action_raw = str(data.get("action", "")).upper()
        if action_raw not in valid_actions:
            raise ParseError(f"Invalid action in LLM response: {action_raw!r}")

        action: Literal["BUY", "SELL", "CANCEL", "MODIFY", "STATUS", "EXIT"] = action_raw  # type: ignore[assignment]

        # Validate order_type
        order_type_raw = str(data.get("order_type") or "").upper() or None
        order_type: Literal["MARKET", "LIMIT"] | None
        if order_type_raw in ("MARKET", "LIMIT"):
            order_type = order_type_raw  # type: ignore[assignment]
        else:
            order_type = None

        # Clamp confidence to [0.0, 1.0]
        try:
            confidence = float(data.get("confidence", 0.5))
        except (TypeError, ValueError):
            confidence = 0.5
        confidence = max(0.0, min(1.0, confidence))

        # Normalise exchange
        exchange_raw = str(data.get("exchange") or "").upper() or None
        exchange = exchange_raw if exchange_raw in _EXCHANGE_ALIASES.values() else exchange_raw

        # Normalise quantity
        qty_raw = data.get("quantity")
        try:
            quantity: int | None = int(qty_raw) if qty_raw is not None else None
        except (TypeError, ValueError):
            quantity = None

        # Normalise price
        price_raw = data.get("price")
        try:
            price: float | None = float(price_raw) if price_raw is not None else None
        except (TypeError, ValueError):
            price = None

        warnings: list[str] = list(data.get("warnings") or [])

        return VoiceOrderIntent(
            action=action,
            symbol=str(data["symbol"]).upper() if data.get("symbol") else None,
            exchange=exchange,
            quantity=quantity,
            order_type=order_type,
            price=price,
            confidence=confidence,
            raw_text=raw_text,
            warnings=warnings,
        )

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    async def execute(
        self,
        intent: VoiceOrderIntent,
        confirm: bool = True,
    ) -> dict[str, Any]:
        """Execute a parsed intent, optionally requiring approval.

        For high-risk actions (CANCEL, EXIT, large quantities), if ``confirm``
        is ``True``, this method raises :class:`PendingApprovalError` instead
        of executing immediately. The caller should surface this to the UI for
        explicit approval.

        Args:
            intent: Parsed :class:`VoiceOrderIntent` from :meth:`parse`.
            confirm: When True and the action is high-risk, require approval.

        Returns:
            A dict with ``status``, ``action``, and ``data`` keys.

        Raises:
            LowConfidenceError: When confidence is below ``min_confidence``.
            PendingApprovalError: When a high-risk action needs confirmation.
            VoiceOrderError: On execution failure.
        """
        if intent.confidence < self._min_confidence:
            raise LowConfidenceError(
                f"Confidence {intent.confidence:.2f} below threshold "
                f"{self._min_confidence:.2f} — please rephrase the command"
            )

        if confirm and intent.is_high_risk:
            raise PendingApprovalError(intent)

        try:
            if intent.action == "STATUS":
                return await self._handle_status(intent)
            elif intent.action in ("BUY", "SELL"):
                return await self._handle_order(intent)
            elif intent.action == "CANCEL":
                return await self._handle_cancel(intent)
            elif intent.action == "EXIT":
                return await self._handle_exit(intent)
            elif intent.action == "MODIFY":
                return await self._handle_modify(intent)
            else:
                return {"status": "error", "message": f"Unsupported action: {intent.action}"}
        except (PendingApprovalError, LowConfidenceError):
            raise
        except Exception as exc:
            logger.error("Execution failed for intent %s: %s", intent.action, exc)
            raise VoiceOrderError(f"Execution failed: {exc}") from exc

    async def _handle_order(self, intent: VoiceOrderIntent) -> dict[str, Any]:
        """Place a BUY or SELL market/limit order.

        Args:
            intent: Validated intent with action BUY or SELL.

        Returns:
            Execution result dict.
        """
        if not intent.symbol:
            return {"status": "error", "message": "Symbol is required for BUY/SELL orders"}
        if not intent.quantity:
            return {"status": "error", "message": "Quantity is required for BUY/SELL orders"}

        order_params: dict[str, Any] = {
            "action": intent.action,
            "symbol": intent.symbol,
            "exchange": intent.exchange or "NSE",
            "quantity": intent.quantity,
            "price_type": intent.order_type or "MARKET",
            "strategy": "VoiceOrder",
        }
        if intent.order_type == "LIMIT" and intent.price is not None:
            order_params["price"] = intent.price

        result = await self._router.place_order(order_params)
        logger.info(
            "Voice order placed: %s %d %s — result: %s",
            intent.action, intent.quantity, intent.symbol, result,
        )
        return {"status": "success", "action": intent.action, "data": result}

    async def _handle_cancel(self, intent: VoiceOrderIntent) -> dict[str, Any]:
        """Cancel the most recent open order (or order by symbol if provided).

        Args:
            intent: Validated intent with action CANCEL.

        Returns:
            Execution result dict.
        """
        result = await self._router.cancel_last_order(symbol=intent.symbol)
        return {"status": "success", "action": "CANCEL", "data": result}

    async def _handle_exit(self, intent: VoiceOrderIntent) -> dict[str, Any]:
        """Close all open positions for the given symbol (or all symbols).

        Args:
            intent: Validated intent with action EXIT.

        Returns:
            Execution result dict.
        """
        result = await self._router.close_position(symbol=intent.symbol)
        return {"status": "success", "action": "EXIT", "data": result}

    async def _handle_status(self, intent: VoiceOrderIntent) -> dict[str, Any]:
        """Return current positions, optionally filtered by symbol.

        Args:
            intent: Validated intent with action STATUS.

        Returns:
            Position data dict.
        """
        positions = await self._tracker.get_positions()
        if intent.symbol:
            positions = [
                p for p in positions
                if str(p.get("symbol", "")).upper() == intent.symbol.upper()
            ]
        return {"status": "success", "action": "STATUS", "data": positions}

    async def _handle_modify(self, intent: VoiceOrderIntent) -> dict[str, Any]:
        """Modify the most recent pending order (price or quantity).

        Args:
            intent: Validated intent with action MODIFY.

        Returns:
            Execution result dict.
        """
        modify_params: dict[str, Any] = {}
        if intent.price is not None:
            modify_params["price"] = intent.price
        if intent.quantity is not None:
            modify_params["quantity"] = intent.quantity

        result = await self._router.modify_last_order(
            symbol=intent.symbol, **modify_params
        )
        return {"status": "success", "action": "MODIFY", "data": result}

    # ------------------------------------------------------------------
    # Audio transcription
    # ------------------------------------------------------------------

    def transcribe_audio(self, audio_bytes: bytes, language: str = "en") -> str:
        """Transcribe raw audio bytes to text using Whisper.

        Whisper is optional — if the ``openai-whisper`` package is not installed,
        this method raises :class:`TranscribeUnavailableError` with instructions.

        Args:
            audio_bytes: Raw audio file content (wav, mp3, webm, flac, ogg).
            language: ISO-639-1 language code (default ``"en"``).

        Returns:
            Transcribed text string.

        Raises:
            TranscribeUnavailableError: When Whisper is not installed.
            VoiceOrderError: When transcription fails for any other reason.
        """
        try:
            import whisper  # type: ignore[import-untyped]
        except ImportError as exc:
            raise TranscribeUnavailableError(
                "openai-whisper is not installed. "
                "Run: pip install openai-whisper"
            ) from exc

        import tempfile
        import os

        # Whisper requires a file path — write bytes to a temp file
        try:
            suffix = ".wav"
            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
                tmp.write(audio_bytes)
                tmp_path = tmp.name

            try:
                model = whisper.load_model("base")
                result = model.transcribe(tmp_path, language=language)
                text: str = result.get("text", "").strip()
                logger.info("Whisper transcription: %r", text)
                return text
            finally:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
        except TranscribeUnavailableError:
            raise
        except Exception as exc:
            raise VoiceOrderError(f"Transcription failed: {exc}") from exc
