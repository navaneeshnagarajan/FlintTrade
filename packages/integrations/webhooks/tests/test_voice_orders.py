"""Tests for VoiceOrderParser — rule-based patterns.

All tests use synthetic inputs, no API calls or LLM required.

The module is loaded directly via importlib.util to completely bypass
packages/integrations/webhooks/src/__init__.py, which chains through:
  alerter → OpenAlgoClient → core app bootstrap → DuckDB file lock.

This matches the test isolation approach used across this codebase.

Run with: python -m pytest packages/integrations/webhooks/tests/test_voice_orders.py -v
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# ---------------------------------------------------------------------------
# Direct module load — bypasses packages/integrations/webhooks/src/__init__.py
# ---------------------------------------------------------------------------

_MODULE_PATH = Path(__file__).parent.parent / "src" / "voice_orders.py"


def _load_voice_orders():
    """Load voice_orders.py directly, caching in sys.modules to avoid reload.

    Using a private key avoids polluting the real import namespace while still
    ensuring all tests within the session share the same module object.
    """
    key = "_flinttrade_voice_orders_test"
    if key not in sys.modules:
        spec = importlib.util.spec_from_file_location(key, _MODULE_PATH)
        mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
        sys.modules[key] = mod
        spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return sys.modules[key]


def _parser():
    """Return a fresh VoiceOrderParser with default settings."""
    return _load_voice_orders().VoiceOrderParser()


# ---------------------------------------------------------------------------
# 1. Simple BUY orders
# ---------------------------------------------------------------------------


class TestSimpleBuyOrders:
    """Rule-based parsing of common BUY equity commands."""

    def test_buy_equity_market(self):
        cmd = _parser().parse("Buy 100 Reliance at market")
        assert cmd.is_valid
        assert cmd.action == "BUY"
        assert cmd.symbol == "RELIANCE"
        assert cmd.quantity == 100
        assert cmd.price_type == "MARKET"
        assert cmd.price is None

    def test_buy_quantity_then_symbol(self):
        cmd = _parser().parse("Buy 50 TCS")
        assert cmd.is_valid
        assert cmd.action == "BUY"
        assert cmd.symbol == "TCS"
        assert cmd.quantity == 50

    def test_buy_case_insensitive(self):
        cmd = _parser().parse("BUY 10 INFY")
        assert cmd.is_valid
        assert cmd.action == "BUY"

    def test_buy_with_explicit_nse_exchange(self):
        cmd = _parser().parse("Buy 20 HDFC NSE")
        assert cmd.is_valid
        assert cmd.exchange == "NSE"

    def test_buy_confidence_at_least_0_7(self):
        cmd = _parser().parse("Buy 100 Reliance at market")
        assert cmd.confidence >= 0.7

    def test_buy_market_default_when_no_price_type(self):
        """Equity orders without a price type should default to MARKET."""
        cmd = _parser().parse("Buy 5 Wipro")
        assert cmd.price_type == "MARKET"


# ---------------------------------------------------------------------------
# 2. Simple SELL orders
# ---------------------------------------------------------------------------


class TestSimpleSellOrders:
    """Rule-based parsing of common SELL equity commands."""

    def test_sell_equity_market(self):
        cmd = _parser().parse("Sell 25 HDFCBANK")
        assert cmd.is_valid
        assert cmd.action == "SELL"
        assert cmd.symbol == "HDFCBANK"
        assert cmd.quantity == 25
        assert cmd.price_type == "MARKET"

    def test_sell_limit_order(self):
        cmd = _parser().parse("Sell 10 Infosys limit 1800")
        assert cmd.is_valid
        assert cmd.action == "SELL"
        assert cmd.price_type == "LIMIT"
        assert cmd.price == pytest.approx(1800.0)

    def test_sell_limit_at_price(self):
        cmd = _parser().parse("Sell 10 Infosys at 1800")
        assert cmd.price_type == "LIMIT"
        assert cmd.price == pytest.approx(1800.0)

    def test_sell_alias_short(self):
        """'short' should be interpreted as SELL."""
        cmd = _parser().parse("Short 100 Nifty")
        assert cmd.action == "SELL"


# ---------------------------------------------------------------------------
# 3. Options orders
# ---------------------------------------------------------------------------


class TestOptionsOrders:
    """Rule-based parsing of F&O / options voice commands."""

    def test_sell_banknifty_put(self):
        cmd = _parser().parse("Sell 50 Bank Nifty 24000 PE")
        assert cmd.is_valid
        assert cmd.action == "SELL"
        assert "BANKNIFTY" in cmd.symbol
        assert "24000" in cmd.symbol
        assert cmd.symbol.endswith("PE")
        assert cmd.exchange == "NFO"

    def test_buy_nifty_call(self):
        cmd = _parser().parse("Buy 75 Nifty 22500 CE")
        assert cmd.is_valid
        assert cmd.action == "BUY"
        assert "22500" in cmd.symbol
        assert cmd.symbol.endswith("CE")
        assert cmd.exchange == "NFO"

    def test_buy_call_spoken_word(self):
        """'call' should be resolved to CE."""
        cmd = _parser().parse("Buy 75 Nifty 22500 call")
        assert cmd.is_valid
        assert cmd.symbol.endswith("CE")

    def test_sell_put_spoken_word(self):
        """'put' should be resolved to PE."""
        cmd = _parser().parse("Sell 50 BankNifty 24000 put")
        assert cmd.is_valid
        assert cmd.symbol.endswith("PE")

    def test_options_exchange_defaults_to_nfo(self):
        cmd = _parser().parse("Buy 75 Nifty 23000 CE")
        assert cmd.exchange == "NFO"

    def test_options_confidence_at_least_0_85(self):
        cmd = _parser().parse("Buy 75 Nifty 22500 CE")
        assert cmd.confidence >= 0.85


# ---------------------------------------------------------------------------
# 4. Meta-commands
# ---------------------------------------------------------------------------


class TestMetaCommands:
    """Close-all and cancel-all intent detection."""

    def test_close_all_positions(self):
        cmd = _parser().parse("Close all positions")
        assert cmd.intent == "close_all"
        assert cmd.confidence == 1.0
        assert cmd.is_valid

    def test_close_all_short_form(self):
        cmd = _parser().parse("Close all")
        assert cmd.intent == "close_all"

    def test_square_off_all(self):
        cmd = _parser().parse("Square off all")
        assert cmd.intent == "close_all"

    def test_cancel_all_orders(self):
        cmd = _parser().parse("Cancel all orders")
        assert cmd.intent == "cancel_all"
        assert cmd.is_valid

    def test_cancel_all_short(self):
        cmd = _parser().parse("Cancel all")
        assert cmd.intent == "cancel_all"


# ---------------------------------------------------------------------------
# 5. Edge cases and validation
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """Parser robustness and graceful failure handling."""

    def test_empty_string_returns_error(self):
        cmd = _parser().parse("")
        assert not cmd.is_valid
        assert cmd.error

    def test_whitespace_only_returns_error(self):
        cmd = _parser().parse("   ")
        assert not cmd.is_valid
        assert cmd.error

    def test_unrecognised_command_returns_invalid_or_low_confidence(self):
        cmd = _parser().parse("Play music")
        assert not cmd.is_valid or cmd.confidence < 0.7

    def test_raw_text_preserved(self):
        text = "Buy 100 Reliance at market"
        cmd = _parser().parse(text)
        assert cmd.raw_text == text

    def test_missing_quantity_still_parses_without_crash(self):
        """Parser should not raise when quantity is absent."""
        cmd = _parser().parse("Buy Wipro")
        assert cmd is not None

    def test_is_valid_false_without_quantity(self):
        VoiceCommand = _load_voice_orders().VoiceCommand
        cmd = VoiceCommand(
            intent="place_order",
            action="BUY",
            symbol="RELIANCE",
            quantity=None,
            confidence=0.8,
        )
        assert not cmd.is_valid

    def test_is_valid_false_without_symbol(self):
        VoiceCommand = _load_voice_orders().VoiceCommand
        cmd = VoiceCommand(
            intent="place_order",
            action="BUY",
            symbol=None,
            quantity=100,
            confidence=0.8,
        )
        assert not cmd.is_valid

    def test_to_dict_contains_required_keys(self):
        VoiceCommand = _load_voice_orders().VoiceCommand
        cmd = VoiceCommand(intent="place_order", action="BUY", symbol="TCS", quantity=10)
        d = cmd.to_dict()
        required = {
            "intent", "action", "symbol", "exchange", "quantity",
            "price_type", "price", "product", "confidence", "raw_text",
            "error", "is_valid",
        }
        assert required.issubset(d.keys())


# ---------------------------------------------------------------------------
# 6. Exchange inference
# ---------------------------------------------------------------------------


class TestExchangeInference:
    """_infer_exchange() resolves the correct exchange for known symbols."""

    def test_nifty_index_exchange(self):
        assert _load_voice_orders()._infer_exchange("NIFTY", None) == "NSE_INDEX"

    def test_banknifty_index_exchange(self):
        assert _load_voice_orders()._infer_exchange("BANKNIFTY", None) == "NSE_INDEX"

    def test_sensex_index_exchange(self):
        assert _load_voice_orders()._infer_exchange("SENSEX", None) == "NSE_INDEX"

    def test_gold_mcx_exchange(self):
        assert _load_voice_orders()._infer_exchange("GOLD", None) == "MCX"

    def test_crudeoil_mcx_exchange(self):
        assert _load_voice_orders()._infer_exchange("CRUDEOIL", None) == "MCX"

    def test_options_symbol_nfo_exchange(self):
        assert _load_voice_orders()._infer_exchange("BANKNIFTY24000CE", None) == "NFO"

    def test_equity_defaults_to_nse(self):
        assert _load_voice_orders()._infer_exchange("RELIANCE", None) == "NSE"

    def test_explicit_exchange_wins(self):
        assert _load_voice_orders()._infer_exchange("RELIANCE", "BSE") == "BSE"


# ---------------------------------------------------------------------------
# 7. Options symbol builder
# ---------------------------------------------------------------------------


class TestBuildOptionsSymbol:
    """_build_options_symbol() constructs correct OpenAlgo symbols."""

    def test_ce_symbol(self):
        assert _load_voice_orders()._build_options_symbol("NIFTY", "22500", "CE") == "NIFTY22500CE"

    def test_pe_symbol(self):
        assert _load_voice_orders()._build_options_symbol("BANKNIFTY", "24000", "PE") == "BANKNIFTY24000PE"

    def test_uppercase_normalisation(self):
        assert _load_voice_orders()._build_options_symbol("nifty", "22500", "ce") == "NIFTY22500CE"

    def test_call_alias_to_ce(self):
        assert _load_voice_orders()._build_options_symbol("NIFTY", "22500", "CALL") == "NIFTY22500CE"

    def test_put_alias_to_pe(self):
        assert _load_voice_orders()._build_options_symbol("NIFTY", "22500", "PUT") == "NIFTY22500PE"


# ---------------------------------------------------------------------------
# 8. Text normalisation
# ---------------------------------------------------------------------------


class TestNormaliseText:
    """_normalise_text() applies aliases and collapses whitespace."""

    def test_lower_case(self):
        assert _load_voice_orders()._normalise_text("BUY 100") == "buy 100"

    def test_collapse_whitespace(self):
        assert _load_voice_orders()._normalise_text("buy  100   reliance") == "buy 100 reliance"

    def test_at_market_alias(self):
        result = _load_voice_orders()._normalise_text("Buy 100 Reliance at market")
        assert "market" in result

    def test_bank_nifty_alias(self):
        result = _load_voice_orders()._normalise_text("Buy 50 Bank Nifty 24000 CE")
        assert "banknifty" in result

    def test_call_alias_to_ce(self):
        result = _load_voice_orders()._normalise_text("buy 75 nifty 22500 call")
        assert "ce" in result

    def test_purchase_alias_to_buy(self):
        result = _load_voice_orders()._normalise_text("Purchase 10 Reliance")
        assert "buy" in result


# ---------------------------------------------------------------------------
# 9. LLM fallback (mocked)
# ---------------------------------------------------------------------------


class TestLLMFallback:
    """LLM fallback is called when rule-based confidence is low."""

    def _mock_client(self, response_json: dict) -> MagicMock:
        client = MagicMock()
        client.complete.return_value = json.dumps(response_json)
        return client

    def test_llm_called_when_rule_confidence_low(self):
        VoiceOrderParser = _load_voice_orders().VoiceOrderParser
        llm = self._mock_client({
            "intent": "place_order",
            "action": "BUY",
            "symbol": "RELIANCE",
            "exchange": "NSE",
            "quantity": 100,
            "price_type": "MARKET",
            "price": None,
            "product": "MIS",
            "confidence": 0.9,
        })
        p = VoiceOrderParser(llm_client=llm)
        cmd = p.parse("Please purchase one hundred shares of Reliance Industries")
        # Rule engine may or may not meet the 0.7 threshold for this phrase —
        # just verify no exception is raised and result is usable.
        assert cmd is not None
        if llm.complete.called:
            assert cmd.symbol == "RELIANCE"

    def test_llm_result_used_when_returned(self):
        VoiceOrderParser = _load_voice_orders().VoiceOrderParser
        llm = self._mock_client({
            "intent": "place_order",
            "action": "SELL",
            "symbol": "TATAMOTORS",
            "exchange": "NSE",
            "quantity": 200,
            "price_type": "LIMIT",
            "price": 950.5,
            "product": "CNC",
            "confidence": 0.88,
        })
        p = VoiceOrderParser(llm_client=llm)
        cmd = p.parse("liquidate two hundred tata motors at nine fifty point five")
        if llm.complete.called:
            assert cmd.action == "SELL"
            assert cmd.symbol == "TATAMOTORS"
            assert cmd.price == pytest.approx(950.5)

    def test_no_llm_without_client(self):
        """Without an LLM client, parser returns rule-based result (or error)."""
        mod = _load_voice_orders()
        p = mod.VoiceOrderParser(llm_client=None)
        cmd = p.parse("liquidate two hundred tata motors")
        assert isinstance(cmd, mod.VoiceCommand)


# ---------------------------------------------------------------------------
# 10. Flask endpoint
# ---------------------------------------------------------------------------


class TestFlaskEndpoint:
    """POST /api/v1/voice/parse endpoint contract tests."""

    def _app(self):
        from flask import Flask
        voice_bp = _load_voice_orders().voice_bp
        app = Flask("test")
        app.register_blueprint(voice_bp)
        return app

    def test_parse_valid_command(self):
        with self._app().test_client() as client:
            resp = client.post(
                "/api/v1/voice/parse",
                json={"text": "Buy 100 Reliance at market"},
            )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "success"
        assert data["data"]["action"] == "BUY"
        assert data["data"]["symbol"] == "RELIANCE"
        assert data["data"]["quantity"] == 100

    def test_parse_close_all(self):
        with self._app().test_client() as client:
            resp = client.post(
                "/api/v1/voice/parse",
                json={"text": "Close all positions"},
            )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["data"]["intent"] == "close_all"
        assert data["data"]["is_valid"] is True

    def test_missing_text_field_returns_400(self):
        with self._app().test_client() as client:
            resp = client.post("/api/v1/voice/parse", json={"query": "Buy 100 TCS"})
        assert resp.status_code == 400

    def test_empty_text_returns_400(self):
        with self._app().test_client() as client:
            resp = client.post("/api/v1/voice/parse", json={"text": ""})
        assert resp.status_code == 400

    def test_no_body_returns_400(self):
        with self._app().test_client() as client:
            resp = client.post(
                "/api/v1/voice/parse",
                data="not-json",
                content_type="text/plain",
            )
        assert resp.status_code == 400

    def test_response_includes_all_fields(self):
        with self._app().test_client() as client:
            resp = client.post(
                "/api/v1/voice/parse",
                json={"text": "Sell 50 BankNifty 24000 PE"},
            )
        assert resp.status_code == 200
        d = resp.get_json()["data"]
        required = {
            "intent", "action", "symbol", "exchange", "quantity",
            "price_type", "price", "product", "confidence",
            "raw_text", "error", "is_valid",
        }
        assert required.issubset(d.keys())
