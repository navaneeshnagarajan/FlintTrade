"""Extended tests for TradingView webhook parser — payloads, signal extraction, webhook class.

All tests are purely in-process. No HTTP calls made.
"""

from __future__ import annotations

import hashlib
import hmac
import json



# ---------------------------------------------------------------------------
# TradingViewAlert dataclass
# ---------------------------------------------------------------------------


class TestTradingViewAlertDataclass:
    def test_default_values(self):
        from packages.integration.src.tradingview import TradingViewAlert
        a = TradingViewAlert()
        assert a.action == ""
        assert a.exchange == "NSE"
        assert a.quantity == "1"
        assert a.pricetype == "MARKET"
        assert a.product == "MIS"
        assert a.strategy == "Flint"
        assert not a.is_valid
        assert a.error == ""

    def test_valid_alert_fields(self):
        from packages.integration.src.tradingview import TradingViewAlert
        a = TradingViewAlert(
            action="BUY", symbol="RELIANCE", exchange="NSE",
            quantity="10", price="2500", pricetype="LIMIT",
            product="CNC", strategy="MyStrat",
            is_valid=True,
        )
        assert a.is_valid
        assert a.action == "BUY"
        assert a.symbol == "RELIANCE"


# ---------------------------------------------------------------------------
# parse_tradingview_payload — JSON paths
# ---------------------------------------------------------------------------


class TestParseJsonPayload:
    def test_all_fields_explicit(self):
        from packages.integration.src.tradingview import parse_tradingview_payload
        payload = json.dumps({
            "action": "SELL",
            "symbol": "TCS",
            "exchange": "BSE",
            "quantity": "20",
            "price": "3500",
            "pricetype": "LIMIT",
            "product": "CNC",
            "strategy": "BreakoutStrat",
        })
        a = parse_tradingview_payload(payload)
        assert a.is_valid
        assert a.action == "SELL"
        assert a.symbol == "TCS"
        assert a.exchange == "BSE"
        assert a.quantity == "20"
        assert a.price == "3500"
        assert a.pricetype == "LIMIT"
        assert a.product == "CNC"
        assert a.strategy == "BreakoutStrat"

    def test_lowercase_action_normalised(self):
        from packages.integration.src.tradingview import parse_tradingview_payload
        a = parse_tradingview_payload(json.dumps({"action": "sell", "symbol": "infy"}))
        assert a.action == "SELL"
        assert a.symbol == "INFY"

    def test_invalid_pricetype_falls_back_to_market(self):
        from packages.integration.src.tradingview import parse_tradingview_payload
        a = parse_tradingview_payload(json.dumps({
            "action": "BUY", "symbol": "RELIANCE", "pricetype": "GARBAGE",
        }))
        assert a.is_valid
        assert a.pricetype == "MARKET"

    def test_invalid_product_falls_back_to_mis(self):
        from packages.integration.src.tradingview import parse_tradingview_payload
        a = parse_tradingview_payload(json.dumps({
            "action": "BUY", "symbol": "RELIANCE", "product": "JUNK",
        }))
        assert a.is_valid
        assert a.product == "MIS"

    def test_trigger_price_field(self):
        from packages.integration.src.tradingview import parse_tradingview_payload
        a = parse_tradingview_payload(json.dumps({
            "action": "BUY", "symbol": "NIFTY",
            "pricetype": "SL", "price": "24000", "trigger_price": "23990",
        }))
        assert a.trigger_price == "23990"

    def test_empty_json_object(self):
        from packages.integration.src.tradingview import parse_tradingview_payload
        a = parse_tradingview_payload("{}")
        assert not a.is_valid
        assert "action" in a.error.lower()

    def test_non_dict_json_fails(self):
        from packages.integration.src.tradingview import parse_tradingview_payload
        a = parse_tradingview_payload("[1,2,3]")
        # Array doesn't start with '{', so parsed as text → also invalid
        assert not a.is_valid

    def test_strategy_defaults_to_flint(self):
        from packages.integration.src.tradingview import parse_tradingview_payload
        a = parse_tradingview_payload(json.dumps({"action": "BUY", "symbol": "X"}))
        assert a.strategy == "Flint"

    def test_custom_default_strategy(self):
        from packages.integration.src.tradingview import parse_tradingview_payload
        a = parse_tradingview_payload(
            json.dumps({"action": "BUY", "symbol": "X"}),
            default_strategy="CustomBot",
        )
        assert a.strategy == "CustomBot"

    def test_strategy_in_payload_overrides_default(self):
        from packages.integration.src.tradingview import parse_tradingview_payload
        a = parse_tradingview_payload(
            json.dumps({"action": "BUY", "symbol": "X", "strategy": "TVBot"}),
            default_strategy="CustomBot",
        )
        assert a.strategy == "TVBot"


# ---------------------------------------------------------------------------
# parse_tradingview_payload — text format
# ---------------------------------------------------------------------------


class TestParseTextPayload:
    def test_minimal_action_symbol(self):
        from packages.integration.src.tradingview import parse_tradingview_payload
        a = parse_tradingview_payload("SELL HDFC")
        assert a.is_valid
        assert a.action == "SELL"
        assert a.symbol == "HDFC"
        assert a.exchange == "NSE"  # default

    def test_exchange_nfo(self):
        from packages.integration.src.tradingview import parse_tradingview_payload
        a = parse_tradingview_payload("BUY BANKNIFTY NFO 30")
        assert a.exchange == "NFO"
        assert a.quantity == "30"

    def test_exchange_mcx(self):
        from packages.integration.src.tradingview import parse_tradingview_payload
        a = parse_tradingview_payload("BUY CRUDEOIL MCX 100")
        assert a.exchange == "MCX"

    def test_limit_order_with_price(self):
        from packages.integration.src.tradingview import parse_tradingview_payload
        a = parse_tradingview_payload("BUY NIFTY NSE 50 LIMIT 24500")
        assert a.pricetype == "LIMIT"
        assert a.price == "24500"

    def test_sl_order_pricetype(self):
        from packages.integration.src.tradingview import parse_tradingview_payload
        a = parse_tradingview_payload("SELL RELIANCE NSE 10 SL 2400")
        assert a.pricetype == "SL"
        assert a.price == "2400"

    def test_no_exchange_no_qty_defaults(self):
        from packages.integration.src.tradingview import parse_tradingview_payload
        a = parse_tradingview_payload("BUY INFY")
        assert a.exchange == "NSE"
        assert a.quantity == "1"
        assert a.pricetype == "MARKET"

    def test_bytes_input(self):
        from packages.integration.src.tradingview import parse_tradingview_payload
        a = parse_tradingview_payload(b"SELL TCS NSE 5")
        assert a.is_valid
        assert a.action == "SELL"
        assert a.symbol == "TCS"

    def test_only_one_word_invalid(self):
        from packages.integration.src.tradingview import parse_tradingview_payload
        a = parse_tradingview_payload("BUY")
        assert not a.is_valid

    def test_invalid_action_hold_fails(self):
        from packages.integration.src.tradingview import parse_tradingview_payload
        a = parse_tradingview_payload("HOLD RELIANCE")
        assert not a.is_valid
        assert "HOLD" in a.error

    def test_cds_exchange_recognised(self):
        from packages.integration.src.tradingview import parse_tradingview_payload
        a = parse_tradingview_payload("BUY USDINR CDS 1")
        assert a.exchange == "CDS"


# ---------------------------------------------------------------------------
# alert_to_order
# ---------------------------------------------------------------------------


class TestAlertToOrder:
    def test_order_maps_all_fields(self):
        from packages.integration.src.tradingview import TradingViewAlert, alert_to_order
        alert = TradingViewAlert(
            action="BUY", symbol="RELIANCE", exchange="NSE",
            quantity="10", price="2500", trigger_price="0",
            pricetype="LIMIT", product="CNC", strategy="S",
            is_valid=True,
        )
        order = alert_to_order(alert)
        assert order is not None
        assert order.symbol == "RELIANCE"
        assert order.action == "BUY"
        assert order.exchange == "NSE"
        assert order.quantity == "10"
        assert order.pricetype == "LIMIT"
        assert order.product == "CNC"
        assert order.strategy == "S"

    def test_invalid_alert_returns_none(self):
        from packages.integration.src.tradingview import TradingViewAlert, alert_to_order
        a = TradingViewAlert(is_valid=False, error="bad")
        assert alert_to_order(a) is None

    def test_order_from_text_alert(self):
        from packages.integration.src.tradingview import alert_to_order, parse_tradingview_payload
        alert = parse_tradingview_payload("BUY NIFTY NFO 75")
        order = alert_to_order(alert)
        assert order is not None
        assert order.symbol == "NIFTY"
        assert order.exchange == "NFO"
        assert order.quantity == "75"


# ---------------------------------------------------------------------------
# verify_webhook_signature
# ---------------------------------------------------------------------------


class TestVerifyWebhookSignature:
    def test_correct_hmac_accepted(self):
        from packages.integration.src.tradingview import verify_webhook_signature
        body = b'{"action":"BUY","symbol":"NIFTY"}'
        secret = "supersecret"
        sig = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        assert verify_webhook_signature(body, sig, secret)

    def test_tampered_body_rejected(self):
        from packages.integration.src.tradingview import verify_webhook_signature
        body = b'{"action":"BUY","symbol":"NIFTY"}'
        secret = "supersecret"
        sig = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        tampered = b'{"action":"SELL","symbol":"NIFTY"}'
        assert not verify_webhook_signature(tampered, sig, secret)

    def test_wrong_secret_rejected(self):
        from packages.integration.src.tradingview import verify_webhook_signature
        body = b"data"
        sig = hmac.new(b"correct", body, hashlib.sha256).hexdigest()
        assert not verify_webhook_signature(body, sig, "wrong")

    def test_empty_secret_skips_validation(self):
        from packages.integration.src.tradingview import verify_webhook_signature
        assert verify_webhook_signature(b"anything", "any_sig", "")

    def test_empty_signature_with_secret_rejected(self):
        """Fail-closed: when a secret is configured, a missing signature rejects."""
        from packages.integration.src.tradingview import verify_webhook_signature
        assert not verify_webhook_signature(b"anything", "", "secret")


# ---------------------------------------------------------------------------
# TradingViewWebhook class
# ---------------------------------------------------------------------------


class TestTradingViewWebhookClass:
    def test_default_strategy_applied(self):
        from packages.integration.src.tradingview import TradingViewWebhook
        tv = TradingViewWebhook(default_strategy="PinescriptBot")
        alert = tv.handle("BUY NIFTY")
        assert alert.strategy == "PinescriptBot"

    def test_to_order_returns_order(self):
        from packages.integration.src.tradingview import TradingViewWebhook
        tv = TradingViewWebhook()
        alert = tv.handle(json.dumps({"action": "BUY", "symbol": "RELIANCE"}))
        order = tv.to_order(alert)
        assert order is not None

    def test_to_order_invalid_alert_returns_none(self):
        from packages.integration.src.tradingview import TradingViewWebhook
        tv = TradingViewWebhook()
        alert = tv.handle("")
        order = tv.to_order(alert)
        assert order is None

    def test_handle_string_body(self):
        from packages.integration.src.tradingview import TradingViewWebhook
        tv = TradingViewWebhook()
        alert = tv.handle('{"action":"SELL","symbol":"TCS"}')
        assert alert.is_valid

    def test_handle_bytes_body(self):
        from packages.integration.src.tradingview import TradingViewWebhook
        tv = TradingViewWebhook()
        alert = tv.handle(b"BUY INFY NSE 10")
        assert alert.is_valid

    def test_handle_with_valid_signature(self):
        from packages.integration.src.tradingview import TradingViewWebhook
        body = b'{"action":"BUY","symbol":"NIFTY"}'
        secret = "abc123"
        sig = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        tv = TradingViewWebhook(secret=secret)
        alert = tv.handle(body, signature=sig)
        assert alert.is_valid

    def test_handle_with_invalid_signature(self):
        from packages.integration.src.tradingview import TradingViewWebhook
        tv = TradingViewWebhook(secret="correct")
        alert = tv.handle(b'{"action":"BUY","symbol":"NIFTY"}', signature="badsig")
        assert not alert.is_valid
        assert "signature" in alert.error.lower()

    def test_no_signature_and_no_secret_passes(self):
        from packages.integration.src.tradingview import TradingViewWebhook
        tv = TradingViewWebhook(secret="")
        alert = tv.handle('{"action":"BUY","symbol":"X"}', signature="anything")
        assert alert.is_valid

    def test_handle_empty_payload(self):
        from packages.integration.src.tradingview import TradingViewWebhook
        tv = TradingViewWebhook()
        alert = tv.handle("")
        assert not alert.is_valid
        assert "Empty" in alert.error

    def test_nfo_exchange_preserved(self):
        from packages.integration.src.tradingview import TradingViewWebhook
        tv = TradingViewWebhook()
        alert = tv.handle(json.dumps({
            "action": "BUY", "symbol": "NIFTY", "exchange": "NFO", "quantity": "75",
        }))
        assert alert.exchange == "NFO"
        assert alert.quantity == "75"


# ---------------------------------------------------------------------------
# Valid constants
# ---------------------------------------------------------------------------


class TestValidConstants:
    def test_valid_exchanges_include_nfo_mcx(self):
        from packages.integration.src.tradingview import _VALID_EXCHANGES
        assert "NFO" in _VALID_EXCHANGES
        assert "MCX" in _VALID_EXCHANGES
        assert "NSE" in _VALID_EXCHANGES
        assert "BSE" in _VALID_EXCHANGES

    def test_valid_products(self):
        from packages.integration.src.tradingview import _VALID_PRODUCTS
        assert "MIS" in _VALID_PRODUCTS
        assert "CNC" in _VALID_PRODUCTS
        assert "NRML" in _VALID_PRODUCTS

    def test_valid_pricetypes(self):
        from packages.integration.src.tradingview import _VALID_PRICETYPES
        assert "MARKET" in _VALID_PRICETYPES
        assert "LIMIT" in _VALID_PRICETYPES
        assert "SL" in _VALID_PRICETYPES
        assert "SL-M" in _VALID_PRICETYPES

    def test_valid_actions(self):
        from packages.integration.src.tradingview import _VALID_ACTIONS
        assert "BUY" in _VALID_ACTIONS
        assert "SELL" in _VALID_ACTIONS
        assert len(_VALID_ACTIONS) == 2  # only BUY and SELL
